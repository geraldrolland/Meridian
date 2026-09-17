#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end test script for the MERIDIAN platform.

Covers: invalid route, register, login, refresh, /me, upload video,
MinIO bucket notification, DB verification, outbox event, logout.

Usage:
    python e2e_test.py
"""

import hashlib
import hmac
import json
import sys
import time
from urllib.parse import quote
from io import BytesIO

import psycopg2
import requests

# Ensure stdout uses UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

API_GATEWAY = "http://localhost:3001"
VIDEO_SERVICE = "http://localhost:8000"
MINIO_ENDPOINT = "http://localhost:9000"
PROXY_SECRET = "test-proxy-secret"
DB_DSN = "host=localhost port=5434 dbname=video_db user=postgres password=postgres"


def _proxy_sign(method: str, path: str, secret: str = PROXY_SECRET) -> dict[str, str]:
    """Generate HMAC-SHA256 proxy signature headers."""
    timestamp = str(int(time.time() * 1000))
    payload = f"{method}:{path}:{timestamp}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {
        "x-proxy-signature": signature,
        "x-proxy-timestamp": timestamp,
    }


def _session_cookie(user_id: int, email: str, role: str = "user") -> str:
    """Build URI-encoded session cookie value."""
    data = {"userId": user_id, "role": role, "email": email}
    return f"session={quote(json.dumps(data))}"


def _parse_cookies(response: requests.Response) -> dict[str, str]:
    """Extract cookies from a response into a dict."""
    return {name: value for name, value in response.cookies.items()}


def _assert(condition: bool, msg: str):
    if not condition:
        raise AssertionError(msg)
    print(f"  PASS: {msg}")


# ── Step 1: Invalid route ──────────────────────────────────────────
# /health is excluded from auth; /health/nonexistent has no upstream match → 404
print("\n[1] GET /health/nonexistent → expect 404")
r = requests.get(f"{API_GATEWAY}/health/nonexistent")
_assert(r.status_code == 404, f"status=404 (got {r.status_code})")


# ── Step 2: Register ──────────────────────────────────────────────
print("\n[2] POST /api/auth/register → expect 201")
TEST_EMAIL = f"e2e_{int(time.time())}@test.com"
TEST_PASSWORD = "test123456"
r = requests.post(
    f"{API_GATEWAY}/api/auth/register",
    json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
)
_assert(r.status_code == 201, f"status=201 (got {r.status_code})")
user_id = r.json()["user"]["id"]
_assert(isinstance(user_id, int), f"user_id is int (got {type(user_id)})")
print(f"  Registered user_id={user_id}")


# ── Step 3: Login ─────────────────────────────────────────────────
print("\n[3] POST /api/auth/login → expect 200 + accessToken + refresh cookie")
r = requests.post(
    f"{API_GATEWAY}/api/auth/login",
    json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
)
_assert(r.status_code == 200, f"status=200 (got {r.status_code})")
login_data = r.json()
_assert("accessToken" in login_data, "response contains accessToken")
_assert(login_data["user"]["email"] == TEST_EMAIL, "returned email matches")
cookies = _parse_cookies(r)
_assert("refresh" in cookies, "refresh cookie set")
access_token = login_data["accessToken"]
print(f"  Logged in, accessToken={access_token[:20]}...")


# ── Step 4: Refresh token ─────────────────────────────────────────
print("\n[4] POST /api/auth/refresh-token → expect 200 + new accessToken")
r = requests.post(
    f"{API_GATEWAY}/api/auth/refresh-token",
    cookies={"refresh": cookies["refresh"]},
)
_assert(r.status_code == 200, f"status=200 (got {r.status_code})")
refresh_data = r.json()
_assert("accessToken" in refresh_data, "response contains accessToken")
_assert(refresh_data["accessToken"] != access_token, "new accessToken differs from old")
access_token = refresh_data["accessToken"]
new_cookies = _parse_cookies(r)
_assert("refresh" in new_cookies, "new refresh cookie set")
print(f"  Refreshed, new accessToken={access_token[:20]}...")


# ── Step 5: /me profile ───────────────────────────────────────────
print("\n[5] GET /api/auth/me → expect 200")
r = requests.get(
    f"{API_GATEWAY}/api/auth/me",
    headers={"Authorization": f"Bearer {access_token}"},
)
_assert(r.status_code == 200, f"status=200 (got {r.status_code})")
me_data = r.json()
_assert(me_data["user"]["email"] == TEST_EMAIL, "email matches")
_assert(me_data["user"]["id"] == user_id, "user_id matches")
print(f"  Profile: {me_data['user']}")


# ── Step 6: Upload video record ───────────────────────────────────
print("\n[6] POST /api/video/upload → expect 201 + presigned POST data")
VIDEO_FILENAME = f"test_video_{int(time.time())}.mp4"
VIDEO_CONTENT = b"\x00" * 1024  # 1 KB dummy video
sign_headers = _proxy_sign("POST", "/api/video/upload")
session_cookie = _session_cookie(user_id, TEST_EMAIL)

r = requests.post(
    f"{VIDEO_SERVICE}/api/video/upload",
    json={"filename": VIDEO_FILENAME, "content_type": "video/mp4", "file_size": len(VIDEO_CONTENT)},
    headers={
        **sign_headers,
        "Cookie": session_cookie,
        "Content-Type": "application/json",
    },
)
_assert(r.status_code == 201, f"status=201 (got {r.status_code})")
upload_data = r.json()
video_id = upload_data["id"]
upload_info = upload_data["upload"]
upload_url = upload_info["url"].replace("http://minio:9000", MINIO_ENDPOINT)
upload_fields = upload_info["fields"]
_assert(upload_url is not None, "upload url is not None")
_assert(upload_fields is not None, "upload fields is not None")
_assert(upload_data["user_id"] == user_id, f"user_id matches (got {upload_data.get('user_id')})")
print(f"  Created video id={video_id}, upload_url={upload_url[:80]}...")
print(f"  Fields: {list(upload_fields.keys())}")


# ── Step 7: Upload file to MinIO via presigned POST ────────────────
print("\n[7] Upload to MinIO via presigned POST")
data = upload_fields.copy()
data["Content-Type"] = "video/mp4"
files = {"file": (VIDEO_FILENAME, BytesIO(VIDEO_CONTENT), "video/mp4")}
r = requests.post(upload_url, data=data, files=files)
_assert(r.status_code in (200, 204), f"MinIO upload status 200/204 (got {r.status_code})")
print(f"  Uploaded {len(VIDEO_CONTENT)} bytes to MinIO")


# ── Step 7b: Reject non-video extension ────────────────────────────
print("\n[7b] POST /api/video/upload with .txt extension → expect 422")
sign_headers = _proxy_sign("POST", "/api/video/upload")
r = requests.post(
    f"{VIDEO_SERVICE}/api/video/upload",
    json={"filename": "malicious.txt", "content_type": "text/plain"},
    headers={
        **sign_headers,
        "Cookie": session_cookie,
        "Content-Type": "application/json",
    },
)
_assert(r.status_code == 422, f"status=422 for .txt (got {r.status_code})")
_assert("not allowed" in r.text, "rejection message mentions 'not allowed'")


# ── Step 8: Poll video-db for bucket notification ──────────────────
print("\n[8] Poll bucket_notification_events → expect row within 20s")
conn = psycopg2.connect(DB_DSN)
conn.autocommit = True
cur = conn.cursor()

notification_found = False
for _ in range(20):
    cur.execute("SELECT id, status FROM bucket_notification_events LIMIT 1")
    row = cur.fetchone()
    if row:
        notification_found = True
        print(f"  Found notification id={row[0]}, status={row[1]}")
        break
    time.sleep(1)
cur.close()
_assert(notification_found, "bucket_notification_events row exists")


# ── Step 9: Poll video for QUEUED status + size ───────────────────
print("\n[9] Poll videos table → expect status=QUEUED + size set within 20s")
cur = conn.cursor()
video_updated = False
for _ in range(20):
    cur.execute("SELECT status, size FROM videos WHERE id = %s", (video_id,))
    row = cur.fetchone()
    if row and row[0] == "QUEUED" and row[1] is not None:
        video_updated = True
        print(f"  Video status={row[0]}, size={row[1]}")
        break
    time.sleep(1)
cur.close()
_assert(video_updated, "video status=QUEUED and size is set")


# ── Step 10: Poll outbox for event ─────────────────────────────────
print("\n[10] Poll outbox → expect row within 20s")
cur = conn.cursor()
outbox_found = False
for _ in range(20):
    cur.execute("SELECT id, topic, status FROM outbox LIMIT 1")
    row = cur.fetchone()
    if row:
        outbox_found = True
        print(f"  Found outbox id={row[0]}, topic={row[1]}, status={row[2]}")
        break
    time.sleep(1)
cur.close()
_assert(outbox_found, "outbox row exists")
conn.close()


# ── Step 11: Logout ───────────────────────────────────────────────
print("\n[11] POST /api/auth/logout → expect 200")
r = requests.post(
    f"{API_GATEWAY}/api/auth/logout",
    headers={"Authorization": f"Bearer {access_token}"},
)
_assert(r.status_code == 200, f"status=200 (got {r.status_code})")
_assert(r.json().get("message") == "Logged out successfully", "logout message")


# ── Done ───────────────────────────────────────────────────────────
print("\n" + "=" * 50)
print("ALL E2E TESTS PASSED")
print("=" * 50)
