# MERIDIAN Video Service

A production-grade video upload and processing microservice built with FastAPI, Python, PostgreSQL, MinIO, and Kafka. Handles presigned upload URLs, multipart uploads for large files, and asynchronous video processing via bucket notification events.

## Overview

The Video Service is the media backbone of MERIDIAN. It runs behind the API Gateway and is protected by HMAC-SHA256 proxy signatures — all requests must originate from the gateway to be accepted.

**Key responsibilities:**
- Presigned POST upload URL generation with Content-Type enforcement
- Server-side multipart upload initiation for large files (>100 MB)
- MinIO bucket notification consumption via Kafka
- Video status lifecycle management (awaiting upload → queued → processing → generating manifest → completed/failed/retry)
- Outbox pattern for reliable downstream event dispatch
- 6 Kafka consumers: notification, retry, processing, failure, manifest_generating, manifest_completed
- Distributed Redis locks with nested lock pattern (PROCESS + COMMIT)
- Real-time WebSocket notifications for video status updates
- Ownership-based access control on all video endpoints

## Architecture

```
┌──────────┐    ┌─────────────┐    ┌───────────────┐
│  Client  │───▶│ API Gateway │───▶│ Video Service │
│          │◀───│  (port 3001)│    │  (port 8000)  │
└──────────┘ WS └──────┬──────┘    └───────┬──────┘
                       │                   │
                  HMAC-signed          ┌───┴───┐
                  requests + WS proxy  │       │
                                    ┌──┴──┐ ┌──┴────┐
                                    │Redis│ │PostgreSQL│
                                    │:6379│ │  :5432  │
                                    └─────┘ └────────┘
                                              │
                       ┌──────────────────────┤
                       │                      │
                  ┌────┴─────┐          ┌─────┴──────┐
                  │  MinIO   │          │   Kafka    │
                  │  :9000   │──notifs─▶│   :9092    │
                  └──────────┘          └─────┬──────┘
                                              │
                                        ┌─────┴──────┐
                                        │  Celery    │
                                        │ (worker +  │
                                        │   beat)    │
                                        └────────────┘
```

**Upload flow:**
1. Client requests an upload URL from the video service via the API gateway
2. Service validates the file extension, creates a video record, and returns presigned POST data
3. Client uploads directly to MinIO using the presigned URL
4. MinIO fires a bucket notification to Kafka
5. `process_queued_videos` sets published=true and creates Outbox record
6. `process_outbox_events` dispatches Outbox events to Kafka
7. Real-time status updates are pushed to connected clients via WebSocket (Redis pub/sub)

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Runtime | Python 3.12+ |
| Framework | FastAPI (async) |
| ORM | SQLModel (SQLAlchemy async) |
| Database | PostgreSQL 16 (asyncpg) |
| Object Storage | MinIO (S3-compatible) |
| Message Broker | Apache Kafka (aiokafka) |
| Task Queue | Celery + RabbitMQ |
| Cache | Redis 7 |
| Testing | pytest + pytest-asyncio |
| Container | Docker (multi-stage) |

## Quick Start

### Prerequisites
- Python 3.12+
- PostgreSQL 16+
- Redis 7+
- MinIO
- Kafka

### Local Development

```bash
# Clone the repository
git clone https://github.com/geraldrolland/video_service_meridian.git
cd video_service_meridian

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database, MinIO, and Kafka credentials

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker

```bash
# Build and run with Docker Compose (from MERIDIAN root)
docker compose up --build video-service

# Or standalone
docker build -t video-service .
docker run -p 8000:8000 --env-file .env video-service
```

## API Endpoints

All endpoints are prefixed with `/api/video` and require a valid proxy signature header from the API gateway. Endpoints that access specific videos require ownership (the authenticated user must match the video's `user_id`).

### Get Video

```
GET /api/video/{video_id}
```

Returns a video by ID. Supports optional `?status=` query filter.

**Response (200):**
```json
{
  "id": "uuid",
  "filename": "clip.mp4",
  "status": "COMPLETED",
  "user_id": 1,
  "published": true,
  "num_of_retries": 0,
  "created_at": "2026-09-16T12:00:00"
}
```

| Status | Condition |
|--------|-----------|
| 200 | Video found |
| 403 | Not authorized (user_id mismatch) |
| 404 | Video not found or status mismatch |

### Retry Video

```
POST /api/video/{video_id}/retry
```

Retries a video in `RETRY` status — resets it to `QUEUED` with `published=false` and increments `num_of_retries`.

**Response (200):**
```json
{
  "id": "uuid",
  "filename": "clip.mp4",
  "status": "QUEUED",
  "user_id": 1,
  "published": false,
  "num_of_retries": 1,
  "created_at": "2026-09-16T12:00:00"
}
```

| Status | Condition |
|--------|-----------|
| 200 | Video queued for retry |
| 400 | Video is not in RETRY status |
| 403 | Not authorized |
| 404 | Video not found |

### Upload Video

```
POST /api/video/upload
```

Creates a video record and returns upload data. Small files get a single presigned POST; large files (>100 MB) get server-side multipart initiation.

**Request:**
```json
{ "filename": "clip.mp4", "content_type": "video/mp4", "file_size": 1048576 }
```

**Response — Small file (201):**
```json
{
  "id": "uuid",
  "filename": "clip.mp4",
  "status": "AWAITING_UPLOAD",
  "user_id": 1,
  "created_at": "2026-09-16T12:00:00",
  "upload": {
    "url": "http://minio:9000/viduploads",
    "fields": {
      "key": "videos/uuid/clip.mp4",
      "policy": "...",
      "x-amz-algorithm": "AWS4-HMAC-SHA256",
      "x-amz-credential": "...",
      "x-amz-date": "...",
      "x-amz-signature": "..."
    }
  }
}
```

**Response — Large file (201):**
```json
{
  "id": "uuid",
  "filename": "large.mp4",
  "status": "AWAITING_UPLOAD",
  "upload": {
    "mode": "multipart",
    "video_id": "uuid",
    "upload_id": "upload-id-123",
    "part_size": 5242880,
    "total_parts": 40,
    "parts": [
      { "part_number": 1, "url": "http://minio/part1" },
      { "part_number": 2, "url": "http://minio/part2" }
    ]
  }
}
```

| Status | Condition |
|--------|-----------|
| 201 | Upload data generated |
| 422 | File extension not allowed |
| 500 | Server error |

### Complete Multipart Upload

```
POST /api/video/{video_id}/upload/complete
```

Finalizes a multipart upload server-side after all parts have been uploaded directly to MinIO.

**Request:**
```json
{
  "upload_id": "upload-id-123",
  "parts": [
    { "part_number": 1, "etag": "etag-1" },
    { "part_number": 2, "etag": "etag-2" }
  ]
}
```

**Response (200):**
```json
{ "status": "QUEUED" }
```

| Status | Condition |
|--------|-----------|
| 200 | Upload completed, video queued |
| 400 | No multipart upload in progress |
| 404 | Video not found |

### Abort Multipart Upload

```
POST /api/video/{video_id}/upload/abort
```

Discards all uploaded parts and marks the video as failed.

**Request:**
```json
{ "upload_id": "upload-id-123" }
```

**Response (200):**
```json
{ "status": "FAILED" }
```

| Status | Condition |
|--------|-----------|
| 200 | Upload aborted |
| 400 | No multipart upload in progress |
| 404 | Video not found |

### WebSocket Notifications

```
WS /ws/video/notification
```

Real-time video status updates via WebSocket. The API gateway proxies the connection and attaches `x-proxy-signature` / `x-proxy-timestamp` headers for authentication. The video service verifies the HMAC signature before accepting.

**Connection flow:**
1. Client connects to API gateway at `/ws/video/notification` with `Authorization: Bearer <jwt>`
2. Gateway verifies JWT, attaches proxy signature headers, forwards to video service
3. Video service verifies proxy signature, extracts `user_id` from session cookie, accepts connection
4. Status updates are pushed as JSON messages whenever a video's status changes

**Message format:**
```json
{
  "video_id": "uuid",
  "status": "COMPLETED",
  "user_id": 1
}
```

**Close codes:**

| Code | Reason |
|------|--------|
| 4001 | Missing session cookie |
| 4003 | Invalid or missing proxy signature |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://postgres:postgres@video-db:5432/video_db` |
| `MINIO_ENDPOINT` | MinIO endpoint | `minio:9000` |
| `MINIO_ACCESS_KEY` | MinIO access key | `minioadmin` |
| `MINIO_SECRET_KEY` | MinIO secret key | `minioadmin` |
| `MINIO_BUCKET` | Upload bucket name | `viduploads` |
| `MINIO_SECURE` | Use HTTPS for MinIO | `false` |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka broker addresses | `kafka:29092` |
| `KAFKA_TOPIC` | Bucket notification topic | `bucketnotifications` |
| `KAFKA_CONSUMER_GROUP_ID` | Consumer group ID | `meridian-video-consumer-group` |
| `KAFKA_AUTO_OFFSET_RESET` | Offset reset policy | `earliest` |
| `CELERY_BROKER_URL` | RabbitMQ broker URL | `amqp://guest:guest@rabbitmq:5672//` |
| `CELERY_RESULT_BACKEND` | Redis result backend | `redis://redis:6379/1` |
| `REDIS_HOST` | Redis host | `redis` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_DB` | Redis database number for pub/sub | `3` |
| `JWT_SECRET` | JWT signing secret for WebSocket auth | `test-secret` |
| `PROXY_SECRET` | HMAC shared secret with API gateway | `change-me-in-production` |
| `ALLOWED_VIDEO_EXTENSIONS` | Comma-separated allowed extensions | `mp4,mov,avi,mkv,webm,flv,wmv` |
| `MULTIPART_THRESHOLD` | File size (bytes) for multipart switch | `104857600` (100 MB) |
| `DEFAULT_PART_SIZE` | Part size (bytes) for multipart uploads | `5242880` (5 MB) |
| `OUTBOX_MAX_RETRY` | Max retries before outbox event is marked FAILED | `5` |
| `LOG_LEVEL` | Python logging level | `info` |

## Kafka Consumers

The video service runs 6 Kafka consumers on startup, each handling a specific event type:

| Consumer | Topic | Action |
|----------|-------|--------|
| `notification_consumer` | `bucketnotifications` | Stores event, sets video to QUEUED, creates outbox |
| `retry_consumer` | `video.retry` | Resets video to QUEUED, creates outbox |
| `processing_consumer` | `video.processing` | Sets video status to PROCESSING |
| `failure_consumer` | `job.failed` / `manifest.failed` | Sets video to FAILED or RETRY |
| `manifest_generating_consumer` | `manifest.generating` | Sets video to GENERATING_MANIFEST |
| `manifest_completed_consumer` | `manifest.completed` | Sets video status to COMPLETED |

## Project Structure

```
video_service/
├── app/
│   ├── config.py              # Centralized settings (pydantic-settings)
│   ├── consumers/
│   │   ├── __init__.py        # Re-exports all consumers
│   │   ├── base.py            # AppRebalanceListener
│   │   ├── notification_consumer.py   # bucketnotifications → QUEUED + Outbox
│   │   ├── retry_consumer.py          # video.retry → QUEUED + Outbox
│   │   ├── processing_consumer.py     # video.processing → PROCESSING
│   │   ├── failure_consumer.py        # job.failed/manifest.failed → FAILED/RETRY
│   │   ├── manifest_generating_consumer.py  # manifest.generating → GENERATING_MANIFEST
│   │   └── manifest_completed_consumer.py   # manifest.completed → COMPLETED
│   ├── database.py            # Async SQLAlchemy engine + session factory
│   ├── main.py                # FastAPI app bootstrap + startup/shutdown
│   ├── minio_client.py        # MinIO presigned URL + multipart helpers
│   ├── producer.py            # KafkaProducer (auto event_id + ISO timestamp)
│   ├── tasks/
│   │   ├── __init__.py        # Re-exports all 2 tasks
│   │   ├── process_queued_videos.py   # QUEUED + published=false → Outbox
│   │   └── process_outbox_events.py   # PENDING Outbox → Kafka publish
│   ├── celery_app.py          # Celery config with video queue routing
│   ├── lock.py                # Redis distributed locks (PROCESS + COMMIT nested pattern)
│   ├── websocket.py           # WebSocket hub: Redis pub/sub, proxy signature verification
│   ├── middleware/
│   │   ├── check_proxy_signature.py  # HMAC gateway signature verification
│   │   └── get_user_session.py       # Session cookie extraction
│   ├── models/
│   │   ├── events.py          # MinIO event Pydantic models
│   │   ├── notification.py    # DEPRECATED — BucketNotificationEvent removed
│   │   ├── outbox.py          # Outbox event SQLModel (with video_id FK)
│   │   ├── session.py         # SessionData Pydantic model
│   │   └── video.py           # Video SQLModel + VideoStatus enum (7 states, notif_reference_id)
│   ├── routes/
│   │   ├── video.py           # Upload, complete, abort, get, retry, WS endpoints
│   │   └── ready.py           # Database readiness probe
│   └── utils/
│       └── notification_utils.py  # build_object_url, build_id, extract_video_id
├── tests/
│   ├── middleware/             # Middleware unit tests
│   ├── test_minio_client.py   # MinIO client tests
│   ├── test_multipart_upload.py  # Multipart upload tests
│   ├── test_process_notifications.py  # Celery task tests
│   ├── test_ready.py          # Readiness endpoint tests
│   ├── test_routes.py         # Upload, get, retry endpoint tests
│   ├── test_upload_endpoint.py  # Upload route tests
│   ├── test_video_model.py    # Model validation tests
│   └── test_websocket.py      # WebSocket + proxy signature tests
├── Dockerfile
├── .env.example
├── requirements.txt
└── start.sh                   # Container entrypoint
```

## Testing

Tests use **pytest** with **pytest-asyncio** for async route testing. External dependencies (MinIO, Kafka, PostgreSQL) are mocked in unit tests.

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_upload_endpoint.py -v
```

### Test Coverage

| Module | Tests |
|--------|-------|
| Middleware (proxy signature + session) | 7 tests |
| MinIO client (presigned POST) | 2 tests |
| Multipart upload functions | 4 tests |
| Process outbox + queued videos tasks | 10 tests |
| Ready endpoint | 6 tests |
| Routes (upload, get, retry) | 16 tests |
| Upload endpoint | 8 tests |
| Video/Upload models | 14 tests |
| Lock system | 6 tests |
| Producer | 4 tests |
| WebSocket + proxy signature | 17 tests |
| **Total** | **81 tests** |

## Docker

### With Docker Compose (from MERIDIAN root)

```bash
# Start all services
docker compose up --build -d

# View video service logs
docker compose logs -f video-service

# Stop
docker compose down
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| Video Service | `8000` | FastAPI application |
| PostgreSQL | `5432` | Video database |
| MinIO | `9000` / `9001` | Object storage + web UI |
| Kafka | `9092` | Bucket notification events |
| RabbitMQ | `5672` | Celery task broker |
| Redis | `6379` | Celery result backend |

## License

ISC
