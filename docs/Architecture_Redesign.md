# Single Shot AAS v2.0 — Finalized Architecture Redesign
## Faculty Handset-Based Attendance System

**Version:** 2.0 — Finalized (Updated Sept 19, 2026)
**Date:** September 17, 2026 | **Last Updated:** September 19, 2026
**Status:** ✅ All Owner Directives Incorporated — Ready for Implementation

---

> [!IMPORTANT]
> This document is the **authoritative architecture specification** for Single Shot AAS v2.0. It incorporates all decisions made during the owner review session. The core goal is a **full shift from hardware-based (fixed IP cameras) to faculty-handset-based capture** — making the system zero-hardware-cost, deployable in any classroom, and fully autonomous.

---

## Finalized Owner Decisions

| Decision Point | Directive | Status |
|---|---|---|
| Camera hardware | Eliminate expensive IP cameras; use faculty's smartphone | ✅ Confirmed |
| Networking | **Hybrid: Campus LAN + Pi Hotspot + Pi Router** — all three tiers active | ✅ Confirmed |
| Protocol | **PWA on Flask** — no internet for local server; LAN is the medium | ✅ Confirmed |
| Admin vs Faculty UI | Same codebase, same URL, role-based layout separation | ✅ Confirmed |
| ML Model | Continue open-source pre-trained (dlib ResNet) — no change | ✅ Confirmed |
| Subject/Period tracking | Implement in Google Sheets columns + Web UI | ✅ Confirmed |
| Fallback Level 1 | Manual toggle — **always present, must be included** | ✅ Confirmed |
| Fallback Level 2 | Individual student retake — **activated when 10+ are missing** | ✅ Confirmed |
| Fallback Level 3 | Bulk manual add — **extension of Level 1, on faculty's desire** | ✅ Confirmed |
| Parent notification | Not needed — removed from scope | ❌ Out of scope |
| Separate mobile app | Not needed — PWA handles it | ❌ Out of scope |
| **Login System** | **ID Number + Password login page; SQLite on Pi; no Google OAuth at gate** | ✅ New |
| **Attendance Sheet Format** | **Follow the Sample Excel structure as the standard — weekly, per-subject, eligibility flag** | ✅ New |

---

## Table of Contents

1. [The Paradigm Shift](#1-the-paradigm-shift)
2. [Networking — Three-Tier Hybrid Model](#2-networking--three-tier-hybrid-model)
3. [Protocol — PWA on Flask (LAN-Only)](#3-protocol--pwa-on-flask-lan-only)
4. [Complete New User Flows](#4-complete-new-user-flows)
5. [Fallback System — Three Levels Defined](#5-fallback-system--three-levels-defined)
6. [Role-Based UI — Admin vs Faculty](#6-role-based-ui--admin-vs-faculty)
7. [Subject and Period Tracking](#7-subject-and-period-tracking)
8. [Data Model Changes](#8-data-model-changes)
9. [Code Change Map — What Changes, What Stays](#9-code-change-map--what-changes-what-stays)
10. [Full System Topology](#10-full-system-topology)
11. [Phased Build Order](#11-phased-build-order)

---

## 1. The Paradigm Shift

### Old Architecture (v1.0 — Hardware Based)

```
Fixed IP Camera (₹4,000–8,000/room)
    │  RTSP stream over LAN
    ▼
Raspberry Pi → captures frame via cv2.VideoCapture("rtsp://...")
    │
    ▼
Recognition → Google Sheets → Student Emails
```

**Problems:**
- Camera costs ₹4,000–8,000 per classroom
- RTSP wiring + mounting + NVR infrastructure
- Fixed position → angle issues, back-row failures
- If camera fails → room unusable until repaired
- No faculty involvement — admin controls everything

---

### New Architecture (v2.0 — Faculty Handset Based)

```
Faculty's Smartphone (₹0 extra cost)
    │  HTTP POST (photo upload) over College LAN / Pi Hotspot / Pi Router
    ▼
Raspberry Pi → receives uploaded photo, saves to data/captured/
    │
    ▼
Recognition (UNCHANGED) → Google Sheets → Student Emails + Teacher Summary
```

**Advantages:**
- ₹0 camera cost — every faculty already has a phone
- No wiring, no mounting, no infrastructure
- Faculty moves to best angle, zooms in, retakes if needed
- If one faculty's phone fails → use another device or tablet
- Faculty is now an active participant in the system
- Modern mid-range phones (₹10,000–15,000) have 48–108MP cameras → **far exceeds** any 8MP IP camera

### Resolution Comparison (Why Phone Wins)

| Device | Resolution | Back-Row Face (10m, 100° FOV) | Cost |
|---|---|---|---|
| Budget IP Camera | 2MP (1080p) | ~70px ❌ | ₹1,500 |
| Standard IP Camera | 5MP | ~108px ✅ | ₹4,000 |
| Recommended IP Camera | 8MP/4K | ~140px ✅ | ₹6,000 |
| **Faculty Smartphone (mid-range)** | **50MP** | **Faculty walks closer → 400px+** ✅✅ | **₹0 extra** |
| Faculty Smartphone (flagship) | 108MP | Faculty frames the shot | ₹0 extra |

> The faculty is not ceiling-mounted. They **walk to the best position**, hold the phone at face level, and take one wide shot. A 50MP photo from 4m away gives every student 300–400px face width — far beyond what any fixed ceiling camera can achieve.

---

## 2. Networking — Three-Tier Hybrid Model

**Owner directive:** *"Yes, we use Hybrid Model to make it flexible (Full Campus LAN — Pi+Hotspot — Pi+Router)"*

All three tiers run simultaneously. Faculty phones connect to whichever tier is available, automatically.

---

### Tier 1 — College Campus LAN (Primary)

```
College LAN Infrastructure (existing)
    │
    ├── Ethernet port → Raspberry Pi 4 (server)
    │
    └── WiFi Access Points (existing college APs)
              │
              └── Faculty phones connect as normal college WiFi users
                  → Open browser → http://192.168.X.Y:5000 (Pi's LAN IP)
```

**Specs:**
- Coverage: Entire campus (every room with college WiFi)
- Speed: 50–300 Mbps WiFi → image upload < 1 second
- Cost: ₹0 — Pi needs one Ethernet cable
- Dependency: College IT must allow Pi on the network
- Faculty device: Any phone/tablet/laptop on college WiFi

**When it works:** Normal operation — every teaching day.

---

### Tier 2 — Pi's Built-in WiFi Hotspot (Secondary / Fallback)

```
Raspberry Pi 4
    │  Built-in 802.11ac WiFi (hostapd)
    └── Broadcasts SSID: "SingleShot-AAS"
              │
              └── Faculty phones manually connect to this SSID
                  → Open browser → http://10.0.0.1:5000 (Pi hotspot IP)
```

**Pi Hotspot Specs:**
```
SSID:             SingleShot-AAS
Password:         (set during setup)
Band:             2.4 GHz + 5 GHz (dual-band)
Max connections:  20–30 simultaneous devices
Indoor range:     30–50 metres (line of sight)
Through walls:    15–25 metres (covers 2–3 adjacent classrooms)
IP assigned:      10.0.0.x via dnsmasq DHCP
Pi's IP:          10.0.0.1 (fixed, always same)
Internet access:  None — LAN only (no external dependency)
```

**When it activates:** College WiFi is down or Pi cannot connect to college LAN.
**Limitation:** Only covers the floor/wing where the Pi is physically placed.

---

### Tier 3 — Pi + External WiFi Router (Tertiary / Expansion)

```
TP-Link / D-Link Router (₹700–1,500)
    │  Ethernet → Raspberry Pi 4
    └── WiFi SSID: "AAS-Network"
              │
              ├── 100–150m outdoor range (covers entire building exterior)
              └── Faculty phones connect to "AAS-Network"
                  → Open browser → http://192.168.1.1:5000
```

**Router Specs (for ₹700 TP-Link WR841N):**
```
Range:           100–150m (open area), 50–80m (through walls)
Building floors: Covers 2–3 floors from ground placement
Max speed:       300 Mbps (more than enough for image uploads)
Cost:            ₹700–1,500
Power:           Plugged into same socket as Pi
```

**When it activates:**
- Institution has no existing WiFi infrastructure
- Pi's built-in hotspot doesn't reach all classrooms (multi-floor buildings)
- Pilot deployment before college IT approves LAN connection

---

### Three-Tier Priority Logic (Auto-Switching)

```
Faculty opens browser on phone:

  Step 1: Try http://<College-LAN-IP>:5000
          Connected to college WiFi? → ✅ Tier 1 — fast, full-campus
          
  Step 2: Try http://10.0.0.1:5000
          Connected to Pi Hotspot? → ✅ Tier 2 — limited range, no internet
          
  Step 3: Try http://192.168.1.1:5000
          Connected to Pi Router network? → ✅ Tier 3 — extended range

  All three can be active simultaneously.
  Faculty connects to whichever network their phone is on.
  Pi Flask server listens on 0.0.0.0:5000 — responds on all interfaces.
```

**Key point:** `Flask` with `WEB_HOST=0.0.0.0` already listens on ALL network interfaces simultaneously. **No code change needed for multi-tier networking.** The Pi just needs all three network adapters configured (Ethernet for Tier 1, built-in WiFi for Tier 2, USB WiFi or external router for Tier 3).

> [!NOTE]
> **Internet access** is only needed for Google Sheets sync and student emails. The attendance capture, recognition, and faculty UI all work **100% on the local network (LAN)**. If internet is down, attendance is still taken and stored locally — sync happens when connectivity restores.

---

## 3. Protocol — PWA on Flask (LAN-Only)

**Owner directive:** *"Yes, Option B. It also avoids need of internet access to connect to local server because LAN is the communication medium."*

### Why PWA Is the Right Choice

| Factor | PWA (Selected) | Native Android APK |
|---|---|---|
| **Development effort** | Zero extra — same Flask codebase | 2–3 months separate development |
| **Distribution** | Share the URL | Upload APK, faculty must install |
| **Updates** | Instant — deploy to Pi → all faculty updated | Manual APK redistribution |
| **Internet required?** | **No — LAN only** | No (if APK is local) |
| **Camera access** | ✅ `getUserMedia()` works in Chrome/Safari | ✅ Native camera API |
| **Home screen install** | ✅ "Add to Home Screen" via manifest.json | ✅ Via Play Store / sideload |
| **Works on all phones** | ✅ Any browser, any OS | Android only unless cross-platform |
| **Offline capability** | ✅ Service worker caches UI | ✅ |

### LAN-Only Communication — No Internet Needed for Attendance

```
Faculty Phone                  Raspberry Pi (Flask)
     │                                │
     │  GET http://192.168.1.10:5000  │  ← Load the UI
     │ ──────────────────────────────▶ │
     │                                │
     │  POST /take-attendance         │  ← Upload photo
     │  (multipart/form-data)         │
     │  payload: photo JPEG bytes     │
     │ ──────────────────────────────▶ │
     │                                │  ← Recognition runs on Pi
     │  200 OK + JSON result          │
     │  {present, absent, boys, girls}│
     │ ◀────────────────────────────── │
     │                                │
     │  (Optional, if internet on)    │
     │                          Google Sheets ← ← Pi syncs sheet
     │                          Student emails ← Pi sends emails
```

The entire **capture → recognition → result display** cycle happens on the local network. Google Sheets sync is a **secondary step** that happens in the background if internet is available.

### PWA Installation on Faculty Phone (One-Time Setup)

```
Faculty opens Chrome on phone → types http://<Pi-IP>:5000

Chrome shows banner: "Add Single Shot AAS to Home Screen"
Faculty taps "Add"

→ App icon appears on phone home screen
→ Tapping opens full-screen (no browser address bar)
→ Looks and feels exactly like a native app
→ Works only on college WiFi / Pi hotspot (intentional — LAN only)
```

**Files needed for PWA:**
```
web/static/manifest.json   → App name, icon, display mode
web/static/sw.js           → Service worker (caches UI for offline loading)
web/static/icon-192.png    → App icon
web/static/icon-512.png    → App icon (large)
```

**Flask route to serve manifest:**
```python
@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory(static_dir, 'manifest.json',
                               mimetype='application/manifest+json')
```

---

## 4. Complete New User Flows

### 4A. Faculty Flow — Taking Attendance

```
STEP 1: Faculty arrives at classroom (any time, any subject)
        ──────────────────────────────────────────────────────
        Phone auto-connects to college WiFi (or Pi hotspot)
        Opens "AAS" app from home screen (or types URL in Chrome)

STEP 2: Login
        ──────────────────────────────────────────────────────
        "Login with Google" → faculty's personal Google account
        System identifies: "This is Dr. Ramesh → CSE-A section"
        Timetable check: "Current time 11:05 AM → Period 3 → DBMS"

STEP 3: Faculty sees their simplified dashboard
        ──────────────────────────────────────────────────────
        ┌─────────────────────────────────┐
        │  👋 Dr. Ramesh                  │
        │  📚 CSE-A  |  DBMS  |  P3      │
        │  🕑 11:00 AM – 12:00 PM        │
        │  👥 60 students enrolled        │
        │  ─────────────────────────────  │
        │                                 │
        │  ┌─────────────────────────┐   │
        │  │   📷 LIVE PREVIEW       │   │
        │  │   (phone rear camera)   │   │
        │  └─────────────────────────┘   │
        │                                 │
        │  ┌─────────────────────────┐   │
        │  │  📸 TAKE ATTENDANCE     │   │
        │  └─────────────────────────┘   │
        │                                 │
        │  Last taken: Mon 9:05 AM        │
        │  55 Present / 5 Absent          │
        └─────────────────────────────────┘

STEP 4: Faculty holds phone toward class, taps "TAKE ATTENDANCE"
        ──────────────────────────────────────────────────────
        Rear camera captures one wide-angle photo
        Photo uploaded to Pi via WiFi HTTP POST
        "Processing... ⏳" spinner shown (5–10 seconds on Pi)

STEP 5: Results displayed on faculty's phone
        ──────────────────────────────────────────────────────
        ┌─────────────────────────────────────────┐
        │  ✅ 55 Present   ❌ 5 Absent   ⏰ 0 Late │
        │  ─────────────────────────────────────── │
        │  ABSENT STUDENTS:                        │
        │  ○ Raju Kumar      [✅ Present] [📷 Retry]│
        │  ○ Priya Sharma    [✅ Present] [📷 Retry]│
        │  ○ Arjun Rao       [✅ Present] [📷 Retry]│
        │  ○ Kavya Reddy     [✅ Present] [📷 Retry]│
        │  ○ Mohan Das       [✅ Present] [📷 Retry]│
        │  ─────────────────────────────────────── │
        │  [➕ Add Student Manually]                │
        │  ─────────────────────────────────────── │
        │  [✔ CONFIRM & SUBMIT]                    │
        └─────────────────────────────────────────┘

STEP 6: Faculty reviews, uses fallback if needed, confirms
        ──────────────────────────────────────────────────────
        See Section 5 for fallback details.

STEP 7: Confirmation
        ──────────────────────────────────────────────────────
        "✅ Attendance submitted for DBMS P3"
        Google Sheet updated (column: "9/17 DBMS P3")
        Student emails dispatched
        🔊 TTS: "Successfully Taken the Attendance, Boys: 30, Girls: 25, Total: 60"
        Faculty's phone shows summary + timestamp
```

---

### 4B. Admin Flow — Setup and Management

```
STEP 1: Admin opens http://<Pi-IP>:5000 on PC/laptop
STEP 2: Login with Admin Google account (designated during setup)
STEP 3: Full admin dashboard with all sections:

        ┌──────────────────────────────────────────────────┐
        │  Single Shot AAS — Admin Dashboard               │
        │  Institution: Govt. Engineering College, Nellore │
        │  ─────────────────────────────────────────────── │
        │  [📊 Overview] [👤 Faculty] [🎓 Enroll Students] │
        │  [📅 Reports]  [⚙️ Settings] [🗂️ Timetable]      │
        │  ─────────────────────────────────────────────── │
        │  TODAY'S ATTENDANCE                              │
        │  ┌─────────────────────────────────────────────┐ │
        │  │ CSE-A   DBMS P3   11:05 AM   55/60 ✅       │ │
        │  │ ECE-B   Maths P2  10:02 AM   48/55 ✅       │ │
        │  │ MECH-C  Physics   09:10 AM   40/45 ✅       │ │
        │  │ CSE-B   OS P4     Not taken  —/60  ⏳       │ │
        │  └─────────────────────────────────────────────┘ │
        │  ─────────────────────────────────────────────── │
        │  [Enroll New Student]  [Add Faculty]             │
        │  [Generate Report]     [Export CSV]              │
        └──────────────────────────────────────────────────┘
```

---

## 5. Fallback System — Three Levels Defined

**Owner directives:**
- *Level 1: Simple and must always be included*
- *Level 2: Best for when more than 10 are missing*
- *Level 3: Bulk manual addition — extension of Level 1, based on faculty desire*

---

### Level 1 — Manual Toggle (Always Present, Required)

**When:** Any time — standard post-recognition review. Faculty knows their students personally.

**How it works:**
```
After recognition result loads, faculty sees the ABSENT list.
Each absent student has a [✅ Mark Present] button.
Faculty taps the button → student flips to PRESENT instantly.
No re-recognition. No camera. Instant.

Use case: "I can see Raju sitting in the back — the camera missed him."
→ Tap [✅ Present] → Raju is marked present.
```

**Backend:**
```
POST /api/attendance/override
Body: { "camera_id": "cam-001", "name": "Raju Kumar", "status": "present" }
Response: { "status": "success", "updated": "Raju Kumar → present" }
```

**UI Rule:** This button is ALWAYS visible next to every absent student. No threshold, no conditions. It is the primary human correction mechanism.

---

### Level 2 — Individual Student Retake (Activated When 10+ Are Missing)

**When:** Recognition returns more than 10 absent students — indicating a systematic issue (bad lighting, angle, obstruction). A re-capture of specific students via individual targeted photos helps.

**How it works:**
```
When absent count > 10, the UI shows an additional prompt:
"⚠️ 15 students undetected. Consider retaking individual photos."

Each absent student has a [📷 Retry Photo] button.
Faculty taps [📷 Retry] for any student.
→ Camera opens focused on one student.
→ Faculty points phone at that specific student's face (close-up).
→ Photo uploaded to targeted recognition route.
→ System runs recognition ONLY comparing that photo against
  that specific student's enrolled encoding (not full database).
→ Match found → student marked present.
→ No match → student stays absent.

Use case: 18 students absent. Teacher takes close-up photos of
each one visible in the room → 15 matched → only 3 genuinely absent.
```

**Backend:**
```
POST /take-attendance-individual
Body: { "camera_id": "cam-001", "target_name": "Raju Kumar" }
Files: photo (close-up of that specific student)
Response: { "matched": true/false, "name": "Raju Kumar", "status": "present/absent" }
```

**UI Rule:** The [📷 Retry] button appears next to each absent student only when `absent_count > 10`. When `absent_count ≤ 10`, only Level 1 (manual toggle) is shown — simpler for small corrections.

**Why this threshold?**
- 1–9 absent: Likely genuine absences or minor misses → Level 1 toggle is enough
- 10+ absent: Something went wrong with the main shot → Level 2 guided retake is justified

---

### Level 3 — Bulk Manual Addition (Extension of Level 1, On Faculty Demand)

**When:** Faculty wants to manually add students who are not even in the absent list (e.g., enrolled late, visiting students, or the system has no encoding for them yet).

**How it works:**
```
Faculty taps [➕ Add Student Manually] button (always visible below absent list).
→ Searchable dropdown of all enrolled students appears.
→ Faculty selects name(s) from the list.
→ Selected students marked PRESENT immediately.
→ Faculty can select multiple students at once.

Use case: "3 transfer students joined this week — they're enrolled in
the sheet but not yet in the face encoding database."
→ Faculty manually adds them → present in sheet.

OR: "Faculty wants to mark 8 students present at once without
     taking individual retake photos."
→ Multi-select from enrolled list → bulk mark present.
```

**Backend:** No new route needed — reuses the same `/api/attendance/override` endpoint in a loop for each selected name.

**UI Rule:** The [➕ Add Student Manually] button is always visible (Level 1 extension). It opens a multi-select searchable list of all enrolled students. This is not a separate system — it's the same "mark present" action but applied to students not shown in the absent list.

---

### Fallback Decision Flow Summary

```
Recognition completes → Result returned
         │
         ▼
Absent count ≤ 9?
    ├── YES → Show Level 1 only:
    │         [✅ Mark Present] next to each absent student
    │         [➕ Add Student Manually] below list (Level 3)
    │
    └── NO (10+ absent) → Show ALL levels:
              [✅ Mark Present] (Level 1)
              [📷 Retry Photo] (Level 2 — also shown)
              [➕ Add Student Manually] (Level 3)
              + Banner: "⚠️ High absence count — check lighting/angle"
         │
         ▼
Faculty makes corrections → Taps [✔ CONFIRM & SUBMIT]
         │
         ▼
Final roster written to Google Sheet
Student emails dispatched
TTS announces result
```

---

## 6. Role-Based UI — Admin vs Faculty (Same Codebase)

**Owner directive:** *"No separate app development. Use same web UI with different layouts/interlinking for faculty vs admin."*

### Implementation Strategy: One Template, One Route, Two Renders

```python
# app.py — modified dashboard route
@app.route('/dashboard')
@login_required
def dashboard():
    if not _is_setup_complete():
        return redirect('/setup')

    from aas.core.roles import get_user_role, get_faculty_cameras
    role = get_user_role(session['user_email'])

    if role == 'faculty':
        cameras = get_faculty_cameras(session['user_email'])
        return render_template('index.html',
                               layout='faculty',
                               cameras=cameras,          # only assigned section(s)
                               user_name=session.get('user_name'),
                               user_email=session.get('user_email'))
    else:
        from aas.capture.camera_registry import load_cameras
        cameras = load_cameras()
        return render_template('index.html',
                               layout='admin',
                               cameras=cameras,          # all sections
                               user_name=session.get('user_name'),
                               user_email=session.get('user_email'))
```

```javascript
// index.html — single template, layout-aware JS
const LAYOUT = "{{ layout }}";  // Jinja2 injects 'admin' or 'faculty'

document.addEventListener('DOMContentLoaded', () => {
    if (LAYOUT === 'faculty') {
        initFacultyView();   // mobile-first, single section, large capture button
    } else {
        initAdminView();     // full dashboard, all sections, management panels
    }
});
```

### Admin Controls (Full Dashboard)

```
/dashboard (admin layout)
├── Section Overview Panel — all sections, today's status
├── Enroll Student — 3-angle webcam or photo upload
├── Faculty Management — assign faculty to sections
├── Timetable Configuration — set period times and subjects
├── Reports Panel — cumulative %, defaulter list, export
├── Settings — recognition tolerance, max_in_time, etc.
├── Camera Registry — manage section-camera mappings
└── All attendance history per section
```

### Faculty Controls (Simplified Mobile View)

```
/dashboard (faculty layout)
├── My Section Card — section name, subject, period, time
├── Live Camera Preview — full-width phone camera feed
├── Take Attendance Button — large, tap-friendly
├── Post-Recognition Results — present/absent split
│   ├── Level 1: [✅ Mark Present] per absent student
│   ├── Level 2: [📷 Retry Photo] when 10+ absent
│   └── Level 3: [➕ Add Student Manually]
├── [✔ Confirm & Submit]
└── View My Section's Today Report (read-only)

NOT VISIBLE TO FACULTY:
├── Enrollment
├── Other sections' data
├── System settings
├── Camera management
└── Other faculty's sections
```

### New File: `aas/core/roles.py`

```python
# roles.py — Role resolution and faculty-camera mapping
import json
import os
from aas.core.config import CONFIG_DIR

FACULTY_REGISTRY_PATH = os.path.join(CONFIG_DIR, 'faculty_registry.json')
ADMIN_EMAILS_PATH = os.path.join(CONFIG_DIR, 'institution.json')


def get_user_role(email: str) -> str:
    """Return 'admin' or 'faculty' for the given Google account email."""
    try:
        with open(ADMIN_EMAILS_PATH) as f:
            inst = json.load(f)
        admin_email = inst.get('contact_email', '')
        admin_emails = inst.get('admin_emails', [admin_email])
        if email in admin_emails:
            return 'admin'
    except Exception:
        pass
    return 'faculty'


def get_faculty_cameras(email: str) -> list[dict]:
    """Return list of camera dicts assigned to this faculty member."""
    from aas.capture.camera_registry import load_cameras
    all_cameras = load_cameras()
    return [c for c in all_cameras
            if c.get('assigned_faculty_email', '').lower() == email.lower()]
```

---

## 7. Subject and Period Tracking

**Owner directive:** *"Yes, we need to implement these in data sheets and Web UI."*

### Google Sheet Column Format (New)

```
Current columns:
| Name | Email | Gender | PIN | 9/17/2026 | 9/18/2026 |

New columns:
| Name | Email | Gender | PIN | 9/17 DBMS P3 | 9/17 Maths P5 | 9/18 OS P2 | 9/18 Physics P1 |
```

Each attendance event creates a **unique column** per subject+period combination. Multiple subjects in the same day get separate columns — no overwriting.

### Column Naming Function

```python
# spreadsheet.py — modified
def _today_period_string(subject: str = '', period: int = 0) -> str:
    """
    Generate a column header for today's attendance.
    
    Examples:
        subject='DBMS', period=3  → '9/17 DBMS P3'
        subject='',     period=0  → '9/17/2026'  (backward compatible)
    """
    now = datetime.date.today()
    if subject and period:
        return f"{now.month}/{now.day} {subject} P{period}"
    return f"{now.month}/{now.day}/{now.year}"  # legacy format
```

### Timetable Configuration (`config/timetable.json`)

```json
{
  "cam-001": {
    "section_display": "CSE-A",
    "schedule": [
      {
        "period": 1,
        "start_time": "09:00",
        "end_time":   "10:00",
        "subject":    "Mathematics",
        "faculty_email": "maths.prof@college.edu",
        "faculty_name":  "Dr. Lakshmi"
      },
      {
        "period": 2,
        "start_time": "10:00",
        "end_time":   "11:00",
        "subject":    "Physics",
        "faculty_email": "physics.prof@college.edu",
        "faculty_name":  "Dr. Suresh"
      },
      {
        "period": 3,
        "start_time": "11:00",
        "end_time":   "12:00",
        "subject":    "DBMS",
        "faculty_email": "dbms.prof@college.edu",
        "faculty_name":  "Dr. Ramesh"
      },
      {
        "period": 4,
        "start_time": "13:00",
        "end_time":   "14:00",
        "subject":    "Operating Systems",
        "faculty_email": "os.prof@college.edu",
        "faculty_name":  "Dr. Kavitha"
      }
    ]
  }
}
```

### Auto-Period Detection Logic

```python
# roles.py — added helper
def get_current_period(camera_id: str) -> dict | None:
    """
    Return the current period details based on system time.
    Returns None if no period is currently active.
    """
    import datetime
    from aas.core.config import CONFIG_DIR

    timetable_path = os.path.join(CONFIG_DIR, 'timetable.json')
    try:
        with open(timetable_path) as f:
            timetable = json.load(f)
        schedule = timetable.get(camera_id, {}).get('schedule', [])
        now = datetime.datetime.now().strftime('%H:%M')
        for period in schedule:
            if period['start_time'] <= now <= period['end_time']:
                return period  # → {'period': 3, 'subject': 'DBMS', ...}
    except Exception:
        pass
    return None
```

When faculty opens the dashboard:
1. System calls `get_current_period(cam_id)`
2. If a period is active → shows "DBMS | Period 3 | 11:00–12:00" pre-filled
3. Faculty taps "Take Attendance" → column named `"9/17 DBMS P3"` automatically
4. If between periods (lunch, break) → faculty is prompted to select subject manually from a dropdown

### Timetable Admin UI (Admin Panel)

Admin can create/edit the timetable from the dashboard:

```
Admin Dashboard → Timetable
  Section: CSE-A
  ┌─────────────────────────────────────────────────┐
  │ P1  09:00–10:00  Mathematics  Dr. Lakshmi       │
  │ P2  10:00–11:00  Physics      Dr. Suresh         │
  │ P3  11:00–12:00  DBMS         Dr. Ramesh         │
  │ P4  13:00–14:00  OS           Dr. Kavitha        │
  │ [+ Add Period]                                   │
  └─────────────────────────────────────────────────┘
  [Save Timetable]
```

---

## 8. Data Model Changes

### cameras.json — New Fields Added

```jsonc
{
  "cameras": [
    {
      // Existing fields (unchanged):
      "id": "cam-001",
      "display_name": "CSE A Section",
      "rtsp_url": "",              // Now optional — empty when phone is used
      "sheet_id": "1abc...",
      "sheet_name": "Single Shot AAS -1 CSE Y(2024-2027) S(A)",
      "drive_folder_id": "xyz...",
      "encodings_subfolder": "cam-001",
      "section_code": "CSE",
      "year_start": 2024,
      "year_end": 2027,
      "section": "A",
      "serial": 1,

      // NEW FIELDS:
      "capture_mode": "mobile_upload",    // "rtsp" | "webcam" | "mobile_upload"
      "assigned_faculty_email": "dbms.prof@college.edu",
      "faculty_name": "Dr. Ramesh"
    }
  ]
}
```

### faculty_registry.json (New File)

```json
{
  "admins": [
    "principal@college.edu",
    "hod.cse@college.edu"
  ],
  "faculty": [
    {
      "email": "dbms.prof@college.edu",
      "name": "Dr. Ramesh",
      "assigned_cameras": ["cam-001"]
    },
    {
      "email": "maths.prof@college.edu",
      "name": "Dr. Lakshmi",
      "assigned_cameras": ["cam-001", "cam-002"]
    }
  ]
}
```

### institution.json — Admin Email Extension

```json
{
  "institution_name": "Govt. Engineering College",
  "city": "Nellore",
  "state": "Andhra Pradesh",
  "contact_email": "principal@college.edu",
  "admin_emails": ["principal@college.edu", "hod.cse@college.edu"],
  "drive_root_folder_id": "...",
  "next_serial": 3,
  "created_at": "2026-09-17T00:00:00"
}
```

---

## 9. Code Change Map — What Changes, What Stays

### ✅ ABSOLUTELY UNCHANGED — Do Not Touch

| Module | Lines of Code | Why Safe |
|---|---|---|
| `recognition/engine.py` | ~300 | Complete CV pipeline — production-grade |
| `recognition/detectors.py` | ~150 | YuNet + dlib — no change |
| `recognition/metrics.py` | ~80 | Sharpness, IPD, adaptive scale |
| `attendance/spreadsheet.py` | ~411 | Google Sheets batch write — only extend `_today_string()` |
| `integrations/google/drive_manager.py` | ~200 | Drive folder creation |
| `notifications/tts.py` | ~153 | TTS announcement |
| `core/safe_pickle.py` | ~60 | Security — critical |
| `core/retry.py` | ~30 | API retry |
| All 103 tests | — | Run before every change |

### 🔄 MODIFIED (Extend, Not Rewrite)

| Module | Change | Risk |
|---|---|---|
| `capture/capture.py` | Add `capture_from_upload(file_bytes)` as Mode D | Low — additive |
| `capture/camera_registry.py` | Add `capture_mode`, `assigned_faculty_email` fields to schema | Low — additive |
| `web/app.py` | Add role detection, override route, individual retake route, timetable route | Medium — surgical additions |
| `web/templates/index.html` | Add layout flag + faculty vs admin render blocks | Medium — UI only |
| `attendance/spreadsheet.py` | Add `_today_period_string()` alongside existing `_today_string()` | Low — backward compatible |
| `notifications/emailing.py` | Add `send_faculty_summary(faculty_email, section, present, absent_names)` | Low — additive |
| `config/institution.json` | Add `admin_emails` array | Low — additive |

### 🆕 NEW FILES (Additions Only)

| File | Purpose | Effort |
|---|---|---|
| `aas/core/roles.py` | Role resolution, faculty-camera mapping, period detection | Medium |
| `config/timetable.json` | Per-section period schedule | Low (data file) |
| `config/faculty_registry.json` | Faculty email → camera assignments | Low (data file) |
| `web/static/manifest.json` | PWA manifest | Low |
| `web/static/sw.js` | Service worker (offline UI caching) | Low |
| `web/static/icon-192.png` | PWA app icon | Low (asset) |
| `web/static/icon-512.png` | PWA app icon | Low (asset) |

### New API Routes Required

```
POST /api/attendance/override
     Body: {camera_id, name, status}
     Action: Mark specific student present/absent
     Returns: {status, updated_name, new_status}

POST /take-attendance-individual
     Body: {camera_id, target_name} + photo file
     Action: Run recognition on one photo vs one enrolled student
     Returns: {matched, name, status}

GET  /api/timetable/<camera_id>
     Action: Return current and upcoming periods for a section
     Returns: {current_period, schedule}

POST /api/timetable/<camera_id>
     Action: Admin saves/updates timetable for a section
     Body: {schedule: [...periods]}

GET  /api/faculty/cameras
     Action: Return cameras assigned to logged-in faculty
     Returns: {cameras: [...]}

POST /api/setup/assign-faculty
     Action: Admin assigns faculty email to a camera
     Body: {camera_id, faculty_email, faculty_name}
```

---

## 10. Full System Topology

```
╔═════════════════════════════════════════════════════════════════════════════╗
║                  SINGLE SHOT AAS v2.0 — FULL SYSTEM TOPOLOGY               ║
╚═════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│                        NETWORK LAYER (THREE-TIER HYBRID)                    │
│                                                                             │
│  Tier 1: College Campus LAN                                                 │
│  ─────────────────────────                                                  │
│  Faculty Phone ──WiFi──▶ College AP ──LAN──▶ Pi (Gigabit Ethernet)         │
│  Coverage: Full campus | Cost: ₹0 | Primary mode                           │
│                                                                             │
│  Tier 2: Pi Built-in Hotspot (SSID: SingleShot-AAS)                       │
│  ──────────────────────────────────────────────────                         │
│  Faculty Phone ──WiFi──▶ Pi's own access point (10.0.0.1:5000)             │
│  Coverage: 30–50m, 1 floor | Cost: ₹0 | Fallback                          │
│                                                                             │
│  Tier 3: Pi + External Router (SSID: AAS-Network)                          │
│  ─────────────────────────────────────────────────                          │
│  Faculty Phone ──WiFi──▶ Router ──Ethernet──▶ Pi (192.168.1.1:5000)        │
│  Coverage: 100–150m, 2–3 floors | Cost: ₹700 | Expansion                  │
│                                                                             │
│  Flask listens on 0.0.0.0:5000 → responds on ALL interfaces simultaneously │
└─────────────────────────────────────────────────────────────────────────────┘
                    │ HTTP (LAN only — no internet needed for this step)
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│               CLIENT LAYER (PWA — Same URL, Role-Based Layout)              │
│                                                                             │
│  ADMIN (PC/Laptop)                    FACULTY (Smartphone)                  │
│  ─────────────────                    ───────────────────                   │
│  Full Dashboard                       Simplified Mobile View                │
│  ├── All sections overview            ├── My section only                   │
│  ├── Student enrollment               ├── Live camera preview               │
│  ├── Faculty assignment               ├── Large "Take Attendance" button    │
│  ├── Timetable editor                 ├── Post-result: Present/Absent list  │
│  ├── Reports + Export                 │   ├── Level 1: Manual toggle        │
│  └── System settings                  │   ├── Level 2: Retake (if 10+)     │
│                                        │   └── Level 3: Add manually        │
│                                        └── My section's today report        │
└─────────────────────────────────────────────────────────────────────────────┘
                    │ POST /take-attendance OR /upload-photo (existing route)
                    │ Payload: JPEG from phone camera (50MP → resized by Pi)
                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RASPBERRY PI 4 — FLASK SERVER                            │
│                                                                             │
│  Role Engine (NEW)                                                          │
│  ├── get_user_role(email) → 'admin' | 'faculty'                             │
│  ├── get_faculty_cameras(email) → assigned sections                         │
│  └── get_current_period(cam_id) → {subject, period, times}                  │
│                                                                             │
│  Capture Module (EXTENDED — Mode D added)                                   │
│  ├── Mode A: RTSP IP Camera (legacy optional)                               │
│  ├── Mode B: USB Webcam (testing)                                           │
│  └── Mode D: Mobile Upload ← NEW PRIMARY (faculty phone photo)             │
│              capture_from_upload(file_bytes) → saved JPEG                   │
│                                                                             │
│  Recognition Pipeline (COMPLETELY UNCHANGED)                                │
│  ├── Quality Gate (sharpness ≥ 40, brightness ≥ 40, width ≥ 1280)          │
│  ├── Adaptive Resolution Scaling (4K→0.5, 2K→0.75, 1080p→1.0)             │
│  ├── Multi-Scale Detection (YuNet FPN primary, dlib HOG fallback)           │
│  ├── IEC 62676-4 Gate: face ≥ 80×80px                                      │
│  ├── ISO/IEC 19794-5 Gate: IPD ≥ 30px                                      │
│  └── ResNet 128-D Embedding → L2 Distance → Match (threshold 0.55)         │
│                                                                             │
│  Fallback Engine (NEW)                                                      │
│  ├── Level 1: /api/attendance/override → manual toggle                      │
│  ├── Level 2: /take-attendance-individual → single student retake           │
│  └── Level 3: Bulk override via repeated Level 1 calls                      │
│                                                                             │
│  Notifications (EXTENDED)                                                   │
│  ├── TTS: pyttsx3 classroom announcement (unchanged)                        │
│  ├── Student emails: existing emailing.py (unchanged)                       │
│  └── Faculty summary email (NEW): present count + absent names list         │
└─────────────────────────────────────────────────────────────────────────────┘
        │ HTTPS (only this step needs internet)
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    GOOGLE CLOUD (FREE TIER — EXTENDED)                      │
│                                                                             │
│  Google Sheets (Extended column format)                                     │
│  | Name | Email | Gender | PIN | 9/17 DBMS P3 | 9/17 Maths P5 | ...       │
│  Each subject-period gets its own column                                    │
│  Multiple periods per day → multiple columns (no overwriting)               │
│                                                                             │
│  Google Drive (Unchanged)                                                   │
│  └── Enrolled face photos backup, institution config                        │
│                                                                             │
│  Gmail SMTP (Extended)                                                      │
│  ├── Student emails: "Your attendance for DBMS P3: PRESENT" (existing)     │
│  └── Faculty email (NEW): "CSE-A DBMS P3: 55 present, 5 absent: [names]"  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Phased Build Order

### Phase 1 — Core Faculty Mobile Flow (5–7 days)
*Goal: Faculty can take attendance from their phone. Hardware cameras optional.*

| Task | File | Effort |
|---|---|---|
| Add `capture_mode` + `assigned_faculty_email` to camera schema | `camera_registry.py` | 1 hr |
| Create `config/faculty_registry.json` + `timetable.json` | New files | 1 hr |
| Create `aas/core/roles.py` | New file | 3 hrs |
| Modify dashboard route for role detection | `app.py` | 2 hrs |
| Add `/api/faculty/cameras` route | `app.py` | 1 hr |
| Add `/api/timetable/<cam_id>` GET/POST routes | `app.py` | 2 hrs |
| Build faculty mobile layout in `index.html` | `index.html` | 4 hrs |
| Mobile-first CSS (large buttons, responsive layout) | `style.css` | 3 hrs |
| Add PWA manifest + icons | `manifest.json`, icons | 1 hr |
| Faculty assignment UI in admin panel | `index.html` (admin) | 3 hrs |
| Faculty summary email after attendance | `emailing.py`, `app.py` | 2 hrs |
| **Deliverable: Faculty uses phone → takes attendance → sees results** | | **~20 hrs** |

---

### Phase 2 — Fallback System + Subject Tracking (3–4 days)
*Goal: Zero false absences. Subject/period columns in sheets.*

| Task | File | Effort |
|---|---|---|
| `POST /api/attendance/override` (Level 1) | `app.py` | 2 hrs |
| Level 1 UI: [✅ Mark Present] buttons on absent list | `index.html` | 2 hrs |
| `capture_from_upload()` as standalone function (Mode D) | `capture.py` | 1 hr |
| `POST /take-attendance-individual` (Level 2) | `app.py` | 3 hrs |
| Level 2 UI: [📷 Retry Photo] shown when absent_count > 10 | `index.html` | 2 hrs |
| Level 3 UI: [➕ Add Manually] searchable dropdown | `index.html` | 2 hrs |
| `_today_period_string()` function | `spreadsheet.py` | 1 hr |
| Pass subject+period through take-attendance flow | `app.py` | 1 hr |
| Timetable admin UI in admin dashboard | `index.html` | 3 hrs |
| Auto-period detection on faculty dashboard load | `roles.py`, `app.py` | 2 hrs |
| **Deliverable: Reliable attendance with human fallback + per-subject columns** | | **~19 hrs** |

---

### Phase 3 — Reporting + PWA Polish (3–4 days)
*Goal: Complete, production-grade system with analytics.*

| Task | File | Effort |
|---|---|---|
| Cumulative attendance % per student (API) | `app.py`, `spreadsheet.py` | 3 hrs |
| Cumulative % display in admin dashboard | `index.html` | 2 hrs |
| Defaulter list (below 75% threshold) | `app.py` | 2 hrs |
| PDF/CSV export of attendance report | `app.py` | 3 hrs |
| Service worker `sw.js` (PWA offline UI) | `sw.js` | 2 hrs |
| Multi-user simultaneous login (per-user token storage) | `oauth.py` | 4 hrs |
| Timetable import from CSV (bulk setup for admin) | `app.py` | 2 hrs |
| **Deliverable: Full analytics, offline PWA, multi-faculty simultaneous use** | | **~18 hrs** |

---

## Summary

**What changes fundamentally:**
- No more fixed hardware cameras required (RTSP optional, not mandatory)
- Faculty's smartphone is the primary capture device, accessed via browser PWA
- Three-tier network (LAN + Pi Hotspot + Router) ensures connectivity everywhere
- Role-based UI: same web app, two completely different visual experiences
- Three-level fallback ensures no student is wrongly marked absent
- Subject/period tracking: each class period gets its own column in the sheet

**What doesn't change at all:**
- The entire face recognition pipeline (engine, detectors, metrics)
- Google Sheets integration and batch write logic
- Student email notifications
- Voice trigger and TTS announcement
- OAuth security and safe pickle deserialization
- All 103 automated tests

**Total estimated build time:** ~57 hours (~8 focused working days)
**Phased delivery:** Phase 1 alone (20 hrs) makes the system fully usable from faculty phones.

---

*Architecture finalized. Approved for implementation.*
*Start with Phase 1: `aas/core/roles.py` → `app.py` role routing → faculty mobile UI.*

---

## 12. Local Login System — ID & Password Authentication

### 12.1 Why Local Login (Not Google OAuth at the Gate)

The current system relies on Google OAuth for login. This has two problems:
- It requires internet access to reach Google's auth servers — defeating the LAN-only goal
- Faculty without a personal Google account linked to the institution cannot log in

v2.0 introduces a **local ID + Password login page** as the primary authentication gate. Credentials are stored in an SQLite database on the Raspberry Pi. Google OAuth is **retained only** for Google Sheets API access (writing attendance records) — not for the login UI itself.

```
Faculty/Admin opens http://<Pi-IP>:5000

  ┌──────────────────────────────────────┐
  │      Single Shot AAS                 │
  │      Attendance System               │
  │                                      │
  │  Employee / Faculty ID               │
  │  ┌────────────────────────────────┐  │
  │  │  e.g.  FAC-2025-007           │  │
  │  └────────────────────────────────┘  │
  │                                      │
  │  Password                            │
  │  ┌────────────────────────────────┐  │
  │  │  ••••••••                     │  │
  │  └────────────────────────────────┘  │
  │                                      │
  │  [ 🔐  LOGIN ]                       │
  │                                      │
  │  ─────────────────────────────────   │
  │  Forgot Password? → Contact Admin    │
  └──────────────────────────────────────┘
```

**No Google Sign-In button on this page.** Google OAuth is handled silently in the background for Sheets sync only, using the admin-level service account token stored securely on the Pi.

---

### 12.2 SQLite Database Schema on the Pi

Database file: `config/aas_users.db`

```sql
-- ─── users table ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT    UNIQUE NOT NULL,   -- "ADM-001" / "FAC-2025-007"
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL,          -- 'admin' or 'faculty'
    password_hash TEXT    NOT NULL,          -- bcrypt hash (salt embedded)
    email         TEXT,                      -- Optional, for Sheets write-back
    assigned_cameras TEXT DEFAULT '[]',      -- JSON array: ["cam-001","cam-002"]
    is_active     INTEGER DEFAULT 1,         -- 1 = active, 0 = deactivated
    is_locked     INTEGER DEFAULT 0,         -- 1 = locked after failed attempts
    failed_attempts INTEGER DEFAULT 0,
    created_at    TEXT    NOT NULL,
    last_login    TEXT,
    created_by    TEXT                       -- user_id of admin who created this
);

-- ─── sessions table ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    session_token TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    role          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    ip_address    TEXT
);

-- ─── audit_log table ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    user_id    TEXT,
    action     TEXT    NOT NULL,  -- 'login', 'logout', 'create_user', 'deactivate', etc.
    details    TEXT,
    ip_address TEXT
);
```

**Password security:**
```python
import bcrypt

def hash_password(plain: str) -> str:
    """One-way bcrypt hash — salt is embedded in the result."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
```

**Account lockout rule:** After 5 consecutive failed login attempts, `is_locked = 1`. Only an Admin can unlock the account. This prevents brute-force on the Pi.

---

### 12.3 Login Flow — Step by Step

```
User submits ID + Password via POST /login

  Step 1: Look up user_id in users table
          → Not found → "Invalid ID or Password" (do not reveal which)

  Step 2: Check is_active == 1
          → is_active == 0 → "Account deactivated. Contact Admin."

  Step 3: Check is_locked == 0
          → is_locked == 1 → "Account locked. Contact Admin."

  Step 4: verify_password(submitted, stored_hash)
          → False → failed_attempts += 1
                    if failed_attempts >= 5: is_locked = 1
                    → "Invalid ID or Password"
          → True  → failed_attempts = 0
                    Create session token (UUID4, 8-hour expiry)
                    Store in sessions table
                    Set cookie: aas_session=<token>
                    Log to audit_log: action='login'

  Step 5: Redirect based on role
          → 'admin'   → Full admin dashboard
          → 'faculty' → Faculty mobile dashboard (their section only)
```

**Flask route:**
```python
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uid  = request.form.get('user_id', '').strip().upper()
        pwd  = request.form.get('password', '')
        user = db_get_user(uid)

        if not user or not user['is_active'] or user['is_locked']:
            flash("Invalid credentials or account unavailable.")
            return render_template('login.html')

        if not verify_password(pwd, user['password_hash']):
            db_increment_failed(uid)
            flash("Invalid ID or Password.")
            return render_template('login.html')

        token = create_session(uid, user['role'])
        resp  = make_response(redirect('/dashboard'))
        resp.set_cookie('aas_session', token, httponly=True,
                        samesite='Lax', max_age=8*3600)
        return resp

    return render_template('login.html')
```

---

### 12.4 Admin Setup — First-Time Wizard

On first boot (when `config/aas_users.db` does not exist), the system shows a **First-Time Setup Wizard** instead of the login page:

```
http://<Pi-IP>:5000

  ┌──────────────────────────────────────────────────┐
  │  🔧 Single Shot AAS — First Time Setup           │
  │  ─────────────────────────────────────────────── │
  │  Step 1 of 3 — Create Admin Account              │
  │                                                  │
  │  Admin Full Name                                 │
  │  ┌──────────────────────────────────────────┐    │
  │  │  Dr. Ramakrishna Prasad                  │    │
  │  └──────────────────────────────────────────┘    │
  │                                                  │
  │  Admin ID (you will use this to log in)          │
  │  ┌──────────────────────────────────────────┐    │
  │  │  ADM-001                                 │    │
  │  └──────────────────────────────────────────┘    │
  │                                                  │
  │  Password          Confirm Password              │
  │  ┌─────────────┐   ┌─────────────────────────┐  │
  │  │  ••••••••  │   │  ••••••••               │  │
  │  └─────────────┘   └─────────────────────────┘  │
  │                                                  │
  │  Institution Name                                │
  │  ┌──────────────────────────────────────────┐    │
  │  │  Govt. Engineering College, Nellore      │    │
  │  └──────────────────────────────────────────┘    │
  │                                                  │
  │  [  Next → Institution Setup  ]                  │
  └──────────────────────────────────────────────────┘
```

**Setup Wizard Steps:**

```
Step 1 — Admin Account Creation
  → Full Name, Admin ID (auto-suggest: ADM-001), Password, Institution Name

Step 2 — Institution Configuration
  → Department name, Academic year, Exam eligibility threshold (default: 75%)
  → Google Sheets Service Account JSON upload (for Sheets sync)

Step 3 — Confirm & Initialize
  → Creates aas_users.db
  → Inserts admin account with bcrypt hash
  → Creates institution.json
  → Redirects to admin dashboard
  → Never shows setup wizard again (flag: setup_complete=true in institution.json)
```

---

### 12.5 Admin Panel — User Management

After login, admin sees a **User Management** section:

```
Admin Dashboard → User Management

  ┌─────────────────────────────────────────────────────────────────┐
  │  SYSTEM USERS                         [+ Add Faculty]  [+ Add Admin]│
  │  ─────────────────────────────────────────────────────────────── │
  │  ID          Name              Role     Section      Status      │
  │  ADM-001     Dr. R. Prasad     Admin    —            🟢 Active   │
  │  FAC-001     Dr. Ramesh K.     Faculty  CSE-A        🟢 Active   │
  │  FAC-002     Dr. Lakshmi S.    Faculty  CSE-A/CSE-B  🟢 Active   │
  │  FAC-003     Dr. Suresh P.     Faculty  ECE-B        🔴 Locked   │
  │  FAC-004     Dr. Kavitha N.    Faculty  CSE-A        ⚪ Inactive  │
  │  ─────────────────────────────────────────────────────────────── │
  │  Actions: [🔑 Reset Password]  [🔓 Unlock]  [🔴 Deactivate]    │
  └─────────────────────────────────────────────────────────────────┘
```

**Add New Staff/Faculty Account:**

```
[+ Add Faculty] button → Opens form:
  Full Name:      ___________________
  Faculty ID:     FAC-___  (auto-numbered: FAC-005)
  Email:          ___________________  (optional, for notifications)
  Assigned Section(s): [CSE-A ▼] [+ Add Another Section]
  Temporary Password: ___________________  (admin sets it; faculty must change on first login)
  [ Create Account ]
```

**Staff Enrollment Flow (New Faculty):**
```
1. Admin creates account → sets temporary password
2. Admin shares: Faculty ID (e.g. FAC-005) + Temporary Password (verbally or on paper)
3. Faculty logs in with temp credentials
4. System forces password change on first login
5. Faculty sets their own permanent password
6. Faculty sees only their assigned section(s) from then on
```

---

### 12.6 Opening and Closing Procedures

#### Daily Opening (Faculty)
```
1. Faculty arrives at classroom
2. Opens http://<Pi-IP>:5000 on phone
3. Enters Faculty ID + Password → Logged in
4. Dashboard shows: Section, Current Period, Subject (auto-detected from timetable)
5. [TAKE ATTENDANCE] → captures → reviews → confirms
6. Done — no special "open" step needed
```

#### Session Logout (Faculty)
```
Faculty taps [🚪 Logout] → Session token deleted from sessions table
                         → Cookie cleared
                         → Returned to login page
Auto-logout: Session expires after 8 hours of inactivity
```

#### End-of-Day Closing (Admin)
```
Admin Dashboard → [🔒 End of Day Report]
  → Summary generated: all sections, total present/absent
  → PDF/CSV exported automatically
  → Google Sheet marked as "Day closed" (colour coding on date column)
  → Admin logs out
```

#### Account Deactivation (When Faculty Leaves)
```
Admin → User Management → Select FAC-XXX → [🔴 Deactivate]
  → is_active = 0
  → All active sessions for that user deleted immediately
  → Faculty cannot log in again
  → Their attendance records remain in sheets (historical data preserved)
  → Account can be reactivated if needed
```

---

### 12.7 New Files for Login System

| File | Purpose |
|---|---|
| `config/aas_users.db` | SQLite database — users, sessions, audit log |
| `aas/core/auth.py` | `hash_password`, `verify_password`, `create_session`, `validate_session`, `db_get_user` |
| `aas/core/db.py` | SQLite connection manager, schema initializer |
| `web/templates/login.html` | Login page — ID + Password form |
| `web/templates/setup_wizard.html` | First-time setup pages (Steps 1–3) |
| `web/templates/user_management.html` | Admin user management panel |

---

## 13. Standard Attendance Sheet Structure

### 13.1 Source

The following structure is derived directly from the **"Sample Structure of Attendance Sheet.xlsx"** file provided by the owner. This is the **mandatory standard** for all Google Sheets generated by Single Shot AAS v2.0. Every section's attendance sheet must follow this layout exactly.

---

### 13.2 Complete Sheet Layout

**Sheet Name:** `Weekly Attendance` (one sheet per week, or one sheet per section per semester)

#### Header Block (Rows 1–5)

```
Row 1 (Title):
┌──────────────────────────────────────────────────────────────────────────────────┐
│  WEEKLY ATTENDANCE REGISTER — DEPARTMENT OF COMPUTER SCIENCE & ENGINEERING       │
│  (spans full width — merged across all columns)                                  │
└──────────────────────────────────────────────────────────────────────────────────┘

Row 2 (Metadata):
│ Class & Degree: │ B.Tech CSE │ Section: │ CSE-A │ Semester: │ IV │ Acad. Year: │ 2025-2026 │ Faculty: │ Dr. K. Sharma │ Room/Lab: │ Hall 302 │

Row 3 (Week Info):
│ Week Duration: │ 15/09/2025–20/09/2025 │ Working Days: │ 6 Days (Mon–Sat) │ Curriculum: │ 6 Subjects (36 Periods/Wk) │ Marking: │ 1=Present, 0=Absent │ Rule: │ Min 75% Eligibility │ Status: │ Active & Verified │

Rows 4–5 (Summary Stats — auto-calculated):
│ TOTAL STUDENTS │         │ TOTAL SESSIONS │         │ CLASS AVERAGE │         │ ELIGIBLE (≥75%) │         │ SHORTAGE (<75%) │
│ =COUNTA(B9:B28)│         │ =MAX(AU9:AU28) │         │ =AVERAGE(AV9) │         │ =COUNTIF(…,"El")│         │ =COUNTIF(…,"Sh")│
```

#### Column Header Block (Rows 7–8)

```
Row 7 (Day groups — merged across 6 subject columns each):
│ S.No. │ Name │ Roll No. │ Day 1 (Mon 15/09) ──────── │ Day 2 (Tue 16/09) ──────── │ ... │ Day 6 (Sat 20/09) ──────── │ CUMULATIVE (Subject-wise) ─── │ OVERALL SUMMARY ─────── │

Row 8 (Individual subject columns per day):
│       │      │          │ Math │ PHY │ CHE │ CSE │ ENG │ EVS │ Math │ PHY │ CHE │ CSE │ ENG │ EVS │ ... (×6 days) │ Math│PHY│CHE│CSE│ENG│EVS │ Attended│Conducted│Attend%│Eligibility│
```

**Column layout expanded:**

| Col Range | Content | Width |
|---|---|---|
| A | S.No. (Serial Number) | Fixed |
| B | Name of Student | Wide |
| C | Roll Number (e.g. CSE2025001) | Fixed |
| D–I | Day 1 subjects: Math, PHY, CHE, CSE, ENG, EVS | 6 cols |
| J–O | Day 2 subjects (same 6) | 6 cols |
| P–U | Day 3 subjects | 6 cols |
| V–AA | Day 4 subjects | 6 cols |
| AB–AG | Day 5 subjects | 6 cols |
| AH–AM | Day 6 subjects | 6 cols |
| AN–AS | Cumulative per-subject totals (6 cols) | 6 cols |
| AT | Total Attended (SUM of AN:AS) | Fixed |
| AU | Total Conducted (COUNTA of date header row) | Fixed |
| AV | Attendance % (AT/AU) | Fixed |
| AW | Eligibility: "Eligible" if AV≥0.75, else "Shortage" | Fixed |

**Total columns: 49 (A through AW)**

#### Data Row Format (Rows 9 onward, one row per student)

```
| 1 | Arjun Singh | CSE2025001 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 1 | 1 | ... (36 daily cells) ... | =SUM(D9,J9,P9,V9,AB9,AH9) | ... (6 subject totals) ... | =SUM(AN9:AS9) | =COUNTA($D$8:$AM$8) | =AT9/AU9 | =IF(AV9>=0.75,"Eligible","Shortage") |
```

**Marking convention:**
- `1` = Present
- `0` = Absent
- Empty cell = Period not conducted (holiday, no class)

#### Footer / Summary Row (Last data row + 1)

```
Row 29 (example for 20 students ending at row 28):
│ TOTAL │ (blank) │ (blank) │ =SUM(D9:D28) │ =SUM(E9:E28) │ ... (sum for each subject column) ... │
```

---

### 13.3 How Single Shot AAS v2.0 Maps to This Structure

The system writes to Google Sheets in this exact format. Here is the mapping between AAS data and the Excel columns:

| Excel Column | AAS Data Source | How Written |
|---|---|---|
| Col A (S.No.) | Row index | Auto-incremented from enrollment |
| Col B (Name) | `enrolled_name` from face encoding | From enrollment database |
| Col C (Roll No.) | `roll_number` from camera registry | From student enrollment record |
| Day-Subject cells (D–AM) | Recognition result for that period | `1` if present, `0` if absent — written by `spreadsheet.py` |
| Cumulative cols (AN–AS) | `=SUM(D{r},J{r},P{r},V{r},AB{r},AH{r})` for each subject | Google Sheets formula, written once during sheet initialization |
| Col AT (Attended) | `=SUM(AN{r}:AS{r})` | Formula |
| Col AU (Conducted) | `=COUNTA($D$8:$AM$8)` | Formula (counts non-empty header cells = total periods held) |
| Col AV (%) | `=AT{r}/AU{r}` | Formula |
| Col AW (Eligibility) | `=IF(AV{r}>=0.75,"Eligible","Shortage")` | Formula |

**The `eligibility_threshold` (75%) is configurable** in `institution.json`:
```json
{ "exam_eligibility_threshold": 0.75 }
```

---

### 13.4 How AAS Writes a Single Attendance Event

When faculty takes attendance for `CSE-A | DBMS | Period 3 | Day 3 (Wed)`:

```
Step 1: Identify the target column
  → Day 3 = Wed column group (P–U)
  → "DBMS" maps to "CSE" subject column within that group
  → Target column = column R (for example)

Step 2: Identify the target header cell
  → Row 8, column R → write "DBMS" (if not already written)
  → Row 7, column P–U group header → update to "Day 3 (Wed DD/MM)"

Step 3: Write attendance values for each student
  → For each student in cam-001's enrolled list:
      - If recognized as present → write 1
      - If in absent list (or not recognized) → write 0
  → Batch update via Google Sheets API batchUpdate() (single API call)

Step 4: Formulas self-update
  → Cumulative totals, %, Eligibility all recalculate automatically
```

---

### 13.5 Column Naming — Subject Code Mapping

The 6 subjects per day match the Excel sample. The admin configures these in `config/timetable.json`. Subject names are truncated to 3–5 characters for the column header to fit the cell:

| Full Subject Name | Column Header |
|---|---|
| Mathematics | Maths |
| Physics | PHY |
| Chemistry | CHE |
| Computer Science / DBMS / OS | CSE (or subject abbreviation) |
| English / Professional Communication | ENG |
| Environmental Science | EVS |

The admin can override these abbreviations in the timetable config.

---

### 13.6 Sheet Creation — Admin Initialization Flow

When a new section is enrolled:
```
1. Admin enrolls section (CSE-A) via admin dashboard
2. System calls spreadsheet.py → create_weekly_sheet(section_id, week_start_date)
3. Sheet is created in Google Drive with:
   - Title: "Weekly Attendance — CSE-A — Week of 15/09/2025"
   - Row 1: Title merged across A1:AW1
   - Row 2: Metadata (Class, Section, Semester, Year, Faculty, Room)
   - Row 3: Week info (Duration, Working Days, Curriculum, Marking Guide, Rule, Status)
   - Rows 4–5: Summary stats formulas
   - Row 7: Day group headers (merged)
   - Row 8: Subject sub-headers
   - Rows 9+: Student rows (Name, Roll No., 36 empty daily cells, formula cells)
4. Sheet is formatted: Navy header (#1A365D), zebra striping, bold headers
5. Sheet ID is stored in cameras.json for future write-back
```

**New weekly sheet auto-creation:** Every Monday (or on first attendance of the week), the system checks if a sheet exists for the current week. If not, it creates one automatically. Weekly sheets are named: `"CSE-A Week 37 (15-20 Sep 2025)"`.

---

### 13.7 Updated `spreadsheet.py` — Key Function Signatures

```python
def create_weekly_sheet(
    camera_id: str,
    week_start: datetime.date,
    subjects: list[str],  # e.g. ['Maths','PHY','CHE','CSE','ENG','EVS']
    students: list[dict]  # [{name, roll_number}, ...]
) -> str:
    """Create a new weekly attendance Google Sheet. Returns sheet ID."""

def write_attendance_event(
    sheet_id:   str,
    day_number: int,       # 1–6 (Mon–Sat)
    subject:    str,       # e.g. 'DBMS' → maps to 'CSE' column position
    present:    list[str], # list of student names marked present
    absent:     list[str]  # list of student names marked absent
) -> bool:
    """Write 1/0 for one attendance event (one period). Single batchUpdate call."""

def get_student_summary(
    sheet_id: str,
    student_name: str
) -> dict:
    """Return {attended, conducted, percentage, eligibility} for one student."""

def get_section_summary(sheet_id: str) -> dict:
    """Return aggregate stats: total students, sessions, avg %, eligible count, shortage count."""
```

---

*Sections 12 and 13 added on September 19, 2026.*
*Next update: Implementation task breakdown for the login system and sheet initialization.*
