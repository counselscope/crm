import os
import json
import csv
import io
import base64
import requests
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, make_response, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "counselscope_world_class_crm_2026_secret"
CORS(app)

LOGIN_LOGS_FILE = "login_logs.json"
DATA_FILE = "leads.json"
COLLEGES_FILE = "colleges.json"
HISTORY_FILE = "work_history.json"
USERS_FILE = "users.json"

# GitHub API Configuration from Environment Variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "") # e.g. "username/repository-name"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

def get_default_users():
    return {
        "admin": {
            "password": generate_password_hash("admin123"),
            "role": "Admin"
        },
        "client": {
            "password": generate_password_hash("client123"),
            "role": "Client"
        }
    }

def load_users():
    if not os.path.exists(USERS_FILE):
        default_users = get_default_users()
        save_data(USERS_FILE, default_users)
        return default_users
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return get_default_users()

def get_geolocation(ip):
    if not ip or ip in ["127.0.0.1", "localhost", "::1"]:
        return "Local / Unknown"
    try:
        res = requests.get(f"https://ipapi.co/{ip}/json/", timeout=2)
        if res.status_code == 200:
            data = res.json()
            if not data.get("error"):
                city = data.get("city", "Unknown")
                region = data.get("region", "Unknown")
                country = data.get("country_name", "Unknown")
                return f"{city}, {region}, {country}"
    except Exception:
        pass
    return "Unknown"

def parse_user_agent_detailed(ua_string):
    ua = (ua_string or "").lower()
    browser = "Unknown Browser"
    browser_version = "Unknown"
    
    if "chrome" in ua and "edge" not in ua and "opr" not in ua:
        browser = "Google Chrome"
        try:
            parts = ua.split("chrome/")
            if len(parts) > 1:
                browser_version = parts[1].split(" ")[0]
        except:
            pass
    elif "firefox" in ua:
        browser = "Mozilla Firefox"
        try:
            parts = ua.split("firefox/")
            if len(parts) > 1:
                browser_version = parts[1].split(" ")[0]
        except:
            pass
    elif "safari" in ua and "chrome" not in ua:
        browser = "Apple Safari"
        try:
            parts = ua.split("version/")
            if len(parts) > 1:
                browser_version = parts[1].split(" ")[0]
        except:
            pass
    elif "edge" in ua:
        browser = "Microsoft Edge"
        try:
            parts = ua.split("edg/")
            if len(parts) > 1:
                browser_version = parts[1].split(" ")[0]
        except:
            pass
    elif "opr" in ua or "opera" in ua:
        browser = "Opera"
    
    os_name = "Unknown OS"
    if "windows" in ua:
        os_name = "Windows"
    elif "macintosh" in ua or "mac os" in ua:
        os_name = "macOS"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "android" in ua:
        os_name = "Android"
    elif "linux" in ua:
        os_name = "Linux"
        
    return f"{browser} ({browser_version})", os_name

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
    
    if GITHUB_TOKEN and GITHUB_REPO and filename in [DATA_FILE, COLLEGES_FILE, HISTORY_FILE, LOGIN_LOGS_FILE, USERS_FILE]:
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

def log_login_activity(username, role, req, status="Successful"):
    logs = load_data(LOGIN_LOGS_FILE)
    now_local = datetime.now()
    
    ip = req.headers.get('X-Forwarded-For', req.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    if not ip:
        ip = "127.0.0.1"
        
    ua_string = req.headers.get('User-Agent', '')
    browser_info, os_info = parse_user_agent_detailed(ua_string)
    location = get_geolocation(ip)
    
    if status == "Successful":
        for l in logs:
            if l.get('username') == username and l.get('status') == 'Active':
                l['status'] = 'Logged Out'
                l['logout_date'] = now_local.strftime("%Y-%m-%d")
                l['logout_time'] = now_local.strftime("%d %b %Y, %I:%M %p")
                l['logout_timestamp'] = now_local.timestamp()
                
    log_entry = {
        "id": len(logs) + 1,
        "username": username,
        "role": role,
        "ip_address": ip,
        "user_agent": ua_string,
        "browser": browser_info,
        "os": os_info,
        "login_date": now_local.strftime("%Y-%m-%d"),
        "login_time": now_local.strftime("%d %b %Y, %I:%M %p"),
        "login_timestamp": now_local.timestamp(),
        "logout_date": "N/A",
        "logout_time": "N/A",
        "logout_timestamp": None,
        "location": location,
        "status": "Active" if status == "Successful" else "Failed",
        "session_info": f"Session ID: {abs(hash(ip + str(now_local.timestamp())))}"
    }
    logs.append(log_entry)
    save_data(LOGIN_LOGS_FILE, logs)

def log_logout_activity(username):
    logs = load_data(LOGIN_LOGS_FILE)
    now_local = datetime.now()
    for l in logs:
        if l.get('username') == username and l.get('status') == 'Active':
            l['status'] = 'Logged Out'
            l['logout_date'] = now_local.strftime("%Y-%m-%d")
            l['logout_time'] = now_local.strftime("%d %b %Y, %I:%M %p")
            l['logout_timestamp'] = now_local.timestamp()
    save_data(LOGIN_LOGS_FILE, logs)

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
        ext = os.path.splitext(original_filename)[1].lower() or ".jpg"
        target_filename = f"doc_{int(datetime.now().timestamp())}{ext}"
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

# --- API ENDPOINTS ---

@app.route('/api/submit-lead', methods=['POST'])
def submit_lead():
    try:
        form_data = request.form.to_dict()
        if not form_data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        student_name = form_data.get('student_name') or form_data.get('name') or 'Valued Enquirer'
        contact_number = form_data.get('contact_number') or form_data.get('phone') or 'N/A'
        student_email = form_data.get('student_email') or form_data.get('email') or 'N/A'

        document_filename = None
        if 'id_document' in request.files:
            file = request.files['id_document']
            if file and file.filename != '':
                document_filename = upload_file_to_github(file, student_name, file.filename)
        elif len(request.files) > 0:
            for file_key in request.files:
                file = request.files[file_key]
                if file and file.filename != '':
                    document_filename = upload_file_to_github(file, student_name, file.filename)
                    break

        leads = load_data(DATA_FILE)
        now = datetime.now()

        new_lead = {
            "id": len(leads) + 1,
            "student_name": student_name,
            "contact_number": contact_number,
            "student_email": student_email,
            "id_document": document_filename,
            "status": "New Lead",
            "score": 80 if contact_number != 'N/A' else 50,
            "notes": "Enquiry received via dynamic HTML form submission.",
            "is_deleted": False,
            "created_date": now.strftime("%Y-%m-%d"),
            "created_at": now.strftime("%d %b %Y, %I:%M %p"),
            "created_timestamp": now.timestamp(),
            "form_data": form_data
        }
        
        leads.append(new_lead)
        save_data(DATA_FILE, leads)
        log_activity("New Lead Form", f"New dynamic enquiry received for {student_name} ({contact_number})")

        return jsonify({"status": "success", "message": "Lead captured and stored dynamically!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/update-lead', methods=['POST'])
def update_lead():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        form_data = request.form.to_dict()
        lead_id = int(form_data.get('lead_id'))
        
        leads = load_data(DATA_FILE)
        target_lead = None
        for lead in leads:
            if lead['id'] == lead_id:
                target_lead = lead
                break
        
        if not target_lead:
            return jsonify({"status": "error", "message": "Lead not found"}), 404

        if 'student_name' in form_data:
            target_lead['student_name'] = form_data.get('student_name')
        if 'contact_number' in form_data:
            target_lead['contact_number'] = form_data.get('contact_number')
        if 'student_email' in form_data:
            target_lead['student_email'] = form_data.get('student_email')

        delete_doc = form_data.get('delete_doc') == 'true'
        if delete_doc:
            target_lead['id_document'] = None

        if 'id_document' in request.files:
            file = request.files['id_document']
            if file and file.filename != '':
                doc_path = upload_file_to_github(file, target_lead.get('student_name', 'Student'), file.filename)
                if doc_path:
                    target_lead['id_document'] = doc_path

        if 'form_data' not in target_lead or not isinstance(target_lead['form_data'], dict):
            target_lead['form_data'] = {}
        
        for k, v in form_data.items():
            if k != 'lead_id' and k != 'delete_doc':
                target_lead['form_data'][k] = v

        save_data(DATA_FILE, leads)
        log_activity("Lead Updated", f"Updated dynamic lead information for #{lead_id}")
        return jsonify({"status": "success", "message": "Lead updated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/get-leads', methods=['GET'])
def get_leads_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(DATA_FILE))


@app.route('/api/get-logs', methods=['GET'])
def get_logs_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    logs = load_data(LOGIN_LOGS_FILE)
    logs.sort(key=lambda x: x.get('login_timestamp', 0), reverse=True)
    return jsonify(logs)


@app.route('/api/clear-logs', methods=['POST'])
def clear_logs():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    
    save_data(LOGIN_LOGS_FILE, [])
    log_activity("Clear Logs", f"Admin {session.get('username')} cleared all login activity logs.")
    return jsonify({"status": "success", "message": "All login logs cleared successfully."})


@app.route('/api/delete-logs-range', methods=['POST'])
def delete_logs_range():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    
    data = request.json or {}
    date_val = data.get('date')
    from_date = data.get('from_date')
    to_date = data.get('to_date')
    
    logs = load_data(LOGIN_LOGS_FILE)
    new_logs = []
    for l in logs:
        ldate = l.get('login_date', '')
        keep = True
        if date_val and ldate == date_val:
            keep = False
        if from_date and to_date and (from_date <= ldate <= to_date):
            keep = False
        if keep:
            new_logs.append(l)
            
    save_data(LOGIN_LOGS_FILE, new_logs)
    log_activity("Delete Logs", f"Admin deleted login logs by filter (date: {date_val}, range: {from_date} to {to_date})")
    return jsonify({"status": "success", "message": "Selected login logs deleted successfully."})


@app.route('/api/delete-history-range', methods=['POST'])
def delete_history_range():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    
    data = request.json or {}
    date_val = data.get('date')
    from_date = data.get('from_date')
    to_date = data.get('to_date')
    
    history = load_data(HISTORY_FILE)
    new_hist = []
    for h in history:
        hdate = h.get('date', '')
        keep = True
        if date_val and hdate == date_val:
            keep = False
        if from_date and to_date and (from_date <= hdate <= to_date):
            keep = False
        if keep:
            new_hist.append(h)
            
    save_data(HISTORY_FILE, new_hist)
    log_activity("Delete Work History", f"Admin deleted work history by filter (date: {date_val}, range: {from_date} to {to_date})")
    return jsonify({"status": "success", "message": "Selected work history records deleted successfully."})


@app.route('/api/delete-college-range', methods=['POST'])
def delete_college_range():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    
    data = request.json or {}
    college_id = data.get('college_id')
    
    colleges = load_data(COLLEGES_FILE)
    colleges = [c for c in colleges if c.get('id') != college_id]
    save_data(COLLEGES_FILE, colleges)
    log_activity("Delete College", f"Admin deleted college tie-up #{college_id}")
    return jsonify({"status": "success", "message": "College record deleted successfully."})


@app.route('/api/delete-lead-range', methods=['POST'])
def delete_lead_range():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    
    data = request.json or {}
    lead_id = data.get('lead_id')
    date_val = data.get('date')
    from_date = data.get('from_date')
    to_date = data.get('to_date')
    
    leads = load_data(DATA_FILE)
    if lead_id:
        for l in leads:
            if l.get('id') == lead_id:
                l['is_deleted'] = True
    elif date_val or (from_date and to_date):
        for l in leads:
            ldate = l.get('created_date', '')
            if date_val and ldate == date_val:
                l['is_deleted'] = True
            if from_date and to_date and (from_date <= ldate <= to_date):
                l['is_deleted'] = True
                
    save_data(DATA_FILE, leads)
    log_activity("Delete Leads", f"Admin deleted lead records by filter")
    return jsonify({"status": "success", "message": "Selected lead records moved to trash successfully."})


@app.route('/api/change-password', methods=['POST'])
def change_password():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    
    data = request.json or request.form
    target_user = data.get('target_user')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')
    
    if not target_user or not new_password or not confirm_password:
        return jsonify({"status": "error", "message": "All fields are required."}), 400
        
    if new_password != confirm_password:
        return jsonify({"status": "error", "message": "New passwords do not match."}), 400
        
    users = load_users()
    if target_user not in users:
        return jsonify({"status": "error", "message": "Target user not found."}), 404
        
    users[target_user]['password'] = generate_password_hash(new_password)
    save_data(USERS_FILE, users)
    log_activity("Password Changed", f"Admin changed password for user: {target_user}")
    
    return jsonify({"status": "success", "message": f"Password for {target_user} updated successfully."})


# --- PDF-ONLY EXPORT ENDPOINTS ---

@app.route('/api/export-logs-pdf', methods=['GET'])
def export_logs_pdf():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
        
    logs = load_data(LOGIN_LOGS_FILE)
    date_filter = request.args.get('date')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    
    filtered = []
    for l in logs:
        ldate = l.get('login_date', '')
        if date_filter and ldate != date_filter:
            continue
        if from_date and to_date and not (from_date <= ldate <= to_date):
            continue
        filtered.append(l)
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Login Activity Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; color: #1e293b; padding: 25px; }}
            h1 {{ color: #2563eb; font-size: 22px; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }}
            .filter-info {{ font-size: 12px; color: #64748b; margin-bottom: 15px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }}
            td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - Login Activity Report</h1>
        <div class="filter-info">Generated on: {datetime.now().strftime('%d %b %Y, %I:%M %p')} | Filter: Date={date_filter or 'All'}, Range={from_date or 'N/A'} to {to_date or 'N/A'}</div>
        <table>
            <thead>
                <tr><th>ID</th><th>Username</th><th>Role</th><th>IP Address</th><th>Browser / OS</th><th>Location</th><th>Login Time</th><th>Logout Time</th><th>Status</th></tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>#{l.get('id')}</td><td><strong>{l.get('username')}</strong></td><td>{l.get('role')}</td><td>{l.get('ip_address')}</td><td>{l.get('browser')} / {l.get('os')}</td><td>{l.get('location')}</td><td>{l.get('login_time')}</td><td>{l.get('logout_time')}</td><td>{l.get('status')}</td></tr>" for l in filtered])}
            </tbody>
        </table>
        <script>window.onload = function() {{ window.print(); }}</script>
    </body>
    </html>
    """
    resp = make_response(html)
    resp.headers["Content-Disposition"] = "inline; filename=Login_Activity_Report.html"
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route('/api/export-history-pdf', methods=['GET'])
def export_history_pdf():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
        
    history = load_data(HISTORY_FILE)
    date_filter = request.args.get('date')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    
    filtered = []
    for h in history:
        hdate = h.get('date', '')
        if date_filter and hdate != date_filter:
            continue
        if from_date and to_date and not (from_date <= hdate <= to_date):
            continue
        filtered.append(h)
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Work History Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; color: #1e293b; padding: 25px; }}
            h1 {{ color: #2563eb; font-size: 22px; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }}
            .filter-info {{ font-size: 12px; color: #64748b; margin-bottom: 15px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }}
            td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - Work History Report</h1>
        <div class="filter-info">Generated on: {datetime.now().strftime('%d %b %Y, %I:%M %p')}</div>
        <table>
            <thead>
                <tr><th>ID</th><th>Date</th><th>Time</th><th>Action Type</th><th>Details</th></tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>#{h.get('id')}</td><td>{h.get('date')}</td><td>{h.get('time')}</td><td><strong>{h.get('action_type')}</strong></td><td>{h.get('details')}</td></tr>" for h in filtered])}
            </tbody>
        </table>
        <script>window.onload = function() {{ window.print(); }}</script>
    </body>
    </html>
    """
    resp = make_response(html)
    resp.headers["Content-Disposition"] = "inline; filename=Work_History_Report.html"
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route('/api/export-college-pdf', methods=['GET'])
def export_college_pdf():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
        
    colleges = load_data(COLLEGES_FILE)
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>College Directory Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; color: #1e293b; padding: 25px; }}
            h1 {{ color: #2563eb; font-size: 22px; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }}
            .filter-info {{ font-size: 12px; color: #64748b; margin-bottom: 15px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }}
            td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - College Directory Report</h1>
        <div class="filter-info">Generated on: {datetime.now().strftime('%d %b %Y, %I:%M %p')}</div>
        <table>
            <thead>
                <tr><th>ID</th><th>College Name</th><th>Location</th><th>Courses Offered</th><th>Avg Package</th></tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>#{c.get('id')}</td><td><strong>{c.get('college_name')}</strong></td><td>{c.get('location')}</td><td>{c.get('courses')}</td><td>{c.get('package')}</td></tr>" for c in colleges])}
            </tbody>
        </table>
        <script>window.onload = function() {{ window.print(); }}</script>
    </body>
    </html>
    """
    resp = make_response(html)
    resp.headers["Content-Disposition"] = "inline; filename=College_Directory_Report.html"
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route('/api/export-leads-pdf', methods=['GET'])
def export_leads_pdf():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
        
    leads = [l for l in load_data(DATA_FILE) if not l.get('is_deleted')]
    date_filter = request.args.get('date')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    
    filtered = []
    for l in leads:
        ldate = l.get('created_date', '')
        if date_filter and ldate != date_filter:
            continue
        if from_date and to_date and not (from_date <= ldate <= to_date):
            continue
        filtered.append(l)
        
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Student Leads Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; color: #1e293b; padding: 25px; }}
            h1 {{ color: #2563eb; font-size: 22px; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }}
            .filter-info {{ font-size: 12px; color: #64748b; margin-bottom: 15px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }}
            td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - Student Leads Report</h1>
        <div class="filter-info">Generated on: {datetime.now().strftime('%d %b %Y, %I:%M %p')}</div>
        <table>
            <thead>
                <tr><th>ID</th><th>Student Name</th><th>Contact</th><th>Email</th><th>Status</th><th>Form Details</th></tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>#{l.get('id')}</td><td><strong>{l.get('student_name')}</strong></td><td>{l.get('contact_number')}</td><td>{l.get('student_email')}</td><td>{l.get('status')}</td><td><small>{str(l.get('form_data',''))}</small></td></tr>" for l in filtered])}
            </tbody>
        </table>
        <script>window.onload = function() {{ window.print(); }}</script>
    </body>
    </html>
    """
    resp = make_response(html)
    resp.headers["Content-Disposition"] = "inline; filename=Student_Leads_Report.html"
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


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


@app.route('/api/export-excel', methods=['GET'])
def export_excel():
    return redirect(url_for('crm_dashboard'))

@app.route('/api/export-pdf', methods=['GET'])
def export_pdf():
    return redirect(url_for('crm_dashboard'))


# --- ROUTING & VIEWS ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        
        users = load_users()
        user_data = users.get(username)
        
        if user_data and check_password_hash(user_data['password'], password):
            session['logged_in'] = True
            session['username'] = username
            session['role'] = user_data['role']
            log_login_activity(username, user_data['role'], request, status="Successful")
            return redirect(url_for('crm_dashboard'))
        else:
            log_login_activity(username if username else "unknown", "Unknown", request, status="Failed")
            error = "Invalid Username or Password!"
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/dashboard')
def crm_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template_string(MAIN_DASHBOARD_HTML, role=session.get('role', 'Client'), username=session.get('username', 'admin'))

@app.route('/logout')
def logout():
    username = session.get('username', 'admin')
    log_logout_activity(username)
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('role', None)
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
        .credentials-hint { background: #0f172a; padding: 12px; border-radius: 8px; margin-top: 15px; font-size: 11.5px; color: #94a3b8; border: 1px solid #334155; text-align: left; line-height: 1.5; }
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
            <input type="text" name="username" required placeholder="admin or client">
            <label>Password</label>
            <input type="password" name="password" required placeholder="••••••••">
            <button type="submit">Sign In</button>
        </form>
        <div class="credentials-hint">
            <strong>Default Logins:</strong><br>
            • Admin: <code>admin</code> / <code>admin123</code><br>
            • Client: <code>client</code> / <code>client123</code>
        </div>
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

        .modal-overlay { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; backdrop-filter: blur(4px); padding: 15px; }
        .modal-content { background: white; padding: 25px; border-radius: 16px; max-width: 520px; width: 100%; text-align: left; position: relative; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); animation: modalPopup 0.3s cubic-bezier(0.16, 1, 0.3, 1); max-height: 95vh; overflow-y: auto; }
        @keyframes modalPopup { from { transform: scale(0.85); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        .close-modal { position: absolute; top: 15px; right: 20px; font-size: 22px; cursor: pointer; color: #64748b; transition: 0.2s; }
        .close-modal:hover { color: #0f172a; }

        .form-control { width: 100%; padding: 10px 12px; margin-bottom: 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13.5px; }
        .form-control:focus { outline: none; border-color: #2563eb; }

        @media (max-width: 900px) {
            body { flex-direction: column; height: auto; overflow: auto; }
            .sidebar { position: fixed; top: 0; left: -270px; width: 260px; height: 100vh; flex-direction: column; padding: 20px 15px; box-shadow: 5px 0 25px rgba(0,0,0,0.5); }
            .sidebar.show { left: 0; }
            .menu-toggle-btn { display: block; }
            .main-wrapper { height: auto; overflow: visible; }
            .dashboard-grid { grid-template-columns: 1fr; }
            .top-header { padding: 12px 15px; flex-wrap: wrap; height: auto; gap: 10px; }
            .search-bar { width: 100%; order: 3; }
            .content-area { padding: 15px; gap: 18px; }
            .hero-banner { padding: 20px; flex-direction: column; align-items: flex-start; text-align: left; }
            .export-btns-group { width: 100%; display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
            .export-btns-group a { width: 100%; justify-content: center; }
            .smart-watch { font-size: 12px; padding: 6px 12px; }
            .metrics-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
            .metric-card { padding: 14px; }
            .m-info h3 { font-size: 18px; }
            .analytics-grid-mobile { grid-template-columns: 1fr !important; gap: 15px; }
            .form-control { font-size: 14px; }
            table { min-width: 600px; }
            .modal-content { max-width: 95vw !important; padding: 18px; margin: 10px; }
        }

        @media (max-width: 500px) {
            .metrics-grid { grid-template-columns: 1fr; }
            .hero-text h1 { font-size: 20px; }
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
                    <p>Role: {{ role }}</p>
                </div>
            </div>
            <ul class="nav-menu">
                <li class="nav-item active" onclick="switchTab('dashboard-tab', this)"><button><i class="fa-solid fa-chart-pie"></i> Dashboard</button></li>
                <li class="nav-item" onclick="switchTab('leads-tab', this)"><button><i class="fa-solid fa-users"></i> All Leads</button></li>
                <li class="nav-item" onclick="switchTab('colleges-tab', this)"><button><i class="fa-solid fa-building-columns"></i> Colleges Manager</button></li>
                <li class="nav-item" onclick="switchTab('history-tab', this)"><button><i class="fa-solid fa-clock-rotate-left"></i> Work History</button></li>
                <li class="nav-item" onclick="switchTab('trash-tab', this)"><button><i class="fa-solid fa-trash-can"></i> Trash Bin</button></li>
                <li class="nav-item" onclick="switchTab('settings-tab', this)"><button><i class="fa-solid fa-gear"></i> Settings & Logs</button></li>
            </ul>
        </div>
        <div style="padding: 10px;">
            <div style="font-size:11.5px; color:#94a3b8; margin-bottom:8px; text-align:center;">Logged in as: <strong>{{ username }}</strong></div>
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
                        <h1 id="timeGreeting">Good Morning {{ username | title }}</h1>
                        <p>Welcome to your CounselScope CRM. Track dynamic leads, follow-up recalls, and student admissions in real-time.</p>
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
                        <div class="card-header"><h3>Recent Dynamic Enquiries</h3></div>
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

            <!-- ALL LEADS TAB (WITH PDF EXPORT & ROLE-BASED DELETE) -->
            <div id="leads-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <h3><i class="fa-solid fa-users"></i> All Leads Management & PDF Export</h3>
                    </div>
                    <div style="background: #f8fafc; padding: 15px; border-radius: 10px; border: 1px solid var(--border-color); display: flex; gap: 15px; flex-wrap: wrap; align-items: flex-end;">
                        <div>
                            <label style="font-size: 11.5px; font-weight: 600; color: #475569;">Specific Date</label>
                            <input type="date" id="leadDlDate" class="form-control" style="margin:0;">
                        </div>
                        <div>
                            <label style="font-size: 11.5px; font-weight: 600; color: #475569;">From Date</label>
                            <input type="date" id="leadDlFrom" class="form-control" style="margin:0;">
                        </div>
                        <div>
                            <label style="font-size: 11.5px; font-weight: 600; color: #475569;">To Date</label>
                            <input type="date" id="leadDlTo" class="form-control" style="margin:0;">
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <button onclick="downloadLeadsPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Download PDF Report</button>
                            {% if role == 'Admin' %}
                            <button onclick="deleteLeadsRange()" style="background: #ef4444; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-trash-can"></i> Delete Range</button>
                            {% endif %}
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header"><h3>Registered Leads Directory</h3></div>
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

            <!-- WORK HISTORY TAB (WITH PDF EXPORT & ROLE-BASED DELETE) -->
            <div id="history-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <h3><i class="fa-solid fa-clock-rotate-left"></i> Work History & PDF Export</h3>
                    </div>
                    <div style="background: #f8fafc; padding: 15px; border-radius: 10px; border: 1px solid var(--border-color); display: flex; gap: 15px; flex-wrap: wrap; align-items: flex-end;">
                        <div>
                            <label style="font-size: 11.5px; font-weight: 600; color: #475569;">Specific Date</label>
                            <input type="date" id="histDlDate" class="form-control" style="margin:0;" onchange="fetchWorkHistory()">
                        </div>
                        <div>
                            <label style="font-size: 11.5px; font-weight: 600; color: #475569;">From Date</label>
                            <input type="date" id="histDlFrom" class="form-control" style="margin:0;">
                        </div>
                        <div>
                            <label style="font-size: 11.5px; font-weight: 600; color: #475569;">To Date</label>
                            <input type="date" id="histDlTo" class="form-control" style="margin:0;">
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <button onclick="downloadHistoryPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Download PDF Report</button>
                            {% if role == 'Admin' %}
                            <button onclick="deleteHistoryRange()" style="background: #ef4444; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-trash-can"></i> Delete Range</button>
                            {% endif %}
                        </div>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header"><h3>Work Activity History Log</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>Date & Time</th>
                                    <th>Activity / Task</th>
                                    <th>Details</th>
                                </tr>
                            </thead>
                            <tbody id="historyTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- COLLEGES TAB (WITH PDF EXPORT & ROLE-BASED DELETE) -->
            <div id="colleges-tab" class="tab-section">
                {% if role == 'Admin' %}
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
                {% endif %}

                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header"><h3>College Directory PDF Export</h3></div>
                    <button onclick="downloadCollegePDF()" style="background: #dc2626; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Download College Directory PDF</button>
                </div>

                <div class="card">
                    <div class="card-header"><h3>Partner Colleges List</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead><tr><th>#ID</th><th>College Name</th><th>Location</th><th>Courses Offered</th><th>Avg Package</th>{% if role == 'Admin' %}<th>Action</th>{% endif %}</tr></thead>
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

            <!-- SETTINGS & LOGS TAB -->
            <div id="settings-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header"><h3><i class="fa-solid fa-gear"></i> System Settings & Login Activity Logs</h3></div>
                    <p style="color: var(--text-muted); font-size: 13.5px; margin-bottom: 20px; line-height: 1.5;">Review detailed login records with IP addresses, geolocation, browser/OS specs, and manage system security.</p>
                    
                    <!-- Download Reports Section (PDF Only) -->
                    <div style="background: #f8fafc; padding: 18px; border-radius: 12px; border: 1px solid var(--border-color); margin-bottom: 20px;">
                        <h4 style="font-size: 14px; margin-bottom: 12px; color: var(--text-dark);"><i class="fa-solid fa-file-pdf"></i> Download Login Activity PDF Report</h4>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; align-items: center;">
                            <div>
                                <label style="font-size: 11.5px; font-weight: 600; color: #475569;">Specific Date</label>
                                <input type="date" id="dlDate" class="form-control" style="margin:0;">
                            </div>
                            <div>
                                <label style="font-size: 11.5px; font-weight: 600; color: #475569;">From Date</label>
                                <input type="date" id="dlFromDate" class="form-control" style="margin:0;">
                            </div>
                            <div>
                                <label style="font-size: 11.5px; font-weight: 600; color: #475569;">To Date</label>
                                <input type="date" id="dlToDate" class="form-control" style="margin:0;">
                            </div>
                        </div>
                        <div style="margin-top: 15px; display: flex; gap: 10px; flex-wrap: wrap;">
                            <button onclick="downloadLogsPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px; display: inline-flex; align-items: center; gap: 6px;"><i class="fa-solid fa-file-pdf"></i> Download PDF Report</button>
                            {% if role == 'Admin' %}
                            <button onclick="deleteLogsRange()" style="background: #ef4444; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-trash-can"></i> Delete Selected Range</button>
                            {% endif %}
                            <button onclick="resetLogFilters()" style="background: #64748b; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;">Reset Filters</button>
                        </div>
                    </div>

                    {% if role == 'Admin' %}
                    <!-- Admin Only: Clear Logs & Password Management -->
                    <div style="background: #fff1f2; padding: 18px; border-radius: 12px; border: 1px solid #fecdd3; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px;">
                        <div>
                            <h4 style="font-size: 14px; color: #9f1239; margin-bottom: 4px;"><i class="fa-solid fa-triangle-exclamation"></i> Danger Zone (Admin Only)</h4>
                            <p style="font-size: 12px; color: #881337; margin:0;">Permanently clear all login activity records from the database.</p>
                        </div>
                        <button onclick="clearAllLogs()" style="background: #ef4444; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px; display: inline-flex; align-items: center; gap: 6px;"><i class="fa-solid fa-trash-can"></i> Clear All Logs</button>
                    </div>

                    <div style="background: #f8fafc; padding: 20px; border-radius: 12px; border: 1px solid var(--border-color); margin-bottom: 20px;">
                        <h4 style="font-size: 14px; margin-bottom: 12px; color: var(--text-dark);"><i class="fa-solid fa-key"></i> Password Management (Admin Only)</h4>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 15px;">
                            <div>
                                <label style="font-size: 11.5px; font-weight: 600; color: #475569;">Select User Account</label>
                                <select id="targetUser" class="form-control" style="margin:0;">
                                    <option value="admin">Admin Account</option>
                                    <option value="client">Client Account</option>
                                </select>
                            </div>
                            <div>
                                <label style="font-size: 11.5px; font-weight: 600; color: #475569;">New Password</label>
                                <input type="password" id="newPassword" placeholder="Enter new password" class="form-control" style="margin:0;">
                            </div>
                            <div>
                                <label style="font-size: 11.5px; font-weight: 600; color: #475569;">Confirm New Password</label>
                                <input type="password" id="confirmPassword" placeholder="Confirm new password" class="form-control" style="margin:0;">
                            </div>
                        </div>
                        <button onclick="updatePassword()" style="background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-floppy-disk" style="margin-right: 5px;"></i> Save Updated Password</button>
                    </div>
                    {% endif %}

                    <!-- Detailed Login Activity Table -->
                    <h4 style="font-size: 14px; margin-bottom: 12px; color: var(--text-dark);"><i class="fa-solid fa-list-check"></i> Complete Login Activity Logs</h4>
                    <div style="overflow-x: auto; max-height: 480px;">
                        <table>
                            <thead>
                                <tr>
                                    <th>#ID</th>
                                    <th>Username</th>
                                    <th>Role</th>
                                    <th>IP Address</th>
                                    <th>Browser / OS</th>
                                    <th>Location</th>
                                    <th>Login Time</th>
                                    <th>Logout Time</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody id="settingsLogsTbody">
                                <tr><td colspan="9" style="text-align:center; color:#94a3b8;">Loading logs...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- VIEW DOCUMENT MODAL -->
    <div id="docModal" class="modal-overlay">
        <div class="modal-content">
            <span class="close-modal" onclick="closeDocModal()">&times;</span>
            <h3 style="margin-bottom: 15px; color: #1e293b; font-size: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px;"><i class="fa-solid fa-id-card" style="color:#2563eb; margin-right:8px;"></i> Dynamic Form Fields & Document</h3>
            <div id="modalBodyContainer"></div>
            <div style="margin-top: 20px; text-align: right;">
                <a id="modalDownloadBtn" href="#" class="action-icon-btn doc-btn" style="padding: 10px 18px; text-decoration: none; border-radius: 8px; display: inline-flex; align-items: center; gap: 8px; font-size: 13.5px; font-weight: 600; width: auto; height: auto;" target="_blank"><i class="fa-solid fa-download"></i> Download Document</a>
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
                <input type="text" id="edit_student_name" name="student_name" class="form-control" required>
                <label style="font-size:12px; font-weight:600; color:#475569;">Contact Number</label>
                <input type="tel" id="edit_contact_number" name="contact_number" class="form-control" required>
                <label style="font-size:12px; font-weight:600; color:#475569;">Email ID</label>
                <input type="email" id="edit_student_email" name="student_email" class="form-control" required>
                
                <label style="font-size:12px; font-weight:600; color:#475569;">Update / Replace Document</label>
                <input type="file" id="edit_id_document" name="id_document" class="form-control" accept="image/*,.pdf">
                
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

        function updateClockAndGreeting() {
            const now = new Date();
            let hours = now.getHours();
            const minutes = String(now.getMinutes()).padStart(2, '0');
            const seconds = String(now.getSeconds()).padStart(2, '0');
            const ampm = hours >= 12 ? 'PM' : 'AM';
            
            let greeting = "Good Morning {{ username | title }}";
            if (hours >= 12 && hours < 17) {
                greeting = "Good Afternoon {{ username | title }}";
            } else if (hours >= 17) {
                greeting = "Good Evening {{ username | title }}";
            }
            document.getElementById('timeGreeting').innerText = greeting;

            hours = hours % 12;
            hours = hours ? hours : 12;
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
                fetchWorkHistory();
            }
            if(tabId === 'settings-tab') {
                fetchSettingsLogs();
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

        async function fetchSettingsLogs() {
            const tbody = document.getElementById('settingsLogsTbody');
            if(!tbody) return;
            try {
                const res = await fetch('/api/get-logs');
                if(res.ok) {
                    const logs = await res.json();
                    tbody.innerHTML = '';
                    if(logs.length === 0) {
                        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:#94a3b8;">No login activity logs available.</td></tr>`;
                        return;
                    }
                    logs.forEach(log => {
                        const statusBadge = log.status === 'Active' ? '<span class="badge-status badge-closed">Active</span>' : (log.status === 'Failed' ? '<span class="badge-status badge-rejected">Failed</span>' : '<span class="badge-status badge-contacted">Logged Out</span>');
                        tbody.innerHTML += `
                            <tr>
                                <td>#${log.id}</td>
                                <td><strong>${log.username}</strong></td>
                                <td><span class="badge-status badge-followup">${log.role || 'N/A'}</span></td>
                                <td><code>${log.ip_address}</code></td>
                                <td>${log.browser || 'Unknown'} / ${log.os || 'Unknown'}</td>
                                <td><small>${log.location || 'Unknown'}</small></td>
                                <td>${log.login_time}</td>
                                <td>${log.logout_time}</td>
                                <td>${statusBadge}</td>
                            </tr>
                        `;
                    });
                }
            } catch(e) {
                tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:#ef4444;">Failed to load logs.</td></tr>`;
            }
        }

        function downloadLogsPDF() {
            const date = document.getElementById('dlDate').value;
            const fromDate = document.getElementById('dlFromDate').value;
            const toDate = document.getElementById('dlToDate').value;
            let url = `/api/export-logs-pdf?1=1`;
            if(date) url += `&date=${date}`;
            if(fromDate) url += `&from_date=${fromDate}`;
            if(toDate) url += `&to_date=${toDate}`;
            window.open(url, '_blank');
        }

        function downloadHistoryPDF() {
            const date = document.getElementById('histDlDate').value;
            const fromDate = document.getElementById('histDlFrom').value;
            const toDate = document.getElementById('histDlTo').value;
            let url = `/api/export-history-pdf?1=1`;
            if(date) url += `&date=${date}`;
            if(fromDate) url += `&from_date=${fromDate}`;
            if(toDate) url += `&to_date=${toDate}`;
            window.open(url, '_blank');
        }

        function downloadCollegePDF() {
            window.open('/api/export-college-pdf', '_blank');
        }

        function downloadLeadsPDF() {
            const date = document.getElementById('leadDlDate').value;
            const fromDate = document.getElementById('leadDlFrom').value;
            const toDate = document.getElementById('leadDlTo').value;
            let url = `/api/export-leads-pdf?1=1`;
            if(date) url += `&date=${date}`;
            if(fromDate) url += `&from_date=${fromDate}`;
            if(toDate) url += `&to_date=${toDate}`;
            window.open(url, '_blank');
        }

        function resetLogFilters() {
            document.getElementById('dlDate').value = '';
            document.getElementById('dlFromDate').value = '';
            document.getElementById('dlToDate').value = '';
        }

        async function clearAllLogs() {
            if(confirm("Are you sure you want to permanently clear all login activity logs?")) {
                const res = await fetch('/api/clear-logs', { method: 'POST' });
                if(res.ok) { alert('Logs cleared.'); fetchSettingsLogs(); }
            }
        }

        async function deleteLogsRange() {
            const date = document.getElementById('dlDate').value;
            const from_date = document.getElementById('dlFromDate').value;
            const to_date = document.getElementById('dlToDate').value;
            if(!date && (!from_date || !to_date)) {
                alert('Please select a specific date or date range to delete.');
                return;
            }
            if(confirm("Are you sure you want to delete selected login logs?")) {
                const res = await fetch('/api/delete-logs-range', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({date, from_date, to_date})
                });
                if(res.ok) { alert('Selected logs deleted.'); fetchSettingsLogs(); }
                else { alert('Unauthorized or error.'); }
            }
        }

        async function deleteHistoryRange() {
            const date = document.getElementById('histDlDate').value;
            const from_date = document.getElementById('histDlFrom').value;
            const to_date = document.getElementById('histDlTo').value;
            if(!date && (!from_date || !to_date)) {
                alert('Please select a date or date range to delete work history.');
                return;
            }
            if(confirm("Are you sure you want to delete selected work history records?")) {
                const res = await fetch('/api/delete-history-range', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({date, from_date, to_date})
                });
                if(res.ok) { alert('Selected work history deleted.'); fetchWorkHistory(); }
                else { alert('Unauthorized or error.'); }
            }
        }

        async function deleteCollegeRecord(id) {
            if(confirm("Are you sure you want to delete this college record?")) {
                const res = await fetch('/api/delete-college-range', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({college_id: id})
                });
                if(res.ok) { alert('College deleted.'); fetchColleges(); }
                else { alert('Unauthorized or error.'); }
            }
        }

        async function deleteLeadsRange() {
            const date = document.getElementById('leadDlDate').value;
            const from_date = document.getElementById('leadDlFrom').value;
            const to_date = document.getElementById('leadDlTo').value;
            if(!date && (!from_date || !to_date)) {
                alert('Please select a date or date range to delete lead records.');
                return;
            }
            if(confirm("Are you sure you want to delete selected lead records?")) {
                const res = await fetch('/api/delete-lead-range', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({date, from_date, to_date})
                });
                if(res.ok) { alert('Selected leads moved to trash.'); fetchLeadsData(); }
                else { alert('Unauthorized or error.'); }
            }
        }

        async function updatePassword() {
            const targetUser = document.getElementById('targetUser').value;
            const newPassword = document.getElementById('newPassword').value;
            const confirmPassword = document.getElementById('confirmPassword').value;
            
            if(!newPassword || newPassword !== confirmPassword) {
                alert('Passwords do not match or are empty.');
                return;
            }
            const res = await fetch('/api/change-password', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target_user: targetUser, new_password: newPassword, confirm_password: confirmPassword})
            });
            if(res.ok) { alert('Password updated successfully!'); document.getElementById('newPassword').value=''; document.getElementById('confirmPassword').value=''; }
            else { alert('Unauthorized.'); }
        }

        async function fetchWorkHistory() {
            const selectedDate = document.getElementById('histDlDate').value;
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
                            <td><strong style="color:#2563eb;">${item.date} ${item.time}</strong></td>
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
                    let actionHtml = '';
                    {% if role == 'Admin' %}
                    actionHtml = `<td><button onclick="deleteCollegeRecord(${c.id})" class="action-icon-btn trash-btn"><i class="fa-solid fa-trash-can"></i></button></td>`;
                    {% endif %}
                    tbody.innerHTML += `<tr><td>#${c.id}</td><td><strong>${c.college_name}</strong></td><td>${c.location}</td><td>${c.courses}</td><td>${c.package}</td>${actionHtml}</tr>`;
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
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(lead)})' title="View Dynamic Data"><i class="fa-solid fa-eye"></i></button>`;
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
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(lead)})' title="View Dynamic Data"><i class="fa-solid fa-eye"></i></button>`;
                allTbody.innerHTML += `
                    <tr>
                        <td>#${lead.id}</td>
                        <td><strong>${lead.student_name}</strong></td>
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
                docPreviewHtml = `<div style="margin-top: 15px; background: #fffbeb; border: 1px solid #fde68a; padding: 12px; border-radius: 8px;"><p style="color:#b45309; font-size:13px; margin:0;"><i class="fa-solid fa-triangle-exclamation" style="margin-right:5px;"></i> Document not attached.</p></div>`;
            }

            let dynamicFieldsHtml = '<div style="background: #f8fafc; padding: 16px; border-radius: 10px; border: 1px solid #e2e8f0; font-size: 13.5px; color: #334155; line-height: 1.6; max-height: 250px; overflow-y: auto;">';
            if (lead.form_data && typeof lead.form_data === 'object') {
                for (const [key, val] of Object.entries(lead.form_data)) {
                    const formattedKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                    dynamicFieldsHtml += `<p style="margin-bottom:6px;"><strong>${formattedKey}:</strong> ${val}</p>`;
                }
            } else {
                dynamicFieldsHtml += `<p><strong>Student Name:</strong> ${lead.student_name}</p><p><strong>Contact:</strong> ${lead.contact_number}</p><p><strong>Email:</strong> ${lead.student_email}</p>`;
            }
            dynamicFieldsHtml += '</div>';

            container.innerHTML = `
                ${dynamicFieldsHtml}
                ${docPreviewHtml}
            `;
            modal.style.display = 'flex';
        }
        function closeDocModal() { document.getElementById('docModal').style.display = 'none'; }

        function openEditModal(lead) {
            document.getElementById('edit_lead_id').value = lead.id;
            document.getElementById('edit_student_name').value = lead.student_name || '';
            document.getElementById('edit_contact_number').value = lead.contact_number || '';
            document.getElementById('edit_student_email').value = lead.student_email || '';
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
            formData.append('contact_number', document.getElementById('edit_contact_number').value);
            formData.append('student_email', document.getElementById('edit_student_email').value);
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
            const oneWeekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);

            const weekLeads = activeLeads.filter(l => {
                if(!l.created_timestamp) return true;
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
