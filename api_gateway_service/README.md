# MERIDIAN API Gateway

A production-grade reverse proxy API gateway built with Express, TypeScript, and Redis. Handles authentication, rate limiting, request logging, and routes traffic to upstream microservices.

## Overview

The API Gateway sits in front of your backend services and provides:

- **Reverse Proxy** — routes requests to upstream services based on configurable path prefixes
- **WebSocket Proxy** — proxies WebSocket connections with JWT + Redis session validation
- **JWT Authentication** — validates Bearer tokens and enforces session-based auth via Redis
- **Rate Limiting** — per-route rate limiting with fixed window or token bucket strategies
- **CORS** — configurable cross-origin resource sharing
- **Structured Logging** — JSON-formatted incoming request and response logging via Winston
- **Request Validation** — HMAC-signed proxy headers for upstream verification
- **Security Headers** — Helmet.js for HTTP security headers

## Architecture

```
                          ┌─────────────────┐
                          │      Redis       │
                          │  (sessions,      │
                          │   rate limits)   │
                          └────────┬────────┘
                                   │
┌──────────┐    ┌─────────────┐    │    ┌──────────────┐
│  Client  │───▶│ API Gateway │────┼───▶│ User Service │
│ (HTTP)   │    │  (port 3000)│    │    └──────────────┘
└──────────┘    └──────┬──────┘    │
                       │           │    ┌──────────────┐
┌──────────┐           │           └───▶│ Video Service│
│  Client  │───(WS)───┤                └──────────────┘
│ (Browser)│           │
└──────────┘           │           ┌──────────────┐
                       └──────────▶│ Auth Service  │
                                   └──────────────┘
```

## Prerequisites

- **Node.js** 20+
- **Redis** 7+
- **Docker** and **Docker Compose** (optional, for containerised deployment)

## Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd api_gateway_service

# Install dependencies
npm install

# Copy environment variables
cp .env.example .env

# Configure routes in .env, then start
npm run dev
```

The gateway starts on `http://127.0.0.1:3000` by default.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Server port | `3000` |
| `HOST` | Bind address | `127.0.0.1` |
| `CORS_ORIGIN` | Allowed origins (`*` or comma-separated) | `*` |
| `CORS_METHODS` | Allowed HTTP methods | `GET,POST,PUT,PATCH,DELETE,OPTIONS` |
| `CORS_HEADERS` | Allowed headers | `Content-Type,Authorization,X-Request-ID` |
| `CORS_CREDENTIALS` | Allow credentials | `false` |
| `JWT_SECRET` | Secret for JWT signing/verification | `change-me-in-production` |
| `AUTH_EXCLUDE_PATHS` | Comma-separated paths exempt from auth | `/health,/ready,/api/auth/login,/api/auth/register` |
| `RATE_LIMIT_WINDOW_MS` | Global rate limit window (ms) | `900000` (15 min) |
| `RATE_LIMIT_MAX` | Global max requests per window | `100` |
| `LOG_LEVEL` | Winston log level | `info` |
| `REDIS_HOST` | Redis host | `127.0.0.1` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis password | (empty) |
| `REDIS_DB` | Redis database number | `0` |
| `PROXY_SECRET` | HMAC secret for signed proxy headers | `change-me-in-production` |
| `ROUTES` | JSON array of route definitions | `[]` |
| `CACHE_ROUTES` | Comma-separated path prefixes cached for GET (JSON, 200) | `/api/video` |
| `CACHE_TTL` | Response cache TTL in seconds | `420` (7 min) |

### Route Configuration

Routes are defined as a JSON array in the `ROUTES` environment variable:

```json
[
  {
    "prefix": "/api/auth",
    "target": "http://localhost:4002",
    "rateLimit": {
      "strategy": "fixedWindow",
      "windowMs": 900000,
      "max": 100
    }
  },
  {
    "prefix": "/api/video",
    "target": "http://localhost:4002",
    "rateLimit": {
      "strategy": "tokenBucket",
      "max": 10,
      "refillRate": 2
    }
  }
]
```

| Field | Required | Description |
|-------|----------|-------------|
| `prefix` | Yes | Path prefix that triggers this route |
| `target` | Yes | Upstream service URL |
| `rewrite` | No | Strip the prefix before forwarding (`false` default) |
| `rateLimit.strategy` | No | `"fixedWindow"` or `"tokenBucket"` |
| `rateLimit.windowMs` | No | Window duration in ms (fixedWindow) |
| `rateLimit.max` | No | Max requests per window or bucket capacity |
| `rateLimit.refillRate` | No | Tokens per second (tokenBucket only) |

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start with hot reload via nodemon + tsx |
| `npm run build` | Compile TypeScript to `dist/` |
| `npm start` | Run compiled production build |
| `npm test` | Run all Jest tests |
| `npm run test:unit` | Run unit tests only |
| `npm run test:integration` | Run integration tests only |
| `npm run test:smoke` | Run smoke tests only |
| `npm run test:all` | Run unit + integration + smoke |
| `npm run test:load` | Run load tests (ts-node) |
| `npm run test:perf` | Run performance benchmarks (ts-node) |

## Rate Limiting

### Fixed Window

Counts requests within a sliding time window. Resets after the window expires.

```
Window: 15 min, Max: 100 requests
├── 00:00 ──────── 00:15 ──────── 00:30
│   [  allowed  ]   [  allowed  ]
│   count: 0→100    count: 0→100
```

- Returns `429` when limit exceeded
- Sets `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
- Sets `Retry-After` header on rejection

### Token Bucket

Refills tokens at a steady rate. Allows short bursts up to bucket capacity.

```
Capacity: 10, Refill: 2 tokens/sec
├── Request consumes 1 token
├── Tokens refill at 2/sec
└── Empty bucket → wait for refill
```

- Atomic operations via Redis Lua script
- Best for APIs with bursty traffic patterns

## Authentication

1. Client sends `Authorization: Bearer <token>` header
2. Gateway verifies JWT signature using `JWT_SECRET`
3. Extracts `sessionId` from token payload
4. Looks up session in Redis (`session:<sessionId>`)
5. Attaches session data (`userId`, `role`, `email`) to `req.user`
6. Paths in `AUTH_EXCLUDE_PATHS` bypass authentication

## Response Cache

Caches authenticated JSON GET responses whose path starts with one of the
`CACHE_ROUTES` prefixes (`cache:resp:{userId}:{originalUrl}`, TTL
`CACHE_TTL`). Only 200 responses with a JSON content type are stored; misses,
parse errors and Redis errors fail open to the upstream service. Non-GET
requests are never cached.

Staleness is prevented from two directions:

- **WebSocket status pushes** — when the gateway forwards a status frame, it
  first deletes that video's cached entries (`invalidateVideoCache`) so the
  client's realtime-triggered refetch cannot read a stale response.
- **`DELETE /api/video/{id}`** — before proxying the request, the gateway
  flushes *every* cached video response (`invalidateAllVideoCache`,
  pattern `cache:resp:*:/api/video*`), so detail and list entries for the
  deleted video (and any refreshed by it) are gone. The flush fails open.

## Proxy

- Requests matching a route prefix are forwarded to the target service
- Each request is signed with an HMAC-SHA256 header (`x-proxy-signature`) for upstream verification
- Upstream services can validate the signature using the shared `PROXY_SECRET`
- Errors return `502 Bad Gateway`

## WebSocket Proxy

The gateway proxies WebSocket connections to upstream services:

```
ws://localhost:3000/ws/video/notification
Authorization: Bearer <jwt>
```

**Flow:**

1. Client initiates WebSocket upgrade to `/ws/video/notification` with `Authorization: Bearer <jwt>` header
2. Gateway extracts and verifies the JWT token using `JWT_SECRET`
3. Gateway looks up the session in Redis (`session:<sessionId>`)
4. If valid, gateway opens an upstream WebSocket to `ws://video-service:8000/ws/video/notification` with HMAC-signed headers (`x-proxy-signature`, `x-proxy-timestamp`)
5. Messages are proxied bidirectionally between client and upstream
6. On disconnect, both sides are cleaned up

**Close Codes:**

| Code | Meaning |
|------|---------|
| 4001 | Missing token, invalid token, expired session |
| 1011 | Backend unavailable (upstream connection error) |

## Docker

### With Docker Compose (from repository root)

```bash
# Start all services (gateway + Redis + Kafka + MinIO)
docker compose up --build -d

# View logs
docker compose logs -f api-gateway

# Stop
docker compose down
```

### Standalone

```bash
# Build
docker build -t api-gateway ./api_gateway_service

# Run
docker run -p 3000:3000 --env-file api_gateway_service/.env api-gateway
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| API Gateway | `3000` | The gateway service |
| Redis | `6379` | Session store + rate limiting |
| Kafka | `9092` | Message broker (KRaft mode) |
| MinIO Console | `9001` | Object storage web UI |
| MinIO API | `9000` | S3-compatible API |

## Project Structure

```
src/
├── config/
│   ├── index.ts              # Environment-based configuration
│   └── redis.ts              # Redis client (ioredis)
├── handlers/
│   └── refreshToken.ts       # Token refresh endpoint
├── middleware/
│   ├── auth.ts               # JWT authentication middleware
│   ├── cache.ts              # Redis response cache + video invalidation
│   ├── cors.ts               # CORS configuration
│   ├── errorHandler.ts       # Global error handler
│   ├── logger.ts             # Winston logger + request logging
│   └── ratelimit/
│       ├── index.ts          # Rate limiter entry point + route matching
│       ├── fixedWindow.ts    # Fixed window strategy
│       ├── tokenBucket.ts    # Token bucket strategy (Lua script)
│       └── utils.ts          # Shared helpers (identifier, headers)
├── proxy/
│   ├── index.ts              # HTTP proxy middleware + HMAC signing
│   └── ws.ts                 # WebSocket proxy + JWT session auth
├── types/
│   └── index.ts              # TypeScript interfaces
└── server.ts                 # Express app bootstrap + startup
```

## Testing

Tests use **Jest** with **@swc/jest** for fast TypeScript compilation. Redis is mocked in unit tests.

```bash
npm test              # Run all tests
npm run test:unit     # Unit tests only
npm run test:integration  # Integration tests (requires Redis)
npm run test:smoke    # Smoke tests (requires running server)
npm run test:all      # Unit + integration + smoke
```

### Test Coverage

| Suite | Tests |
|-------|-------|
| Config | Environment parsing, defaults, route validation |
| Middleware (auth, cache, errorHandler, logger) | JWT auth, Redis response cache, error handling, logging |
| Rate limiting (fixedWindow, tokenBucket, index, utils) | Strategy behaviour + route matching |
| Proxy (HTTP + WebSocket) | HMAC signing, upstream forwarding, WS session auth |
| Integration (health, ready) | 2 skipped — require a live Redis |

Latest local run: **116 passed, 2 skipped** (14 of 16 suites).

### Load & Performance

```bash
npm run test:load     # Load test with autocannon
npm run test:perf     # Performance benchmarks
```

## License

ISC
