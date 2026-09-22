# MERIDIAN

A production-grade microservices-based video processing platform built with Express, FastAPI, PostgreSQL, Redis, Kafka, and MinIO.

MERIDIAN provides a complete pipeline for user authentication, video upload (with direct-to-storage presigned URLs and multipart support), asynchronous event-driven processing via Kafka and Celery, media transcoding into multiple renditions, and real-time WebSocket push notifications.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Infrastructure](#infrastructure)
- [Kafka Topics](#kafka-topics)
- [Security Model](#security-model)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
- [Local Development](#local-development)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Design Patterns](#design-patterns)
- [Environment Variables](#environment-variables)
- [License](#license)

---

## System Architecture

### API Gateway (Port 3001)

The single entry point for all client requests. Built with Express and TypeScript, it handles cross-cutting concerns before forwarding to upstream services.

**Middleware Pipeline (executed in order):**

1. **Helmet** -- HTTP security headers (X-Content-Type-Options, X-Frame-Options, Strict-Transport-Security, CSP, etc.)
2. **CORS** -- Configurable cross-origin resource sharing with credentials support
3. **Request Logger** -- Structured JSON logging via Winston with request/response metadata
4. **Cookie Parser** -- Parses incoming cookies for session extraction
5. **JWT Auth Middleware** -- Validates Bearer tokens, looks up Redis sessions, populates `req.user`
6. **Rate Limiter** -- Per-route rate limiting with two strategies: Fixed Window and Token Bucket
7. **Proxy Router** -- http-proxy-middleware with HMAC-SHA256 request signing
8. **Body Parser** -- Express JSON parser (applied after proxy to preserve raw streams)
9. **Error Handler** -- Global error handler with structured error responses

**HMAC-SHA256 Proxy Signing:**

Every request forwarded to an upstream service is signed with:
- `x-proxy-signature`: HMAC-SHA256 of `"{METHOD}:{URL}:{TIMESTAMP}"` using a shared secret
- `x-proxy-timestamp`: Current Unix timestamp (30-second replay window)

Upstream services verify this signature before processing, preventing unauthorized inter-service calls. Signature verification uses `crypto.timingSafeEqual` to prevent timing attacks.

**Rate Limiting Strategies:**

| Strategy | Algorithm | Best For |
|----------|-----------|----------|
| Fixed Window | Counter per time window | Simple, predictable limits |
| Token Bucket | Atomic Redis Lua script | Burst-tolerant, smooth throttling |

The Token Bucket implementation uses an atomic Lua script executed in Redis, handling concurrent requests without race conditions. It supports configurable refill rates and bucket capacities per route.

**WebSocket Proxy:**

The gateway proxies WebSocket connections to upstream services:

```
ws://localhost:3001/ws/video/<user_id>?token=<token>
```

The gateway validates the JWT token from the query parameter, verifies the session in Redis, then forwards the connection to the Video Service with HMAC-signed upgrade headers.

**Route Configuration:**

Routes are defined via the `ROUTES` environment variable as a JSON array:
```json
[
  { "prefix": "/api/auth", "target": "http://auth-service:4000" },
  { "prefix": "/api/video", "target": "http://video-service:8000" }
]
```

Each route can include per-route rate limiting overrides.

---

### Auth Service (Port 4000)

Handles identity, session management, and the JWT token lifecycle. Built with Express and TypeScript, backed by PostgreSQL and Redis.

**API Endpoints:**

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | /api/auth/register | Create account (bcrypt, 12 rounds) | No |
| POST | /api/auth/login | Authenticate + issue JWT pair | No |
| POST | /api/auth/logout | Invalidate session + clear cookie | Yes |
| GET | /api/auth/me | Return authenticated user profile | Yes |
| POST | /api/auth/refresh-token | Single-use token rotation | No (uses cookie) |
| GET | /health | Health check | No |
| GET | /ready | Database connectivity probe | No |

**Session Architecture:**

```
Client                  Gateway                 Auth Service              Redis
  |                        |                         |                      |
  |-- POST /login -------->|-- HMAC signed req ----->|                       |
  |                        |                         |-- SET session:UUID -->|
  |                        |                         |   (7-day TTL)        |
  |<-- Set-Cookie: refresh |<-- 200 + accessToken ---|                      |
  |    + accessToken       |                         |                      |
  |                        |                         |                      |
  |-- GET /me (Bearer) --->|-- HMAC signed req ----->|                      |
  |                        |                         |-- GET session:UUID ->|
  |<-- 200 + user data ----|<-- 200 + user data -----|<-- {userId, email} --|
```

- **Access Token**: 7-minute expiry, returned in response body
- **Refresh Token**: 7-day expiry, set as httpOnly, Secure, SameSite=strict cookie scoped to `/api/auth/refresh-token`
- **Session Storage**: Redis key `session:<UUID>` with JSON payload `{ userId, email }` and 7-day TTL
- **Token Rotation**: Each refresh creates a new session UUID and deletes the old one (single-use tokens)

**Database Schema:**

```sql
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(255) UNIQUE NOT NULL,
    hash_password VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### Video Service (Port 8000)

Manages video upload, storage, and the async processing lifecycle. Built with FastAPI (async Python), backed by PostgreSQL, MinIO, Kafka, and Celery. Runs 5 Kafka consumers for event-driven state transitions and provides WebSocket push notifications.

**API Endpoints:**

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | /api/video/{video_id} | Get video by ID (optional ?status= filter) | Yes |
| POST | /api/video/upload | Create video + generate upload data | Yes |
| POST | /api/video/{id}/upload/complete | Finalize multipart upload | Yes |
| POST | /api/video/{id}/upload/abort | Discard multipart upload | Yes |
| POST | /api/video/{id}/retry | Retry a video in RETRY status | Yes |
| WS | /ws/video/{user_id}?token=<jwt> | WebSocket for real-time updates | Yes (JWT + HMAC) |
| GET | /ready | Database readiness probe | No |

**Upload Flow:**

```
Client                Video Service           MinIO                Kafka
  |                         |                    |                    |
  |-- POST /upload -------->|                    |                    |
  |   (filename, size)      |-- Validate ext     |                    |
  |                         |-- Create Video     |                    |
  |                         |   (AWAITING_UPLOAD)|                    |
  |<-- presigned URLs ------|                    |                    |
  |                         |                    |                    |
  |-- PUT (direct) -------->+-------------------->|                    |
  |   or multipart PUTs     |                    |-- bucket notif --->|
  |                         |                    |   (topic:          |
  |                         |                    |    bucketnotifs)   |
  |                         |<--- Kafka consumer -+                    |
  |                         |    stores event    |                    |
  |                         |                    |                    |
  |                    [Celery beat: process_notifications]           |
  |                         |-- Extract video_id |                    |
  |                         |-- Set QUEUED       |                    |
  |                         |                    |                    |
  |                    [Celery beat: process_queued_videos]           |
  |                         |-- Set published=T  |                    |
  |                         |-- Create Outbox    |                    |
  |                         |                    |                    |
  |                    [Celery beat: process_outbox_events]           |
  |                         |-- Publish to Kafka +------------------->|
  |                         |   (distributed lock)                    |
```

**Upload Modes:**

| Mode | Condition | Mechanism |
|------|-----------|-----------|
| Presigned POST | file_size <= threshold (100 MB) | Single PUT directly to MinIO |
| Multipart | file_size > threshold | Server-initiated multipart with presigned PUT per part |

Supported extensions: `mp4`, `mov`, `avi`, `mkv`, `webm`, `flv`, `wmv`

**Video State Machine:**

```
AWAITING_UPLOAD --> QUEUED --> PROCESSING --> GENERATING_MANIFEST --> COMPLETED
                        |           |              |
                        |           +--> FAILED <--+
                        +--> RETRY (retries up to 5 times)
```

**Transactional Outbox Pattern:**

Ensures reliable event publishing to Kafka even during broker outages:

1. `process_notifications` sets video status to QUEUED (no outbox creation)
2. `process_queued_videos` polls QUEUED videos with `published=false` in batches of 50, sets `published=true`, and creates an Outbox record in the same DB transaction
3. A separate Celery beat task (`process_outbox_events`, every 10s) polls PENDING outbox records
4. Events are published to Kafka with distributed Redis locks to prevent duplicate processing
5. Failed events are retried up to 5 times with 2-minute backoff intervals
6. After 5 failures, the event is marked FAILED and the associated video status is set to FAILED

**WebSocket Architecture:**

```
Client (Browser)              API Gateway               Video Service
      |                            |                           |
      |-- WS /ws/video/uid ------>|-- HMAC signed upgrade --->|
      |   ?token=<jwt>             |   + JWT validation       |
      |                            |                           |-- accept()
      |<--- Connection established -|                           |-- register in dict
      |                            |                           |
      |                       [Redis pubsub: video:notification]
      |                            |                           |
      |<--- send_text(data) -------|<-- publish_update() -----|
```

- **Connection Registry**: `dict[user_id, list[WebSocket]]` maps each user to their active WebSocket connections
- **Shared Redis Pub/Sub**: Events published to the `video:notification` channel are forwarded to the relevant user's WebSocket connections
- **Stale Connection Cleanup**: Dead connections are automatically removed from the registry

**Distributed Locking:**

Redis-based locks with 2-minute TTL prevent duplicate task processing across Celery workers. The lock is acquired before processing and released in a `finally` block to ensure cleanup.

---

### Media Processing Service (Port 8001)

The core video processing engine. Built with FastAPI + Celery (Python 3.12), it consumes events from Kafka, downloads video segments from MinIO, transcodes to multiple renditions, uploads results back to MinIO, and publishes completion/failure events via the transactional outbox pattern.

**Processing Pipeline:**

```
video.queued event
    |
    v
+------------------------------------------+
|  1. Kafka Consumer                       |
|     Creates Job (status: QUEUED)         |
+-------------------+----------------------+
                    |
                    v
+------------------------------------------+
|  2. process_queued_jobs (every 15s)      |
|     Download video from MinIO            |
|     Generate thumbnail                   |
|     Segment into 6-second chunks         |
|     Generate init segments (CMAF)        |
|     Create TranscodeTasks                |
|     Status -> PROCESSING                 |
+-------------------+----------------------+
                    |
                    v
+------------------------------------------+
|  3. process_transcode_tasks (every 10s)  |
|     Transcode each segment:              |
|     360p / 480p / 720p / 1080p           |
|     Create UploadTasks                   |
+-------------------+----------------------+
                    |
                    v
+------------------------------------------+
|  4. process_upload_tasks (every 10s)     |
|     Upload CMAF .m4s segments and init   |
|     files to MinIO vidsegments bucket    |
+-------------------+----------------------+
                    |
                    v
+------------------------------------------+
|  5. check_completed_jobs (every 15s)     |
|     Verify all TranscodeTasks done       |
|     Status -> COMPLETED                  |
+-------------------+----------------------+
                    |
                    v
+------------------------------------------+
|  6. process_completed_jobs (every 15s)   |
|     Extract video duration               |
|     Cleanup temp files                   |
|     Publish job.completed to Kafka       |
|     via Outbox pattern                   |
+------------------------------------------+
```

**Celery Beat Schedule (7 tasks):**

| Task | Schedule | Description |
|------|----------|-------------|
| `process_queued_jobs` | Every 15s | Download video, generate thumbnail, segment, generate init segments, create TranscodeTasks |
| `process_transcode_tasks` | Every 10s | Transcode segments into 360p/480p/720p/1080p |
| `process_upload_tasks` | Every 10s | Upload CMAF .m4s segments and init files to MinIO vidsegments bucket |
| `check_completed_jobs` | Every 15s | Check all TranscodeTasks are COMPLETED, mark job COMPLETED |
| `process_outbox_events` | Every 10s | Publish pending outbox events to Kafka |
| `process_failed_jobs` | Every 15s | Cleanup failed jobs (MinIO + temp), publish `job.failed` |
| `process_completed_jobs` | Every 15s | Extract video duration, cleanup temp files, publish `job.completed` |

**DB Schema (4 tables):**

**jobs:**
| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(128) PK | Job identifier (`job:{event_id}`) |
| `status` | VARCHAR(16) | QUEUED -> PROCESSING -> COMPLETED / FAILED |
| `video_id` | VARCHAR(255) | Video identifier |
| `object_url` | VARCHAR(1024) | Original video URL in MinIO |
| `published` | BOOLEAN | Whether outbox event has been published |
| `vid_thumbnail_url` | VARCHAR(1024) | Thumbnail URL |
| `num_of_retries` | INT | Retry counter |
| `retry_after` | TIMESTAMP | Next retry window |

**transcode_tasks:**
| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `job_id` | VARCHAR(128) FK | Parent job |
| `status` | VARCHAR(16) | QUEUED -> PROCESSING -> COMPLETED / FAILED |
| `input_file` | VARCHAR(1024) | Local segment file path |

**upload_tasks:**
| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `transcode_id` | VARCHAR(36) FK | Parent transcode task |
| `upload_files` | JSON | List of file paths to upload |
| `status` | VARCHAR(16) | PENDING -> COMPLETED / FAILED |

**outbox:**
| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `topic` | VARCHAR(255) | Kafka topic to publish to |
| `payload` | JSON | Event payload |
| `status` | VARCHAR(32) | PENDING -> PROCESSED / FAILED |
| `retry_count` | INT | Retry counter |

**Dual Redis Locks:**

- **PROCESSING lock** -- guards download + segment + upload operations
- **COMMITTING lock** -- guards database writes

Both locks use a 2-minute TTL with a 5-second blocking timeout. Locks are always released in `finally` blocks to prevent deadlocks.

**API Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (always returns 200) |
| `GET` | `/ready` | Readiness check (verifies DB + Redis connectivity) |

---

## Infrastructure

| Service | Port (Host / Container) | Purpose |
|---------|------------------------|---------|
| PostgreSQL (auth-db) | 5433 / 5432 | Auth user storage |
| PostgreSQL (video-db) | 5434 / 5432 | Video records, notifications, outbox |
| PostgreSQL (media-processing-db) | 5435 / 5432 | Jobs, transcode tasks, upload tasks, outbox |
| Redis | 6379 | Sessions, rate limits, Celery result backend, distributed locks, pub/sub |
| Kafka (KRaft mode) | 9092 | Event streaming (8 topics) |
| MinIO (API) | 9000 | S3-compatible video object storage |
| MinIO (Console) | 9001 | MinIO web UI |
| RabbitMQ (AMQP) | 5672 | Celery task broker |
| RabbitMQ (Management) | 15672 | RabbitMQ web UI |

---

## Kafka Topics

| Topic | Partitions | Producers | Consumers | Purpose |
|-------|------------|-----------|-----------|---------|
| `bucketnotifications` | 4 | MinIO | Video Service | MinIO bucket PUT event notifications |
| `video.queued` | 8 | Video Service | Media Processing Service | Video ready for processing |
| `video.processing` | 4 | Media Processing Service | Video Service | Video processing started |
| `job.completed` | 4 | Media Processing Service | Video Service | Job finished processing successfully |
| `job.failed` | 4 | Media Processing Service | Video Service | Job failed after processing attempts |
| `manifest.generating` | 4 | Media Processing Service | Video Service | Manifest generation started |
| `manifest.completed` | 4 | Media Processing Service | Video Service | Manifest generation completed |
| `manifest.failed` | 4 | Media Processing Service | Video Service | Manifest generation failed |

---

## Security Model

MERIDIAN implements defense-in-depth across five layers:

| Layer | Mechanism | Details |
|-------|-----------|---------|
| Edge | Helmet.js | HTTP security headers (HSTS, X-Frame-Options, CSP, X-Content-Type-Options, etc.) |
| Gateway | JWT + Redis Sessions | Bearer token validation with server-side session lookup |
| Gateway | Rate Limiting | Per-IP and per-user rate limits (Fixed Window or Token Bucket) |
| Inter-Service | HMAC-SHA256 Signing | Every proxied request signed with shared secret, 30s replay window |
| Inter-Service | Constant-Time Comparison | `crypto.timingSafeEqual` prevents timing attacks on signature verification |
| Auth | bcrypt | 12 salt rounds for password hashing |
| Auth | Token Rotation | Single-use refresh tokens; old session deleted on each rotation |
| Cookies | Security Flags | httpOnly, Secure, SameSite=strict, scoped path |
| WebSocket | JWT + Session Lookup | WebSocket upgrade validated via JWT query param + Redis session check |
| WebSocket | HMAC Proxy Signature | WebSocket connections from gateway include HMAC-signed headers |
| Video | Extension Whitelist | Only approved video extensions accepted |
| Data | Database Isolation | Separate PostgreSQL databases per service (4 databases) |
| Data | Redis DB Separation | DB 0: sessions/rate limits, DB 1: Celery results, DB 2: distributed locks (video), DB 3: pub/sub (video), DB 4: distributed locks (media) |

---

## Technology Stack

| Category | Technology | Version |
|----------|-----------|---------|
| **Languages** | TypeScript (Node.js) | Node 20+ |
| | Python | 3.12+ |
| **Frameworks** | Express | 5.2.1 |
| | FastAPI | 0.115.12 |
| **Databases** | PostgreSQL | 16 (Alpine) |
| | Redis | 7 (Alpine) |
| **Object Storage** | MinIO (S3-compatible) | Latest |
| **Message Broker** | Apache Kafka (KRaft mode) | Confluent 7.6.0 |
| **Task Queue** | Celery + RabbitMQ | 5.4.0 / 3.12 |
| **Auth** | bcrypt + jsonwebtoken | 12 rounds / 9.0.3 |
| **ORM (Python)** | SQLModel (SQLAlchemy async) | 0.0.24 |
| **DB Drivers** | pg (Node), asyncpg (Python) | 8.13.1 / 0.30.0 |
| **Redis Clients** | ioredis (Node), redis-py (Python) | 6.0.0 / 5.2.1 |
| **WebSocket** | ws (Node.js proxy) | Latest |
| **Video Processing** | FFmpeg | Latest |
| **Testing** | Jest + pytest + autocannon | 30 / 8.x / latest |
| **Containerization** | Docker Compose | v2 |
| **HTTP Proxy** | http-proxy-middleware | 3.x |

---

## Getting Started

### Prerequisites

- Docker and Docker Compose v2+
- Git

### Quick Start (Docker)

#### Step 1: Clone the Repository

```bash
git clone https://github.com/geraldrolland/Meridian.git
cd Meridian
```

#### Step 2: Start All Services

```bash
docker compose up --build -d
```

This command builds all service images and starts **18 containers**:

| Container | Service | Purpose |
|-----------|---------|---------|
| meridian-api-gateway | API Gateway | Entry point, auth, rate limiting, WebSocket proxy |
| meridian-auth-service | Auth Service | User registration, login, JWT |
| meridian-video-service | Video Service | Video upload, processing lifecycle, WebSocket |
| meridian-video-celery-worker | Video Celery Worker | Processes notifications + queued videos + outbox |
| meridian-video-celery-beat | Video Celery Beat | Periodic task scheduler |
| meridian-media-processing-service | Media Processing Service | FFmpeg pipeline, CMAF transcoding, init segments |
| meridian-media-processing-celery-worker | Media Processing Celery Worker | 7 periodic processing tasks |
| meridian-media-processing-celery-beat | Media Processing Celery Beat | Periodic task scheduler |
| meridian-auth-db | PostgreSQL (auth) | Auth user storage |
| meridian-video-db | PostgreSQL (video) | Video records, outbox |
| meridian-media-processing-db | PostgreSQL (media-processing) | Jobs, tasks, outbox |
| meridian-redis | Redis | Sessions, rate limits, locks, pub/sub |
| meridian-kafka | Kafka (KRaft) | Event streaming |
| meridian-kafka-init | Kafka Init | Creates all 8 topics |
| meridian-minio | MinIO | S3-compatible object storage |
| meridian-minio-init | MinIO Init | Creates viduploads bucket + notification config |
| meridian-rabbitmq | RabbitMQ | Celery task broker |
| meridian-celery-worker | Celery Worker (video) | Processes notifications + queued videos + outbox |

#### Step 3: Verify All Services Are Running

```bash
# Check container status (all should show "Up" or "running")
docker compose ps

# Check service health
docker compose logs api-gateway | grep -i "ready\|listening"
docker compose logs auth-service | grep -i "ready\|listening"
docker compose logs video-service | grep -i "ready\|listening"
docker compose logs media-processing-service | grep -i "ready\|listening"
```

#### Step 4: Test the API Gateway

```bash
# Health check
curl http://localhost:3001/health

# Should return: {"status":"ok"}
```

#### Step 5: Run the End-to-End Test

```bash
# Install Python dependencies (if not already installed)
pip install requests psycopg2-binary

# Run the full E2E test suite
python e2e_test.py
```

The E2E test validates the complete pipeline: register, login, token refresh, profile, video upload, MinIO notification, video status, outbox event, and logout.

#### Step 6: View Logs

```bash
# Follow all logs
docker compose logs -f

# Follow specific service logs
docker compose logs -f api-gateway
docker compose logs -f auth-service
docker compose logs -f video-service
docker compose logs -f video-celery-worker
docker compose logs -f media-processing-service
docker compose logs -f media-processing-celery-worker

# View last 100 lines of a service
docker compose logs --tail 100 api-gateway
```

#### Step 7: Access Service Consoles

| Service | URL | Credentials |
|---------|-----|-------------|
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| RabbitMQ Management | http://localhost:15672 | guest / guest |

#### Step 8: Stop Services

```bash
# Stop all services (preserves volumes)
docker compose down

# Stop all services and remove volumes (fresh start)
docker compose down -v

# Stop and remove images
docker compose down --rmi all
```

### Service URLs

| Service | URL |
|---------|-----|
| API Gateway | http://localhost:3001 |
| API Gateway Health | http://localhost:3001/health |
| Auth Service | http://localhost:4000 |
| Video Service | http://localhost:8000 |
| Media Processing Service | http://localhost:8001 |
| MinIO Console | http://localhost:9001 |
| RabbitMQ Management | http://localhost:15672 |
| Kafka (external) | localhost:9092 |
| Auth DB | localhost:5433 |
| Video DB | localhost:5434 |
| Media Processing DB | localhost:5435 |
| Redis | localhost:6379 |

---

## Local Development

Each service can be developed independently. Prerequisites and full setup instructions are in each service's README.

### API Gateway

```bash
cd api_gateway_service
cp .env.example .env       # configure environment
npm install
npm run dev                # starts on http://localhost:3000
```

Available scripts:

| Command | Description |
|---------|-------------|
| `npm run dev` | Start with hot reload via nodemon + tsx |
| `npm run build` | Compile TypeScript to `dist/` |
| `npm start` | Run compiled production build |
| `npm test` | Run all Jest tests |
| `npm run test:unit` | Unit tests only |
| `npm run test:integration` | Integration tests (requires Redis) |
| `npm run test:smoke` | Smoke tests (requires running server) |
| `npm run test:all` | Unit + integration + smoke |
| `npm run test:load` | Load test with autocannon |
| `npm run test:perf` | Performance benchmarks |

### Auth Service

```bash
cd auth_service
cp .env.example .env       # configure environment
npm install
npm run dev                # starts on http://localhost:4000
```

Migrations run automatically at server startup via `start.sh` (Docker) or `runMigrations()` in code.

Available scripts:

| Command | Description |
|---------|-------------|
| `npm run dev` | Start with hot reload via nodemon + tsx |
| `npm run build` | Compile TypeScript to `dist/` |
| `npm start` | Run compiled production build |
| `npm test` | Run all Jest tests |
| `npm run test:unit` | Unit tests only |

### Video Service

```bash
cd video_service
cp .env.example .env       # configure environment
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Media Processing Service

The media processing service has three components: the FastAPI web server, Celery worker, and Celery beat scheduler.

```bash
cd media_processing_service
cp .env.example .env       # configure environment
pip install -r requirements.txt

# Terminal 1: FastAPI server + Kafka consumer
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Terminal 2: Celery worker (processes all 7 periodic tasks)
celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo

# Terminal 3: Celery beat (periodic task scheduler)
celery -A app.celery_app:celery_app beat --loglevel=info
```

---

## Testing

### Unit and Integration Tests

```bash
# API Gateway (Jest + TypeScript)
cd api_gateway_service
npm test

# Auth Service (Jest + TypeScript)
cd auth_service
npm test

# Video Service (pytest + Python)
cd video_service
python -m pytest tests/ -v
```

### Video Service Test Coverage

| Module | Tests |
|--------|-------|
| Middleware (proxy signature + session) | 7 tests |
| MinIO client (presigned POST) | 2 tests |
| Multipart upload functions | 4 tests |
| Process notifications task | 9 tests |
| Ready endpoint | 6 tests |
| Upload endpoint | 8 tests |
| Video/Upload models | 14 tests |
| Lock system | 6 tests |
| Producer | 4 tests |
| **Total** | **60 tests** |

### Load and Performance Testing

```bash
# API Gateway load tests (autocannon)
cd api_gateway_service
npm run test:load
npm run test:perf
```

### End-to-End Testing

```bash
# Full pipeline validation (requires all services running via Docker Compose)
pip install requests psycopg2-binary
python e2e_test.py
```

The E2E test validates the complete request pipeline across all services:

1. Invalid route handling (404)
2. User registration
3. User login (JWT + refresh cookie)
4. Token refresh (single-use rotation)
5. Authenticated profile retrieval
6. Video upload initiation
7. Direct MinIO upload via presigned POST
8. Non-video extension rejection (422)
9. Bucket notification processing (Kafka)
10. Video status polling (state machine)
11. Outbox event processing
12. Job creation in media-processing-db
13. Transcode tasks + segments on disk
14. Upload tasks created and completed
15. Objects in vidsegments bucket (MinIO)
16. Job status = COMPLETED
17. Outbox job.completed event published
18. Temp file cleanup verification (segments, transcoded, downloads, thumbnails)
19. Failure flow: seed FAILED job, process_failed_jobs, job.failed event, object cleanup, video status=FAILED
20. Retry flow: seed RETRY video, retry endpoint, status transitions
21. User logout (session invalidation)

---

## Project Structure

```
MERIDIAN/
├── api_gateway_service/              # Express TypeScript API Gateway (Port 3001)
│   ├── src/
│   │   ├── config/                   # Centralized configuration
│   │   │   ├── index.ts              # Environment-based config
│   │   │   └── redis.ts              # Redis client (ioredis)
│   │   ├── handlers/                 # Route handlers
│   │   │   └── refreshToken.ts       # Token refresh endpoint
│   │   ├── middleware/               # Auth, CORS, logger, error handler, rate limiting
│   │   │   ├── auth.ts               # JWT authentication middleware
│   │   │   ├── cors.ts               # CORS configuration
│   │   │   ├── errorHandler.ts       # Global error handler
│   │   │   ├── logger.ts             # Winston logger + request logging
│   │   │   └── ratelimit/            # Fixed window + token bucket (Lua script)
│   │   │       ├── index.ts
│   │   │       ├── fixedWindow.ts
│   │   │       ├── tokenBucket.ts
│   │   │       └── utils.ts
│   │   ├── proxy/                    # HTTP proxy + HMAC-SHA256 signing
│   │   │   └── index.ts
│   │   ├── types/                    # TypeScript type definitions
│   │   │   └── index.ts
│   │   └── server.ts                 # Express app bootstrap + startup
│   ├── tests/                        # Unit, smoke, performance tests
│   ├── Dockerfile                    # Multi-stage Node 20 Alpine build
│   ├── package.json
│   └── tsconfig.json
│
├── auth_service/                     # Express TypeScript Auth Service (Port 4000)
│   ├── src/
│   │   ├── config/                   # Config, database (pg), Redis (ioredis)
│   │   │   ├── index.ts
│   │   │   ├── database.ts
│   │   │   └── redis.ts
│   │   ├── middleware/               # HMAC verification, session extraction
│   │   │   ├── checkProxySignature.ts
│   │   │   ├── errorHandler.ts
│   │   │   ├── getUserSession.ts
│   │   │   └── requestLogger.ts
│   │   ├── routes/                   # Auth endpoints + readiness probe
│   │   │   ├── auth.ts
│   │   │   └── ready.ts
│   │   ├── types/                    # TypeScript type definitions
│   │   │   └── index.ts
│   │   └── server.ts                 # Express app bootstrap + startup
│   ├── migrations/                   # SQL migration files
│   │   └── 001_create_users.sql
│   ├── tests/                        # Unit tests
│   │   └── unit/
│   ├── Dockerfile                    # Multi-stage Node 20 Alpine build
│   ├── start.sh                      # Container entrypoint (migrations + server)
│   ├── package.json
│   └── tsconfig.json
│
├── video_service/                    # FastAPI Python Video Service (Port 8000)
│   ├── app/
│   │   ├── config.py                 # pydantic-settings configuration
│   │   ├── database.py               # Async SQLAlchemy engine
│   │   ├── database_sync.py          # Sync engine for Celery tasks
│   │   ├── consumers/
│   │   │   ├── __init__.py           # Re-exports all consumers
│   │   │   ├── base.py               # AppRebalanceListener
│   │   │   ├── notification_consumer.py    # bucketnotifications → QUEUED
│   │   │   ├── processing_consumer.py      # video.processing → PROCESSING
│   │   │   ├── failure_consumer.py         # job.failed/manifest.failed → FAILED
│   │   │   ├── manifest_generating_consumer.py  # manifest.generating
│   │   │   └── manifest_completed_consumer.py   # manifest.completed → COMPLETED
│   │   ├── producer.py               # KafkaProducer (auto event_id/timestamp)
│   │   ├── minio_client.py           # MinIO presigned URLs + multipart
│   │   ├── celery_app.py             # Celery configuration (video queue routing)
│   │   ├── tasks.py                  # process_notifications, queued_videos, outbox, failed
│   │   ├── lock.py                   # Redis distributed locks (PROCESS + COMMIT)
│   │   ├── main.py                   # FastAPI app bootstrap + startup/shutdown
│   │   ├── websocket.py              # WebSocket manager + Redis pub/sub
│   │   ├── middleware/               # Proxy signature + session verification
│   │   │   ├── check_proxy_signature.py
│   │   │   └── get_user_session.py
│   │   ├── models/                   # SQLModel: video, notification, outbox, session
│   │   │   ├── video.py              # VideoStatus: 7 states + published field
│   │   │   ├── notification.py       # BucketNotificationEvent (FK video_id)
│   │   │   ├── outbox.py             # Outbox (FK video_id)
│   │   │   ├── events.py
│   │   │   └── session.py
│   │   ├── routes/                   # Video endpoints + health/readiness + WebSocket
│   │   │   ├── video.py
│   │   │   └── ready.py
│   │   └── utils/                    # S3 key extraction helpers
│   │       └── notification_utils.py
│   ├── tests/                        # pytest unit tests (60 tests)
│   ├── Dockerfile                    # Python 3.12-slim
│   ├── Dockerfile.celery             # Celery worker/beat image
│   ├── requirements.txt
│   └── start.sh                      # Container entrypoint (uvicorn)
│
├── media_processing_service/         # FastAPI + Celery Python 3.12 (Port 8001)
│   ├── app/
│   │   ├── main.py                   # FastAPI application entry point
│   │   ├── celery_app.py             # Celery configuration + beat schedule (7 tasks)
│   │   ├── config.py                 # Pydantic settings (env-based)
│   │   ├── consumer.py               # Kafka consumer (video.queued)
│   │   ├── producer.py               # Singleton sync Kafka producer
│   │   ├── lock.py                   # Redis distributed lock (PROCESSING + COMMITTING)
│   │   ├── utils.py                  # build_object_url, resolve_object_key, get_video_duration
│   │   ├── db_config/
│   │   │   ├── __init__.py
│   │   │   ├── database.py           # Async engine + session factory
│   │   │   └── database_sync.py      # Sync engine for Celery tasks
│   │   ├── media_service/
│   │   │   ├── __init__.py
│   │   │   ├── segmentation.py       # FFmpeg video segmentation
│   │   │   ├── thumbnail.py          # FFmpeg thumbnail generation
│   │   │   ├── transcoder.py         # CMAF multi-rendition transcoding (360p-1080p)
│   │   │   ├── generate_init.py      # CMAF init segment generation (video + audio)
│   │   │   └── cleanup.py            # Singleton MinIO + temp file cleanup
│   │   ├── minio_client/
│   │   │   └── __init__.py           # download, upload, delete (MinIO SDK)
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── job.py                # Job table + JobStatus enum
│   │   │   ├── transcode_task.py     # TranscodeTask table + TranscodeTaskStatus
│   │   │   ├── upload_task.py        # UploadTask table + UploadStatus
│   │   │   ├── outbox.py             # Transactional Outbox table + OutboxStatus
│   │   │   └── event.py              # Pydantic model for incoming Kafka events
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── health.py             # GET /health
│   │   │   └── ready.py              # GET /ready (checks DB + Redis)
│   │   └── tasks/
│   │       ├── __init__.py
│   │       ├── process_queued_jobs.py        # Download, segment, create TranscodeTasks
│   │       ├── process_transcode_tasks.py    # Transcode segments into renditions
│   │       ├── process_upload_tasks.py       # Upload to MinIO vidsegments
│   │       ├── check_completed_jobs.py       # Verify completion, mark COMPLETED
│   │       ├── process_outbox_events.py      # Publish outbox events to Kafka
│   │       ├── process_failed_jobs.py        # Cleanup failed jobs, publish job.failed
│   │       └── process_completed_jobs.py     # Cleanup completed jobs, publish job.completed
│   ├── .env.example
│   ├── requirements.txt
│   ├── Dockerfile                    # FastAPI web server + Kafka consumer
│   ├── Dockerfile.celery             # Celery worker (solo pool)
│   └── start.sh
│
├── docker-compose.yml                # Full-stack orchestration (18 containers)
├── e2e_test.py                       # End-to-end test script
├── .gitignore
└── README.md
```

---

## Design Patterns

| Pattern | Implementation | Benefit |
|---------|---------------|---------|
| **Transactional Outbox** | Outbox table in video_db and media_processing_db with Celery beat publisher | Reliable event delivery even during Kafka outages |
| **Distributed Locking** | Redis locks with TTL via `lock.py` (dual-lock: PROCESSING + COMMITTING, nested pattern) | Prevents duplicate task processing across workers |
| **Token Bucket** | Atomic Redis Lua script in API Gateway | Burst-tolerant rate limiting without race conditions |
| **Singleton** | Singleton pattern for MinIO client and Kafka producer in media_processing_service | Ensures single instance across Celery worker processes |
| **Presigned URLs** | MinIO presigned POST/PUT | Client uploads bypass application server for large files |
| **CQRS (implicit)** | Separate read/write paths via async event processing | Decouples upload from processing |
| **Circuit Breaker** | Celery retry with backoff + outbox retry logic (5 retries, 2-min backoff) | Graceful degradation during broker failures |
| **Middleware Pipeline** | Express middleware chain in API Gateway | Composable, order-dependent request processing |
| **Health Probes** | `/health` and `/ready` endpoints per service | Kubernetes-ready liveness and readiness checks |
| **WebSocket Pub/Sub** | Shared Redis pub/sub on `video:notification` channel | Cross-instance real-time push to WebSocket clients |

---

## Environment Variables

### API Gateway

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 3000 | Server port |
| `HOST` | 127.0.0.1 | Bind address |
| `REDIS_HOST` | 127.0.0.1 | Redis host |
| `REDIS_PORT` | 6379 | Redis port |
| `REDIS_DB` | 0 | Redis database number |
| `JWT_SECRET` | -- | Shared JWT signing secret |
| `PROXY_SECRET` | -- | HMAC-SHA256 proxy signing secret |
| `AUTH_EXCLUDE_PATHS` | `/health,/api/auth/refresh-token,...` | Paths bypassing JWT auth |
| `RATE_LIMIT_WINDOW_MS` | 900000 | Rate limit window (15 min) |
| `RATE_LIMIT_MAX` | 100 | Max requests per window |
| `ROUTES` | `[]` | JSON array of route configurations |
| `CORS_ORIGIN` | * | Allowed CORS origins |
| `LOG_LEVEL` | info | Winston log level |

### Auth Service

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 4000 | Server port |
| `HOST` | 127.0.0.1 | Bind address |
| `DB_HOST` | 127.0.0.1 | PostgreSQL host |
| `DB_PORT` | 5432 | PostgreSQL port |
| `DB_USER` | postgres | Database user |
| `DB_PASSWORD` | -- | Database password |
| `DB_NAME` | auth_db | Database name |
| `REDIS_HOST` | 127.0.0.1 | Redis host |
| `REDIS_PORT` | 6379 | Redis port |
| `REDIS_PASSWORD` | (empty) | Redis password |
| `REDIS_DB` | 0 | Redis database number |
| `JWT_SECRET` | -- | JWT signing secret |
| `ACCESS_TOKEN_EXPIRY` | 7m | Access token TTL |
| `REFRESH_TOKEN_EXPIRY` | 7d | Refresh token TTL |
| `REFRESH_TOKEN_MAX_AGE` | 604800000 | Refresh cookie Max-Age (ms, 7 days) |
| `PROXY_SECRET` | -- | HMAC proxy verification secret |
| `LOG_LEVEL` | info | Winston log level |

### Video Service

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | -- | PostgreSQL async connection string |
| `KAFKA_BOOTSTRAP_SERVERS` | localhost:9092 | Kafka broker addresses |
| `KAFKA_TOPIC` | bucketnotifications | Kafka topic for MinIO events |
| `KAFKA_CONSUMER_GROUP_ID` | meridian-video-consumer-group | Consumer group ID |
| `KAFKA_AUTO_OFFSET_RESET` | earliest | Offset reset policy |
| `MINIO_ENDPOINT` | localhost:9000 | MinIO endpoint |
| `MINIO_ACCESS_KEY` | minioadmin | MinIO access key |
| `MINIO_SECRET_KEY` | minioadmin | MinIO secret key |
| `MINIO_BUCKET` | viduploads | MinIO bucket name |
| `MINIO_SECURE` | false | Use HTTPS for MinIO |
| `PROXY_SECRET` | -- | HMAC proxy verification secret |
| `CELERY_BROKER_URL` | -- | RabbitMQ connection string |
| `CELERY_RESULT_BACKEND` | -- | Redis URL for Celery results |
| `REDIS_HOST` | redis | Redis host |
| `REDIS_PORT` | 6379 | Redis port |
| `REDIS_DB` | 3 | Redis database for pub/sub |
| `JWT_SECRET` | -- | JWT signing secret (for WebSocket auth) |
| `ALLOWED_VIDEO_EXTENSIONS` | mp4,mov,avi,mkv,webm,flv,wmv | Comma-separated allowed extensions |
| `MULTIPART_THRESHOLD` | 104857600 | File size (bytes) for multipart switch (100 MB) |
| `DEFAULT_PART_SIZE` | 5242880 | Part size (bytes) for multipart uploads (5 MB) |
| `LOG_LEVEL` | info | Python logging level |

### Media Processing Service

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | -- | PostgreSQL async connection string |
| `KAFKA_BOOTSTRAP_SERVERS` | kafka:29092 | Kafka broker addresses |
| `KAFKA_TOPIC` | video.queued | Incoming video topic |
| `KAFKA_CONSUMER_GROUP_ID` | meridian-media-processing-consumer-group | Consumer group ID |
| `KAFKA_AUTO_OFFSET_RESET` | earliest | Offset reset policy |
| `REDIS_HOST` | redis | Redis host for distributed locks |
| `REDIS_PORT` | 6379 | Redis port |
| `MINIO_ENDPOINT` | minio:9000 | MinIO endpoint |
| `MINIO_ACCESS_KEY` | minioadmin | MinIO access key |
| `MINIO_SECRET_KEY` | minioadmin | MinIO secret key |
| `MINIO_DOWNLOAD_BUCKET` | viduploads | Bucket to download original videos from |
| `MINIO_UPLOAD_BUCKET` | vidsegments | Bucket for transcoded segments |
| `MINIO_THUMBNAIL_BUCKET` | vidthumbnails | Bucket for thumbnails |
| `MINIO_SECURE` | false | Use HTTPS for MinIO |
| `CELERY_BROKER_URL` | amqp://guest:guest@rabbitmq:5672// | RabbitMQ broker |
| `CELERY_RESULT_BACKEND` | redis://redis:6379/1 | Redis for Celery results |
| `SEGMENT_DURATION` | 6 | Segment duration in seconds |
| `SEGMENT_PREFIX` | seg_ | Filename prefix for generated segments |
| `LOG_LEVEL` | info | Python logging level |

---

## License

ISC
