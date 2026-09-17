# MERIDIAN

A production-grade microservices-based video processing platform built with Express, FastAPI, PostgreSQL, Redis, Kafka, and MinIO.

MERIDIAN provides a complete pipeline for user authentication, video upload (with direct-to-storage presigned URLs and multipart support), asynchronous event-driven processing via Kafka and Celery, and reliable event dispatch using the Transactional Outbox pattern with distributed Redis locking.

---

## Architecture Overview

`
                          +----------------+
                          |     Redis      |
                          | (sessions,     |
                          |  rate limits,  |
                          |  locks)        |
                          +-------+--------+
                                  |
+----------+  +-----------+       |  +-------------+  +----------------+
|          |  |           |       |  |             |  |                |
|  Client  +->+ API       +-------+--+ Auth        |  | Video          |
|          |  | Gateway   |       |  | Service     |  | Service        |
+----------+  | :3001     |       |  | :4000       |  | :8000          |
              +-----+-----+       |  +------+------+  +-------+--------+
                    |             |         |                  |
                    |             |         |         +--------+--------+
                    |             |         |         |                 |
                    |             |         |   +-----+------+  +------+------+
                    |             |         |   | PostgreSQL  |  |   MinIO     |
                    |             |         |   | auth_db     |  |  :9000      |
                    |             |         |   | video_db    |  | (S3 compat) |
                    |             |         |   +------------+  +------+------+
                    |             |         |                            |
                    |             |         |                     +------+------+
                    |             |         |                     |   Kafka     |
                    |             |         |                     |   :9092     |
                    |             |         |                     +------+------+
                    |             |         |                            |
                    |             |         |                     +------+------+
                    |             |         +-------------------->+|  MinIO     |
                    |             |         |   Bucket Notifs     || (Producer) |
                    |             |         |                     +-------------+
                    |             |
                    |       +-----+------+    +-----------+
                    +------+  RabbitMQ   +----+  Celery   |
                           |  :5672     |    | (worker + |
                           +------------+    |   beat)   |
                                             +-----------+
`

---

## System Architecture

### API Gateway (Port 3001)

The single entry point for all client requests. Built with Express and TypeScript, it handles cross-cutting concerns before forwarding to upstream services.

**Middleware Pipeline (executed in order):**

1. **Helmet** -- HTTP security headers (X-Content-Type-Options, X-Frame-Options, Strict-Transport-Security, etc.)
2. **CORS** -- Configurable cross-origin resource sharing with credentials support
3. **Request Logger** -- Structured JSON logging via Winston with request/response metadata
4. **Cookie Parser** -- Parses incoming cookies for session extraction
5. **JWT Auth Middleware** -- Validates Bearer tokens, looks up Redis sessions, populates eq.user
6. **Rate Limiter** -- Per-route rate limiting with two strategies: Fixed Window and Token Bucket
7. **Proxy Router** -- http-proxy-middleware with HMAC-SHA256 request signing
8. **Body Parser** -- Express JSON parser (applied after proxy to preserve raw streams)
9. **Error Handler** -- Global error handler with structured error responses

**HMAC-SHA256 Proxy Signing:**

Every request forwarded to an upstream service is signed with:
- x-proxy-signature: HMAC-SHA256 of "{METHOD}:{URL}:{TIMESTAMP}" using a shared secret
- x-proxy-timestamp: Current Unix timestamp (30-second replay window)

Upstream services verify this signature before processing, preventing unauthorized inter-service calls.

**Rate Limiting Strategies:**

| Strategy | Algorithm | Best For |
|----------|-----------|----------|
| Fixed Window | Counter per time window | Simple, predictable limits |
| Token Bucket | Atomic Redis Lua script | Burst-tolerant, smooth throttling |

The Token Bucket implementation uses an atomic Lua script executed in Redis, handling concurrent requests without race conditions. It supports configurable refill rates and bucket capacities per route.

**Route Configuration:**

Routes are defined via the ROUTES environment variable as a JSON array:
`json
[
  { "prefix": "/api/auth", "target": "http://auth-service:4000" },
  { "prefix": "/api/video", "target": "http://video-service:8000" }
]
`

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

`
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
`

- **Access Token**: 7-minute expiry, returned in response body
- **Refresh Token**: 7-day expiry, set as httpOnly, Secure, SameSite=strict cookie scoped to /api/auth/refresh-token
- **Session Storage**: Redis key session:<UUID> with JSON payload { userId, email } and 7-day TTL
- **Token Rotation**: Each refresh creates a new session UUID and deletes the old one (single-use tokens)

**Database Schema:**

`sql
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(255) UNIQUE NOT NULL,
    hash_password VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
`

---

### Video Service (Port 8000)

Manages video upload, storage, and the async processing lifecycle. Built with FastAPI (async Python), backed by PostgreSQL, MinIO, Kafka, and Celery.

**API Endpoints:**

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | /api/video/upload | Create video + generate upload data | Yes |
| POST | /api/video/{id}/upload/complete | Finalize multipart upload | Yes |
| POST | /api/video/{id}/upload/abort | Discard multipart upload | Yes |
| GET | /ready | Database readiness probe | No |

**Upload Flow:**

`
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
  |                         |-- Create Outbox    |                    |
  |                         |                    |                    |
  |                    [Celery beat: process_outbox_events]           |
  |                         |-- Publish to Kafka +------------------->|
  |                         |   (distributed lock)                    |
`

**Upload Modes:**

| Mode | Condition | Mechanism |
|------|-----------|-----------|
| Presigned POST | file_size <= threshold | Single PUT directly to MinIO |
| Multipart | file_size > threshold | Server-initiated multipart with presigned PUT per part |

Supported extensions: mp4, mov, vi, mkv, webm, lv, wmv

**Video State Machine:**

`
AWAITING_UPLOAD --> QUEUED --> PROCESSING --> COMPLETED
                        |           |
                        +--> FAILED (outbox retry exhaustion)
`

**Transactional Outbox Pattern:**

Ensures reliable event publishing to Kafka even during broker outages:

1. When a notification is processed, an Outbox record is created in the same database transaction as the video status update
2. A separate Celery beat task (process_outbox_events, every 10s) polls PENDING outbox records
3. Events are published to Kafka with distributed Redis locks to prevent duplicate processing
4. Failed events are retried up to 5 times with 2-minute backoff intervals
5. After 5 failures, the event is marked FAILED and the associated video status is set to FAILED

**Distributed Locking:**

Redis-based locks with 2-minute TTL prevent duplicate task processing across Celery workers. The lock is acquired before processing and released in a inally block to ensure cleanup.

---

### Infrastructure

| Service | Port (Host / Container) | Purpose |
|---------|------------------------|---------|
| PostgreSQL (auth-db) | 5433 / 5432 | Auth user storage |
| PostgreSQL (video-db) | 5434 / 5432 | Video records, notifications, outbox |
| Redis | 6379 | Sessions, rate limits, Celery result backend, distributed locks |
| Kafka (KRaft) | 9092 | Bucket notification events (topic: ucketnotifications, 4 partitions) |
| MinIO | 9000 (API) / 9001 (Console) | S3-compatible video object storage |
| RabbitMQ | 5672 (AMQP) / 15672 (Management) | Celery task broker |
| Celery Worker | -- | Processes notification and outbox events |
| Celery Beat | -- | Periodic task scheduler (15s notifications, 10s outbox) |

**Init Containers:**
- kafka-init: Creates the ucketnotifications topic with 4 partitions
- minio-init: Creates the iduploads bucket and configures MinIO-to-Kafka SQS notification

---

## Security Model

MERIDIAN implements defense-in-depth across five layers:

| Layer | Mechanism | Details |
|-------|-----------|---------|
| Edge | Helmet.js | HTTP security headers (HSTS, X-Frame-Options, CSP, etc.) |
| Gateway | JWT + Redis Sessions | Bearer token validation with server-side session lookup |
| Gateway | Rate Limiting | Per-IP and per-user rate limits (Fixed Window or Token Bucket) |
| Inter-Service | HMAC-SHA256 Signing | Every proxied request signed with shared secret, 30s replay window |
| Inter-Service | Constant-Time Comparison | crypto.timingSafeEqual prevents timing attacks on signature verification |
| Auth | bcrypt | 12 salt rounds for password hashing |
| Auth | Token Rotation | Single-use refresh tokens; old session deleted on each rotation |
| Cookies | Security Flags | httpOnly, Secure, SameSite=strict, scoped path |
| Video | Extension Whitelist | Only approved video extensions accepted |
| Data | Database Isolation | Separate PostgreSQL databases per service |
| Data | Redis DB Separation | DB 0: sessions/rate limits, DB 1: Celery results, DB 2: distributed locks |

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
| **Testing** | Jest + pytest + autocannon | 30 / 8.x / latest |
| **Containerization** | Docker Compose | v2 |
| **HTTP Proxy** | http-proxy-middleware | 3.x |

---

## Getting Started

### Prerequisites

- Docker and Docker Compose v2+
- Git

### Quick Start (Docker)

`ash
# Clone the repository
git clone https://github.com/geraldrolland/Meridian.git
cd Meridian

# Start all services
docker compose up --build -d

# View logs
docker compose logs -f

# Stop all services
docker compose down
`

**Service URLs after startup:**

| Service | URL |
|---------|-----|
| API Gateway | http://localhost:3001 |
| MinIO Console | http://localhost:9001 |
| RabbitMQ Management | http://localhost:15672 |
| Kafka (external) | localhost:9092 |
| Auth DB | localhost:5433 |
| Video DB | localhost:5434 |

### Local Development (Individual Services)

Each service can be developed independently. Prerequisites and full setup instructions are in each service's README.

**API Gateway:**
`ash
cd api_gateway_service
cp .env.example .env  # configure environment
npm install
npm run dev
`

**Auth Service:**
`ash
cd auth_service
cp .env.example .env  # configure environment
npm install
npm run dev
`

**Video Service:**
`ash
cd video_service
cp .env.example .env  # configure environment
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
`

---

## Testing

### Unit and Integration Tests

`ash
# API Gateway (Jest + TypeScript)
cd api_gateway_service
npm test

# Auth Service (Jest + TypeScript)
cd auth_service
npm test

# Video Service (pytest + Python)
cd video_service
pytest
`

### Load and Performance Testing

`ash
# API Gateway load tests (autocannon)
cd api_gateway_service
npm run test:performance
`

### End-to-End Testing

`ash
# Full pipeline validation (requires all services running via Docker Compose)
python e2e_test.py
`

The E2E test validates the complete request pipeline across all services:

1. Invalid route handling (404)
2. User registration
3. User login (JWT + refresh cookie)
4. Token refresh (single-use rotation)
5. Authenticated profile retrieval
6. Video upload initiation
7. Direct MinIO upload
8. Non-video extension rejection
9. Bucket notification processing (Kafka)
10. Video status polling (state machine)
11. Outbox event processing
12. User logout (session invalidation)

---

## Project Structure

`
MERIDIAN/
|
+-- api_gateway_service/          # Express TypeScript API Gateway
|   +-- src/
|   |   +-- config/               # Centralized configuration
|   |   +-- handlers/             # Route handlers
|   |   +-- middleware/            # Auth, CORS, logger, error handler, rate limiting
|   |   |   +-- ratelimit/        # Fixed window + token bucket (Lua script)
|   |   +-- proxy/                # HTTP proxy + HMAC-SHA256 signing
|   |   +-- types/                # TypeScript type definitions
|   +-- tests/                    # Unit, smoke, performance tests
|   +-- Dockerfile                # Multi-stage Node 20 Alpine build
|   +-- package.json
|   +-- tsconfig.json
|
+-- auth_service/                 # Express TypeScript Auth Service
|   +-- src/
|   |   +-- config/               # Config, database (pg), Redis (ioredis)
|   |   +-- middleware/            # HMAC verification, session extraction
|   |   +-- routes/               # Auth endpoints + readiness probe
|   |   +-- types/                # TypeScript type definitions
|   +-- migrations/               # SQL migration files
|   +-- tests/                    # Unit tests
|   +-- Dockerfile                # Multi-stage Node 20 Alpine build
|   +-- start.sh                  # Container entrypoint (migrations + server)
|   +-- package.json
|   +-- tsconfig.json
|
+-- video_service/                # FastAPI Python Video Service
|   +-- app/
|   |   +-- middleware/            # Proxy signature + session verification
|   |   +-- models/               # SQLModel: video, notification, outbox, session
|   |   +-- routes/               # Video endpoints + health/readiness
|   |   +-- utils/                # S3 key extraction helpers
|   |   +-- config.py             # pydantic-settings configuration
|   |   +-- database.py           # Async SQLAlchemy engine
|   |   +-- consumer.py           # Kafka consumer (bucket notifications)
|   |   +-- producer.py           # Kafka producer
|   |   +-- minio_client.py       # MinIO presigned URLs + multipart
|   |   +-- celery_app.py         # Celery configuration + beat schedule
|   |   +-- tasks.py              # process_notifications, process_outbox_events
|   |   +-- lock.py               # Redis distributed locks
|   +-- tests/                    # pytest unit tests
|   +-- Dockerfile                # Python 3.12-slim
|   +-- Dockerfile.celery         # Celery worker/beat image
|   +-- requirements.txt
|   +-- start.sh                  # Container entrypoint (uvicorn)
|
+-- docker-compose.yml            # Full-stack orchestration (11 services)
+-- e2e_test.py                   # End-to-end test script
+-- .gitignore
+-- README.md
`

---

## Design Patterns

| Pattern | Implementation | Benefit |
|---------|---------------|---------|
| **Transactional Outbox** | Outbox table in video_db with Celery beat publisher | Reliable event delivery even during Kafka outages |
| **Distributed Locking** | Redis locks with TTL via lock.py | Prevents duplicate task processing across workers |
| **Token Bucket** | Atomic Redis Lua script in API Gateway | Burst-tolerant rate limiting without race conditions |
| **Presigned URLs** | MinIO presigned POST/PUT | Client uploads bypass application server for large files |
| **CQRS (implicit)** | Separate read/write paths via async event processing | Decouples upload from processing |
| **Circuit Breaker** | Celery retry with backoff + outbox retry logic | Graceful degradation during broker failures |
| **Middleware Pipeline** | Express middleware chain in API Gateway | Composable, order-dependent request processing |
| **Health Probes** | /health and /readiness endpoints per service | Kubernetes-ready liveness and readiness checks |

---

## Environment Variables

### API Gateway

| Variable | Default | Description |
|----------|---------|-------------|
| PORT | 3000 | Server port |
| HOST | 127.0.0.1 | Bind address |
| REDIS_HOST | 127.0.0.1 | Redis host |
| REDIS_PORT | 6379 | Redis port |
| REDIS_DB | 0 | Redis database number |
| JWT_SECRET | -- | Shared JWT signing secret |
| PROXY_SECRET | -- | HMAC-SHA256 proxy signing secret |
| AUTH_EXCLUDE_PATHS | /health,/api/auth/refresh-token,... | Paths bypassing JWT auth |
| RATE_LIMIT_WINDOW_MS | 900000 | Rate limit window (15 min) |
| RATE_LIMIT_MAX | 100 | Max requests per window |
| ROUTES | [] | JSON array of route configurations |
| CORS_ORIGIN | * | Allowed CORS origins |
| LOG_LEVEL | info | Winston log level |

### Auth Service

| Variable | Default | Description |
|----------|---------|-------------|
| PORT | 4000 | Server port |
| DB_HOST | 127.0.0.1 | PostgreSQL host |
| DB_PORT | 5432 | PostgreSQL port |
| DB_USER | postgres | Database user |
| DB_PASSWORD | -- | Database password |
| DB_NAME | auth_db | Database name |
| REDIS_HOST | 127.0.0.1 | Redis host |
| JWT_SECRET | -- | JWT signing secret |
| PROXY_SECRET | -- | HMAC proxy verification secret |

### Video Service

| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL | -- | PostgreSQL async connection string |
| KAFKA_BOOTSTRAP_SERVERS | localhost:9092 | Kafka broker addresses |
| KAFKA_TOPIC | bucketnotifications | Kafka topic for MinIO events |
| KAFKA_CONSUMER_GROUP_ID | meridian-video-consumer-group | Consumer group ID |
| MINIO_ENDPOINT | localhost:9000 | MinIO endpoint |
| MINIO_ACCESS_KEY | minioadmin | MinIO access key |
| MINIO_SECRET_KEY | minioadmin | MinIO secret key |
| MINIO_BUCKET | viduploads | MinIO bucket name |
| PROXY_SECRET | -- | HMAC proxy verification secret |
| CELERY_BROKER_URL | -- | RabbitMQ connection string |
| CELERY_RESULT_BACKEND | -- | Redis URL for Celery results |

---

## License

ISC