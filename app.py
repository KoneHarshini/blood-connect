
import os
import csv
import io

from flask import Flask, render_template, request, redirect, url_for, flash, Response
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")

URI = os.getenv("NEO4J_URI", "")
USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

driver = None

if URI and PASSWORD:
    try:
        driver = GraphDatabase.driver(
            URI,
            auth=(USERNAME, PASSWORD)
        )
    except Exception as exc:
        print("Neo4j driver initialization failed:", exc)


def run_query(query, params=None):
    if not driver:
        raise RuntimeError(
            "Neo4j is not configured. Check NEO4J_URI, "
            "NEO4J_USERNAME and NEO4J_PASSWORD in your .env file."
        )

    with driver.session(database=DATABASE) as session:
        return [record.data() for record in session.run(query, params or {})]


def safe_text(value):
    return (value or "").strip()


# --------------------------------------------------
# ENTITY CONFIGURATION
# --------------------------------------------------

ENTITY_CONFIG = {
    "donors": {
        "label": "Donor",
        "title": "Donors",
        "id": "Donor_ID",
        "fields": [
            "Donor_ID", "Name", "Gender", "Age",
            "Blood_Group", "Phone", "Address"
        ]
    },
    "donations": {
        "label": "Donation",
        "title": "Donations",
        "id": "Donation_ID",
        "fields": ["Donation_ID", "Donation_Date"]
    },
    "blood-units": {
        "label": "BloodUnit",
        "title": "Blood Units",
        "id": "Blood_ID",
        "fields": [
            "Blood_ID", "Blood_Group", "Quantity",
            "Collection_Date", "Expiry_Date", "Status",
            "Donation_ID", "Bank_ID"
        ]
    },
    "blood-banks": {
        "label": "BloodBank",
        "title": "Blood Banks",
        "id": "Bank_ID",
        "fields": ["Bank_ID", "Bank_Name", "Location", "Phone"]
    },
    "patients": {
        "label": "Patient",
        "title": "Patients",
        "id": "Patient_ID",
        "fields": [
            "Patient_ID", "Name", "Age",
            "Blood_Group", "Hospital_ID"
        ]
    },
    "hospitals": {
        "label": "Hospital",
        "title": "Hospitals",
        "id": "Hospital_ID",
        "fields": ["Hospital_ID", "Hospital_Name", "Address", "Phone"]
    },
    "requests": {
        "label": "Request",
        "title": "Blood Requests",
        "id": "Request_ID",
        "fields": [
            "Request_ID", "Request_Date", "Quantity",
            "Status", "Patient_ID", "Donation_ID"
        ]
    }
}


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

def count_nodes(label):
    id_fields = {
        "Donor": "Donor_ID",
        "Donation": "Donation_ID",
        "BloodUnit": "Blood_ID",
        "BloodBank": "Bank_ID",
        "Patient": "Patient_ID",
        "Hospital": "Hospital_ID",
        "Request": "Request_ID"
    }

    if label not in id_fields:
        return 0

    id_field = id_fields[label]

    result = run_query(
        f"""
        MATCH (n:{label})
        WHERE n.{id_field} IS NOT NULL
        RETURN count(DISTINCT n.{id_field}) AS count
        """
    )

    return result[0]["count"] if result else 0


@app.route("/")
def dashboard():
    error = None
    stats = {}
    recent_donations = []
    recent_requests = []
    units = []

    try:
        stats = {
            "donors": count_nodes("Donor"),
            "donations": count_nodes("Donation"),
            "units": count_nodes("BloodUnit"),
            "banks": count_nodes("BloodBank"),
            "patients": count_nodes("Patient"),
            "hospitals": count_nodes("Hospital"),
            "requests": count_nodes("Request")
        }

        # One row per Donation_ID.
        recent_donations = run_query("""
            MATCH (d:Donation)
            WHERE d.Donation_ID IS NOT NULL
            WITH d.Donation_ID AS id,
                 collect(d)[0] AS d
            OPTIONAL MATCH (donor:Donor)-[:MADE]->(d)
            WITH id, d.Donation_Date AS date,
                 collect(DISTINCT donor.Name)[0] AS donor
            RETURN id, date, donor
            ORDER BY date DESC
            LIMIT 5
        """)

        # One row per Request_ID, despite duplicate nodes or relationships.
        recent_requests = run_query("""
            MATCH (r:Request)
            WHERE r.Request_ID IS NOT NULL
            WITH r.Request_ID AS id,
                 collect(r)[0] AS r
            OPTIONAL MATCH (p:Patient)-[:MADE_REQUEST]->(r)
            WITH id, r.Request_Date AS date,
                 r.Quantity AS quantity,
                 r.Status AS status,
                 collect(DISTINCT p.Name)[0] AS patient
            RETURN id, patient, quantity, status, date
            ORDER BY date DESC
            LIMIT 5
        """)

        # One row per Blood_ID.
        units = run_query("""
            MATCH (u:BloodUnit)
            WHERE u.Blood_ID IS NOT NULL
            WITH u.Blood_ID AS blood_id,
                 collect(u)[0] AS u
            RETURN blood_id AS id,
                   u.Blood_Group AS `group`,
                   u.Quantity AS quantity,
                   u.Status AS status,
                   u.Expiry_Date AS expiry
            ORDER BY blood_id
            LIMIT 8
        """)

    except Exception as exc:
        error = str(exc)

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_donations=recent_donations,
        recent_requests=recent_requests,
        units=units,
        error=error
    )


# --------------------------------------------------
# ENTITY TABLES
# --------------------------------------------------

def get_entity_rows(key):
    cfg = ENTITY_CONFIG[key]
    fields = cfg["fields"]

    # Select one representative node per business ID.
    projection = ", ".join(
        f"n.{field} AS `{field}`" for field in fields
    )

    query = (
        f"MATCH (original:{cfg['label']}) "
        f"WHERE original.{cfg['id']} IS NOT NULL "
        f"WITH original.{cfg['id']} AS record_id, "
        f"collect(original)[0] AS n "
        f"RETURN {projection} "
        f"ORDER BY record_id"
    )

    return run_query(query)


@app.route("/entity/<key>", methods=["GET", "POST"])
def entity_page(key):
    if key not in ENTITY_CONFIG:
        return redirect(url_for("dashboard"))

    cfg = ENTITY_CONFIG[key]

    if request.method == "POST":
        values = {
            field: safe_text(request.form.get(field))
            for field in cfg["fields"]
        }

        if not values.get(cfg["id"]):
            flash(f'{cfg["id"]} is required.', "error")
            return redirect(url_for("entity_page", key=key))

        numeric_fields = {
            "Age", "Quantity", "Donor_ID", "Donation_ID",
            "Blood_ID", "Bank_ID", "Patient_ID",
            "Hospital_ID", "Request_ID"
        }

        props = {}

        for field, value in values.items():
            if value == "":
                continue

            if field in numeric_fields:
                try:
                    props[field] = int(value)
                except ValueError:
                    flash(f"{field} must be a whole number.", "error")
                    return redirect(url_for("entity_page", key=key))
            else:
                props[field] = value

        label = cfg["label"]
        idfield = cfg["id"]

        try:
            # MERGE prevents creating another node for a new write
            # when a node with this ID already exists.
            run_query(
                f"""
                MERGE (n:{label} {{{idfield}: $id}})
                SET n += $props
                RETURN n
                """,
                {
                    "id": props[idfield],
                    "props": props
                }
            )

            flash("Record saved successfully.", "success")

        except Exception as exc:
            flash(f"Could not save record: {exc}", "error")

        return redirect(url_for("entity_page", key=key))

    try:
        rows = get_entity_rows(key)
        error = None
    except Exception as exc:
        rows = []
        error = str(exc)

    return render_template(
        "entity.html",
        cfg=cfg,
        rows=rows,
        error=error,
        key=key
    )


@app.post("/entity/<key>/delete/<record_id>")
def delete_entity(key, record_id):
    if key not in ENTITY_CONFIG:
        return redirect(url_for("dashboard"))

    cfg = ENTITY_CONFIG[key]

    try:
        run_query(
            f"""
            MATCH (n:{cfg['label']} {{{cfg['id']}: $id}})
            DETACH DELETE n
            """,
            {"id": int(record_id)}
        )

        flash(
            "Matching record nodes and their relationships deleted.",
            "success"
        )

    except Exception as exc:
        flash(f"Could not delete record: {exc}", "error")

    return redirect(url_for("entity_page", key=key))


# --------------------------------------------------
# RELATIONSHIPS
# --------------------------------------------------

@app.route("/relationships", methods=["GET", "POST"])
def relationships():
    rel_types = {
        "MADE": ("Donor", "Donor_ID", "Donation", "Donation_ID"),
        "PRODUCED": ("Donation", "Donation_ID", "BloodUnit", "Blood_ID"),
        "STORED_IN": ("BloodUnit", "Blood_ID", "BloodBank", "Bank_ID"),
        "TREATED_AT": ("Patient", "Patient_ID", "Hospital", "Hospital_ID"),
        "MADE_REQUEST": ("Patient", "Patient_ID", "Request", "Request_ID"),
        "FOR": ("Request", "Request_ID", "Donation", "Donation_ID")
    }

    if request.method == "POST":
        rel = request.form.get("rel_type")

        if rel not in rel_types:
            flash("Choose a valid relationship.", "error")
            return redirect(url_for("relationships"))

        sl, sid, tl, tid = rel_types[rel]

        try:
            s_id = int(request.form.get("source_id", ""))
            t_id = int(request.form.get("target_id", ""))

            result = run_query(
                f"""
                MATCH (s:{sl} {{{sid}: $sid}}),
                      (t:{tl} {{{tid}: $tid}})
                WITH head(collect(s)) AS s,
                     head(collect(t)) AS t
                WHERE s IS NOT NULL AND t IS NOT NULL
                MERGE (s)-[r:{rel}]->(t)
                RETURN count(r) AS total
                """,
                {"sid": s_id, "tid": t_id}
            )

            if result and result[0]["total"]:
                flash(
                    "Relationship saved (or it already existed).",
                    "success"
                )
            else:
                flash(
                    "Could not create relationship: check that both records exist.",
                    "error"
                )

        except Exception as exc:
            flash(f"Could not create relationship: {exc}", "error")

        return redirect(url_for("relationships"))

    rel_rows = []
    error = None

    try:
        rel_rows = run_query("""
            MATCH (a)-[r]->(b)
            WITH labels(a)[0] AS source_type,
                 properties(a) AS source,
                 type(r) AS relationship,
                 labels(b)[0] AS target_type,
                 properties(b) AS target
            WITH source_type, source, relationship, target_type, target
            RETURN DISTINCT source_type, source, relationship,
                            target_type, target
            ORDER BY source_type, relationship
            LIMIT 200
        """)

    except Exception as exc:
        error = str(exc)

    return render_template(
        "relationships.html",
        rel_rows=rel_rows,
        error=error
    )


# --------------------------------------------------
# QUERY EXPLORER
# --------------------------------------------------

@app.route("/query-explorer", methods=["GET", "POST"])
def query_explorer():
    query_names = {
        "bank_donors": "Donors whose blood units are stored in a selected bank",
        "available_group": "Available blood units by exact blood group",
        "hospital_patients": "Patients treated at a selected hospital",
        "patient_requests": "Requests made by a selected patient",
        "bank_units": "Blood units stored in a selected bank",
        "donor_donations": "Donations made by a selected donor",
        "pending": "Pending blood requests",
        "expiry": "Expired or soon-expiring blood units",
        "patient_details": "Selected patient's details",
        "donation_flow": "Donation flow: donor → donation → blood unit → bank"
    }

    query_text = ""
    results = []
    error = None

    chosen = request.form.get("query_name", "pending")
    params = {}

    queries = {
        "bank_donors": (
            """
            MATCH (d:Donor)-[:MADE]->(:Donation)
                  -[:PRODUCED]->(u:BloodUnit)
                  -[:STORED_IN]->(b:BloodBank)
            WHERE b.Bank_ID = $id
            RETURN DISTINCT d.Donor_ID AS donor_id,
                            d.Name AS donor,
                            d.Blood_Group AS blood_group,
                            b.Bank_Name AS bank
            """,
            "id"
        ),
        "available_group": (
            """
            MATCH (u:BloodUnit)
            WHERE u.Status = 'Available'
              AND toUpper(u.Blood_Group) = toUpper($group)
            WITH u.Blood_ID AS id, collect(u)[0] AS u
            RETURN id AS blood_id,
                   u.Blood_Group AS blood_group,
                   u.Quantity AS quantity,
                   u.Expiry_Date AS expiry,
                   u.Status AS status
            ORDER BY blood_id
            """,
            "group"
        ),
        "hospital_patients": (
            """
            MATCH (p:Patient)-[:TREATED_AT]->(h:Hospital)
            WHERE h.Hospital_ID = $id
            RETURN DISTINCT p.Patient_ID AS patient_id,
                            p.Name AS patient,
                            p.Blood_Group AS blood_group,
                            h.Hospital_Name AS hospital
            """,
            "id"
        ),
        "patient_requests": (
            """
            MATCH (p:Patient)-[:MADE_REQUEST]->(r:Request)
            WHERE p.Patient_ID = $id
            WITH r.Request_ID AS id, collect(r)[0] AS r,
                 collect(DISTINCT p.Name)[0] AS patient
            RETURN id AS request_id,
                   r.Request_Date AS date,
                   r.Quantity AS quantity,
                   r.Status AS status,
                   patient
            ORDER BY request_id
            """,
            "id"
        ),
        "bank_units": (
            """
            MATCH (u:BloodUnit)-[:STORED_IN]->(b:BloodBank)
            WHERE b.Bank_ID = $id
            WITH u.Blood_ID AS id, collect(u)[0] AS u,
                 collect(DISTINCT b.Bank_Name)[0] AS bank
            RETURN id AS blood_id,
                   u.Blood_Group AS blood_group,
                   u.Quantity AS quantity,
                   u.Status AS status,
                   bank
            ORDER BY blood_id
            """,
            "id"
        ),
        "donor_donations": (
            """
            MATCH (d:Donor)-[:MADE]->(x:Donation)
            WHERE d.Donor_ID = $id
            WITH x.Donation_ID AS id, collect(x)[0] AS x,
                 collect(DISTINCT d.Name)[0] AS donor
            RETURN id AS donation_id,
                   x.Donation_Date AS date,
                   donor
            ORDER BY donation_id
            """,
            "id"
        ),
        "pending": (
            """
            MATCH (r:Request)
            WHERE toLower(r.Status) = 'pending'
            WITH r.Request_ID AS id, collect(r)[0] AS r
            OPTIONAL MATCH (p:Patient)-[:MADE_REQUEST]->(r)
            RETURN id AS request_id,
                   collect(DISTINCT p.Name)[0] AS patient,
                   r.Quantity AS quantity,
                   r.Request_Date AS date,
                   r.Status AS status
            ORDER BY date
            """,
            None
        ),
        "expiry": (
            """
            MATCH (u:BloodUnit)
            WHERE u.Blood_ID IS NOT NULL
              AND u.Expiry_Date IS NOT NULL
              AND date(toString(u.Expiry_Date))
                  <= date() + duration({days: 30})
            WITH u.Blood_ID AS id, collect(u)[0] AS u
            RETURN id AS blood_id,
                   u.Blood_Group AS blood_group,
                   u.Expiry_Date AS expiry,
                   u.Status AS status
            ORDER BY expiry
            """,
            None
        ),
        "patient_details": (
            """
            MATCH (p:Patient)
            WHERE p.Patient_ID = $id
            WITH p.Patient_ID AS id, collect(p)[0] AS p
            OPTIONAL MATCH (p)-[:TREATED_AT]->(h:Hospital)
            OPTIONAL MATCH (p)-[:MADE_REQUEST]->(r:Request)
            RETURN p AS patient,
                   collect(DISTINCT h.Hospital_Name)[0] AS hospital,
                   collect(DISTINCT r{.*}) AS requests
            """,
            "id"
        ),
        "donation_flow": (
            """
            MATCH (d:Donor)-[:MADE]->(x:Donation)
                  -[:PRODUCED]->(u:BloodUnit)
                  -[:STORED_IN]->(b:BloodBank)
            WITH d, x, u, b
            RETURN DISTINCT d.Name AS donor,
                            x.Donation_ID AS donation_id,
                            u.Blood_ID AS blood_id,
                            u.Blood_Group AS blood_group,
                            b.Bank_Name AS bank
            LIMIT 100
            """,
            None
        )
    }

    if request.method == "POST":
        if chosen not in queries:
            error = "Invalid query selection."
        else:
            cypher, param = queries[chosen]
            query_text = cypher

            if param == "id":
                try:
                    params["id"] = int(request.form.get("id", ""))
                except ValueError:
                    error = "Enter a numeric ID."

            elif param == "group":
                params["group"] = safe_text(request.form.get("group"))
                if not params["group"]:
                    error = "Enter a blood group such as O+."

            if not error:
                try:
                    results = run_query(cypher, params)

                    def clean(value):
                        if hasattr(value, "iso_format"):
                            return value.iso_format()
                        if hasattr(value, "items"):
                            return {
                                k: clean(v) for k, v in value.items()
                            }
                        if isinstance(value, list):
                            return [clean(v) for v in value]
                        return value

                    results = [
                        {k: clean(v) for k, v in row.items()}
                        for row in results
                    ]

                except Exception as exc:
                    error = str(exc)

    return render_template(
        "query_explorer.html",
        query_names=query_names,
        chosen=chosen,
        query_text=query_text,
        results=results,
        error=error
    )


# --------------------------------------------------
# CSV EXPORT
# --------------------------------------------------

@app.route("/export/<key>.csv")
def export_csv(key):
    if key not in ENTITY_CONFIG:
        return redirect(url_for("dashboard"))

    try:
        rows = get_entity_rows(key)
        output = io.StringIO()
        fields = ENTITY_CONFIG[key]["fields"]

        writer = csv.DictWriter(
            output,
            fieldnames=fields,
            extrasaction="ignore"
        )
        writer.writeheader()

        for row in rows:
            writer.writerow({
                k: str(v) if v is not None else ""
                for k, v in row.items()
            })

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition":
                f"attachment; filename={key}.csv"
            }
        )

    except Exception as exc:
        flash(f"Export failed: {exc}", "error")
        return redirect(url_for("entity_page", key=key))


# --------------------------------------------------
# GRAPH VISUALIZATION
# --------------------------------------------------

@app.route("/graph")
def graph():
    nodes = []
    edges = []
    error = None

    try:
        data = run_query("""
            MATCH (a)-[r]->(b)
            RETURN elementId(a) AS source,
                   labels(a)[0] AS source_label,
                   properties(a) AS source_props,
                   elementId(b) AS target,
                   labels(b)[0] AS target_label,
                   properties(b) AS target_props,
                   type(r) AS rel
            LIMIT 300
        """)

        seen = set()
        seen_edges = set()

        for row in data:
            for eid, label, props in [
                (
                    row["source"],
                    row["source_label"],
                    row["source_props"]
                ),
                (
                    row["target"],
                    row["target_label"],
                    row["target_props"]
                )
            ]:
                if eid not in seen:
                    seen.add(eid)

                    title = ", ".join(
                        f"{k}: {v}"
                        for k, v in list(props.items())[:6]
                    )

                    name = (
                        props.get("Name")
                        or props.get("Bank_Name")
                        or props.get("Hospital_Name")
                        or props.get("Blood_Group")
                        or label
                    )

                    nodes.append({
                        "id": eid,
                        "label": f"{label}\n{name}",
                        "title": title,
                        "group": label
                    })

            edge_key = (
                row["source"],
                row["target"],
                row["rel"]
            )

            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append({
                    "from": row["source"],
                    "to": row["target"],
                    "label": row["rel"],
                    "arrows": "to"
                })

    except Exception as exc:
        error = str(exc)

    return render_template(
        "graph.html",
        nodes=nodes,
        edges=edges,
        error=error
    )


# --------------------------------------------------
# ABOUT AND HEALTH CHECK
# --------------------------------------------------

@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/health")
def health():
    try:
        run_query("RETURN 1 AS ok")
        return {"status": "ok", "neo4j": "connected"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}, 503


if __name__ == "__main__":
    app.run(
        debug=True,
        port=int(os.getenv("PORT", "5000"))
    )
