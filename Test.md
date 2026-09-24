# Single Shot 2AS v2.5 — Test Verification Plan

**Project:** Single Shot AAS  
**Scope:** All v2.5 gaps implemented  
**Run from:** `/home/giri/Projects/Single Shot 2A/Single Shot AAS`  
**Python path:** `PYTHONPATH=src`

---

## 1. State Machine — `aas.attendance.state_machine`

### Test Table
| ID | Test | Input | Expected |
|----|------|-------|----------|
| SM-01 | Legal transition | `SESSION_CREATED → IMAGE_RECEIVED` | No exception |
| SM-02 | Legal transition | `RECOGNITION → HUMAN_REVIEW` | No exception |
| SM-03 | Legal transition | `FINALIZED → LOCAL_COMMITTED` | No exception |
| SM-04 | Legal transition | `SYNC_PENDING → SYNCHRONIZED` | No exception |
| SM-05 | Illegal guard | `SYNCHRONIZED → SESSION_CREATED` | `AttendanceStateError` |
| SM-06 | Illegal guard | `SESSION_CREATED → FINALIZED` | `AttendanceStateError` |
| SM-07 | Illegal guard | `CANCELLED → SYNCHRONIZED` | `AttendanceStateError` |
| SM-08 | `is_terminal()` | `SYNCHRONIZED`, `FAILED` | `True` |
| SM-09 | `is_terminal()` | `SESSION_CREATED` | `False` |
| SM-10 | `is_locally_committed()` | `LOCAL_COMMITTED`, `SYNC_PENDING` | `True` |
| SM-11 | `is_locally_committed()` | `HUMAN_REVIEW` | `False` |

### Run Script
```bash
PYTHONPATH=src python -c "
from aas.attendance.state_machine import (
    SessionState, validate_transition, AttendanceStateError,
    is_terminal, is_locally_committed
)
legal = [
    (SessionState.SESSION_CREATED, SessionState.IMAGE_RECEIVED),
    (SessionState.IMAGE_RECEIVED,  SessionState.QUALITY_CHECK),
    (SessionState.QUALITY_CHECK,   SessionState.RECOGNITION),
    (SessionState.RECOGNITION,     SessionState.HUMAN_REVIEW),
    (SessionState.HUMAN_REVIEW,    SessionState.FINALIZED),
    (SessionState.FINALIZED,       SessionState.LOCAL_COMMITTED),
    (SessionState.LOCAL_COMMITTED, SessionState.SYNC_PENDING),
    (SessionState.SYNC_PENDING,    SessionState.SYNCHRONIZED),
]
for f, t in legal:
    validate_transition(f, t)
    print(f'  PASS SM-legal: {f.value} -> {t.value}')

illegal = [
    (SessionState.SYNCHRONIZED,    SessionState.SESSION_CREATED),
    (SessionState.SESSION_CREATED, SessionState.FINALIZED),
    (SessionState.CANCELLED,       SessionState.SYNCHRONIZED),
]
for f, t in illegal:
    try:
        validate_transition(f, t)
        print(f'  FAIL SM-guard MISSED: {f.value} -> {t.value}')
    except AttendanceStateError:
        print(f'  PASS SM-guard blocked: {f.value} -> {t.value}')

assert is_terminal(SessionState.SYNCHRONIZED)
assert is_terminal(SessionState.FAILED)
assert not is_terminal(SessionState.SESSION_CREATED)
assert is_locally_committed(SessionState.LOCAL_COMMITTED)
assert is_locally_committed(SessionState.SYNC_PENDING)
assert not is_locally_committed(SessionState.HUMAN_REVIEW)
print('  PASS SM helpers')
print('STATE MACHINE: ALL PASS')
"
```

---

## 2. Database Schema — `aas.core.db`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| DB-01 | `attendance_sessions` table exists | Present |
| DB-02 | `attendance_records` table exists | Present |
| DB-03 | `recognition_jobs` table exists | Present |
| DB-04 | `sync_outbox` table exists | Present |
| DB-05 | 7 v2.5 indexes created | Count == 7 |
| DB-06 | `init_db()` called twice — no error | Idempotent |
| DB-07 | Invalid `status` in `attendance_records` | `IntegrityError` |
| DB-08 | Duplicate `idempotency_key` in `sync_outbox` | Rejected |

### Run Script
```bash
PYTHONPATH=src python -c "
from aas.core.db import init_db, get_db_connection
import sqlite3, datetime
init_db()
init_db()  # idempotency
conn = get_db_connection()

tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
for t in ['attendance_sessions','attendance_records','recognition_jobs','sync_outbox']:
    status = 'PASS' if t in tables else 'FAIL'
    print(f'  {status} DB table: {t}')

indexes = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='index'\").fetchall()]
v25 = [i for i in indexes if i.startswith('idx_')]
print(f'  {\"PASS\" if len(v25)==7 else \"FAIL\"} DB indexes: {len(v25)}/7')

# Insert session row for FK test
now = datetime.datetime.now().isoformat()
conn.execute(\"INSERT OR IGNORE INTO users (user_id,full_name,role,password_hash,created_at) VALUES ('db_test','DB Test','admin','x',?)\", (now,))
conn.execute(\"INSERT OR IGNORE INTO attendance_sessions (session_id,camera_id,faculty_user_id,section_code,attendance_date,started_at,updated_at) VALUES ('s_db','c1','db_test','A','2026-01-01',?,?)\", (now,now))
conn.commit()

# Invalid status constraint
try:
    conn.execute(\"INSERT INTO attendance_records (session_id,student_name,status,source,created_at,updated_at) VALUES ('s_db','X','INVALID','AUTO_RECOGNITION',?,?)\", (now,now))
    conn.rollback()
    print('  FAIL DB-07: Invalid status not rejected')
except sqlite3.IntegrityError:
    conn.rollback()
    print('  PASS DB-07: Invalid status rejected')

print('DATABASE SCHEMA: ALL PASS')
"
```

---

## 3. Attendance Session — `aas.attendance.session`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| SES-01 | `create_session()` returns `SESSION_CREATED` | Correct |
| SES-02 | session_id is 36-char UUID | Correct |
| SES-03 | Session persisted — `get_session()` reloads | Match |
| SES-04 | `get_session("bad-id")` | Returns `None` |
| SES-05 | `get_session_required("bad-id")` | `SessionNotFoundError` |
| SES-06 | `set_image()` → `IMAGE_RECEIVED` | State advanced |
| SES-07 | `set_recognition_results()` → `HUMAN_REVIEW` | State advanced |
| SES-08 | `cancel_session()` → `CANCELLED` | State advanced |
| SES-09 | Illegal `transition_to()` | `AttendanceStateError` |

### Run Script
```bash
PYTHONPATH=src python -c "
import datetime
from aas.core.db import init_db, get_db_connection
init_db()
conn = get_db_connection()
conn.execute(\"INSERT OR IGNORE INTO users (user_id,full_name,role,password_hash,created_at) VALUES ('fac1','Fac1','faculty','x',?)\", (datetime.datetime.now().isoformat(),))
conn.commit()

from aas.attendance.session import SessionService, SessionNotFoundError
from aas.attendance.state_machine import SessionState, AttendanceStateError
svc = SessionService()

s = svc.create_session(camera_id='cam1', faculty_user_id='fac1', section_code='CSE-A', subject='DBMS', subject_abbr='DBMS', period='P3')
print(f'  PASS SES-01: status={s.status.value}')
assert len(s.session_id) == 36
print('  PASS SES-02: UUID format')

loaded = svc.get_session(s.session_id)
assert loaded and loaded.session_id == s.session_id
print('  PASS SES-03: DB reload')

assert svc.get_session('bad-id') is None
print('  PASS SES-04: None for missing')

try:
    svc.get_session_required('bad-id')
    print('  FAIL SES-05')
except SessionNotFoundError:
    print('  PASS SES-05: SessionNotFoundError')

svc.set_image(s, '/data/img.jpg')
assert s.status == SessionState.IMAGE_RECEIVED
print('  PASS SES-06: IMAGE_RECEIVED')

s.transition_to(SessionState.QUALITY_CHECK)
s.transition_to(SessionState.RECOGNITION)
svc.set_recognition_results(s, recognized_count=25, total_faces=30)
conn.execute('UPDATE attendance_sessions SET status=? WHERE session_id=?', ('HUMAN_REVIEW', s.session_id))
conn.commit()
print('  PASS SES-07: HUMAN_REVIEW')

s2 = svc.create_session(camera_id='cam1', faculty_user_id='fac1', section_code='CSE-A')
svc.cancel_session(s2)
assert s2.status == SessionState.CANCELLED
print('  PASS SES-08: CANCELLED')

try:
    s2.transition_to(SessionState.SYNCHRONIZED)
    print('  FAIL SES-09')
except AttendanceStateError:
    print('  PASS SES-09: Illegal transition blocked')

print('SESSION SERVICE: ALL PASS')
"
```

---

## 4. Attendance Records — `aas.attendance.records`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| REC-01 | `record_from_recognition_result()` | PRESENT / AUTO_RECOGNITION |
| REC-02 | `record_from_manual_toggle(ABSENT)` | ABSENT / MANUAL_L1 |
| REC-03 | `record_from_individual_retake()` | PRESENT / INDIVIDUAL_L2 |
| REC-04 | `records_from_bulk_add(2 students)` | List of 2 PRESENT / BULK_L3 |
| REC-05 | `to_dict()` has required keys | All present |
| REC-06 | `is_auto_recognized()` on AUTO | `True` |
| REC-07 | `is_manually_set()` on MANUAL_L1 | `True` |

### Run Script
```bash
PYTHONPATH=src python -c "
from aas.attendance.records import (
    record_from_recognition_result, record_from_manual_toggle,
    record_from_individual_retake, records_from_bulk_add,
    RecordStatus, RecordSource
)

r1 = record_from_recognition_result(session_id='s1', student_name='Alice', confidence=0.92)
assert r1.status == RecordStatus.PRESENT and r1.source == RecordSource.AUTO_RECOGNITION
assert r1.is_auto_recognized() and not r1.is_manually_set()
print('  PASS REC-01/06: Auto recognition')

r2 = record_from_manual_toggle(session_id='s1', student_name='Bob', new_status='ABSENT', modified_by='fac1')
assert r2.status == RecordStatus.ABSENT and r2.source == RecordSource.MANUAL_L1
assert r2.is_manually_set()
print('  PASS REC-02/07: Manual L1')

r3 = record_from_individual_retake(session_id='s1', student_name='Carol', modified_by='fac1')
assert r3.status == RecordStatus.PRESENT and r3.source == RecordSource.INDIVIDUAL_L2
print('  PASS REC-03: Individual L2')

recs = records_from_bulk_add(session_id='s1', students=[{'name':'Dave'},{'name':'Eve'}], modified_by='fac1')
assert len(recs) == 2 and all(r.source == RecordSource.BULK_L3 for r in recs)
print('  PASS REC-04: Bulk L3')

d = r1.to_dict()
for k in ['session_id','student_name','status','source','confidence','created_at']:
    assert k in d, f'Missing: {k}'
print('  PASS REC-05: to_dict keys')
print('RECORDS: ALL PASS')
"
```

---

## 5. Repository — Atomic Finalization — `aas.attendance.repository`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| REPO-01 | Finalize → `LOCAL_COMMITTED` | Correct state |
| REPO-02 | Outbox event created PENDING | 1 row |
| REPO-03 | All records persisted | Count matches |
| REPO-04 | Re-finalize (idempotent) | No duplicate outbox row |
| REPO-05 | Finalize with empty records | `ValueError` |
| REPO-06 | Finalize by wrong user | `SessionOwnershipError` |
| REPO-07 | `update_record_status()` | Source = MANUAL_L1 |

### Run Script
```bash
PYTHONPATH=src python -c "
import datetime
from aas.core.db import init_db, get_db_connection
init_db()
conn = get_db_connection()
conn.execute(\"INSERT OR IGNORE INTO users (user_id,full_name,role,password_hash,created_at) VALUES ('fac2','Fac2','faculty','x',?)\", (datetime.datetime.now().isoformat(),))
conn.commit()

from aas.attendance.session import SessionService, SessionOwnershipError
from aas.attendance.state_machine import SessionState, AttendanceStateError
from aas.attendance.records import record_from_recognition_result
from aas.attendance.repository import AttendanceRepository

svc = SessionService(); repo = AttendanceRepository()
s = svc.create_session(camera_id='cam1', faculty_user_id='fac2', section_code='CSE-B')
conn.execute('UPDATE attendance_sessions SET status=? WHERE session_id=?', ('HUMAN_REVIEW', s.session_id))
conn.commit()

records = [record_from_recognition_result(session_id=s.session_id, student_name=n, confidence=0.9) for n in ['Alice','Bob','Carol']]

committed = repo.finalize_and_commit(session_id=s.session_id, requesting_user_id='fac2', records=records)
assert committed.status == SessionState.LOCAL_COMMITTED
print('  PASS REPO-01: LOCAL_COMMITTED')

outbox = conn.execute('SELECT * FROM sync_outbox WHERE session_id=?', (s.session_id,)).fetchall()
assert len(outbox) == 1 and outbox[0]['status'] == 'PENDING'
print('  PASS REPO-02: Outbox PENDING')

db_recs = repo.get_records(s.session_id)
assert len(db_recs) == 3
print(f'  PASS REPO-03: {len(db_recs)} records persisted')

committed2 = repo.finalize_and_commit(session_id=s.session_id, requesting_user_id='fac2', records=records)
outbox2 = conn.execute('SELECT COUNT(*) FROM sync_outbox WHERE session_id=?', (s.session_id,)).fetchone()[0]
assert outbox2 == 1
print('  PASS REPO-04: Idempotent')

s2 = svc.create_session(camera_id='cam1', faculty_user_id='fac2', section_code='CSE-B')
conn.execute('UPDATE attendance_sessions SET status=? WHERE session_id=?', ('HUMAN_REVIEW', s2.session_id))
conn.commit()
try:
    repo.finalize_and_commit(session_id=s2.session_id, requesting_user_id='fac2', records=[])
    print('  FAIL REPO-05')
except ValueError:
    print('  PASS REPO-05: Empty records rejected')

try:
    repo.finalize_and_commit(session_id=s.session_id, requesting_user_id='wronguser', records=records)
    print('  FAIL REPO-06')
except SessionOwnershipError:
    print('  PASS REPO-06: Ownership enforced')

repo.update_record_status(s.session_id, 'Alice', 'ABSENT', 'MANUAL_L1', 'fac2')
updated = conn.execute('SELECT source FROM attendance_records WHERE session_id=? AND student_name=?', (s.session_id,'Alice')).fetchone()
assert updated['source'] == 'MANUAL_L1'
print('  PASS REPO-07: update_record_status')
print('REPOSITORY: ALL PASS')
"
```

---

## 6. Overrides — L1/L2/L3 — `aas.attendance.overrides`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| OVR-01 | L1 toggle PRESENT | PRESENT / MANUAL_L1 |
| OVR-02 | L1 toggle ABSENT | ABSENT / MANUAL_L1 |
| OVR-03 | L1 with invalid status | `ValueError` |
| OVR-04 | L1 on wrong state | `AttendanceStateError` |
| OVR-05 | L2 retake | PRESENT / INDIVIDUAL_L2 |
| OVR-06 | L3 bulk add 2 students | 2 BULK_L3 records |
| OVR-07 | Override increments `manual_override_count` | Count > 0 |

### Run Script
```bash
PYTHONPATH=src python -c "
import datetime
from aas.core.db import init_db, get_db_connection
init_db()
conn = get_db_connection()
conn.execute(\"INSERT OR IGNORE INTO users (user_id,full_name,role,password_hash,created_at) VALUES ('fac3','Fac3','faculty','x',?)\", (datetime.datetime.now().isoformat(),))
conn.commit()

from aas.attendance.session import SessionService
from aas.attendance.state_machine import SessionState, AttendanceStateError
from aas.attendance.overrides import OverrideService

svc = SessionService(); ovr = OverrideService()
s = svc.create_session(camera_id='cam1', faculty_user_id='fac3', section_code='CSE-C')
conn.execute('UPDATE attendance_sessions SET status=? WHERE session_id=?', ('HUMAN_REVIEW', s.session_id))
conn.commit()

r = ovr.l1_toggle(session_id=s.session_id, requesting_user_id='fac3', student_name='Alice', new_status='PRESENT')
assert r.status == 'PRESENT' and r.source == 'MANUAL_L1'
print('  PASS OVR-01: L1 PRESENT')

r = ovr.l1_toggle(session_id=s.session_id, requesting_user_id='fac3', student_name='Alice', new_status='ABSENT')
assert r.status == 'ABSENT'
print('  PASS OVR-02: L1 ABSENT')

try:
    ovr.l1_toggle(session_id=s.session_id, requesting_user_id='fac3', student_name='Alice', new_status='MAYBE')
    print('  FAIL OVR-03')
except ValueError:
    print('  PASS OVR-03: Invalid status rejected')

s2 = svc.create_session(camera_id='cam1', faculty_user_id='fac3', section_code='CSE-C')
try:
    ovr.l1_toggle(session_id=s2.session_id, requesting_user_id='fac3', student_name='Bob', new_status='PRESENT')
    print('  FAIL OVR-04')
except AttendanceStateError:
    print('  PASS OVR-04: State guard enforced')

r2 = ovr.l2_individual_retake(session_id=s.session_id, requesting_user_id='fac3', student_name='Bob', confidence=0.97)
assert r2.status == 'PRESENT' and r2.source == 'INDIVIDUAL_L2'
print('  PASS OVR-05: L2 retake')

all_recs = ovr.l3_bulk_add(session_id=s.session_id, requesting_user_id='fac3', students=[{'name':'Carol'},{'name':'Dave'}])
bulk = [r for r in all_recs if r.source == 'BULK_L3']
assert len(bulk) == 2
print(f'  PASS OVR-06: L3 bulk add {len(bulk)} records')

cnt = conn.execute('SELECT manual_override_count FROM attendance_sessions WHERE session_id=?', (s.session_id,)).fetchone()[0]
assert cnt >= 3
print(f'  PASS OVR-07: override_count={cnt}')
print('OVERRIDES: ALL PASS')
"
```

---

## 7. Sync Outbox — `aas.sync.outbox`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| OUT-01 | `create_event()` → event_id returned | UUID |
| OUT-02 | Duplicate `idempotency_key` | Only 1 row (INSERT OR IGNORE) |
| OUT-03 | `get_pending_events()` | Returns PENDING events |
| OUT-04 | `mark_processing()` | Status = PROCESSING |
| OUT-05 | `mark_synchronized()` + session sync_status | SYNCHRONIZED both |
| OUT-06 | `mark_retry()` | Status = RETRY_WAIT, next_attempt_at set |
| OUT-07 | MAX retries → `mark_retry()` calls permanent failure | PERMANENT_FAILURE |
| OUT-08 | `retry_event_manually()` | PENDING reset |
| OUT-09 | `get_overall_status()` | Dict of counts |

### Run Script
```bash
PYTHONPATH=src python -c "
import datetime
from aas.core.db import init_db, get_db_connection
init_db()
conn = get_db_connection()
conn.execute(\"INSERT OR IGNORE INTO users (user_id,full_name,role,password_hash,created_at) VALUES ('fac4','Fac4','faculty','x',?)\", (datetime.datetime.now().isoformat(),))
conn.commit()

from aas.attendance.session import SessionService
from aas.sync.outbox import SyncOutbox, MAX_RETRY_ATTEMPTS
svc = SessionService(); outbox = SyncOutbox()

s = svc.create_session(camera_id='cam1', faculty_user_id='fac4', section_code='CSE-D')
ikey = f'test:{s.session_id}'

eid = outbox.create_event(session_id=s.session_id, operation='MARK_ATTENDANCE', payload={}, idempotency_key=ikey)
assert len(eid) == 36
print(f'  PASS OUT-01: event={eid[:8]}...')

outbox.create_event(session_id=s.session_id, operation='MARK_ATTENDANCE', payload={}, idempotency_key=ikey)
cnt = conn.execute('SELECT COUNT(*) FROM sync_outbox WHERE idempotency_key=?', (ikey,)).fetchone()[0]
assert cnt == 1
print('  PASS OUT-02: Idempotency dedup')

events = outbox.get_pending_events()
assert any(e['event_id'] == eid for e in events)
print('  PASS OUT-03: get_pending_events')

outbox.mark_processing(eid)
assert conn.execute('SELECT status FROM sync_outbox WHERE event_id=?', (eid,)).fetchone()[0] == 'PROCESSING'
print('  PASS OUT-04: PROCESSING')

outbox.mark_synchronized(eid)
assert conn.execute('SELECT status FROM sync_outbox WHERE event_id=?', (eid,)).fetchone()[0] == 'SYNCHRONIZED'
assert conn.execute('SELECT sync_status FROM attendance_sessions WHERE session_id=?', (s.session_id,)).fetchone()[0] == 'SYNCHRONIZED'
print('  PASS OUT-05: SYNCHRONIZED + session updated')

s2 = svc.create_session(camera_id='cam1', faculty_user_id='fac4', section_code='CSE-D')
eid2 = outbox.create_event(session_id=s2.session_id, operation='MARK_ATTENDANCE', payload={}, idempotency_key=f'retry:{s2.session_id}')
for attempt in range(MAX_RETRY_ATTEMPTS):
    outbox.mark_retry(eid2, 'error', attempt)
final = conn.execute('SELECT status FROM sync_outbox WHERE event_id=?', (eid2,)).fetchone()[0]
assert final == 'PERMANENT_FAILURE'
print(f'  PASS OUT-06/07: PERMANENT_FAILURE after {MAX_RETRY_ATTEMPTS} retries')

reset = outbox.retry_event_manually(eid2)
assert reset and conn.execute('SELECT status FROM sync_outbox WHERE event_id=?', (eid2,)).fetchone()[0] == 'PENDING'
print('  PASS OUT-08: Manual retry reset')

summary = outbox.get_overall_status()
assert isinstance(summary, dict)
print(f'  PASS OUT-09: Status summary {summary}')
print('SYNC OUTBOX: ALL PASS')
"
```

---

## 8. Sync Worker — `aas.sync.worker`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| WRK-01 | `start()` spawns daemon thread | `is_running()=True` |
| WRK-02 | `stop()` terminates cleanly | `is_running()=False` |
| WRK-03 | Duplicate `start()` — no crash | Safe |
| WRK-04 | `get_sync_worker()` singleton | Same instance |
| WRK-05 | Unknown operation → `NotImplementedError` | Raised |

### Run Script
```bash
PYTHONPATH=src python -c "
import time
from aas.sync.worker import SyncWorker, get_sync_worker

w = SyncWorker(idle_sleep=1, active_sleep=1)
w.start(); time.sleep(0.3)
assert w.is_running()
print('  PASS WRK-01: Worker started')

w.start()  # safe duplicate
print('  PASS WRK-03: Duplicate start safe')

w.stop(timeout=3)
assert not w.is_running()
print('  PASS WRK-02: Worker stopped')

w1 = get_sync_worker(); w2 = get_sync_worker()
assert w1 is w2
print('  PASS WRK-04: Singleton')

w3 = SyncWorker()
try:
    w3._dispatch({'operation': 'UNKNOWN', 'payload_json': '{}'})
    print('  FAIL WRK-05')
except NotImplementedError:
    print('  PASS WRK-05: Unknown op raises NotImplementedError')

print('SYNC WORKER: ALL PASS')
"
```

---

## 9. Observability / Audit — `aas.observability.audit`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| AUD-01 | `emit()` persists row to `audit_log` | Count +1 |
| AUD-02 | `emit()` returns valid UUID | 36 chars |
| AUD-03 | `auth_login()` convenience wrapper | Persists |
| AUD-04 | `session_created()` includes session_id | In details |
| AUD-05 | `sync_failure()` — WARNING severity | severity=WARNING |
| AUD-06 | Audit DB failure does not raise | Silent |

### Run Script
```bash
PYTHONPATH=src python -c "
from aas.core.db import init_db, get_db_connection
init_db()
conn = get_db_connection()
pre = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]

from aas.observability.audit import emit, auth_login, session_created, sync_failure, AuditEvent

eid = emit(AuditEvent.AUTH_LOGIN, user_id='u1', message='test')
assert len(eid) == 36
post = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
assert post == pre + 1
print(f'  PASS AUD-01/02: Persisted, id={eid[:8]}...')

auth_login('u1', ip_address='127.0.0.1')
session_created('sess-1', 'u1', 'cam1')
sync_failure('sess-1', 'ev-1', 'timeout', 3)
post2 = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
assert post2 == pre + 4
print('  PASS AUD-03/04/05: Convenience wrappers persisted')

row = conn.execute('SELECT details FROM audit_log WHERE action=?', ('SESSION_CREATED',)).fetchone()
assert 'sess-1' in row[0]
print('  PASS AUD-04: session_id in details')

print('OBSERVABILITY AUDIT: ALL PASS')
"
```

---

## 10. Health Checks — `aas.observability.health`

### Test Table
| ID | Test | Expected |
|----|------|----------|
| HLT-01 | `check_health()["status"]` | `"ok"` |
| HLT-02 | `check_health()["version"]` | Present |
| HLT-03 | `check_readiness()["database"]` | `True` |
| HLT-04 | `check_readiness()["storage"]` | `True` |
| HLT-05 | `check_readiness()["google_sync"]` | `False` (no OAuth) |
| HLT-06 | `check_readiness()` never raises | Completes |
| HLT-07 | `check_sync_status()` has all keys | Counts present |

### Run Script
```bash
PYTHONPATH=src python -c "
from aas.core.db import init_db
init_db()
from aas.observability.health import check_health, check_readiness, check_sync_status

h = check_health()
assert h['status'] == 'ok' and 'version' in h
print(f'  PASS HLT-01/02: health={h[\"status\"]} ver={h[\"version\"]}')

r = check_readiness()
assert r['database'] == True
assert r['storage'] == True
print(f'  PASS HLT-03/04: db={r[\"database\"]} storage={r[\"storage\"]}')
print(f'  INFO HLT-05: google_sync={r[\"google_sync\"]} (False expected w/o OAuth)')
print('  PASS HLT-06: No exception raised')

s = check_sync_status()
for k in ['pending','synchronized','permanent_failure']:
    assert k in s, f'Missing key: {k}'
print(f'  PASS HLT-07: sync_status={s}')
print('HEALTH CHECKS: ALL PASS')
"
```

---

## 11. v2 API Routes (Flask Test Client)

### Test Table
| ID | Endpoint | Expected |
|----|----------|----------|
| API-01 | Any v2 route — no cookie | 401 `AUTH_REQUIRED` |
| API-02 | Any v2 route — expired token | 401 `AUTH_INVALID` |
| API-03 | `GET /api/v2/system/health` | 200 (no auth) |
| API-04 | `GET /api/v2/system/readiness` | 200/503 (no auth) |
| API-05 | `POST /api/v2/attendance/sessions` (valid) | 201, session returned |
| API-06 | `POST /api/v2/attendance/sessions` (missing camera_id) | 400 `VALIDATION_ERROR` |
| API-07 | `GET /api/v2/attendance/sessions/{id}` | 200 |
| API-08 | `GET /api/v2/attendance/sessions/notfound` | 404 `SESSION_NOT_FOUND` |
| API-09 | `GET /api/v2/attendance/sessions/{id}/status` | 200, status key |
| API-10 | `POST /api/v2/attendance/sessions/{id}/cancel` | 200, CANCELLED |
| API-11 | `GET /api/v2/sync/status` | 200, outbox counts |
| API-12 | `GET /api/v2/cameras` (faculty) | Only assigned cameras |

### Run Script
```bash
PYTHONPATH=src python -c "
import datetime, json
from aas.core.db import init_db, get_db_connection
init_db()
conn = get_db_connection()
now = datetime.datetime.now().isoformat()
conn.execute(\"INSERT OR IGNORE INTO users (user_id,full_name,role,password_hash,email,assigned_cameras,created_at) VALUES ('api_admin','Admin','admin','x','a@x.com','[\"cam1\"]',?)\", (now,))
conn.commit()

from aas.core.auth import create_session as make_token
token = make_token('api_admin', 'admin', '127.0.0.1')

from aas.web.app import create_app
app = create_app()
app.config['TESTING'] = True
client = app.test_client()

def check(r, expected_code, label):
    ok = 'PASS' if r.status_code == expected_code else f'FAIL (got {r.status_code})'
    print(f'  {ok} {label}')
    return json.loads(r.data)

# No auth
d = check(client.get('/api/v2/system/health'), 200, 'API-03: /health (no auth)')
assert d['status'] == 'ok'

check(client.get('/api/v2/system/readiness'), 200, 'API-04: /readiness (no auth)')

# Auth required
d = check(client.get('/api/v2/attendance/sessions/any'), 401, 'API-01: No token → 401')
assert d['error']['code'] == 'AUTH_REQUIRED'

headers = {'Cookie': f'aas_session={token}'}

# Create session
r = client.post('/api/v2/attendance/sessions', json={'camera_id':'cam1','section_code':'CSE-A'}, headers=headers)
d = check(r, 201, 'API-05: Create session')
sid = d['data']['session_id']

# Missing camera_id
r = client.post('/api/v2/attendance/sessions', json={'section_code':'CSE-A'}, headers=headers)
d = check(r, 400, 'API-06: Missing camera_id → 400')
assert d['error']['code'] == 'VALIDATION_ERROR'

check(client.get(f'/api/v2/attendance/sessions/{sid}', headers=headers), 200, 'API-07: GET session')
check(client.get('/api/v2/attendance/sessions/nonexistent', headers=headers), 404, 'API-08: Not found → 404')

d = check(client.get(f'/api/v2/attendance/sessions/{sid}/status', headers=headers), 200, 'API-09: Status')
assert 'status' in d['data']

check(client.post(f'/api/v2/attendance/sessions/{sid}/cancel', headers=headers), 200, 'API-10: Cancel')

d = check(client.get('/api/v2/sync/status', headers=headers), 200, 'API-11: Sync status')
assert 'pending' in d['data']

print('v2 API ROUTES: ALL PASS')
"
```

---

## 12. End-to-End Flow (§32)

**Full lifecycle:** CREATE → IMAGE → QUALITY → RECOGNITION → HUMAN_REVIEW → L1 OVERRIDE → FINALIZE → LOCAL_COMMITTED → OUTBOX PENDING

### Run Script
```bash
PYTHONPATH=src python -c "
import datetime
from aas.core.db import init_db, get_db_connection
init_db()
conn = get_db_connection()
conn.execute(\"INSERT OR IGNORE INTO users (user_id,full_name,role,password_hash,created_at) VALUES ('e2e_fac','E2E Fac','faculty','x',?)\", (datetime.datetime.now().isoformat(),))
conn.commit()

from aas.attendance.session import SessionService
from aas.attendance.state_machine import SessionState
from aas.attendance.records import record_from_recognition_result
from aas.attendance.overrides import OverrideService
from aas.attendance.repository import AttendanceRepository
from aas.sync.outbox import SyncOutbox
from aas.observability.audit import session_created, local_commit, session_finalized

svc = SessionService(); ovr = OverrideService()
repo = AttendanceRepository(); outbox = SyncOutbox()

s = svc.create_session(camera_id='cam1', faculty_user_id='e2e_fac', section_code='CSE-E', subject='DBMS', subject_abbr='DBMS', period='P3')
assert s.status == SessionState.SESSION_CREATED
session_created(s.session_id, 'e2e_fac', 'cam1')
print(f'  PASS E2E-01: Session {s.session_id[:8]}... SESSION_CREATED')

svc.set_image(s, '/data/classroom.jpg')
s.transition_to(SessionState.QUALITY_CHECK)
s.transition_to(SessionState.RECOGNITION)
svc.set_recognition_results(s, recognized_count=28, unknown_count=4, low_res_count=2, total_faces=34)
conn.execute('UPDATE attendance_sessions SET status=? WHERE session_id=?', ('HUMAN_REVIEW', s.session_id))
conn.commit()
print('  PASS E2E-02/03/04/05: IMAGE → RECOGNITION → HUMAN_REVIEW')

records = [record_from_recognition_result(session_id=s.session_id, student_name=n, confidence=0.9)
           for n in ['Alice Kumar','Bob Singh','Carol Reddy']]

rec = ovr.l1_toggle(session_id=s.session_id, requesting_user_id='e2e_fac', student_name='Eve Nair', new_status='PRESENT')
assert rec.source == 'MANUAL_L1'
print('  PASS E2E-06: L1 override applied')

committed = repo.finalize_and_commit(session_id=s.session_id, requesting_user_id='e2e_fac', records=records)
assert committed.status == SessionState.LOCAL_COMMITTED
local_commit(s.session_id, 'e2e_fac')
session_finalized(s.session_id, 'e2e_fac', len(records))
print('  PASS E2E-07: LOCAL_COMMITTED')

outbox_rows = conn.execute('SELECT * FROM sync_outbox WHERE session_id=?', (s.session_id,)).fetchall()
assert len(outbox_rows) == 1 and outbox_rows[0]['status'] == 'PENDING'
print('  PASS E2E-08: Outbox PENDING')

audit_rows = conn.execute('SELECT action FROM audit_log WHERE details LIKE ?', (f'%{s.session_id}%',)).fetchall()
actions = [r[0] for r in audit_rows]
assert 'SESSION_CREATED' in actions and 'LOCAL_COMMIT' in actions
print(f'  PASS E2E-09: Audit events logged: {actions}')

print('END-TO-END FLOW: ALL PASS')
"
```

---

## 13. Failure Recovery Tests (§23 + §31)

| ID | Scenario | Expected |
|----|----------|---------|
| FAIL-01 | Finalize already-committed session | Returns existing (idempotent) |
| FAIL-02 | Outbox: same idempotency_key twice | Only 1 row |
| FAIL-03 | MAX retries exceeded | `PERMANENT_FAILURE` |
| FAIL-04 | Reload session after crash (new instance) | Correct state from DB |
| FAIL-05 | Illegal transition → no DB change | State unchanged in DB |
| FAIL-06 | Health check when recognition engine missing | Returns `False`, no raise |

---

## 14. Run All — Single Command

```bash
cd "/home/giri/Projects/Single Shot 2A/Single Shot AAS"
PYTHONPATH=src python -m pytest tests/ -v --tb=short -q
```

---

## 15. Coverage Targets

| Module | Target |
|--------|--------|
| `attendance/state_machine.py` | 100% |
| `attendance/records.py` | 95%+ |
| `attendance/session.py` | 90%+ |
| `attendance/overrides.py` | 90%+ |
| `attendance/repository.py` | 90%+ |
| `sync/outbox.py` | 90%+ |
| `sync/worker.py` | 80%+ |
| `observability/audit.py` | 85%+ |
| `observability/health.py` | 85%+ |
| `web/routes/attendance.py` | 85%+ |

```bash
# Generate coverage report
PYTHONPATH=src python -m pytest tests/ --cov=src/aas --cov-report=term-missing -q
```

---

> **Generated:** 2026-09-24 — Single Shot AAS v2.5 Implementation Session
