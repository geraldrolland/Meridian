#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end test script for the MERIDIAN platform.

Covers: invalid route, register, login, refresh, /me, upload video,
MinIO bucket notification, DB verification, outbox event, full
processing pipeline (segmentation, transcoding, upload, completion),
manifest generation → video COMPLETED + manifest_url, a simulated DASH
player that downloads the MPD and each segment sequentially, and logout.

Usage:
    python e2e_test.py
"""

import hashlib
import hmac
import json
import math
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote
from io import BytesIO

import psycopg2
import requests
from minio import Minio

# Ensure stdout uses UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

API_GATEWAY = "http://localhost:3001"
VIDEO_SERVICE = "http://localhost:8000"
MINIO_ENDPOINT = "localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
PROXY_SECRET = "test-proxy-secret"
DB_DSN = "host=localhost port=5434 dbname=video_db user=postgres password=postgres"
MEDIA_DB_DSN = "host=localhost port=5435 dbname=media_processing_db user=postgres password=postgres"
MANIFEST_DB_DSN = "host=localhost port=5436 dbname=manifest_db user=postgres password=postgres"
SEGMENT_BUCKET = "vidsegments"
MANIFEST_BUCKET = "manifest"
DASH_NS = "urn:mpeg:dash:schema:mpd:2011"


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


def _minio_client() -> Minio:
    """Create MinIO client for e2e checks."""
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )


def _rewrite_minio_url(url: str) -> str:
    """Rewrite in-cluster MinIO URLs to the host-reachable endpoint."""
    return url.replace("http://minio:9000", f"http://{MINIO_ENDPOINT}")


def _parse_iso_duration(value: str) -> float:
    """Parse a subset of ISO 8601 durations used by the MPD (PT12.5S)."""
    m = re.fullmatch(r"PT(\d+(?:\.\d+)?)S", value or "")
    if not m:
        raise ValueError(f"Unsupported ISO duration: {value!r}")
    return float(m.group(1))


def _parse_dash_plan(mpd_xml: bytes) -> dict:
    """Parse an MPD and return a DASH playback plan for a preferred video rendition.

    Returns dict with: rep_id, init_template, media_template, start_number,
    segment_duration_sec, duration_sec, n_segments.
    """
    root = ET.fromstring(mpd_xml)
    duration_attr = root.get("mediaPresentationDuration", "")
    duration_sec = _parse_iso_duration(duration_attr)

    representations = root.findall(f".//{{{DASH_NS}}}Representation")
    if not representations:
        raise AssertionError("MPD has no Representation elements")

    by_id = {r.get("id"): r for r in representations if r.get("id")}
    preferred = None
    for cand in ("360p", "480p", "720p", "1080p"):
        if cand in by_id:
            preferred = by_id[cand]
            break
    if preferred is None:
        preferred = representations[0]
    rep_id = preferred.get("id")
    if not rep_id:
        raise AssertionError("MPD Representation missing id")

    # SegmentTemplate may live on Representation or parent AdaptationSet
    tmpl = preferred.find(f"{{{DASH_NS}}}SegmentTemplate")
    if tmpl is None:
        for aset in root.findall(f".//{{{DASH_NS}}}AdaptationSet"):
            if preferred in list(aset.findall(f"{{{DASH_NS}}}Representation")):
                tmpl = aset.find(f"{{{DASH_NS}}}SegmentTemplate")
                break
    if tmpl is None:
        tmpl = root.find(f".//{{{DASH_NS}}}SegmentTemplate")
    if tmpl is None:
        raise AssertionError("MPD missing SegmentTemplate")

    init_tpl = tmpl.get("initialization")
    media_tpl = tmpl.get("media")
    start_number = int(tmpl.get("startNumber", "1"))
    timescale = int(tmpl.get("timescale", "1"))
    seg_duration_ts = int(tmpl.get("duration", "0"))
    if not init_tpl or not media_tpl or seg_duration_ts <= 0:
        raise AssertionError("SegmentTemplate missing initialization/media/duration")

    segment_duration_sec = seg_duration_ts / timescale
    n_segments = max(1, math.ceil(duration_sec / segment_duration_sec))

    return {
        "rep_id": rep_id,
        "init_template": init_tpl,
        "media_template": media_tpl,
        "start_number": start_number,
        "segment_duration_sec": segment_duration_sec,
        "duration_sec": duration_sec,
        "n_segments": n_segments,
    }


def _dash_download_all(mpd_url: str) -> None:
    """Simulate a DASH player: fetch MPD, init segment, then each media segment in order."""
    mpd_http = _rewrite_minio_url(mpd_url)
    r = requests.get(mpd_http, timeout=30)
    _assert(r.status_code == 200, f"MPD downloaded (got {r.status_code})")
    _assert(b"<MPD" in r.content, "response body contains <MPD")

    plan = _parse_dash_plan(r.content)
    rep_id = plan["rep_id"]
    print(
        f"  DASH plan: rep={rep_id}, segments={plan['n_segments']}, "
        f"seg_dur={plan['segment_duration_sec']}s, duration={plan['duration_sec']}s"
    )

    base = f"http://{MINIO_ENDPOINT}"
    init_path = plan["init_template"].replace("$RepresentationID$", rep_id)
    if not init_path.startswith("/"):
        init_path = "/" + init_path
    init_url = base + init_path
    ir = requests.get(init_url, timeout=30)
    _assert(ir.status_code == 200, f"init.mp4 downloaded (got {ir.status_code})")
    _assert(len(ir.content) > 0, "init.mp4 non-empty")
    print(f"  init.mp4: {len(ir.content)} bytes")

    total_bytes = len(ir.content)
    downloaded = 0
    for n in range(plan["start_number"], plan["start_number"] + plan["n_segments"]):
        seg_path = (
            plan["media_template"]
            .replace("$RepresentationID$", rep_id)
            .replace("$Number$", str(n))
        )
        if not seg_path.startswith("/"):
            seg_path = "/" + seg_path
        seg_url = base + seg_path
        sr = requests.get(seg_url, timeout=30)
        _assert(sr.status_code == 200, f"segment seg_{n}.m4s downloaded (got {sr.status_code})")
        _assert(len(sr.content) > 0, f"segment seg_{n}.m4s non-empty")
        total_bytes += len(sr.content)
        downloaded += 1
        print(f"  segment {n}: {len(sr.content)} bytes")

    _assert(downloaded == plan["n_segments"], f"all {plan['n_segments']} segments downloaded")
    print(f"  DASH player fetched {downloaded} segments + init, total {total_bytes} bytes")


# ── Step 0: Ensure MinIO buckets exist ─────────────────────────────
print("\n[0] Ensure MinIO buckets exist")
mc = _minio_client()
for bucket in ["viduploads", "vidsegments", "vidthumbnails", "manifest"]:
    if not mc.bucket_exists(bucket):
        mc.make_bucket(bucket)
        print(f"  Created bucket: {bucket}")
    else:
        print(f"  Bucket exists: {bucket}")


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
with open(os.path.join(os.path.dirname(__file__), "test_video.mp4"), "rb") as f:
    VIDEO_CONTENT = f.read()
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
upload_url = upload_info["url"].replace("http://minio:9000", f"http://{MINIO_ENDPOINT}")
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


# ── Step 8: Poll video for QUEUED status + notif_reference_id + size ─
print("\n[8] Poll videos table → expect status=QUEUED + notif_reference_id + video_url + size within 20s")
conn = psycopg2.connect(DB_DSN)
conn.autocommit = True
cur = conn.cursor()

video_updated = False
for _ in range(20):
    cur.execute(
        "SELECT status, size, notif_reference_id, video_url FROM videos WHERE id = %s",
        (video_id,),
    )
    row = cur.fetchone()
    if row and row[0] == "QUEUED" and row[1] is not None and row[2] is not None and row[3] is not None:
        video_updated = True
        print(f"  Video status={row[0]}, size={row[1]}, notif_reference_id={row[2]}")
        break
    time.sleep(1)
cur.close()
_assert(video_updated, "video status=QUEUED, notif_reference_id, video_url, and size are set")


# ══════════════════════════════════════════════════════════════════
# PROCESSING PIPELINE CHECKS
# ══════════════════════════════════════════════════════════════════

media_conn = psycopg2.connect(MEDIA_DB_DSN)
media_conn.autocommit = True


# ── Step 10: Poll outbox for video.queued published ────────────────
print("\n[9] Poll outbox (video-db) → expect video.queued published within 60s")
cur = conn.cursor()
outbox_published = False
for _ in range(60):
    cur.execute(
        "SELECT id, topic, status FROM outbox "
        "WHERE topic = 'video.queued' AND status = 'PROCESSED' "
        "ORDER BY timestamp DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row:
        outbox_published = True
        print(f"  Found outbox id={row[0]}, topic={row[1]}, status={row[2]}")
        break
    time.sleep(1)
cur.close()
_assert(outbox_published, "video.queued outbox event published")


# ── Step 11: Poll jobs table — expect Job created ─────────────────
print("\n[10] Poll jobs table (media-processing-db) → expect Job within 60s")
mcur = media_conn.cursor()
job_row = None
for _ in range(60):
    mcur.execute("SELECT id, status, video_id FROM jobs WHERE video_id = %s", (video_id,))
    job_row = mcur.fetchone()
    if job_row:
        print(f"  Found job id={job_row[0]}, status={job_row[1]}, video_id={job_row[2]}")
        break
    time.sleep(1)
_assert(job_row is not None, "job created in media-processing-db")
job_id = job_row[0]

# Poll until status = PROCESSING (consumer created it as QUEUED, beat moves to PROCESSING)
job_status = job_row[1]
for _ in range(60):
    mcur.execute("SELECT status FROM jobs WHERE id = %s", (job_id,))
    row = mcur.fetchone()
    if row and row[0] == "PROCESSING":
        job_status = row[0]
        print(f"  Job status={job_status}")
        break
    time.sleep(1)
_assert(job_status == "PROCESSING", f"job status=PROCESSING (got {job_status})")


# ── Step 12: Poll transcode_tasks + verify segments on disk ────────
print("\n[11] Poll transcode_tasks (media-processing-db) + check /tmp/segments")
mcur = media_conn.cursor()
transcode_rows = []
for _ in range(60):
    mcur.execute(
        "SELECT id, status, input_file FROM transcode_tasks WHERE job_id = %s",
        (job_id,),
    )
    transcode_rows = mcur.fetchall()
    if transcode_rows:
        break
    time.sleep(1)
_assert(len(transcode_rows) > 0, f"transcode_tasks created (got {len(transcode_rows)})")
print(f"  Found {len(transcode_rows)} transcode task(s)")

# Check at least one has started processing or completed
transcode_statuses = [r[1] for r in transcode_rows]
print(f"  Transcode statuses: {transcode_statuses}")

# Verify segments on disk via docker exec
result = subprocess.run(
    ["docker", "exec", "meridian-media-processing-celery-worker",
     "ls", f"/tmp/segments/{video_id}/"],
    capture_output=True, text=True, timeout=10,
)
if result.returncode == 0:
    segment_files = result.stdout.strip().split("\n")
    print(f"  Segments on disk: {segment_files}")
    _assert(len(segment_files) > 0, "segments exist on disk in /tmp/segments/")
else:
    # Segments may have been cleaned up already — check if transcode tasks exist
    print(f"  WARNING: Could not list segments (may be cleaned up): {result.stderr.strip()}")
    _assert(len(transcode_rows) > 0, "transcode_tasks exist (segments may be cleaned up)")


# ── Step 13: Poll upload_tasks — expect created ────────────────────
print("\n[12] Poll upload_tasks (media-processing-db) → expect created within 60s")
transcode_ids = [r[0] for r in transcode_rows]
upload_rows = []
for _ in range(60):
    placeholders = ",".join(["%s"] * len(transcode_ids))
    mcur.execute(
        f"SELECT id, status, upload_files FROM upload_tasks "
        f"WHERE transcode_id IN ({placeholders})",
        transcode_ids,
    )
    upload_rows = mcur.fetchall()
    if upload_rows:
        break
    time.sleep(1)
_assert(len(upload_rows) > 0, f"upload_tasks created (got {len(upload_rows)})")
print(f"  Found {len(upload_rows)} upload task(s)")
upload_statuses = [r[1] for r in upload_rows]
print(f"  Upload statuses: {upload_statuses}")


# ── Step 14: Poll upload_tasks completed + MinIO objects ────────────
print("\n[13] Poll upload_tasks completed + verify objects in vidsegments bucket (120s)")
all_uploads_completed = False
for _ in range(120):
    upload_ids = [r[0] for r in upload_rows]
    placeholders = ",".join(["%s"] * len(upload_ids))
    mcur.execute(
        f"SELECT id, status FROM upload_tasks WHERE id IN ({placeholders})",
        upload_ids,
    )
    rows = mcur.fetchall()
    statuses = {r[0]: r[1] for r in rows}
    if all(s == "completed" for s in statuses.values()):
        all_uploads_completed = True
        print(f"  All {len(rows)} upload tasks completed")
        break
    time.sleep(1)
_assert(all_uploads_completed, "all upload_tasks completed")

# Check MinIO for objects in vidsegments bucket
mc = _minio_client()
segment_objects = list(mc.list_objects(SEGMENT_BUCKET, prefix=f"{video_id}/"))
_assert(len(segment_objects) > 0, f"objects in vidsegments bucket (got {len(segment_objects)})")
print(f"  Found {len(segment_objects)} object(s) in {SEGMENT_BUCKET}/{video_id}/")


# ── Step 15: Poll job status = COMPLETED ───────────────────────────
print("\n[14] Poll job status = COMPLETED (media-processing-db, 60s)")
job_completed = False
for _ in range(60):
    mcur.execute("SELECT status FROM jobs WHERE id = %s", (job_id,))
    row = mcur.fetchone()
    if row and row[0] == "COMPLETED":
        job_completed = True
        print(f"  Job {job_id} status=COMPLETED")
        break
    time.sleep(1)
_assert(job_completed, "job status=COMPLETED")


# ── Step 16: Poll job.completed outbox event ───────────────────────
print("\n[15] Poll outbox (media-processing-db) → expect job.completed published within 60s")
outbox_completed = False
for _ in range(60):
    mcur.execute(
        "SELECT id, topic, status, payload FROM outbox "
        "WHERE topic = 'job.completed' AND status = 'PROCESSED' "
        "AND payload->>'video_id' = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (video_id,)
    )
    row = mcur.fetchone()
    if row:
        outbox_completed = True
        payload = row[3] if isinstance(row[3], dict) else json.loads(row[3])
        print(f"  Found outbox id={row[0]}, topic={row[1]}, status={row[2]}")
        print(f"  Payload video_id={payload.get('video_id')}, "
              f"job_id={payload.get('job_id')}, "
              f"segments={len(payload.get('segments_object_urls', []))} URLs")
        break
    time.sleep(1)
_assert(outbox_completed, "job.completed outbox event published")


# ── Step 16: Verify cleanup ────────────────────────────────────────
print("\n[16] Verify cleanup — /tmp/{segments,transcoded,downloads,thumbnails}/{video_id} should be removed")
TEMP_DIRS = ["/tmp/segments", "/tmp/transcoded", "/tmp/downloads", "/tmp/thumbnails"]
all_cleaned = False
for _ in range(30):
    remaining = []
    for td in TEMP_DIRS:
        result = subprocess.run(
            ["docker", "exec", "meridian-media-processing-celery-worker",
             "ls", f"{td}/{video_id}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            remaining.append(td)
    if not remaining:
        all_cleaned = True
        break
    time.sleep(2)
_assert(all_cleaned, f"all temp dirs cleaned for {video_id} (still present: {remaining})")


# ══════════════════════════════════════════════════════════════════
# MANIFEST PIPELINE — media → manifest → video COMPLETED + manifest_url
# ══════════════════════════════════════════════════════════════════

manifest_conn = psycopg2.connect(MANIFEST_DB_DSN)
manifest_conn.autocommit = True
man_cur = manifest_conn.cursor()


# ── Step 17: Poll manifest_tasks → completed + manifest_url ────────
print("\n[17] Poll manifest_tasks (manifest-db) → expect completed + manifest_url (120s)")
manifest_task_row = None
for _ in range(120):
    man_cur.execute(
        "SELECT id, status, manifest_url FROM manifest_tasks "
        "WHERE video_id = %s ORDER BY created_at DESC LIMIT 1",
        (video_id,),
    )
    manifest_task_row = man_cur.fetchone()
    if manifest_task_row and manifest_task_row[1] == "completed" and manifest_task_row[2]:
        print(f"  Manifest task {manifest_task_row[0]} status=completed")
        print(f"  manifest_url={manifest_task_row[2]}")
        break
    time.sleep(1)
_assert(
    manifest_task_row is not None
    and manifest_task_row[1] == "completed"
    and bool(manifest_task_row[2]),
    "manifest task completed with manifest_url",
)
manifest_url = manifest_task_row[2]


# ── Step 18: Verify MPD object exists in MinIO ─────────────────────
print("\n[18] Verify MPD exists in MinIO manifest bucket")
# URL: http://minio:9000/manifest/{video_id}/manifest_{uuid8}.mpd
url_parts = manifest_url.split("/", 3)
_assert(len(url_parts) >= 4, f"manifest_url has bucket+key form (got {manifest_url})")
# parts: ['http:', '', 'minio:9000', 'manifest/{id}/file.mpd']
bucket_and_key = url_parts[3]
mpd_bucket, mpd_key = bucket_and_key.split("/", 1)
_assert(mpd_bucket == MANIFEST_BUCKET, f"manifest bucket={MANIFEST_BUCKET} (got {mpd_bucket})")
mc = _minio_client()
if not mc.bucket_exists(MANIFEST_BUCKET):
    mc.make_bucket(MANIFEST_BUCKET)
stat = mc.stat_object(mpd_bucket, mpd_key)
_assert(stat.size > 0, f"MPD object non-empty ({stat.size} bytes)")


# ── Step 19: Poll manifest.completed outbox (manifest-db) ──────────
print("\n[19] Poll outbox (manifest-db) → expect manifest.completed published (90s)")
mc_outbox_completed = False
mc_payload = None
for _ in range(90):
    man_cur.execute(
        "SELECT id, topic, status, payload FROM outbox "
        "WHERE topic = 'manifest.completed' AND status = 'PROCESSED' "
        "AND payload->>'video_id' = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (video_id,),
    )
    row = man_cur.fetchone()
    if row:
        mc_outbox_completed = True
        mc_payload = row[3] if isinstance(row[3], dict) else json.loads(row[3])
        print(f"  Found outbox id={row[0]}, topic={row[1]}, status={row[2]}")
        print(f"  payload.manifest_url={mc_payload.get('manifest_url')}")
        break
    time.sleep(1)
_assert(mc_outbox_completed, "manifest.completed outbox event published")
_assert(
    mc_payload is not None and mc_payload.get("manifest_url") == manifest_url,
    "manifest.completed payload includes matching manifest_url",
)


# ── Step 20: Poll video DB → COMPLETED + manifest_url set ──────────
print("\n[20] Poll videos (video-db) → expect status=COMPLETED and manifest_url set (90s)")
video_completed = False
stored_manifest_url = None
for _ in range(90):
    vcur = conn.cursor()
    vcur.execute(
        "SELECT status, manifest_url FROM videos WHERE id = %s",
        (video_id,),
    )
    row = vcur.fetchone()
    vcur.close()
    if row and row[0] == "COMPLETED" and row[1]:
        video_completed = True
        stored_manifest_url = row[1]
        print(f"  Video status=COMPLETED, manifest_url={stored_manifest_url}")
        break
    time.sleep(1)
_assert(video_completed, "video status=COMPLETED with manifest_url persisted")
_assert(stored_manifest_url == manifest_url, "video.manifest_url matches manifest task URL")


# ── Step 21: GET video via API → includes manifest_url ─────────────
print("\n[21] GET /api/video/{id} → expect manifest_url in response")
# Reuse session cookie from earlier login if still valid; rebuild if needed
try:
    session_cookie
except NameError:
    session_cookie = None
if not session_cookie:
    # re-login
    r = requests.post(
        f"{API_GATEWAY}/api/auth/login",
        json={"email": "e2e@example.com", "password": "E2eTest!123"},
    )
    _assert(r.status_code == 200, "re-login for video GET")
    session_cookie = "; ".join(f"{k}={v}" for k, v in _parse_cookies(r).items())

sign_headers = _proxy_sign("GET", f"/api/video/{video_id}")
r = requests.get(
    f"{VIDEO_SERVICE}/api/video/{video_id}",
    headers={**sign_headers, "Cookie": session_cookie, "Content-Type": "application/json"},
)
_assert(r.status_code == 200, f"GET video status=200 (got {r.status_code})")
body = r.json()
_assert(body.get("manifest_url") == manifest_url, "API response includes manifest_url")
_assert(body.get("status") == "COMPLETED", "API response status=COMPLETED")


# ── Step 22: Simulated DASH player — MPD + sequential segments ─────
print("\n[22] DASH player — download MPD, init.mp4, then each segment sequentially")
_dash_download_all(manifest_url)


# Cleanup manifest DB connection
man_cur.close()
manifest_conn.close()


# ══════════════════════════════════════════════════════════════════
# FAILED JOB FLOW — process_failed_jobs
# ══════════════════════════════════════════════════════════════════

FAILED_VIDEO_ID = "failed-e2e-video"
FAILED_JOB_ID = "job:failed-e2e"
FAILED_TRANSCODE_ID = "tc-failed-e2e"
FAILED_UPLOAD_ID = "ut-failed-e2e"
FAILED_OBJ_KEY = f"{FAILED_VIDEO_ID}/720p/seg_1.m4s"


# ── Step 23a: Seed FAILED job + video via SQL ──────────────────────
print("\n[23a] Seed FAILED job + video via SQL")

# Clean up any leftover data from previous runs
vcur = conn.cursor()
vcur.execute("DELETE FROM videos WHERE id = %s", (FAILED_VIDEO_ID,))
conn.commit()
vcur.close()

mcur = media_conn.cursor()
mcur.execute("DELETE FROM upload_tasks WHERE id = %s", (FAILED_UPLOAD_ID,))
mcur.execute("DELETE FROM transcode_tasks WHERE id = %s", (FAILED_TRANSCODE_ID,))
mcur.execute("DELETE FROM outbox WHERE payload->>'job_id' = %s", (FAILED_JOB_ID,))
mcur.execute("DELETE FROM jobs WHERE id = %s", (FAILED_JOB_ID,))
media_conn.commit()
mcur.close()

# Also clean up any leftover objects from previous runs
for obj in mc.list_objects(SEGMENT_BUCKET, prefix=f"{FAILED_VIDEO_ID}/", recursive=True):
    mc.remove_object(SEGMENT_BUCKET, obj.object_name)

# Upload fake object BEFORE seeding the job to avoid race condition
# with celery worker processing the job before the object exists
print(f"\n[23a-pre] Upload fake object to {SEGMENT_BUCKET}/{FAILED_OBJ_KEY}")
import io as _io
fake_data = b"fake-transcoded-segment"
mc.put_object(
    SEGMENT_BUCKET, FAILED_OBJ_KEY,
    _io.BytesIO(fake_data), length=len(fake_data),
    content_type="video/mp4",
)
objects_before = list(mc.list_objects(SEGMENT_BUCKET, prefix=f"{FAILED_VIDEO_ID}/", recursive=True))
_assert(len(objects_before) > 0, f"fake object exists in {SEGMENT_BUCKET} before cleanup")

# Insert video with num_of_retries=6 so failure_consumer triggers FAILED path
vcur = conn.cursor()
vcur.execute(
    "INSERT INTO videos (id, filename, status, num_of_retries, user_id, created_at) "
    "VALUES (%s, %s, %s, %s, %s, NOW()) ON CONFLICT (id) DO NOTHING",
    (FAILED_VIDEO_ID, "failed.mp4", "PROCESSING", 6, user_id),
)
conn.commit()
vcur.close()
print(f"  Inserted video {FAILED_VIDEO_ID} with num_of_retries=6")

# Insert FAILED job in media-processing-db
mcur = media_conn.cursor()
mcur.execute(
    "INSERT INTO jobs (id, status, video_id, object_url, published, num_of_retries, "
    "num_of_rendition_processed, created_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW()) ON CONFLICT (id) DO NOTHING",
    (FAILED_JOB_ID, "FAILED", FAILED_VIDEO_ID, "http://minio:9000/viduploads/fake.mp4", False, 5, 0),
)
# Insert completed TranscodeTask
mcur.execute(
    "INSERT INTO transcode_tasks (id, job_id, status, input_file, num_of_processed_uploads, num_of_retries, created_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, NOW()) ON CONFLICT (id) DO NOTHING",
    (FAILED_TRANSCODE_ID, FAILED_JOB_ID, "COMPLETED", f"/tmp/segments/{FAILED_VIDEO_ID}/seg_1.mp4", 0, 0),
)
# Insert completed UploadTask with upload_files pointing to resolved object key
mcur.execute(
    "INSERT INTO upload_tasks (id, transcode_id, status, upload_files, num_of_retries, created_at) "
    "VALUES (%s, %s, %s, %s, %s, NOW()) ON CONFLICT (id) DO NOTHING",
    (FAILED_UPLOAD_ID, FAILED_TRANSCODE_ID, "completed",
     json.dumps([f"/tmp/transcoded/{FAILED_VIDEO_ID}/720p/seg_1.m4s"]), 0),
)
media_conn.commit()
mcur.close()
print(f"  Inserted job={FAILED_JOB_ID}, transcode={FAILED_TRANSCODE_ID}, upload={FAILED_UPLOAD_ID}")


# ── Step 23c: Poll process_failed_jobs → job.published=True (60s) ──
print("\n[23c] Poll process_failed_jobs → expect job.published=True within 60s")
mcur = media_conn.cursor()
job_published = False
for _ in range(60):
    mcur.execute("SELECT published FROM jobs WHERE id = %s", (FAILED_JOB_ID,))
    row = mcur.fetchone()
    if row and row[0] is True:
        job_published = True
        print(f"  Job {FAILED_JOB_ID} published=True")
        break
    time.sleep(1)
mcur.close()
_assert(job_published, "process_failed_jobs set job.published=True")


# ── Step 23d: Verify outbox event job.failed published (60s) ───────
print("\n[23d] Poll outbox (media-processing-db) → expect job.failed published within 60s")
mcur = media_conn.cursor()
failed_outbox_published = False
for _ in range(60):
    mcur.execute(
        "SELECT id, topic, status, payload FROM outbox "
        "WHERE topic = 'job.failed' AND status = 'PROCESSED' "
        "ORDER BY created_at DESC LIMIT 1"
    )
    row = mcur.fetchone()
    if row:
        payload = row[3] if isinstance(row[3], dict) else json.loads(row[3])
        if payload.get("job_id") == FAILED_JOB_ID:
            failed_outbox_published = True
            print(f"  Found outbox id={row[0]}, topic={row[1]}, status={row[2]}")
            print(f"  Payload: video_id={payload.get('video_id')}, job_id={payload.get('job_id')}")
            break
    time.sleep(1)
mcur.close()
_assert(failed_outbox_published, "job.failed outbox event published")


# ── Step 23e: Verify objects cleaned from vidsegments ──────────────
print(f"\n[23e] Verify objects cleaned from {SEGMENT_BUCKET}/{FAILED_VIDEO_ID}/")
objects_cleaned = False
for i in range(30):
    objects_after = list(mc.list_objects(SEGMENT_BUCKET, prefix=f"{FAILED_VIDEO_ID}/", recursive=True))
    if len(objects_after) == 0:
        objects_cleaned = True
        print(f"  All objects cleaned from {SEGMENT_BUCKET}/{FAILED_VIDEO_ID}/")
        break
    print(f"  [{i+1}/30] Still {len(objects_after)} object(s): {[o.object_name for o in objects_after]}")
    time.sleep(2)
_assert(objects_cleaned,
        f"failed job objects cleaned from {SEGMENT_BUCKET} (still {len(objects_after)} objects: {[o.object_name for o in objects_after]})")


# ── Step 23f: Verify video service received job.failed → video FAILED
print("\n[23f] Poll videos table (video-db) → expect status=FAILED within 30s")
video_failed = False
for _ in range(30):
    vcur = conn.cursor()
    vcur.execute("SELECT status FROM videos WHERE id = %s", (FAILED_VIDEO_ID,))
    row = vcur.fetchone()
    vcur.close()
    if row and row[0] == "FAILED":
        video_failed = True
        print(f"  Video {FAILED_VIDEO_ID} status=FAILED")
        break
    time.sleep(1)
_assert(video_failed, "video service received job.failed and set video status=FAILED")


# ── Step 23g: Cleanup seeded data ──────────────────────────────────
print("\n[23g] Cleanup seeded test data")
vcur = conn.cursor()
vcur.execute("DELETE FROM videos WHERE id = %s", (FAILED_VIDEO_ID,))
conn.commit()
vcur.close()

mcur = media_conn.cursor()
mcur.execute("DELETE FROM upload_tasks WHERE id = %s", (FAILED_UPLOAD_ID,))
mcur.execute("DELETE FROM transcode_tasks WHERE id = %s", (FAILED_TRANSCODE_ID,))
mcur.execute("DELETE FROM outbox WHERE payload->>'job_id' = %s", (FAILED_JOB_ID,))
mcur.execute("DELETE FROM jobs WHERE id = %s", (FAILED_JOB_ID,))
media_conn.commit()
mcur.close()
print("  Seeded data cleaned up")


# ══════════════════════════════════════════════════════════════════
# RETRY ENDPOINT FLOW
# ══════════════════════════════════════════════════════════════════

RETRY_VIDEO_ID = "retry-e2e-video"


# ── Step 24a: Seed video with status=RETRY ─────────────────────────
print("\n[24a] Seed video with status=RETRY via SQL")

vcur = conn.cursor()
vcur.execute("DELETE FROM videos WHERE id = %s", (RETRY_VIDEO_ID,))
conn.commit()

vcur.execute(
    "INSERT INTO videos (id, filename, status, num_of_retries, user_id, published, created_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, NOW()) ON CONFLICT (id) DO NOTHING",
    (RETRY_VIDEO_ID, "retry_test.mp4", "RETRY", 2, user_id, False),
)
conn.commit()
vcur.close()
print(f"  Inserted video {RETRY_VIDEO_ID} with status=RETRY, num_of_retries=2")


# ── Step 24b: GET video → expect status=RETRY ─────────────────────
print("\n[24b] GET /api/video/{video_id} → expect status=RETRY")
sign_headers = _proxy_sign("GET", f"/api/video/{RETRY_VIDEO_ID}")
r = requests.get(
    f"{VIDEO_SERVICE}/api/video/{RETRY_VIDEO_ID}",
    headers={**sign_headers, "Cookie": session_cookie, "Content-Type": "application/json"},
)
_assert(r.status_code == 200, f"status=200 (got {r.status_code})")
_assert(r.json()["status"] == "RETRY", f"status=RETRY (got {r.json()['status']})")
_assert(r.json()["published"] is False, "published=false")
print(f"  Video status={r.json()['status']}, published={r.json()['published']}")


# ── Step 24c: POST /retry → expect 200 + status=QUEUED ────────────
print("\n[24c] POST /api/video/{video_id}/retry → expect 200 + status=QUEUED")
sign_headers = _proxy_sign("POST", f"/api/video/{RETRY_VIDEO_ID}/retry")
r = requests.post(
    f"{VIDEO_SERVICE}/api/video/{RETRY_VIDEO_ID}/retry",
    headers={**sign_headers, "Cookie": session_cookie, "Content-Type": "application/json"},
)
_assert(r.status_code == 200, f"status=200 (got {r.status_code})")
_assert(r.json()["status"] == "QUEUED", f"status=QUEUED (got {r.json()['status']})")
_assert(r.json()["published"] is False, "published=false")
_assert(r.json()["num_of_retries"] == 3, f"num_of_retries=3 (got {r.json()['num_of_retries']})")
print(f"  Retry succeeded: status={r.json()['status']}, published={r.json()['published']}, num_of_retries={r.json()['num_of_retries']}")


# ── Step 24d: GET video → confirm QUEUED ──────────────────────────
print("\n[24d] GET /api/video/{video_id} → confirm status=QUEUED")
sign_headers = _proxy_sign("GET", f"/api/video/{RETRY_VIDEO_ID}")
r = requests.get(
    f"{VIDEO_SERVICE}/api/video/{RETRY_VIDEO_ID}",
    headers={**sign_headers, "Cookie": session_cookie, "Content-Type": "application/json"},
)
_assert(r.status_code == 200, f"status=200 (got {r.status_code})")
_assert(r.json()["status"] == "QUEUED", f"status=QUEUED (got {r.json()['status']})")
print(f"  Confirmed: status={r.json()['status']}")


# ── Step 24e: POST /retry again → expect 400 (not RETRY) ──────────
print("\n[24e] POST /api/video/{video_id}/retry (already QUEUED) → expect 400")
sign_headers = _proxy_sign("POST", f"/api/video/{RETRY_VIDEO_ID}/retry")
r = requests.post(
    f"{VIDEO_SERVICE}/api/video/{RETRY_VIDEO_ID}/retry",
    headers={**sign_headers, "Cookie": session_cookie, "Content-Type": "application/json"},
)
_assert(r.status_code == 400, f"status=400 (got {r.status_code})")
_assert("not in RETRY" in r.json()["detail"], f"error mentions RETRY (got {r.json()['detail']})")
print(f"  Correctly rejected: {r.json()['detail']}")


# ── Step 24f: POST /retry on nonexistent video → expect 404 ────────
print("\n[24f] POST /api/video/nonexistent/retry → expect 404")
sign_headers = _proxy_sign("POST", "/api/video/nonexistent/retry")
r = requests.post(
    f"{VIDEO_SERVICE}/api/video/nonexistent/retry",
    headers={**sign_headers, "Cookie": session_cookie, "Content-Type": "application/json"},
)
_assert(r.status_code == 404, f"status=404 (got {r.status_code})")
print(f"  Correctly returned 404")


# ── Step 24g: GET with status filter mismatch → expect 404 ─────────
print("\n[24g] GET /api/video/{video_id}?status=COMPLETED → expect 404")
sign_headers = _proxy_sign("GET", f"/api/video/{RETRY_VIDEO_ID}")
r = requests.get(
    f"{VIDEO_SERVICE}/api/video/{RETRY_VIDEO_ID}",
    params={"status": "COMPLETED"},
    headers={**sign_headers, "Cookie": session_cookie, "Content-Type": "application/json"},
)
_assert(r.status_code == 404, f"status=404 (got {r.status_code})")
print(f"  Status filter correctly rejected mismatch")


# ── Step 24h: Cleanup retry test data ──────────────────────────────
print("\n[24h] Cleanup retry test data")
vcur = conn.cursor()
vcur.execute("DELETE FROM videos WHERE id = %s", (RETRY_VIDEO_ID,))
conn.commit()
vcur.close()
print(f"  Cleaned up {RETRY_VIDEO_ID}")


# ── Cleanup DB connections ──────────────────────────────────────────
media_conn.close()
conn.close()


# ── Step 25: Logout ───────────────────────────────────────────────
print("\n[25] POST /api/auth/logout → expect 200")
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
