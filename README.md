# BloodConnect – Blood Bank Management System

A Flask website that connects to your existing Neo4j AuraDB database. It does **not** seed, wipe, or recreate your database.

## Features
- Dashboard with counts, recent donations and requests, and blood-unit status.
- Browse/add/update/delete records for donors, donations, blood units, blood banks, patients, hospitals, and requests.
- Create the six project relationship types without duplicating existing relationships.
- Query Explorer with ten predefined Cypher queries.
- Export entity tables to CSV.
- Interactive graph view using vis-network.
- Parameterized values for data inputs.

## Run locally (Windows PowerShell)
1. Install Python 3.10 or newer.
2. Extract this ZIP and open PowerShell in the `BloodConnect_Website` folder.
3. Create and activate a virtual environment:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
5. Copy `.env.example` to `.env`, then replace the placeholder URI and password with the credentials from Neo4j AuraDB. Keep `.env private and never upload it to GitHub.
6. Start the website:
   ```powershell
   python app.py
   ```
7. Open http://127.0.0.1:5000

## Important
- Use the same AuraDB instance and database where your existing project data lives.
- The app never creates sample records automatically.
- A delete operation removes the selected node and its connected relationships. The page asks for confirmation first.
- Do not use a publicly exposed deployment with real patient data without adding authentication and access controls.
- Test the graph relationship patterns against your current database. If your existing node property names differ, update `ENTITY_CONFIG` and the relevant queries in `app.py`.
