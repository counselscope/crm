import os
import json
import csv
import io
import base64
import uuid
import requests
import mimetypes
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, make_response, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# Multi-sheet Excel support via openpyxl
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

app = Flask(__name__)
app.secret_key = "counselscope_world_class_crm_2026_secret"
CORS(app)

LOGIN_LOGS_FILE = "login_logs.json"
DATA_FILE = "leads.json"
COLLEGES_FILE = "colleges.json"
HISTORY_FILE = "work_history.json"
USERS_FILE = "users.json"
STUDENTS_FILE = "students.json"
TRASH_FILE = "trash.json"

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
    
    if GITHUB_TOKEN and GITHUB_REPO and filename in [DATA_FILE, COLLEGES_FILE, HISTORY_FILE, LOGIN_LOGS_FILE, USERS_FILE, STUDENTS_FILE, TRASH_FILE]:
        commit_json_to_github(filename)


def _trash_category_for_file(filename):
    return {DATA_FILE:"Leads", STUDENTS_FILE:"Students", COLLEGES_FILE:"Colleges",
            HISTORY_FILE:"Work History", LOGIN_LOGS_FILE:"Logs"}.get(filename, "Other")


def _archive_record(filename, record, record_id=None, category=None, extra=None):
    if not isinstance(record, dict):
        return None
    trash = load_data(TRASH_FILE)
    source_id = record_id if record_id is not None else record.get("student_id" if filename == STUDENTS_FILE else "id")
    cat = category or _trash_category_for_file(filename)
    existing = next((x for x in trash if x.get("source_file")==filename and
                     str(x.get("source_id"))==str(source_id) and x.get("category")==cat), None)
    if existing:
        return existing
    now=datetime.now()
    item={"trash_id":uuid.uuid4().hex,"category":cat,"source_file":filename,"source_id":source_id,
          "record":record,"deleted_date":now.strftime("%Y-%m-%d"),
          "deleted_at":now.strftime("%d %b %Y, %I:%M %p"),"deleted_timestamp":now.timestamp()}
    if extra: item["extra"]=extra
    trash.append(item); save_data(TRASH_FILE,trash)
    return item


def _restore_trash_item(item):
    source=item.get("source_file"); source_id=item.get("source_id"); record=item.get("record")
    if not isinstance(record,dict): raise ValueError("Trash record snapshot is missing.")
    if source == "student_document":
        extra=item.get("extra") or {}
        if extra.get("parent_type") == "lead":
            leads=load_data(DATA_FILE)
            parent=next((x for x in leads if str(x.get("id"))==str(extra.get("lead_id"))),None)
            if parent:
                field=extra.get("field") or "id_document"
                parent[field]=record.get("stored_name")
                if isinstance(parent.get("form_data"),dict): parent["form_data"][field]=record.get("stored_name")
                save_data(DATA_FILE,leads)
            else:
                trash_records=load_data(TRASH_FILE)
                archived=next((x for x in trash_records if x.get("source_file")==DATA_FILE and
                               str(x.get("source_id"))==str(extra.get("lead_id"))),None)
                if not archived or not isinstance(archived.get("record"),dict):
                    raise ValueError("The associated lead is not available to restore the document.")
                field=extra.get("field") or "id_document"
                archived["record"][field]=record.get("stored_name")
                if isinstance(archived["record"].get("form_data"),dict): archived["record"]["form_data"][field]=record.get("stored_name")
                save_data(TRASH_FILE,trash_records)
        else:
            students=load_data(STUDENTS_FILE)
            student=next((x for x in students if str(x.get("student_id"))==str(extra.get("student_id"))),None)
            target=student
            if target is None:
                trash_records=load_data(TRASH_FILE)
                parent=next((x for x in trash_records if x.get("source_file")==STUDENTS_FILE and
                             str(x.get("source_id"))==str(extra.get("student_id"))),None)
                if parent and isinstance(parent.get("record"),dict): target=parent["record"]
            if target:
                field=extra.get("field")
                if field and extra.get("top_level", True):
                    target[field]=record.get("stored_name")
                if field and extra.get("form_data_ref") and isinstance(target.get("form_data"),dict):
                    target["form_data"][field]=record.get("stored_name")
                attachment=record.get("attachment")
                if attachment:
                    arr=target.setdefault("attachments",[])
                    if not any(isinstance(x,dict) and x.get("stored_name")==attachment.get("stored_name") for x in arr): arr.append(attachment)
                if student is not None: save_data(STUDENTS_FILE,students)
                else: save_data(TRASH_FILE,trash_records)
            else:
                raise ValueError("The associated student is not available to restore the document.")
    elif source in (DATA_FILE,STUDENTS_FILE,COLLEGES_FILE,HISTORY_FILE,LOGIN_LOGS_FILE):
        records=load_data(source); key="student_id" if source==STUDENTS_FILE else "id"
        existing=next((x for x in records if str(x.get(key))==str(source_id)),None)
        restored=dict(record)
        if source==DATA_FILE:
            restored["is_deleted"]=False
            for k in ("deleted_date","deleted_at","deleted_timestamp"): restored.pop(k,None)
        if existing: existing.update(restored)
        else: records.append(restored)
        save_data(source,records)
    else: raise ValueError("Unsupported Trash Bin source.")
    trash=load_data(TRASH_FILE); save_data(TRASH_FILE,[x for x in trash if x.get("trash_id")!=item.get("trash_id")])


def _find_github_document_paths(value):
    found=set()
    if isinstance(value,dict):
        for key,child in value.items():
            if isinstance(child,str) and child.startswith(("student_documents/","student/college/")):
                found.add(child)
            else: found.update(_find_github_document_paths(child))
    elif isinstance(value,list):
        for child in value: found.update(_find_github_document_paths(child))
    return found


def _delete_github_file_if_unreferenced(path, deleted_item):
    if not path or not GITHUB_TOKEN or not GITHUB_REPO:
        return
    # Avoid deleting a file still referenced by another live CRM record.
    for filename in (DATA_FILE,STUDENTS_FILE,COLLEGES_FILE):
        for rec in load_data(filename):
            if filename==deleted_item.get("source_file") and str(rec.get("student_id" if filename==STUDENTS_FILE else "id"))==str(deleted_item.get("source_id")):
                continue
            if path in _find_github_document_paths(rec):
                return
    for archived in load_data(TRASH_FILE):
        if archived.get("trash_id") != deleted_item.get("trash_id") and path in _find_github_document_paths(archived.get("record") or {}):
            return
    url=f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    headers={"Authorization":f"Bearer {GITHUB_TOKEN}","Accept":"application/vnd.github+json"}
    try:
        check=requests.get(url,headers=headers,params={"ref":GITHUB_BRANCH},timeout=20)
        if check.status_code==404: return
        if check.status_code!=200: return
        sha=check.json().get("sha")
        if sha:
            requests.delete(url,headers=headers,json={"message":f"Permanently delete CRM attachment {os.path.basename(path)}",
                              "sha":sha,"branch":GITHUB_BRANCH},timeout=30)
    except Exception as exc:
        app.logger.warning("Unable to permanently remove GitHub attachment %s: %s",path,exc)


def _permanently_delete_trash_item(item):
    source=item.get("source_file")
    snapshot=item.get("record") or {}
    if source=="student_document":
        extra=item.get("extra") or {}; field=extra.get("field")
        if extra.get("parent_type")=="lead":
            parent_id=extra.get("lead_id"); parent_file=DATA_FILE; key="id"
        else:
            parent_id=extra.get("student_id"); parent_file=STUDENTS_FILE; key="student_id"
        live=load_data(parent_file)
        parent=next((x for x in live if str(x.get(key))==str(parent_id)),None)
        if parent:
            if field and parent.get(field)==snapshot.get("stored_name"): parent[field]=None
            if field and isinstance(parent.get("form_data"),dict) and parent["form_data"].get(field)==snapshot.get("stored_name"):
                parent["form_data"][field]=None
            parent["attachments"]=[a for a in parent.get("attachments",[]) if not
                (isinstance(a,dict) and a.get("stored_name")==snapshot.get("stored_name"))]
            save_data(parent_file,live)
        else:
            archived=load_data(TRASH_FILE)
            parent_item=next((x for x in archived if x.get("source_file")==parent_file and str(x.get("source_id"))==str(parent_id)),None)
            if parent_item and isinstance(parent_item.get("record"),dict):
                if field and parent_item["record"].get(field)==snapshot.get("stored_name"): parent_item["record"][field]=None
                if field and isinstance(parent_item["record"].get("form_data"),dict) and parent_item["record"]["form_data"].get(field)==snapshot.get("stored_name"):
                    parent_item["record"]["form_data"][field]=None
                parent_item["record"]["attachments"]=[a for a in parent_item["record"].get("attachments",[]) if not
                    (isinstance(a,dict) and a.get("stored_name")==snapshot.get("stored_name"))]
                save_data(TRASH_FILE,archived)
    for path in _find_github_document_paths(snapshot):
        _delete_github_file_if_unreferenced(path,item)
    if source in (DATA_FILE,STUDENTS_FILE,COLLEGES_FILE,HISTORY_FILE,LOGIN_LOGS_FILE):
        key="student_id" if source==STUDENTS_FILE else "id"
        records=load_data(source)
        save_data(source,[x for x in records if str(x.get(key))!=str(item.get("source_id"))])
    trash=load_data(TRASH_FILE)
    save_data(TRASH_FILE,[x for x in trash if x.get("trash_id")!=item.get("trash_id")])


def _migrate_legacy_deleted_leads():
    for lead in load_data(DATA_FILE):
        if lead.get("is_deleted"):
            _archive_record(DATA_FILE,lead,lead.get("id"),"Leads")

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
        target_filename = f"doc_{int(datetime.now().timestamp())}_{secure_filename(original_filename)}"
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


# College Manager GitHub storage helpers.
# These helpers are intentionally separate from upload_file_to_github(),
# because student documents must keep their existing student_documents/ path.
def college_github_headers(raw=False):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError("GitHub is not configured. Set GITHUB_TOKEN and GITHUB_REPO environment variables.")
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json"
    }


def safe_college_folder_name(college_name):
    name = (college_name or "College").strip()
    safe = "".join(ch if ch.isalnum() or ch in (" ", "_", "-") else "_" for ch in name)
    safe = "_".join(safe.split()).strip("_.-")
    return safe or "College"


def upload_college_content_to_github(repo_path, content, commit_message):
    """Create/update a file in the College Manager's own GitHub folder."""
    headers = college_github_headers()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}"
    check = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=30)
    sha = None
    if check.status_code == 200:
        sha = check.json().get("sha")
    elif check.status_code != 404:
        raise RuntimeError(f"GitHub could not check {repo_path}: {check.status_code} {check.text[:300]}")

    payload = {
        "message": commit_message,
        "content": base64.b64encode(content).decode("utf-8"),
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(url, headers=headers, json=payload, timeout=60)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"GitHub upload failed for {repo_path}: {response.status_code} {response.text[:500]}")
    return repo_path


def save_college_record_to_github(college):
    folder = safe_college_folder_name(college.get("college_name"))
    # Add the record ID only if another college already uses the same folder name.
    all_colleges = load_data(COLLEGES_FILE)
    same_name = [c for c in all_colleges if safe_college_folder_name(c.get("college_name")) == folder]
    if len(same_name) > 1:
        folder = f"{folder}_{college.get('id')}"
    repo_path = f"student/college/{folder}/college.json"
    college["github_record_path"] = repo_path
    payload = json.dumps(college, ensure_ascii=False, indent=4).encode("utf-8")
    upload_college_content_to_github(repo_path, payload, f"Update college record: {college.get('college_name', 'College')}")
    return repo_path


def upload_college_document_to_github(upload, college_name, college_id):
    if not upload or not upload.filename:
        return None
    original_name = secure_filename(upload.filename)
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".pdf"):
        raise ValueError("Only JPG, JPEG, PNG and PDF files are allowed.")
    content = upload.read()
    if not content:
        raise ValueError("The selected college file is empty.")
    # GitHub's Contents API is limited to files up to 1 MB.
    if len(content) > 1_000_000:
        raise ValueError("College files must be 1 MB or smaller for this GitHub upload method.")
    folder = safe_college_folder_name(college_name)
    all_colleges = load_data(COLLEGES_FILE)
    same_name = [c for c in all_colleges if safe_college_folder_name(c.get("college_name")) == folder]
    if any(int(c.get("id", -1)) != int(college_id) for c in same_name):
        folder = f"{folder}_{college_id}"
    stored_name = f"college_{uuid.uuid4().hex}{ext}"
    repo_path = f"student/college/{folder}/{stored_name}"
    upload_college_content_to_github(repo_path, content, f"Upload college document: {college_name}")
    return {
        "stored_name": repo_path,
        "github_path": repo_path,
        "original_name": original_name,
        "extension": ext
    }


def get_college_file_from_github(repo_path):
    headers = college_github_headers()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}"
    response = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"GitHub file retrieval failed: {response.status_code}")
    result = response.json()
    if result.get("encoding") != "base64" or not result.get("content"):
        raise RuntimeError("GitHub did not return the file content in base64 format.")
    return base64.b64decode(result["content"])

# --- API ENDPOINTS ---

@app.route('/api/submit-lead', methods=['POST'])
def submit_lead():
    try:
        flat_form = {}
        for k, v in request.form.lists():
            if len(v) == 1:
                flat_form[k] = v[0]
            else:
                flat_form[k] = v

        student_name = flat_form.get('student_name') or flat_form.get('name') or 'Valued Enquirer'
        contact_number = flat_form.get('contact_number') or flat_form.get('phone') or 'N/A'
        student_email = flat_form.get('student_email') or flat_form.get('email') or 'N/A'

        # Handle every uploaded registration attachment, including optional photo/image fields.
        uploaded_files = {}
        attachment_records = []
        known_file_keys = ['id_document', 'class_10_doc', 'class_12_doc', 'aadhar_doc', 'edu_scorecard', 'passport_photo']
        for f_key, file_list in request.files.lists():
            for file in file_list:
                if file and file.filename:
                    original_name = secure_filename(file.filename)
                    if f_key == 'passport_photo':
                        ext = os.path.splitext(original_name)[1].lower()
                        if ext not in ('.jpg', '.jpeg', '.png'):
                            return jsonify({"status":"error","message":"Passport photograph must be JPG, JPEG or PNG."}), 400
                        content = file.read()
                        if not content or len(content) > 1_000_000:
                            return jsonify({"status":"error","message":"Passport photograph must be non-empty and no larger than 1 MB."}), 400
                        file.stream.seek(0)
                    stored_path = upload_file_to_github(file, student_name, file.filename)
                    if f_key not in uploaded_files or not uploaded_files.get(f_key):
                        uploaded_files[f_key] = stored_path
                    if stored_path:
                        attachment_records.append({
                            'field': f_key,
                            'stored_name': stored_path,
                            'original_name': original_name,
                            'extension': os.path.splitext(original_name)[1].lower()
                        })
        for f_key in known_file_keys:
            uploaded_files.setdefault(f_key, None)

        leads = load_data(DATA_FILE)
        now = datetime.now()

        new_lead = {
            "id": len(leads) + 1,
            "student_name": student_name,
            "father_name": flat_form.get('father_name', ''),
            "contact_number": contact_number,
            "alternate_number": flat_form.get('alternate_number', ''),
            "student_email": student_email,
            "current_education_level": flat_form.get('current_education_level', ''),
            "qualification": flat_form.get('qualification', ''),
            "percentage_10th": flat_form.get('percentage_10th', ''),
            "percentage_12th": flat_form.get('percentage_12th', ''),
            "edu_percentage": flat_form.get('edu_percentage', ''),
             "course_interest": flat_form.get('course_interest') or flat_form.get('Which course are you interested in?') or flat_form.get('which_course') or flat_form.get('course', ''),
            "other_course": flat_form.get('other_course', ''),
             "course_details": flat_form.get('course_details', '') or flat_form.get('course_interest') or flat_form.get('Which course are you interested in?') or flat_form.get('which_course') or flat_form.get('course', ''),
            "hear_about": flat_form.get('hear_about', ''),
            "other_source": flat_form.get('other_source', ''),
            "preferred_time": flat_form.get('preferred_time', ''),
            "help_with": flat_form.get('help_with', ''),
            "annual_budget": flat_form.get('annual_budget', '') or flat_form.get('budget', ''),
            "budget": flat_form.get('annual_budget', '') or flat_form.get('budget', ''),
            "fee_payment_option": flat_form.get('fee_payment_option', ''),
            "payment_mode": flat_form.get('payment_mode', ''),
            "installment_duration": flat_form.get('installment_duration', '') if flat_form.get('payment_mode') == 'Installment' else '',
            "loan_assistance": flat_form.get('loan_assistance', ''),
            "hostel_required": flat_form.get('hostel_required', '') or flat_form.get('hostel_preference', ''),
            "hostel_preference": flat_form.get('hostel_required', '') or flat_form.get('hostel_preference', ''),
            "contacted_college": flat_form.get('contacted_college', ''),
            "col_name_1": flat_form.get('col_name_1', ''),
            "col_state_1": flat_form.get('col_state_1', ''),
            "col_name_2": flat_form.get('col_name_2', ''),
            "col_state_2": flat_form.get('col_state_2', ''),
            "col_name_3": flat_form.get('col_name_3', ''),
            "col_state_3": flat_form.get('col_state_3', ''),
            "admission_preference": flat_form.get('admission_preference', ''),
            "assigned_college": flat_form.get('assigned_college', ''),
            "state": flat_form.get('state', ''),
            "city": flat_form.get('city', ''),
            "id_document": uploaded_files.get('id_document'),
            "class_10_doc": uploaded_files.get('class_10_doc'),
            "class_12_doc": uploaded_files.get('class_12_doc'),
            "aadhar_doc": uploaded_files.get('aadhar_doc'),
            "edu_scorecard": uploaded_files.get('edu_scorecard'),
            "attachments": attachment_records,
            "status": "New Lead",
            "score": 80 if contact_number != 'N/A' else 50,
            "notes": "Enquiry received via dynamic HTML form submission.",
            "is_deleted": False,
            "created_date": now.strftime("%Y-%m-%d"),
            "created_at": now.strftime("%d %b %Y, %I:%M %p"),
            "created_timestamp": now.timestamp(),
            "form_data": flat_form
        }
        
        for upload_key, stored_path in uploaded_files.items():
            if upload_key not in new_lead and stored_path:
                new_lead[upload_key] = stored_path
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

        target_lead['student_name'] = form_data.get('student_name', target_lead.get('student_name'))
        target_lead['father_name'] = form_data.get('father_name', target_lead.get('father_name', ''))
        target_lead['contact_number'] = form_data.get('contact_number', target_lead.get('contact_number'))
        target_lead['alternate_number'] = form_data.get('alternate_number', target_lead.get('alternate_number', ''))
        target_lead['student_email'] = form_data.get('student_email', target_lead.get('student_email'))
        target_lead['current_education_level'] = form_data.get('current_education_level', target_lead.get('current_education_level', ''))
        target_lead['qualification'] = form_data.get('qualification', target_lead.get('qualification', ''))
        target_lead['percentage_10th'] = form_data.get('percentage_10th', target_lead.get('percentage_10th', ''))
        target_lead['percentage_12th'] = form_data.get('percentage_12th', target_lead.get('percentage_12th', ''))
        target_lead['course_details'] = form_data.get('course_details', form_data.get('course_interest', target_lead.get('course_details', '')))
        if 'course_interest' in form_data:
            target_lead['course_interest'] = form_data.get('course_interest', '')
        elif 'course_details' in form_data:
            target_lead['course_interest'] = form_data.get('course_details', '')
        else:
            target_lead['course_interest'] = target_lead.get('course_interest') or target_lead.get('course_details', '')
        if isinstance(target_lead.get('form_data'), dict):
            target_lead['form_data'].update(form_data)
            target_lead['form_data']['course_interest'] = target_lead['course_interest']
            target_lead['form_data']['course_details'] = target_lead['course_details']
            if 'Which course are you interested in?' in target_lead['form_data']:
                target_lead['form_data']['Which course are you interested in?'] = target_lead['course_interest']
        target_lead['budget'] = form_data.get('budget', target_lead.get('budget', ''))
        target_lead['hostel_preference'] = form_data.get('hostel_preference', target_lead.get('hostel_preference', ''))
        target_lead['admission_preference'] = form_data.get('admission_preference', target_lead.get('admission_preference', ''))
        target_lead['assigned_college'] = form_data.get('assigned_college', target_lead.get('assigned_college', ''))
        target_lead['state'] = form_data.get('state', target_lead.get('state', ''))
        target_lead['city'] = form_data.get('city', target_lead.get('city', ''))

        delete_doc = form_data.get('delete_doc') == 'true'
        if delete_doc:
            old_doc=target_lead.get('id_document')
            if old_doc:
                _archive_record("student_document",{"stored_name":old_doc,"original_name":os.path.basename(str(old_doc))},
                                f"lead:{lead_id}:id_document:{uuid.uuid4().hex}","Student Documents",
                                {"parent_type":"lead","lead_id":lead_id,"field":"id_document"})
            target_lead['id_document'] = None
            if isinstance(target_lead.get('form_data'),dict): target_lead['form_data']['id_document']=None

        if 'id_document' in request.files:
            file = request.files['id_document']
            if file and file.filename != '':
                doc_path = upload_file_to_github(file, target_lead.get('student_name', 'Student'), file.filename)
                if doc_path:
                    target_lead['id_document'] = doc_path

        save_data(DATA_FILE, leads)
        log_activity("Lead Updated", f"Updated comprehensive information for lead #{lead_id} ({target_lead['student_name']})")
        return jsonify({"status": "success", "message": "Lead updated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _lead_creation_date(lead):
    """Return a lead creation date as YYYY-MM-DD, supporting legacy records."""
    raw = str(lead.get('created_date') or '').strip()
    if raw:
        try:
            return datetime.strptime(raw[:10], '%Y-%m-%d').date()
        except ValueError:
            pass
    raw = str(lead.get('created_at') or '').strip()
    for fmt in ('%d %b %Y, %I:%M %p', '%d %B %Y, %I:%M %p',
                '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _filtered_active_leads(statuses=None, start_date='', end_date=''):
    statuses = statuses or []
    start_obj = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
    end_obj = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
    if start_obj and end_obj and start_obj > end_obj:
        raise ValueError('Start date cannot be after end date.')

    selected = []
    for lead in load_data(DATA_FILE):
        if lead.get('is_deleted'):
            continue
        if statuses:
            status = str(lead.get('status') or '').strip()
            # "Contact" is the UI label for the CRM's existing "Contacted" value.
            if status not in statuses and not (status == 'Contacted' and 'Contact' in statuses):
                continue
        if start_obj or end_obj:
            created = _lead_creation_date(lead)
            if not created or (start_obj and created < start_obj) or (end_obj and created > end_obj):
                continue
        selected.append(lead)
    return selected


@app.route('/api/all-leads/export-csv', methods=['GET'])
def export_filtered_leads_csv():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        statuses = request.args.getlist('status')
        start_date = (request.args.get('start_date') or '').strip()
        end_date = (request.args.get('end_date') or '').strip()
        leads = _filtered_active_leads(statuses, start_date, end_date)
        # Preserve every existing lead field, including fields added dynamically.
        fieldnames = []
        for lead in leads:
            for key in lead.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ['id', 'student_name', 'contact_number', 'student_email',
                          'status', 'created_date', 'created_at']
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for lead in leads:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                for key, value in lead.items()
            })
        response = make_response('\ufeff' + output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = 'attachment; filename=All_Leads_Filtered.csv'
        return response
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route('/api/all-leads/delete-filtered', methods=['POST'])
def delete_filtered_leads():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    data = request.json or {}
    statuses = data.get('statuses') or []
    start_date = (data.get('start_date') or '').strip()
    end_date = (data.get('end_date') or '').strip()
    try:
        # Recalculate the exact matching set on the server; never trust client row counts.
        matching = _filtered_active_leads(statuses, start_date, end_date)
        if not matching:
            return jsonify({"status": "success", "deleted_count": 0,
                            "message": "No matching active leads were found."})
        matching_ids = {str(lead.get('id')) for lead in matching}
        all_leads = load_data(DATA_FILE)
        kept_leads, deleted_names = [], []
        for lead in all_leads:
            if not lead.get('is_deleted') and str(lead.get('id')) in matching_ids:
                _archive_record(DATA_FILE, lead, lead.get('id'), "Leads")
                deleted_names.append(str(lead.get('student_name') or lead.get('id')))
            else:
                kept_leads.append(lead)
        save_data(DATA_FILE, kept_leads)
        log_activity("Delete Filtered Leads",
                     f"Admin moved {len(deleted_names)} filtered lead(s) to Trash Bin.")
        return jsonify({"status": "success", "deleted_count": len(deleted_names),
                        "message": f"{len(deleted_names)} matching lead(s) moved to Trash Bin."})
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@app.route('/api/get-leads', methods=['GET'])
def get_leads_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(DATA_FILE))


def _enrich_registration_record(record):
    """Expose submitted registration values at top level while retaining original form_data."""
    if not isinstance(record, dict):
        return record
    form = record.get('form_data')
    if not isinstance(form, dict):
        return record
    for key, value in form.items():
        if value not in (None, '', [], {}) and record.get(key) in (None, '', [], {}):
            record[key] = value
    aliases = {
        'student_name': ('name',), 'contact_number': ('phone', 'mobile', 'contact'),
        'student_email': ('email',), 'course_interest': ('Which course are you interested in?', 'which_course', 'course'), 'annual_budget': ('budget',),
        'budget': ('annual_budget',), 'hostel_required': ('hostel_preference',),
        'hostel_preference': ('hostel_required',), 'course_details': ('course_interest', 'Which course are you interested in?', 'which_course', 'course'),
        'state': ('permanent_state',), 'city': ('permanent_city',)
    }
    for target, sources in aliases.items():
        if record.get(target) in (None, '', [], {}):
            for source in sources:
                value = form.get(source)
                if value not in (None, '', [], {}):
                    record[target] = value
                    break
    if record.get('course_interest') in (None, '', [], {}):
        for key, value in form.items():
            if str(key).strip().lower() in ('which course are you interested in?', 'which_course', 'course', 'course_interest') and value not in (None, '', [], {}):
                record['course_interest'] = value
                break
    if record.get('course_details') in (None, '', [], {}) and record.get('course_interest') not in (None, '', [], {}):
        record['course_details'] = record['course_interest']
    return record


@app.route('/api/get-students', methods=['GET'])
def get_students_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify([_enrich_registration_record(dict(student)) for student in load_data(STUDENTS_FILE)])


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
    for s in students:
        if s.get('original_lead_id') == lead_id:
            return jsonify({"status": "success", "message": "Lead is already converted to student."})
            
    new_student = _enrich_registration_record(dict(target_lead))
    new_student['course_interest'] = new_student.get('course_interest') or new_student.get('course_details') or ''
    new_student['course_details'] = new_student.get('course_details') or new_student.get('course_interest') or ''
    new_student['student_id'] = len(students) + 1
    new_student['original_lead_id'] = lead_id
    new_student['converted_at'] = datetime.now().strftime("%d %b %Y, %I:%M %p")
    
    students.append(new_student)
    save_data(STUDENTS_FILE, students)
    
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
        target_student = next((s for s in students if str(s.get('student_id')) == str(student_id)), None)
        if not target_student:
            return jsonify({"status": "error", "message": "Student not found"}), 404

        # Merge arbitrary submitted fields without dropping any existing registration data.
        raw_record = form_data.get('student_data_json')
        if raw_record:
            submitted = json.loads(raw_record)
            if not isinstance(submitted, dict):
                raise ValueError('Student data must be a JSON object.')
            protected = {'student_id', 'original_lead_id'}
            for key, value in submitted.items():
                if key not in protected and key not in ('id_document','class_10_doc','class_12_doc','aadhar_doc','edu_scorecard','passport_photo'):
                    target_student[key] = value
            if isinstance(submitted.get('form_data'), dict):
                target_student['form_data'] = submitted['form_data']
        # Existing named form fields remain supported and take precedence when supplied.
        for field, aliases in {
            'student_name': ('student_name',), 'father_name': ('father_name',),
            'contact_number': ('contact_number',), 'alternate_number': ('alternate_number',),
            'student_email': ('student_email',), 'current_education_level': ('current_education_level',),
            'qualification': ('qualification',), 'percentage_10th': ('percentage_10th',),
            'percentage_12th': ('percentage_12th',), 'edu_percentage': ('edu_percentage',),
            'course_interest': ('course_interest',), 'other_course': ('other_course',),
            'course_details': ('course_details',), 'hear_about': ('hear_about',),
            'other_source': ('other_source',), 'preferred_time': ('preferred_time',),
            'help_with': ('help_with',), 'annual_budget': ('annual_budget','budget'),
            'budget': ('budget','annual_budget'), 'fee_payment_option': ('fee_payment_option',),
            'payment_mode': ('payment_mode',), 'installment_duration': ('installment_duration',),
            'loan_assistance': ('loan_assistance',), 'hostel_required': ('hostel_required','hostel_preference'),
            'hostel_preference': ('hostel_preference','hostel_required'), 'contacted_college': ('contacted_college',),
            'col_name_1': ('col_name_1',), 'col_state_1': ('col_state_1',),
            'col_name_2': ('col_name_2',), 'col_state_2': ('col_state_2',),
            'col_name_3': ('col_name_3',), 'col_state_3': ('col_state_3',),
            'admission_preference': ('admission_preference',), 'assigned_college': ('assigned_college',),
            'state': ('state',), 'city': ('city',)
        }.items():
            for alias in aliases:
                if alias in form_data:
                    target_student[field] = form_data[alias]
                    break
        # Keep the original registration payload in sync for fields edited through the JSON editor.
        if isinstance(target_student.get('form_data'), dict):
            for key, value in form_data.items():
                if key not in ('student_id','student_data_json'):
                    target_student['form_data'][key] = value
            for key in ('student_name','father_name','contact_number','alternate_number','student_email',
                        'current_education_level','qualification','percentage_10th','percentage_12th',
                        'edu_percentage','course_interest','other_course','course_details','hear_about',
                        'other_source','preferred_time','help_with','annual_budget','budget',
                        'fee_payment_option','payment_mode','installment_duration','loan_assistance','hostel_required','hostel_preference',
                        'contacted_college','col_name_1','col_state_1','col_name_2','col_state_2',
                        'col_name_3','col_state_3','admission_preference','assigned_college','state','city'):
                if key in target_student:
                    target_student['form_data'][key] = target_student[key]
        for file_key, upload_list in request.files.lists():
            for upload in upload_list:
                if upload and upload.filename:
                    path = upload_file_to_github(upload, target_student.get('student_name', 'Student'), upload.filename)
                    if path:
                        old_path = target_student.get(file_key)
                        target_student['attachments'] = [a for a in target_student.get('attachments', [])
                            if not (isinstance(a, dict) and a.get('field') == file_key and a.get('stored_name') == old_path)]
                        target_student[file_key] = path
                        target_student.setdefault('attachments', []).append({
                            'field': file_key, 'stored_name': path,
                            'original_name': secure_filename(upload.filename),
                            'extension': os.path.splitext(upload.filename)[1].lower()
                        })
        save_data(STUDENTS_FILE, students)
        log_activity("Student Updated", f"Updated complete student profile for #{student_id} ({target_student.get('student_name','Student')})")
        return jsonify({"status": "success", "message": "Student updated successfully!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/delete-selected-students', methods=['POST'])
def delete_selected_students():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error":"Unauthorized. Admin access required."}),403
    ids={str(x) for x in (request.json or {}).get('student_ids',[])}
    records=load_data(STUDENTS_FILE); kept=[]; moved=0
    for rec in records:
        if str(rec.get('student_id')) in ids:
            _archive_record(STUDENTS_FILE,rec,rec.get('student_id'),"Students"); moved+=1
        else: kept.append(rec)
    save_data(STUDENTS_FILE,kept)
    log_activity("Delete Students",f"Admin moved {moved} student record(s) to Trash Bin.")
    return jsonify({"status":"success","message":f"{moved} student record(s) moved to Trash Bin."})


@app.route('/api/delete-selected-leads', methods=['POST'])
def delete_selected_leads():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error":"Unauthorized. Admin access required."}),403
    ids={str(x) for x in (request.json or {}).get('lead_ids',[])}
    records=load_data(DATA_FILE); kept=[]; moved=0
    for rec in records:
        if str(rec.get('id')) in ids and not rec.get('is_deleted'):
            _archive_record(DATA_FILE,rec,rec.get('id'),"Leads"); moved+=1
        else: kept.append(rec)
    save_data(DATA_FILE,kept)
    log_activity("Delete Leads",f"Admin moved {moved} lead(s) to Trash Bin.")
    return jsonify({"status":"success","message":f"{moved} lead(s) moved to Trash Bin."})


@app.route('/api/delete-selected-colleges', methods=['POST'])
def delete_selected_colleges():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error":"Unauthorized. Admin access required."}),403
    ids={str(x) for x in (request.json or {}).get('college_ids',[])}
    records=load_data(COLLEGES_FILE); kept=[]; moved=0
    for rec in records:
        if str(rec.get('id')) in ids:
            _archive_record(COLLEGES_FILE,rec,rec.get('id'),"Colleges"); moved+=1
        else: kept.append(rec)
    save_data(COLLEGES_FILE,kept)
    log_activity("Delete Colleges",f"Admin moved {moved} college record(s) to Trash Bin.")
    return jsonify({"status":"success","message":f"{moved} college record(s) moved to Trash Bin."})


@app.route('/api/delete-selected-history', methods=['POST'])
def delete_selected_history():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error":"Unauthorized. Admin access required."}),403
    ids={str(x) for x in (request.json or {}).get('history_ids',[])}
    records=load_data(HISTORY_FILE); kept=[]; moved=0
    for rec in records:
        if str(rec.get('id')) in ids:
            _archive_record(HISTORY_FILE,rec,rec.get('id'),"Work History"); moved+=1
        else: kept.append(rec)
    save_data(HISTORY_FILE,kept)
    log_activity("Delete Work History",f"Admin moved {moved} history record(s) to Trash Bin.")
    return jsonify({"status":"success","message":f"{moved} history record(s) moved to Trash Bin."})


@app.route('/api/delete-selected-logs', methods=['POST'])
def delete_selected_logs():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error":"Unauthorized. Admin access required."}),403
    ids={str(x) for x in (request.json or {}).get('log_ids',[])}
    records=load_data(LOGIN_LOGS_FILE); kept=[]; moved=0
    for rec in records:
        if str(rec.get('id')) in ids:
            _archive_record(LOGIN_LOGS_FILE,rec,rec.get('id'),"Logs"); moved+=1
        else: kept.append(rec)
    save_data(LOGIN_LOGS_FILE,kept)
    log_activity("Delete Login Logs",f"Admin moved {moved} login log record(s) to Trash Bin.")
    return jsonify({"status":"success","message":f"{moved} login log record(s) moved to Trash Bin."})


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
        return jsonify({"error":"Unauthorized. Admin access required."}),403
    logs=load_data(LOGIN_LOGS_FILE)
    for rec in logs: _archive_record(LOGIN_LOGS_FILE,rec,rec.get('id'),"Logs")
    save_data(LOGIN_LOGS_FILE,[])
    log_activity("Clear Logs",f"Admin {session.get('username')} moved all login activity logs to Trash Bin.")
    return jsonify({"status":"success","message":"All login logs moved to Trash Bin."})


@app.route('/api/get-trash', methods=['GET'])
def get_trash_api():
    if not session.get('logged_in'):
        return jsonify({"error":"Unauthorized"}),401
    _migrate_legacy_deleted_leads()
    items=load_data(TRASH_FILE)
    items.sort(key=lambda x:x.get('deleted_timestamp',0),reverse=True)
    return jsonify(items)


@app.route('/api/trash/restore', methods=['POST'])
def trash_restore():
    if not session.get('logged_in'):
        return jsonify({"error":"Unauthorized"}),401
    trash_id=str((request.json or {}).get('trash_id') or '')
    item=next((x for x in load_data(TRASH_FILE) if str(x.get('trash_id'))==trash_id),None)
    if not item:
        return jsonify({"status":"error","message":"Trash record not found."}),404
    try:
        _restore_trash_item(item)
        log_activity("Trash Restore",f"Restored {item.get('category')} record #{item.get('source_id')}.")
        return jsonify({"status":"success","message":"Record restored successfully."})
    except Exception as exc:
        return jsonify({"status":"error","message":str(exc)}),500


@app.route('/api/trash/delete-permanent', methods=['POST'])
def trash_permanent_delete():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error":"Unauthorized. Admin access required."}),403
    ids={str(x) for x in (request.json or {}).get('trash_ids',[])}
    items=[x for x in load_data(TRASH_FILE) if str(x.get('trash_id')) in ids]
    for item in items: _permanently_delete_trash_item(item)
    log_activity("Permanent Delete",f"Admin permanently deleted {len(items)} records from Trash Bin.")
    return jsonify({"status":"success","message":f"{len(items)} selected record(s) permanently deleted."})


@app.route('/api/trash/download', methods=['POST'])
def trash_download():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    trash_ids = {str(x) for x in data.get('trash_ids', data.get('lead_ids', []))}
    _migrate_legacy_deleted_leads()
    selected_trash = [x for x in load_data(TRASH_FILE) if str(x.get('trash_id')) in trash_ids]
    
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
                <tr><th>Category</th><th>ID</th><th>Record</th><th>Contact</th><th>Email</th><th>Deleted Date</th></tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td>{x.get('category','Other')}</td><td>#{x.get('source_id')}</td><td><strong>{(x.get('record') or {}).get('student_name') or (x.get('record') or {}).get('college_name') or (x.get('record') or {}).get('username') or (x.get('record') or {}).get('action_type') or 'Record'}</strong></td><td>{(x.get('record') or {}).get('contact_number','')}</td><td>{(x.get('record') or {}).get('student_email','')}</td><td>{x.get('deleted_at','')}</td></tr>" for x in selected_trash])}
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


@app.route('/api/admin/change-password', methods=['POST'])
def admin_change_password():
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    
    data = request.json or {}
    target_user = data.get('target_user')
    new_password = data.get('new_password')
    
    if not target_user or not new_password:
        return jsonify({"status": "error", "message": "Target user and new password are required."}), 400
        
    users = load_users()
    if target_user not in users:
        return jsonify({"status": "error", "message": "User not found."}), 404
        
    users[target_user]['password'] = generate_password_hash(new_password)
    save_data(USERS_FILE, users)
    log_activity("Password Changed", f"Admin {session.get('username')} updated password for user: {target_user}")
    return jsonify({"status": "success", "message": f"Password for {target_user} updated successfully."})


@app.route('/api/export-full-excel', methods=['GET'])
def export_full_excel():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    if not OPENPYXL_AVAILABLE:
        return "openpyxl library not installed on server.", 500

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    ws_dash = wb.create_sheet(title="Dashboard Summary")
    leads = load_data(DATA_FILE)
    active_leads = [l for l in leads if not l.get('is_deleted')]
    students = load_data(STUDENTS_FILE)
    colleges = load_data(COLLEGES_FILE)

    dash_data = [
        ["CounselScope CRM Executive Summary", ""],
        ["Generated On", datetime.now().strftime('%d %b %Y, %I:%M %p')],
        ["Metric", "Value"],
        ["Total Active Leads", len(active_leads)],
        ["Registered Students", len(students)],
        ["Partner Colleges", len(colleges)],
        ["Contacted Leads", len([l for l in active_leads if l.get('status') == 'Contacted'])],
        ["Follow-Up Leads", len([l for l in active_leads if l.get('status') == 'Follow Up'])],
        ["Rejected Leads", len([l for l in active_leads if l.get('status') == 'Rejected'])],
        ["New Leads", len([l for l in active_leads if l.get('status') == 'New Lead'])]
    ]
    for row in dash_data:
        ws_dash.append(row)

    ws_leads = wb.create_sheet(title="All Leads")
    ws_leads.append(["ID", "Student Name", "Father Name", "Contact", "Email", "Assigned College", "Status", "Course Details", "Budget"])
    for cell in ws_leads[1]:
        cell.fill = header_fill
        cell.font = header_font
    for l in active_leads:
        ws_leads.append([l.get('id'), l.get('student_name'), l.get('father_name',''), l.get('contact_number'), l.get('student_email'), l.get('assigned_college','None'), l.get('status'), l.get('course_details',''), l.get('budget','')])

    ws_students = wb.create_sheet(title="Students")
    ws_students.append(["Student ID", "Original Lead ID", "Student Name", "Father Name", "Contact", "Email", "Assigned College", "Qualification", "10th %", "12th %", "Course Details", "Budget", "Admission Status", "Converted At"])
    for cell in ws_students[1]:
        cell.fill = header_fill
        cell.font = header_font
    for s in students:
        ws_students.append([
            s.get('student_id'), 
            s.get('original_lead_id', 'N/A'), 
            s.get('student_name'), 
            s.get('father_name', ''), 
            s.get('contact_number'), 
            s.get('student_email'), 
            s.get('assigned_college', 'Not Assigned'), 
            s.get('qualification', 'N/A'), 
            s.get('percentage_10th', 'N/A'), 
            s.get('percentage_12th', 'N/A'), 
            s.get('course_details', 'N/A'), 
            s.get('budget', 'N/A'), 
            s.get('status', 'Registered Student'), 
            s.get('converted_at', 'N/A')
        ])

    ws_colleges = wb.create_sheet(title="College Management")
    ws_colleges.append(["ID", "College Name", "Location", "Courses Offered", "Avg Package"])
    for cell in ws_colleges[1]:
        cell.fill = header_fill
        cell.font = header_font
    for c in colleges:
        ws_colleges.append([c.get('id'), c.get('college_name'), c.get('location'), c.get('courses'), c.get('package')])

    ws_history = wb.create_sheet(title="Work History")
    ws_history.append(["ID", "Username", "Role", "Date", "Time", "Action Type", "Details"])
    for cell in ws_history[1]:
        cell.fill = header_fill
        cell.font = header_font
    for h in load_data(HISTORY_FILE):
        ws_history.append([h.get('id'), h.get('username','Admin'), h.get('role','Admin'), h.get('date'), h.get('time'), h.get('action_type'), h.get('details')])

    ws_logs = wb.create_sheet(title="Activity Logs")
    ws_logs.append(["ID", "Username", "Role", "IP Address", "Browser", "OS", "Location", "Login Time", "Logout Time", "Status"])
    for cell in ws_logs[1]:
        cell.fill = header_fill
        cell.font = header_font
    for log in load_data(LOGIN_LOGS_FILE):
        ws_logs.append([log.get('id'), log.get('username'), log.get('role'), log.get('ip_address'), log.get('browser'), log.get('os'), log.get('location'), log.get('login_time'), log.get('logout_time'), log.get('status')])

    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            sheet.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 60)
        # Excel cells cannot store Python dictionaries/lists. Convert nested CRM fields to JSON text.
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, (dict, list, tuple, set)):
                    cell.value = json.dumps(cell.value, ensure_ascii=False, default=str)
                elif cell.value is not None and not isinstance(cell.value, (str, int, float, bool)):
                    cell.value = str(cell.value)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name='CounselScope_Complete_CRM_Export.xlsx')


@app.route('/api/export-full-pdf', methods=['GET'])
def export_full_pdf():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401

    leads = [l for l in load_data(DATA_FILE) if not l.get('is_deleted')]
    students = load_data(STUDENTS_FILE)
    colleges = load_data(COLLEGES_FILE)
    history = load_data(HISTORY_FILE)
    logs = load_data(LOGIN_LOGS_FILE)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>CounselScope Full CRM Executive PDF Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; color: #1e293b; padding: 25px; line-height: 1.4; }}
            h1 {{ color: #2563eb; font-size: 24px; border-bottom: 3px solid #2563eb; padding-bottom: 8px; margin-bottom: 5px; }}
            h2 {{ color: #0f172a; font-size: 16px; border-bottom: 2px solid #cbd5e1; padding-bottom: 4px; margin-top: 30px; margin-bottom: 12px; page-break-before: always; }}
            h2:first-of-type {{ page-break-before: avoid; }}
            .summary-box {{ background: #f8fafc; border: 1px solid #cbd5e1; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 20px; flex-wrap: wrap; }}
            .stat-item {{ font-size: 13px; }}
            .stat-item strong {{ color: #2563eb; font-size: 16px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 10.5px; page-break-inside: auto; }}
            tr {{ page-break-inside: avoid; page-break-after: auto; }}
            th {{ background: #0f172a; color: white; padding: 7px; text-align: left; }}
            td {{ padding: 6px; border-bottom: 1px solid #cbd5e1; }}
        </style>
    </head>
    <body>
        <h1>CounselScope CRM - Complete System PDF Report</h1>
        <p style="font-size: 12px; color: #64748b; margin-bottom: 20px;">Generated on: {datetime.now().strftime('%d %b %Y, %I:%M %p')}</p>

        <div class="summary-box">
            <div class="stat-item">Total Leads: <strong>{len(leads)}</strong></div>
            <div class="stat-item">Registered Students: <strong>{len(students)}</strong></div>
            <div class="stat-item">Partner Colleges: <strong>{len(colleges)}</strong></div>
            <div class="stat-item">Activity Records: <strong>{len(history)}</strong></div>
        </div>

        <h2>1. Registered Students Directory</h2>
        <table>
            <thead><tr><th>#ID</th><th>Student Name</th><th>Contact</th><th>Email</th><th>Assigned College</th><th>Course</th></tr></thead>
            <tbody>
                {''.join([f"<tr><td>#{s.get('student_id')}</td><td><strong>{s.get('student_name')}</strong></td><td>{s.get('contact_number')}</td><td>{s.get('student_email')}</td><td>{s.get('assigned_college','Not Assigned')}</td><td>{s.get('course_details','N/A')}</td></tr>" for s in students]) if students else "<tr><td colspan='6'>No student records found.</td></tr>"}
            </tbody>
        </table>

        <h2>2. Active Leads Directory</h2>
        <table>
            <thead><tr><th>#ID</th><th>Student Name</th><th>Contact</th><th>Email</th><th>Assigned College</th><th>Status</th></tr></thead>
            <tbody>
                {''.join([f"<tr><td>#{l.get('id')}</td><td><strong>{l.get('student_name')}</strong></td><td>{l.get('contact_number')}</td><td>{l.get('student_email')}</td><td>{l.get('assigned_college','None')}</td><td>{l.get('status')}</td></tr>" for l in leads])}
            </tbody>
        </table>

        <h2>3. Partner Colleges Directory</h2>
        <table>
            <thead><tr><th>#ID</th><th>College Name</th><th>Location</th><th>Courses Offered</th><th>Avg Package</th></tr></thead>
            <tbody>
                {''.join([f"<tr><td>#{c.get('id')}</td><td><strong>{c.get('college_name')}</strong></td><td>{c.get('location')}</td><td>{c.get('courses')}</td><td>{c.get('package')}</td></tr>" for c in colleges])}
            </tbody>
        </table>

        <h2>4. Work History & Activity Logs</h2>
        <table>
            <thead><tr><th>User</th><th>Role</th><th>Date & Time</th><th>Action Type</th><th>Details</th></tr></thead>
            <tbody>
                {''.join([f"<tr><td>{h.get('username','Admin')}</td><td>{h.get('role','Admin')}</td><td>{h.get('date')} {h.get('time')}</td><td><strong>{h.get('action_type')}</strong></td><td>{h.get('details')}</td></tr>" for h in history[-25:]])}
            </tbody>
        </table>

        <script>window.onload = function() {{ window.print(); }}</script>
    </body>
    </html>
    """
    resp = make_response(html)
    resp.headers["Content-Disposition"] = "inline; filename=CounselScope_Complete_CRM_Report.html"
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route('/api/export-logs-pdf', methods=['GET'])
def export_logs_pdf():
    return export_filtered_logs_pdf()


@app.route('/api/export-history-pdf', methods=['GET'])
def export_history_pdf():
    return export_filtered_history_pdf()


def _parse_flexible_date(value):
    raw = str(value or '').strip()
    if not raw: return None
    for fmt in ('%Y-%m-%d','%d %b %Y, %I:%M %p','%d %B %Y, %I:%M %p','%d-%m-%Y','%d/%m/%Y'):
        try: return datetime.strptime(raw[:25],fmt).date()
        except ValueError: pass
    try: return datetime.fromtimestamp(float(raw)).date()
    except (ValueError,TypeError,OSError): return None


def _filter_date_range(records,start_date='',end_date='',date_getter=None):
    start=_parse_flexible_date(start_date); end=_parse_flexible_date(end_date)
    if start and end and start>end: raise ValueError('Start date cannot be after End date.')
    if not start and not end: return records
    out=[]
    for item in records:
        d=_parse_flexible_date(date_getter(item) if date_getter else item.get('date'))
        if d and (not start or d>=start) and (not end or d<=end): out.append(item)
    return out


def _trash_record_date(lead):
    return lead.get('deleted_date') or lead.get('deleted_at') or lead.get('created_date') or lead.get('created_at')


def _history_record_date(item):
    return item.get('date') or item.get('timestamp') or item.get('created_at')


def _log_record_in_range(log,start_date='',end_date=''):
    start=_parse_flexible_date(start_date); end=_parse_flexible_date(end_date)
    if start and end and start>end: raise ValueError('Start date cannot be after End date.')
    if not start and not end: return True
    vals=[log.get('login_date') or log.get('login_time'),log.get('logout_date') or log.get('logout_time'),log.get('login_timestamp'),log.get('logout_timestamp')]
    return any((d:=_parse_flexible_date(v)) and (not start or d>=start) and (not end or d<=end) for v in vals)


def _get_attachment_bytes(reference,college=False):
    if not reference: return None
    if isinstance(reference,dict):
        path=reference.get('github_path') or reference.get('stored_name') or reference.get('path') or reference.get('url')
        if path and str(path).startswith('data:'):
            try: return base64.b64decode(str(path).split(',',1)[1])
            except Exception: return None
        if path: reference=path
        else:
            encoded=reference.get('content_base64') or reference.get('base64')
            if encoded:
                try: return base64.b64decode(encoded)
                except Exception: return None
            return None
    path=str(reference)
    if path.startswith('data:'):
        try: return base64.b64decode(path.split(',',1)[1])
        except Exception: return None
    if os.path.isfile(path):
        try:
            with open(path,'rb') as f: return f.read()
        except OSError: return None
    if not GITHUB_REPO: return None
    if college and path.startswith('student/college/'):
        try: return get_college_file_from_github(path)
        except Exception: pass
    try:
        url=f'https://api.github.com/repos/{GITHUB_REPO}/contents/{path}'
        headers={'Authorization':f'Bearer {GITHUB_TOKEN}','Accept':'application/vnd.github+json'} if GITHUB_TOKEN else {'Accept':'application/vnd.github+json'}
        response=requests.get(url,headers=headers,params={'ref':GITHUB_BRANCH},timeout=30)
        if response.status_code==200:
            payload=response.json()
            if payload.get('encoding')=='base64' and payload.get('content'): return base64.b64decode(payload['content'])
    except Exception as exc: print('Attachment retrieval error:',exc)
    return None


def _build_report_pdf(title,entities,entity_label,attachment_getter=None):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,Image as RLImage
    # pypdf is optional: ordinary report PDFs must still work when it is unavailable.
    try:
        from pypdf import PdfReader, PdfWriter
        PYPDF_AVAILABLE = True
    except ImportError:
        PdfReader = PdfWriter = None
        PYPDF_AVAILABLE = False
    styles=getSampleStyleSheet()
    title_style=ParagraphStyle('ReportTitle',parent=styles['Title'],textColor=colors.HexColor('#0f172a'),alignment=TA_CENTER,spaceAfter=12)
    heading=ParagraphStyle('EntityHeading',parent=styles['Heading2'],textColor=colors.HexColor('#1d4ed8'),spaceBefore=8,spaceAfter=8)
    normal=ParagraphStyle('SmallBody',parent=styles['BodyText'],fontSize=8.5,leading=11,wordWrap='CJK')
    def esc(v):
        if isinstance(v,(dict,list)): v=json.dumps(v,ensure_ascii=False,default=str)
        raw = str(v if v is not None else '')
        # Remove XML-invalid control characters before passing text to ReportLab Paragraph.
        raw = ''.join(ch for ch in raw if ch in ('\n','\r','\t') or ord(ch) >= 32)
        return raw.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br/>').replace('\r','')
    story=[Paragraph(esc(title),title_style),Paragraph('Generated: '+datetime.now().strftime('%d %b %Y, %I:%M %p'),normal),Spacer(1,8)]
    pdf_attachments=[]
    for idx,entity in enumerate(entities,1):
        name=entity.get('college_name') if entity_label=='College' else entity.get('student_name') or entity.get('username')
        story.append(Paragraph(f'{entity_label} {idx}: {esc(name or "Unnamed")}',heading))
        pairs=[]
        for key,value in entity.items():
            if key in ('document','attachments','form_data') or value in (None,'',[],{}): continue
            pairs.append([Paragraph('<b>'+esc(str(key).replace('_',' ').title())+'</b>',normal),Paragraph(esc(value),normal)])
        if isinstance(entity.get('form_data'),dict):
            for key,value in entity['form_data'].items():
                if value not in (None,'',[],{}): pairs.append([Paragraph('<b>Registration: '+esc(str(key).replace('_',' ').title())+'</b>',normal),Paragraph(esc(value),normal)])
        if pairs:
            table=Table(pairs,colWidths=[48*mm,125*mm])
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(0,-1),colors.HexColor('#eff6ff')),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#cbd5e1')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
            story.append(table)
        refs=attachment_getter(entity) if attachment_getter else []
        for label,item in refs or []:
            data=_get_attachment_bytes(item,college=(entity_label=='College'))
            if not data:
                story.append(Paragraph('Attachment unavailable: '+esc(label),normal)); continue
            rawname=item.get('original_name','') if isinstance(item,dict) else str(item)
            ext=(os.path.splitext(rawname)[1] or (item.get('extension','') if isinstance(item,dict) else '')).lower()
            if ext in ('.jpg','.jpeg','.png','.gif','.webp') or data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff'):
                story.append(Paragraph('Image Attachment: '+esc(label),heading))
                try: story.append(RLImage(io.BytesIO(data),width=150*mm,height=105*mm,kind='proportional')); story.append(Spacer(1,8))
                except Exception: story.append(Paragraph('Image could not be embedded: '+esc(label),normal))
            elif ext=='.pdf' or data.startswith(b'%PDF-'):
                pdf_attachments.append((name or f'{entity_label} {idx}',label,data))
                story.append(Paragraph('PDF attachment included after record sections: '+esc(label),normal))
            else: story.append(Paragraph('Unsupported attachment type: '+esc(label),normal))
        if idx<len(entities): story.append(PageBreak())
    base=io.BytesIO()
    SimpleDocTemplate(base,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=16*mm,bottomMargin=16*mm,title=title).build(story)
    base.seek(0)

    # Merge attached PDFs only when pypdf is installed. The main report remains downloadable
    # even if optional PDF-merging support is unavailable or an attachment is damaged.
    if pdf_attachments and PYPDF_AVAILABLE:
        try:
            writer=PdfWriter()
            writer.append(PdfReader(base))
            for owner,label,data in pdf_attachments:
                try:
                    cover=io.BytesIO()
                    SimpleDocTemplate(cover,pagesize=A4).build([
                        Paragraph(esc(title),title_style), Spacer(1,20),
                        Paragraph('Attachment for: '+esc(owner),heading), Paragraph(esc(label),normal)
                    ])
                    cover.seek(0)
                    writer.append(PdfReader(cover))
                    writer.append(PdfReader(io.BytesIO(data)))
                except Exception as attachment_error:
                    print('PDF attachment merge skipped:', attachment_error)
            final=io.BytesIO()
            writer.write(final)
            final.seek(0)
            return final
        except Exception as merge_error:
            print('PDF merge failed; returning main report only:', merge_error)

    base.seek(0)
    return base


@app.route('/api/export-filtered-logs-pdf', methods=['GET'])
def export_filtered_logs_pdf():
    if not session.get('logged_in'):
        return jsonify({'error':'Unauthorized'}), 401
    try:
        start_date = request.args.get('start_date','').strip(); end_date = request.args.get('end_date','').strip()
        user_type = request.args.get('user_type','All Users').strip()
        logs = load_data(LOGIN_LOGS_FILE)
        if user_type in ('Admin','Client'):
            logs = [l for l in logs if str(l.get('role','')).lower() == user_type.lower()]
        logs = [l for l in logs if _log_record_in_range(l, start_date, end_date)]
        html_rows = []
        for l in logs:
            for label, date_value, time_value, timestamp in [('Login',l.get('login_date'),l.get('login_time'),l.get('login_timestamp')),('Logout',l.get('logout_date'),l.get('logout_time'),l.get('logout_timestamp'))]:
                if date_value not in (None,'','N/A') or time_value not in (None,'','N/A'):
                    if start_date or end_date:
                        event_date = date_value or timestamp
                        parsed_event_date = _parse_flexible_date(event_date)
                        start_obj = _parse_flexible_date(start_date); end_obj = _parse_flexible_date(end_date)
                        if not parsed_event_date or (start_obj and parsed_event_date < start_obj) or (end_obj and parsed_event_date > end_obj):
                            continue
                    html_rows.append({'id':l.get('id'),'username':l.get('username'),'role':l.get('role'),'activity':label,'date':date_value,'time':time_value,'ip':l.get('ip_address'),'browser':l.get('browser'),'os':l.get('os'),'location':l.get('location'),'status':l.get('status'),'session_info':l.get('session_info'),'user_agent':l.get('user_agent')})
        pdf = _build_report_pdf('CounselScope CRM - Filtered Security & Login Logs', html_rows, 'Log')
        return send_file(pdf, mimetype='application/pdf', as_attachment=True, download_name='Security_Logs_Filtered.pdf')
    except ValueError as e:
        return jsonify({'error':str(e)}), 400
    except Exception as e:
        app.logger.exception('Security log PDF export failed')
        return jsonify({'error':f'Security log PDF export failed: {e}'}), 500


@app.route('/api/export-filtered-history-pdf', methods=['GET'])
def export_filtered_history_pdf():
    if not session.get('logged_in'):
        return jsonify({'error':'Unauthorized'}), 401
    try:
        history = _filter_date_range(load_data(HISTORY_FILE), request.args.get('start_date',''), request.args.get('end_date',''), _history_record_date)
        pdf = _build_report_pdf('CounselScope CRM - Work History', history, 'Work History')
        return send_file(pdf, mimetype='application/pdf', as_attachment=True, download_name='Work_History_Filtered.pdf')
    except ValueError as e:
        return jsonify({'error':str(e)}), 400
    except Exception as e:
        app.logger.exception('Work history PDF export failed')
        return jsonify({'error':f'Work history PDF export failed: {e}'}), 500


@app.route('/api/export-filtered-trash-pdf', methods=['GET'])
def export_filtered_trash_pdf():
    if not session.get('logged_in'):
        return jsonify({'error':'Unauthorized'}), 401
    try:
        _migrate_legacy_deleted_leads()
        trash = load_data(TRASH_FILE)
        trash = _filter_date_range(trash, request.args.get('start_date',''), request.args.get('end_date',''), lambda x: _parse_flexible_date(x.get('deleted_date') or x.get('deleted_at')))
        export_rows = []
        for item in trash:
            rec=dict(item.get('record') or {})
            rec.update({'category':item.get('category'),'trash_id':item.get('trash_id'),
                        'source_id':item.get('source_id'),'deleted_at':item.get('deleted_at')})
            export_rows.append(rec)
        pdf = _build_report_pdf('CounselScope CRM - Trash Bin Report', export_rows, 'Deleted Record')
        return send_file(pdf, mimetype='application/pdf', as_attachment=True, download_name='Trash_Bin_Filtered.pdf')
    except ValueError as e:
        return jsonify({'error':str(e)}), 400
    except Exception as e:
        app.logger.exception('Trash PDF export failed')
        return jsonify({'error':f'Trash PDF export failed: {e}'}), 500


@app.route('/api/export-students-pdf', methods=['GET'])
def export_students_consolidated_pdf():
    if not session.get('logged_in'):
        return jsonify({'error':'Unauthorized'}), 401
    students = [_enrich_registration_record(dict(student)) for student in load_data(STUDENTS_FILE)]
    def student_attachments(student):
        found=[]
        seen=set()
        def attachment_marker(item):
            if isinstance(item,dict):
                return str(item.get('github_path') or item.get('stored_name') or item.get('path') or item.get('url') or json.dumps(item,sort_keys=True,default=str))
            return str(item)
        for key, value in student.items():
            low=str(key).lower()
            if key != 'attachments' and value and any(token in low for token in ('photo','image','document','attachment','file','scorecard','marksheet','aadhar')):
                values=value if isinstance(value,list) else [value]
                for sub_idx, sub_value in enumerate(values):
                    marker=attachment_marker(sub_value)
                    if marker not in seen: found.append((key.replace('_',' ').title() + (f' {sub_idx+1}' if len(values)>1 else ''),sub_value)); seen.add(marker)
        for idx, item in enumerate(student.get('attachments') or []):
            marker=attachment_marker(item)
            if marker not in seen: found.append((f'Attachment {idx+1}',item)); seen.add(marker)
        if isinstance(student.get('form_data'), dict):
            for key, item in student['form_data'].items():
                low=str(key).lower()
                if item and any(token in low for token in ('photo','image','document','attachment','file','scorecard','marksheet','aadhar')):
                    marker=json.dumps(item,sort_keys=True,default=str)
                    if marker not in seen: found.append((key.replace('_',' ').title(),item)); seen.add(marker)
        return found
    try:
        pdf = _build_report_pdf('CounselScope CRM - Complete Registered Students', students, 'Student', student_attachments)
        return send_file(pdf, mimetype='application/pdf', as_attachment=True, download_name='All_Students_With_Attachments.pdf')
    except Exception as e:
        return jsonify({'error':f'Unable to generate student PDF: {e}'}), 500


@app.route('/api/export-college-pdf', methods=['GET'])
def export_college_pdf():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    colleges = load_data(COLLEGES_FILE)
    def college_attachments(college):
        found=[]
        doc = college.get('document')
        if doc: found.append((doc.get('original_name','College Document') if isinstance(doc,dict) else 'College Document', doc))
        for idx, item in enumerate(college.get('attachments') or []): found.append((f'Attachment {idx+1}',item))
        return found
    try:
        pdf = _build_report_pdf('CounselScope CRM - Complete College Directory', colleges, 'College', college_attachments)
        return send_file(pdf, mimetype='application/pdf', as_attachment=True, download_name='All_Colleges_With_Attachments.pdf')
    except Exception as e:
        return jsonify({'error':f'Unable to generate college PDF: {e}'}), 500


@app.route('/api/export-leads-pdf', methods=['GET'])
def export_leads_pdf():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    leads = [l for l in load_data(DATA_FILE) if not l.get('is_deleted')]
    html = f"""
    <!DOCTYPE html><html><head><meta charset="utf-8"><title>Student Leads Report</title><style>body {{ font-family: Arial, sans-serif; padding: 25px; }} table {{ width: 100%; border-collapse: collapse; font-size: 11px; }} th {{ background: #0f172a; color: white; padding: 8px; text-align: left; }} td {{ padding: 7px; border-bottom: 1px solid #cbd5e1; }}</style></head>
    <body><h1>CounselScope CRM - Student Leads Report</h1><table><thead><tr><th>ID</th><th>Student Name</th><th>Contact</th><th>Email</th><th>College</th><th>Status</th></tr></thead><tbody>
    {''.join([f"<tr><td>#{l.get('id')}</td><td><strong>{l.get('student_name')}</strong></td><td>{l.get('contact_number')}</td><td>{l.get('student_email')}</td><td>{l.get('assigned_college','None')}</td><td>{l.get('status')}</td></tr>" for l in leads])}
    </tbody></table><script>window.onload = function() {{ window.print(); }}</script></body></html>
    """
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route('/download-doc/<path:filename>', methods=['GET'])
def download_document(filename):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if not GITHUB_REPO:
        return jsonify({"error": "GitHub repository configuration is missing. Set GITHUB_REPO."}), 503
    safe_path = str(filename or '').lstrip('/')
    if '..' in safe_path.split('/'):
        return jsonify({"error": "Invalid document path."}), 400
    raw_github_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{safe_path}"
    try:
        download_headers = {'Authorization': f'Bearer {GITHUB_TOKEN}'} if GITHUB_TOKEN else {}
        upstream = requests.get(raw_github_url, headers=download_headers, timeout=30, stream=True)
        if upstream.status_code != 200:
            return jsonify({"error": f"Document not found in GitHub (HTTP {upstream.status_code})."}), 404
        content = upstream.content
        mimetype = upstream.headers.get('Content-Type') or mimetypes.guess_type(safe_path)[0] or 'application/octet-stream'
        return send_file(io.BytesIO(content), mimetype=mimetype, as_attachment=request.args.get('download') == '1', download_name=os.path.basename(safe_path))
    except requests.RequestException as e:
        app.logger.exception('GitHub document download failed')
        return jsonify({"error": f"Unable to retrieve document from GitHub: {e}"}), 502


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
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error":"Unauthorized. Admin access required."}),403
    lead_id=(request.json or {}).get('lead_id')
    records=load_data(DATA_FILE)
    target=next((x for x in records if str(x.get('id'))==str(lead_id)),None)
    if not target: return jsonify({"status":"error","message":"Lead not found."}),404
    _archive_record(DATA_FILE,target,target.get('id'),"Leads")
    save_data(DATA_FILE,[x for x in records if str(x.get('id'))!=str(lead_id)])
    log_activity("Moved to Trash",f"Moved lead #{lead_id} ({target.get('student_name','')}) to trash")
    return jsonify({"status":"success","message":"Lead moved to Trash Bin."})


@app.route('/api/restore-lead', methods=['POST'])
def restore_lead():
    if not session.get('logged_in'):
        return jsonify({"error":"Unauthorized"}),401
    lead_id=(request.json or {}).get('lead_id')
    item=next((x for x in load_data(TRASH_FILE) if x.get('source_file')==DATA_FILE and str(x.get('source_id'))==str(lead_id)),None)
    if item: _restore_trash_item(item)
    else:
        records=load_data(DATA_FILE)
        for rec in records:
            if str(rec.get('id'))==str(lead_id): rec['is_deleted']=False
        save_data(DATA_FILE,records)
    log_activity("Restored Lead",f"Restored lead #{lead_id} from trash")
    return jsonify({"status":"success"})


@app.route('/api/get-history', methods=['GET'])
def get_history_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(HISTORY_FILE))


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
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    try:
        if not GITHUB_TOKEN or not GITHUB_REPO:
            return jsonify({"status": "error", "message": "GitHub storage is not configured. Set GITHUB_TOKEN and GITHUB_REPO before adding colleges."}), 503

        data = request.form
        name = (data.get('college_name') or '').strip()
        if not name:
            return jsonify({"status": "error", "message": "College name is required."}), 400

        colleges = load_data(COLLEGES_FILE)
        existing_ids = [int(c.get('id', 0)) for c in colleges if str(c.get('id', '')).isdigit()]
        new_c = {
            "id": max(existing_ids, default=0) + 1,
            "college_name": name,
            "location": (data.get('address') or '').strip(),
            "address": (data.get('address') or '').strip(),
            "phone": (data.get('phone') or '').strip(),
            "email": (data.get('email') or '').strip(),
            "description": (data.get('description') or '').strip(),
            "courses": "",
            "package": "N/A",
            "document": None
        }

        upload = request.files.get('college_file')
        if upload and upload.filename:
            new_c['document'] = upload_college_document_to_github(upload, name, new_c['id'])

        # Per-college JSON and any uploaded document live in this college's folder.
        new_c['github_record_path'] = save_college_record_to_github(new_c)
        colleges.append(new_c)
        save_data(COLLEGES_FILE, colleges)  # Keep the existing CRM-wide index for current UI/report compatibility.
        log_activity("College Added", f"Added new college: {name}")
        return jsonify({"status": "success", "message": "College added and saved to GitHub successfully.", "college": new_c})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/update-college/<int:college_id>', methods=['POST'])
def update_college(college_id):
    if not session.get('logged_in') or session.get('role') != 'Admin':
        return jsonify({"error": "Unauthorized. Admin access required."}), 403
    try:
        if not GITHUB_TOKEN or not GITHUB_REPO:
            return jsonify({"status": "error", "message": "GitHub storage is not configured. Set GITHUB_TOKEN and GITHUB_REPO before updating colleges."}), 503

        colleges = load_data(COLLEGES_FILE)
        target = next((c for c in colleges if c.get('id') == college_id), None)
        if not target:
            return jsonify({"status": "error", "message": "College not found."}), 404

        data = request.form
        name = (data.get('college_name') or target.get('college_name') or '').strip()
        if not name:
            return jsonify({"status": "error", "message": "College name is required."}), 400
        address = data.get('address')
        if address is not None:
            target['address'] = address.strip()
            target['location'] = address.strip()  # Keep legacy college dropdown/report compatibility.
        for field in ('phone', 'email', 'description'):
            if field in data:
                target[field] = data.get(field, '').strip()
        target['college_name'] = name

        upload = request.files.get('college_file')
        if upload and upload.filename:
            target['document'] = upload_college_document_to_github(upload, name, college_id)

        # No replacement file? Existing document metadata remains unchanged.
        target['github_record_path'] = save_college_record_to_github(target)
        save_data(COLLEGES_FILE, colleges)
        log_activity("College Updated", f"Updated college #{college_id}: {name}")
        return jsonify({"status": "success", "message": "College updated and saved to GitHub successfully.", "college": target})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/student-document/<int:student_id>/<path:field>', methods=['POST'])
def manage_student_document(student_id, field):
    if not session.get('logged_in'):
        return jsonify({"error":"Unauthorized"}),401
    if session.get('role') != 'Admin':
        return jsonify({"error":"Admin access required"}),403
    students=load_data(STUDENTS_FILE)
    student=next((x for x in students if str(x.get('student_id'))==str(student_id)),None)
    if not student:
        return jsonify({"error":"Student not found"}),404
    payload=request.get_json(silent=True) or {}
    field=request.form.get('field') or payload.get('field') or field
    old_path=request.form.get('stored_name') or payload.get('stored_name') or student.get(field)
    attachment=next((x for x in student.get('attachments',[]) if isinstance(x,dict)
                     and x.get('stored_name')==old_path),None)
    top_level=bool(old_path and student.get(field)==old_path)
    form_data_ref=bool(old_path and isinstance(student.get('form_data'),dict) and student['form_data'].get(field)==old_path)
    action=request.form.get('action') or payload.get('action')
    if action == 'upload':
        upload=request.files.get('file')
        if not upload or not upload.filename:
            return jsonify({"error":"Select a document to upload."}),400
        ext=os.path.splitext(secure_filename(upload.filename))[1].lower()
        if ext not in ('.pdf','.jpg','.jpeg','.png'):
            return jsonify({"error":"Only PDF, JPG, JPEG and PNG files are allowed."}),400
        new_path=upload_file_to_github(upload,student.get('student_name','Student'),upload.filename)
        if not new_path:
            return jsonify({"error":"Unable to upload document. Check GitHub configuration."}),502
        new_field="additional_document_"+uuid.uuid4().hex[:10]
        student[new_field]=new_path
        student.setdefault('attachments',[]).append({
            'field':new_field,'stored_name':new_path,
            'original_name':secure_filename(upload.filename),'extension':ext
        })
        if isinstance(student.get('form_data'),dict):
            student['form_data'][new_field]=new_path
        save_data(STUDENTS_FILE,students)
        log_activity("Student Document Uploaded",f"Uploaded additional document for student #{student_id}.")
        return jsonify({"status":"success","message":"Document uploaded successfully."})
    if action == 'delete':
        if not old_path:
            return jsonify({"error":"Selected document was not found."}),404
        snapshot={"stored_name":old_path,"attachment":attachment,
                  "original_name":(attachment or {}).get('original_name') or os.path.basename(str(old_path))}
        _archive_record("student_document",snapshot,f"{student_id}:{field}:{uuid.uuid4().hex}","Student Documents",
                        {"student_id":student_id,"field":field,"top_level":top_level,"form_data_ref":form_data_ref})
        if top_level: student[field]=None
        if form_data_ref: student['form_data'][field]=None
        student['attachments']=[x for x in student.get('attachments',[]) if not
            (isinstance(x,dict) and x.get('stored_name')==old_path)]
        save_data(STUDENTS_FILE,students)
        log_activity("Student Document Deleted",f"Moved {field} document for student #{student_id} to Trash Bin.")
        return jsonify({"status":"success","message":"Document moved to Trash Bin."})
    if action == 'replace':
        upload=request.files.get('file')
        if not upload or not upload.filename:
            return jsonify({"error":"Select a replacement file."}),400
        ext=os.path.splitext(secure_filename(upload.filename))[1].lower()
        if ext not in ('.pdf','.jpg','.jpeg','.png'):
            return jsonify({"error":"Only PDF, JPG, JPEG and PNG files are allowed."}),400
        new_path=upload_file_to_github(upload,student.get('student_name','Student'),upload.filename)
        if not new_path:
            return jsonify({"error":"Unable to upload replacement document. Check GitHub configuration."}),502
        if top_level: student[field]=new_path
        if form_data_ref: student['form_data'][field]=new_path
        new_attachment={"field":field,"stored_name":new_path,"original_name":secure_filename(upload.filename),"extension":ext}
        if attachment:
            student['attachments']=[new_attachment if (isinstance(x,dict) and x.get('stored_name')==old_path) else x
                                    for x in student.get('attachments',[])]
        else:
            student.setdefault('attachments',[]).append(new_attachment)
        save_data(STUDENTS_FILE,students)
        if old_path and old_path != new_path:
            _delete_github_file_if_unreferenced(old_path,{"source_file":STUDENTS_FILE,"source_id":student_id})
        log_activity("Student Document Replaced",f"Replaced {field} document for student #{student_id}.")
        return jsonify({"status":"success","message":"Selected document replaced successfully.","document":new_attachment})
    return jsonify({"error":"Unsupported document action."}),400


@app.route('/api/college-file/<int:college_id>', methods=['GET'])
def college_file(college_id):
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    colleges = load_data(COLLEGES_FILE)
    target = next((c for c in colleges if c.get('id') == college_id), None)
    document = target.get('document') if target else None
    if not document or not document.get('stored_name'):
        return jsonify({"error": "No document found for this college."}), 404

    stored_name = document.get('stored_name', '')
    github_path = document.get('github_path') or (stored_name if stored_name.startswith('student/college/') else None)
    ext = (document.get('extension') or os.path.splitext(stored_name)[1]).lower()
    mimetype = 'application/pdf' if ext == '.pdf' else ('image/png' if ext == '.png' else 'image/jpeg')

    if github_path:
        try:
            file_bytes = get_college_file_from_github(github_path)
            return send_file(io.BytesIO(file_bytes), mimetype=mimetype,
                             as_attachment=request.args.get('download') == '1',
                             download_name=document.get('original_name') or os.path.basename(github_path))
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    # Backward compatibility: files uploaded by the older local-storage version.
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'college_uploads')
    legacy_path = os.path.join(upload_dir, os.path.basename(stored_name))
    if os.path.isfile(legacy_path):
        return send_file(legacy_path, mimetype=mimetype,
                         as_attachment=request.args.get('download') == '1',
                         download_name=document.get('original_name') or os.path.basename(stored_name), conditional=True)
    return jsonify({"error": "The stored college document was not found in GitHub or on this server."}), 404


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
        <img src="logo.png" class="logo-img" alt="CounselScope Logo">
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

        .sidebar { width: 255px; background-color: var(--sidebar-bg); color: #fff; display: flex; flex-direction: column; padding: 20px 15px; flex-shrink: 0; justify-content: space-between; transition: 0.3s ease; z-index: 1000; }
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
        .m-icon.red { background: #ffeeef; color: #dc2626; }
        .m-icon.indigo { background: #eef2ff; color: #6366f1; }
        .m-info h3 { font-size: 22px; font-weight: 800; color: var(--text-dark); }
        .m-info p { font-size: 11.5px; color: var(--text-muted); font-weight: 500; }

        .dashboard-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 25px; }
        .analytics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-top: 25px; }
        
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

        .modal-overlay { display: none; position: fixed; z-index: 2000; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); align-items: center; justify-content: center; backdrop-filter: blur(4px); padding: 15px; }
        .modal-content { background: white; padding: 25px; border-radius: 16px; max-width: 650px; width: 100%; text-align: left; position: relative; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); animation: modalPopup 0.3s cubic-bezier(0.16, 1, 0.3, 1); max-height: 90vh; overflow-y: auto; }
        @keyframes modalPopup { from { transform: scale(0.85); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        .close-modal { position: absolute; top: 15px; right: 20px; font-size: 22px; cursor: pointer; color: #64748b; transition: 0.2s; }
        .close-modal:hover { color: #0f172a; }

        .form-control { width: 100%; padding: 10px 12px; margin-bottom: 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13.5px; }
        .form-control:focus { outline: none; border-color: #2563eb; }

        /* Sidebar Backdrop Overlay for Mobile */
        .sidebar-backdrop {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            z-index: 900;
            backdrop-filter: blur(2px);
        }
        .sidebar-backdrop.show {
            display: block;
        }

        @media (max-width: 900px) {
            body { flex-direction: column; height: 100vh; overflow-x: hidden; overflow-y: auto; }
            .sidebar { 
                position: fixed; 
                top: 0; 
                left: -280px; 
                width: 260px; 
                height: 100vh; 
                flex-direction: column; 
                padding: 20px 15px; 
                box-shadow: 5px 0 25px rgba(0,0,0,0.5); 
                transition: left 0.3s ease;
            }
            .sidebar.show { left: 0; }
            .menu-toggle-btn { display: block; }
            .main-wrapper { height: 100vh; overflow-x: hidden; overflow-y: auto; width: 100%; max-width: 100vw; }
            .top-header { padding: 10px 15px; height: auto; flex-direction: column; align-items: stretch; gap: 10px; position: sticky; top: 0; width: 100%; box-sizing: border-box; }
            .header-left { justify-content: space-between; width: 100%; }
            .search-bar { width: 100%; max-width: 100%; box-sizing: border-box; order: 2; }
            .content-area { padding: 12px; gap: 15px; width: 100%; max-width: 100%; box-sizing: border-box; overflow-x: hidden; }
            .hero-banner { padding: 18px; flex-direction: column; align-items: flex-start; text-align: left; width: 100%; box-sizing: border-box; }
            .hero-text h1 { font-size: 20px; }
            .hero-text p { font-size: 12.5px; }
            .hero-banner > div:last-child { width: 100%; display: flex; flex-direction: column; gap: 8px; }
            .hero-banner a { width: 100%; justify-content: center; text-align: center; padding: 10px; box-sizing: border-box; }
            .metrics-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; width: 100%; }
            .metric-card { padding: 12px; gap: 10px; width: 100%; box-sizing: border-box; }
            .m-icon { width: 36px; height: 36px; font-size: 15px; flex-shrink: 0; }
            .m-info h3 { font-size: 18px; }
            .m-info p { font-size: 11px; }
            .analytics-grid { grid-template-columns: 1fr; gap: 15px; width: 100%; }
            .dashboard-grid { grid-template-columns: 1fr; gap: 15px; width: 100%; }
            .card { padding: 16px; width: 100%; box-sizing: border-box; overflow-x: hidden; }
            .card-header h3 { font-size: 14px; }
            .chart-container { height: 190px; width: 100%; max-width: 100%; }
            table { font-size: 12px; width: 100%; }
            th, td { padding: 8px 10px; }
            .modal-content { max-width: 95vw !important; padding: 18px; margin: 10px; max-height: 85vh; }
        }
    </style>
</head>
<body>

    <!-- Sidebar Backdrop Overlay -->
    <div class="sidebar-backdrop" id="sidebarBackdrop" onclick="toggleSidebar()"></div>

    <aside class="sidebar" id="sidebarNav">
        <div>
            <div class="sidebar-brand">
                <img src="logo.png" alt="Logo">
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
                    <div style="display:flex; gap:10px; flex-wrap:wrap;">
                        <a href="/api/export-full-excel" style="background:#16a34a; color:white; border:none; padding:10px 16px; border-radius:10px; font-weight:700; text-decoration:none; font-size:13px; display:inline-flex; align-items:center; gap:8px;"><i class="fa-solid fa-file-excel"></i> Export Complete Excel</a>
                        <a href="/api/export-full-pdf" target="_blank" style="background:#dc2626; color:white; border:none; padding:10px 16px; border-radius:10px; font-weight:700; text-decoration:none; font-size:13px; display:inline-flex; align-items:center; gap:8px;"><i class="fa-solid fa-file-pdf"></i> Export Complete PDF</a>
                    </div>
                </div>

                <div class="metrics-grid" style="margin-bottom: 25px;">
                    <div class="metric-card"><div class="m-icon blue"><i class="fa-solid fa-users"></i></div><div class="m-info"><h3 id="statTotal">0</h3><p>Total Leads</p></div></div>
                    <div class="metric-card"><div class="m-icon green"><i class="fa-solid fa-user-graduate"></i></div><div class="m-info"><h3 id="statStudents">0</h3><p>Registered Students</p></div></div>
                    <div class="metric-card"><div class="m-icon orange"><i class="fa-solid fa-phone-volume"></i></div><div class="m-info"><h3 id="statContacted">0</h3><p>Contacted</p></div></div>
                    <div class="metric-card"><div class="m-icon purple"><i class="fa-solid fa-spinner"></i></div><div class="m-info"><h3 id="statNew">0</h3><p>New Leads</p></div></div>
                    <div class="metric-card"><div class="m-icon indigo"><i class="fa-solid fa-calendar-days"></i></div><div class="m-info"><h3 id="statFollowUp">0</h3><p>Follow-Up Leads</p></div></div>
                    <div class="metric-card"><div class="m-icon red"><i class="fa-solid fa-ban"></i></div><div class="m-info"><h3 id="statRejected">0</h3><p>Rejected Leads</p></div></div>
                </div>

                <div class="analytics-grid" style="margin-bottom: 25px;">
                    <div class="card">
                        <div class="card-header">
                            <h3>This Week – Lead Statistics</h3>
                            <span id="weekRangeLabel" style="font-size: 11.5px; color: var(--text-muted); font-weight: 600;"></span>
                        </div>
                        <div class="chart-container"><canvas id="weeklyPieChart"></canvas></div>
                        <div style="text-align: center; margin-top: 10px; font-size: 12.5px; color: var(--text-muted);">Total Leads This Week: <strong id="weekTotalCount" style="color: var(--primary);">0</strong></div>
                    </div>

                    <div class="card">
                        <div class="card-header">
                            <h3>This Month – Lead Statistics</h3>
                            <span id="monthRangeLabel" style="font-size: 11.5px; color: var(--text-muted); font-weight: 600;"></span>
                        </div>
                        <div class="chart-container"><canvas id="monthlyPieChart"></canvas></div>
                        <div style="text-align: center; margin-top: 10px; font-size: 12.5px; color: var(--text-muted);">Total Leads This Month: <strong id="monthTotalCount" style="color: var(--primary);">0</strong></div>
                    </div>

                    <div class="card">
                        <div class="card-header">
                            <h3>This Year – Lead Statistics</h3>
                            <span id="yearRangeLabel" style="font-size: 11.5px; color: var(--text-muted); font-weight: 600;"></span>
                        </div>
                        <div class="chart-container"><canvas id="yearlyPieChart"></canvas></div>
                        <div style="text-align: center; margin-top: 10px; font-size: 12.5px; color: var(--text-muted);">Total Leads This Year: <strong id="yearTotalCount" style="color: var(--primary);">0</strong></div>
                    </div>
                </div>

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
                                        <th>Course</th>
                                        <th>Details</th>
                                        <th>Status</th>
                                        {% if role == 'Admin' %}<th>Action</th>{% endif %}
                                    </tr>
                                </thead>
                                <tbody id="recentLeadsTbody"></tbody>
                            </table>
                        </div>
                    </div>
                    <div class="card">
                        <div class="card-header"><h3>Overall Leads Overview Chart</h3></div>
                        <div class="chart-container"><canvas id="leadsPieChart"></canvas></div>
                        <div id="leadsPieSummary" style="margin-top:12px;font-size:12px;line-height:1.8;color:var(--text-muted);"></div>
                    </div>
                </div>
            </div>

            <!-- ALL LEADS TAB -->
            <div id="leads-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <h3><i class="fa-solid fa-users"></i> All Leads Management</h3>
                    </div>
                    <div style="background: #f8fafc; padding: 15px; border-radius: 10px; border: 1px solid var(--border-color); display: flex; gap: 12px; flex-wrap: wrap; align-items: center;">
                        <button onclick="downloadLeadsPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Download Leads PDF</button>
                        {% if role == 'Admin' %}
                        <button onclick="deleteSelectedLeads()" style="background: #ef4444; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-trash-can"></i> Delete Selected Leads</button>
                        {% endif %}
                    </div>
                    <div style="background:#f8fafc; padding:15px; border:1px solid var(--border-color); border-radius:10px; margin-top:12px;">
                        <div style="display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end;">
                            <div style="min-width:220px; flex:1;">
                                <label for="leadStatusFilter" style="display:block; font-size:12px; font-weight:700; margin-bottom:6px;">Lead Status (select multiple)</label>
                                <select id="leadStatusFilter" class="form-control" multiple size="5" onchange="applyAllLeadsFilters()" style="min-height:112px;">
                                    <option value="Contacted">Contact</option>
                                    <option value="Follow Up">Follow Up</option>
                                    <option value="Rejected">Rejected</option>
                                    <option value="Closed">Closed</option>
                                    <option value="New Lead">New Lead</option>
                                </select>
                                <small style="color:#64748b;">Use Ctrl (Windows) / Command (Mac) to select multiple statuses.</small>
                            </div>
                            <div style="min-width:155px;">
                                <label for="leadStartDate" style="display:block; font-size:12px; font-weight:700; margin-bottom:6px;">Start Date</label>
                                <input type="date" id="leadStartDate" class="form-control" onchange="applyAllLeadsFilters()">
                            </div>
                            <div style="min-width:155px;">
                                <label for="leadEndDate" style="display:block; font-size:12px; font-weight:700; margin-bottom:6px;">End Date</label>
                                <input type="date" id="leadEndDate" class="form-control" onchange="applyAllLeadsFilters()">
                            </div>
                            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                                <button onclick="resetAllLeadsFilters()" style="background:#64748b; color:white; border:none; padding:10px 14px; border-radius:8px; font-weight:600; cursor:pointer;"><i class="fa-solid fa-rotate-left"></i> Clear Filters</button>
                                <button onclick="downloadFilteredLeadsCSV()" style="background:#16a34a; color:white; border:none; padding:10px 14px; border-radius:8px; font-weight:600; cursor:pointer;"><i class="fa-solid fa-file-csv"></i> Download CSV</button>
                                {% if role == 'Admin' %}
                                <button onclick="deleteFilteredLeads()" style="background:#b91c1c; color:white; border:none; padding:10px 14px; border-radius:8px; font-weight:600; cursor:pointer;"><i class="fa-solid fa-trash-can"></i> Delete Filtered Leads</button>
                                {% endif %}
                            </div>
                        </div>
                        <div id="allLeadsFilterSummary" style="margin-top:10px; color:#475569; font-size:12px; font-weight:600;">Showing all active leads.</div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header"><h3>Registered Leads Directory</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    {% if role == 'Admin' %}<th><input type="checkbox" onclick="toggleSelectAll('leads', this)"></th>{% endif %}
                                    <th>#ID</th>
                                    <th>Student Name</th>
                                    <th>Contact</th>
                                    <th>Email ID</th>
                                    <th>Course</th>
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
                    </div>
                    <div style="background: #f8fafc; padding: 15px; border-radius: 10px; border: 1px solid var(--border-color); display: flex; gap: 12px; flex-wrap: wrap; align-items: center;">
                        <button onclick="downloadStudentsPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Download Students PDF</button>
                        {% if role == 'Admin' %}
                        <button onclick="deleteSelectedStudents()" style="background: #ef4444; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-trash-can"></i> Delete Selected Students</button>
                        {% endif %}
                    </div>
                </div>
                <div class="card">
                    <div class="card-header"><h3>Students Directory</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    {% if role == 'Admin' %}<th><input type="checkbox" onclick="toggleSelectAll('students', this)"></th>{% endif %}
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
                                <tr><td colspan="8" style="text-align:center; color:#94a3b8;">No registered students yet. Convert leads from All Leads tab.</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- WORK HISTORY TAB -->
            <div id="history-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <h3><i class="fa-solid fa-clock-rotate-left"></i> Synchronized Activity Logs & Work History</h3>
                    </div>
                    <div style="background: #f8fafc; padding: 15px; border-radius: 10px; border: 1px solid var(--border-color); display: flex; gap: 12px; flex-wrap: wrap; align-items: center;">
                        <label>Particular Date <input type="date" id="historySingleDate" class="form-control" onchange="setSingleDateFilter('history')"></label>
                        <label>Start Date <input type="date" id="historyStartDate" class="form-control" onchange="applyHistoryFilters()"></label>
                        <label>End Date <input type="date" id="historyEndDate" class="form-control" onchange="applyHistoryFilters()"></label>
                        <button onclick="resetHistoryFilters()" style="background:#64748b;color:white;border:0;padding:10px 14px;border-radius:8px;">Clear Filters</button>
                        <span id="historyFilterSummary" style="font-size:12px;font-weight:600;color:#475569;"></span>
                        <button onclick="downloadHistoryPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Download Work History PDF</button>
                        {% if role == 'Admin' %}
                        <button onclick="deleteSelectedHistory()" style="background: #ef4444; color: white; border: none; padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-trash-can"></i> Delete Selected Work History</button>
                        {% endif %}
                    </div>
                </div>
                <div class="card">
                    <div class="card-header"><h3>Activity Records</h3></div>
                    <div style="overflow-x: auto;">
                        <table>
                            <thead>
                                <tr>
                                    {% if role == 'Admin' %}<th><input type="checkbox" onclick="toggleSelectAll('history', this)"></th>{% endif %}
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
                    <h3 id="collegeFormHeading">Add New College</h3>
                    <form id="collegeForm" onsubmit="saveCollege(event)" enctype="multipart/form-data">
                        <input type="hidden" id="collegeEditId" value="">
                        <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin-top:15px;">
                            <div><label for="colName">College Name *</label><input type="text" id="colName" class="form-control" required placeholder="College Name" style="margin:0;"></div>
                            <div><label for="colLoc">Address</label><input type="text" id="colLoc" class="form-control" placeholder="Full address" style="margin:0;"></div>
                            <div><label for="colPhone">Phone Number</label><input type="tel" id="colPhone" class="form-control" placeholder="Phone number" style="margin:0;"></div>
                            <div><label for="colEmail">Email Address</label><input type="email" id="colEmail" class="form-control" placeholder="Email address" style="margin:0;"></div>
                        </div>
                        <div style="margin-top:14px;">
                            <label for="colDescription">Description</label>
                            <textarea id="colDescription" class="form-control" rows="4" placeholder="College description" style="width:100%; resize:vertical;"></textarea>
                        </div>
                        <div style="margin-top:14px;">
                            <label for="colFile">Upload Document / Image (JPG, JPEG, PNG, PDF)</label>
                            <input type="file" id="colFile" class="form-control" accept=".jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf" style="margin:0;">
                            <small id="collegeCurrentFile" style="display:block;color:#64748b;margin-top:6px;"></small>
                        </div>
                        <div style="display:flex;gap:10px;margin-top:16px;flex-wrap:wrap;">
                            <button type="submit" id="collegeSaveBtn" style="background:#2563eb;color:white;border:none;border-radius:8px;font-weight:600;cursor:pointer;padding:10px 20px;">Save College</button>
                            <button type="button" id="collegeCancelEdit" onclick="resetCollegeForm()" style="display:none;background:#64748b;color:white;border:none;border-radius:8px;font-weight:600;cursor:pointer;padding:10px 20px;">Cancel Edit</button>
                        </div>
                    </form>
                </div>
                {% endif %}

                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header"><h3>College Directory Export & Management</h3></div>
                    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
                        <button onclick="downloadCollegePDF()" style="background:#dc2626;color:white;border:none;padding:10px 18px;border-radius:8px;font-weight:600;cursor:pointer;font-size:13px;"><i class="fa-solid fa-file-pdf"></i> Download College PDF</button>
                        {% if role == 'Admin' %}
                        <button onclick="deleteSelectedColleges()" style="background:#ef4444;color:white;border:none;padding:10px 18px;border-radius:8px;font-weight:600;cursor:pointer;font-size:13px;"><i class="fa-solid fa-trash-can"></i> Delete Selected Colleges</button>
                        {% endif %}
                    </div>
                </div>

                <div class="card">
                    <div class="card-header"><h3>Partner Colleges List</h3></div>
                    <div style="overflow-x:auto;">
                        <table>
                            <thead>
                                <tr>
                                    {% if role == 'Admin' %}<th><input type="checkbox" onclick="toggleSelectAll('colleges', this)"></th>{% endif %}
                                    <th>#ID</th><th>College Name</th><th>Address</th><th>Phone</th><th>Email</th><th>Description</th><th>Document</th>
                                    {% if role == 'Admin' %}<th>Action</th>{% endif %}
                                </tr>
                            </thead>
                            <tbody id="collegesTbody"></tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- College document preview modal (Colleges Manager only) -->
            <div id="collegePreviewModal" style="display:none;position:fixed;inset:0;background:rgba(15,23,42,.72);z-index:9999;align-items:center;justify-content:center;padding:18px;" onclick="if(event.target===this) closeCollegePreview();">
                <div style="background:#fff;width:min(850px,96vw);height:min(650px,90vh);border-radius:14px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.3);">
                    <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #e2e8f0;">
                        <strong id="collegePreviewTitle" style="color:#0f172a;">College Document</strong>
                        <div style="display:flex;gap:8px;align-items:center;">
                            <a id="collegePreviewDownload" href="#" download style="display:none;background:#2563eb;color:#fff;padding:8px 12px;border-radius:7px;text-decoration:none;font-size:13px;">Download</a>
                            <button type="button" onclick="closeCollegePreview()" style="background:#64748b;color:white;border:0;border-radius:7px;padding:8px 12px;cursor:pointer;">Close</button>
                        </div>
                    </div>
                    <div id="collegePreviewBody" style="flex:1;min-height:0;display:flex;align-items:center;justify-content:center;background:#f1f5f9;padding:10px;overflow:auto;"></div>
                </div>
            </div>

                        <!-- TRASH BIN TAB -->
            <div id="trash-tab" class="tab-section">
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header"><h3 style="color: #ef4444;"><i class="fa-solid fa-trash-can"></i> Trash Bin Management</h3></div>
                    <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
                        <label>Particular Date <input type="date" id="trashSingleDate" class="form-control" onchange="setSingleDateFilter('trash')"></label>
                        <label>Start Date <input type="date" id="trashStartDate" class="form-control" onchange="applyTrashFilters()"></label>
                        <label>End Date <input type="date" id="trashEndDate" class="form-control" onchange="applyTrashFilters()"></label>
                        <button onclick="resetTrashFilters()" style="background:#64748b;color:white;border:0;padding:10px 14px;border-radius:8px;">Clear Filters</button>
                        <button onclick="downloadAllFilteredTrash()" style="background:#2563eb;color:white;border:0;padding:10px 14px;border-radius:8px;">Download Filtered PDF</button>
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
                                    <th>Category</th>
                                    <th>Record ID</th>
                                    <th>Record Details</th>
                                    <th>Contact</th>
                                    <th>Email</th>
                                    <th>Deleted Date</th>
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
                {% if role == 'Admin' %}
                <div class="card" style="margin-bottom: 25px; border-left: 5px solid #2563eb;">
                    <div class="card-header">
                        <h3 style="color: #2563eb;"><i class="fa-solid fa-key" style="margin-right: 8px;"></i> Admin Password Management</h3>
                    </div>
                    <p style="font-size: 12.5px; color: var(--text-muted); margin-bottom: 15px;">Update passwords securely using the application's hashing mechanism.</p>
                    <form onsubmit="handleAdminPasswordChange(event)" style="max-width: 450px;">
                        <label style="font-size: 12px; font-weight: 600; color: var(--text-dark);">Select Account to Update</label>
                        <select id="pwdTargetUser" class="form-control">
                            <option value="admin">Admin Account (admin)</option>
                            <option value="client">Client Account (client)</option>
                        </select>
                        <label style="font-size: 12px; font-weight: 600; color: var(--text-dark);">New Password</label>
                        <input type="password" id="pwdNewPassword" class="form-control" required placeholder="Enter new secure password">
                        <button type="submit" style="background: #2563eb; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;">Update Password</button>
                    </form>
                </div>
                {% endif %}

                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header"><h3><i class="fa-solid fa-gear"></i> System Settings & Login Activity Logs</h3></div>
                    
                    <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 20px;">
                        <label>Particular Date <input type="date" id="logsSingleDate" class="form-control" onchange="setSingleDateFilter('logs')"></label>
                        <label>Start Date <input type="date" id="logsStartDate" class="form-control" onchange="applyLogsFilters()"></label>
                        <label>End Date <input type="date" id="logsEndDate" class="form-control" onchange="applyLogsFilters()"></label>
                        <label>User Type <select id="logsUserType" class="form-control" onchange="applyLogsFilters()"><option>All Users</option><option>Admin</option><option>Client</option></select></label>
                        <button onclick="resetLogsFilters()" style="background:#64748b;color:white;border:0;padding:10px 14px;border-radius:8px;">Clear Filters</button>
                        <button onclick="downloadLogsPDF()" style="background: #dc2626; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-file-pdf"></i> Export Activity Logs PDF</button>
                        {% if role == 'Admin' %}
                        <button onclick="deleteSelectedLogs()" style="background: #ef4444; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-trash-can"></i> Delete Selected Logs</button>
                        <button onclick="clearAllLogs()" style="background: #ef4444; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 13px;"><i class="fa-solid fa-dumpster"></i> Clear All Logs</button>
                        {% endif %}
                    </div>

                    <h4 style="font-size: 14px; margin-bottom: 12px; color: var(--text-dark);"><i class="fa-solid fa-list-check"></i> Complete Login Activity Logs</h4>
                    <div style="overflow-x: auto; max-height: 480px;">
                        <table>
                            <thead>
                                <tr>
                                    {% if role == 'Admin' %}<th><input type="checkbox" onclick="toggleSelectAll('logs', this)"></th>{% endif %}
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
                                <tr><td colspan="10" style="text-align:center; color:#94a3b8;">Loading logs...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- ORGANIZED STUDENT DETAILS & DOCUMENT MODAL -->
    <div id="docModal" class="modal-overlay">
        <div class="modal-content" style="max-width: 750px;">
            <span class="close-modal" onclick="closeDocModal()">&times;</span>
            <h3 style="margin-bottom: 15px; color: #1e293b; font-size: 18px; border-bottom: 1px solid #e2e8f0; padding-bottom: 10px;"><i class="fa-solid fa-user-graduate" style="color:#2563eb; margin-right:8px;"></i> Organized Student Registration & Document View</h3>
            <div id="modalBodyContainer"></div>
        </div>
    </div>

    <!-- COMPREHENSIVE EDIT LEAD MODAL -->
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
                <div id="studentStructuredFields" style="margin-top:14px;"></div>
                <div style="margin-top:14px;border:1px solid #e2e8f0;border-radius:9px;padding:12px;">
                    <h4 style="margin:0 0 8px;color:#2563eb;font-size:13px;">Student Documents</h4>
                    <div id="studentEditDocumentControls" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;"></div>
                    <label style="font-size:12px;font-weight:600;">Upload New Document</label>
                    <input type="file" id="studentNewDocumentFile" accept=".pdf,.jpg,.jpeg,.png" style="width:100%;margin-top:5px;">
                    <button type="button" onclick="uploadNewStudentDocument()" style="margin-top:8px;background:#2563eb;color:#fff;border:0;padding:7px 10px;border-radius:6px;cursor:pointer;">Upload Document</button>
                </div>
                <div style="margin-top:14px;">
                    <button type="button" onclick="document.getElementById('studentAdvancedFields').style.display=document.getElementById('studentAdvancedFields').style.display==='none'?'block':'none';" style="background:#64748b;color:white;border:0;padding:7px 10px;border-radius:6px;cursor:pointer;">Show / Hide Advanced Registration Data</button>
                    <div id="studentAdvancedFields" style="display:none;margin-top:8px;">
                        <label style="font-size:12px;font-weight:700;">Complete Saved Registration Data (JSON backup/editor)</label>
                        <textarea id="student_all_data_json" class="form-control" rows="12" style="width:100%;font-family:monospace;font-size:12px;white-space:pre;" spellcheck="false"></textarea>
                        <small style="color:#64748b;">All original fields and nested form_data are retained. Structured fields above are synchronized when saving.</small>
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
        let weeklyPieInstance = null;
        let monthlyPieInstance = null;
        let yearlyPieInstance = null;
        const userRole = "{{ role }}";

        function toggleSidebar() {
            document.getElementById('sidebarNav').classList.toggle('show');
            document.getElementById('sidebarBackdrop').classList.toggle('show');
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
            if(tabId === 'trash-tab') fetchTrashData();
            if(window.innerWidth <= 900) {
                document.getElementById('sidebarNav').classList.remove('show');
                document.getElementById('sidebarBackdrop').classList.remove('show');
            }
        }

        function toggleSelectAll(section, masterCb) {
            document.querySelectorAll(`.${section}-checkbox`).forEach(cb => cb.checked = masterCb.checked);
        }

        async function fetchLeadsData() {
            try {
                const res = await fetch('/api/get-leads');
                if(res.ok) {
                    rawLeadsData = await res.json();
                    renderUI(rawLeadsData);
                    fetchTrashData();
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
            const tbody = document.getElementById('settingsLogsTbody'); if(!tbody) return;
            try { const res=await fetch('/api/get-logs'); if(res.ok){rawLogsData=await res.json();applyLogsFilters();} }
            catch(e){tbody.innerHTML='<tr><td colspan="10" style="text-align:center;color:#ef4444;">Failed to load logs.</td></tr>';}
        }


        let rawHistoryData = [];
        let rawTrashData = [];
        let rawLogsData = [];
        function setSingleDateFilter(kind) {
            const date=document.getElementById(kind+'SingleDate').value;
            document.getElementById(kind+'StartDate').value=date;
            document.getElementById(kind+'EndDate').value=date;
            if(kind==='history') applyHistoryFilters(); else if(kind==='trash') applyTrashFilters(); else applyLogsFilters();
        }
        function dateInRange(value,start,end){const raw=String(value||'').trim();let d=/^\\d{4}-\\d{2}-\\d{2}/.test(raw)?raw.slice(0,10):'';if(!d){const m=raw.match(/^(\\d{1,2})\\s+([A-Za-z]{3})\\s+(\\d{4})/);if(m){const months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];const month=months.findIndex(x=>x.toLowerCase()===m[2].toLowerCase())+1;if(month)d=`${m[3]}-${String(month).padStart(2,'0')}-${String(Number(m[1])).padStart(2,'0')}`;}}return !!d&&(!start||d>=start)&&(!end||d<=end);}
        function applyHistoryFilters(){const start=document.getElementById('historyStartDate').value,end=document.getElementById('historyEndDate').value;if(start&&end&&start>end){alert('Start Date cannot be after End Date.');return;}const rows=rawHistoryData.filter(x=>!start&&!end||dateInRange(x.date||x.created_date||x.created_at,start,end));renderHistoryRows(rows);document.getElementById('historyFilterSummary').textContent=`Showing ${rows.length} of ${rawHistoryData.length} work history records.`;}
        function resetHistoryFilters(){['historySingleDate','historyStartDate','historyEndDate'].forEach(id=>document.getElementById(id).value='');applyHistoryFilters();}
        function applyTrashFilters(){const start=document.getElementById('trashStartDate').value,end=document.getElementById('trashEndDate').value;if(start&&end&&start>end){alert('Start Date cannot be after End Date.');return;}const rows=rawTrashData.filter(x=>!start&&!end||dateInRange(x.deleted_date||x.deleted_at,start,end));populateTrashTable(rows);}
        function resetTrashFilters(){['trashSingleDate','trashStartDate','trashEndDate'].forEach(id=>document.getElementById(id).value='');applyTrashFilters();}
        function applyLogsFilters(){const start=document.getElementById('logsStartDate').value,end=document.getElementById('logsEndDate').value;if(start&&end&&start>end){alert('Start Date cannot be after End Date.');return;}const role=document.getElementById('logsUserType').value;const rows=rawLogsData.filter(x=>(role==='All Users'||String(x.role||'').toLowerCase()===role.toLowerCase())&&(!start&&!end||[x.login_date,x.logout_date].some(v=>dateInRange(v,start,end))));renderLoginLogRows(rows);}
        function resetLogsFilters(){['logsSingleDate','logsStartDate','logsEndDate'].forEach(id=>document.getElementById(id).value='');document.getElementById('logsUserType').value='All Users';applyLogsFilters();}
        function downloadAllFilteredTrash(){const q=new URLSearchParams();const a=document.getElementById('trashStartDate').value,b=document.getElementById('trashEndDate').value;if(a)q.set('start_date',a);if(b)q.set('end_date',b);window.open('/api/export-filtered-trash-pdf?'+q.toString(),'_blank');}
        function renderLoginLogRows(logs){const tbody=document.getElementById('settingsLogsTbody');tbody.innerHTML='';if(!logs.length){tbody.innerHTML='<tr><td colspan="10" style="text-align:center;color:#94a3b8;">No matching login activity logs.</td></tr>';return;}logs.forEach(log=>{const badge=log.status==='Active'?'<span class="badge-status badge-closed">Active</span>':(log.status==='Failed'?'<span class="badge-status badge-rejected">Failed</span>':'<span class="badge-status badge-contacted">Logged Out</span>');const cb=userRole==='Admin'?`<td><input type="checkbox" class="logs-checkbox" value="${log.id}"></td>`:'';tbody.innerHTML+=`<tr>${cb}<td>#${log.id}</td><td><strong>${log.username||''}</strong></td><td><span class="badge-status badge-followup">${log.role||'N/A'}</span></td><td><code>${log.ip_address||''}</code></td><td>${log.browser||'Unknown'} / ${log.os||'Unknown'}</td><td><small>${log.location||'Unknown'}</small></td><td>${log.login_time||'N/A'}</td><td>${log.logout_time||'N/A'}</td><td>${badge}</td></tr>`;});}
        function renderHistoryRows(history){const tbody=document.getElementById('historyTbody');tbody.innerHTML='';if(!history.length){tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:#94a3b8;">No matching activity logged.</td></tr>';return;}history.slice().reverse().forEach(item=>{const cb=userRole==='Admin'?`<td><input type="checkbox" class="history-checkbox" value="${item.id}"></td>`:'';tbody.innerHTML+=`<tr>${cb}<td><strong>${item.username||'Admin'}</strong></td><td><span class="badge-status badge-followup">${item.role||'Admin'}</span></td><td><strong style="color:#2563eb;">${item.date||''} ${item.time||''}</strong></td><td><span class="badge-status badge-new">${item.action_type||''}</span></td><td>${item.details||''}</td></tr>`;});}

        async function handleAdminPasswordChange(e) {
            e.preventDefault();
            const targetUser = document.getElementById('pwdTargetUser').value;
            const newPassword = document.getElementById('pwdNewPassword').value;
            
            const res = await fetch('/api/admin/change-password', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target_user: targetUser, new_password: newPassword})
            });
            const result = await res.json();
            if(res.ok) {
                alert(result.message);
                document.getElementById('pwdNewPassword').value = '';
            } else {
                alert('Error: ' + result.message);
            }
        }

        async function fetchWorkHistory() {
            const res=await fetch('/api/get-history');
            if(res.ok){rawHistoryData=await res.json();applyHistoryFilters();}
        }


        async function fetchColleges() {
            const res = await fetch('/api/get-colleges');
            if(res.ok) {
                collegesData = await res.json();
                const tbody = document.getElementById('collegesTbody');
                tbody.innerHTML = '';
                collegesData.forEach(c => {
                    const cbHtml = userRole === 'Admin' ? `<td><input type="checkbox" class="colleges-checkbox" value="${c.id}"></td>` : '';
                    const doc = c.document || null;
                    const fileHtml = doc ? `<button type="button" onclick="openCollegePreview(${c.id})" style="border:0;background:#e0edff;color:#1d4ed8;padding:6px 10px;border-radius:7px;cursor:pointer;"> <i class="fa-solid fa-eye"></i> View</button>` : '<span style="color:#94a3b8;">No file</span>';
                    const actionHtml = userRole === 'Admin' ? `<td><button type="button" onclick="editCollegeRecord(${c.id})" class="action-icon-btn" title="Edit" style="color:#2563eb;"><i class="fa-solid fa-pen-to-square"></i></button> <button type="button" onclick="deleteCollegeRecord(${c.id})" class="action-icon-btn trash-btn" title="Delete"><i class="fa-solid fa-trash-can"></i></button></td>` : '';
                    const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
                    tbody.innerHTML += `<tr>${cbHtml}<td>#${c.id}</td><td><strong>${esc(c.college_name)}</strong></td><td>${esc(c.address ?? c.location ?? '')}</td><td>${esc(c.phone || '')}</td><td>${esc(c.email || '')}</td><td style="max-width:240px;white-space:normal;">${esc(c.description || '')}</td><td>${fileHtml}</td>${actionHtml}</tr>`;
                });
                populateCollegeDropdowns();
            }
        }

        function resetCollegeForm() {
            const form = document.getElementById('collegeForm');
            if(form) form.reset();
            document.getElementById('collegeEditId').value = '';
            document.getElementById('collegeFormHeading').textContent = 'Add New College';
            document.getElementById('collegeSaveBtn').textContent = 'Save College';
            document.getElementById('collegeCancelEdit').style.display = 'none';
            document.getElementById('collegeCurrentFile').textContent = '';
        }

        function editCollegeRecord(id) {
            const c = collegesData.find(item => item.id === id);
            if(!c) return;
            document.getElementById('collegeEditId').value = c.id;
            document.getElementById('colName').value = c.college_name || '';
            document.getElementById('colLoc').value = c.address ?? c.location ?? '';
            document.getElementById('colPhone').value = c.phone || '';
            document.getElementById('colEmail').value = c.email || '';
            document.getElementById('colDescription').value = c.description || '';
            document.getElementById('colFile').value = '';
            document.getElementById('collegeCurrentFile').textContent = c.document ? 'Current file: ' + (c.document.original_name || 'Uploaded file') + ' (choose a file only to replace it)' : 'No file currently uploaded.';
            document.getElementById('collegeFormHeading').textContent = 'Edit College #' + c.id;
            document.getElementById('collegeSaveBtn').textContent = 'Update College';
            document.getElementById('collegeCancelEdit').style.display = 'inline-block';
            document.getElementById('collegeForm').scrollIntoView({behavior:'smooth',block:'center'});
        }

        async function saveCollege(event) {
            event.preventDefault();
            const id = document.getElementById('collegeEditId').value;
            const formData = new FormData();
            formData.append('college_name', document.getElementById('colName').value.trim());
            formData.append('address', document.getElementById('colLoc').value);
            formData.append('phone', document.getElementById('colPhone').value);
            formData.append('email', document.getElementById('colEmail').value);
            formData.append('description', document.getElementById('colDescription').value);
            const file = document.getElementById('colFile').files[0];
            if(file) formData.append('college_file', file);
            const endpoint = id ? `/api/update-college/${id}` : '/api/add-college';
            const res = await fetch(endpoint, {method:'POST', body:formData});
            const result = await res.json();
            if(!res.ok) { alert(result.message || result.error || 'Unable to save college.'); return; }
            resetCollegeForm();
            await fetchColleges();
            alert(result.message || 'College saved successfully.');
        }

        function openCollegePreview(id) {
            const college = collegesData.find(item => item.id === id);
            if(!college || !college.document) return;
            const ext = (college.document.extension || '').toLowerCase();
            const url = `/api/college-file/${id}`;
            const body = document.getElementById('collegePreviewBody');
            body.innerHTML = '';
            document.getElementById('collegePreviewTitle').textContent = college.document.original_name || college.college_name;
            const download = document.getElementById('collegePreviewDownload');
            download.href = url + '?download=1';
            download.style.display = 'inline-block';
            if(ext === '.pdf') {
                const frame = document.createElement('iframe');
                frame.src = url;
                frame.title = 'College PDF preview';
                frame.style.cssText = 'width:100%;height:100%;border:0;background:white;';
                body.appendChild(frame);
            } else {
                const image = document.createElement('img');
                image.src = url;
                image.alt = college.document.original_name || college.college_name;
                image.style.cssText = 'max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;display:block;';
                body.appendChild(image);
            }
            document.getElementById('collegePreviewModal').style.display = 'flex';
        }

        function closeCollegePreview() {
            document.getElementById('collegePreviewModal').style.display = 'none';
            document.getElementById('collegePreviewBody').innerHTML = '';
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
            const form = document.getElementById('collegeForm');
            if(form) return form.requestSubmit();
        }

        async function deleteCollegeRecord(id) {
            if(confirm("Are you sure you want to delete this college record?")) {
                const res = await fetch('/api/delete-selected-colleges', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({college_ids: [id]})
                });
                if(res.ok) { alert('College moved to Trash Bin.'); fetchColleges(); fetchTrashData(); }
                else { alert('Unauthorized.'); }
            }
        }

        function getAllLeadsFilterValues() {
            const statusSelect = document.getElementById('leadStatusFilter');
            const statuses = statusSelect
                ? Array.from(statusSelect.selectedOptions).map(option => option.value)
                : [];
            return {
                statuses,
                start_date: document.getElementById('leadStartDate')?.value || '',
                end_date: document.getElementById('leadEndDate')?.value || ''
            };
        }

        function getLeadCreatedDateValue(lead) {
            const raw = String(lead.created_date || '').trim();
            if (/^\\d{4}-\\d{2}-\\d{2}$/.test(raw)) return raw;
            const createdAt = String(lead.created_at || '').trim();
            const parsed = new Date(createdAt);
            if (!Number.isNaN(parsed.getTime())) {
                const y = parsed.getFullYear();
                const m = String(parsed.getMonth() + 1).padStart(2, '0');
                const d = String(parsed.getDate()).padStart(2, '0');
                return `${y}-${m}-${d}`;
            }
            const match = createdAt.match(/^(\\d{1,2})\\s+([A-Za-z]{3})\\s+(\\d{4})/);
            if (match) {
                const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                const month = months.findIndex(v => v.toLowerCase() === match[2].toLowerCase()) + 1;
                if (month > 0) return `${match[3]}-${String(month).padStart(2,'0')}-${String(Number(match[1])).padStart(2,'0')}`;
            }
            return '';
        }

        function getFilteredAllLeads() {
            const filters = getAllLeadsFilterValues();
            const active = rawLeadsData.filter(lead => !lead.is_deleted);
            return active.filter(lead => {
                if (filters.statuses.length && !filters.statuses.includes(lead.status)) return false;
                const created = getLeadCreatedDateValue(lead);
                if (filters.start_date && (!created || created < filters.start_date)) return false;
                if (filters.end_date && (!created || created > filters.end_date)) return false;
                return true;
            });
        }

        function applyAllLeadsFilters() {
            const start = document.getElementById('leadStartDate')?.value || '';
            const end = document.getElementById('leadEndDate')?.value || '';
            if (start && end && start > end) {
                alert('Start date cannot be after end date.');
                document.getElementById('leadEndDate').value = '';
            }
            const filtered = getFilteredAllLeads();
            populateAllLeadsTable(filtered);
            const summary = document.getElementById('allLeadsFilterSummary');
            if (summary) {
                const filters = getAllLeadsFilterValues();
                const parts = [];
                if (filters.statuses.length) parts.push(`Statuses: ${filters.statuses.map(v => v === 'Contacted' ? 'Contact' : v).join(', ')}`);
                if (filters.start_date || filters.end_date) parts.push(`Dates: ${filters.start_date || 'Any'} to ${filters.end_date || 'Any'}`);
                summary.textContent = `Showing ${filtered.length} of ${rawLeadsData.filter(l => !l.is_deleted).length} active leads${parts.length ? ' • ' + parts.join(' • ') : ' • No filters applied'}.`;
            }
            const master = document.querySelector('#leads-tab thead input[type="checkbox"]');
            if (master) master.checked = false;
            filterLeadsTable();
        }

        function resetAllLeadsFilters() {
            const statusSelect = document.getElementById('leadStatusFilter');
            if (statusSelect) Array.from(statusSelect.options).forEach(option => option.selected = false);
            const start = document.getElementById('leadStartDate');
            const end = document.getElementById('leadEndDate');
            if (start) start.value = '';
            if (end) end.value = '';
            applyAllLeadsFilters();
        }

        function downloadFilteredLeadsCSV() {
            const filters = getAllLeadsFilterValues();
            const params = new URLSearchParams();
            filters.statuses.forEach(status => params.append('status', status));
            if (filters.start_date) params.set('start_date', filters.start_date);
            if (filters.end_date) params.set('end_date', filters.end_date);
            window.location.href = `/api/all-leads/export-csv?${params.toString()}`;
        }

        async function deleteFilteredLeads() {
            if (userRole !== 'Admin') return alert('Unauthorized. Admin access required.');
            const filters = getAllLeadsFilterValues();
            if (!filters.statuses.length && !filters.start_date && !filters.end_date) {
                const total = rawLeadsData.filter(lead => !lead.is_deleted).length;
                if (!confirm(`No filters are applied. This will move ALL ${total} active leads to the Trash Bin. Continue?`)) return;
            } else {
                const count = getFilteredAllLeads().length;
                if (!count) return alert('There are no matching leads to delete.');
                if (!confirm(`You are about to move ${count} lead(s) matching the current filters to the Trash Bin. Unmatched leads will remain untouched. Continue?`)) return;
            }
            const res = await fetch('/api/all-leads/delete-filtered', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(filters)
            });
            const result = await res.json().catch(() => ({}));
            if (res.ok && result.status === 'success') {
                alert(result.message || `${result.deleted_count || 0} lead(s) moved to Trash Bin.`);
                await fetchLeadsData();
                applyAllLeadsFilters();
            } else {
                alert(result.message || result.error || 'Unable to delete matching leads.');
            }
        }

        function renderUI(dataList) {
            const activeLeads = dataList.filter(l => !l.is_deleted);
            const trashLeads = dataList.filter(l => l.is_deleted);
            rawTrashData = trashLeads.slice();
            
            document.getElementById('statTotal').innerText = activeLeads.length;
            document.getElementById('statContacted').innerText = activeLeads.filter(l => l.status === 'Contacted').length;
            document.getElementById('statNew').innerText = activeLeads.filter(l => l.status === 'New Lead').length;
            document.getElementById('statFollowUp').innerText = activeLeads.filter(l => l.status === 'Follow Up').length;
            document.getElementById('statRejected').innerText = activeLeads.filter(l => l.status === 'Rejected').length;
            
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
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(lead)})' title="View Organized Details"><i class="fa-solid fa-eye"></i></button>`;
                const deleteBtn = userRole === 'Admin' ? `<td><button class="action-icon-btn trash-btn" onclick="deleteLead(${lead.id})"><i class="fa-solid fa-trash-can"></i></button></td>` : '';
                recentTbody.innerHTML += `
                    <tr>
                        <td><strong>${lead.student_name}</strong></td>
                        <td><a href="tel:${lead.contact_number}" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
                        <td><a href="mailto:${lead.student_email}" class="action-icon-btn mail-btn"><i class="fa-solid fa-envelope"></i></a> ${lead.student_email}</td>
                        <td>${lead.course_interest || lead.course_details || lead.other_course || (lead.form_data && (lead.form_data.course_interest || lead.form_data.course || lead.form_data.which_course || lead.form_data['Which course are you interested in?'])) || 'N/A'}</td>
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
                        ${deleteBtn}
                    </tr>
                `;
            });
            
            applyTrashFilters();
            applyAllLeadsFilters();
            updatePieChart(activeLeads);
            updateTimeFilteredCharts(activeLeads);
            fetchStudentsData();
        }

        function renderStudentsUI(students) {
            document.getElementById('statStudents').innerText = students.length;
            const tbody = document.getElementById('studentsTbody');
            tbody.innerHTML = '';
            if(students.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:#94a3b8;">No registered students yet. Convert leads from All Leads tab.</td></tr>`;
                return;
            }
            students.slice().reverse().forEach(st => {
                const cbHtml = userRole === 'Admin' ? `<td><input type="checkbox" class="students-checkbox" value="${st.student_id}"></td>` : '';
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(st)})' title="View Organized Details"><i class="fa-solid fa-eye"></i></button>`;
                tbody.innerHTML += `
                    <tr>
                        ${cbHtml}
                        <td>#${st.student_id}</td>
                        <td><strong>${st.student_name}</strong></td>
                        <td>${st.contact_number}</td>
                        <td>${st.student_email}</td>
                        <td><span class="badge-status badge-closed">${st.assigned_college || 'Not Assigned'}</span></td>
                        <td>${st.course_interest || st.course_details || st.other_course || 'N/A'}</td>
                        <td>
                            ${docAction}
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
                const docAction = `<button class="action-icon-btn doc-btn" onclick='openDocModal(${JSON.stringify(lead)})' title="View Organized Details"><i class="fa-solid fa-eye"></i></button>`;
                const convertBtn = `<button class="convert-btn" onclick="convertToStudent(${lead.id})"><i class="fa-solid fa-user-check"></i> Convert</button>`;
                const cbHtml = userRole === 'Admin' ? `<td><input type="checkbox" class="leads-checkbox" value="${lead.id}"></td>` : '';
                const deleteBtn = userRole === 'Admin' ? `<button class="action-icon-btn trash-btn" onclick="deleteLead(${lead.id})" title="Delete Lead"><i class="fa-solid fa-trash-can"></i></button>` : '';
                
                allTbody.innerHTML += `
                    <tr>
                        ${cbHtml}
                        <td>#${lead.id}</td>
                        <td><strong>${lead.student_name}</strong></td>
                        <td><a href="tel:${lead.contact_number}" class="action-icon-btn call-btn"><i class="fa-solid fa-phone"></i></a> ${lead.contact_number}</td>
                        <td><a href="mailto:${lead.student_email}" class="action-icon-btn mail-btn"><i class="fa-solid fa-envelope"></i></a> ${lead.student_email}</td>
                        <td>${lead.course_interest || lead.course_details || lead.other_course || (lead.form_data && (lead.form_data.course_interest || lead.form_data.course || lead.form_data.which_course || lead.form_data['Which course are you interested in?'])) || 'N/A'}</td>
                        <td><span style="font-size:12px; font-weight:600; color:#0284c7;">${lead.assigned_college || 'None'}</span></td>
                        <td>
                            <select class="status-select" onchange="updateStatus(${lead.id}, this.value)">
                                <option value="New Lead" ${lead.status==='New Lead'?'selected':''}>New Lead</option>
                                <option value="Contacted" ${lead.status==='Contacted'?'selected':''}>Contacted</option>
                                <option value="Follow Up" ${lead.status==='Follow Up'?'selected':''}>Follow Up</option>
                                <option value="Closed" ${lead.status==='Closed'?'selected':''}>Closed</option>
                                <option value="Rejected" ${lead.status==='Rejected'?'selected':''}>Rejected</option>
                                <option value="Converted to Student" ${lead.status==='Converted to Student'?'selected':''}>Converted to Student</option>
                            </select>
                        </td>
                        <td>
                            ${docAction}
                            ${convertBtn}
                            <button class="action-icon-btn edit-btn" onclick='openEditModal(${JSON.stringify(lead)})' title="Edit All Fields"><i class="fa-solid fa-pen"></i></button>
                            ${deleteBtn}
                        </td>
                    </tr>
                `;
            });
        }

        async function fetchTrashData() {
            try {
                const res = await fetch('/api/get-trash');
                if (res.ok) {
                    rawTrashData = await res.json();
                    applyTrashFilters();
                }
            } catch (e) { console.error('Trash Bin load failed', e); }
        }

        function populateTrashTable(items) {
            const tbody=document.getElementById('trashTbody');
            tbody.innerHTML='';
            if(!items.length){
                tbody.innerHTML='<tr><td colspan="8" style="text-align:center;color:#94a3b8;">Trash bin is empty.</td></tr>';
                return;
            }
            const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
            const order=['Logs','Work History','Colleges','Students','Student Documents','Leads','Other'];
            const categories=[...new Set(items.map(x=>x.category||'Other'))].sort((a,b)=>(order.indexOf(a)<0?99:order.indexOf(a))-(order.indexOf(b)<0?99:order.indexOf(b)));
            categories.forEach(category=>{
                tbody.innerHTML+=`<tr style="background:#f1f5f9;"><td colspan="8" style="font-weight:800;color:#0f172a;padding:10px 12px;">${esc(category)} <span style="font-weight:500;color:#64748b;">(${items.filter(x=>(x.category||'Other')===category).length})</span></td></tr>`;
                items.filter(x=>(x.category||'Other')===category).forEach(item=>{
                    const record=item.record||{};
                    const name=record.student_name||record.college_name||record.username||record.action_type||record.details||record.original_name||record.name||`Record #${item.source_id}`;
                    const contact=record.contact_number||record.phone||record.ip_address||'—';
                    const email=record.student_email||record.email||'—';
                    const when=item.deleted_at||item.deleted_date||'—';
                    tbody.innerHTML+=`<tr>
                        <td><input type="checkbox" class="trash-checkbox" value="${esc(item.trash_id)}"></td>
                        <td>${esc(category)}</td><td>#${esc(item.source_id)}</td>
                        <td><strong>${esc(name)}</strong><div style="font-size:11px;color:#64748b;">${esc(record.details||record.action_type||record.description||record.original_name||'')}</div></td>
                        <td>${esc(contact)}</td><td>${esc(email)}</td><td>${esc(when)}</td>
                        <td><button onclick="restoreTrashRecord('${esc(item.trash_id)}')" style="background:#16a34a;color:white;border:0;padding:5px 10px;border-radius:6px;cursor:pointer;font-weight:600;">Restore</button></td>
                    </tr>`;
                });
            });
        }

        async function restoreTrashRecord(trashId) {
            const res=await fetch('/api/trash/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({trash_id:trashId})});
            const result=await res.json();
            if(res.ok){alert(result.message||'Record restored.');fetchLeadsData();fetchStudentsData();fetchColleges();fetchWorkHistory();fetchSettingsLogs();fetchTrashData();}
            else alert(result.message||'Unable to restore this record.');
        }

        function toggleSelectAllTrash(master) {
            document.querySelectorAll('.trash-checkbox').forEach(cb => cb.checked = master.checked);
        }

        async function trashSelectedDelete() {
            const selectedIds = Array.from(document.querySelectorAll('.trash-checkbox:checked')).map(cb => cb.value);
            if(selectedIds.length === 0) {
                alert('Please select at least one record from Trash Bin.');
                return;
            }
            if(confirm(`Are you sure you want to permanently delete ${selectedIds.length} selected records?`)) {
                const res = await fetch('/api/trash/delete-permanent', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({trash_ids: selectedIds})
                });
                if(res.ok) {
                    alert('Selected records permanently deleted.');
                    fetchLeadsData(); fetchTrashData();
                } else {
                    alert('Unauthorized.');
                }
            }
        }

        function trashSelectedDownload() {
            const selectedIds = Array.from(document.querySelectorAll('.trash-checkbox:checked')).map(cb => cb.value);
            if(selectedIds.length === 0) {
                alert('Please select at least one record from Trash Bin to download.');
                return;
            }
            fetch('/api/trash/download', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({trash_ids: selectedIds})
            }).then(res => res.text()).then(html => {
                const win = window.open('', '_blank');
                win.document.write(html);
                win.document.close();
            });
        }

        async function deleteSelectedLeads() {
            const selectedIds = Array.from(document.querySelectorAll('.leads-checkbox:checked')).map(cb => parseInt(cb.value));
            if(selectedIds.length === 0) return alert('Select at least one lead.');
            if(confirm(`Move ${selectedIds.length} leads to Trash Bin?`)) {
                const res = await fetch('/api/delete-selected-leads', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({lead_ids: selectedIds}) });
                if(res.ok) fetchLeadsData(); else alert('Unauthorized.');
            }
        }

        async function deleteSelectedStudents() {
            const selectedIds = Array.from(document.querySelectorAll('.students-checkbox:checked')).map(cb => parseInt(cb.value));
            if(selectedIds.length === 0) return alert('Select at least one student.');
            if(confirm(`Delete ${selectedIds.length} student records?`)) {
                const res = await fetch('/api/delete-selected-students', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({student_ids: selectedIds}) });
                if(res.ok) { fetchStudentsData(); fetchTrashData(); } else alert('Unauthorized.');
            }
        }

        async function deleteSelectedColleges() {
            const selectedIds = Array.from(document.querySelectorAll('.colleges-checkbox:checked')).map(cb => parseInt(cb.value));
            if(selectedIds.length === 0) return alert('Select at least one college.');
            if(confirm(`Delete ${selectedIds.length} college records?`)) {
                const res = await fetch('/api/delete-selected-colleges', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({college_ids: selectedIds}) });
                if(res.ok) { fetchColleges(); fetchTrashData(); } else alert('Unauthorized.');
            }
        }

        async function deleteSelectedHistory() {
            const selectedIds = Array.from(document.querySelectorAll('.history-checkbox:checked')).map(cb => parseInt(cb.value));
            if(selectedIds.length === 0) return alert('Select at least one history entry.');
            if(confirm(`Delete ${selectedIds.length} history records?`)) {
                const res = await fetch('/api/delete-selected-history', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({history_ids: selectedIds}) });
                if(res.ok) { fetchWorkHistory(); fetchTrashData(); } else alert('Unauthorized.');
            }
        }

        async function deleteSelectedLogs() {
            const selectedIds = Array.from(document.querySelectorAll('.logs-checkbox:checked')).map(cb => parseInt(cb.value));
            if(selectedIds.length === 0) return alert('Select at least one log entry.');
            if(confirm(`Delete ${selectedIds.length} login log entries?`)) {
                const res = await fetch('/api/delete-selected-logs', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({log_ids: selectedIds}) });
                if(res.ok) { fetchSettingsLogs(); fetchTrashData(); } else alert('Unauthorized.');
            }
        }

        async function clearAllLogs() {
            if(confirm("Move all login activity logs to the Trash Bin?")) {
                const res = await fetch('/api/clear-logs', { method: 'POST' });
                if(res.ok) { fetchSettingsLogs(); fetchTrashData(); } else alert('Unauthorized.');
            }
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

        function renderAdditionalRegistrationSections(record) {
            const core=new Set(['student_name','name','father_name','contact_number','phone','alternate_number','student_email','email',
                'state','city','current_education_level','qualification','percentage_10th','percentage_12th','edu_percentage',
                'course_interest','course_details','other_course','Which course are you interested in?','which_course','course','hear_about','other_source','preferred_time','annual_budget','budget',
                'fee_payment_option','loan_assistance','hostel_required','hostel_preference','contacted_college','help_with',
                'col_name_1','col_state_1','col_name_2','col_state_2','col_name_3','col_state_3','admission_preference','assigned_college']);
            const excluded=/^(student_id|original_lead_id|id|status|score|notes|is_deleted|attachments|form_data|github_record_path|converted_at|created_|deleted_)/i;
            const values={};
            Object.entries((record&&record.form_data)||{}).forEach(([k,v])=>{if(v!==null&&v!==''&&!(Array.isArray(v)&&!v.length))values[k]=v;});
            Object.entries(record||{}).forEach(([k,v])=>{if(!(k in values)&&v!==null&&v!==''&&typeof v!=='undefined'&&!core.has(k)&&!excluded.test(k)&&!/(document|_doc$|scorecard|marksheet|aadhar|photo|image|attachment|file)/i.test(k))values[k]=v;});
            const fields=Object.entries(values).filter(([k,v])=>!core.has(k)&&!excluded.test(k)&&!/(document|_doc$|scorecard|marksheet|aadhar|photo|image|attachment|file)/i.test(k));
            if(!fields.length)return '<div style="color:#64748b;font-size:12px;">No additional registration fields.</div>';
            const groups=[
                {name:'Additional Personal Details',test:k=>/(name|father|mother|contact|phone|mobile|email|gender|dob|birth)/i.test(k)},
                {name:'Additional Academic Details',test:k=>/(education|qualification|percentage|10th|12th|score|board|school|academic)/i.test(k)},
                {name:'Additional Course & Admission Details',test:k=>/(course|admission|hostel|budget|fee|loan|help|preferred|hear|source)/i.test(k)},
                {name:'Additional Address Details',test:k=>/(address|state|city|district|pin|postal|country)/i.test(k)},
                {name:'Other Submitted Fields',test:k=>true}
            ];
            const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
            const used=new Set();
            return groups.map(group=>{
                const selected=fields.filter(([k])=>!used.has(k)&&group.test(k));
                selected.forEach(([k])=>used.add(k));
                if(!selected.length)return '';
                return `<section style="border:1px solid #e2e8f0;border-radius:8px;padding:10px;margin:10px 0;background:#f8fafc;">
                    <h5 style="margin:0 0 8px;color:#334155;font-size:12px;">${group.name}</h5>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:7px;">
                    ${selected.map(([k,v])=>`<div style="padding:5px 7px;border-bottom:1px solid #e2e8f0;"><strong>${esc(k.replace(/_/g,' '))}:</strong> ${esc(typeof v==='object'?JSON.stringify(v):v)}</div>`).join('')}
                    </div></section>`;
            }).join('');
        }

        /* --- ORGANIZED STUDENT DETAILS & MULTIPLE DOCUMENT VIEW MODAL --- */
        function openDocModal(lead) {
            const modal = document.getElementById('docModal');
            const container = document.getElementById('modalBodyContainer');
            
            let helpWithText = lead.help_with || 'N/A';
            if(Array.isArray(helpWithText)) helpWithText = helpWithText.join(', ');

            container.innerHTML = `
                <div style="font-size: 13px; line-height: 1.6; color: #1e293b; max-height: 75vh; overflow-y: auto; padding-right: 5px;">
                    <!-- Section 1: Personal Details -->
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 15px;">
                        <h4 style="color: #2563eb; margin-bottom: 10px; font-size: 14px; border-bottom: 1px solid #cbd5e1; padding-bottom: 5px;"><i class="fa-solid fa-user"></i> Personal Details</h4>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                            <div><strong>Student Name:</strong> ${lead.student_name || 'N/A'}</div>
                            <div><strong>Father's Name:</strong> ${lead.father_name || 'N/A'}</div>
                            <div><strong>Email ID:</strong> ${lead.student_email || 'N/A'}</div>
                            <div><strong>Contact Number:</strong> ${lead.contact_number || 'N/A'}</div>
                            <div><strong>Alternate Number:</strong> ${lead.alternate_number || 'N/A'}</div>
                        </div>
                    </div>

                    <!-- Section 2: Address Details -->
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 15px;">
                        <h4 style="color: #2563eb; margin-bottom: 10px; font-size: 14px; border-bottom: 1px solid #cbd5e1; padding-bottom: 5px;"><i class="fa-solid fa-location-dot"></i> Address Details</h4>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                            <div><strong>State:</strong> ${lead.state || 'N/A'}</div>
                            <div><strong>City:</strong> ${lead.city || 'N/A'}</div>
                        </div>
                    </div>

                    <!-- Section 3: Academic Details -->
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 15px;">
                        <h4 style="color: #2563eb; margin-bottom: 10px; font-size: 14px; border-bottom: 1px solid #cbd5e1; padding-bottom: 5px;"><i class="fa-solid fa-graduation-cap"></i> Academic Details</h4>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                            <div><strong>Current Education Level:</strong> ${lead.current_education_level || 'N/A'}</div>
                            <div><strong>10th Percentage / CGPA:</strong> ${lead.percentage_10th || 'N/A'}</div>
                            <div><strong>12th Percentage / CGPA:</strong> ${lead.percentage_12th || 'N/A'}</div>
                            <div><strong>Scorecard %:</strong> ${lead.edu_percentage || 'N/A'}</div>
                        </div>
                    </div>

                    <!-- Section 4: Course Preferences & Admission Details -->
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 15px;">
                        <h4 style="color: #2563eb; margin-bottom: 10px; font-size: 14px; border-bottom: 1px solid #cbd5e1; padding-bottom: 5px;"><i class="fa-solid fa-book-open"></i> Course Preferences & Admission Details</h4>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
                            <div><strong>Course Interest:</strong> ${lead.course_interest || lead.course_details || lead.other_course || 'N/A'}</div>
                            <div><strong>How did they hear:</strong> ${lead.hear_about || 'N/A'} ${lead.other_source ? '('+lead.other_source+')' : ''}</div>
                            <div><strong>Preferred Counselling Time:</strong> ${lead.preferred_time || 'N/A'}</div>
                            <div><strong>Annual Budget:</strong> ${lead.annual_budget || lead.budget || 'N/A'}</div>
                            <div><strong>Fee Payment Option:</strong> ${lead.fee_payment_option || 'N/A'}</div>
                            <div><strong>Payment Mode:</strong> ${lead.payment_mode || 'N/A'}</div>
                            ${lead.payment_mode === 'Installment' ? `<div><strong>Installment Duration:</strong> ${lead.installment_duration || 'N/A'}</div>` : ''}
                            <div><strong>Loan Assistance:</strong> ${lead.loan_assistance || 'N/A'}</div>
                            <div><strong>Hostel Required:</strong> ${lead.hostel_required || lead.hostel_preference || 'N/A'}</div>
                            <div><strong>Contacted College:</strong> ${lead.contacted_college || 'N/A'}</div>
                            <div style="grid-column: span 2;"><strong>Help With:</strong> ${helpWithText}</div>
                            ${lead.col_name_1 ? `<div style="grid-column: span 2;"><strong>Desired College 1:</strong> ${lead.col_name_1} (${lead.col_state_1 || ''})</div>` : ''}
                            ${lead.col_name_2 ? `<div style="grid-column: span 2;"><strong>Desired College 2:</strong> ${lead.col_name_2} (${lead.col_state_2 || ''})</div>` : ''}
                            ${lead.col_name_3 ? `<div style="grid-column: span 2;"><strong>Desired College 3:</strong> ${lead.col_name_3} (${lead.col_state_3 || ''})</div>` : ''}
                        </div>
                    </div>

                    <!-- Section 5: Multiple Documents & Photographs -->
                    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:15px;">
                        <h4 style="color:#2563eb;margin-bottom:10px;font-size:14px;border-bottom:1px solid #cbd5e1;padding-bottom:5px;"><i class="fa-solid fa-folder-open"></i> Uploaded Documents & Photographs</h4>
                        ${lead.passport_photo ? `<div style="margin:8px 0;"><strong>Passport Size Photograph</strong><br><img src="/download-doc/${encodeURIComponent(lead.passport_photo).replace(/%2F/g,'/')}" alt="Student passport photograph" style="max-width:110px;max-height:140px;object-fit:cover;border:1px solid #cbd5e1;border-radius:6px;"></div>` : ''}
                        <div id="studentDocumentControls" style="display:flex;gap:12px;flex-wrap:wrap;"></div>
                    </div>
                </div>
            `;
            const extra = document.createElement('div');
            extra.style.cssText='background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px;margin-top:12px;';
            extra.innerHTML='<h4 style="color:#2563eb;margin:0 0 8px;">Additional Submitted Registration Information</h4>'+renderAdditionalRegistrationSections(lead);
            container.appendChild(extra);
            renderStudentDocumentControls(lead);
            modal.style.display = 'flex';
        }

        function renderStudentDocumentControls(student, hostId='studentDocumentControls') {
            const host=document.getElementById(hostId);
            if(!host) return;
            const docs=[]; const seen=new Set();
            Object.entries(student||{}).forEach(([field,value])=>{
                if(typeof value==='string' && value && /(document|_doc$|scorecard|marksheet|aadhar|photo|image|attachment|file)/i.test(field)){
                    if(!seen.has(value)){docs.push({field,path:value,title:field.replace(/_/g,' ').replace(/\\b\\w/g,c=>c.toUpperCase())});seen.add(value);}
                }
            });
            (student.attachments||[]).forEach((a,i)=>{
                if(a && typeof a==='object' && a.stored_name && !seen.has(a.stored_name)){
                    docs.push({field:a.field||`attachment_${i}`,path:a.stored_name,title:a.original_name||`Attachment ${i+1}`});seen.add(a.stored_name);
                }
            });
            if(!docs.length){host.innerHTML='<span style="color:#64748b;font-size:12.5px;">No documents uploaded.</span>';return;}
            window.currentStudentDocumentFields=window.currentStudentDocumentFields||{};
            host.innerHTML=docs.map((d,docIndex)=>{
                const path='/download-doc/'+encodeURIComponent(d.path).replace(/%2F/g,'/');
                const token=(String(d.field).replace(/[^a-zA-Z0-9_-]/g,'_')+'_'+docIndex);
                const sid=Number(student.student_id)||0;
                window.currentStudentDocumentFields[`${sid}:${token}`]={field:d.field,path:d.path,topLevel:student[d.field]===d.path};
                const controls=(userRole==='Admin' && sid)?`<button type="button" onclick="replaceStudentDocument(${sid},'${token}')" style="background:#d97706;color:#fff;border:0;padding:6px 9px;border-radius:6px;cursor:pointer;">Replace</button>
                    <button type="button" onclick="deleteStudentDocument(${sid},'${token}')" style="background:#dc2626;color:#fff;border:0;padding:6px 9px;border-radius:6px;cursor:pointer;">Delete</button>
                    <input type="file" accept=".pdf,.jpg,.jpeg,.png" id="replaceDoc_${token}" style="display:none" onchange="submitStudentDocumentReplace(${sid},'${token}')">`:'';
                return `<div style="border:1px solid #dbeafe;background:#fff;border-radius:8px;padding:10px;min-width:210px;">
                    <div style="font-weight:700;font-size:12px;margin-bottom:8px;">${d.title}</div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">
                        <button type="button" onclick="previewDocument('${path}','${d.title.replace(/'/g,"&#39;")}')" style="background:#2563eb;color:#fff;border:0;padding:6px 9px;border-radius:6px;cursor:pointer;">View</button>
                        <a href="${path}?download=1" style="background:#16a34a;color:#fff;padding:6px 9px;border-radius:6px;text-decoration:none;">Download</a>${controls}
                    </div></div>`;
            }).join('');
        }
        async function uploadNewStudentDocument() {
            const studentId = document.getElementById('student_edit_id').value;
            const input = document.getElementById('studentNewDocumentFile');
            if (!input || !input.files.length) { alert('Please select a document first.'); return; }
            const fd = new FormData();
            fd.append('action','upload');
            fd.append('file',input.files[0]);
            const res = await fetch(`/api/student-document/${studentId}/additional_document`, {method:'POST',body:fd});
            const data = await res.json();
            if (res.ok) {
                alert(data.message || 'Document uploaded.');
                input.value = '';
                fetchStudentsData();
            } else alert(data.error || 'Unable to upload document.');
        }

        function replaceStudentDocument(studentId, token) {
            const input=document.getElementById('replaceDoc_'+token); if(input) input.click();
        }
        async function submitStudentDocumentReplace(studentId, token) {
            const input=document.getElementById('replaceDoc_'+token); if(!input || !input.files.length) return;
            const doc=(window.currentStudentDocumentFields||{})[`${studentId}:${token}`]||{field:token,path:''};
            const field=doc.field;
            const fd=new FormData(); fd.append('action','replace'); fd.append('field',field); fd.append('stored_name',doc.path); fd.append('file',input.files[0]);
            const res=await fetch(`/api/student-document/${studentId}/${encodeURIComponent(field)}`,{method:'POST',body:fd});
            const data=await res.json();
            if(res.ok){alert(data.message||'Document replaced.');fetchStudentsData();fetchLeadsData();}
            else alert(data.error||'Unable to replace document.');
            input.value='';
        }
        async function deleteStudentDocument(studentId, token) {
            if(!confirm('Move this individual document to Trash Bin?')) return;
            const doc=(window.currentStudentDocumentFields||{})[`${studentId}:${token}`]||{field:token,path:''};
            const field=doc.field;
            const res=await fetch(`/api/student-document/${studentId}/${encodeURIComponent(field)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',field,stored_name:doc.path})});
            const data=await res.json();
            if(res.ok){alert(data.message||'Document moved to Trash Bin.');closeDocModal();fetchStudentsData();fetchTrashData();}
            else alert(data.error||'Unable to delete document.');
        }

        function previewDocument(url, title) {
            const subModal = document.createElement('div');
            subModal.id = 'docPreviewSubModal';
            subModal.style.cssText = 'position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.85); z-index:2000; display:flex; justify-content:center; align-items:center; padding:12px; overflow:auto;';
            
            let previewContent = '';
            if(url.match(/\\.(jpeg|jpg|png|gif|webp)(?:\\?.*)?$/i)) {
                previewContent = `<img src="${url}" style="max-width:100%; max-height:70vh; border-radius:8px; box-shadow:0 10px 25px rgba(0,0,0,0.5);" alt="${title}">`;
            } else {
                previewContent = `<iframe src="${url}" style="width:100%; max-width:800px; height:70vh; border:none; border-radius:8px; background:white;" title="${title}"></iframe>`;
            }

            subModal.innerHTML = `
                <style>@media(max-width:600px){ #docPreviewSubModal .doc-preview-panel{padding:12px!important;max-height:96dvh;overflow:auto}#docPreviewSubModal .doc-preview-actions{display:flex!important;flex-direction:column!important;gap:10px!important;align-items:stretch!important}#docPreviewSubModal .doc-preview-actions a,#docPreviewSubModal .doc-preview-actions button{width:100%!important;min-height:44px;justify-content:center;box-sizing:border-box}#docPreviewSubModal .doc-preview-heading{gap:8px;flex-wrap:wrap}#docPreviewSubModal .doc-preview-heading h4{max-width:calc(100% - 40px);overflow-wrap:anywhere}}</style>
                <div class="doc-preview-panel" style="background:#1e293b; padding:20px; border-radius:12px; width:100%; max-width:850px; max-height:96vh; overflow:auto; text-align:center; position:relative; box-shadow:0 20px 25px rgba(0,0,0,0.5);">
                    <div class="doc-preview-heading" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; color:white;">
                        <h4 style="margin:0; font-size:16px;">${title}</h4>
                        <button onclick="document.getElementById('docPreviewSubModal').remove()" style="background:none; border:none; color:white; font-size:24px; cursor:pointer;">&times;</button>
                    </div>
                    <div style="margin-bottom:15px; display:flex; justify-content:center;">
                        ${previewContent}
                    </div>
                    <div class="doc-preview-actions" style="display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap;">
                        <a href="${url}${url.includes('?')?'&':'?'}download=1" class="action-icon-btn doc-btn" style="background:#16a34a; color:white; padding:8px 16px; border-radius:6px; text-decoration:none; display:inline-flex; align-items:center; gap:6px; font-weight:600; width:auto; height:auto;" target="_blank"><i class="fa-solid fa-download"></i> Download Document</a>
                        <button onclick="document.getElementById('docPreviewSubModal').remove()" style="background:#64748b; color:white; border:none; padding:8px 16px; border-radius:6px; cursor:pointer; font-weight:600;">Close Preview</button>
                    </div>
                </div>
            `;
            document.body.appendChild(subModal);
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

        function renderStructuredStudentEditor(student) {
            const host=document.getElementById('studentStructuredFields'); if(!host) return;
            const record={...(student||{})};
            const form=(student&&student.form_data&&typeof student.form_data==='object')?student.form_data:{};
            Object.entries(form).forEach(([k,v])=>{if(record[k]===undefined || record[k]==='') record[k]=v;});
            const excluded=new Set(['student_id','id','original_lead_id','is_deleted','attachments','form_data','github_record_path','converted_at','created_at','created_date','created_timestamp','deleted_date','deleted_at','deleted_timestamp','status','score','notes']);
            const groups=[
                {name:'Personal & Contact Details',test:k=>/(name|father|mother|contact|phone|mobile|email|gender|dob|birth)/i.test(k)},
                {name:'Academic Details',test:k=>/(education|qualification|percentage|10th|12th|score|board|school|college)/i.test(k)},
                {name:'Course & Admission Preferences',test:k=>/(course|admission|hostel|budget|fee|loan|help|preferred|hear|source)/i.test(k)},
                {name:'Address Details',test:k=>/(address|state|city|district|pin|postal|country)/i.test(k)},
                {name:'Other Registration Information',test:k=>true}
            ];
            const entries=Object.entries(record).filter(([k,v])=>!excluded.has(k)&&v!==null&&typeof v!=='undefined'&&!/(document|_doc$|scorecard|marksheet|aadhar|photo|image|attachment|file)/i.test(k));
            const used=new Set();
            host.innerHTML=groups.map(group=>{
                const fields=entries.filter(([k])=>!used.has(k)&&group.test(k));
                fields.forEach(([k])=>used.add(k));
                if(!fields.length)return '';
                return `<section style="border:1px solid #e2e8f0;border-radius:9px;padding:12px;margin-bottom:12px;background:#f8fafc;">
                    <h4 style="margin:0 0 10px;color:#2563eb;font-size:13px;">${group.name}</h4>
                    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;">
                    ${fields.map(([k,v])=>`<label style="font-size:11px;font-weight:700;color:#475569;">${k.replace(/_/g,' ').replace(/\\b\\w/g,c=>c.toUpperCase())}
                        <input class="form-control student-dynamic-field" data-field="${encodeURIComponent(k)}" value="${String(typeof v==='object'?JSON.stringify(v):v??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;')}" style="margin-top:4px;">
                    </label>`).join('')}
                    </div></section>`;
            }).join('');
        }

        function openStudentEditModal(st) {
            document.getElementById('student_edit_id').value = st.student_id;
            document.getElementById('s_edit_name').value = st.student_name || '';
            document.getElementById('s_edit_contact').value = st.contact_number || '';
            document.getElementById('s_edit_email').value = st.student_email || '';
            document.getElementById('s_edit_course').value = st.course_details || '';
            document.getElementById('s_edit_college').value = st.assigned_college || '';
            document.getElementById('s_edit_budget').value = st.budget || '';
            document.getElementById('student_all_data_json').value = JSON.stringify(st, null, 2);
            renderStructuredStudentEditor(st);
            const editDocHost = document.getElementById('studentEditDocumentControls');
            if (editDocHost) {
                editDocHost.innerHTML = '';
                renderStudentDocumentControls(st, 'studentEditDocumentControls');
            }
            document.getElementById('studentEditModal').style.display = 'flex';
        }
        function closeStudentEditModal() { document.getElementById('studentEditModal').style.display = 'none'; }

        async function submitEditStudent(e) {
            e.preventDefault();
            const formData = new FormData();
            formData.append('student_id', document.getElementById('student_edit_id').value);
            try {
                const fullRecord=JSON.parse(document.getElementById('student_all_data_json').value);
                fullRecord.student_id=document.getElementById('student_edit_id').value;
                fullRecord.student_name=document.getElementById('s_edit_name').value;
                fullRecord.contact_number=document.getElementById('s_edit_contact').value;
                fullRecord.student_email=document.getElementById('s_edit_email').value;
                fullRecord.course_details=document.getElementById('s_edit_course').value;
                fullRecord.assigned_college=document.getElementById('s_edit_college').value;
                fullRecord.budget=document.getElementById('s_edit_budget').value;
                document.querySelectorAll('#studentStructuredFields .student-dynamic-field').forEach(input=>{
                    const key=decodeURIComponent(input.dataset.field||'');
                    let value=input.value;
                    if((value.startsWith('[')&&value.endsWith(']'))||(value.startsWith('{')&&value.endsWith('}'))){try{value=JSON.parse(value);}catch(e){}}
                    fullRecord[key]=value;
                    if(!fullRecord.form_data || typeof fullRecord.form_data!=='object') fullRecord.form_data={};
                    fullRecord.form_data[key]=value;
                });
                fullRecord.student_name=document.getElementById('s_edit_name').value;
                fullRecord.contact_number=document.getElementById('s_edit_contact').value;
                fullRecord.student_email=document.getElementById('s_edit_email').value;
                fullRecord.course_details=document.getElementById('s_edit_course').value;
                fullRecord.course_interest=fullRecord.course_details || fullRecord.course_interest || '';
                fullRecord.assigned_college=document.getElementById('s_edit_college').value;
                fullRecord.budget=document.getElementById('s_edit_budget').value;
                if(!fullRecord.form_data || typeof fullRecord.form_data!=='object') fullRecord.form_data={};
                Object.assign(fullRecord.form_data,{student_name:fullRecord.student_name,contact_number:fullRecord.contact_number,
                    student_email:fullRecord.student_email,course_details:fullRecord.course_details,
                    course_interest:fullRecord.course_interest,assigned_college:fullRecord.assigned_college,budget:fullRecord.budget});
                fullRecord.course_interest=fullRecord.course_interest||fullRecord.course_details||'';
                fullRecord.form_data.course_interest=fullRecord.course_interest;
                formData.append('student_data_json', JSON.stringify(fullRecord));
            } catch(err) { alert('Please correct the JSON in All Saved Registration Fields.'); return; }

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
        function downloadStudentsPDF() { window.open('/api/export-students-pdf', '_blank'); }
        function downloadHistoryPDF() { const q=new URLSearchParams();const a=document.getElementById('historyStartDate').value,b=document.getElementById('historyEndDate').value;if(a)q.set('start_date',a);if(b)q.set('end_date',b);window.open('/api/export-history-pdf?'+q.toString(),'_blank'); }
        function downloadCollegePDF() { window.open('/api/export-college-pdf', '_blank'); }
        function downloadLogsPDF() { const q=new URLSearchParams();const a=document.getElementById('logsStartDate').value,b=document.getElementById('logsEndDate').value;if(a)q.set('start_date',a);if(b)q.set('end_date',b);q.set('user_type',document.getElementById('logsUserType').value);window.open('/api/export-logs-pdf?'+q.toString(),'_blank'); }

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
                const res = await fetch('/api/delete-lead', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({lead_id: id}) });
                if(res.ok) fetchLeadsData(); else alert('Unauthorized.');
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
                'Rejected': activeLeads.filter(l => l.status==='Rejected').length,
                'Converted to Student': activeLeads.filter(l => l.status==='Converted to Student').length
            };
            const ctx = document.getElementById('leadsPieChart').getContext('2d');
            if(pieChartInstance) pieChartInstance.destroy();
            const total=activeLeads.length;
            const labels=['New Lead','Contacted','Follow Up','Closed','Rejected','Converted to Student'];
            const values=labels.map(k=>counts[k]||0);
            const converted=activeLeads.filter(l=>l.status==='Converted to Student').length;
            const conversionRate=total ? (converted/total*100) : 0;
            document.getElementById('leadsPieSummary').innerHTML =
                labels.map((label,i)=>`<div style="display:flex;justify-content:space-between;gap:12px;"><span>${label}</span><strong>${values[i]} (${total?(values[i]/total*100).toFixed(1):'0.0'}%)</strong></div>`).join('')+
                `<div style="border-top:1px solid var(--border-color);margin-top:6px;padding-top:6px;display:flex;justify-content:space-between;"><span>Converted to Students</span><strong>${converted} (${conversionRate.toFixed(1)}%)</strong></div><div style="display:flex;justify-content:space-between;"><span>Total Leads</span><strong>${total}</strong></div>`;
            pieChartInstance = new Chart(ctx, {
                type: 'doughnut',
                data: { labels, datasets: [{ data: values, backgroundColor: ['#38bdf8', '#f59e0b', '#6366f1', '#22c55e', '#ef4444', '#0ea5e9'] }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: {
                    legend: { position: 'bottom' },
                    tooltip: { callbacks: { label: context => `${context.label}: ${context.raw} (${total?(context.raw/total*100).toFixed(1):'0.0'}%)` } }
                } }
            });
        }

        function updateTimeFilteredCharts(activeLeads) {
            const now = new Date();
            const currentDay = now.getDay() || 7;
            const monday = new Date(now);
            monday.setDate(now.getDate() - currentDay + 1);
            monday.setHours(0,0,0,0);
            
            const weeklyLeads = activeLeads.filter(l => {
                const lDate = l.created_timestamp ? new Date(l.created_timestamp * 1000) : new Date(l.created_date || now);
                return lDate >= monday;
            });

            const firstDayMonth = new Date(now.getFullYear(), now.getMonth(), 1);
            const monthlyLeads = activeLeads.filter(l => {
                const lDate = l.created_timestamp ? new Date(l.created_timestamp * 1000) : new Date(l.created_date || now);
                return lDate >= firstDayMonth;
            });

            const firstDayYear = new Date(now.getFullYear(), 0, 1);
            const yearlyLeads = activeLeads.filter(l => {
                const lDate = l.created_timestamp ? new Date(l.created_timestamp * 1000) : new Date(l.created_date || now);
                return lDate >= firstDayYear;
            });

            document.getElementById('weekRangeLabel').innerText = `Since ${monday.toLocaleDateString()}`;
            document.getElementById('weekTotalCount').innerText = weeklyLeads.length;

            document.getElementById('monthRangeLabel').innerText = now.toLocaleString('default', { month: 'long', year: 'numeric' });
            document.getElementById('monthTotalCount').innerText = monthlyLeads.length;

            document.getElementById('yearRangeLabel').innerText = `Year ${now.getFullYear()}`;
            document.getElementById('yearTotalCount').innerText = yearlyLeads.length;

            const getCounts = (list) => ({
                'New': list.filter(l => l.status==='New Lead').length,
                'Contacted': list.filter(l => l.status==='Contacted').length,
                'Follow Up': list.filter(l => l.status==='Follow Up').length,
                'Closed': list.filter(l => l.status==='Closed').length,
                'Rejected': list.filter(l => l.status==='Rejected').length
            });

            const wCounts = getCounts(weeklyLeads);
            const mCounts = getCounts(monthlyLeads);
            const yCounts = getCounts(yearlyLeads);

            if(weeklyPieInstance) weeklyPieInstance.destroy();
            weeklyPieInstance = new Chart(document.getElementById('weeklyPieChart').getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: ['New', 'Contacted', 'Follow Up', 'Closed', 'Rejected'],
                    datasets: [{ data: [wCounts['New'], wCounts['Contacted'], wCounts['Follow Up'], wCounts['Closed'], wCounts['Rejected']], backgroundColor: ['#38bdf8', '#f59e0b', '#6366f1', '#22c55e', '#ef4444'] }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
            });

            if(monthlyPieInstance) monthlyPieInstance.destroy();
            monthlyPieInstance = new Chart(document.getElementById('monthlyPieChart').getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: ['New', 'Contacted', 'Follow Up', 'Closed', 'Rejected'],
                    datasets: [{ data: [mCounts['New'], mCounts['Contacted'], mCounts['Follow Up'], mCounts['Closed'], mCounts['Rejected']], backgroundColor: ['#38bdf8', '#f59e0b', '#6366f1', '#22c55e', '#ef4444'] }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
            });

            if(yearlyPieInstance) yearlyPieInstance.destroy();
            yearlyPieInstance = new Chart(document.getElementById('yearlyPieChart').getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: ['New', 'Contacted', 'Follow Up', 'Closed', 'Rejected'],
                    datasets: [{ data: [yCounts['New'], yCounts['Contacted'], yCounts['Follow Up'], yCounts['Closed'], yCounts['Rejected']], backgroundColor: ['#38bdf8', '#f59e0b', '#6366f1', '#22c55e', '#ef4444'] }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
            });
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
