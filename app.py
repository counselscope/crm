import os
import json
import csv
import io
import base64
import urllib.request
import urllib.error
import urllib.parse
import traceback
import secrets
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_from_directory, make_response
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "counselscope_github_persistent_secret_2026"
CORS(app, supports_credentials=True)

DATA_FILE = "leads.json"
COLLEGES_FILE = "colleges.json"
HISTORY_FILE = "history.json"
BASE_DIR_FOLDER = "Council CRM"

if not os.path.exists(BASE_DIR_FOLDER):
    os.makedirs(BASE_DIR_FOLDER)

# GitHub Configuration from Environment Variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "counselscope/counselscope-crm").strip()
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip()

def load_data(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_data(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def get_ist_time():
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    return ist_now

def get_dynamic_greeting():
    hour = get_ist_time().hour
    if 5 <= hour < 12:
        return "Good Morning"
    elif 12 <= hour < 17:
        return "Good Afternoon"
    elif 17 <= hour < 21:
        return "Good Evening"
    else:
        return "Good Night"

def log_history(student_name, activity_type, description, followup_date="", status="Completed"):
    history = load_data(HISTORY_FILE)
    now_ist = get_ist_time()
    entry = {
        "id": len(history) + 1,
        "student_name": student_name or "General",
        "activity_type": activity_type,
        "description": description,
        "activity_date": now_ist.strftime("%Y-%m-%d"),
        "activity_time": now_ist.strftime("%I:%M %p"),
        "followup_date": followup_date or "",
        "status": status,
        "timestamp": now_ist.strftime("%d %b %Y, %I:%M %p")
    }
    history.append(entry)
    save_data(HISTORY_FILE, history)
    save_file_to_github(HISTORY_FILE, f"Council CRM/{HISTORY_FILE}", f"Update history log for {student_name}")

def github_api_request(url, method="GET", data=None):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return None
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "CounselScope-CRM-App"
    }
    
    json_bytes = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=json_bytes, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            return json.loads(res_body) if res_body else {}
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"GitHub API HTTP Error [{method} {url}]: Code {e.code}")
        return None
    except Exception as e:
        print(f"GitHub API General Error [{method} {url}]: {e}")
        return None

def save_file_to_github(file_bytes_or_path, github_path, commit_message):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{github_path}"
    existing_file = github_api_request(f"{url}?ref={GITHUB_BRANCH}", method="GET")
    sha = existing_file.get("sha") if existing_file and isinstance(existing_file, dict) else None

    try:
        if isinstance(file_bytes_or_path, bytes):
            encoded_content = base64.b64encode(file_bytes_or_path).decode("utf-8")
        else:
            with open(file_bytes_or_path, "rb") as bf:
                encoded_content = base64.b64encode(bf.read()).decode("utf-8")
        
        payload = {
            "message": commit_message,
            "content": encoded_content,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha
            
        res = github_api_request(url, method="PUT", data=payload)
        return res is not None
    except Exception as e:
        print(f"Error executing GitHub commit for {github_path}: {e}")
        return False

def sync_from_github():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    for filename in [DATA_FILE, HISTORY_FILE, COLLEGES_FILE]:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/Council%20CRM/{filename}?ref={GITHUB_BRANCH}"
        file_data = github_api_request(url, method="GET")
        if file_data and "content" in file_data:
            try:
                decoded = base64.b64decode(file_data["content"]).decode("utf-8")
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(decoded)
            except Exception as e:
                print(f"Error syncing {filename}: {e}")

try:
    sync_from_github()
except Exception as e:
    print(f"GitHub Sync Notice: {e}")

@app.route('/api/submit-lead', methods=['POST'])
def submit_lead():
    try:
        student_name = request.form.get('student_name')
        if not student_name:
            return jsonify({"status": "error", "message": "Student name is required"}), 400

        current_leads = load_data(DATA_FILE)
        lead_id = request.form.get('lead_id')
        
        target_lead = None
        if lead_id:
            for l in current_leads:
                if str(l.get('id')) == str(lead_id):
                    target_lead = l
                    break

        safe_student_name = secure_filename(student_name)
        student_folder = os.path.join(BASE_DIR_FOLDER, safe_student_name)
        if not os.path.exists(student_folder):
            os.makedirs(student_folder)

        def handle_file_upload(file_key):
            if file_key in request.files:
                file = request.files[file_key]
                if file and file.filename != '':
                    fname = secure_filename(f"{file_key}_{int(get_ist_time().timestamp())}_{file.filename}")
                    full_local_path = os.path.join(student_folder, fname)
                    file_bytes = file.read()
                    with open(full_local_path, "wb") as lf:
                        lf.write(file_bytes)
                    gh_rel_path = f"Council CRM/{safe_student_name}/{fname}"
                    save_file_to_github(file_bytes, gh_rel_path, f"Upload {file_key} for {student_name}")
                    return f"/counsel-files/{safe_student_name}/{fname}"
            return target_lead.get(file_key, "N/A") if target_lead else "N/A"

        browser_token = target_lead.get('browser_token') if target_lead else secrets.token_hex(32)
        help_topics_val = request.form.get('help_with_list') or request.form.get('help_topics', 'N/A')

        if target_lead:
            target_lead.update({
                "student_name": student_name,
                "father_name": request.form.get('father_name', 'N/A'),
                "contact_number": request.form.get('contact_number', 'N/A'),
                "alternate_number": request.form.get('alternate_number', 'N/A'),
                "student_email": request.form.get('student_email', 'N/A'),
                "current_education": request.form.get('current_education_level', request.form.get('current_education', 'N/A')),
                "exam_name": request.form.get('exam_name', 'None'),
                "exam_score": request.form.get('edu_percentage', 'N/A'),
                "caste_category": request.form.get('caste_category', 'General'),
                "preferred_location": request.form.get('preferred_location', 'N/A'),
                "state": request.form.get('state', 'N/A'),
                "city": request.form.get('city', 'N/A'),
                "course_interest": request.form.get('course_interest', 'General'),
                "budget": request.form.get('annual_budget', request.form.get('budget', 'N/A')),
                "contacted_college": request.form.get('contacted_college', 'No'),
                "fee_payment": request.form.get('fee_payment_option', request.form.get('fee_payment', 'N/A')),
                "hostel_required": request.form.get('hostel_required', 'No'),
                "loan_assistance": request.form.get('loan_assistance', 'No'),
                "help_topics": help_topics_val,
                "source": request.form.get('hear_about', request.form.get('source', 'N/A')),
                "counselling_time": request.form.get('preferred_time', request.form.get('counselling_time', 'N/A')),
                "desired_colleges": request.form.get('desired_colleges', 'N/A'),
                "aadhar_file": handle_file_upload('aadhar_doc') if 'aadhar_doc' in request.files else handle_file_upload('aadhar_file'),
                "class10_file": handle_file_upload('class_10_doc') if 'class_10_doc' in request.files else handle_file_upload('class10_file'),
                "class12_file": handle_file_upload('class_12_doc') if 'class_12_doc' in request.files else handle_file_upload('class12_file'),
                "exam_file": handle_file_upload('edu_scorecard') if 'edu_scorecard' in request.files else handle_file_upload('exam_file'),
            })
            lead_data = target_lead
            log_history(student_name, "Student Self-Update", "Student updated their submitted application via browser.")
        else:
            new_id = len(current_leads) + 1
            lead_data = {
                "id": new_id,
                "student_name": student_name,
                "father_name": request.form.get('father_name', 'N/A'),
                "contact_number": request.form.get('contact_number', 'N/A'),
                "alternate_number": request.form.get('alternate_number', 'N/A'),
                "student_email": request.form.get('student_email', 'N/A'),
                "current_education": request.form.get('current_education_level', request.form.get('current_education', 'N/A')),
                "exam_name": request.form.get('exam_name', 'None'),
                "exam_score": request.form.get('edu_percentage', 'N/A'),
                "caste_category": request.form.get('caste_category', 'General'),
                "preferred_location": request.form.get('preferred_location', 'N/A'),
                "state": request.form.get('state', 'N/A'),
                "city": request.form.get('city', 'N/A'),
                "course_interest": request.form.get('course_interest', 'General'),
                "budget": request.form.get('annual_budget', request.form.get('budget', 'N/A')),
                "contacted_college": request.form.get('contacted_college', 'No'),
                "fee_payment": request.form.get('fee_payment_option', request.form.get('fee_payment', 'N/A')),
                "hostel_required": request.form.get('hostel_required', 'No'),
                "loan_assistance": request.form.get('loan_assistance', 'No'),
                "help_topics": help_topics_val,
                "source": request.form.get('hear_about', request.form.get('source', 'N/A')),
                "counselling_time": request.form.get('preferred_time', request.form.get('counselling_time', 'N/A')),
                "desired_colleges": request.form.get('desired_colleges', 'N/A'),
                "aadhar_file": handle_file_upload('aadhar_doc') if 'aadhar_doc' in request.files else handle_file_upload('aadhar_file'),
                "class10_file": handle_file_upload('class_10_doc') if 'class_10_doc' in request.files else handle_file_upload('class10_file'),
                "class12_file": handle_file_upload('class_12_doc') if 'class_12_doc' in request.files else handle_file_upload('class12_file'),
                "exam_file": handle_file_upload('edu_scorecard') if 'edu_scorecard' in request.files else handle_file_upload('exam_file'),
                "status": "New Lead",
                "followup_date": "",
                "followup_reason": "Initial Enquiry",
                "notes": "",
                "score": 85,
                "is_deleted": False,
                "allow_editing": False,
                "browser_token": browser_token,
                "created_at": get_ist_time().strftime("%d %b %Y, %I:%M %p")
            }
            current_leads.append(lead_data)
            log_history(student_name, "New Lead Added", f"New student lead registered for {lead_data['course_interest']}")

        details_path = os.path.join(student_folder, "details.json")
        with open(details_path, "w", encoding="utf-8") as sf:
            json.dump(lead_data, sf, indent=4)
        
        save_file_to_github(details_path, f"Council CRM/{safe_student_name}/details.json", f"Add/Update record for {student_name}")
        save_data(DATA_FILE, current_leads)
        save_file_to_github(DATA_FILE, f"Council CRM/{DATA_FILE}", "Update leads.json")

        resp = make_response(jsonify({"status": "success", "message": "Form submitted & saved to GitHub permanently!", "lead_id": lead_data['id']}))
        resp.set_cookie('student_browser_token', browser_token, httponly=True, secure=True, samesite='None')
        return resp, 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/toggle-editing', methods=['POST'])
def toggle_editing():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    lead_id = data.get('lead_id')
    allow = data.get('allow', False)
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == lead_id:
            lead['allow_editing'] = allow
            log_history(lead['student_name'], "Editing Permission", f"Student form editing permission {'granted' if allow else 'revoked'}.")
            break
    save_data(DATA_FILE, leads)
    save_file_to_github(DATA_FILE, f"Council CRM/{DATA_FILE}", "Update editing permission")
    return jsonify({"status": "success"})

@app.route('/api/student-auth-status', methods=['GET'])
def student_auth_status():
    browser_token = request.cookies.get('student_browser_token')
    if not browser_token:
        return jsonify({"authorized": False, "message": "Editing Access Not Available"})
    
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead.get('browser_token') == browser_token and not lead.get('is_deleted'):
            if lead.get('allow_editing'):
                return jsonify({"authorized": True, "lead": lead, "message": "Editing Access Granted"})
            else:
                return jsonify({"authorized": False, "message": "Editing Access Revoked by Counselor"})
                
    return jsonify({"authorized": False, "message": "Editing Access Not Available"})

@app.route('/counsel-files/<path:filename>')
def downloaded_file(filename):
    return send_from_directory(BASE_DIR_FOLDER, filename)

@app.route('/api/get-leads', methods=['GET'])
def get_leads_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(DATA_FILE))

@app.route('/api/get-history', methods=['GET'])
def get_history_api():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_data(HISTORY_FILE))

@app.route('/api/log-action', methods=['POST'])
def log_action():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    log_history(
        data.get('student_name'),
        data.get('activity_type'),
        data.get('description'),
        data.get('followup_date', ''),
        data.get('status', 'Completed')
    )
    return jsonify({"status": "success"})

@app.route('/api/update-followup', methods=['POST'])
def update_followup():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    lead_id = data.get('lead_id')
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == lead_id:
            lead['followup_date'] = data.get('followup_date', lead.get('followup_date', ''))
            lead['followup_reason'] = data.get('followup_reason', lead.get('followup_reason', ''))
            lead['notes'] = data.get('notes', lead.get('notes', ''))
            if data.get('mark_completed'):
                lead['followup_date'] = ''
                log_history(lead['student_name'], "Follow-up Completed", f"Completed follow-up task. Notes: {lead['notes']}")
            break
    save_data(DATA_FILE, leads)
    save_file_to_github(DATA_FILE, f"Council CRM/{DATA_FILE}", "Update followup")
    return jsonify({"status": "success"})

@app.route('/api/update-status', methods=['POST'])
def update_status():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == data.get('lead_id'):
            old_status = lead['status']
            lead['status'] = data.get('status')
            log_history(lead['student_name'], "Status Update", f"Lead status changed from {old_status} to {lead['status']}")
            break
    save_data(DATA_FILE, leads)
    save_file_to_github(DATA_FILE, f"Council CRM/{DATA_FILE}", "Update status")
    return jsonify({"status": "success"})

@app.route('/api/edit-lead', methods=['POST'])
def edit_lead():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    
    lead_id = int(request.form.get('lead_id'))
    leads = load_data(DATA_FILE)
    target_lead = None
    for lead in leads:
        if lead['id'] == lead_id:
            target_lead = lead
            break
            
    if not target_lead:
        return jsonify({"status": "error", "message": "Lead not found"}), 404

    safe_name = secure_filename(target_lead['student_name'])
    student_folder = os.path.join(BASE_DIR_FOLDER, safe_name)
    if not os.path.exists(student_folder):
        os.makedirs(student_folder)

    def handle_doc_action(file_key):
        if request.form.get(f"delete_{file_key}") == "true":
            target_lead[file_key] = "N/A"
        if file_key in request.files:
            file = request.files[file_key]
            if file and file.filename != '':
                fname = secure_filename(f"{file_key}_{int(get_ist_time().timestamp())}_{file.filename}")
                full_path = os.path.join(student_folder, fname)
                fbytes = file.read()
                with open(full_path, "wb") as f:
                    f.write(fbytes)
                gh_path = f"Council CRM/{safe_name}/{fname}"
                save_file_to_github(fbytes, gh_path, f"Update {file_key} for {target_lead['student_name']}")
                target_lead[file_key] = f"/counsel-files/{safe_name}/{fname}"

    handle_doc_action('aadhar_file')
    handle_doc_action('class10_file')
    handle_doc_action('class12_file')
    handle_doc_action('exam_file')

    target_lead['student_name'] = request.form.get('student_name', target_lead['student_name'])
    target_lead['father_name'] = request.form.get('father_name', target_lead['father_name'])
    target_lead['contact_number'] = request.form.get('contact_number', target_lead['contact_number'])
    target_lead['student_email'] = request.form.get('student_email', target_lead['student_email'])
    target_lead['course_interest'] = request.form.get('course_interest', target_lead['course_interest'])
    target_lead['budget'] = request.form.get('budget', target_lead['budget'])
    target_lead['city'] = request.form.get('city', target_lead['city'])
    target_lead['state'] = request.form.get('state', target_lead['state'])

    details_path = os.path.join(student_folder, "details.json")
    with open(details_path, "w", encoding="utf-8") as sf:
        json.dump(target_lead, sf, indent=4)
    save_file_to_github(details_path, f"Council CRM/{safe_name}/details.json", f"Update details for {target_lead['student_name']}")

    save_data(DATA_FILE, leads)
    save_file_to_github(DATA_FILE, f"Council CRM/{DATA_FILE}", "Save updated leads")
    log_history(target_lead['student_name'], "Details Edited", f"Updated profile details for {target_lead['student_name']}")

    return jsonify({"status": "success", "message": "Record and documents updated successfully!"})

@app.route('/api/delete-lead', methods=['POST'])
def delete_lead():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == data.get('lead_id'):
            lead['is_deleted'] = True
            log_history(lead['student_name'], "Moved to Trash", "Lead moved to trash bin")
            break
    save_data(DATA_FILE, leads)
    save_file_to_github(DATA_FILE, f"Council CRM/{DATA_FILE}", "Delete lead")
    return jsonify({"status": "success"})

@app.route('/api/restore-lead', methods=['POST'])
def restore_lead():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    leads = load_data(DATA_FILE)
    for lead in leads:
        if lead['id'] == data.get('lead_id'):
            lead['is_deleted'] = False
            log_history(lead['student_name'], "Restored Lead", "Lead restored from trash bin")
            break
    save_data(DATA_FILE, leads)
    save_file_to_github(DATA_FILE, f"Council CRM/{DATA_FILE}", "Restore lead")
    return jsonify({"status": "success"})

@app.route('/api/permanent-delete', methods=['POST'])
def permanent_delete():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    leads = load_data(DATA_FILE)
    leads = [l for l in leads if l['id'] != data.get('lead_id')]
    save_data(DATA_FILE, leads)
    save_file_to_github(DATA_FILE, f"Council CRM/{DATA_FILE}", "Permanent delete")
    return jsonify({"status": "success"})

@app.route('/api/export-csv', methods=['GET'])
def export_csv():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    leads = [l for l in load_data(DATA_FILE) if not l['is_deleted']]
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['ID', 'Student Name', 'Father Name', 'Contact', 'Email', 'Education', 'Course', 'Budget', 'City', 'Status'])
    for l in leads:
        writer.writerow([l.get('id'), l.get('student_name'), l.get('father_name'), l.get('contact_number'), l.get('student_email'), l.get('current_education'), l.get('course_interest'), l.get('budget'), l.get('city'), l.get('status')])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=counselscope_leads.csv"
    output.headers["Content-type"] = "text/csv"
    return output

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
    save_file_to_github(COLLEGES_FILE, f"Council CRM/{COLLEGES_FILE}", "Add college")
    return jsonify({"status": "success"})

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
    greeting = get_dynamic_greeting()
    return render_template_string(MAIN_DASHBOARD_HTML, greeting=greeting)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
def home():
    return jsonify({"status": "success", "message": "CounselScope CRM Backend API is running successfully!"})

LOGIN_HTML = """...""" # (Admin Login HTML template)
MAIN_DASHBOARD_HTML = """...""" # (Admin Dashboard HTML template)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
