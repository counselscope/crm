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

# Persistent storage path setup for Cloud (Render/Heroku/Local)
# Render पर डिस्क माउंट करने केلिए '/opt/render/project/src/student_documents' या लोकल फोल्डर उपयोग करें
UPLOAD_FOLDER = os.path.join(os.getcwd(), "student_documents")
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
                # Create a secure folder structure for the student name inside UPLOAD_FOLDER
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


@app.route('/api/delete-lead', methods=['POST'])
def delete_lead():
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized"}}, 401
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


# --- LOGIN & DASHBOARD HTML TEMPLATES (SAME AS BEFORE) ---
LOGIN_HTML = """...""" # (वही पुराना लॉगिन HTML कोड यहाँ रखें)
MAIN_DASHBOARD_HTML = """...""" # (वही पुराना डैशबोर्ड HTML कोड यहाँ रखें)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
