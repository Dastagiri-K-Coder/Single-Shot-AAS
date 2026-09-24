#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_drive.py — Full GUI verification for Single Shot AAS.

Run:
    cd "Single Shot AAS"
    python test_drive.py

Open:
    http://localhost:5000/demo          ← menu with all views
    http://localhost:5000/demo/admin    ← admin dashboard (auto-login)
    http://localhost:5000/demo/faculty  ← faculty mobile view (auto-login)
    http://localhost:5000/demo/faculty2 ← faculty idle/no-period state
"""

import os, sys, json, datetime, time, threading, webbrowser

SRC_DIR = os.path.join(os.path.dirname(__file__), 'src')
sys.path.insert(0, SRC_DIR)

from aas.core.config import (
    INSTITUTION_JSON_PATH, CAMERAS_JSON_PATH,
    CAPTURED_FOLDER, PHOTO_FOLDER, ENCODINGS_FOLDER,
)

# ── Demo Data ──────────────────────────────────────────────────────────────
DEMO_SUBJECTS  = ["Maths","PHY","CHE","CSE","ENG","EVS"]
DEMO_TIMETABLE = {d: DEMO_SUBJECTS for d in ["Mon","Tue","Wed","Thu","Fri","Sat"]}

STUDENTS_A = [
    {"name":"Aarav_Patel",    "roll_number":"CSE2025001","gender":"M"},
    {"name":"Ananya_Sharma",  "roll_number":"CSE2025002","gender":"F"},
    {"name":"Rohan_Iyer",     "roll_number":"CSE2025003","gender":"M"},
    {"name":"Sneha_Reddy",    "roll_number":"CSE2025004","gender":"F"},
    {"name":"Vikram_Malhotra","roll_number":"CSE2025005","gender":"M"},
    {"name":"Priya_Nair",     "roll_number":"CSE2025006","gender":"F"},
    {"name":"Karthik_Verma",  "roll_number":"CSE2025007","gender":"M"},
    {"name":"Divya_Menon",    "roll_number":"CSE2025008","gender":"F"},
    {"name":"Arjun_Singh",    "roll_number":"CSE2025009","gender":"M"},
    {"name":"Meera_Krishnan", "roll_number":"CSE2025010","gender":"F"},
]
STUDENTS_B = [
    {"name":"Rahul_Gupta",    "roll_number":"CSE2025011","gender":"M"},
    {"name":"Pooja_Desai",    "roll_number":"CSE2025012","gender":"F"},
    {"name":"Nikhil_Joshi",   "roll_number":"CSE2025013","gender":"M"},
    {"name":"Kavya_Rao",      "roll_number":"CSE2025014","gender":"F"},
    {"name":"Siddharth_Kumar","roll_number":"CSE2025015","gender":"M"},
    {"name":"Ishaan_Mehta",   "roll_number":"CSE2025016","gender":"M"},
    {"name":"Tanvi_Shah",     "roll_number":"CSE2025017","gender":"F"},
    {"name":"Aditya_Pandey",  "roll_number":"CSE2025018","gender":"M"},
    {"name":"Riya_Choudhary", "roll_number":"CSE2025019","gender":"F"},
    {"name":"Harsh_Aggarwal", "roll_number":"CSE2025020","gender":"M"},
]

DEMO_CAMERAS = [
    {"id":"cam_cse_a","display_name":"CSE-A Hall 101","rtsp_url":"demo://cam_cse_a",
     "sheet_name":"CSE-A","section_code":"CSE","year_start":2025,"year_end":2026,"section":"A",
     "sheet_id":"DEMO_SHEET_CSE_A","folder_id":"DEMO_FOLDER_CSE_A",
     "timetable":DEMO_TIMETABLE,"status":"active","enrolled_students":STUDENTS_A,
     "assigned_faculty_email":"faculty@democollege.edu","assigned_faculty_id":2},
    {"id":"cam_cse_b","display_name":"CSE-B Hall 102","rtsp_url":"demo://cam_cse_b",
     "sheet_name":"CSE-B","section_code":"CSE","year_start":2025,"year_end":2026,"section":"B",
     "sheet_id":"DEMO_SHEET_CSE_B","folder_id":"DEMO_FOLDER_CSE_B",
     "timetable":DEMO_TIMETABLE,"status":"active","enrolled_students":STUDENTS_B,
     "assigned_faculty_email":"faculty2@democollege.edu","assigned_faculty_id":3},
    {"id":"cam_cse_c","display_name":"CSE-C Lab 203","rtsp_url":"demo://cam_cse_c",
     "sheet_name":"CSE-C","section_code":"CSE","year_start":2025,"year_end":2026,"section":"C",
     "sheet_id":"DEMO_SHEET_CSE_C","folder_id":"DEMO_FOLDER_CSE_C",
     "timetable":DEMO_TIMETABLE,"status":"idle","enrolled_students":[],
     "assigned_faculty_email":None,"assigned_faculty_id":None},
]

DEMO_PERIODS = {
    "cam_cse_a":{"subject":"Maths","period_num":1,"start_time":"09:00","end_time":"09:50"},
    "cam_cse_b":{"subject":"PHY",  "period_num":2,"start_time":"09:55","end_time":"10:45"},
}

# ── Seed ───────────────────────────────────────────────────────────────────
def seed():
    for f in [CAPTURED_FOLDER, PHOTO_FOLDER, ENCODINGS_FOLDER]:
        os.makedirs(f, exist_ok=True)

    inst = {}
    if os.path.exists(INSTITUTION_JSON_PATH):
        try:
            with open(INSTITUTION_JSON_PATH) as fh: inst = json.load(fh)
        except Exception: pass
    inst.update({
        "institution_name":     inst.get("institution_name") or "Demo Engineering College",
        "drive_root_folder_id": inst.get("drive_root_folder_id") or "DEMO_FOLDER",
        "department":           "Computer Science & Engineering",
        "academic_year":        "2025-2026",
        "setup_complete":       True,
        "updated_at":           datetime.datetime.now().isoformat(),
    })
    with open(INSTITUTION_JSON_PATH,"w") as fh: json.dump(inst, fh, indent=2)
    print("  ✓ institution.json seeded")

    cams = {}
    if os.path.exists(CAMERAS_JSON_PATH):
        try:
            with open(CAMERAS_JSON_PATH) as fh: cams = json.load(fh)
        except Exception: pass
    if not cams.get("cameras"):
        with open(CAMERAS_JSON_PATH,"w") as fh: json.dump({"cameras":DEMO_CAMERAS},fh,indent=2)
        print(f"  ✓ cameras.json seeded ({len(DEMO_CAMERAS)} demo cameras)")
    else:
        print(f"  ✓ cameras.json: using existing ({len(cams['cameras'])} cameras)")

    try:
        from aas.core.auth import init_db, create_user, user_exists
        init_db()
        if not user_exists("admin@democollege.edu"):
            create_user(email="admin@democollege.edu",password="Demo@1234",
                        role="admin",full_name="Demo Admin",must_change_password=False)
        if not user_exists("faculty@democollege.edu"):
            create_user(email="faculty@democollege.edu",password="Demo@1234",
                        role="faculty",full_name="Dr. K. Sharma",must_change_password=False)
        if not user_exists("faculty2@democollege.edu"):
            create_user(email="faculty2@democollege.edu",password="Demo@1234",
                        role="faculty",full_name="Prof. R. Mehta",must_change_password=False)
        print("  ✓ demo users created")
    except Exception as e:
        print(f"  ⚠ User seed: {e}")

# ── Patches ────────────────────────────────────────────────────────────────
def patch(app):
    import aas.integrations.google.oauth as _o
    _o.is_authenticated = lambda: True
    _o.get_credentials  = lambda: None

    try:
        import aas.notifications.tts as _t
        _t.announce_attendance = lambda **kw: None
    except Exception: pass

    try:
        import aas.capture.capture as _c
        demo_img = os.path.join(CAPTURED_FOLDER,"demo.jpg")
        if not os.path.exists(demo_img):
            try:
                import numpy as np, cv2
                img = np.zeros((480,640,3),dtype=np.uint8); img[:]=(20,30,50)
                cv2.putText(img,"DEMO CAPTURE",(100,240),cv2.FONT_HERSHEY_SIMPLEX,2,(80,200,80),3)
                cv2.imwrite(demo_img,img)
            except Exception: open(demo_img,'wb').close()
        _c.capture_single_shot = lambda camera_id='',**kw: demo_img
    except Exception: pass

    try:
        import aas.recognition.engine as _r
        _r.known_face_encodings = [True]
        _r.load_facial_encodings_and_names_from_memory = lambda: None
        _r.run_recognition = lambda p: {
            "present":["Aarav_Patel","Ananya_Sharma","Rohan_Iyer","Sneha_Reddy","Priya_Nair"],
            "absent": ["Vikram_Malhotra","Karthik_Verma"],
            "boys_count":3,"girls_count":2,"unknown_count":0,"total_faces":5,
        }
        _r.annotate_image = lambda *a: None
    except Exception: pass

    try:
        import aas.core.roles as _rl
        _rl.get_current_period       = lambda cam_id: DEMO_PERIODS.get(cam_id,{"subject":"","period_num":0,"start_time":"--:--","end_time":"--:--"})
        _rl.get_faculty_cameras_by_id= lambda uid: [DEMO_CAMERAS[0]] if uid==2 else ([DEMO_CAMERAS[1]] if uid==3 else [DEMO_CAMERAS[0]])
        _rl.get_faculty_cameras      = lambda email: [DEMO_CAMERAS[0]]
    except Exception as e: print(f"  ⚠ roles: {e}")

    try:
        import aas.core.auth as _a
        _orig = _a.validate_session
        _MAP  = {
            "DEMO_ADMIN_TOKEN":   {"user_id":1,"email":"admin@democollege.edu",  "full_name":"Demo Admin",   "role":"admin"},
            "DEMO_FACULTY_TOKEN": {"user_id":2,"email":"faculty@democollege.edu","full_name":"Dr. K. Sharma","role":"faculty"},
            "DEMO_FAC2_TOKEN":    {"user_id":3,"email":"faculty2@democollege.edu","full_name":"Prof. R. Mehta","role":"faculty"},
        }
        _a.validate_session = lambda tok: _MAP.get(tok) or (lambda: (lambda r: r if r else None)(_orig(tok) if callable(_orig) else None))()
    except Exception: pass

    print("  ✓ patches applied")


DEMO_MENU = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>AAS Test Drive</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.wrap{max-width:700px;width:100%}
h1{font-size:2rem;font-weight:800;color:#f1f5f9;margin-bottom:4px}
.sub{color:#64748b;font-size:.85rem;margin-bottom:32px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}
.card{background:rgba(30,41,59,.7);border:1px solid rgba(99,102,241,.2);border-radius:16px;padding:22px;text-decoration:none;display:block;transition:transform .15s,border-color .15s,box-shadow .15s}
.card:hover{transform:translateY(-4px);border-color:rgba(99,102,241,.5);box-shadow:0 12px 40px rgba(99,102,241,.15)}
.icon{font-size:2rem;margin-bottom:10px}
.ctitle{font-size:.95rem;font-weight:700;color:#f1f5f9;margin-bottom:4px}
.cdesc{font-size:.75rem;color:#94a3b8;line-height:1.55}
.badge{display:inline-block;padding:2px 9px;border-radius:99px;font-size:.62rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;margin-top:10px}
.ba{background:rgba(59,130,246,.12);color:#60a5fa;border:1px solid rgba(59,130,246,.25)}
.bf{background:rgba(99,102,241,.12);color:#818cf8;border:1px solid rgba(99,102,241,.25)}
.bg{background:rgba(16,185,129,.12);color:#34d399;border:1px solid rgba(16,185,129,.25)}
.info{background:rgba(99,102,241,.06);border:1px solid rgba(99,102,241,.18);border-radius:12px;padding:16px 20px;font-size:.78rem;color:#94a3b8;line-height:1.8}
code{background:rgba(255,255,255,.07);padding:1px 6px;border-radius:4px;color:#c4b5fd}
.sep{grid-column:1/-1;border-top:1px solid rgba(255,255,255,.06);padding-top:4px}
</style></head><body><div class="wrap">
<h1>🚀 AAS Test Drive</h1>
<p class="sub">All conditions pre-satisfied — click a card to enter that view instantly. No login required.</p>
<div class="grid">
  <a href="/demo/admin" class="card">
    <div class="icon">🖥️</div>
    <div class="ctitle">Admin Dashboard</div>
    <div class="cdesc">Full desktop panel · 3 cameras · 20 students · live stats · enroll · attendance · reports · settings</div>
    <span class="badge ba">Admin Role</span>
  </a>
  <a href="/demo/faculty" class="card">
    <div class="icon">📱</div>
    <div class="ctitle">Faculty View — Active Period</div>
    <div class="cdesc">Mobile phone UI · CSE-A · Maths Period 1 active · Take Attendance CTA · 10 students</div>
    <span class="badge bf">Faculty · Dr. K. Sharma</span>
  </a>
  <a href="/demo/faculty2" class="card">
    <div class="icon">☕</div>
    <div class="ctitle">Faculty View — Break Time</div>
    <div class="cdesc">Faculty with no active period · CSE-B · shows amber "No active period" idle state</div>
    <span class="badge bf">Faculty · Idle State</span>
  </a>
  <a href="/setup" class="card">
    <div class="icon">⚙️</div>
    <div class="ctitle">Setup Wizard</div>
    <div class="cdesc">First-time setup flow · Institution → Sections → Cameras → Complete</div>
    <span class="badge bg">Setup Flow</span>
  </a>
  <div class="sep"></div>
  <a href="/login" class="card">
    <div class="icon">🔐</div>
    <div class="ctitle">Login Page</div>
    <div class="cdesc">Standard login screen · Email + Password form · Google OAuth button</div>
    <span class="badge bg">Auth Screen</span>
  </a>
  <a href="/admin/users" class="card">
    <div class="icon">👥</div>
    <div class="ctitle">User Management</div>
    <div class="cdesc">Admin user list · Create / reset password / deactivate faculty accounts</div>
    <span class="badge ba">Admin Only</span>
  </a>
</div>
<div class="info">
<strong style="color:#c4b5fd">Credentials (if prompted)</strong><br>
Admin &nbsp;&nbsp;: <code>admin@democollege.edu</code> / <code>Demo@1234</code> &nbsp;·&nbsp;
Faculty : <code>faculty@democollege.edu</code> / <code>Demo@1234</code><br>
<strong style="color:#c4b5fd">APIs</strong>: Google Sheets / Drive / Camera capture all patched — no real credentials needed<br>
<strong style="color:#c4b5fd">Take Attendance</strong>: returns 5 demo recognized students with absent list
</div></div></body></html>"""


def inject_routes(app):
    from flask import session, redirect, Response, jsonify

    @app.route('/demo')
    def demo_index():
        return Response(DEMO_MENU, mimetype='text/html')

    @app.route('/demo/admin')
    def demo_admin():
        session.clear()
        session.update({'user_id':1,'user_email':'admin@democollege.edu',
                        'user_name':'Demo Admin','role':'admin','demo_mode':True})
        r = redirect('/dashboard')
        r.set_cookie('aas_session','DEMO_ADMIN_TOKEN',max_age=86400)
        return r

    @app.route('/demo/faculty')
    def demo_faculty():
        session.clear()
        session.update({'user_id':2,'user_email':'faculty@democollege.edu',
                        'user_name':'Dr. K. Sharma','role':'faculty','demo_mode':True})
        r = redirect('/dashboard')
        r.set_cookie('aas_session','DEMO_FACULTY_TOKEN',max_age=86400)
        return r

    @app.route('/demo/faculty2')
    def demo_faculty2():
        session.clear()
        session.update({'user_id':3,'user_email':'faculty2@democollege.edu',
                        'user_name':'Prof. R. Mehta','role':'faculty','demo_mode':True})
        r = redirect('/dashboard')
        r.set_cookie('aas_session','DEMO_FAC2_TOKEN',max_age=86400)
        return r

    print("  ✓ demo routes injected")


def main():
    print("\n" + "═"*58)
    print("  AAS TEST DRIVE — Seeding demo environment...")
    print("═"*58)
    seed()
    print("\n  Creating Flask app...")
    from aas.web.app import create_app
    app = create_app()
    patch(app)
    inject_routes(app)

    PORT = 5000
    print(f"""
{"═"*58}
  ✅  READY

  📋 Menu     → http://localhost:{PORT}/demo
  🖥️  Admin    → http://localhost:{PORT}/demo/admin
  📱 Faculty  → http://localhost:{PORT}/demo/faculty
  ☕ Idle     → http://localhost:{PORT}/demo/faculty2

  Press CTRL+C to stop
{"═"*58}
""")
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(f"http://localhost:{PORT}/demo")),daemon=True).start()
    app.run(host='0.0.0.0',port=PORT,debug=False,use_reloader=False,threaded=True)

if __name__ == '__main__':
    main()
