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

# Excel export support via openpyxl if available
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    openpyxl = None

app = Flask(__name__)
app.secret_key = "counselscope_world_class_crm_2026_secret"
CORS(app)

LOGIN_LOGS_FILE = "login_logs.json"
DATA_FILE = "leads.json"
COLLEGES_FILE = "colleges.json"
HISTORY_FILE = "work_history.json"
USERS_FILE = "users.json"
STUDENTS_FILE = "students.json"

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
    
    if GITHUB_TOKEN and GITHUB_REPO and filename in [DATA_FILE, COLLEGES_FILE, HISTORY_FILE, LOGIN_LOGS_FILE, USERS_FILE, STUDENTS_FILE]:
        commit_json_to_github(filename)

def log_activity(action_type, details, username=None, role=None):
    history = load_data(HISTORY_FILE)
    now = datetime.now()
    uname = username or session.get('username', 'System')
    urole = role or session.get('role', 'Admin')
    log_item = {
        "id": len(history) + 1,
        "username": uname,
        "role": urole,
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
    log_activity("User Login", f"User {username} ({role}) logged in successfully from IP {ip}", username=username, role=role)

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
    log_activity("User Logout", f"User {username} logged out.", username=username)

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
            "father_name": form_data.get('father_name', ''),
            "contact_number": contact_number,
            "alternate_number": form_data.get('alternate_number', ''),
            "student_email": student_email,
            "current_education_level": form_data.get('current_education_level', ''),
            "qualification": form_data.get('qualification', ''),
            "percentage_10th": form_data.get('percentage_10th', ''),
            "percentage_12th": form_data.get('percentage_12th', ''),
            "course_details": form_data.get('course_details', ''),
            "budget": form_data.get('budget', ''),
            "hostel_preference": form_data.get('hostel_preference', ''),
            "admission_preference": form_data.get('admission_preference', ''),
            "assigned_college": form_data.get('assigned_college', ''),
            "state": form_data.get('state', ''),
            "city": form_data.get('city', ''),
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
        log_activity("Lead Created", f"New dynamic enquiry received for {student_name} ({contact_number})")

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

        # Update all comprehensive lead/student fields
        target_lead['student_name'] = form_data.get('student_name', target_lead.get('student_name'))
        target_lead['father_name'] = form_data.get('father_name', target_lead.get('father_name', ''))
        target_lead['contact_number'] = form_data.get('contact_number', target_lead.get('contact_number'))
        target_lead['alternate_number'] = form_data.get('alternate_number', target_lead.get('alternate_number', ''))
        target_lead['student_email'] = form_data.get('student_email', target_lead.get('student_email'))
        target_lead['current_education_level'] = form_data.get('current_education_level', target_lead.get('current_education_level', ''))
        target_lead['qualification'] = form_data.get('qualification', target_lead.get('qualification', ''))
        target_lead['percentage_10th'] = form_data.get('percentage_10th', target_lead.get('percentage_10th', ''))
        target_lead['percentage_12th'] = form_data.get('percentage_12th', target_lead.get('percentage_12th', ''))
        target_lead['course_details'] = form_data.get('course_details', target_lead.get('course_details', ''))
        target_lead['budget'] = form_data.get('budget', target_lead.get('budget', ''))
        target_lead['hostel_preference'] = form_data.get('hostel_preference', target_lead.get('hostel_preference', ''))
        target_lead['admission_preference'] = form_data.get('admission_preference', target_lead.get('admission_preference', ''))
        target_lead['assigned_college'] = form_data.get('assigned_college', target_lead.get('assigned_college', ''))
        target_lead['state'] = form_data.get('state', target_lead.get('state', ''))
        target_lead['city'] = form_data.get('city', target_lead.get('city', ''))

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
        log_activity("Lead Updated", f"Updated comprehensive information for lead #{lead_id} ({target_lead['student_name']})")
        return jsonify({"status": "success", "message": "Lead updated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/get-leads', methods=['GET'])
def get_leads_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(DATA_FILE))


@app.route('/api/get-students', methods=['GET'])
def get_students_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(STUDENTS_FILE))


@app.route('/api/convert-to-student', methods=['POST'])
def convert_to_student():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    lead_id = data.get('lead_id')
    
    leads = load_data(DATA_FILE)
    target_lead = None
    for lead in leads:
        if lead['id'] == lead_id:
            target_lead = lead
            break
            
    if not target_lead:
        return jsonify({"status": "error", "message": "Lead not found"}), 404
        
    students = load_data(STUDENTS_FILE)
    # Check if already converted
    for s in students:
        if s.get('original_lead_id') == lead_id:
            return jsonify({"status": "success", "message": "Lead is already converted to student."})
            
    new_student = dict(target_lead)
    new_student['student_id'] = len(students) + 1
    new_student['original_lead_id'] = lead_id
    new_student['converted_at'] = datetime.now().strftime("%d %b %Y, %I:%M %p")
    
    students.append(new_student)
    save_data(STUDENTS_FILE, students)
    
    # Update lead status
    target_lead['status'] = 'Converted to Student'
    save_data(DATA_FILE, leads)
    
    log_activity("Student Converted", f"Converted lead #{lead_id} ({target_lead['student_name']}) into a registered Student.")
    return jsonify({"status": "success", "message": "Lead successfully converted to Student!"})


@app.route('/api/update-student', methods=['POST'])
def update_student():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        form_data = request.form.to_dict()
        student_id = int(form_data.get('student_id'))
        
        students = load_data(STUDENTS_FILE)
        target_student = None
        for s in students:
            if s.get('student_id') == student_id:
                target_student = s
                break
                
        if not target_student:
            return jsonify({"status": "error", "message": "Student not found"}), 404
            
        target_student['student_name'] = form_data.get('student_name', target_student.get('student_name'))
        target_student['father_name'] = form_data.get('father_name', target_student.get('father_name', ''))
        target_student['contact_number'] = form_data.get('contact_number', target_student.get('contact_number'))
        target_student['alternate_number'] = form_data.get('alternate_number', target_student.get('alternate_number', ''))
        target_student['student_email'] = form_data.get('student_email', target_student.get('student_email'))
        target_student['current_education_level'] = form_data.get('current_education_level', target_student.get('current_education_level', ''))
        target_student['qualification'] = form_data.get('qualification', target_student.get('qualification', ''))
        target_student['percentage_10th'] = form_data.get('percentage_10th', target_student.get('percentage_10th', ''))
        target_student['percentage_12th'] = form_data.get('percentage_12th', target_student.get('percentage_12th', ''))
        target_student['course_details'] = form_data.get('course_details', target_student.get('course_details', ''))
        target_student['budget'] = form_data.get('budget', target_student.get('budget', ''))
        target_student['hostel_preference'] = form_data.get('hostel_preference', target_student.get('hostel_preference', ''))
        target_student['admission_preference'] = form_data.get('admission_preference', target_student.get('admission_preference', ''))
        target_student['assigned_college'] = form_data.get('assigned_college', target_student.get('assigned_college', ''))
        target_student['state'] = form_data.get('state', target_student.get('state', ''))
        target_student['city'] = form_data.get('city', target_student.get('city', ''))
        
        if 'id_document' in request.files:
            file = request.files['id_document']
            if file and file.filename != '':
                doc_path = upload_file_to_github(file, target_student.get('student_name', 'Student'), file.filename)
                if doc_path:
                    target_student['id_document'] = doc_path
                    
        save_data(STUDENTS_FILE, students)
        log_activity("Student Updated", f"Updated student profile for #{student_id} ({target_student['student_name']})")
        return jsonify({"status": "success", "message": "Student updated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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
    log_activity("Delete Logs", f"Admin deleted login logs by filter")
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
    log_activity("Delete Work History", f"Admin deleted work history records")
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
    log_activity("Delete Leads", f"Admin moved lead records to trash by filter")
    return jsonify({"status": "success", "message": "Selected lead records moved to trash successfully."})


# --- TRASH BIN SPECIFIC DELETE & DOWNLOAD ENDPOINTS ---

@app.route('/api/trash/delete-permanent', methods=['POST'])
def trash_permanent_delete():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    data = request.json or {}
    lead_ids = data.get('lead_ids', [])
    
    leads = load_data(DATA_FILE)
    new_leads = [l for l in leads if l.get('id') not in lead_ids]
    save_data(DATA_FILE, new_leads)
    log_activity("Permanent Delete", f"Admin permanently deleted {len(lead_ids)} records from Trash Bin.")
    return jsonify({"status": "success", "message": "Selected records permanently deleted from Trash Bin."})


@app.route('/api/trash/download', methods=['POST'])
def trash_download():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    lead_ids = data.get('lead_ids', [])
    
    leads = load_data(DATA_FILE)
    selected_trash = [l for l in leads if l.get('is_deleted') and l.get('id') in lead_ids]
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Trash Bin Export Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; color: #1e293b; padding: 25px; }}
            h1 {{ color: #2563eb; font-size: 22px; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }}
            td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - Trash Bin Export Report</h1>
        <div style="font-size: 12px; color: #64748b; margin-bottom: 15px;">Generated on: {datetime.now().strftime('%d %b %Y, %I:%M %p')}</div>
        <table>
            <thead>
                <tr><th>ID</th><th>Student Name</th><th>Contact</th><th>Email</th><th>Created Date</th></tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>#{l.get('id')}</td><td><strong>{l.get('student_name')}</strong></td><td>{l.get('contact_number')}</td><td>{l.get('student_email')}</td><td>{l.get('created_at')}</td></tr>" for l in selected_trash])}
            </tbody>
        </table>
        <script>window.onload = function() {{ window.print(); }}</script>
    </body>
    </html>
    """
    resp = make_response(html)
    resp.headers["Content-Disposition"] = "inline; filename=Trash_Bin_Report.html"
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


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


# --- PDF EXPORT ENDPOINTS ---

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
        <div class="filter-info">Generated on: {datetime.now().strftime('%d %b %Y, %I:%M %p')}</div>
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
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }}
            td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - Work History Report</h1>
        <table>
            <thead>
                <tr><th>ID</th><th>User</th><th>Role</th><th>Date / Time</th><th>Action Type</th><th>Details</th></tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>#{h.get('id')}</td><td>{h.get('username','Admin')}</td><td>{h.get('role','Admin')}</td><td>{h.get('date')} {h.get('time')}</td><td><strong>{h.get('action_type')}</strong></td><td>{h.get('details')}</td></tr>" for h in filtered])}
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
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }}
            td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - College Directory Report</h1>
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
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Student Leads Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; color: #1e293b; padding: 25px; }}
            h1 {{ color: #2563eb; font-size: 22px; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }}
            td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - Student Leads Report</h1>
        <table>
            <thead>
                <tr><th>ID</th><th>Student Name</th><th>Contact</th><th>Email</th><th>College</th><th>Status</th></tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>#{l.get('id')}</td><td><strong>{l.get('student_name')}</strong></td><td>{l.get('contact_number')}</td><td>{l.get('student_email')}</td><td>{l.get('assigned_college','None')}</td><td>{l.get('status')}</td></tr>" for l in leads])}
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
    data = request.json or {}
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
    data = request.json or {}
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
    data = request.json or {}
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
    data = request.json or {}
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
    data = request.json or {}
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
    data = request.json or {}
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
        .nav-menu { margin-top: 15px; display: flex; flex-direction: column; gap: 5px; list-style: none; overflow-y: auto; max-height: calc(100vh - 160px); }
        .nav-item button { width: 100%; display: flex; align-items: center; gap: 12px; padding: 11px 14px; border-radius: 10px; color: #94a3b8; background: none; border: none; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.2s; text-align: left; }
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
        .convert-btn { background: #dcfce7; color: #15803d; border: none; cursor: pointer; padding: 5px 10px; border-radius: 6px; font-weight: 600; font-size: 11.5px; }
        .trash-btn { background: #fee2e2; color: #dc2626; border: none; cursor: pointer; }

        .chart-container { position: relative; height: 210px; display: flex; justify-content: center; }
        .tab-section { display: none; }
        .tab-section.active { display: block; }

        .modal-overlay { display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; backdrop-filter: blur(4px); padding: 15px; }
        .modal-content { background: white; padding: 25px; border-radius: 16px; max-width: 600px; width: 100%; text-align: left; position: relative; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); animation: modalPopup 0.3s cubic-bezier(0.16, 1, 0.3, 1); max-height: 95vh; overflow-y: auto; }
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
            .modal-content { max-width: 95vw !important; padding: 18px; margin: 10px; }
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
                <li class="nav-item" onclick="switchTab('students-tab', this)"><button><i class="fa-solid fa-user-graduate"></i> Students Tab</button></li>
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
                <input type="text" id="globalSearch" onkeyup="filterLeadsTable()" placeholder="Search CRM records...">
            </div>
        </header>

        <div class="content-area">
            <!-- DASHBOARD TAB -->
            <div id="dashboard-tab" class="tab-section active">
                <div class="hero-banner" style="margin-bottom: 25px;">
                    <div class="hero-text">
                        <h1 id="timeGreeting">Good Morning {{ username | title }}</h1>
                        <p>Welcome to your CounselScope CRM. Track dynamic leads, converted students, follow-up recalls, and admissions in real-time.</p>
                    </div>
                </div>

                <div class="metrics-grid" style="margin-bottom: 25px;">
                    <div class="metric-card"><div class="m-icon blue"><i class="fa-solid fa-users"></i></div><div class="m-info"><h3 id="statTotal">0</h3><p>Total Leads</p></div></div>
                    <div class="metric-card"><div class="m-icon green"><i class="fa-solid fa-user-graduate"></i></div><div class="m-info"><h3 id="statStudents">0</h3><p>Registered Students</p></div></div>
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

            <!-- ALL LEADS TAB -->
            <div id="leads-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <h3><i class="fa-solid fa-users"></i> All Leads Management</h3>
                    </div>
                    <div style="background: #f8fafc; padding: 15px; border-radius: 10px; border: 1px solid var(--border-color); display: flex; gap: 15px; flex-wrap: wrap; align-items: flex-end;">
                        <button onclick="downloadLeadsPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Download Leads PDF</button>
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
                                    <th>Assigned College</th>
                                    <th>Status</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody id="allLeadsTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- NEW STUDENTS TAB -->
            <div id="students-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <h3><i class="fa-solid fa-user-graduate"></i> Registered Students Tab</h3>
                        <p style="font-size: 13px; color: var(--text-muted);">Students who have successfully transitioned from leads.</p>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header"><h3>Students Directory</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>#ID</th>
                                    <th>Student Name</th>
                                    <th>Contact</th>
                                    <th>Email</th>
                                    <th>Assigned College</th>
                                    <th>Course & Qualification</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody id="studentsTbody">
                                <tr><td colspan="7" style="text-align:center; color:#94a3b8;">No registered students yet. Convert leads from All Leads tab.</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- WORK HISTORY TAB -->
            <div id="history-tab" class="tab-section">
                <div class="card">
                    <div class="card-header">
                        <h3><i class="fa-solid fa-clock-rotate-left"></i> Synchronized Activity Logs & Work History</h3>
                        <button onclick="downloadHistoryPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Download PDF Report</button>
                    </div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th>User</th>
                                    <th>Role</th>
                                    <th>Date & Time</th>
                                    <th>Activity Type</th>
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

            <!-- TRASH BIN TAB (WITH PERMANENT DELETE AND DOWNLOAD CHECKBOXES) -->
            <div id="trash-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header"><h3 style="color: #ef4444;"><i class="fa-solid fa-trash-can"></i> Trash Bin Management</h3></div>
                    <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
                        {% if role == 'Admin' %}
                        <button onclick="trashSelectedDelete()" style="background: #ef4444; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-trash"></i> Permanently Delete Selected</button>
                        {% endif %}
                        <button onclick="trashSelectedDownload()" style="background: #2563eb; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-download"></i> Download Selected Records</button>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header"><h3>Deleted Records</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    <th><input type="checkbox" id="selectAllTrash" onclick="toggleSelectAllTrash(this)"></th>
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

            <!-- SETTINGS & LOGS TAB -->
            <div id="settings-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header"><h3><i class="fa-solid fa-gear"></i> System Settings & Login Activity Logs</h3></div>
                    
                    {% if role == 'Admin' %}
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
            <h3 style="margin-bottom: 15px; color: #1e293b; font-size: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px;"><i class="fa-solid fa-id-card" style="color:#2563eb; margin-right:8px;"></i> Student Document & Details</h3>
            <div id="modalBodyContainer"></div>
            <div style="margin-top: 20px; text-align: right;">
                <a id="modalDownloadBtn" href="#" class="action-icon-btn doc-btn" style="padding: 10px 18px; text-decoration: none; border-radius: 8px; display: inline-flex; align-items: center; gap: 8px; font-size: 13.5px; font-weight: 600; width: auto; height: auto;" target="_blank"><i class="fa-solid fa-download"></i> Download Document</a>
            </div>
        </div>
    </div>

    <!-- COMPREHENSIVE EDIT LEAD MODAL WITH "ADD COLLEGE" BUTTON -->
    <div id="editModal" class="modal-overlay">
        <div class="modal-content" style="max-width: 680px;">
            <span class="close-modal" onclick="closeEditModal()">&times;</span>
            <h3 style="margin-bottom: 15px; color: #1e293b; font-size: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px;"><i class="fa-solid fa-pen-to-square" style="color:#d97706; margin-right:8px;"></i> Edit Complete Student & Lead Information</h3>
            <form id="editLeadForm" onsubmit="submitEditLead(event)">
                <input type="hidden" id="edit_lead_id">
                
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Student Name *</label>
                        <input type="text" id="edit_student_name" name="student_name" class="form-control" required>
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Father's Name</label>
                        <input type="text" id="edit_father_name" name="father_name" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Contact Number *</label>
                        <input type="tel" id="edit_contact_number" name="contact_number" class="form-control" required>
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Alternate Contact Number</label>
                        <input type="tel" id="edit_alternate_number" name="alternate_number" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Student Email ID *</label>
                        <input type="email" id="edit_student_email" name="student_email" class="form-control" required>
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Current Education Level</label>
                        <input type="text" id="edit_current_education_level" name="current_education_level" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Qualification</label>
                        <input type="text" id="edit_qualification" name="qualification" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">10th Percentage</label>
                        <input type="text" id="edit_percentage_10th" name="percentage_10th" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">12th Percentage</label>
                        <input type="text" id="edit_percentage_12th" name="percentage_12th" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Course Details</label>
                        <input type="text" id="edit_course_details" name="course_details" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Budget Information</label>
                        <input type="text" id="edit_budget" name="budget" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Hostel Preference</label>
                        <input type="text" id="edit_hostel_preference" name="hostel_preference" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">Admission Preference</label>
                        <input type="text" id="edit_admission_preference" name="admission_preference" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600; color:#475569;">State & City</label>
                        <div style="display:flex; gap:6px;">
                            <input type="text" id="edit_state" name="state" placeholder="State" class="form-control">
                            <input type="text" id="edit_city" name="city" placeholder="City" class="form-control">
                        </div>
                    </div>
                </div>

                <!-- ADD COLLEGE BUTTON & DROPDOWN INSIDE EDIT FORM -->
                <div style="background: #f8fafc; padding: 14px; border-radius: 10px; border: 1px solid #cbd5e1; margin-top: 15px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <label style="font-size: 13px; font-weight: 700; color: #1e293b; margin:0;"><i class="fa-solid fa-building-columns" style="color:#2563eb; margin-right:5px;"></i> College Assignment</label>
                        <button type="button" onclick="openCollegeSelector()" style="background: #16a34a; color: white; border: none; padding: 6px 12px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 12px;"><i class="fa-solid fa-plus"></i> Add College</button>
                    </div>
                    <select id="edit_assigned_college" name="assigned_college" class="form-control" style="margin:0;">
                        <option value="">-- No College Assigned --</option>
                    </select>
                </div>

                <div style="margin-top: 15px;">
                    <label style="font-size:12px; font-weight:600; color:#475569;">Update / Replace Document</label>
                    <input type="file" id="edit_id_document" name="id_document" class="form-control" accept="image/*,.pdf">
                    <div style="margin-top:5px; display:flex; align-items:center; gap:8px;">
                        <input type="checkbox" id="edit_delete_doc" style="width:16px; height:16px;">
                        <label for="edit_delete_doc" style="font-size:12.5px; color:#ef4444; font-weight:600; cursor:pointer;">Delete existing document</label>
                    </div>
                </div>

                <div style="margin-top: 20px; text-align: right;">
                    <button type="submit" id="saveEditBtn" style="background:#2563eb; color:white; border:none; padding:10px 22px; border-radius:8px; font-weight:600; cursor:pointer;">Save Complete Changes</button>
                </div>
            </form>
        </div>
    </div>

    <!-- STUDENT EDIT MODAL -->
    <div id="studentEditModal" class="modal-overlay">
        <div class="modal-content" style="max-width: 600px;">
            <span class="close-modal" onclick="closeStudentEditModal()">&times;</span>
            <h3 style="margin-bottom: 15px; color: #1e293b; font-size: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px;"><i class="fa-solid fa-user-graduate" style="color:#16a34a; margin-right:8px;"></i> Edit Student Profile</h3>
            <form id="editStudentForm" onsubmit="submitEditStudent(event)">
                <input type="hidden" id="student_edit_id">
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                    <div>
                        <label style="font-size:12px; font-weight:600;">Student Name *</label>
                        <input type="text" id="s_edit_name" name="student_name" class="form-control" required>
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600;">Contact Number *</label>
                        <input type="tel" id="s_edit_contact" name="contact_number" class="form-control" required>
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600;">Email ID *</label>
                        <input type="email" id="s_edit_email" name="student_email" class="form-control" required>
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600;">Course Details</label>
                        <input type="text" id="s_edit_course" name="course_details" class="form-control">
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600;">Assigned College</label>
                        <select id="s_edit_college" name="assigned_college" class="form-control">
                            <option value="">-- Select College --</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size:12px; font-weight:600;">Budget</label>
                        <input type="text" id="s_edit_budget" name="budget" class="form-control">
                    </div>
                </div>
                <div style="margin-top: 20px; text-align: right;">
                    <button type="submit" style="background:#16a34a; color:white; border:none; padding:10px 20px; border-radius:8px; font-weight:600; cursor:pointer;">Update Student</button>
                </div>
            </form>
        </div>
    </div>

    <script>
        let rawLeadsData = [];
        let rawStudentsData = [];
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
            if(tabId === 'history-tab') fetchWorkHistory();
            if(tabId === 'students-tab') fetchStudentsData();
            if(tabId === 'settings-tab') fetchSettingsLogs();
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

        async function fetchStudentsData() {
            try {
                const res = await fetch('/api/get-students');
                if(res.ok) {
                    rawStudentsData = await res.json();
                    renderStudentsUI(rawStudentsData);
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

        async function fetchWorkHistory() {
            const res = await fetch('/api/get-history');
            if(res.ok) {
                const history = await res.json();
                const tbody = document.getElementById('historyTbody');
                tbody.innerHTML = '';
                if(history.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:#94a3b8;">No activity logged yet.</td></tr>`;
                    return;
                }
                history.reverse().forEach(item => {
                    tbody.innerHTML += `
                        <tr>
                            <td><strong>${item.username || 'Admin'}</strong></td>
                            <td><span class="badge-status badge-followup">${item.role || 'Admin'}</span></td>
                            <td><strong style="color:#2563eb;">${item.date} ${item.time}</strong></td>
                            <td><span class="badge-status badge-new">${item.action_type}</span></td>
                            <td>${item.details}</td>
                        </tr>
                    `;
                });
            }
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
                
                // Populate college select dropdowns
                populateCollegeDropdowns();
            }
        }

        function populateCollegeDropdowns() {
            const selects = ['edit_assigned_college', 's_edit_college'];
            selects.forEach(selId => {
                const sel = document.getElementById(selId);
                if(sel) {
                    const currentVal = sel.value;
                    sel.innerHTML = `<option value="">-- Select College --</option>`;
                    collegesData.forEach(c => {
                        sel.innerHTML += `<option value="${c.college_name}">${c.college_name} (${c.location})</option>`;
                    });
                    sel.value = currentVal;
                }
            });
        }

        function openCollegeSelector() {
            switchTab('colleges-tab', document.querySelector('.nav-menu li:nth-child(4) button').parentElement);
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

        function renderUI(dataList) {
            const activeLeads = dataList.filter(l => !l.is_deleted);
            const trashLeads = dataList.filter(l => l.is_deleted);
            
            document.getElementById('statTotal').innerText = activeLeads.length;
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
                            <td><a href="tel:${lead.contact_number}" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
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
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(lead)})' title="View Details"><i class="fa-solid fa-eye"></i></button>`;
                recentTbody.innerHTML += `
                    <tr>
                        <td><strong>${lead.student_name}</strong></td>
                        <td><a href="tel:${lead.contact_number}" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
                        <td><a href="mailto:${lead.student_email}" class="action-icon-btn mail-btn"><i class="fa-solid fa-envelope"></i></a> ${lead.student_email}</td>
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
            populateTrashTable(trashLeads);
            updatePieChart(activeLeads);
            fetchStudentsData();
        }

        function renderStudentsUI(students) {
            document.getElementById('statStudents').innerText = students.length;
            const tbody = document.getElementById('studentsTbody');
            tbody.innerHTML = '';
            if(students.length === 0) {
                tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:#94a3b8;">No registered students yet. Convert leads from All Leads tab.</td></tr>`;
                return;
            }
            students.slice().reverse().forEach(st => {
                tbody.innerHTML += `
                    <tr>
                        <td>#${st.student_id}</td>
                        <td><strong>${st.student_name}</strong></td>
                        <td>${st.contact_number}</td>
                        <td>${st.student_email}</td>
                        <td><span class="badge-status badge-closed">${st.assigned_college || 'Not Assigned'}</span></td>
                        <td>${st.course_details || st.qualification || 'N/A'}</td>
                        <td>
                            <button class="action-icon-btn edit-btn" onclick='openStudentEditModal(${JSON.stringify(st)})' title="Edit Student"><i class="fa-solid fa-pen"></i></button>
                        </td>
                    </tr>
                `;
            });
        }

        function populateAllLeadsTable(leads) {
            const allTbody = document.getElementById('allLeadsTbody');
            allTbody.innerHTML = '';
            leads.slice().reverse().forEach(lead => {
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(lead)})' title="View Details"><i class="fa-solid fa-eye"></i></button>`;
                const convertBtn = `<button class="convert-btn" onclick="convertToStudent(${lead.id})"><i class="fa-solid fa-user-check"></i> Convert</button>`;
                allTbody.innerHTML += `
                    <tr>
                        <td>#${lead.id}</td>
                        <td><strong>${lead.student_name}</strong></td>
                        <td><a href="tel:${lead.contact_number}" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
                        <td><a href="mailto:${lead.student_email}" class="action-icon-btn mail-btn"><i class="fa-solid fa-envelope"></i></a> ${lead.student_email}</td>
                        <td><span style="font-size:12px; font-weight:600; color:#0284c7;">${lead.assigned_college || 'None'}</span></td>
                        <td>
                            <select class="status-select" onchange="updateStatus(${lead.id}, this.value)">
                                <option value="New Lead" ${lead.status==='New Lead'?'selected':''}>New Lead</option>
                                <option value="Contacted" ${lead.status==='Contacted'?'selected':''}>Contacted</option>
                                <option value="Follow Up" ${lead.status==='Follow Up'?'selected':''}>Follow Up</option>
                                <option value="Closed" ${lead.status==='Closed'?'selected':''}>Closed</option>
                                <option value="Converted to Student" ${lead.status==='Converted to Student'?'selected':''}>Converted to Student</option>
                            </select>
                        </td>
                        <td>
                            ${convertBtn}
                            <button class="action-icon-btn edit-btn" onclick='openEditModal(${JSON.stringify(lead)})' title="Edit All Fields"><i class="fa-solid fa-pen"></i></button>
                            <button class="action-icon-btn trash-btn" onclick="deleteLead(${lead.id})" title="Delete Lead"><i class="fa-solid fa-trash-can"></i></button>
                        </td>
                    </tr>
                `;
            });
        }

        function populateTrashTable(trashLeads) {
            const trashTbody = document.getElementById('trashTbody');
            trashTbody.innerHTML = '';
            if(trashLeads.length === 0) {
                trashTbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#94a3b8;">Trash bin is empty.</td></tr>`;
                return;
            }
            trashLeads.forEach(lead => {
                trashTbody.innerHTML += `
                    <tr>
                        <td><input type="checkbox" class="trash-checkbox" value="${lead.id}"></td>
                        <td>#${lead.id}</td>
                        <td><strong>${lead.student_name}</strong></td>
                        <td>${lead.contact_number}</td>
                        <td>${lead.student_email}</td>
                        <td><button onclick="restoreLead(${lead.id})" style="background:#16a34a; color:white; border:none; padding:5px 10px; border-radius:6px; cursor:pointer; font-weight:600;">Restore</button></td>
                    </tr>
                `;
            });
        }

        function toggleSelectAllTrash(master) {
            document.querySelectorAll('.trash-checkbox').forEach(cb => cb.checked = master.checked);
        }

        async function trashSelectedDelete() {
            const selectedIds = Array.from(document.querySelectorAll('.trash-checkbox:checked')).map(cb => parseInt(cb.value));
            if(selectedIds.length === 0) {
                alert('Please select at least one record from Trash Bin.');
                return;
            }
            if(confirm(`Are you sure you want to permanently delete ${selectedIds.length} selected records? This cannot be undone.`)) {
                const res = await fetch('/api/trash/delete-permanent', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({lead_ids: selectedIds})
                });
                if(res.ok) {
                    alert('Selected records permanently deleted.');
                    fetchLeadsData();
                } else {
                    alert('Unauthorized or error.');
                }
            }
        }

        function trashSelectedDownload() {
            const selectedIds = Array.from(document.querySelectorAll('.trash-checkbox:checked')).map(cb => parseInt(cb.value));
            if(selectedIds.length === 0) {
                alert('Please select at least one record from Trash Bin to download.');
                return;
            }
            fetch('/api/trash/download', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({lead_ids: selectedIds})
            }).then(res => res.text()).then(html => {
                const win = window.open('', '_blank');
                win.document.write(html);
                win.document.close();
            });
        }

        async function convertToStudent(leadId) {
            if(confirm("Convert this lead into a registered student?")) {
                const res = await fetch('/api/convert-to-student', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({lead_id: leadId})
                });
                const result = await res.json();
                if(res.ok) {
                    alert(result.message);
                    fetchLeadsData();
                } else {
                    alert('Error: ' + result.message);
                }
            }
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
                docPreviewHtml = `<div style="margin-top: 15px;"><p style="color:#2563eb; font-size:13px;"><i class="fa-solid fa-file-pdf"></i> Document attached. Click download.</p></div>`;
            } else {
                downloadBtn.style.display = 'none';
                docPreviewHtml = `<p style="color:#b45309; font-size:13px;">No document attached.</p>`;
            }

            container.innerHTML = `
                <div style="background: #f8fafc; padding: 16px; border-radius: 10px; font-size: 13.5px; line-height: 1.6;">
                    <p><strong>Student Name:</strong> ${lead.student_name}</p>
                    <p><strong>Father's Name:</strong> ${lead.father_name || 'N/A'}</p>
                    <p><strong>Contact:</strong> ${lead.contact_number}</p>
                    <p><strong>Email:</strong> ${lead.student_email}</p>
                    <p><strong>Assigned College:</strong> ${lead.assigned_college || 'None'}</p>
                    <p><strong>Qualification:</strong> ${lead.qualification || 'N/A'}</p>
                    <p><strong>10th %:</strong> ${lead.percentage_10th || 'N/A'} | <strong>12th %:</strong> ${lead.percentage_12th || 'N/A'}</p>
                    <p><strong>Budget:</strong> ${lead.budget || 'N/A'}</p>
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
            document.getElementById('edit_current_education_level').value = lead.current_education_level || '';
            document.getElementById('edit_qualification').value = lead.qualification || '';
            document.getElementById('edit_percentage_10th').value = lead.percentage_10th || '';
            document.getElementById('edit_percentage_12th').value = lead.percentage_12th || '';
            document.getElementById('edit_course_details').value = lead.course_details || '';
            document.getElementById('edit_budget').value = lead.budget || '';
            document.getElementById('edit_hostel_preference').value = lead.hostel_preference || '';
            document.getElementById('edit_admission_preference').value = lead.admission_preference || '';
            document.getElementById('edit_assigned_college').value = lead.assigned_college || '';
            document.getElementById('edit_state').value = lead.state || '';
            document.getElementById('edit_city').value = lead.city || '';
            document.getElementById('edit_delete_doc').checked = false;
            
            document.getElementById('editModal').style.display = 'flex';
        }
        function closeEditModal() { document.getElementById('editModal').style.display = 'none'; }

        async function submitEditLead(e) {
            e.preventDefault();
            const formData = new FormData();
            formData.append('lead_id', document.getElementById('edit_lead_id').value);
            formData.append('student_name', document.getElementById('edit_student_name').value);
            formData.append('father_name', document.getElementById('edit_father_name').value);
            formData.append('contact_number', document.getElementById('edit_contact_number').value);
            formData.append('alternate_number', document.getElementById('edit_alternate_number').value);
            formData.append('student_email', document.getElementById('edit_student_email').value);
            formData.append('current_education_level', document.getElementById('edit_current_education_level').value);
            formData.append('qualification', document.getElementById('edit_qualification').value);
            formData.append('percentage_10th', document.getElementById('edit_percentage_10th').value);
            formData.append('percentage_12th', document.getElementById('edit_percentage_12th').value);
            formData.append('course_details', document.getElementById('edit_course_details').value);
            formData.append('budget', document.getElementById('edit_budget').value);
            formData.append('hostel_preference', document.getElementById('edit_hostel_preference').value);
            formData.append('admission_preference', document.getElementById('edit_admission_preference').value);
            formData.append('assigned_college', document.getElementById('edit_assigned_college').value);
            formData.append('state', document.getElementById('edit_state').value);
            formData.append('city', document.getElementById('edit_city').value);
            formData.append('delete_doc', document.getElementById('edit_delete_doc').checked);

            const fileField = document.getElementById('edit_id_document');
            if (fileField.files.length > 0) {
                formData.append('id_document', fileField.files[0]);
            }

            const res = await fetch('/api/update-lead', { method: 'POST', body: formData });
            if(res.ok) {
                alert('Lead updated successfully!');
                closeEditModal();
                fetchLeadsData();
            } else {
                alert('Error updating lead.');
            }
        }

        function openStudentEditModal(st) {
            document.getElementById('student_edit_id').value = st.student_id;
            document.getElementById('s_edit_name').value = st.student_name || '';
            document.getElementById('s_edit_contact').value = st.contact_number || '';
            document.getElementById('s_edit_email').value = st.student_email || '';
            document.getElementById('s_edit_course').value = st.course_details || '';
            document.getElementById('s_edit_college').value = st.assigned_college || '';
            document.getElementById('s_edit_budget').value = st.budget || '';
            document.getElementById('studentEditModal').style.display = 'flex';
        }
        function closeStudentEditModal() { document.getElementById('studentEditModal').style.display = 'none'; }

        async function submitEditStudent(e) {
            e.preventDefault();
            const formData = new FormData();
            formData.append('student_id', document.getElementById('student_edit_id').value);
            formData.append('student_name', document.getElementById('s_edit_name').value);
            formData.append('contact_number', document.getElementById('s_edit_contact').value);
            formData.append('student_email', document.getElementById('s_edit_email').value);
            formData.append('course_details', document.getElementById('s_edit_course').value);
            formData.append('assigned_college', document.getElementById('s_edit_college').value);
            formData.append('budget', document.getElementById('s_edit_budget').value);

            const res = await fetch('/api/update-student', { method: 'POST', body: formData });
            if(res.ok) {
                alert('Student profile updated successfully!');
                closeStudentEditModal();
                fetchStudentsData();
            } else {
                alert('Error updating student.');
            }
        }

        function downloadLeadsPDF() { window.open('/api/export-leads-pdf', '_blank'); }
        function downloadHistoryPDF() { window.open('/api/export-history-pdf', '_blank'); }

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

        fetchLeadsData();
        fetchColleges();
        setInterval(fetchLeadsData, 5000);
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
