# Single Shot AAS — Gap Analysis & Development Roadmap
**Prepared by:** Technical Review (Antigravity AI)
**Date:** September 17, 2026
**Project:** Single Shot AAS — AI Attendance System
**Author / Owner:** Kummarapalli Dastagiri

---

> [!IMPORTANT]
> This report is a structured audit of **every missing feature, architectural gap, and GUI upgrade** identified during a full code review of the current codebase. Each section maps directly to a question raised during the technical walkthrough. Review each item, mark priority, and proceed with development in phases.

---

## Table of Contents

1. [How the System Works — Confirmed Behaviours](#1-how-the-system-works--confirmed-behaviours)
2. [Gap 1 — Multi-Faculty Login & Access Control](#2-gap-1--multi-faculty-login--access-control)
3. [Gap 2 — Camera Handover to Individual Teachers](#3-gap-2--camera-handover-to-individual-teachers)
4. [Gap 3 — Post-Attendance Notification to Teacher](#4-gap-3--post-attendance-notification-to-teacher)
5. [Gap 4 — ML Model — Custom vs. Open Source](#5-gap-4--ml-model--custom-vs-open-source)
6. [Gap 5 — Subject / Period Awareness](#6-gap-5--subject--period-awareness)
7. [Gap 6 — Dashboard GUI Upgrades](#7-gap-6--dashboard-gui-upgrades)
8. [Gap 7 — Reporting & Analytics](#8-gap-7--reporting--analytics)
9. [Gap 8 — Parent Notification](#9-gap-8--parent-notification)
10. [Gap 9 — Android App Integration](#10-gap-9--android-app-integration)
11. [Priority Matrix — What to Build First](#11-priority-matrix--what-to-build-first)
12. [What Is Already Working Correctly](#12-what-is-already-working-correctly)
13. [Hardware Requirement — Camera Specification for 60-Person Classroom](#13-hardware-requirement--camera-specification-for-60-person-classroom)

---

## 1. How the System Works — Confirmed Behaviours

> These are behaviours that ARE built and working. Listed here for your reference before reviewing gaps.

| # | Feature | Status | Notes |
|---|---|---|---|
| ✅ | Single-shot classroom photo → all faces detected simultaneously | **Working** | Core feature |
| ✅ | 3-angle enrollment (Front / Left / Right) | **Working** | Stored as `.pkl` encoding |
| ✅ | 128-D ResNet face embedding via `face_recognition` (dlib) | **Working** | Pre-trained model, no custom training needed |
| ✅ | Multi-section camera registry (`cameras.json`) | **Working** | Each section has its own camera + Google Sheet |
| ✅ | Google Sheets auto-update (present / absent / late) | **Working** | Atomic batch write, 1 API call for 60 students |
| ✅ | Voice trigger — say "take attendance" → camera fires | **Working** | Vosk offline ASR, 30s debounce guard |
| ✅ | TTS announcement after shot | **Working** | "Boys: 18, Girls: 12, Total: 60" |
| ✅ | Student email notification per attendance event | **Working** | Gmail SMTP, App Password |
| ✅ | Google OAuth2 login (no passwords stored) | **Working** | CSRF protected |
| ✅ | Annotated classroom photo saved after recognition | **Working** | Bounding boxes + names drawn |
| ✅ | `/api/attendance/today` API for live roster | **Working** | Returns `{name, gender, status}` list |
| ✅ | Docker + systemd for headless Pi deployment | **Working** | Auto-restarts on boot |

---

## 2. Gap 1 — Multi-Faculty Login & Access Control

### Problem

**Raised question:** *"The GUI is mainly used for the admin machine — how do individual teachers for different classes use it? How is camera control handed over to a faculty?"*

**Current reality:** The system supports **only ONE Google account** logged in at a time. The OAuth token is saved as a single `token.json` file. Every person who opens `http://<Pi-IP>:5000` shares the same session. There is **no concept of faculty accounts, roles, or assignments**.

```
Current:  ONE admin login → sees ALL sections → can fire ANY camera
Required: Faculty A login → sees ONLY CSE-A section → can ONLY fire cam-001
          Faculty B login → sees ONLY ECE-B section → can ONLY fire cam-002
          Admin login    → sees ALL sections → full control
```

### What Is Missing

| Missing | Description |
|---|---|
| **Per-faculty Google login** | Each teacher logs in with their own Google account |
| **Per-user token storage** | Tokens stored as `tokens/<email_hash>.json`, not a single `token.json` |
| **Faculty registry** | A database/JSON mapping: `{faculty_email → [camera_id_1, camera_id_2]}` |
| **Role system** | `admin` role vs `faculty` role — admin can enroll, manage cameras; faculty can only take attendance |
| **Filtered dashboard** | Faculty sees only their assigned cameras/sections on login |
| **Admin panel** | Admin can assign sections to faculty members |

### Files to Modify

- `src/aas/integrations/google/oauth.py` — multi-user token storage
- `src/aas/web/app.py` — role-based route guards, filtered dashboard
- `config/cameras.json` — add `assigned_faculty_email` field per camera
- **[NEW]** `config/faculty_registry.json` — faculty → section assignments
- **[NEW]** `src/aas/web/templates/admin.html` — admin management panel

### Data Model Change Required

```jsonc
// cameras.json — add these fields to each camera entry
{
  "id": "cam-001",
  "display_name": "CSE A Section",
  "rtsp_url": "rtsp://192.168.1.20/stream",
  "sheet_id": "1abc...",
  "section_code": "CSE",
  // NEW FIELDS:
  "assigned_faculty_email": "teacher1@college.edu",
  "subject": "DBMS",
  "period_number": 3
}
```

---

## 3. Gap 2 — Camera Handover to Individual Teachers

### Problem

**Raised question:** *"How does the control of camera get handed over to a faculty?"*

**Current reality:** Camera control is not "handed over" — anyone on the dashboard can click "Take Attendance" for any camera. There is no assignment, no handover, no lock.

### Real-World Deployment Options (Workarounds That Work Today)

These are practical workarounds that work with the **current system** before multi-faculty is built:

| Option | How It Works | Best For |
|---|---|---|
| **Voice Trigger** | Teacher says "take attendance" in classroom → ceiling mic hears it → camera fires | Most hands-free, recommended |
| **Room Tablet** | Cheap Android tablet mounted per classroom at `http://<Pi-IP>:5000` | Each teacher taps their section |
| **Teacher's Phone** | Teacher opens URL on phone (same WiFi) | No extra hardware needed |
| **Auto-schedule** | Cron job fires attendance at fixed timetable slots | Fully automatic, no teacher action needed |

### What Needs to Be Built for Proper Handover

| Feature | Description |
|---|---|
| **Camera-scoped session** | After login, teacher is locked to their assigned cameras only |
| **One-tap interface** | Teacher sees ONE big "Take Attendance" button for their room — not a full admin dashboard |
| **Timetable-based auto-trigger** | System automatically fires at period start time for each section |

---

## 4. Gap 3 — Post-Attendance Notification to Teacher

### Problem

**Raised question:** *"After taking attendance how does the teacher know the presencies and absenties to note it down? Is there any mechanism built for it?"*

### What IS Built (Confirmed)

| Mechanism | Who Gets It | Content | Status |
|---|---|---|---|
| 🔊 TTS Speaker | Everyone in classroom | "Boys: 18, Girls: 12, Total: 60" | ✅ Working |
| 📧 Student Email | Each student individually | "Your attendance is PRESENT/ABSENT" | ✅ Working |
| 📊 Google Sheet | Whoever opens the sheet | Full present/absent/late table | ✅ Working |
| 🖼️ Annotated Photo | Dashboard viewer | Photo with names drawn on faces | ✅ Working |
| 📋 `/api/attendance/today` | Dashboard (API) | JSON list of names + statuses | ✅ Working |

### What Is MISSING

| Missing | Priority | Description |
|---|---|---|
| ❌ **Teacher summary email** | 🔴 HIGH | After every shot, teacher receives email: *"Section CSE-A — 18 present, 5 absent: [Raju, Priya, ...]"* |
| ❌ **Dashboard absent list panel** | 🔴 HIGH | The API data exists (`/api/attendance/today`) but the **UI does not display a clear Present ✅ / Absent ❌ split list** after each shot |
| ❌ **Absent name list in TTS** | 🟡 MEDIUM | TTS only says counts. Could also read out absent names: *"Absent: Raju Kumar, Priya Sharma"* |
| ❌ **WhatsApp / SMS channel** | 🟢 LOW | Students without email access miss alerts. Twilio API integration needed |
| ❌ **Push notification to teacher phone** | 🟢 LOW | Browser push notification when attendance completes |

> [!NOTE]
> The teacher summary email is the **easiest and highest impact fix**. The `cameras.json` already stores `sheet_id`. Adding `faculty_email` to each camera + one extra `send_email()` call in `take_attendance()` completes this feature. Estimated effort: **2–3 hours**.

---

## 5. Gap 4 — ML Model — Custom vs. Open Source

### Problem

**Raised question:** *"What kind of ML model is used? Is it ready-available or custom? If own, is it best to use a ready-available open-source model to fit standards?"*

### Current Model Stack

| Component | Library | Model | Trained By | Status |
|---|---|---|---|---|
| **Face Detection** | OpenCV YuNet | Feature Pyramid Network CNN | OpenCV team | ✅ Pre-trained, ready |
| **Face Recognition** | `face_recognition` (dlib) | ResNet + Triplet Loss | dlib team, 3M+ face dataset | ✅ Pre-trained, ready |
| **Fallback Detection** | dlib HOG | HOG + Linear SVM | dlib team | ✅ Pre-trained, ready |
| **Voice ASR** | Vosk | Kaldi TDNN acoustic model | Alphacephei | ✅ Pre-trained, ready |

**No custom training is done.** All models are pre-trained open-source. This is the correct approach for this use case.

### Assessment

The current pre-trained dlib ResNet achieves **99.38% accuracy on the LFW benchmark** — this is production-grade. Custom training is **not needed** for a 35–60 student classroom.

### What Could Be Improved (Optional Upgrade)

| Upgrade | Benefit | Effort |
|---|---|---|
| **InsightFace (ArcFace)** | Better accuracy for partial faces, side angles, low-light | Medium — swap `face_recognition` for `insightface` |
| **Fine-tuning on enrolled photos** | Better accuracy for your specific students | High — needs GPU, training pipeline |
| **ONNX quantized models** | Faster inference on Raspberry Pi (ARM) | Medium — use pre-quantized ONNX weights |

> [!TIP]
> **Recommendation:** Keep the current dlib ResNet for now. If recognition accuracy becomes a real-world problem after deployment, upgrade to **InsightFace ArcFace** — it's open-source, has Python bindings, and outperforms dlib on partial/angled faces. Do NOT build custom models from scratch.

---

## 6. Gap 5 — Subject / Period Awareness

### Problem

**Context:** In a college, the same classroom section has multiple subjects per day. CSE-A may have Physics at 9 AM, DBMS at 11 AM, OS at 2 PM — each with a different teacher. Currently the system only knows "section + date". If DBMS teacher takes attendance at 11 AM it **overwrites** any previous attendance entry for the same date column, and there is no record of which subject it was for.

### What Is Missing

| Missing | Description |
|---|---|
| **Subject field in attendance** | Google Sheet columns should be `9/17/2026 - DBMS (P3)` not just `9/17/2026` |
| **Period-aware date column** | Multiple attendance entries per day per section (one per period/subject) |
| **Timetable configuration** | Admin sets the college timetable: which subject, which faculty, which period, what time |
| **Auto-subject detection** | Based on current time, system auto-selects the correct subject when attendance is taken |

### Data Model Change Required

```python
# Currently:
_today_string() → "9/17/2026"

# Required:
_today_period_string(subject, period) → "9/17/2026 | DBMS | P3"
```

### Files to Modify

- `src/aas/attendance/spreadsheet.py` — `_today_string()` → `_today_period_string()`
- `config/cameras.json` — add timetable per camera
- **[NEW]** `config/timetable.json` — full college timetable
- `src/aas/web/app.py` — pass subject/period to attendance route

---

## 7. Gap 6 — Dashboard GUI Upgrades

### Problem

**Context:** The dashboard is a single-page app (SPA) at `index.html`. After taking attendance, results are shown but the UI lacks clarity, faculty-specific views, and actionable post-attendance display.

### 7.1 Post-Attendance Results Panel

**Currently:** After "Take Attendance" is clicked, the API returns JSON data but the UI's display of results is minimal. The teacher cannot quickly identify who is absent.

**Required UI:**
```
┌────────────────────────────────────────────────────────┐
│  📷 CSE-A — Attendance Taken at 9:05 AM                │
│  ─────────────────────────────────────────────────────  │
│  ✅ Present (32)     ❌ Absent (8)     ⏰ Late (2)      │
│  ─────────────────────────────────────────────────────  │
│  PRESENT:  Raju, Priya, Arjun, Sita ... (+28 more)     │
│  ABSENT:   Mohan, Kavya, Deepak, Sushma (+4 more)      │
│  LATE:     Rohit, Anjali                                │
│  ─────────────────────────────────────────────────────  │
│  [📧 Email Absentees]  [📥 Download Report]  [🔁 Retry]│
└────────────────────────────────────────────────────────┘
```

**Gap:** This panel does not exist. The API data exists (`/api/attendance/today`) but the UI doesn't render a clear split view.

### 7.2 Faculty-Scoped Dashboard

**Currently:** All cameras visible to all users.
**Required:** Teacher logs in → sees only their section's camera and a single large "Take Attendance" button.

### 7.3 Live Camera Preview Before Shot

**Currently:** MJPEG stream exists at `/api/camera/stream` but no guaranteed live preview before shooting.
**Required:** Before clicking "Take Attendance", teacher should see a **live preview** of the camera feed to confirm lighting and student positioning are correct.

### 7.4 Enrollment UI Quality Feedback

**Currently:** Enrollment captures 3 angles but gives no real-time feedback on quality.

**Required feedback during webcam capture:**
- ✅ Face detected — ready to save
- ⚠️ Face too small — move closer to camera
- ❌ No face found — reposition yourself
- ⚠️ Image too blurry — hold still

### 7.5 Setup Wizard Improvements

**Currently:** Setup creates sections and cameras. RTSP URLs are entered but not validated live.
**Required:**
- Live camera test frame preview during Step 3
- RTSP URL format validator (check stream before saving)
- Faculty email assignment during section creation

### 7.6 Mobile-Responsive Design

**Required:** Teachers must be able to use the dashboard fully from a **smartphone** on college WiFi. Current SPA must be responsive for phone screen sizes (≤ 480px).

### 7.7 Session Management for Multiple Teachers

**Required:** When multiple faculty log in simultaneously from different devices/browsers, sessions should be independent. Currently the server uses a shared single-user session model.

---

## 8. Gap 7 — Reporting & Analytics

### Problem

**Context:** Google Sheets accumulates a growing history of attendance dates. But there is no way to view cumulative analytics or generate reports from within the system.

### Missing Reporting Features

| Feature | Description | Priority |
|---|---|---|
| ❌ **Cumulative attendance %** | "Raju has attended 72 of 100 classes = 72%" — visible per student | 🔴 HIGH |
| ❌ **Defaulter list** | Students below 75% attendance threshold — auto-flagged and listed | 🔴 HIGH |
| ❌ **PDF report export** | Download "CSE-A — September 2026 Attendance Report.pdf" | 🟡 MEDIUM |
| ❌ **Excel/CSV export** | Download raw CSV from the dashboard | 🟡 MEDIUM |
| ❌ **Monthly summary view** | Calendar-style heatmap of attendance per student | 🟢 LOW |
| ❌ **Section-level analytics** | Average attendance per section, per subject | 🟢 LOW |
| ❌ **Teacher report** | Summary of how many periods each faculty conducted | 🟢 LOW |

> [!NOTE]
> All data for these reports **already exists in Google Sheets**. A new `/api/attendance/history?camera_id=xxx` endpoint that reads all date columns from the sheet would enable all the above reports without any new storage system.

---

## 9. Gap 8 — Parent Notification

### Problem

**Context:** Currently, attendance emails go only to students. In most Indian colleges, parents/guardians also need to be informed — especially when a student is absent.

### What Is Missing

| Missing | Description |
|---|---|
| ❌ **Parent email field in enrollment** | Enrollment form has no `parent_email` field |
| ❌ **Parent column in Google Sheet** | No storage for parent contact |
| ❌ **Parent notification on absence** | No mechanism to email parents when student is marked absent |
| ❌ **Configurable alert threshold** | e.g., "Alert parent only if absent 3 consecutive days" |

### Data Model Change Required

```
Google Sheet columns — current:
Col 1: Name  |  Col 2: Email  |  Col 3: Gender  |  Col 4: PIN  |  Col 5+: Dates

Required addition:
Col 1: Name  |  Col 2: Email  |  Col 3: Parent Email  |  Col 4: Gender  |  Col 5: PIN  |  Col 6+: Dates
```

---

## 10. Gap 9 — Android App Integration

### Problem

**Context:** The project includes `android/Attendance_app.aia` (MIT App Inventor companion app) but there is no documentation on how it integrates with the Flask backend, and the required REST endpoints do not exist.

### What Is Missing

| Missing | Description |
|---|---|
| ❌ **Student login via PIN** | PIN is sent to student at enrollment (`email_pin()`) but there is no API that accepts the PIN for authentication |
| ❌ **REST API for student self-service** | No `/api/student/me?pin=1234` endpoint returning that student's own attendance history |
| ❌ **Dispute / correction request** | No mechanism for student to flag an incorrect marking via app |
| ❌ **Teacher app interface** | No mobile-optimised view for faculty to trigger attendance from their phone |

### Endpoints to Build

```
[NEW] GET  /api/student/me?pin=1234      → Returns student's full attendance history
[NEW] POST /api/student/dispute          → Student raises dispute for incorrect marking
[NEW] GET  /api/teacher/my-sections      → Returns sections assigned to logged-in faculty
```

---

## 11. Priority Matrix — What to Build First

> [!IMPORTANT]
> Recommended development order based on impact vs. effort. Review and confirm priorities before proceeding.

| Priority | # | Feature | Effort | Phase |
|---|---|---|---|---|
| 🔴 CRITICAL | 1 | **Teacher summary email** after each attendance shot | 2–3 hrs | Phase 1 |
| 🔴 CRITICAL | 2 | **Post-attendance results panel** — present/absent split in dashboard UI | 1 day | Phase 1 |
| 🔴 CRITICAL | 3 | **Faculty email field** in `cameras.json` (setup wizard + UI) | 1 day | Phase 1 |
| 🔴 CRITICAL | 4 | **Faculty-scoped dashboard** — teacher sees only their assigned sections | 2 days | Phase 1 |
| 🟡 HIGH | 5 | **Subject / Period awareness** in attendance date column naming | 2 days | Phase 2 |
| 🟡 HIGH | 6 | **Cumulative attendance %** per student — API + dashboard UI | 2 days | Phase 2 |
| 🟡 HIGH | 7 | **Defaulter list** (below 75% threshold) — auto-generated | 1 day | Phase 2 |
| 🟡 HIGH | 8 | **Multi-faculty OAuth login** (per-user token storage + role system) | 3 days | Phase 2 |
| 🟡 HIGH | 9 | **PDF / CSV export** of attendance report | 1 day | Phase 2 |
| 🟡 HIGH | 10 | **Enrollment quality feedback UI** (blur/size/face detection live feedback) | 1 day | Phase 2 |
| 🟡 HIGH | 11 | **Mobile-responsive dashboard** design | 2 days | Phase 2 |
| 🟢 MEDIUM | 12 | **Parent email notification** + `parent_email` field | 1 day | Phase 3 |
| 🟢 MEDIUM | 13 | **Timetable-based auto-trigger** (cron per period start time) | 2 days | Phase 3 |
| 🟢 MEDIUM | 14 | **Android app REST API** (`/api/student/me`, `/api/student/dispute`) | 2 days | Phase 3 |
| 🟢 LOW | 15 | **InsightFace ArcFace upgrade** (optional accuracy improvement) | 3 days | Phase 3 |
| 🟢 LOW | 16 | **Monthly analytics dashboard** (heatmap, section-level stats) | 3 days | Phase 3 |
| 🟢 LOW | 17 | **WhatsApp / SMS via Twilio** for absentee alerts | 2 days | Phase 3 |

---

## 12. What Is Already Working Correctly

> [!NOTE]
> Do NOT change these systems — they are production-ready and tested with 103 automated tests.

| System | Why It Is Solid |
|---|---|
| **Face recognition pipeline** | Standards-compliant (IEC 62676-4, ISO/IEC 19794-5), quality-gated, adaptive scaling |
| **Google Sheets batch write** | Atomic 1-API-call update, rate-limit safe, exponential backoff retry |
| **Voice trigger (Vosk)** | Fully offline, debounce-protected, non-blocking thread |
| **Safe Pickle deserialization** | `RestrictedUnpickler` blocks RCE exploits — do not replace with raw `pickle.load()` |
| **OAuth CSRF protection** | 32-byte state token verified on every callback — secure |
| **Multi-section camera registry** | `cameras.json` CRUD is thread-safe and extensible |
| **Docker + systemd deployment** | Production-ready for Raspberry Pi 4 headless operation |
| **103 automated tests** | Full unit + integration coverage — always run `pytest` before committing changes |

---

## 13. Hardware Requirement — Camera Specification for 60-Person Classroom

### The Core Constraint — The Back-Row Problem

This is the most critical physical limitation. A ceiling-mounted camera captures students at **vastly different distances** — front row at ~3m, back row at ~10m. The AI pipeline (enforced by IEC 62676-4 and ISO/IEC 19794-5 standards baked into `engine.py`) requires every face — **including the back row** — to occupy at least **80 × 80 pixels** in the raw frame. If the back-row face is smaller than this, the system counts that student as "present in room" but **refuses to identify them** (excluded from matching to prevent false positives).

```
         CAMERA (ceiling, 3.5m height)
           ▼
Row 1 ——— 3m  ——→ Face ~220px wide  ✅ Easily identified
Row 2 ——— 5m  ——→ Face ~130px wide  ✅ Identified
Row 3 ——— 7m  ——→ Face  ~90px wide  ✅ Identified
Row 4 ——— 8m  ——→ Face  ~75px wide  ⚠️ Borderline at 1080p
Row 5 ——— 9m  ——→ Face  ~60px wide  ❌ FAILS at 1080p — below 80px gate
Row 6 ——— 10m ——→ Face  ~50px wide  ❌ FAILS at 1080p — below 80px gate
```

**Conclusion:** A standard 1080p (2MP) camera physically cannot identify back-row students in a 10m-deep classroom. Higher resolution is mandatory.

---

### Standards Enforced by the System

| Standard | Minimum Requirement | Consequence of Failure |
|---|---|---|
| **IEC 62676-4 DORI** | Face bounding box ≥ **80 × 80 px** | Face detected but NOT identified — marked absent |
| **ISO/IEC 19794-5** | Interpupillary Distance (IPD) ≥ **30 px** | Face excluded from embedding comparison |
| **System minimum frame width** | ≥ **1280 px** (recommended ≥ 1920 px) | Frame rejected entirely by quality gate |
| **Brightness gate** | Grayscale mean ≥ **40.0** | Frame rejected — camera needs IR or good lighting |
| **Blur / sharpness gate** | Laplacian variance ≥ **40.0** | Frame rejected — autofocus drift causes false absences |

---

### Resolution vs. Back-Row Coverage Table

*Assumptions: 10m-deep classroom, 8m wide, standard Indian adult face width = 16cm, camera at 3.5m ceiling height, 100° FOV lens.*

| Camera Resolution | Megapixels | Back-Row Face Width | Eye-to-Eye (IPD) | Verdict |
|---|---|---|---|---|
| 720p (1280 × 720) | 0.9 MP | ~35 px | ~13 px | ❌ **Fails completely** — back 3 rows unidentifiable |
| **1080p (1920 × 1080)** | **2 MP** | ~70 px | ~26 px | ⚠️ **Borderline** — only front 4 rows reliably identified |
| **2K / QHD (2560 × 1440)** | **3.7 MP** | ~93 px | ~35 px | ✅ **Minimum safe** — all 6 rows identifiable |
| **5MP (2592 × 1944)** | **5 MP** | ~108 px | ~40 px | ✅ **Good** — standard entry-level IP camera range |
| **4K UHD (3840 × 2160)** | **8.3 MP** | ~140 px | ~52 px | ✅ **Recommended** — comfortable margin for all rows |
| **8MP (3264 × 2448)** | **8 MP** | ~135 px | ~50 px | ✅ **Very Good** — matches 4K performance |
| **12MP+** | **12+ MP** | ~180+ px | ~65+ px | ✅ **Excellent** — forensic-quality, future-proof |

> [!IMPORTANT]
> **Minimum for 60 students in a 10m classroom: 5MP**
> **Recommended: 8MP / 4K UHD**
> **Never use 1080p (2MP) for rooms deeper than 7 metres.**

---

### All Specs That Matter — Not Just Megapixels

Megapixels alone won't guarantee success. Every spec below matters equally:

| Spec | Minimum | Recommended | Why It Matters |
|---|---|---|---|
| **Resolution** | 5MP (2592×1944) | 8MP / 4K (3840×2160) | Back-row face pixel count — the critical constraint |
| **Lens FOV** | 90° wide-angle | 100°–110° | Must cover full 8m classroom width from ceiling |
| **Focal Length** | 4mm | 2.8mm | Short focal length = wide angle = ceiling coverage |
| **Low-light / LUX** | ≤ 0.5 Lux | ≤ 0.1 Lux (with IR) | Early morning / dim classrooms fail the brightness gate |
| **IR Night Vision** | Optional | Yes (IR LEDs) | Ensures capture even in poorly lit rooms |
| **Compression** | H.264 | H.265 | For RTSP streaming over LAN to the Raspberry Pi |
| **RTSP support** | **Required** | Required | `cv2.VideoCapture("rtsp://...")` is how the system captures |
| **Focus type** | Fixed focus | Fixed (not autofocus) | Autofocus drift causes blur — fails the Laplacian sharpness gate |
| **Frame rate** | 1 FPS sufficient | 5–15 FPS | Single-shot only — high FPS is not needed |
| **Sensor type** | CMOS | Sony STARVIS CMOS | Better dynamic range for mixed lighting (tubelight + window) |
| **Shutter speed** | ≥ 1/60s | ≥ 1/100s | Prevents motion blur when students shift in seats |
| **Mounting** | Ceiling centre | Ceiling centre or front-wall top | Minimizes occlusion — student heads don't block each other |
| **IP Rating** | IP54 | IP66 | Dust and moisture resistance for long-term deployment |

---

### Lens + Ceiling Height Coverage Calculation

```
Room:              8m wide × 10m deep, 3.5m ceiling
Camera FOV:        100° wide-angle lens
Mounting point:    Ceiling centre, front half of room

Horizontal coverage at floor level:
  Width = 2 × 3.5m × tan(50°) = 2 × 3.5 × 1.19 = 8.3m  ✅ covers full width

For 8MP camera (3264 × 2448) at back row (10m depth):
  Pixels per metre = 3264px ÷ 8.3m = ~393 px/m
  Face width (16cm) at back = 393 × 0.16 = ~63 px    ← at extreme edge
  Face width (16cm) at centre = ~100–140 px            ← comfortable

→ Edge seats at back row: 63px — just below the 80px gate.
→ Fix: Use 4K (3840×2160) instead → 462 px/m → ~74px at edge → safer.
→ Better fix: Mount two cameras (one per half of classroom).
```

> [!TIP]
> For classrooms wider than 8m or deeper than 10m, consider **two cameras** — one covering the front half, one covering the back half. The system already supports multiple cameras per section via `cameras.json`.

---

### Recommended Camera Models (India Market)

| Model | Resolution | FOV | RTSP | Price Range | Verdict |
|---|---|---|---|---|---|
| **Hikvision DS-2CD2185G1-I** | 8MP (4K) | 107° (2.8mm) | ✅ Yes | ₹4,000–6,000 | ✅ Best value |
| **Dahua IPC-HDW2831T-AS** | 8MP | 107° (2.8mm) | ✅ Yes | ₹4,500–7,000 | ✅ Reliable |
| **CP Plus CP-UNC-TA81L3C** | 8MP | 105° (2.8mm) | ✅ Yes | ₹3,500–5,500 | ✅ Popular in India |
| **Reolink RLC-810A** | 8MP (4K) | 105° | ✅ Yes | ₹5,000–8,000 | ✅ Easy RTSP setup |
| **Hikvision DS-2CD2T47G2** | 4MP | 103° | ✅ Yes | ₹2,500–4,000 | ⚠️ Minimum for 10m depth |
| **Generic USB Webcam 1080p** | 2MP | ~70° | ❌ USB only | ₹800–1,500 | ❌ Only front 3 rows — not suitable |

---

### Summary of Camera Requirement

| Use Case | Minimum Spec | Recommended Spec |
|---|---|---|
| Classroom ≤ 7m deep, 30 students | 2MP 1080p, 90° FOV | 5MP, 100° FOV |
| **Classroom ~10m deep, 60 students** | **5MP, 100° FOV, Fixed Focus, RTSP** | **8MP / 4K, 105°–110° FOV, IR, RTSP** |
| Large hall > 10m, 100+ students | 8MP per zone (2 cameras) | 12MP or 2× 8MP cameras |

> [!CAUTION]
> Do **not** rely on a single 1080p camera for a full 60-student classroom. Back-row students will be systematically marked absent due to pixel count failure — the system will silently refuse to identify them rather than make a false guess. This is by design (IEC/ISO compliance) but the fix is hardware, not software.

---

## Summary

The core computer vision engine, cloud ledger, and voice pipeline are **production-ready**. The three biggest real-world usability gaps are:

1. **Teachers cannot identify themselves to the system** — no per-faculty login exists
2. **Teachers have no automatic way to see absent names** — only the Google Sheet (requires manual lookup)
3. **No subject/period awareness** — the same section cannot log attendance for multiple subjects in a single day without overwriting

On the **hardware side**, using a camera below 5MP in a 10m-deep classroom is a guaranteed failure point — back-row students will be silently excluded from identification by the IEC/ISO compliance gates. An 8MP/4K wide-angle RTSP camera is the recommended minimum for a full 60-student deployment.

Completing **Phase 1** (teacher summary email + post-attendance results panel + faculty assignment to cameras) would make this system **genuinely usable in a real college** with approximately 5–7 days of focused development.

---

*End of Gap Analysis Report*
*Next step: Review priorities above, confirm approved items, and proceed to Phase 1 implementation.*
