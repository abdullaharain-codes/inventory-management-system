"""
End-to-end verification of SSE notification stream.
Uses real auth, real DB, real broadcaster — no mocks.
"""
import sys, os, time, json, threading, datetime

sys.path.insert(0, os.path.dirname(__file__))

import requests

BASE = "http://127.0.0.1:5000"
ADMIN_EMAIL = "admin@test.com"
ADMIN_PASS  = "Admin@123"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []

def log(tag, msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"  [{ts}] {tag}: {msg}")

def record(name, passed, detail=""):
    status = PASS if passed else FAIL
    results.append((name, passed, detail))
    print(f"\n  >> [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return passed


# ── 0. Ensure server is up ───────────────────────────────────────
print("\n" + "="*60)
print("  SSE NOTIFICATION STREAM — END-TO-END TEST")
print("="*60)

print("\n[Step 0] Checking server is up ...")
try:
    r = requests.get(f"{BASE}/", timeout=3, allow_redirects=False)
    log("server", f"status={r.status_code}")
except Exception as e:
    print(f"  FATAL: Server not reachable at {BASE} — {e}")
    print("  Start the Flask server first:  python app.py")
    sys.exit(1)


# ── 1. Login with real credentials ───────────────────────────────
print("\n[Step 1] Logging in via POST /api/auth/login ...")
session = requests.Session()
login_resp = session.post(f"{BASE}/api/auth/login", json={
    "email": ADMIN_EMAIL,
    "password": ADMIN_PASS,
}, timeout=5)
log("login", f"status={login_resp.status_code}  body={login_resp.text[:200]}")

logged_in = login_resp.status_code == 200
if not logged_in:
    print("  FATAL: Login failed. Cannot continue.")
    sys.exit(1)

# Verify /api/auth/me works with the session
me = session.get(f"{BASE}/api/auth/me", timeout=5)
log("auth/me", f"status={me.status_code}  body={me.text[:200]}")
user = me.json()
ADMIN_USER_ID = user.get("user_id")
ADMIN_ROLE    = user.get("role")
log("auth/me", f"user_id={ADMIN_USER_ID}  role={ADMIN_ROLE}")
record("Login and session cookie", logged_in and me.status_code == 200)


# ── Shared state for background stream thread ────────────────────
stream_events   = []   # (ts, event_dict)
stream_log      = []   # (ts, raw_line)
stream_error    = [None]
stream_done     = threading.Event()
disconnect_done = threading.Event()
subscriber_before = [None]
subscriber_after  = [None]


def background_stream(url, stop_after_sec):
    """Open SSE stream in a background thread, collect events for stop_after_sec."""
    ts_start = time.time()
    try:
        log("stream-thread", f"Opening stream: {url}")
        resp = session.get(url, stream=True, timeout=(5, stop_after_sec + 5))
        log("stream-thread", f"Connected  status={resp.status_code}")

        buffer = ""
        for raw_line in resp.iter_lines(decode_unicode=True):
            elapsed = time.time() - ts_start
            if elapsed > stop_after_sec:
                log("stream-thread", f"Time limit ({stop_after_sec}s) reached — closing")
                break
            log("stream-thread", f"RAW [{elapsed:.2f}s]: {raw_line!r}")
            stream_log.append((elapsed, raw_line))

            if raw_line == "":
                # blank line = end of event block
                if buffer.strip():
                    for bline in buffer.split("\n"):
                        if bline.startswith("data: "):
                            try:
                                payload = json.loads(bline[6:])
                                elapsed2 = time.time() - ts_start
                                stream_events.append((elapsed2, payload))
                                log("stream-thread", f"EVENT [{elapsed2:.2f}s]: {payload.get('title','?')}")
                            except json.JSONDecodeError:
                                pass
                buffer = ""
            else:
                buffer += raw_line + "\n"

        resp.close()
        log("stream-thread", "Connection closed cleanly")
    except Exception as e:
        stream_error[0] = str(e)
        log("stream-thread", f"Exception: {e}")
    finally:
        stream_done.set()
        disconnect_done.set()


# ── 2 + 3. Open stream, wait 3s, create notification ────────────
print("\n[Step 2] Opening SSE stream in background thread ...")
stream_url = f"{BASE}/api/notifications/stream"
t = threading.Thread(target=background_stream, args=(stream_url, 12), daemon=True)
t.start()

time.sleep(1)
log("main", "Stream thread started, sleeping 3s before creating notification ...")
time.sleep(3)

# Capture broadcaster subscriber count BEFORE creating notification
from utils.notification_broadcaster import _subscribers, _lock
with _lock:
    subscriber_before[0] = len(_subscribers)
log("main", f"Subscribers in broadcaster BEFORE create: {subscriber_before[0]}")

print("\n[Step 3] Creating notification via create_notification() ...")
from utils.notifier import create_notification
create_ts = time.time()
create_notification(
    title="E2E Test Notification",
    message="This is an automated test of the SSE notification stream.",
    notification_type="product_added",
    target_role="all",
    related_id=99999,
    related_type="product",
)
log("main", f"create_notification() returned at {time.time() - create_ts:.2f}s after start")

# Wait for stream thread to finish
stream_done.wait(timeout=10)
log("main", "Stream thread finished")


# ── 4. Validate results ─────────────────────────────────────────
print("\n[Step 4] Validating results ...")

# Filter to real data events (skip heartbeat comments)
data_events = [e for e in stream_events if e[1].get("notification_id") is not None]
test_events = [e for e in data_events if e[1].get("title") == "E2E Test Notification"]

received = len(test_events) > 0
latency = test_events[0][0] if test_events else None

if received:
    record("Notification received via SSE", True, f"latency={latency:.2f}s")
    fast = latency is not None and latency < 3.0
    record("Delivery latency < 3s (push, not heartbeat)", fast, f"latency={latency:.2f}s")
else:
    record("Notification received via SSE", False,
           f"got {len(data_events)} data events, 0 matched test")
    record("Delivery latency < 3s", False, "no event received")

# Verify fields
if test_events:
    evt = test_events[0][1]
    fields_ok = all(k in evt for k in ["notification_id", "title", "message", "notification_type", "target_role"])
    record("Event payload has all expected fields", fields_ok, str(list(evt.keys())))


# ── 5. Check disconnect cleanup ─────────────────────────────────
print("\n[Step 5] Checking disconnect cleanup ...")
disconnect_done.wait(timeout=5)
time.sleep(0.5)

with _lock:
    subscriber_after[0] = len(_subscribers)

log("main", f"Subscribers in broadcaster AFTER disconnect: {subscriber_after[0]}")
cleaned = subscriber_after[0] < subscriber_before[0] or subscriber_after[0] == 0
record("Subscriber removed from broadcaster after disconnect",
       cleaned,
       f"before={subscriber_before[0]}  after={subscriber_after[0]}")


# ── 6. Catch-up test ────────────────────────────────────────────
print("\n[Step 6] Testing catch-up ...")
log("main", "Creating 3 notifications while NO stream is connected ...")
time.sleep(0.3)

catch_ids = []
for i in range(3):
    create_notification(
        title=f"CatchUp-{i+1}",
        message=f"Catch-up test notification #{i+1}",
        notification_type="general",
        target_role="all",
    )
    time.sleep(0.15)

log("main", "Sleeping 1s to let DB commits settle ...")
time.sleep(1)

# Query DB to find the IDs of those notifications
from db.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute("""
    SELECT notification_id, title FROM notifications
    WHERE title LIKE 'CatchUp-%'
    ORDER BY notification_id DESC LIMIT 3
""")
rows = cur.fetchall()
cur.close()
conn.close()

if rows:
    rows.reverse()
    catch_ids = [r['notification_id'] for r in rows]
    log("main", f"Created catch-up notifications with IDs: {catch_ids}")
    last_id = catch_ids[0] - 1  # request catch-up from just before these
    log("main", f"Opening stream with ?last_id={last_id}")
else:
    log("main", "WARNING: Could not find CatchUp notifications in DB")
    last_id = 0

# Open a fresh session for catch-up (separate from the first stream)
catchup_session = requests.Session()
catchup_session.post(f"{BASE}/api/auth/login", json={
    "email": ADMIN_EMAIL, "password": ADMIN_PASS
}, timeout=5)

catchup_events = []
catchup_log    = []
catchup_error  = [None]

def catchup_stream(url):
    try:
        resp = catchup_session.get(url, stream=True, timeout=(5, 10))
        log("catchup-thread", f"Connected  status={resp.status_code}")
        buffer = ""
        for raw_line in resp.iter_lines(decode_unicode=True):
            catchup_log.append(raw_line)
            log("catchup-thread", f"RAW: {raw_line!r}")
            if raw_line == "":
                if buffer.strip():
                    for bline in buffer.split("\n"):
                        if bline.startswith("data: "):
                            try:
                                payload = json.loads(bline[6:])
                                catchup_events.append(payload)
                                log("catchup-thread", f"EVENT: id={payload.get('notification_id')} title={payload.get('title')}")
                            except json.JSONDecodeError:
                                pass
                buffer = ""
            else:
                buffer += raw_line + "\n"
        resp.close()
    except Exception as e:
        catchup_error[0] = str(e)
        log("catchup-thread", f"Exception: {e}")

ct = threading.Thread(target=catchup_stream,
                      args=(f"{BASE}/api/notifications/stream?last_id={last_id}"),
                      daemon=True)
ct.start()
ct.join(timeout=8)

catchup_test_events = [e for e in catchup_events if e.get('title', '').startswith('CatchUp-')]
log("main", f"Catch-up events received: {len(catchup_test_events)} (expected 3)")
all_received = len(catchup_test_events) == 3
record("Catch-up: all 3 notifications received", all_received,
       f"got {len(catchup_test_events)} of 3")

if all_received:
    received_ids = [e['notification_id'] for e in catchup_test_events]
    ids_match = received_ids == catch_ids
    record("Catch-up: correct notification IDs in order", ids_match,
           f"expected={catch_ids}  got={received_ids}")


# ── Summary ──────────────────────────────────────────────────────
print("\n" + "="*60)
print("  RESULTS SUMMARY")
print("="*60)
all_pass = True
for name, passed, detail in results:
    icon = "✅" if passed else "❌"
    line = f"  {icon} {name}"
    if detail:
        line += f"  —  {detail}"
    print(line)
    if not passed:
        all_pass = False

print()
if all_pass:
    print("  ALL TESTS PASSED ✅")
else:
    print("  SOME TESTS FAILED ❌")
print("="*60 + "\n")
