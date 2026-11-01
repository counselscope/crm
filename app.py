import os
import json
import csv
import io
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, make_response, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "counselscope_world_class_crm_2026_secret"
CORS(app)

DATA_FILE = "leads.json"
COLLEGES_FILE = "colleges.json"
UPLOAD_FOLDER = "student_documents"
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

        # Handle file upload ([Redacted ID] Document)
        document_filename = None
        if 'id_document' in request.files:
            file = request.files['id_document']
            if file and file.filename != '':
                # Create a secure folder structure for the student name
                safe_student_name = "".join(c for c in student_name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
                student_folder = os.path.join(app.config['UPLOAD_FOLDER'], safe_student_name)
                os.makedirs(student_folder, exist_ok=True)
                
                filename = secure_filename(file.filename)
                timestamp_prefix = datetime.now().strftime("%Y%m%d_%H%M%S_")
                document_filename = f"{timestamp_prefix}{filename}"
                file_path = os.path.join(student_folder, document_filename)
                file.save(file_path)
                
                # Relative path to store in JSON
                document_filename = f"{safe_student_name}/{document_filename}"

        leads = load_data(DATA_FILE)
        
        # AI Smart Lead Scoring based on completeness
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
            "notes": "Enquiry received via Web Portal with document.",
            "is_deleted": False,
            "created_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
        }
        leads.append(new_lead)
        save_data(DATA_FILE, leads)

        return jsonify({"status": "success", "message": "Lead captured successfully!"}), 200
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
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)


@app.route('/api/update-status', methods=['POST'])
def update_status():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    lead_id = data.get('lead_id')
    new_status = data.get('status')
    
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == lead_id:
            lead['status'] = new_status
            break
    save_data(DATA_FILE, leads)
    return jsonify({"status": "success"})


@app.route('/api/update-notes', methods=['POST'])
def update_notes():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    lead_id = data.get('lead_id')
    notes = data.get('notes')
    
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == lead_id:
            lead['notes'] = notes
            break
    save_data(DATA_FILE, leads)
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
    return jsonify({"status": "success"})


# --- EXPORT & IMPORT DATA API ---

@app.route('/api/export-csv', methods=['GET'])
def export_csv():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    leads = [l for l in load_data(DATA_FILE) if not l['is_deleted']]
    
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['ID', 'Student Name', 'Father Name', 'Contact', 'Alternate', 'Email', 'State', 'City', 'Course', 'Status', 'Score', 'Date'])
    
    for l in leads:
        writer.writerow([l.get('id'), l.get('student_name'), l.get('father_name'), l.get('contact_number'), l.get('alternate_number'), l.get('student_email'), l.get('state'), l.get('city'), l.get('course_interest'), l.get('status'), l.get('score'), l.get('created_at')])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=counselscope_leads.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@app.route('/api/import-csv', methods=['POST'])
def import_csv():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
    
    file = request.files['file']
    try:
        stream = io.TextIOWrapper(file.stream, encoding="utf-8")
        reader = csv.DictReader(stream)
        leads = load_data(DATA_FILE)
        
        for row in reader:
            new_lead = {
                "id": len(leads) + 1,
                "student_name": row.get('Student Name', 'Unknown'),
                "father_name": row.get('Father Name', 'N/A'),
                "contact_number": row.get('Contact', '0000000000'),
                "alternate_number": row.get('Alternate', 'N/A'),
                "student_email": row.get('Email', 'no@email.com'),
                "state": row.get('State', 'N/A'),
                "city": row.get('City', 'N/A'),
                "course_interest": row.get('Course', 'General'),
                "id_document": None,
                "status": row.get('Status', 'New Lead'),
                "score": 60,
                "notes": "Imported via CSV",
                "is_deleted": False,
                "created_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
            }
            leads.append(new_lead)
        
        save_data(DATA_FILE, leads)
        return jsonify({"status": "success", "message": "Leads imported successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# --- COLLEGES MANAGEMENT API ---

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


# --- FRONTEND TEMPLATES (EMBEDDED WITH FULL FEATURES) ---

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CounselScope CRM - Login</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Plus Jakarta Sans', sans-serif; box-sizing: border-box; }
        body { background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-card { background: #1e293b; padding: 40px; border-radius: 20px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); width: 380px; border: 1px solid #334155; text-align: center; }
        .logo-img { max-width: 140px; margin-bottom: 20px; border-radius: 8px; }
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

        .sidebar { width: 255px; background-color: var(--sidebar-bg); color: #fff; display: flex; flex-direction: column; padding: 20px 15px; flex-shrink: 0; justify-content: space-between; }
        .sidebar-brand { display: flex; align-items: center; gap: 12px; padding: 10px 10px 25px 10px; border-bottom: 1px solid rgba(255,255,255,0.08); }
        .sidebar-brand img { width: 38px; height: 38px; border-radius: 8px; }
        .sidebar-brand-text h3 { font-size: 16px; font-weight: 700; color: #fff; }
        .sidebar-brand-text p { font-size: 10px; color: #94a3b8; }

        .nav-menu { margin-top: 20px; display: flex; flex-direction: column; gap: 6px; list-style: none; }
        .nav-item button { width: 100%; display: flex; align-items: center; gap: 12px; padding: 12px 15px; border-radius: 10px; color: #94a3b8; background: none; border: none; font-size: 13.5px; font-weight: 500; cursor: pointer; transition: all 0.2s; text-align: left; }
        .nav-item button:hover, .nav-item.active button { background-color: var(--primary); color: #fff; font-weight: 600; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3); }

        .main-wrapper { flex: 1; display: flex; flex-direction: column; overflow-y: auto; }
        .top-header { background: var(--card-bg); height: 70px; display: flex; align-items: center; justify-content: space-between; padding: 0 30px; border-bottom: 1px solid var(--border-color); position: sticky; top: 0; z-index: 100; }
        .search-bar { display: flex; align-items: center; background: #f1f5f9; padding: 10px 16px; border-radius: 20px; width: 350px; gap: 10px; }
        .search-bar input { border: none; background: transparent; outline: none; width: 100%; font-size: 13px; }

        .header-actions { display: flex; align-items: center; gap: 15px; }
        .btn-export { background: #16a34a; color: white; padding: 8px 14px; border-radius: 8px; text-decoration: none; font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }
        .btn-import { background: #9333ea; color: white; padding: 8px 14px; border-radius: 8px; border: none; font-size: 12px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }

        .content-area { padding: 30px; display: flex; flex-direction: column; gap: 25px; }
        .hero-banner { background: linear-gradient(135deg, #0b1329 0%, #1d3557 100%); border-radius: 20px; padding: 35px 40px; color: white; box-shadow: 0 10px 25px rgba(11, 19, 41, 0.15); }
        .hero-text h1 { font-size: 26px; font-weight: 800; margin-bottom: 8px; }
        .hero-text p { font-size: 13.5px; color: #94a3b8; max-width: 500px; line-height: 1.5; }

        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 18px; }
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
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
        .card-header h3 { font-size: 15px; font-weight: 700; color: var(--text-dark); }

        .filter-bar { display: flex; gap: 12px; margin-bottom: 15px; flex-wrap: wrap; }
        .filter-bar select, .filter-bar input { padding: 8px 12px; border-radius: 8px; border: 1px solid var(--border-color); font-size: 12.5px; background: #fff; }

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
        .call-btn:hover { background: #16a34a; color: white; }
        .mail-btn { background: #e0f2fe; color: #0284c7; }
        .mail-btn:hover { background: #0284c7; color: white; }
        .doc-btn { background: #fef3c7; color: #d97706; }
        .doc-btn:hover { background: #d97706; color: white; }
        .trash-btn { background: #fee2e2; color: #dc2626; border: none; cursor: pointer; }
        .trash-btn:hover { background: #dc2626; color: white; }

        .chart-container { position: relative; height: 210px; display: flex; justify-content: center; }
        .tab-section { display: none; }
        .tab-section.active { display: block; }

        /* Modal for viewing documents */
        #docModal { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; }
        .modal-content { background: white; padding: 25px; border-radius: 12px; max-width: 500px; width: 90%; text-align: center; position: relative; }
        .close-modal { position: absolute; top: 12px; right: 15px; font-size: 20px; cursor: pointer; color: #64748b; }
    </style>
</head>
<body>

    <aside class="sidebar">
        <div>
            <div class="sidebar-brand">
                <img src="https://i.ibb.co/6R6t2Y0/unnamed.jpg" alt="Logo">
                <div class="sidebar-brand-text">
                    <h3>CounselScope</h3>
                    <p>World-Class CRM</p>
                </div>
            </div>

            <ul class="nav-menu">
                <li class="nav-item active" onclick="switchTab('dashboard-tab', this)">
                    <button><i class="fa-solid fa-chart-pie"></i> Dashboard</button>
                </li>
                <li class="nav-item" onclick="switchTab('leads-tab', this)">
                    <button><i class="fa-solid fa-users"></i> All Leads</button>
                </li>
                <li class="nav-item" onclick="switchTab('colleges-tab', this)">
                    <button><i class="fa-solid fa-building-columns"></i> Colleges Manager</button>
                </li>
                <li class="nav-item" onclick="switchTab('trash-tab', this)">
                    <button><i class="fa-solid fa-trash-can"></i> Trash Bin</button>
                </li>
            </ul>
        </div>

        <div style="padding: 10px;">
            <a href="/logout" style="background:#ef4444; color:white; padding:10px; border-radius:8px; display:block; text-align:center; text-decoration:none; font-weight:600; font-size:13px;">Logout Admin</a>
        </div>
    </aside>

    <div class="main-wrapper">
        <header class="top-header">
            <div class="search-bar">
                <i class="fa-solid fa-magnifying-glass"></i>
                <input type="text" id="globalSearch" onkeyup="filterLeadsTable()" placeholder="Search leads by name, email, phone...">
            </div>

            <div class="header-actions">
                <a href="/api/export-csv" class="btn-export"><i class="fa-solid fa-file-excel"></i> Export CSV</a>
                <button class="btn-import" onclick="document.getElementById('csvFileInput').click()"><i class="fa-solid fa-file-arrow-up"></i> Import CSV</button>
                <input type="file" id="csvFileInput" style="display:none" accept=".csv" onchange="uploadCSV(this)">
            </div>
        </header>

        <div class="content-area">

            <!-- TAB 1: DASHBOARD -->
            <div id="dashboard-tab" class="tab-section active">
                <div class="hero-banner" style="margin-bottom: 25px;">
                    <div class="hero-text">
                        <h1>Build Relationships. Grow Admissions.</h1>
                        <p>Complete AI-enabled college CRM with instant calling, direct mailer dispatch, live status charts, and document management.</p>
                    </div>
                </div>

                <div class="metrics-grid" style="margin-bottom: 25px;">
                    <div class="metric-card">
                        <div class="m-icon blue"><i class="fa-solid fa-users"></i></div>
                        <div class="m-info"><h3 id="statTotal">0</h3><p>Total Leads</p></div>
                    </div>
                    <div class="metric-card">
                        <div class="m-icon green"><i class="fa-solid fa-graduation-cap"></i></div>
                        <div class="m-info"><h3 id="statClosed">0</h3><p>Admissions Closed</p></div>
                    </div>
                    <div class="metric-card">
                        <div class="m-icon orange"><i class="fa-solid fa-phone-volume"></i></div>
                        <div class="m-info"><h3 id="statContacted">0</h3><p>Contacted</p></div>
                    </div>
                    <div class="metric-card">
                        <div class="m-icon purple"><i class="fa-solid fa-spinner"></i></div>
                        <div class="m-info"><h3 id="statNew">0</h3><p>New Leads</p></div>
                    </div>
                </div>

                <div class="dashboard-grid">
                    <div class="card">
                        <div class="card-header">
                            <h3>Recent Lead Enquiries</h3>
                        </div>
                        <div style="overflow-x: auto;">
                            <table>
                                <thead>
                                    <tr>
                                        <th>Student</th>
                                        <th>Contact / Call</th>
                                        <th>Email / Mailer</th>
                                        <th>[Redacted ID] Doc</th>
                                        <th>Status</th>
                                        <th>Action</th>
                                    </tr>
                                </thead>
                                <tbody id="recentLeadsTbody"></tbody>
                            </table>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header">
                            <h3>Leads Overview Chart</h3>
                        </div>
                        <div class="chart-container">
                            <canvas id="leadsPieChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>

            <!-- TAB 2: ALL LEADS -->
            <div id="leads-tab" class="tab-section">
                <div class="card">
                    <div class="card-header">
                        <h3>All Registered Leads & Advanced Filters</h3>
                    </div>
                    
                    <div class="filter-bar">
                        <select id="filterStatus" onchange="applyAdvancedFilters()">
                            <option value="">All Statuses</option>
                            <option value="New Lead">New Lead</option>
                            <option value="Contacted">Contacted</option>
                            <option value="Follow Up">Follow Up</option>
                            <option value="Closed">Closed</option>
                            <option value="Rejected">Rejected</option>
                        </select>
                        <select id="filterState" onchange="applyAdvancedFilters()">
                            <option value="">All States</option>
                            <option value="Delhi">Delhi</option>
                            <option value="Uttar Pradesh">Uttar Pradesh</option>
                            <option value="Maharashtra">Maharashtra</option>
                            <option value="Bihar">Bihar</option>
                            <option value="Karnataka">Karnataka</option>
                        </select>
                    </div>

                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>#ID</th>
                                    <th>Student Name</th>
                                    <th>Contact</th>
                                    <th>Email ID</th>
                                    <th>[Redacted ID] Doc</th>
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

            <!-- TAB 3: COLLEGES MANAGER -->
            <div id="colleges-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <h3>Add New College / Tie-up</h3>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 15px;">
                        <input type="text" id="colName" placeholder="College Name" style="padding:10px; border-radius:8px; border:1px solid #cbd5e1;">
                        <input type="text" id="colLoc" placeholder="Location (City, State)" style="padding:10px; border-radius:8px; border:1px solid #cbd5e1;">
                        <input type="text" id="colCourses" placeholder="Courses (B.Tech, MBA)" style="padding:10px; border-radius:8px; border:1px solid #cbd5e1;">
                        <input type="text" id="colPackage" placeholder="Avg Package (e.g. 6 LPA)" style="padding:10px; border-radius:8px; border:1px solid #cbd5e1;">
                        <button onclick="addNewCollege()" style="background:#2563eb; color:white; border:none; border-radius:8px; font-weight:600; cursor:pointer;">Save College</button>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header"><h3>Partner Colleges List</h3></div>
                    <table>
                        <thead>
                            <tr>
                                <th>#ID</th>
                                <th>College Name</th>
                                <th>Location</th>
                                <th>Courses Offered</th>
                                <th>Avg Package</th>
                            </tr>
                        </thead>
                        <tbody id="collegesTbody"></tbody>
                    </table>
                </div>
            </div>

            <!-- TAB 4: TRASH BIN -->
            <div id="trash-tab" class="tab-section">
                <div class="card">
                    <div class="card-header"><h3 style="color: #ef4444;"><i class="fa-solid fa-trash-can"></i> Trash Bin</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>#ID</th>
                                    <th>Student Name</th>
                                    <th>Contact</th>
                                    <th>Email</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody id="trashTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

        </div>
    </div>

    <!-- DOCUMENT VIEW MODAL -->
    <div id="docModal">
        <div class="modal-content">
            <span class="close-modal" onclick="closeDocModal()">&times;</span>
            <h3 style="margin-bottom: 15px; color: #1e293b;">[Redacted ID] Document Viewer</h3>
            <div id="modalBodyContainer" style="margin-bottom: 20px; max-height: 350px; overflow: auto;"></div>
            <a id="modalDownloadBtn" href="#" class="btn-export" style="display: inline-block; text-align: center;"><i class="fa-solid fa-download"></i> Download Document</a>
        </div>
    </div>

    <script>
        let rawLeadsData = [];
        let collegesData = [];
        let pieChartInstance = null;

        function switchTab(tabId, navElement) {
            document.querySelectorAll('.tab-section').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            if(navElement) navElement.classList.add('active');
            if(tabId === 'colleges-tab') fetchColleges();
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

            const recentTbody = document.getElementById('recentLeadsTbody');
            recentTbody.innerHTML = '';
            activeLeads.slice(-5).reverse().forEach(lead => {
                const docAction = lead.id_document ? `<button class="action-icon-btn doc-btn" onclick="openDocModal('${lead.id_document}')" title="View Document"><i class="fa-solid fa-id-card"></i></button>` : `<span style="color:#94a3b8; font-size:11px;">No Doc</span>`;
                recentTbody.innerHTML += `
                    <tr>
                        <td><strong>${lead.student_name}</strong></td>
                        <td>
                            <a href="tel:${lead.contact_number}" class="action-icon-btn call-btn" title="Call Student"><i class="fa-solid fa-phone"></i></a>
                            ${lead.contact_number}
                        </td>
                        <td>
                            <a href="mailto:${lead.student_email}?subject=Admission Enquiry CounselScope&body=Dear ${lead.student_name}, regarding your college admission enquiry..." class="action-icon-btn mail-btn" title="Send Email"><i class="fa-solid fa-envelope"></i></a>
                            ${lead.student_email}
                        </td>
                        <td>${docAction}</td>
                        <td><span class="badge-status ${getBadgeClass(lead.status)}">${lead.status}</span></td>
                        <td>
                            <button class="action-icon-btn trash-btn" onclick="deleteLead(${lead.id})" title="Delete"><i class="fa-solid fa-trash-can"></i></button>
                        </td>
                    </tr>
                `;
            });

            populateAllLeadsTable(activeLeads);

            const trashTbody = document.getElementById('trashTbody');
            trashTbody.innerHTML = '';
            trashLeads.forEach(lead => {
                trashTbody.innerHTML += `
                    <tr>
                        <td>#${lead.id}</td>
                        <td><strong>${lead.student_name}</strong></td>
                        <td>${lead.contact_number}</td>
                        <td>${lead.student_email}</td>
                        <td>
                            <button onclick="restoreLead(${lead.id})" style="background:#16a34a; color:white; border:none; padding:5px 10px; border-radius:6px; cursor:pointer;">Restore</button>
                            <button onclick="permDelete(${lead.id})" style="background:#dc2626; color:white; border:none; padding:5px 10px; border-radius:6px; cursor:pointer;">Delete</button>
                        </td>
                    </tr>
                `;
            });

            updatePieChart(activeLeads);
        }

        function populateAllLeadsTable(leads) {
            const allTbody = document.getElementById('allLeadsTbody');
            allTbody.innerHTML = '';
            leads.slice().reverse().forEach(lead => {
                const docAction = lead.id_document ? `<button class="action-icon-btn doc-btn" onclick="openDocModal('${lead.id_document}')"><i class="fa-solid fa-id-card"></i></button>` : `<span style="color:#94a3b8; font-size:11px;">No Doc</span>`;
                allTbody.innerHTML += `
                    <tr>
                        <td>#${lead.id}</td>
                        <td><strong>${lead.student_name}</strong><br><small>${lead.father_name}</small></td>
                        <td><a href="tel:${lead.contact_number}" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
                        <td><a href="mailto:${lead.student_email}?subject=Admission CounselScope" class="action-icon-btn mail-btn"><i class="fa-solid fa-envelope"></i></a> ${lead.student_email}</td>
                        <td>${docAction}</td>
                        <td><span style="font-weight:700; color:#2563eb;">${lead.score || 50} pts</span></td>
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
                            <button class="action-icon-btn trash-btn" onclick="deleteLead(${lead.id})"><i class="fa-solid fa-trash-can"></i></button>
                        </td>
                    </tr>
                `;
            });
        }

        function openDocModal(docPath) {
            const modal = document.getElementById('docModal');
            const container = document.getElementById('modalBodyContainer');
            const downloadBtn = document.getElementById('modalDownloadBtn');
            
            const fullUrl = `/download-doc/${docPath}`;
            downloadBtn.href = fullUrl;

            if(docPath.match(/\.(jpeg|jpg|png|gif)$/i)) {
                container.innerHTML = `<img src="${fullUrl}" style="max-width:100%; border-radius:8px;" alt="[Redacted ID] Card">`;
            } else {
                container.innerHTML = `<p style="padding:20px; color:#475569;">Document format ready for download.</p>`;
            }
            modal.style.display = 'flex';
        }

        function closeDocModal() {
            document.getElementById('docModal').style.display = 'none';
        }

        function applyAdvancedFilters() {
            const statusVal = document.getElementById('filterStatus').value;
            const stateVal = document.getElementById('filterState').value;
            let filtered = rawLeadsData.filter(l => !l.is_deleted);

            if(statusVal) filtered = filtered.filter(l => l.status === statusVal);
            if(stateVal) filtered = filtered.filter(l => l.state === stateVal);

            populateAllLeadsTable(filtered);
        }

        function getBadgeClass(status) {
            if(status === 'New Lead') return 'badge-new';
            if(status === 'Contacted') return 'badge-contacted';
            if(status === 'Follow Up') return 'badge-followup';
            if(status === 'Closed') return 'badge-closed';
            return 'badge-rejected';
        }

        async function updateStatus(id, newStatus) {
            await fetch('/api/update-status', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({lead_id: id, status: newStatus})
            });
            fetchLeadsData();
        }

        async function deleteLead(id) {
            if(confirm("Move lead to Trash?")) {
                await fetch('/api/delete-lead', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({lead_id: id})
                });
                fetchLeadsData();
            }
        }

        async function restoreLead(id) {
            await fetch('/api/restore-lead', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({lead_id: id})
            });
            fetchLeadsData();
        }

        async function permDelete(id) {
            if(confirm("Permanently delete this lead?")) {
                await fetch('/api/permanent-delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({lead_id: id})
                });
                fetchLeadsData();
            }
        }

        async function uploadCSV(input) {
            const formData = new FormData();
            formData.append("file", input.files[0]);
            const res = await fetch('/api/import-csv', {method: 'POST', body: formData});
            const data = await res.json();
            alert(data.message);
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
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
