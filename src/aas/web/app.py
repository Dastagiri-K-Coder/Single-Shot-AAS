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

from aas.core.safe_pickle import safe_load as _safe_load

from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, Response, redirect, url_for, session
)
from flask_cors import CORS
from dotenv import set_key as dotenv_set_key

from aas.recognition import engine as recognition
from aas.capture import capture
from aas.attendance import spreadsheet
from aas.core.config import (
    CAPTURED_FOLDER, PHOTO_FOLDER, ENCODINGS_FOLDER,
    RECOGNITION_TOLERANCE, RECOGNITION_SCALE, AUTO_SCALE_DETECTION,
    MIN_FACE_SIZE, MIN_IPD_PIXELS, BLUR_THRESHOLD, MAX_IN_TIME,
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
    secret = os.getenv("FLASK_SECRET_KEY")
    if not secret:
        import secrets as _secrets
        secret = _secrets.token_hex(32)
        # Persist so sessions survive restarts
        try:
            from aas.core.config import ROOT_DIR as _root
            dotenv_set_key(os.path.join(_root, '.env'), "FLASK_SECRET_KEY", secret)
            print("  ✓ Generated and saved new FLASK_SECRET_KEY to .env")
        except Exception:
            pass  # Will regenerate on next restart if .env write fails
    app.secret_key = secret
    CORS(app, origins=["http://localhost:5000", "http://127.0.0.1:5000"])

    # ── Auth helpers ─────────────────────────────────────────────────────────

    def _is_authenticated() -> bool:
        if app.config.get("TESTING"):
            return True
        # --- v2.0: prefer local session token ---
        token = request.cookies.get("aas_session")
        if token:
            try:
                from aas.core.auth import validate_session
                user = validate_session(token)
                if user:
                    # Sync into Flask session for backward-compat helpers
                    session["user_id"]    = user["user_id"]
                    session["user_email"] = user.get("email", "")
                    session["user_name"]  = user.get("full_name", "")
                    session["role"]       = user["role"]
                    return True
            except Exception:
                pass
        # --- Legacy: Google OAuth fallback ---
        try:
            from aas.integrations.google.oauth import is_authenticated
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
        from aas.integrations.google.oauth import get_credentials
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
                payload = _safe_load(pkl_path)
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

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        # --- v2.0 Local Login (POST) ---
        if request.method == 'POST':
            uid = request.form.get('user_id', '').strip().upper()
            pwd = request.form.get('password', '')
            if not uid or not pwd:
                return render_template('login.html', error='ID and password are required.')
            try:
                from aas.core.auth import (
                    db_get_user, verify_password,
                    db_increment_failed, db_reset_failed,
                    create_session, log_audit
                )
                from aas.core.db import init_db, has_any_users
                init_db()
                if not has_any_users():
                    return redirect('/setup/wizard')
                user = db_get_user(uid)
                if not user:
                    return render_template('login.html', error='Invalid ID or Password.')
                if not user['is_active']:
                    return render_template('login.html', error='Account deactivated. Contact Admin.')
                if user['is_locked']:
                    return render_template('login.html', error='Account locked. Contact Admin.')
                if not verify_password(pwd, user['password_hash']):
                    db_increment_failed(uid)
                    log_audit(uid, 'login_failed', 'Wrong password.', request.remote_addr)
                    return render_template('login.html', error='Invalid ID or Password.')
                # Successful login
                db_reset_failed(uid)
                token = create_session(uid, user['role'], request.remote_addr)
                log_audit(uid, 'login', 'Successful login.', request.remote_addr)
                session['user_id']    = uid
                session['user_email'] = user.get('email', '')
                session['user_name']  = user.get('full_name', '')
                session['role']       = user['role']
                resp = redirect('/dashboard' if _is_setup_complete() else '/setup')
                resp.set_cookie('aas_session', token,
                                httponly=True, samesite='Lax',
                                max_age=8 * 3600)
                if user.get('must_change_password'):
                    resp = redirect('/change-password')
                    resp.set_cookie('aas_session', token,
                                    httponly=True, samesite='Lax',
                                    max_age=8 * 3600)
                return resp
            except Exception as e:
                traceback.print_exc()
                return render_template('login.html', error=f'Login error: {e}'), 500

        # --- GET: show login page ---
        # If already authenticated redirect immediately
        if _is_authenticated():
            return redirect('/setup' if not _is_setup_complete() else '/dashboard')
        error = request.args.get('error')
        return render_template('login.html', error=error)

    @app.route('/change-password', methods=['GET', 'POST'])
    @login_required
    def change_password():
        if request.method == 'POST':
            new_pwd  = request.form.get('new_password', '')
            confirm  = request.form.get('confirm_password', '')
            if not new_pwd or len(new_pwd) < 8:
                return render_template('change_password.html',
                                       error='Password must be at least 8 characters.')
            if new_pwd != confirm:
                return render_template('change_password.html',
                                       error='Passwords do not match.')
            try:
                from aas.core.auth import db_set_password
                db_set_password(session.get('user_id', ''), new_pwd, clear_force_change=True)
                return redirect('/dashboard')
            except Exception as e:
                return render_template('change_password.html', error=str(e))
        return render_template('change_password.html')

    @app.route('/auth/google')
    def auth_google():
        try:
            from aas.integrations.google.oauth import create_oauth_flow
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
            # Validate OAuth state to prevent CSRF
            expected_state = session.pop('oauth_state', None)
            received_state = request.args.get('state')
            if not expected_state or expected_state != received_state:
                return redirect('/login?error=Invalid+OAuth+state.+Please+try+again.')

            from aas.integrations.google.oauth import create_oauth_flow, save_credentials_from_callback
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
            from aas.integrations.google.oauth import _save_token
            _save_token(creds, email=email, name=name)

            session['user_email'] = email
            session['user_name']  = name

            # Check if this is a new or returning user
            from aas.integrations.google.drive_manager import check_drive_setup_exists
            if check_drive_setup_exists(creds):
                return redirect('/dashboard')
            else:
                return redirect('/setup')

        except Exception as e:
            traceback.print_exc()
            return redirect(f'/login?error={str(e)[:200]}')

    @app.route('/logout')
    def logout():
        # v2.0: delete local session token
        token = request.cookies.get('aas_session')
        if token:
            try:
                from aas.core.auth import delete_session, log_audit
                log_audit(session.get('user_id'), 'logout', '', request.remote_addr)
                delete_session(token)
            except Exception:
                pass
        # Legacy: Google OAuth revoke
        try:
            from aas.integrations.google.oauth import revoke_token
            revoke_token()
        except Exception:
            pass
        session.clear()
        resp = redirect('/login')
        resp.delete_cookie('aas_session')
        return resp

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
            from aas.integrations.google.drive_manager import ensure_root_folder, ensure_section_folder, create_section_spreadsheet
            from aas.capture.camera_registry import add_camera, update_camera

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
                from aas.integrations.google.drive_manager import upload_file_to_folder
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
        from aas.capture.camera_registry import load_cameras
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
            from aas.capture.camera_registry import update_camera
            for item in updates:
                update_camera(item['id'], rtsp_url=item.get('rtsp_url', ''))
            return jsonify({'status': 'success'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/setup/complete')
    @login_required
    def setup_complete():
        from aas.capture.camera_registry import load_cameras
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

        from aas.core.roles import (
            get_user_role, get_faculty_cameras,
            get_faculty_cameras_by_id, get_current_period
        )
        # Determine role — prefer SQLite session, fall back to Google OAuth path
        role    = session.get('role', '')
        user_id = session.get('user_id', '')
        email   = session.get('user_email', '')

        if not role:
            role = get_user_role(email) if email else 'faculty'

        if role == 'faculty':
            # Get cameras assigned to this faculty
            if user_id:
                cameras = get_faculty_cameras_by_id(user_id)
            else:
                cameras = get_faculty_cameras(email)
            # Auto-detect current period for each camera
            current_periods = {
                cam['id']: get_current_period(cam['id'])
                for cam in cameras
            }
            return render_template(
                'index.html',
                layout='faculty',
                cameras=cameras,
                current_periods=current_periods,
                user_name=session.get('user_name', ''),
                user_email=email,
                user_id=user_id or '',
            )
        else:
            from aas.capture.camera_registry import load_cameras
            cameras = load_cameras()
            return render_template(
                'index.html',
                layout='admin',
                cameras=cameras,
                current_periods={},
                user_name=session.get('user_name', ''),
                user_email=email,
                user_id=user_id or '',
            )

    # ══════════════════════════════════════════════════════════════════════════
    # System Status
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/status')
    def status():
        students  = _enrolled_students()
        creds_ok  = os.path.exists(TOKEN_PATH) or os.path.exists(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'credentials.json'))
        from aas.capture.camera_registry import load_cameras
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
    # v2.0 — Faculty APIs (role-aware)
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/faculty/cameras', methods=['GET'])
    @login_required
    def faculty_cameras_api():
        """Return cameras assigned to the logged-in faculty (or all for admin)."""
        from aas.core.roles import get_faculty_cameras, get_faculty_cameras_by_id
        from aas.capture.camera_registry import load_cameras
        role    = session.get('role', 'faculty')
        user_id = session.get('user_id', '')
        email   = session.get('user_email', '')
        if role == 'admin':
            cameras = load_cameras()
        elif user_id:
            cameras = get_faculty_cameras_by_id(user_id)
        else:
            cameras = get_faculty_cameras(email)
        return jsonify({'cameras': cameras, 'count': len(cameras)})

    @app.route('/api/setup/assign-faculty', methods=['POST'])
    @login_required
    def assign_faculty():
        """Admin: assign a faculty member (by email) to a camera/section."""
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        data = request.get_json(force=True) or {}
        cam_id        = data.get('camera_id', '').strip()
        faculty_email = data.get('faculty_email', '').strip()
        faculty_name  = data.get('faculty_name', '').strip()
        if not cam_id or not faculty_email:
            return jsonify({'status': 'error', 'message': 'camera_id and faculty_email are required.'}), 400
        from aas.capture.camera_registry import update_camera
        cam = update_camera(cam_id,
                            assigned_faculty_email=faculty_email,
                            faculty_name=faculty_name)
        if not cam:
            return jsonify({'status': 'error', 'message': f'Camera {cam_id} not found.'}), 404
        return jsonify({'status': 'success', 'camera': cam})

    # ══════════════════════════════════════════════════════════════════════════
    # v2.0 — Timetable APIs
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/timetable/<camera_id>', methods=['GET'])
    @login_required
    def get_timetable(camera_id):
        """Return current period + full schedule for a camera/section."""
        from aas.core.roles import get_current_period, get_full_schedule
        current = get_current_period(camera_id)
        schedule = get_full_schedule(camera_id)
        return jsonify({
            'camera_id':      camera_id,
            'current_period': current,
            'schedule':       schedule,
        })

    @app.route('/api/timetable/<camera_id>', methods=['POST'])
    @login_required
    def save_timetable(camera_id):
        """Admin: save/update timetable for a camera/section."""
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        data = request.get_json(force=True) or {}
        schedule = data.get('schedule', [])
        if not isinstance(schedule, list):
            return jsonify({'status': 'error', 'message': 'schedule must be a list.'}), 400
        try:
            from aas.core.roles import save_schedule
            save_schedule(camera_id, schedule)
            return jsonify({'status': 'success', 'camera_id': camera_id, 'periods': len(schedule)})
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    # ══════════════════════════════════════════════════════════════════════════
    # v2.0 — Attendance Fallback APIs
    # ══════════════════════════════════════════════════════════════════════════

    # In-memory attendance session store: {session_token: {student_name: status}}
    _attendance_sessions: dict = {}

    def _get_attendance_session() -> dict:
        """Return or create the per-session attendance state dict."""
        token = request.cookies.get('aas_session', 'default')
        if token not in _attendance_sessions:
            _attendance_sessions[token] = {}
        return _attendance_sessions[token]

    @app.route('/api/attendance/override', methods=['POST'])
    @login_required
    def attendance_override():
        """Level 1/3 Fallback: manually toggle a student's attendance status."""
        data   = request.get_json(force=True) or {}
        cam_id = data.get('camera_id', '').strip()
        name   = data.get('name', '').strip()
        status = data.get('status', '').strip().lower()
        if not cam_id or not name or status not in ('present', 'absent'):
            return jsonify({
                'status': 'error',
                'message': 'camera_id, name, and status (present|absent) are required.'
            }), 400
        att_state = _get_attendance_session()
        att_state[name] = status
        return jsonify({
            'status':  'success',
            'updated': f'{name} → {status}',
            'name':    name,
            'new_status': status,
        })

    @app.route('/take-attendance-individual', methods=['POST'])
    @login_required
    def take_attendance_individual():
        """Level 2 Fallback: run recognition on a close-up photo of ONE student."""
        cam_id      = request.form.get('camera_id', '').strip()
        target_name = request.form.get('target_name', '').strip()
        if not cam_id or not target_name:
            return jsonify({'status': 'error',
                            'message': 'camera_id and target_name are required.'}), 400
        if 'photo' not in request.files:
            return jsonify({'status': 'error', 'message': 'No photo file uploaded.'}), 400

        photo_file = request.files['photo']
        file_bytes = photo_file.read()
        if not file_bytes:
            return jsonify({'status': 'error', 'message': 'Uploaded photo is empty.'}), 400

        try:
            # Save uploaded photo via Mode D
            from aas.capture.capture import capture_from_upload
            img_path = capture_from_upload(file_bytes, camera_id=cam_id)

            # Load ONLY the target student's encoding
            from aas.capture.camera_registry import get_encodings_path
            from aas.core.safe_pickle import safe_load as _sl
            import os as _os
            enc_path = get_encodings_path(cam_id)
            if not enc_path:
                enc_path = ENCODINGS_FOLDER

            # Build single-student encoding set
            safe_name = target_name.replace(' ', '_')
            pkl_file  = _os.path.join(enc_path, f'{safe_name}.pkl')
            if not _os.path.exists(pkl_file):
                # Try root encodings folder
                pkl_file = _os.path.join(ENCODINGS_FOLDER, f'{safe_name}.pkl')
            if not _os.path.exists(pkl_file):
                return jsonify({'status': 'error',
                                'message': f'No encoding found for {target_name}.'}), 404

            payload = _sl(pkl_file)
            if isinstance(payload, dict):
                target_encs = payload.get('encodings', [])
            elif isinstance(payload, list):
                target_encs = payload
            else:
                target_encs = []

            if not target_encs:
                return jsonify({'status': 'error',
                                'message': f'No valid encodings for {target_name}.'}), 500

            # Run face recognition against only this student
            if not recognition.known_face_encodings:
                recognition.load_facial_encodings_and_names_from_memory()

            # Temporarily override encoding set for single-student comparison
            orig_encs  = recognition.known_face_encodings[:]
            orig_names = recognition.known_face_names[:]
            recognition.known_face_encodings = target_encs
            recognition.known_face_names     = [target_name] * len(target_encs)

            try:
                result = recognition.run_recognition(img_path)
            finally:
                recognition.known_face_encodings = orig_encs
                recognition.known_face_names     = orig_names

            matched = target_name in result.get('present', [])
            new_status = 'present' if matched else 'absent'

            # Auto-apply override if matched
            if matched:
                att_state = _get_attendance_session()
                att_state[target_name] = 'present'

            return jsonify({
                'matched':  matched,
                'name':     target_name,
                'status':   new_status,
            })
        except Exception as e:
            traceback.print_exc()
            return jsonify({'status': 'error', 'message': str(e)}), 500

    # ══════════════════════════════════════════════════════════════════════════
    # v2.0 — PWA Manifest + Service Worker
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/manifest.json')
    def serve_manifest():
        return send_from_directory(static_dir, 'manifest.json',
                                   mimetype='application/manifest+json')

    @app.route('/sw.js')
    def serve_sw():
        return send_from_directory(static_dir, 'sw.js',
                                   mimetype='application/javascript')

    # ══════════════════════════════════════════════════════════════════════════
    # v2.0 — Admin User Management APIs
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/admin/users', methods=['GET'])
    @login_required
    def admin_users():
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        from aas.core.auth import get_all_users
        users = get_all_users()
        return render_template('user_management.html', users=users)

    @app.route('/api/admin/users', methods=['GET'])
    @login_required
    def api_list_users():
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        from aas.core.auth import get_all_users
        return jsonify({'users': get_all_users()})

    @app.route('/api/admin/users/create', methods=['POST'])
    @login_required
    def api_create_user():
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        data = request.get_json(force=True) or {}
        required = ['user_id', 'full_name', 'role', 'password']
        for f in required:
            if not data.get(f):
                return jsonify({'status': 'error', 'message': f'{f} is required.'}), 400
        try:
            from aas.core.auth import db_create_user
            user = db_create_user(
                user_id          = data['user_id'],
                full_name        = data['full_name'],
                role             = data['role'],
                plain_password   = data['password'],
                email            = data.get('email', ''),
                assigned_cameras = data.get('assigned_cameras', []),
                created_by       = session.get('user_id', 'admin'),
                must_change_password = data.get('must_change_password', True),
            )
            uid = user.get('user_id', data['user_id']) if isinstance(user, dict) else data['user_id']
            return jsonify({'status': 'success', 'user': user, 'user_id': uid})
        except ValueError as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/admin/users/<user_id>/reset-password', methods=['POST'])
    @login_required
    def api_reset_password(user_id):
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        data = request.get_json(force=True) or {}
        new_pwd = data.get('password', '')
        if not new_pwd or len(new_pwd) < 8:
            return jsonify({'status': 'error', 'message': 'Password must be ≥ 8 chars.'}), 400
        from aas.core.auth import db_set_password
        db_set_password(user_id, new_pwd, clear_force_change=False)
        return jsonify({'status': 'success', 'message': f'Password reset for {user_id}.'})

    @app.route('/api/admin/users/<user_id>/unlock', methods=['POST'])
    @login_required
    def api_unlock_user(user_id):
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        from aas.core.auth import unlock_user
        unlock_user(user_id, unlocked_by=session.get('user_id', 'admin'))
        return jsonify({'status': 'success', 'message': f'{user_id} unlocked.'})

    @app.route('/api/admin/users/<user_id>/deactivate', methods=['POST'])
    @login_required
    def api_deactivate_user(user_id):
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        if user_id == session.get('user_id'):
            return jsonify({'status': 'error', 'message': 'Cannot deactivate yourself.'}), 400
        from aas.core.auth import deactivate_user
        deactivate_user(user_id, deactivated_by=session.get('user_id', 'admin'))
        return jsonify({'status': 'success', 'message': f'{user_id} deactivated.'})


    @app.route('/api/admin/next-faculty-id', methods=['GET'])
    @login_required
    def api_next_faculty_id():
        """Return the next auto-suggested faculty ID."""
        if session.get('role') != 'admin':
            return jsonify({'status': 'error', 'message': 'Admin only.'}), 403
        from aas.core.roles import get_next_faculty_id
        return jsonify({'status': 'ok', 'next_id': get_next_faculty_id()})


    # ══════════════════════════════════════════════════════════════════════════
    # Camera Management
    # ══════════════════════════════════════════════════════════════════════════

    @app.route('/api/cameras', methods=['GET'])
    def list_cameras():
        from aas.capture.camera_registry import load_cameras
        cameras = load_cameras()
        return jsonify({'cameras': cameras, 'count': len(cameras)})

    @app.route('/api/cameras', methods=['POST'])
    @login_required
    def add_camera_route():
        try:
            data = request.get_json(force=True)
            from aas.capture.camera_registry import add_camera
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
        from aas.capture.camera_registry import delete_camera
        ok = delete_camera(cam_id)
        return jsonify({'status': 'success' if ok else 'not_found'})

    @app.route('/api/cameras/<cam_id>/status', methods=['GET'])
    def camera_status(cam_id):
        from aas.capture.camera_registry import get_camera
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
        students = _enrolled_students()
        return jsonify({'students': students, 'count': len(students)})

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
        name        = request.form.get('name', '').strip().replace(' ', '_')
        email       = request.form.get('email', '').strip()
        gender      = request.form.get('gender', 'M').strip().upper() or 'M'
        cam_id      = request.form.get('camera_id', '')
        roll_number = request.form.get('roll_number', '').strip()  # B1

        if not name:
            return jsonify({'status': 'error', 'message': 'Student name is required'}), 400

        files = request.files.getlist('photos')
        if not files or all(f.filename == '' for f in files):
            return jsonify({'status': 'error', 'message': 'At least one photo required'}), 400

        # Use camera-specific encodings folder if camera_id given
        enc_folder = ENCODINGS_FOLDER
        if cam_id:
            from aas.capture.camera_registry import get_encodings_path
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
                from aas.capture.camera_registry import get_camera
                from aas.attendance.spreadsheet import SpreadsheetManager
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
        data        = request.get_json(force=True)
        name        = data.get('name', '').strip().replace(' ', '_')
        angle       = data.get('angle', 'front').lower()
        img_b64     = data.get('image', '')
        email       = data.get('email', '').strip()
        gender      = data.get('gender', 'M').upper()
        finalize    = data.get('finalize', False)
        cam_id      = data.get('camera_id', '')
        roll_number = data.get('roll_number', '').strip()  # B1

        if not name:
            return jsonify({'status': 'error', 'message': 'Student name required'}), 400

        enc_folder = ENCODINGS_FOLDER
        if cam_id:
            from aas.capture.camera_registry import get_encodings_path
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
                payload = _safe_load(pkl_path)
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
                        from aas.capture.camera_registry import get_camera
                        from aas.attendance.spreadsheet import SpreadsheetManager
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
            data    = request.get_json(force=True) or {}
            cam_id  = data.get('camera_id', '')
            subject = data.get('subject', '')   # B4
            period  = int(data.get('period', 0))  # B4

            if not recognition.known_face_encodings:
                recognition.load_facial_encodings_and_names_from_memory()

            sheet_synced = True
            sheet_msg    = ''

            # Get the sheet for this camera
            sheet_id = None
            cam_total = 0
            if cam_id:
                from aas.capture.camera_registry import get_camera
                cam = get_camera(cam_id)
                if cam:
                    sheet_id  = cam.get('sheet_id', '')
                    cam_total = 0  # will be calculated from sheet

            # Mark all absent first
            try:
                if sheet_id:
                    from aas.attendance.spreadsheet import SpreadsheetManager
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

            # Write present/late for each recognized student in a single batch
            present_names = result.get('present', [])
            if sheet_id:
                from aas.attendance.spreadsheet import SpreadsheetManager
                mgr = SpreadsheetManager(_get_creds())
                mgr.write_batch_to_sheet(sheet_id, present_names)
            else:
                spreadsheet.write_batch_to_sheet(present_names)

            boys_count  = result.get('boys_count', 0)
            girls_count = result.get('girls_count', 0)
            total_class = cam_total or len(result.get('present', [])) + result.get('unknown_count', 0)

            # TTS announcement (non-blocking)
            try:
                from aas.notifications.tts import announce_attendance
                announce_attendance(boys=boys_count, girls=girls_count, total=total_class)
            except Exception as e:
                print(f"  [TTS] Announcement skipped: {e}")

            return jsonify({
                'status':          'success',
                'camera_id':       cam_id,
                'present':         result['present'],
                'absent_students': [{'name': n} for n in result.get('absent', [])],  # B4
                'boys_count':      boys_count,
                'girls_count':     girls_count,
                'unknown_count':   result['unknown_count'],
                'total_faces':     result['total_faces'],
                'total_class':     total_class,
                'subject':         subject,
                'period':          period,
                'timestamp':       datetime.datetime.now().strftime('%I:%M %p, %d %b %Y'),
                'annotated_img':   annotated_url,
                'sheet_synced':    sheet_synced,
                'sheet_msg':       sheet_msg,
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
                from aas.capture.camera_registry import get_camera
                cam = get_camera(cam_id)
                if cam:
                    sheet_id = cam.get('sheet_id', '')
            try:
                if sheet_id:
                    from aas.attendance.spreadsheet import SpreadsheetManager
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

            present_names = result.get('present', [])
            if sheet_id:
                from aas.attendance.spreadsheet import SpreadsheetManager
                mgr = SpreadsheetManager(_get_creds())
                mgr.write_batch_to_sheet(sheet_id, present_names)
            else:
                spreadsheet.write_batch_to_sheet(present_names)

            boys_count  = result.get('boys_count', 0)
            girls_count = result.get('girls_count', 0)
            try:
                from aas.notifications.tts import announce_attendance
                total_class = cam_total or (boys_count + girls_count + result.get('unknown_count', 0))
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
                from aas.capture.camera_registry import get_camera
                cam = get_camera(cam_id)
                if cam:
                    sheet_id = cam.get('sheet_id', '')
            if sheet_id:
                from aas.attendance.spreadsheet import SpreadsheetManager
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
    @login_required
    def camera_stream():
        cam_id = request.args.get('camera_id', '')
        def generate():
            src = capture.get_camera_source(camera_id=cam_id)
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                # Yield a single error frame so the browser shows a message
                error_img = np.zeros((240, 320, 3), dtype=np.uint8)
                cv2.putText(error_img, "Camera Unavailable", (30, 130),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                _, buf = cv2.imencode('.jpg', error_img)
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                       + buf.tobytes() + b'\r\n')
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
            'tolerance':       RECOGNITION_TOLERANCE,
            'scale':           RECOGNITION_SCALE,
            'auto_scale':      AUTO_SCALE_DETECTION,
            'min_face_size':   MIN_FACE_SIZE,
            'min_ipd_pixels':  MIN_IPD_PIXELS,
            'blur_threshold':  BLUR_THRESHOLD,
            'max_in_time':     MAX_IN_TIME,
            'camera_url':      IP_CAMERA_URL,
            'webcam_index':    WEBCAM_INDEX,
            'voice_phrase':    VOICE_TRIGGER_PHRASE,
        })

    @app.route('/api/settings', methods=['POST'])
    @login_required
    def save_settings():
        from aas.core.config import ROOT_DIR
        env_path = os.path.join(ROOT_DIR, '.env')
        data = request.get_json(force=True) or {}
        key_map = {
            'tolerance':      'RECOGNITION_TOLERANCE',
            'scale':          'RECOGNITION_SCALE',
            'auto_scale':     'AUTO_SCALE_DETECTION',
            'min_face_size':  'MIN_FACE_SIZE',
            'min_ipd_pixels': 'MIN_IPD_PIXELS',
            'blur_threshold': 'BLUR_THRESHOLD',
            'max_in_time':    'MAX_IN_TIME',
            'camera_url':     'IP_CAMERA_URL',
            'webcam_index':   'WEBCAM_INDEX',
            'voice_phrase':   'VOICE_TRIGGER_PHRASE',
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

    # ── E1: Camera Lock ────────────────────────────────────────────────────
    _camera_locks: dict = {}  # cam_id → faculty_email

    @app.route('/api/camera/<cam_id>/lock-status', methods=['GET'])
    @login_required
    def camera_lock_status(cam_id):
        busy = cam_id in _camera_locks
        return jsonify({'busy': busy, 'held_by': _camera_locks.get(cam_id)})

    # ── B5: Attendance Finalize ────────────────────────────────────────────
    @app.route('/api/attendance/finalize', methods=['POST'])
    @login_required
    def finalize_attendance():
        """B5: Faculty confirm & submit — writes to weekly Google Sheet."""
        try:
            data    = request.get_json(force=True) or {}
            cam_id  = data.get('camera_id', '')
            subject = data.get('subject', '')
            period  = int(data.get('period', 0))
            _camera_locks.pop(cam_id, None)  # release lock E1

            creds = _get_creds()
            if not creds:
                return jsonify({'ok': True, 'note': 'No Google creds — sheet not written'})

            from aas.capture.camera_registry import get_camera, load_cameras, save_cameras
            from aas.attendance.spreadsheet import (
                create_weekly_sheet, write_attendance_event, _get_gspread_client
            )
            import datetime as _dt

            cam            = get_camera(cam_id) if cam_id else {}
            spreadsheet_id = (cam or {}).get('sheet_id', '')
            if not spreadsheet_id:
                return jsonify({'ok': True, 'note': 'No sheet_id for camera'})

            gc         = _get_gspread_client(creds)
            now        = _dt.datetime.now()
            week_num   = now.isocalendar()[1]
            year_2     = now.strftime('%y')
            week_key   = f"sheet_week_{year_2}_{week_num:02d}"
            week_label = f"Week {week_num} {now.year}"
            section    = (cam or {}).get('sheet_name', 'Section')

            students_raw = (cam or {}).get('enrolled_students', [])
            students = [
                {'name': s.get('name', s) if isinstance(s, dict) else s,
                 'roll_number': s.get('roll_number', '') if isinstance(s, dict) else ''}
                for s in students_raw
            ]

            if cam and week_key not in cam:
                create_weekly_sheet(gc, spreadsheet_id, section, week_label, students)
                cam[week_key] = week_label
                all_cameras = load_cameras()
                for i, c in enumerate(all_cameras):
                    if c.get('id') == cam_id:
                        all_cameras[i] = cam
                        break
                save_cameras(all_cameras)

            tab_name     = (cam or {}).get(week_key, week_label)
            student_rows = [
                {'name': s['name'], 'roll_number': s.get('roll_number', ''), 'row_index': 9 + i}
                for i, s in enumerate(students)
            ]
            present_names = set(session.get('last_present', []))
            day_of_week   = min(now.weekday(), 5)

            write_attendance_event(
                gc, spreadsheet_id, tab_name,
                student_rows, present_names, day_of_week, period
            )

            try:
                from aas.notifications.emailing import send_faculty_summary
                import threading
                threading.Thread(
                    target=send_faculty_summary,
                    args=(session.get('user_email', ''), section,
                          len(present_names), len(students)),
                    daemon=True
                ).start()
            except Exception:
                pass

            return jsonify({'ok': True})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'ok': False, 'error': str(e)}), 500

    # ── C1: Setup Finalize ─────────────────────────────────────────────────
    @app.route('/setup/finalize', methods=['POST'])
    def setup_finalize():
        """C1: Create first admin user and mark setup complete (C3)."""
        if _is_setup_complete():
            return jsonify({'error': 'Already configured'}), 409
        try:
            data           = request.get_json(force=True) or {}
            admin_email    = (data.get('admin_email') or '').strip()
            admin_password = (data.get('admin_password') or '').strip()
            if not admin_email or not admin_password:
                return jsonify({'error': 'Email and password required'}), 400
            if len(admin_password) < 8:
                return jsonify({'error': 'Password must be at least 8 characters'}), 400
            from aas.core.auth import create_user
            create_user(email=admin_email, password=admin_password,
                        role='admin', must_change_password=False)
            inst = _load_institution()
            inst['setup_complete'] = True
            _save_institution(inst)
            return jsonify({'ok': True, 'redirect': '/login'})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    # ── D1: Section Summary ────────────────────────────────────────────────
    @app.route('/api/reports/<cam_id>/summary', methods=['GET'])
    @login_required
    def get_attendance_summary(cam_id):
        try:
            from aas.capture.camera_registry import get_camera
            from aas.attendance.spreadsheet import get_section_summary, _get_gspread_client
            cam = get_camera(cam_id)
            if not cam:
                return jsonify({'error': 'Camera not found'}), 404
            creds = _get_creds()
            if not creds:
                return jsonify({'error': 'No Google credentials'}), 503
            gc        = _get_gspread_client(creds)
            threshold = float(request.args.get('threshold', 0.75))
            summary   = get_section_summary(gc, cam.get('sheet_id', ''), threshold)
            return jsonify({'ok': True, 'data': summary, 'count': len(summary)})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    # ── D2: Student Report ─────────────────────────────────────────────────
    @app.route('/api/reports/<cam_id>/student/<student_name>', methods=['GET'])
    @login_required
    def get_student_report(cam_id, student_name):
        try:
            from aas.capture.camera_registry import get_camera
            from aas.attendance.spreadsheet import get_student_summary, _get_gspread_client
            cam = get_camera(cam_id)
            if not cam:
                return jsonify({'error': 'Camera not found'}), 404
            creds = _get_creds()
            if not creds:
                return jsonify({'error': 'No Google credentials'}), 503
            gc        = _get_gspread_client(creds)
            threshold = float(request.args.get('threshold', 0.75))
            data      = get_student_summary(gc, cam.get('sheet_id', ''), student_name, threshold)
            return jsonify({'ok': True, 'data': data})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    # ── D3: Defaulters ────────────────────────────────────────────────────
    @app.route('/api/reports/<cam_id>/defaulters', methods=['GET'])
    @login_required
    def get_defaulters(cam_id):
        try:
            from aas.capture.camera_registry import get_camera
            from aas.attendance.spreadsheet import get_section_summary, _get_gspread_client
            cam = get_camera(cam_id)
            if not cam:
                return jsonify({'error': 'Camera not found'}), 404
            creds = _get_creds()
            if not creds:
                return jsonify({'error': 'No Google credentials'}), 503
            gc        = _get_gspread_client(creds)
            threshold = float(request.args.get('threshold', 0.75))
            summary   = get_section_summary(gc, cam.get('sheet_id', ''), threshold)
            defaulters = [s for s in summary if s['percentage'] < threshold * 100]
            return jsonify({'ok': True, 'data': defaulters, 'count': len(defaulters)})
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    # ── D4: CSV Export ────────────────────────────────────────────────────
    @app.route('/api/reports/<cam_id>/export/csv', methods=['GET'])
    @login_required
    def export_attendance_csv(cam_id):
        try:
            import csv, io
            from flask import Response
            from aas.capture.camera_registry import get_camera
            from aas.attendance.spreadsheet import get_section_summary, _get_gspread_client
            cam = get_camera(cam_id)
            if not cam:
                return jsonify({'error': 'Camera not found'}), 404
            creds = _get_creds()
            if not creds:
                return jsonify({'error': 'No Google credentials'}), 503
            gc      = _get_gspread_client(creds)
            summary = get_section_summary(gc, cam.get('sheet_id', ''))
            output  = io.StringIO()
            writer  = csv.DictWriter(
                output,
                fieldnames=['name','roll_number','attended','total_classes','percentage','eligible'],
                extrasaction='ignore'
            )
            writer.writeheader()
            writer.writerows(summary)
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment;filename={cam_id}_attendance.csv'}
            )
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    # ── D5: PDF Export ────────────────────────────────────────────────────
    @app.route('/api/reports/<cam_id>/export/pdf', methods=['GET'])
    @login_required
    def export_attendance_pdf(cam_id):
        try:
            import io
            from flask import Response
            from aas.capture.camera_registry import get_camera
            from aas.attendance.spreadsheet import get_section_summary, _get_gspread_client
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
                from reportlab.lib import colors
                from reportlab.lib.styles import getSampleStyleSheet
            except ImportError:
                return jsonify({'error': 'reportlab not installed. pip install reportlab'}), 503
            cam = get_camera(cam_id)
            if not cam:
                return jsonify({'error': 'Camera not found'}), 404
            creds = _get_creds()
            if not creds:
                return jsonify({'error': 'No Google credentials'}), 503
            gc      = _get_gspread_client(creds)
            summary = get_section_summary(gc, cam.get('sheet_id', ''))
            buf     = io.BytesIO()
            doc     = SimpleDocTemplate(buf, pagesize=A4)
            styles  = getSampleStyleSheet()
            elems   = [Paragraph(f"Attendance Report — {cam_id}", styles['Title'])]
            tdata   = [['Name','Roll No','Attended','Total','%','Eligible']]
            for s in summary:
                tdata.append([s['name'], s['roll_number'], str(s['attended']),
                               str(s['total_classes']), f"{s['percentage']}%",
                               'Yes' if s['eligible'] else 'No'])
            t = Table(tdata)
            t.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#1e293b')),
                ('TEXTCOLOR', (0,0),(-1,0), colors.white),
                ('FONTNAME',  (0,0),(-1,0), 'Helvetica-Bold'),
                ('GRID',      (0,0),(-1,-1), 0.5, colors.grey),
            ]))
            elems.append(t)
            doc.build(elems)
            return Response(
                buf.getvalue(),
                mimetype='application/pdf',
                headers={'Content-Disposition': f'attachment;filename={cam_id}_attendance.pdf'}
            )
        except Exception as e:
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    # ── v2.5 Blueprint Registration ───────────────────────────────────────────
    try:
        from aas.web.routes.attendance import attendance_v2_bp
        from aas.web.routes.cameras import cameras_v2_bp
        from aas.web.routes.sync_routes import sync_v2_bp, system_v2_bp

        app.register_blueprint(attendance_v2_bp)
        app.register_blueprint(cameras_v2_bp)
        app.register_blueprint(sync_v2_bp)
        app.register_blueprint(system_v2_bp)
        print("  ✓ [v2.5] API blueprints registered (/api/v2/)")
    except Exception as _bp_err:
        print(f"  [WARN] v2.5 blueprint registration failed: {_bp_err}")

    # ── v2.5 Sync Worker — start background outbox processor ─────────────────
    if not app.config.get("TESTING"):
        try:
            from aas.sync.worker import start_sync_worker
            start_sync_worker()
            print("  ✓ [v2.5] Sync worker started.")
        except Exception as _sw_err:
            print(f"  [WARN] Sync worker failed to start: {_sw_err}")

    return app


# ══════════════════════════════════════════════════════════════════════════════
# NOTE: Routes above registered inside create_app() — do not add module-level routes.
# ══════════════════════════════════════════════════════════════════════════════
