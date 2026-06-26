from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import json, uuid, datetime, os
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = "demo-secret"
STORAGE_FILE = os.path.join(os.path.dirname(__file__), "storage.json")

load_dotenv()
USERNAME         = os.getenv("PORTAL_USERNAME")
PASSWORD         = os.getenv("PORTAL_PASSWORD")
MOCK_CREDENTIALS = {"username": USERNAME, "password": PASSWORD}

# ── helpers ──────────────────────────────────────────────────────────────────

def load_records():
    with open(STORAGE_FILE) as f:
        return json.load(f)

def save_records(records):
    with open(STORAGE_FILE, "w") as f:
        json.dump(records, f, indent=2)

# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if (request.form["username"] == MOCK_CREDENTIALS["username"] and
                request.form["password"] == MOCK_CREDENTIALS["password"]):
            session["user"] = request.form["username"]
            return redirect(url_for("submit_pa"))
        error = "Invalid credentials. Please try again."
    return render_template("login.html", error=error)

@app.route("/submit", methods=["GET", "POST"])
def submit_pa():
    if "user" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        record = {
            "id": str(uuid.uuid4())[:8].upper(),
            "submitted_at": datetime.datetime.now().isoformat(),
            "status": "Pending",
            "patient_name": request.form["patient_name"],
            "dob": request.form["dob"],
            "diagnosis_code": request.form["diagnosis_code"],
            "cpt_code": request.form["cpt_code"],
            "provider_npi": request.form["provider_npi"],
            "requested_units": request.form["requested_units"],
            "notes": request.form.get("notes", ""),
            "payer": request.form["payer"],
        }
        records = load_records()
        records.append(record)
        save_records(records)
        return redirect(url_for("status", pa_id=record["id"]))
    return render_template("submit_pa.html")

@app.route("/status")
def status():
    if "user" not in session:
        return redirect(url_for("login"))
    pa_id = request.args.get("pa_id")
    records = load_records()
    record = next((r for r in records if r["id"] == pa_id), None)
    all_records = sorted(records, key=lambda r: r["submitted_at"], reverse=True)
    return render_template("status.html", record=record, all_records=all_records)

@app.route("/api/records")
def api_records():
    """JSON endpoint for the results dashboard."""
    return jsonify(load_records())

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "../dashboard/index.html")
    with open(dashboard_path) as f:
        html = f.read()
    # Patch the fetch path to use the API endpoint instead of a relative file path
    html = html.replace('"../outputs/agent_run.json"', '"/api/agent-run"')
    return html

@app.route("/api/agent-run")
def api_agent_run():
    run_path = os.path.join(os.path.dirname(__file__), "../outputs/agent_run.json")
    with open(run_path) as f:
        return json.load(f)

if __name__ == "__main__":
    app.run(debug=True, port=5050)