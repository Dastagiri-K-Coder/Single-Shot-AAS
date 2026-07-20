# -*- coding: utf-8 -*-
"""
web_app/app.py — Full-featured Flask backend for Single Shot AAS v2.

New in v2:
  - Google OAuth2 login flow (/auth/google, /auth/google/callback, /logout)
  - Splash → Login → Setup Wizard → Dashboard flow
  - Multi-camera attendance (POST /take-attendance accepts camera_id)
  - Setup wizard API routes (/api/setup/*)
  - Camera management routes (/api/cameras)
  - TTS voice announcement after attendance
  - Gender-aware enrollment (boys_count, girls_count in response)

Routes:
  GET  /                          → Splash screen (auto-redirect)
  GET  /splash                    → Splash animation page
  GET  /login                     → Google login page
  GET  /auth/google               → Initiate OAuth2 flow
  GET  /auth/google/callback      → OAuth2 callback, token save
  GET  /logout                    → Clear session + token
  GET  /api/auth/status           → Auth state for splash JS check
  GET  /dashboard                 → Multi-camera main dashboard
  GET  /api/status                → System health check
  GET  /api/students              → List enrolled students
  POST /api/enroll/upload         → Enroll via photo upload
  POST /api/enroll/webcam         → Enroll via browser webcam (base64)
  DELETE /api/students/<name>     → Remove a student
  POST /take-attendance           → Camera capture → recognize → mark sheet + TTS
  POST /upload-photo              → Upload classroom photo → recognize
  GET  /api/attendance/today      → Today's attendance (accepts camera_id query param)
  GET  /api/camera/stream         → MJPEG stream (accepts camera_id query param)
  GET  /api/cameras               → List all registered cameras
  POST /api/cameras               → Add a new camera
  DELETE /api/cameras/<cam_id>    → Remove a camera
  GET  /api/cameras/<cam_id>/status → Ping camera URL
  GET  /setup                     → Setup wizard step 1
  POST /api/setup/save-institution → Save institution details
  POST /api/setup/create-sections  → Create sections + Drive structure
  POST /api/setup/assign-cameras   → Save camera URLs
  GET  /setup/step2, /setup/step3, /setup/complete
  GET  /api/settings              → Get current settings
  POST /api/settings              → Save settings
  GET  /captured/<filename>       → Serve captured images
  GET  /photos/<filename>         → Serve student photos
"""

import os
import sys
import json
import base64
import pickle
import datetime
import traceback
import threading

from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, Response, redirect, url_for, session
)
from flask_cors import CORS
from dotenv import set_key as dotenv_set_key

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recognition
import capture
import spreadsheet
from config import (
    CAPTURED_FOLDER, PHOTO_FOLDER, ENCODINGS_FOLDER,
    RECOGNITION_TOLERANCE, RECOGNITION_SCALE, MAX_IN_TIME,
    VOICE_TRIGGER_PHRASE, IP_CAMERA_URL, WEBCAM_INDEX,
    INSTITUTION_JSON_PATH, CAMERAS_JSON_PATH,
    OAUTH_CREDS_PATH, TOKEN_PATH,
)

import face_recognition as fr
import cv2
import numpy as np


def create_app() -> Flask:
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    static_dir   = os.path.join(os.path.dirname(__file__), 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "single-shot-aas-secret-v2")
    CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

    # ── Auth helpers ─────────────────────────────────────────────────────────

    def _is_authenticated() -> bool:
        try:
            from oauth import is_authenticated
            return is_authenticated() and session.get("user_email")
        except Exception:
            return False

    def _is_setup_complete() -> bool:
        if not os.path.exists(INSTITUTION_JSON_PATH):
            return False
        try:
            with open(INSTITUTION_JSON_PATH) as f:
                inst = json.load(f)
            return bool(inst.get("drive_root_folder_id") and inst.get("institution_name"))
        except Exception:
            return False

    def _get_creds():
        from oauth import get_credentials
        return get_credentials()

    def login_required(f):
        """Decorator: redirect to /login if not authenticated."""
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            if not _is_authenticated():
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated

    def _load_institution() -> dict:
        if os.path.exists(INSTITUTION_JSON_PATH):
            try:
                with open(INSTITUTION_JSON_PATH) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_institution(data: dict) -> None:
        data["updated_at"] = datetime.datetime.now().isoformat()
        with open(INSTITUTION_JSON_PATH, "w") as f:
            json.dump(data, f, indent=2)

    # ── Student helpers ───────────────────────────────────────────────────────

    def _student_photo(name: str):
        for angle in ['_front', '_left', '_right', '']:
            for ext in ['.jpg', '.jpeg', '.png']:
                fname = f"{name}{angle}{ext}"
                if os.path.exists(os.path.join(PHOTO_FOLDER, fname)):
                    return f"/photos/{fname}"
        return None

    def _enrolled_students():
        students = []
        if not os.path.isdir(ENCODINGS_FOLDER):
            return students
        for fname in sorted(os.listdir(ENCODINGS_FOLDER)):
            if not fname.endswith('.pkl'):
                continue
            name     = fname[:-4]
            pkl_path = os.path.join(ENCODINGS_FOLDER, fname)
            try:
                with open(pkl_path, 'rb') as f:
                    payload = pickle.load(f)
                if isinstance(payload, dict):
                    angles  = len(payload.get("encodings", []))
                    gender  = payload.get("gender", "M")
                    display = payload.get("name", name).replace('_', ' ').title()
                elif isinstance(payload, list):
                    angles  = len(payload)
                    gender  = "M"
                    display = name.replace('_', ' ').title()
                else:
                    angles  = 1
                    gender  = "M"
                    display = name.replace('_', ' ').title()
            except Exception:
                angles  = 0
                gender  = "M"
                display = name.replace('_', ' ').title()
            students.append({
                'name':    name,
                'display': display,
                'gender':  gender,
                'photo':   _student_photo(name),
                'angles':  angles,
                'mtime':   os.path.getmtime(pkl_path),
            })
        return students

    # ══════════════════════════════════════════════════════════════════════════
    # Auth Routes
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/')
    def index():
        return redirect(url_for('splash'))

    @app.route('/splash')
    def splash():
        return render_template('splash.html')

    @app.route('/login')
    def login():
        if _is_authenticated():
            return redirect('/setup' if not _is_setup_complete() else '/dashboard')
        error = request.args.get('error')
        return render_template('login.html', error=error)

    @app.route('/auth/google')
    def auth_google():
        try:
            from oauth import create_oauth_flow
            flow = create_oauth_flow()
            auth_url, state = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent',
            )
            session['oauth_state'] = state
            return redirect(auth_url)
        except FileNotFoundError as e:
            return render_template('login.html', error=str(e)), 400

    @app.route('/auth/google/callback')
    def auth_google_callback():
        try:
            from oauth import create_oauth_flow, save_credentials_from_callback
            from googleapiclient.discovery import build

            flow = create_oauth_flow()
            flow.fetch_token(authorization_response=request.url)
            creds = flow.credentials

            # Get user info
            user_info_service = build('oauth2', 'v2', credentials=creds)
            user_info = user_info_service.userinfo().get().execute()
            email = user_info.get('email', '')
            name  = user_info.get('name', '')

            # Save token with user info
            from oauth import _save_token
            _save_token(creds, email=email, name=name)

            session['user_email'] = email
            session['user_name']  = name

            # Check if this is a new or returning user
            from drive_manager import check_drive_setup_exists
            if check_drive_setup_exists(creds):
                return redirect('/dashboard')
            else:
                return redirect('/setup')

        except Exception as e:
            traceback.print_exc()
            return redirect(f'/login?error={str(e)[:200]}')

    @app.route('/logout')
    def logout():
        from oauth import revoke_token
        revoke_token()
        session.clear()
        return redirect('/login')

    @app.route('/api/auth/status')
    def auth_status():
        return jsonify({
            'authenticated':  _is_authenticated(),
            'setup_complete': _is_setup_complete(),
            'user_email':     session.get('user_email', ''),
            'user_name':      session.get('user_name', ''),
        })

    # ══════════════════════════════════════════════════════════════════════════
    # Setup Wizard Routes
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/setup')
    @login_required
    def setup_step1():
        inst = _load_institution()
        return render_template('setup/step1.html', form=inst, error=None)

    @app.route('/api/setup/save-institution', methods=['POST'])
    @login_required
    def setup_save_institution():
        data = request.form.to_dict()
        required = ['institution_name', 'city', 'state', 'contact_email']
        for field in required:
            if not data.get(field, '').strip():
                return render_template('setup/step1.html', form=data,
                                       error=f"'{field}' is required."), 400
        inst = _load_institution()
        inst.update({
            'institution_name': data['institution_name'].strip(),
            'address':          data.get('address', '').strip(),
            'city':             data['city'].strip(),
            'state':            data['state'].strip(),
            'contact_email':    data['contact_email'].strip(),
        })
        if not inst.get('created_at'):
            inst['created_at'] = datetime.datetime.now().isoformat()
        _save_institution(inst)
        return redirect('/setup/step2')

    @app.route('/setup/step2')
    @login_required
    def setup_step2():
        inst = _load_institution()
        return render_template('setup/step2.html',
                               next_serial=inst.get('next_serial', 1))

    @app.route('/api/setup/create-sections', methods=['POST'])
    @login_required
    def setup_create_sections():
        try:
            data     = request.get_json(force=True)
            sections = data.get('sections', [])
            if not sections:
                return jsonify({'status': 'error', 'message': 'No sections provided'}), 400

            creds = _get_creds()
            from drive_manager import ensure_root_folder, ensure_section_folder, create_section_spreadsheet
            from camera_registry import add_camera, update_camera

            inst = _load_institution()
            # Ensure root folder
            root_id = inst.get('drive_root_folder_id') or ensure_root_folder(creds)
            inst['drive_root_folder_id'] = root_id
            _save_institution(inst)

            created = []
            for sec in sections:
                sheet_name = sec['sheet_name']
                folder_id  = ensure_section_folder(creds, root_id, sheet_name)
                sheet_id   = create_section_spreadsheet(creds, sheet_name, folder_id)

                cam = add_camera(
                    display_name = sheet_name,
                    rtsp_url     = '',
                    section_code = sec['section_code'],
                    year_start   = sec['year_start'],
                    year_end     = sec['year_end'],
                    section      = sec['section'],
                )
                update_camera(cam['id'], sheet_id=sheet_id, drive_folder_id=folder_id)
                created.append(cam['id'])

            # Increment next_serial
            inst['next_serial'] = inst.get('next_serial', 1) + len(sections)
            _save_institution(inst)

            # Upload institution.json to Drive
            try:
                from drive_manager import upload_file_to_folder
                upload_file_to_folder(creds, INSTITUTION_JSON_PATH, root_id,
                                      mime_type='application/json',
                                      drive_filename='institution_config.json')
            except Exception as e:
                print(f"  [WARN] Could not upload institution_config: {e}")

            return jsonify({'status': 'success', 'created': created})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/setup/step3')
    @login_required
    def setup_step3():
        from camera_registry import load_cameras
        cameras = load_cameras()
        return render_template('setup/step3.html',
                               cameras=cameras,
                               cameras_json=json.dumps(cameras))

    @app.route('/api/setup/test-camera', methods=['POST'])
    @login_required
    def setup_test_camera():
        data    = request.get_json(force=True)
        cam_id  = data.get('camera_id', '')
        rtsp    = data.get('rtsp_url', '').strip()
        if not rtsp:
            return jsonify({'ok': False, 'message': 'No URL provided'})
        try:
            cap = cv2.VideoCapture(rtsp)
            ok  = cap.isOpened()
            cap.release()
            return jsonify({'ok': ok, 'message': 'Connected' if ok else 'Cannot open stream'})
        except Exception as e:
            return jsonify({'ok': False, 'message': str(e)})

    @app.route('/api/setup/assign-cameras', methods=['POST'])
    @login_required
    def setup_assign_cameras():
        try:
            data    = request.get_json(force=True)
            updates = data.get('cameras', [])
            from camera_registry import update_camera
            for item in updates:
                update_camera(item['id'], rtsp_url=item.get('rtsp_url', ''))
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/setup/complete')
    @login_required
    def setup_complete():
        from camera_registry import load_cameras
        inst    = _load_institution()
        cameras = load_cameras()
        return render_template('setup/complete.html',
                               institution=inst, cameras=cameras)

    # ══════════════════════════════════════════════════════════════════════════
    # Dashboard
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/dashboard')
    @login_required
    def dashboard():
        if not _is_setup_complete():
            return redirect('/setup')
        return render_template('index.html',
                               user_name=session.get('user_name', ''),
                               user_email=session.get('user_email', ''))

    # ══════════════════════════════════════════════════════════════════════════
    # System Status
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/status')
    def status():
        students  = _enrolled_students()
        creds_ok  = os.path.exists(TOKEN_PATH) or os.path.exists(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'credentials.json'))
        from camera_registry import load_cameras
        cameras   = load_cameras()
        return jsonify({
            'status':            'online',
            'students_enrolled': len(students),
            'encodings_loaded':  len(recognition.known_face_encodings),
            'credentials_ok':    creds_ok,
            'camera_count':      len(cameras),
            'camera_mode':       f'{len(cameras)} cameras' if cameras else (
                                     'IP Camera' if IP_CAMERA_URL else f'Webcam #{WEBCAM_INDEX}'),
            'tolerance':         RECOGNITION_TOLERANCE,
            'timestamp':         datetime.datetime.now().isoformat(),
            'authenticated':     _is_authenticated(),
            'setup_complete':    _is_setup_complete(),
        })

    # ══════════════════════════════════════════════════════════════════════════
    # Camera Management
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/cameras', methods=['GET'])
    def list_cameras():
        from camera_registry import load_cameras
        cameras = load_cameras()
        return jsonify({'cameras': cameras, 'count': len(cameras)})

    @app.route('/api/cameras', methods=['POST'])
    @login_required
    def add_camera_route():
        try:
            data = request.get_json(force=True)
            from camera_registry import add_camera
            cam = add_camera(
                display_name = data.get('display_name', 'New Camera'),
                rtsp_url     = data.get('rtsp_url', ''),
                section_code = data.get('section_code', ''),
                year_start   = int(data.get('year_start', 2024)),
                year_end     = int(data.get('year_end', 2027)),
                section      = data.get('section', 'A'),
            )
            return jsonify({'status': 'success', 'camera': cam})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/cameras/<cam_id>', methods=['DELETE'])
    @login_required
    def delete_camera_route(cam_id):
        from camera_registry import delete_camera
        ok = delete_camera(cam_id)
        return jsonify({'status': 'success' if ok else 'not_found'})

    @app.route('/api/cameras/<cam_id>/status', methods=['GET'])
    def camera_status(cam_id):
        from camera_registry import get_camera
        cam = get_camera(cam_id)
        if not cam:
            return jsonify({'ok': False, 'message': 'Camera not found'}), 404
        url = cam.get('rtsp_url', '')
        if not url:
            return jsonify({'ok': False, 'message': 'No URL configured'})
        try:
            cap = cv2.VideoCapture(url)
            ok  = cap.isOpened()
            cap.release()
            return jsonify({'ok': ok, 'camera_id': cam_id,
                            'message': 'Connected' if ok else 'Unreachable'})
        except Exception as e:
            return jsonify({'ok': False, 'message': str(e)})

    # ══════════════════════════════════════════════════════════════════════════
    # Students
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/students')
    def list_students():
        return jsonify({'students': _enrolled_students(), 'count': len(_enrolled_students())})

    @app.route('/api/students/<name>', methods=['DELETE'])
    @login_required
    def delete_student(name):
        # Sanitise name to prevent path traversal
        import re
        if not re.match(r'^[A-Za-z0-9_\-]+$', name):
            return jsonify({'status': 'error', 'message': 'Invalid name format'}), 400
        deleted = []
        pkl = os.path.join(ENCODINGS_FOLDER, f"{name}.pkl")
        if os.path.exists(pkl):
            os.remove(pkl)
            deleted.append('encoding')
        if os.path.isdir(PHOTO_FOLDER):
            for f in os.listdir(PHOTO_FOLDER):
                if f.startswith(name + '_') or f.startswith(name + '.'):
                    os.remove(os.path.join(PHOTO_FOLDER, f))
                    deleted.append(f'photo:{f}')
        try:
            recognition.load_facial_encodings_and_names_from_memory()
        except Exception:
            pass
        return jsonify({'status': 'success', 'deleted': deleted, 'name': name})

    # ══════════════════════════════════════════════════════════════════════════
    # Enrollment
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/enroll/upload', methods=['POST'])
    def enroll_upload():
        name   = request.form.get('name', '').strip().replace(' ', '_')
        email  = request.form.get('email', '').strip()
        gender = request.form.get('gender', 'M').strip().upper() or 'M'
        cam_id = request.form.get('camera_id', '')

        if not name:
            return jsonify({'status': 'error', 'message': 'Student name is required'}), 400

        files = request.files.getlist('photos')
        if not files or all(f.filename == '' for f in files):
            return jsonify({'status': 'error', 'message': 'At least one photo required'}), 400

        # Use camera-specific encodings folder if camera_id given
        enc_folder = ENCODINGS_FOLDER
        if cam_id:
            from camera_registry import get_encodings_path
            p = get_encodings_path(cam_id)
            if p:
                enc_folder = p

        os.makedirs(PHOTO_FOLDER, exist_ok=True)
        os.makedirs(enc_folder,   exist_ok=True)

        angles_map  = ['front', 'left', 'right']
        saved_encs  = []
        saved_photos = []

        for i, file in enumerate(files[:3]):
            if file.filename == '':
                continue
            angle    = angles_map[i] if i < len(angles_map) else f'angle{i}'
            ext      = os.path.splitext(file.filename)[1].lower() or '.jpg'
            save_name = f"{name}_{angle}{ext}"
            save_path = os.path.join(PHOTO_FOLDER, save_name)
            file.save(save_path)
            img  = fr.load_image_file(save_path)
            locs = fr.face_locations(img)
            if not locs:
                os.remove(save_path)
                return jsonify({'status': 'error',
                                'message': f'No face detected in photo {i+1} ({angle}).'}), 400
            enc = fr.face_encodings(img, locs)[0]
            saved_encs.append(enc)
            saved_photos.append(save_name)

        if not saved_encs:
            return jsonify({'status': 'error', 'message': 'No valid face encodings'}), 400

        # Save as new dict format with gender
        pkl_path = os.path.join(enc_folder, f"{name}.pkl")
        payload  = {"name": name, "gender": gender, "encodings": saved_encs}
        with open(pkl_path, 'wb') as fp:
            pickle.dump(payload, fp)

        # Enroll in sheet
        sheet_msg = ''
        if email and cam_id:
            try:
                from camera_registry import get_camera
                from spreadsheet import SpreadsheetManager
                cam = get_camera(cam_id)
                if cam and cam.get('sheet_id'):
                    mgr = SpreadsheetManager(_get_creds())
                    mgr.enroll_person_to_sheet(cam['sheet_id'],
                                               name.replace('_', ' '), email, gender)
                    sheet_msg = 'Added to Google Sheet.'
            except Exception as e:
                sheet_msg = f'Sheet not updated ({e})'
        elif email:
            try:
                spreadsheet.enroll_person_to_sheet(name.replace('_', ' '), email, gender)
                sheet_msg = 'Added to Google Sheet.'
            except Exception as e:
                sheet_msg = f'Sheet not updated ({e})'

        recognition.load_facial_encodings_and_names_from_memory()
        return jsonify({
            'status':  'success',
            'name':    name,
            'gender':  gender,
            'angles':  len(saved_encs),
            'photos':  saved_photos,
            'sheet':   sheet_msg,
            'message': f"✓ {name.replace('_',' ')} enrolled ({gender}) with {len(saved_encs)} photo(s).",
        })

    @app.route('/api/enroll/webcam', methods=['POST'])
    def enroll_webcam():
        data     = request.get_json(force=True)
        name     = data.get('name', '').strip().replace(' ', '_')
        angle    = data.get('angle', 'front').lower()
        img_b64  = data.get('image', '')
        email    = data.get('email', '').strip()
        gender   = data.get('gender', 'M').upper()
        finalize = data.get('finalize', False)
        cam_id   = data.get('camera_id', '')

        if not name:
            return jsonify({'status': 'error', 'message': 'Student name required'}), 400

        enc_folder = ENCODINGS_FOLDER
        if cam_id:
            from camera_registry import get_encodings_path
            p = get_encodings_path(cam_id)
            if p:
                enc_folder = p

        os.makedirs(PHOTO_FOLDER, exist_ok=True)
        os.makedirs(enc_folder,   exist_ok=True)

        if img_b64:
            try:
                img_bytes = base64.b64decode(img_b64.split(',')[-1])
                nparr     = np.frombuffer(img_bytes, np.uint8)
                frame     = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception as e:
                return jsonify({'status': 'error', 'message': f'Image decode error: {e}'}), 400

            save_path = os.path.join(PHOTO_FOLDER, f"{name}_{angle}.jpg")
            cv2.imwrite(save_path, frame)

            rgb  = frame[:, :, ::-1]
            locs = fr.face_locations(rgb)
            if not locs:
                os.remove(save_path)
                return jsonify({'status': 'no_face', 'message': f'No face for {angle}. Retry.'})

            enc      = fr.face_encodings(rgb, locs)[0]
            pkl_path = os.path.join(enc_folder, f"{name}.pkl")

            existing_encs   = []
            existing_gender = gender
            if os.path.exists(pkl_path):
                with open(pkl_path, 'rb') as fp:
                    payload = pickle.load(fp)
                if isinstance(payload, dict):
                    existing_encs   = payload.get("encodings", [])
                    existing_gender = payload.get("gender", gender)
                elif isinstance(payload, list):
                    existing_encs = payload
            existing_encs.append(enc)
            with open(pkl_path, 'wb') as fp:
                pickle.dump({"name": name, "gender": existing_gender, "encodings": existing_encs}, fp)

        if finalize:
            sheet_msg = ''
            if email:
                try:
                    if cam_id:
                        from camera_registry import get_camera
                        from spreadsheet import SpreadsheetManager
                        cam = get_camera(cam_id)
                        if cam and cam.get('sheet_id'):
                            mgr = SpreadsheetManager(_get_creds())
                            mgr.enroll_person_to_sheet(cam['sheet_id'],
                                                       name.replace('_', ' '), email, gender)
                            sheet_msg = 'Added to Google Sheet.'
                    else:
                        spreadsheet.enroll_person_to_sheet(name.replace('_', ' '), email, gender)
                        sheet_msg = 'Added to Google Sheet.'
                except Exception as e:
                    sheet_msg = f'Sheet not updated: {e}'
            recognition.load_facial_encodings_and_names_from_memory()
            return jsonify({'status': 'enrolled', 'name': name,
                            'sheet': sheet_msg,
                            'message': f"✓ {name.replace('_',' ')} fully enrolled!"})

        return jsonify({'status': 'angle_saved', 'angle': angle,
                        'message': f'✓ {angle.title()} captured'})

    # ══════════════════════════════════════════════════════════════════════════
    # Attendance (Multi-Camera)
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/take-attendance', methods=['POST'])
    def take_attendance():
        try:
            data   = request.get_json(force=True) or {}
            cam_id = data.get('camera_id', '')

            if not recognition.known_face_encodings:
                recognition.load_facial_encodings_and_names_from_memory()

            sheet_synced = True
            sheet_msg    = ''

            # Get the sheet for this camera
            sheet_id = None
            cam_total = 0
            if cam_id:
                from camera_registry import get_camera
                cam = get_camera(cam_id)
                if cam:
                    sheet_id  = cam.get('sheet_id', '')
                    cam_total = 0  # will be calculated from sheet

            # Mark all absent first
            try:
                if sheet_id:
                    from spreadsheet import SpreadsheetManager
                    mgr = SpreadsheetManager(_get_creds())
                    mgr.mark_all_absent(sheet_id)
                    cam_total = mgr.get_class_total(sheet_id)
                else:
                    spreadsheet.mark_all_absent()
            except Exception as e:
                sheet_synced = False
                sheet_msg    = str(e)

            # Capture
            img_path  = capture.capture_single_shot(camera_id=cam_id)
            result    = recognition.run_recognition(img_path)
            annotated = recognition.annotate_image(img_path, result)
            annotated_url = f"/captured/{os.path.basename(annotated)}" if annotated else None

            # Write present/late for each recognized student
            if sheet_id:
                from spreadsheet import SpreadsheetManager
                mgr = SpreadsheetManager(_get_creds())
                for name in result.get('present', []):
                    mgr.write_to_sheet(sheet_id, name)
            else:
                for name in result.get('present', []):
                    spreadsheet.write_to_sheet(name)

            boys_count  = result.get('boys_count', 0)
            girls_count = result.get('girls_count', 0)
            total_class = cam_total or len(result.get('present', [])) + result.get('unknown_count', 0)

            # TTS announcement (non-blocking)
            try:
                from tts import announce_attendance
                announce_attendance(boys=boys_count, girls=girls_count, total=total_class)
            except Exception as e:
                print(f"  [TTS] Announcement skipped: {e}")

            return jsonify({
                'status':        'success',
                'camera_id':     cam_id,
                'present':       result['present'],
                'boys_count':    boys_count,
                'girls_count':   girls_count,
                'unknown_count': result['unknown_count'],
                'total_faces':   result['total_faces'],
                'total_class':   total_class,
                'timestamp':     datetime.datetime.now().strftime('%I:%M %p, %d %b %Y'),
                'annotated_img': annotated_url,
                'sheet_synced':  sheet_synced,
                'sheet_msg':     sheet_msg,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/upload-photo', methods=['POST'])
    def upload_photo():
        if 'photo' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file uploaded'}), 400
        file  = request.files['photo']
        cam_id = request.form.get('camera_id', '')
        os.makedirs(CAPTURED_FOLDER, exist_ok=True)
        ts        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(CAPTURED_FOLDER, f"upload_{ts}.jpg")
        file.save(save_path)
        try:
            if not recognition.known_face_encodings:
                recognition.load_facial_encodings_and_names_from_memory()
            sheet_synced = True
            sheet_msg    = ''
            sheet_id     = None
            if cam_id:
                from camera_registry import get_camera
                cam = get_camera(cam_id)
                if cam:
                    sheet_id = cam.get('sheet_id', '')
            try:
                if sheet_id:
                    from spreadsheet import SpreadsheetManager
                    mgr = SpreadsheetManager(_get_creds())
                    mgr.mark_all_absent(sheet_id)
                else:
                    spreadsheet.mark_all_absent()
            except Exception as e:
                sheet_synced = False
                sheet_msg    = str(e)
            result    = recognition.run_recognition(save_path)
            annotated = recognition.annotate_image(save_path, result)
            annotated_url = f"/captured/{os.path.basename(annotated)}" if annotated else None

            if sheet_id:
                from spreadsheet import SpreadsheetManager
                mgr = SpreadsheetManager(_get_creds())
                for name in result.get('present', []):
                    mgr.write_to_sheet(sheet_id, name)
            else:
                for name in result.get('present', []):
                    spreadsheet.write_to_sheet(name)

            boys_count  = result.get('boys_count', 0)
            girls_count = result.get('girls_count', 0)
            try:
                from tts import announce_attendance
                total_class = boys_count + girls_count + result.get('unknown_count', 0)
                announce_attendance(boys=boys_count, girls=girls_count, total=total_class)
            except Exception:
                pass

            return jsonify({
                'status':        'success',
                'present':       result['present'],
                'boys_count':    boys_count,
                'girls_count':   girls_count,
                'unknown_count': result['unknown_count'],
                'total_faces':   result['total_faces'],
                'timestamp':     datetime.datetime.now().strftime('%I:%M %p, %d %b %Y'),
                'annotated_img': annotated_url,
                'sheet_synced':  sheet_synced,
                'sheet_msg':     sheet_msg,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({'status': 'error', 'message': str(e)}), 500

    # ══════════════════════════════════════════════════════════════════════════
    # Attendance Today
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/attendance/today')
    def attendance_today():
        cam_id   = request.args.get('camera_id', '')
        sheet_id = request.args.get('sheet_id', '')
        try:
            if cam_id:
                from camera_registry import get_camera
                cam = get_camera(cam_id)
                if cam:
                    sheet_id = cam.get('sheet_id', '')
            if sheet_id:
                from spreadsheet import SpreadsheetManager
                mgr = SpreadsheetManager(_get_creds())
                records = mgr.get_today_records(sheet_id)
                return jsonify({'status': 'success', 'records': records, 'camera_id': cam_id})
            # Legacy single-sheet
            s      = spreadsheet._get_sheet()
            today  = spreadsheet._today_string()
            header = s.row_values(1)
            if today not in header:
                return jsonify({'status': 'success', 'date': today, 'records': [],
                                'message': 'No attendance column for today yet.'})
            col    = header.index(today) + 1
            names  = s.col_values(1)[1:]
            statuses = s.col_values(col)[1:]
            records = [{'name': n, 'status': statuses[i] if i < len(statuses) else 'absent'}
                       for i, n in enumerate(names)]
            return jsonify({'status': 'success', 'date': today, 'records': records})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    # ══════════════════════════════════════════════════════════════════════════
    # Camera MJPEG Stream
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/camera/stream')
    def camera_stream():
        cam_id = request.args.get('camera_id', '')
        def generate():
            src = capture.get_camera_source(camera_id=cam_id)
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                return
            deadline = __import__('time').time() + 300  # 5 min max stream
            try:
                while __import__('time').time() < deadline:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                           + buf.tobytes() + b'\r\n')
            finally:
                cap.release()
        return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

    # ══════════════════════════════════════════════════════════════════════════
    # Static Files
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/captured/<filename>')
    def serve_captured(filename):
        return send_from_directory(CAPTURED_FOLDER, filename)

    @app.route('/photos/<filename>')
    def serve_photo(filename):
        return send_from_directory(PHOTO_FOLDER, filename)

    # ══════════════════════════════════════════════════════════════════════════
    # Settings
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/settings', methods=['GET'])
    def get_settings():
        return jsonify({
            'tolerance':     RECOGNITION_TOLERANCE,
            'scale':         RECOGNITION_SCALE,
            'max_in_time':   MAX_IN_TIME,
            'camera_url':    IP_CAMERA_URL,
            'webcam_index':  WEBCAM_INDEX,
            'voice_phrase':  VOICE_TRIGGER_PHRASE,
        })

    @app.route('/api/settings', methods=['POST'])
    @login_required
    def save_settings():
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.env'
        )
        data = request.get_json(force=True) or {}
        key_map = {
            'tolerance':    'RECOGNITION_TOLERANCE',
            'scale':        'RECOGNITION_SCALE',
            'max_in_time':  'MAX_IN_TIME',
            'camera_url':   'IP_CAMERA_URL',
            'webcam_index': 'WEBCAM_INDEX',
            'voice_phrase': 'VOICE_TRIGGER_PHRASE',
        }
        updated = {}
        for field, env_key in key_map.items():
            if field in data:
                value = str(data[field]).strip()
                dotenv_set_key(env_path, env_key, value)
                updated[field] = value
        if not updated:
            return jsonify({'status': 'error', 'message': 'No valid fields provided'}), 400
        return jsonify({
            'status':  'success',
            'updated': updated,
            'message': f"Settings saved: {', '.join(updated.keys())}. Restart to apply.",
        })

    return app
