import os
import json
import csv
import io
import base64
import requests
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, make_response
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "counselscope_world_class_crm_2026_secret"
CORS(app)

DATA_FILE = "leads.json"
COLLEGES_FILE = "colleges.json"
HISTORY_FILE = "work_history.json"

# GitHub API Configuration from Environment Variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "") # e.g. "username/repository-name"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

def load_data(filename):
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except:
        return []

def save_data(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)
    
    if GITHUB_TOKEN and GITHUB_REPO and filename in [DATA_FILE, COLLEGES_FILE, HISTORY_FILE]:
        commit_json_to_github(filename)

def log_activity(action_type, details):
    history = load_data(HISTORY_FILE)
    now = datetime.now()
    log_item = {
        "id": len(history) + 1,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%I:%M:%S %p"),
        "action_type": action_type,
        "details": details
    }
    history.append(log_item)
    save_data(HISTORY_FILE, history)

def commit_json_to_github(filepath):
    try:
        with open(filepath, "rb") as f:
            file_content = f.read()
        encoded_content = base64.b64encode(file_content).decode('utf-8')
        
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        
        get_res = requests.get(url, headers=headers)
        sha = get_res.json().get('sha') if get_res.status_code == 200 else None

        payload = {
            "message": f"Auto-update {filepath} data",
            "content": encoded_content,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha

        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        print("GitHub JSON Commit Error:", e)

def upload_file_to_github(file_storage, student_name, original_filename):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return None
    
    try:
        safe_student_name = "".join(c for c in student_name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        
        ext = os.path.splitext(original_filename)[1].lower()
        if not ext:
            ext = ".jpg"
        target_filename = f"aadhar{ext}"
        
        file_path_in_repo = f"student_documents/{safe_student_name}/{target_filename}"
        
        file_content = file_storage.read()
        encoded_content = base64.b64encode(file_content).decode('utf-8')
        
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path_in_repo}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        
        get_res = requests.get(url, headers=headers)
        sha = get_res.json().get('sha') if get_res.status_code == 200 else None

        payload = {
            "message": f"Upload document for student: {student_name}",
            "content": encoded_content,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha

        response = requests.put(url, headers=headers, json=payload)
        if response.status_code in [201, 200]:
            return file_path_in_repo
    except Exception as e:
        print("GitHub API Document Upload Error:", e)
    
    return None

# --- API ENDPOINTS: LEADS ---

@app.route('/api/submit-lead', methods=['POST'])
def submit_lead():
    try:
        data = request.form
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        student_name = data.get('student_name')
        father_name = data.get('father_name', 'N/A')
        contact_number = data.get('contact_number')
        alternate_number = data.get('alternate_number', 'N/A')
        student_email = data.get('student_email')
        state = data.get('state', 'N/A')
        city = data.get('city', 'N/A')
        course_interest = data.get('course_interest', 'General')

        if not student_name or not contact_number or not student_email:
            return jsonify({"status": "error", "message": "Required fields missing"}), 400

        document_filename = None
        if 'id_document' in request.files:
            file = request.files['id_document']
            if file and file.filename != '':
                document_filename = upload_file_to_github(file, student_name, file.filename)

        leads = load_data(DATA_FILE)
        score = 80 if alternate_number != 'N/A' else 50

        new_lead = {
            "id": len(leads) + 1,
            "student_name": student_name,
            "father_name": father_name,
            "contact_number": contact_number,
            "alternate_number": alternate_number,
            "student_email": student_email,
            "state": state,
            "city": city,
            "course_interest": course_interest,
            "id_document": document_filename,
            "status": "New Lead",
            "score": score,
            "notes": "Enquiry received with document saved.",
            "is_deleted": False,
            "created_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
        }
        leads.append(new_lead)
        save_data(DATA_FILE, leads)
        log_activity("New Lead Form", f"New enquiry received for {student_name} ({contact_number})")

        return jsonify({"status": "success", "message": "Lead captured and document securely stored!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/update-lead', methods=['POST'])
def update_lead():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        lead_id = int(request.form.get('lead_id'))
        student_name = request.form.get('student_name')
        father_name = request.form.get('father_name', 'N/A')
        contact_number = request.form.get('contact_number')
        alternate_number = request.form.get('alternate_number', 'N/A')
        student_email = request.form.get('student_email')
        state = request.form.get('state', 'N/A')
        city = request.form.get('city', 'N/A')
        course_interest = request.form.get('course_interest', 'General')
        delete_doc = request.form.get('delete_doc') == 'true'

        leads = load_data(DATA_FILE)
        target_lead = None
        for lead in leads:
            if lead['id'] == lead_id:
                target_lead = lead
                break
        
        if not target_lead:
            return jsonify({"status": "error", "message": "Lead not found"}), 404

        target_lead['student_name'] = student_name
        target_lead['father_name'] = father_name
        target_lead['contact_number'] = contact_number
        target_lead['alternate_number'] = alternate_number
        target_lead['student_email'] = student_email
        target_lead['state'] = state
        target_lead['city'] = city
        target_lead['course_interest'] = course_interest

        if delete_doc:
            target_lead['id_document'] = None

        if 'id_document' in request.files:
            file = request.files['id_document']
            if file and file.filename != '':
                doc_path = upload_file_to_github(file, student_name, file.filename)
                if doc_path:
                    target_lead['id_document'] = doc_path

        save_data(DATA_FILE, leads)
        log_activity("Lead Updated", f"Updated lead information for {student_name}")
        return jsonify({"status": "success", "message": "Lead updated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/get-leads', methods=['GET'])
def get_leads_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(DATA_FILE))


@app.route('/download-doc/<path:filename>', methods=['GET'])
def download_document(filename):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    if GITHUB_REPO:
        raw_github_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{filename}"
        return redirect(raw_github_url)
    
    return "GitHub repository configuration missing.", 400


@app.route('/api/update-status', methods=['POST'])
def update_status():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    lead_id = data.get('lead_id')
    new_status = data.get('status')
    
    leads = load_data(DATA_FILE)
    student_name = ""
    for lead in leads:
        if lead['id'] == lead_id:
            lead['status'] = new_status
            student_name = lead['student_name']
            break
    save_data(DATA_FILE, leads)
    log_activity("Status Change", f"Status changed to '{new_status}' for student {student_name}")
    return jsonify({"status": "success"})


@app.route('/api/delete-lead', methods=['POST'])
def delete_lead():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    lead_id = data.get('lead_id')
    
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == lead_id:
            lead['is_deleted'] = True
            log_activity("Moved to Trash", f"Moved lead #{lead_id} ({lead['student_name']}) to trash")
            break
    save_data(DATA_FILE, leads)
    return jsonify({"status": "success"})


@app.route('/api/restore-lead', methods=['POST'])
def restore_lead():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    lead_id = data.get('lead_id')
    
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == lead_id:
            lead['is_deleted'] = False
            log_activity("Restored Lead", f"Restored lead #{lead_id} ({lead['student_name']}) from trash")
            break
    save_data(DATA_FILE, leads)
    return jsonify({"status": "success"})


@app.route('/api/permanent-delete', methods=['POST'])
def permanent_delete():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    lead_id = data.get('lead_id')
    
    leads = load_data(DATA_FILE)
    leads = [l for l in leads if l['id'] != lead_id]
    save_data(DATA_FILE, leads)
    log_activity("Permanent Delete", f"Permanently deleted lead #{lead_id}")
    return jsonify({"status": "success"})


@app.route('/api/get-history', methods=['GET'])
def get_history_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    date_filter = request.args.get('date')
    history = load_data(HISTORY_FILE)
    if date_filter:
        history = [h for h in history if h.get('date') == date_filter]
    return jsonify(history)


@app.route('/api/log-action', methods=['POST'])
def log_action_route():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    log_activity(data.get('action_type', 'Action'), data.get('details', ''))
    return jsonify({"status": "success"})


@app.route('/api/get-colleges', methods=['GET'])
def get_colleges():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(COLLEGES_FILE))


@app.route('/api/add-college', methods=['POST'])
def add_college():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    colleges = load_data(COLLEGES_FILE)
    new_c = {
        "id": len(colleges) + 1,
        "college_name": data.get('college_name'),
        "location": data.get('location'),
        "courses": data.get('courses'),
        "package": data.get('package', 'N/A')
    }
    colleges.append(new_c)
    save_data(COLLEGES_FILE, colleges)
    log_activity("College Added", f"Added new college tie-up: {data.get('college_name')}")
    return jsonify({"status": "success"})


# --- ROUTING & VIEWS ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('username') == "admin" and request.form.get('password') == "admin123":
            session['logged_in'] = True
            return redirect(url_for('crm_dashboard'))
        else:
            error = "Invalid Username or Password!"
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/dashboard')
def crm_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template_string(MAIN_DASHBOARD_HTML)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
def home():
    return redirect(url_for('login'))


# --- FRONTEND HTML TEMPLATES ---
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CounselScope CRM - Login</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Plus Jakarta Sans', sans-serif; box-sizing: border-box; }
        body { background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 15px; }
        .login-card { background: #1e293b; padding: 40px; border-radius: 20px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); width: 100%; max-width: 380px; border: 1px solid #334155; text-align: center; }
        .logo-img { max-width: 130px; margin-bottom: 20px; border-radius: 8px; }
        h2 { margin-bottom: 8px; color: #38bdf8; font-size: 22px; }
        p.subtitle { color: #94a3b8; font-size: 13px; margin-bottom: 24px; }
        label { text-align: left; display: block; margin-bottom: 6px; font-size: 13px; color: #cbd5e1; font-weight: 500; }
        input { width: 100%; padding: 12px 14px; margin-bottom: 20px; background: #0f172a; border: 1px solid #334155; border-radius: 10px; color: white; font-size: 14px; }
        input:focus { outline: none; border-color: #38bdf8; }
        button { width: 100%; padding: 12px; background: #0284c7; border: none; border-radius: 10px; color: white; font-weight: 600; font-size: 15px; cursor: pointer; transition: 0.2s; }
        button:hover { background: #0369a1; }
        .error { color: #f43f5e; font-size: 13px; margin-bottom: 15px; background: rgba(244,63,94,0.1); padding: 10px; border-radius: 8px; }
    </style>
</head>
<body>
    <div class="login-card">
        <img src="https://i.ibb.co/6R6t2Y0/unnamed.jpg" class="logo-img" alt="CounselScope Logo">
        <h2>CounselScope CRM</h2>
        <p class="subtitle">Enter your credentials to access portal</p>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <label>Username</label>
            <input type="text" name="username" required placeholder="admin">
            <label>Password</label>
            <input type="password" name="password" required placeholder="••••••••">
            <button type="submit">Sign In</button>
        </form>
    </div>
</body>
</html>
"""

MAIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CounselScope - College Lead CRM</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --bg-main: #f4f6f9;
            --sidebar-bg: #0b1329;
            --primary: #2563eb;
            --text-dark: #1e293b;
            --text-muted: #64748b;
            --card-bg: #ffffff;
            --border-color: #e2e8f0;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background-color: var(--bg-main); color: var(--text-dark); display: flex; height: 100vh; overflow: hidden; }

        .sidebar { width: 255px; background-color: var(--sidebar-bg); color: #fff; display: flex; flex-direction: column; padding: 20px 15px; flex-shrink: 0; justify-content: space-between; transition: 0.3s; z-index: 200; }
        .sidebar-brand { display: flex; align-items: center; gap: 12px; padding: 10px 10px 25px 10px; border-bottom: 1px solid rgba(255,255,255,0.08); }
        .sidebar-brand img { width: 38px; height: 38px; border-radius: 8px; }
        .sidebar-brand-text h3 { font-size: 16px; font-weight: 700; color: #fff; }
        .sidebar-brand-text p { font-size: 10px; color: #94a3b8; }
        .nav-menu { margin-top: 20px; display: flex; flex-direction: column; gap: 6px; list-style: none; }
        .nav-item button { width: 100%; display: flex; align-items: center; gap: 12px; padding: 12px 15px; border-radius: 10px; color: #94a3b8; background: none; border: none; font-size: 13.5px; font-weight: 500; cursor: pointer; transition: all 0.2s; text-align: left; }
        .nav-item button:hover, .nav-item.active button { background-color: var(--primary); color: #fff; font-weight: 600; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3); }

        .main-wrapper { flex: 1; display: flex; flex-direction: column; overflow-y: auto; width: 100%; }
        .top-header { background: var(--card-bg); height: 75px; display: flex; align-items: center; justify-content: space-between; padding: 0 25px; border-bottom: 1px solid var(--border-color); position: sticky; top: 0; z-index: 100; gap: 15px; }
        
        .header-left { display: flex; align-items: center; gap: 15px; }
        .menu-toggle-btn { display: none; background: none; border: none; font-size: 20px; color: var(--text-dark); cursor: pointer; }

        .smart-watch { background: #0f172a; color: #38bdf8; padding: 8px 16px; border-radius: 12px; font-weight: 700; font-size: 14px; display: flex; align-items: center; gap: 8px; border: 1px solid #1e293b; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5); }
        .smart-watch i { color: #f59e0b; animation: tick 1s infinite alternate; }
        @keyframes tick { from { opacity: 0.4; } to { opacity: 1; } }

        .search-bar { display: flex; align-items: center; background: #f1f5f9; padding: 10px 16px; border-radius: 20px; width: 300px; gap: 10px; }
        .search-bar input { border: none; background: transparent; outline: none; width: 100%; font-size: 13px; }

        .content-area { padding: 25px; display: flex; flex-direction: column; gap: 25px; }
        .hero-banner { background: linear-gradient(135deg, #0b1329 0%, #1d3557 100%); border-radius: 20px; padding: 30px 35px; color: white; box-shadow: 0 10px 25px rgba(11, 19, 41, 0.15); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 20px; }
        .hero-text h1 { font-size: 24px; font-weight: 800; margin-bottom: 6px; color: #f8fafc; }
        .hero-text p { font-size: 13.5px; color: #94a3b8; max-width: 500px; line-height: 1.5; }

        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 18px; }
        .metric-card { background: var(--card-bg); padding: 20px; border-radius: 16px; border: 1px solid var(--border-color); display: flex; align-items: center; gap: 15px; }
        .m-icon { width: 45px; height: 45px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 18px; }
        .m-icon.blue { background: #eff6ff; color: #2563eb; }
        .m-icon.green { background: #f0fdf4; color: #16a34a; }
        .m-icon.orange { background: #fff7ed; color: #ea580c; }
        .m-icon.purple { background: #faf5ff; color: #9333ea; }
        .m-info h3 { font-size: 22px; font-weight: 800; color: var(--text-dark); }
        .m-info p { font-size: 11.5px; color: var(--text-muted); font-weight: 500; }

        .dashboard-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 25px; }
        .card { background: var(--card-bg); border-radius: 16px; border: 1px solid var(--border-color); padding: 22px; box-shadow: 0 2px 8px rgba(0,0,0,0.02); }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; flex-wrap: wrap; gap: 10px; }
        .card-header h3 { font-size: 15px; font-weight: 700; color: var(--text-dark); }

        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { font-size: 11.5px; font-weight: 600; color: var(--text-muted); padding: 12px 14px; border-bottom: 1px solid var(--border-color); background: #f8fafc; }
        td { font-size: 13px; padding: 13px 14px; border-bottom: 1px solid var(--border-color); color: var(--text-dark); vertical-align: middle; }
        tr:hover td { background-color: #f8fafc; }

        .badge-status { padding: 5px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; display: inline-block; }
        .badge-new { background: #e0f2fe; color: #0369a1; }
        .badge-contacted { background: #fef3c7; color: #b45309; }
        .badge-followup { background: #e0e7ff; color: #4338ca; }
        .badge-closed { background: #dcfce7; color: #15803d; }
        .badge-rejected { background: #fee2e2; color: #b91c1c; }

        select.status-select { padding: 5px 8px; border-radius: 6px; border: 1px solid var(--border-color); font-size: 12px; font-weight: 600; cursor: pointer; }
        .action-icon-btn { width: 32px; height: 32px; border-radius: 8px; display: inline-flex; align-items: center; justify-content: center; text-decoration: none; font-size: 13px; transition: 0.2s; margin-right: 4px; }
        .call-btn { background: #dcfce7; color: #16a34a; }
        .mail-btn { background: #e0f2fe; color: #0284c7; }
        .doc-btn { background: #e0f2fe; color: #0284c7; }
        .doc-btn:hover { background: #0284c7; color: white; }
        .edit-btn { background: #fef3c7; color: #d97706; }
        .edit-btn:hover { background: #d97706; color: white; }
        .trash-btn { background: #fee2e2; color: #dc2626; border: none; cursor: pointer; }

        .chart-container { position: relative; height: 210px; display: flex; justify-content: center; }
        .tab-section { display: none; }
        .tab-section.active { display: block; }

        /* Responsive Animated Modals */
        .modal-overlay { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; backdrop-filter: blur(4px); padding: 15px; }
        .modal-content { background: white; padding: 25px; border-radius: 16px; max-width: 520px; width: 100%; text-align: left; position: relative; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); animation: modalPopup 0.3s cubic-bezier(0.16, 1, 0.3, 1); max-height: 95vh; overflow-y: auto; }
        @keyframes modalPopup { from { transform: scale(0.85); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        .close-modal { position: absolute; top: 15px; right: 20px; font-size: 22px; cursor: pointer; color: #64748b; transition: 0.2s; }
        .close-modal:hover { color: #0f172a; }

        .form-control { width: 100%; padding: 10px 12px; margin-bottom: 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13.5px; }
        .form-control:focus { outline: none; border-color: #2563eb; }

        /* Media Queries for Maximum Responsiveness */
        @media (max-width: 900px) {
            body { flex-direction: column; height: auto; overflow: auto; }
            .sidebar { position: fixed; top: 0; left: -260px; width: 250px; height: 100vh; flex-direction: column; padding: 20px 15px; }
            .sidebar.show { left: 0; }
            .menu-toggle-btn { display: block; }
            .main-wrapper { height: auto; overflow: visible; }
            .dashboard-grid { grid-template-columns: 1fr; }
            .top-header { padding: 0 15px; flex-wrap: wrap; height: auto; padding-top: 10px; padding-bottom: 10px; }
            .search-bar { width: 100%; order: 3; }
            .content-area { padding: 15px; }
            .hero-banner { padding: 20px; }
            .smart-watch { font-size: 12px; padding: 6px 12px; }
        }
    </style>
</head>
<body>

    <aside class="sidebar" id="sidebarNav">
        <div>
            <div class="sidebar-brand">
                <img src="https://i.ibb.co/6R6t2Y0/unnamed.jpg" alt="Logo">
                <div class="sidebar-brand-text">
                    <h3>CounselScope</h3>
                    <p>World-Class CRM</p>
                </div>
            </div>
            <ul class="nav-menu">
                <li class="nav-item active" onclick="switchTab('dashboard-tab', this)"><button><i class="fa-solid fa-chart-pie"></i> Dashboard</button></li>
                <li class="nav-item" onclick="switchTab('leads-tab', this)"><button><i class="fa-solid fa-users"></i> All Leads</button></li>
                <li class="nav-item" onclick="switchTab('colleges-tab', this)"><button><i class="fa-solid fa-building-columns"></i> Colleges Manager</button></li>
                <li class="nav-item" onclick="switchTab('history-tab', this)"><button><i class="fa-solid fa-clock-rotate-left"></i> Work History</button></li>
                <li class="nav-item" onclick="switchTab('trash-tab', this)"><button><i class="fa-solid fa-trash-can"></i> Trash Bin</button></li>
                <li class="nav-item" onclick="switchTab('settings-tab', this)"><button><i class="fa-solid fa-gear"></i> Settings</button></li>
            </ul>
        </div>
        <div style="padding: 10px;">
            <a href="/logout" style="background:#ef4444; color:white; padding:10px; border-radius:8px; display:block; text-align:center; text-decoration:none; font-weight:600; font-size:13px;">Logout</a>
        </div>
    </aside>

    <div class="main-wrapper">
        <header class="top-header">
            <div class="header-left">
                <button class="menu-toggle-btn" onclick="toggleSidebar()"><i class="fa-solid fa-bars"></i></button>
                <div class="smart-watch">
                    <i class="fa-solid fa-clock"></i>
                    <span id="liveWatch">00:00:00 AM</span>
                </div>
            </div>

            <div class="search-bar">
                <i class="fa-solid fa-magnifying-glass"></i>
                <input type="text" id="globalSearch" onkeyup="filterLeadsTable()" placeholder="Search leads...">
            </div>
        </header>

        <div class="content-area">
            <!-- DASHBOARD TAB -->
            <div id="dashboard-tab" class="tab-section active">
                <div class="hero-banner" style="margin-bottom: 25px;">
                    <div class="hero-text">
                        <h1 id="timeGreeting">Good Morning Shivam Sir</h1>
                        <p>Welcome to your CounselScope CRM. Track work history, follow-up recalls, and student admissions in real-time.</p>
                    </div>
                </div>

                <div class="metrics-grid" style="margin-bottom: 25px;">
                    <div class="metric-card"><div class="m-icon blue"><i class="fa-solid fa-users"></i></div><div class="m-info"><h3 id="statTotal">0</h3><p>Total Leads</p></div></div>
                    <div class="metric-card"><div class="m-icon green"><div class="m-icon green"><i class="fa-solid fa-graduation-cap"></i></div></div><div class="m-info"><h3 id="statClosed">0</h3><p>Admissions Closed</p></div></div>
                    <div class="metric-card"><div class="m-icon orange"><i class="fa-solid fa-phone-volume"></i></div><div class="m-info"><h3 id="statContacted">0</h3><p>Contacted</p></div></div>
                    <div class="metric-card"><div class="m-icon purple"><i class="fa-solid fa-spinner"></i></div><div class="m-info"><h3 id="statNew">0</h3><p>New Leads</p></div></div>
                </div>

                <!-- FOLLOW UP RECALL NOTIFICATION CARD -->
                <div class="card" style="margin-bottom: 25px; border-left: 5px solid #6366f1;">
                    <div class="card-header">
                        <h3 style="color: #4338ca;"><i class="fa-solid fa-bell" style="margin-right: 8px;"></i> Immediate Follow-up & Recalls</h3>
                    </div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>Student</th>
                                    <th>Contact</th>
                                    <th>Status</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody id="followupRecallTbody"></tbody>
                        </table>
                    </div>
                </div>

                <!-- WEEKLY, MONTHLY & YEARLY LEADS ANALYTICS -->
                <div class="card" style="margin-bottom: 25px;">
                    <div class="card-header">
                        <h3>Lead Analytics (Weekly, Monthly & Yearly)</h3>
                        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                            <button onclick="showAnalyticsPeriod('week')" id="btnWeek" style="padding: 6px 14px; border-radius: 8px; border: 1px solid #2563eb; background: #2563eb; color: white; font-weight: 600; cursor: pointer; font-size: 12.5px;">This Week (<span id="countWeek">0</span>)</button>
                            <button onclick="showAnalyticsPeriod('month')" id="btnMonth" style="padding: 6px 14px; border-radius: 8px; border: 1px solid #2563eb; background: white; color: #2563eb; font-weight: 600; cursor: pointer; font-size: 12.5px;">This Month (<span id="countMonth">0</span>)</button>
                            <button onclick="showAnalyticsPeriod('year')" id="btnYear" style="padding: 6px 14px; border-radius: 8px; border: 1px solid #2563eb; background: white; color: #2563eb; font-weight: 600; cursor: pointer; font-size: 12.5px;">This Year (<span id="countYear">0</span>)</button>
                        </div>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: center;" class="analytics-grid-mobile">
                        <div>
                            <p id="analyticsDesc" style="color: var(--text-muted); font-size: 13.5px; margin-bottom: 12px; line-height: 1.5;">Click each option above to view lead status distribution and total statistics for the selected time period.</p>
                            <div id="analyticsSummaryText" style="font-weight: 700; color: var(--text-dark); font-size: 14px;"></div>
                        </div>
                        <div class="chart-container" style="height: 200px;"><canvas id="analyticsPieChart"></canvas></div>
                    </div>
                </div>

                <div class="dashboard-grid">
                    <div class="card">
                        <div class="card-header"><h3>Recent Lead Enquiries</h3></div>
                        <div style="overflow-x: auto;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Student</th>
                                        <th>Contact</th>
                                        <th>Email</th>
                                        <th>ID Doc</th>
                                        <th>Status</th>
                                        <th>Action</th>
                                    </tr>
                                </thead>
                                <tbody id="recentLeadsTbody"></tbody>
                            </table>
                        </div>
                    </div>
                    <div class="card">
                        <div class="card-header"><h3>Leads Overview Chart</h3></div>
                        <div class="chart-container"><canvas id="leadsPieChart"></canvas></div>
                    </div>
                </div>
            </div>

            <!-- ALL LEADS TAB -->
            <div id="leads-tab" class="tab-section">
                <div class="card">
                    <div class="card-header"><h3>All Registered Leads</h3></div>
                    <!-- Filters Section -->
                    <div style="display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; align-items: center; background: #f8fafc; padding: 14px; border-radius: 12px; border: 1px solid var(--border-color);">
                        <select id="filterStatus" class="form-control" style="width: auto; margin:0;" onchange="applyLeadFilters()">
                            <option value="">All Statuses</option>
                            <option value="New Lead">New Lead</option>
                            <option value="Contacted">Contacted</option>
                            <option value="Follow Up">Follow Up</option>
                            <option value="Closed">Closed</option>
                            <option value="Rejected">Rejected</option>
                        </select>
                        <select id="filterState" class="form-control" style="width: auto; margin:0;" onchange="applyLeadFilters()">
                            <option value="">All States</option>
                        </select>
                        <select id="filterCity" class="form-control" style="width: auto; margin:0;" onchange="applyLeadFilters()">
                            <option value="">All Cities</option>
                        </select>
                        <button onclick="resetLeadFilters()" style="background: #64748b; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-rotate-right" style="margin-right: 5px;"></i> Reset Filters</button>
                    </div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>#ID</th>
                                    <th>Student Name</th>
                                    <th>Contact</th>
                                    <th>Email ID</th>
                                    <th>ID Doc</th>
                                    <th>Score</th>
                                    <th>Status</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody id="allLeadsTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- WORK HISTORY TAB -->
            <div id="history-tab" class="tab-section">
                <div class="card">
                    <div class="card-header">
                        <h3><i class="fa-solid fa-clock-rotate-left"></i> Work Activity History Log</h3>
                        <div>
                            <label style="font-size:12px; font-weight:600; margin-right:8px;">Select Date:</label>
                            <input type="date" id="historyDateSelect" class="form-control" style="width:auto; display:inline-block; margin:0;" onchange="fetchWorkHistory()">
                        </div>
                    </div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>Time</th>
                                    <th>Activity / Task</th>
                                    <th>Details</th>
                                </tr>
                            </thead>
                            <tbody id="historyTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- COLLEGES TAB -->
            <div id="colleges-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <h3>Add New College / Tie-up</h3>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 15px;">
                        <input type="text" id="colName" placeholder="College Name" class="form-control" style="margin:0;">
                        <input type="text" id="colLoc" placeholder="Location" class="form-control" style="margin:0;">
                        <input type="text" id="colCourses" placeholder="Courses" class="form-control" style="margin:0;">
                        <input type="text" id="colPackage" placeholder="Avg Package" class="form-control" style="margin:0;">
                        <button onclick="addNewCollege()" style="background:#2563eb; color:white; border:none; border-radius:8px; font-weight:600; cursor:pointer; padding:10px;">Save College</button>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header"><h3>Partner Colleges List</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead><tr><th>#ID</th><th>College Name</th><th>Location</th><th>Courses Offered</th><th>Avg Package</th></tr></thead>
                            <tbody id="collegesTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TRASH TAB -->
            <div id="trash-tab" class="tab-section">
                <div class="card">
                    <div class="card-header"><h3 style="color: #ef4444;"><i class="fa-solid fa-trash-can"></i> Trash Bin</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead><tr><th>#ID</th><th>Student Name</th><th>Contact</th><th>Email</th><th>Actions</th></tr></thead>
                            <tbody id="trashTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- SETTINGS TAB -->
            <div id="settings-tab" class="tab-section">
                <div class="card">
                    <div class="card-header"><h3><i class="fa-solid fa-gear"></i> System Settings & Security Logs</h3></div>
                    <p style="color: var(--text-muted); font-size: 13.5px; margin-bottom: 20px; line-height: 1.5;">Configure system preferences and review secure user login and session activity logs.</p>
                    <div style="display: flex; gap: 15px; flex-wrap: wrap;">
                        <button onclick="openLogsModal()" style="background: var(--primary); color: white; border: none; padding: 12px 24px; border-radius: 10px; font-weight: 600; cursor: pointer; font-size: 14px; display: inline-flex; align-items: center; gap: 8px;"><i class="fa-solid fa-shield-halved"></i> View Login Activity Logs</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- VIEW DOCUMENT MODAL -->
    <div id="docModal" class="modal-overlay">
        <div class="modal-content">
            <span class="close-modal" onclick="closeDocModal()">&times;</span>
            <h3 style="margin-bottom: 15px; color: #1e293b; font-size: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px;"><i class="fa-solid fa-id-card" style="color:#2563eb; margin-right:8px;"></i> Student Details & Document</h3>
            <div id="modalBodyContainer"></div>
            <div style="margin-top: 20px; text-align: right;">
                <a id="modalDownloadBtn" href="#" class="action-icon-btn doc-btn" style="padding: 10px 18px; text-decoration: none; border-radius: 8px; display: inline-flex; align-items: center; gap: 8px; font-size: 13.5px; font-weight: 600; width: auto; height: auto;" target="_blank"><i class="fa-solid fa-download"></i> Download Document</a>
            </div>
        </div>
    </div>

    <!-- LOGS MODAL -->
    <div id="logsModal" class="modal-overlay">
        <div class="modal-content" style="max-width: 820px;">
            <span class="close-modal" onclick="closeLogsModal()">&times;</span>
            <h3 style="margin-bottom: 15px; color: #1e293b; font-size: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px;"><i class="fa-solid fa-shield-halved" style="color:#2563eb; margin-right:8px;"></i> User Login & Session Activity Logs</h3>
            <div style="max-height: 420px; overflow-y: auto;">
                <table>
                    <thead>
                        <tr>
                            <th>User</th>
                            <th>IP Address</th>
                            <th>Browser / OS</th>
                            <th>Login Time</th>
                            <th>Logout Time</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="logsTbody"></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- EDIT LEAD MODAL -->
    <div id="editModal" class="modal-overlay">
        <div class="modal-content">
            <span class="close-modal" onclick="closeEditModal()">&times;</span>
            <h3 style="margin-bottom: 15px; color: #1e293b; font-size: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px;"><i class="fa-solid fa-pen-to-square" style="color:#d97706; margin-right:8px;"></i> Edit Lead Details</h3>
            <form id="editLeadForm" onsubmit="submitEditLead(event)">
                <input type="hidden" id="edit_lead_id">
                <label style="font-size:12px; font-weight:600; color:#475569;">Student Name</label>
                <input type="text" id="edit_student_name" class="form-control" required>
                <label style="font-size:12px; font-weight:600; color:#475569;">Father's Name</label>
                <input type="text" id="edit_father_name" class="form-control">
                <label style="font-size:12px; font-weight:600; color:#475569;">Contact Number</label>
                <input type="tel" id="edit_contact_number" class="form-control" required>
                <label style="font-size:12px; font-weight:600; color:#475569;">Alternate Number</label>
                <input type="tel" id="edit_alternate_number" class="form-control">
                <label style="font-size:12px; font-weight:600; color:#475569;">Email ID</label>
                <input type="email" id="edit_student_email" class="form-control" required>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">State</label>
                        <input type="text" id="edit_state" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">City</label>
                        <input type="text" id="edit_city" class="form-control">
                    </div>
                </div>
                <label style="font-size:12px; font-weight:600; color:#475569;">Course Interest</label>
                <input type="text" id="edit_course_interest" class="form-control">
                
                <label style="font-size:12px; font-weight:600; color:#475569;">Update / Replace Document</label>
                <input type="file" id="edit_id_document" class="form-control" accept="image/*,.pdf">
                
                <div style="margin-top:10px; display:flex; align-items:center; gap:8px;">
                    <input type="checkbox" id="edit_delete_doc" style="width:16px; height:16px;">
                    <label for="edit_delete_doc" style="font-size:13px; color:#ef4444; font-weight:600; cursor:pointer;">Delete existing document</label>
                </div>

                <div style="margin-top: 20px; text-align: right;">
                    <button type="submit" id="saveEditBtn" style="background:#2563eb; color:white; border:none; padding:10px 20px; border-radius:8px; font-weight:600; cursor:pointer;">Save Changes</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        let rawLeadsData = [];
        let collegesData = [];
        let pieChartInstance = null;

        function toggleSidebar() {
            document.getElementById('sidebarNav').classList.toggle('show');
        }

        // Live Smartwatch & Time-based Greeting
        function updateClockAndGreeting() {
            const now = new Date();
            let hours = now.getHours();
            const minutes = String(now.getMinutes()).padStart(2, '0');
            const seconds = String(now.getSeconds()).padStart(2, '0');
            const ampm = hours >= 12 ? 'PM' : 'AM';
            
            // Dynamic Greeting Logic
            let greeting = "Good Morning Shivam Sir";
            if (hours >= 12 && hours < 17) {
                greeting = "Good Afternoon Shivam Sir";
            } else if (hours >= 17) {
                greeting = "Good Evening Shivam Sir";
            }
            document.getElementById('timeGreeting').innerText = greeting;

            hours = hours % 12;
            hours = hours ? hours : 12; // 12-hour format
            const timeString = `${String(hours).padStart(2, '0')}:${minutes}:${seconds} ${ampm}`;
            document.getElementById('liveWatch').innerText = timeString;
        }
        setInterval(updateClockAndGreeting, 1000);
        updateClockAndGreeting();

        function switchTab(tabId, navElement) {
            document.querySelectorAll('.tab-section').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            if(navElement) navElement.classList.add('active');
            if(tabId === 'colleges-tab') fetchColleges();
            if(tabId === 'history-tab') {
                const today = new Date().toISOString().split('T')[0];
                document.getElementById('historyDateSelect').value = today;
                fetchWorkHistory();
            }
            if(window.innerWidth <= 900) {
                document.getElementById('sidebarNav').classList.remove('show');
            }
        }

        async function fetchLeadsData() {
            try {
                const res = await fetch('/api/get-leads');
                if(res.ok) {
                    rawLeadsData = await res.json();
                    renderUI(rawLeadsData);
                }
            } catch(e) { console.error(e); }
        }

        async function fetchWorkHistory() {
            const selectedDate = document.getElementById('historyDateSelect').value;
            const res = await fetch(`/api/get-history?date=${selectedDate}`);
            if(res.ok) {
                const history = await res.json();
                const tbody = document.getElementById('historyTbody');
                tbody.innerHTML = '';
                if(history.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; color:#94a3b8;">No activity logged for this date.</td></tr>`;
                    return;
                }
                history.reverse().forEach(item => {
                    tbody.innerHTML += `
                        <tr>
                            <td><strong style="color:#2563eb;">${item.time}</strong></td>
                            <td><span class="badge-status badge-followup">${item.action_type}</span></td>
                            <td>${item.details}</td>
                        </tr>
                    `;
                });
            }
        }

        async function logAction(action_type, details) {
            await fetch('/api/log-action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action_type, details})
            });
        }

        async function fetchColleges() {
            const res = await fetch('/api/get-colleges');
            if(res.ok) {
                collegesData = await res.json();
                const tbody = document.getElementById('collegesTbody');
                tbody.innerHTML = '';
                collegesData.forEach(c => {
                    tbody.innerHTML += `<tr><td>#${c.id}</td><td><strong>${c.college_name}</strong></td><td>${c.location}</td><td>${c.courses}</td><td>${c.package}</td></tr>`;
                });
            }
        }

        async function addNewCollege() {
            const data = {
                college_name: document.getElementById('colName').value,
                location: document.getElementById('colLoc').value,
                courses: document.getElementById('colCourses').value,
                package: document.getElementById('colPackage').value
            };
            await fetch('/api/add-college', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });
            fetchColleges();
            alert('College added successfully!');
        }

        function renderUI(dataList) {
            const activeLeads = dataList.filter(l => !l.is_deleted);
            const trashLeads = dataList.filter(l => l.is_deleted);
            document.getElementById('statTotal').innerText = activeLeads.length;
            document.getElementById('statClosed').innerText = activeLeads.filter(l => l.status === 'Closed').length;
            document.getElementById('statContacted').innerText = activeLeads.filter(l => l.status === 'Contacted').length;
            document.getElementById('statNew').innerText = activeLeads.filter(l => l.status === 'New Lead').length;
            
            // Populate Followup / Recall section
            const followupRecallTbody = document.getElementById('followupRecallTbody');
            followupRecallTbody.innerHTML = '';
            const recallLeads = activeLeads.filter(l => l.status === 'Follow Up' || l.status === 'Contacted');
            if(recallLeads.length === 0) {
                followupRecallTbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:#94a3b8;">No pending follow-ups for today.</td></tr>`;
            } else {
                recallLeads.forEach(lead => {
                    followupRecallTbody.innerHTML += `
                        <tr>
                            <td><strong>${lead.student_name}</strong></td>
                            <td><a href="tel:${lead.contact_number}" onclick="logAction('Call Initiated', 'Called student ${lead.student_name}')" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
                            <td><span class="badge-status ${getBadgeClass(lead.status)}">${lead.status}</span></td>
                            <td>
                                <select class="status-select" onchange="updateStatus(${lead.id}, this.value)">
                                    <option value="New Lead" ${lead.status==='New Lead'?'selected':''}>New Lead</option>
                                    <option value="Contacted" ${lead.status==='Contacted'?'selected':''}>Contacted</option>
                                    <option value="Follow Up" ${lead.status==='Follow Up'?'selected':''}>Follow Up</option>
                                    <option value="Closed" ${lead.status==='Closed'?'selected':''}>Closed</option>
                                    <option value="Rejected" ${lead.status==='Rejected'?'selected':''}>Rejected</option>
                                </select>
                            </td>
                        </tr>
                    `;
                });
            }

            const recentTbody = document.getElementById('recentLeadsTbody');
            recentTbody.innerHTML = '';
            activeLeads.slice(-5).reverse().forEach(lead => {
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(lead)})' title="View Document"><i class="fa-solid fa-eye"></i></button>`;
                recentTbody.innerHTML += `
                    <tr>
                        <td><strong>${lead.student_name}</strong></td>
                        <td><a href="tel:${lead.contact_number}" onclick="logAction('Call Initiated', 'Called student ${lead.student_name}')" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
                        <td><a href="mailto:${lead.student_email}" onclick="logAction('Email Sent', 'Emailed student ${lead.student_name}')" class="action-icon-btn mail-btn"><i class="fa-solid fa-envelope"></i></a> ${lead.student_email}</td>
                        <td>${docAction}</td>
                        <td>
                            <select class="status-select" onchange="updateStatus(${lead.id}, this.value)">
                                <option value="New Lead" ${lead.status==='New Lead'?'selected':''}>New Lead</option>
                                <option value="Contacted" ${lead.status==='Contacted'?'selected':''}>Contacted</option>
                                <option value="Follow Up" ${lead.status==='Follow Up'?'selected':''}>Follow Up</option>
                                <option value="Closed" ${lead.status==='Closed'?'selected':''}>Closed</option>
                                <option value="Rejected" ${lead.status==='Rejected'?'selected':''}>Rejected</option>
                            </select>
                        </td>
                        <td><button class="action-icon-btn trash-btn" onclick="deleteLead(${lead.id})"><i class="fa-solid fa-trash-can"></i></button></td>
                    </tr>
                `;
            });
            
            updateFilterDropdowns(activeLeads);
            populateAllLeadsTable(activeLeads);
            updateAnalyticsData(activeLeads);

            const trashTbody = document.getElementById('trashTbody');
            trashTbody.innerHTML = '';
            trashLeads.forEach(lead => {
                trashTbody.innerHTML += `<tr><td>#${lead.id}</td><td><strong>${lead.student_name}</strong></td><td>${lead.contact_number}</td><td>${lead.student_email}</td><td><button onclick="restoreLead(${lead.id})" style="background:#16a34a; color:white; border:none; padding:5px 10px; border-radius:6px; cursor:pointer;">Restore</button></td></tr>`;
            });
            updatePieChart(activeLeads);
        }

        function populateAllLeadsTable(leads) {
            const allTbody = document.getElementById('allLeadsTbody');
            allTbody.innerHTML = '';
            leads.slice().reverse().forEach(lead => {
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(lead)})' title="View Document"><i class="fa-solid fa-eye"></i></button>`;
                allTbody.innerHTML += `
                    <tr>
                        <td>#${lead.id}</td>
                        <td><strong>${lead.student_name}</strong><br><small style="color:#64748b;">${lead.father_name || ''}</small></td>
                        <td><a href="tel:${lead.contact_number}" onclick="logAction('Call Initiated', 'Called student ${lead.student_name}')" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
                        <td><a href="mailto:${lead.student_email}" onclick="logAction('Email Sent', 'Emailed student ${lead.student_name}')" class="action-icon-btn mail-btn"><i class="fa-solid fa-envelope"></i></a> ${lead.student_email}</td>
                        <td>${docAction}</td>
                        <td><strong>${lead.score || 50} pts</strong></td>
                        <td>
                            <select class="status-select" onchange="updateStatus(${lead.id}, this.value)">
                                <option value="New Lead" ${lead.status==='New Lead'?'selected':''}>New Lead</option>
                                <option value="Contacted" ${lead.status==='Contacted'?'selected':''}>Contacted</option>
                                <option value="Follow Up" ${lead.status==='Follow Up'?'selected':''}>Follow Up</option>
                                <option value="Closed" ${lead.status==='Closed'?'selected':''}>Closed</option>
                                <option value="Rejected" ${lead.status==='Rejected'?'selected':''}>Rejected</option>
                            </select>
                        </td>
                        <td>
                            <button class="action-icon-btn edit-btn" onclick='openEditModal(${JSON.stringify(lead)})' title="Edit Lead"><i class="fa-solid fa-pen"></i></button>
                            <button class="action-icon-btn trash-btn" onclick="deleteLead(${lead.id})" title="Delete Lead"><i class="fa-solid fa-trash-can"></i></button>
                        </td>
                    </tr>
                `;
            });
        }

        function openDocModal(lead) {
            const modal = document.getElementById('docModal');
            const container = document.getElementById('modalBodyContainer');
            const downloadBtn = document.getElementById('modalDownloadBtn');
            
            let docPreviewHtml = '';
            if (lead.id_document) {
                const fullUrl = `/download-doc/${lead.id_document}`;
                downloadBtn.href = fullUrl;
                downloadBtn.style.display = 'inline-flex';
                
                if(lead.id_document.match(/\.(jpeg|jpg|png|gif)$/i)) {
                    docPreviewHtml = `<div style="margin-top: 15px; text-align: center;"><img src="${fullUrl}" style="max-width:100%; max-height:220px; border-radius:8px; border:1px solid #cbd5e1;" alt="Document"></div>`;
                } else {
                    docPreviewHtml = `<div style="margin-top: 15px;"><p style="color:#475569; font-size:13px;"><i class="fa-solid fa-file-pdf" style="color:#ef4444; margin-right:5px;"></i> Document attached. Click download to view.</p></div>`;
                }
            } else {
                downloadBtn.style.display = 'none';
                docPreviewHtml = `<div style="margin-top: 15px; background: #fffbeb; border: 1px solid #fde68a; padding: 12px; border-radius: 8px;"><p style="color:#b45309; font-size:13px; margin:0;"><i class="fa-solid fa-triangle-exclamation" style="margin-right:5px;"></i> Document has been deleted or is not available. Showing submitted information.</p></div>`;
            }

            container.innerHTML = `
                <div style="background: #f8fafc; padding: 16px; border-radius: 10px; border: 1px solid #e2e8f0; font-size: 13.5px; color: #334155; line-height: 1.6;">
                    <p style="margin-bottom:6px;"><strong>Student Name:</strong> ${lead.student_name}</p>
                    <p style="margin-bottom:6px;"><strong>Father's Name:</strong> ${lead.father_name || 'N/A'}</p>
                    <p style="margin-bottom:6px;"><strong>Contact:</strong> ${lead.contact_number}</p>
                    <p style="margin-bottom:6px;"><strong>Email:</strong> ${lead.student_email}</p>
                    <p style="margin-bottom:6px;"><strong>Location:</strong> ${lead.city || 'N/A'}, ${lead.state || 'N/A'}</p>
                    <p style="margin-bottom:0;"><strong>Course Interest:</strong> ${lead.course_interest || 'General'}</p>
                </div>
                ${docPreviewHtml}
            `;
            modal.style.display = 'flex';
        }
        function closeDocModal() { document.getElementById('docModal').style.display = 'none'; }

        function openEditModal(lead) {
            document.getElementById('edit_lead_id').value = lead.id;
            document.getElementById('edit_student_name').value = lead.student_name || '';
            document.getElementById('edit_father_name').value = lead.father_name || '';
            document.getElementById('edit_contact_number').value = lead.contact_number || '';
            document.getElementById('edit_alternate_number').value = lead.alternate_number || '';
            document.getElementById('edit_student_email').value = lead.student_email || '';
            document.getElementById('edit_state').value = lead.state || '';
            document.getElementById('edit_city').value = lead.city || '';
            document.getElementById('edit_course_interest').value = lead.course_interest || '';
            document.getElementById('edit_delete_doc').checked = false;
            document.getElementById('edit_id_document').value = '';
            
            document.getElementById('editModal').style.display = 'flex';
        }
        function closeEditModal() { document.getElementById('editModal').style.display = 'none'; }

        async function submitEditLead(e) {
            e.preventDefault();
            const btn = document.getElementById('saveEditBtn');
            btn.innerText = "Saving...";
            btn.disabled = true;

            const formData = new FormData();
            formData.append('lead_id', document.getElementById('edit_lead_id').value);
            formData.append('student_name', document.getElementById('edit_student_name').value);
            formData.append('father_name', document.getElementById('edit_father_name').value);
            formData.append('contact_number', document.getElementById('edit_contact_number').value);
            formData.append('alternate_number', document.getElementById('edit_alternate_number').value);
            formData.append('student_email', document.getElementById('edit_student_email').value);
            formData.append('state', document.getElementById('edit_state').value);
            formData.append('city', document.getElementById('edit_city').value);
            formData.append('course_interest', document.getElementById('edit_course_interest').value);
            formData.append('delete_doc', document.getElementById('edit_delete_doc').checked);

            const fileField = document.getElementById('edit_id_document');
            if (fileField.files.length > 0) {
                formData.append('id_document', fileField.files[0]);
            }

            try {
                const res = await fetch('/api/update-lead', {
                    method: 'POST',
                    body: formData
                });
                const result = await res.json();
                if (res.ok) {
                    alert('Lead updated successfully!');
                    closeEditModal();
                    fetchLeadsData();
                } else {
                    alert('Error: ' + result.message);
                }
            } catch(err) {
                console.error(err);
                alert('Something went wrong.');
            } finally {
                btn.innerText = "Save Changes";
                btn.disabled = false;
            }
        }

        function getBadgeClass(status) {
            if(status === 'New Lead') return 'badge-new';
            if(status === 'Contacted') return 'badge-contacted';
            if(status === 'Follow Up') return 'badge-followup';
            if(status === 'Closed') return 'badge-closed';
            return 'badge-rejected';
        }
        async function updateStatus(id, newStatus) {
            await fetch('/api/update-status', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({lead_id: id, status: newStatus}) });
            fetchLeadsData();
        }
        async function deleteLead(id) {
            if(confirm("Move lead to Trash?")) {
                await fetch('/api/delete-lead', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({lead_id: id}) });
                fetchLeadsData();
            }
        }
        async function restoreLead(id) {
            await fetch('/api/restore-lead', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({lead_id: id}) });
            fetchLeadsData();
        }
        function filterLeadsTable() {
            const query = document.getElementById('globalSearch').value.toLowerCase();
            document.querySelectorAll('tbody tr').forEach(row => {
                row.style.display = row.innerText.toLowerCase().includes(query) ? '' : 'none';
            });
        }
        function updatePieChart(activeLeads) {
            const counts = {
                'New Lead': activeLeads.filter(l => l.status==='New Lead').length,
                'Contacted': activeLeads.filter(l => l.status==='Contacted').length,
                'Follow Up': activeLeads.filter(l => l.status==='Follow Up').length,
                'Closed': activeLeads.filter(l => l.status==='Closed').length,
                'Rejected': activeLeads.filter(l => l.status==='Rejected').length
            };
            const ctx = document.getElementById('leadsPieChart').getContext('2d');
            if(pieChartInstance) pieChartInstance.destroy();
            pieChartInstance = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['New', 'Contacted', 'Follow Up', 'Closed', 'Rejected'],
                    datasets: [{
                        data: [counts['New Lead'], counts['Contacted'], counts['Follow Up'], counts['Closed'], counts['Rejected']],
                        backgroundColor: ['#38bdf8', '#f59e0b', '#6366f1', '#22c55e', '#ef4444']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
            });
        }
        fetchLeadsData();
        setInterval(fetchLeadsData, 5000);

        // Filtering Logic for All Leads
        function updateFilterDropdowns(leads) {
            const stateSelect = document.getElementById('filterState');
            const citySelect = document.getElementById('filterCity');
            
            const currentState = stateSelect.value;
            const currentCity = citySelect.value;
            
            const states = [...new Set(leads.map(l => l.state).filter(s => s && s !== 'N/A'))].sort();
            const cities = [...new Set(leads.map(l => l.city).filter(c => c && c !== 'N/A'))].sort();
            
            stateSelect.innerHTML = '<option value="">All States</option>' + states.map(s => `<option value="${s}" ${s===currentState?'selected':''}>${s}</option>`).join('');
            citySelect.innerHTML = '<option value="">All Cities</option>' + cities.map(c => `<option value="${c}" ${c===currentCity?'selected':''}>${c}</option>`).join('');
        }

        function applyLeadFilters() {
            const statusVal = document.getElementById('filterStatus').value;
            const stateVal = document.getElementById('filterState').value;
            const cityVal = document.getElementById('filterCity').value;
            
            const activeLeads = rawLeadsData.filter(l => !l.is_deleted);
            const filtered = activeLeads.filter(l => {
                if(statusVal && l.status !== statusVal) return false;
                if(stateVal && l.state !== stateVal) return false;
                if(cityVal && l.city !== cityVal) return false;
                return true;
            });
            populateAllLeadsTable(filtered);
        }

        function resetLeadFilters() {
            document.getElementById('filterStatus').value = '';
            document.getElementById('filterState').value = '';
            document.getElementById('filterCity').value = '';
            const activeLeads = rawLeadsData.filter(l => !l.is_deleted);
            populateAllLeadsTable(activeLeads);
        }

        // Settings Logs Modal Logic
        async function openLogsModal() {
            const modal = document.getElementById('logsModal');
            const tbody = document.getElementById('logsTbody');
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#94a3b8;">Loading logs...</td></tr>`;
            modal.style.display = 'flex';
            
            try {
                const res = await fetch('/api/get-logs');
                if(res.ok) {
                    const logs = await res.json();
                    tbody.innerHTML = '';
                    if(logs.length === 0) {
                        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#94a3b8;">No login activity logs available.</td></tr>`;
                        return;
                    }
                    logs.forEach(log => {
                        const statusBadge = log.status === 'Active' ? '<span class="badge-status badge-closed">Active</span>' : '<span class="badge-status badge-rejected">Logged Out</span>';
                        tbody.innerHTML += `
                            <tr>
                                <td><strong>${log.username}</strong></td>
                                <td>${log.ip_address}</td>
                                <td>${log.browser} / ${log.os}</td>
                                <td>${log.login_time}</td>
                                <td>${log.logout_time}</td>
                                <td>${statusBadge}</td>
                            </tr>
                        `;
                    });
                }
            } catch(e) {
                tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#ef4444;">Failed to load logs.</td></tr>`;
            }
        }
        function closeLogsModal() { document.getElementById('logsModal').style.display = 'none'; }

        // Weekly, Monthly & Yearly Analytics Logic
        let currentAnalyticsPeriod = 'week';
        let analyticsPieChartInstance = null;

        function showAnalyticsPeriod(period) {
            currentAnalyticsPeriod = period;
            document.getElementById('btnWeek').style.background = period === 'week' ? '#2563eb' : 'white';
            document.getElementById('btnWeek').style.color = period === 'week' ? 'white' : '#2563eb';
            document.getElementById('btnMonth').style.background = period === 'month' ? '#2563eb' : 'white';
            document.getElementById('btnMonth').style.color = period === 'month' ? 'white' : '#2563eb';
            document.getElementById('btnYear').style.background = period === 'year' ? '#2563eb' : 'white';
            document.getElementById('btnYear').style.color = period === 'year' ? 'white' : '#2563eb';
            
            updateAnalyticsData(rawLeadsData.filter(l => !l.is_deleted));
        }

        function updateAnalyticsData(activeLeads) {
            const now = new Date();
            const currentYear = now.getFullYear();
            const currentMonth = now.getMonth();
            
            // Helper for week check (last 7 days or current calendar week)
            const oneWeekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

            const weekLeads = activeLeads.filter(l => {
                if(!l.created_timestamp) return true; // fallback
                const d = new Date(l.created_timestamp * 1000);
                return d >= oneWeekAgo;
            });

            const monthLeads = activeLeads.filter(l => {
                if(!l.created_timestamp) return true;
                const d = new Date(l.created_timestamp * 1000);
                return d.getFullYear() === currentYear && d.getMonth() === currentMonth;
            });

            const yearLeads = activeLeads.filter(l => {
                if(!l.created_timestamp) return true;
                const d = new Date(l.created_timestamp * 1000);
                return d.getFullYear() === currentYear;
            });

            document.getElementById('countWeek').innerText = weekLeads.length;
            document.getElementById('countMonth').innerText = monthLeads.length;
            document.getElementById('countYear').innerText = yearLeads.length;

            let targetLeads = weekLeads;
            let periodName = "this week";
            if(currentAnalyticsPeriod === 'month') {
                targetLeads = monthLeads;
                periodName = "this month";
            } else if(currentAnalyticsPeriod === 'year') {
                targetLeads = yearLeads;
                periodName = "this year";
            }

            document.getElementById('analyticsDesc').innerText = `Displaying lead status distribution for ${periodName} (${targetLeads.length} total leads).`;

            if(targetLeads.length === 0) {
                document.getElementById('analyticsSummaryText').innerText = "No leads available for this period.";
            } else {
                document.getElementById('analyticsSummaryText').innerText = `Total Leads: ${targetLeads.length}`;
            }

            const counts = {
                'New Lead': targetLeads.filter(l => l.status==='New Lead').length,
                'Contacted': targetLeads.filter(l => l.status==='Contacted').length,
                'Follow Up': targetLeads.filter(l => l.status==='Follow Up').length,
                'Closed': targetLeads.filter(l => l.status==='Closed').length,
                'Rejected': targetLeads.filter(l => l.status==='Rejected').length
            };

            const ctx = document.getElementById('analyticsPieChart').getContext('2d');
            if(analyticsPieChartInstance) analyticsPieChartInstance.destroy();
            analyticsPieChartInstance = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['New', 'Contacted', 'Follow Up', 'Closed', 'Rejected'],
                    datasets: [{
                        data: [counts['New Lead'], counts['Contacted'], counts['Follow Up'], counts['Closed'], counts['Rejected']],
                        backgroundColor: ['#38bdf8', '#f59e0b', '#6366f1', '#22c55e', '#ef4444']
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } } }
            });
        }

    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
