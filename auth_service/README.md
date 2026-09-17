# MERIDIAN Auth Service

A production-grade authentication microservice built with Express, TypeScript, PostgreSQL, and Redis. Handles user registration, login, session management, and JWT token lifecycle for the MERIDIAN platform.

## Overview

The Auth Service is the identity backbone of MERIDIAN. It runs behind the API Gateway and is protected by HMAC-SHA256 proxy signatures — all requests must originate from the gateway to be accepted.

**Key responsibilities:**
- User registration with bcrypt password hashing (12 salt rounds)
- Login with JWT access token + httpOnly refresh cookie issuance
- Session management via Redis (7-day TTL)
- Token rotation on refresh (single-use refresh tokens)
- User profile retrieval (`/me`)
- Session invalidation on logout

## Architecture

```
┌──────────┐    ┌─────────────┐    ┌──────────────┐
│  Client  │───▶│ API Gateway │───▶│ Auth Service  │
└──────────┘    │  (port 3001)│    │  (port 4000)  │
                └──────┬──────┘    └───────┬───────┘
                       │                   │
                  HMAC-signed          ┌───┴───┐
                  requests             │       │
                                    ┌──┴──┐ ┌──┴────┐
                                    │Redis│ │PostgreSQL│
                                    │:6379│ │  :5432  │
                                    └─────┘ └────────┘
```

**Request flow:**
1. Client sends request to API Gateway (`localhost:3001`)
2. Gateway validates JWT (for protected routes), signs the request with HMAC-SHA256
3. Auth service verifies the proxy signature (30-second replay window)
4. Auth service processes the request and returns the response directly to the client

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Runtime | Node.js 20+ |
| Framework | Express 5 |
| Language | TypeScript 7 |
| Database | PostgreSQL 16 |
| Cache/Sessions | Redis 7 (ioredis) |
| Password Hashing | bcrypt (12 salt rounds) |
| Tokens | JWT (jsonwebtoken) |
| Testing | Jest 30 + @swc/jest |
| Container | Docker (multi-stage, Alpine) |

## Quick Start

### Prerequisites
- Node.js 20+
- PostgreSQL 16+
- Redis 7+

### Local Development

```bash
# Clone the repository
git clone https://github.com/geraldrolland/auth_service_meridian.git
cd auth_service_meridian

# Install dependencies
npm install

# Configure environment
cp .env.example .env
# Edit .env with your database and Redis credentials

# Start development server (with hot reload)
npm run dev
```

### Docker

```bash
# Build and run with Docker Compose (from MERIDIAN root)
docker compose up --build auth-service

# Or standalone
docker build -t auth-service .
docker run -p 4000:4000 --env-file .env auth-service
```

## API Endpoints

All endpoints are prefixed with `/api/auth` and require a valid proxy signature header from the API gateway.

### Health Check

```
GET /health
GET /
```

**Response:**
```json
{ "status": "ok", "service": "auth-service", "timestamp": "2026-09-13T12:00:00.000Z" }
```

### Register

```
POST /api/auth/register
```

Creates a new user account. Does **not** issue tokens — the user must log in separately.

**Request:**
```json
{ "email": "user@example.com", "password": "secret123" }
```

**Response (201):**
```json
{ "user": { "id": 1, "email": "user@example.com" } }
```

| Status | Condition |
|--------|-----------|
| 201 | User created successfully |
| 400 | Missing email/password, invalid email format, or password < 6 chars |
| 409 | Email already registered |
| 500 | Server error |

### Login

```
POST /api/auth/login
```

Authenticates the user and issues a JWT access token + httpOnly refresh cookie.

**Request:**
```json
{ "email": "user@example.com", "password": "secret123" }
```

**Response (200):**
```json
{ "user": { "id": 1, "email": "user@example.com" }, "accessToken": "eyJhbGci..." }
```

**Set-Cookie:**
```
refresh=<token>; HttpOnly; Secure; SameSite=Strict; Path=/api/auth/refresh-token; Max-Age=604800
```

| Status | Condition |
|--------|-----------|
| 200 | Login successful |
| 400 | Missing email or password |
| 401 | Invalid credentials |
| 500 | Server error |

### Get Current User

```
GET /api/auth/me
```

Returns the authenticated user's profile. Requires a valid Bearer token.

**Headers:**
```
Authorization: Bearer <accessToken>
```

**Response (200):**
```json
{ "user": { "id": 1, "email": "user@example.com" } }
```

| Status | Condition |
|--------|-----------|
| 200 | User profile returned |
| 401 | Missing/invalid token or expired session |
| 500 | Server error |

### Refresh Token

```
POST /api/auth/refresh-token
```

Rotates the refresh token and issues a new access + refresh token pair. The refresh token is read from the httpOnly cookie. This is **single-use** — each refresh token can only be used once.

**Cookie:**
```
refresh=<token>
```

**Response (200):**
```json
{ "accessToken": "eyJhbGci..." }
```

**Set-Cookie:**
```
refresh=<newToken>; HttpOnly; Secure; SameSite=Strict; Path=/api/auth/refresh-token; Max-Age=604800
```

| Status | Condition |
|--------|-----------|
| 200 | Tokens rotated successfully |
| 401 | Missing refresh token, invalid token, or session expired |
| 500 | Server error |

### Logout

```
POST /api/auth/logout
```

Invalidates the current session by deleting it from Redis and clearing the refresh cookie.

**Headers:**
```
Authorization: Bearer <accessToken>
```

**Response (200):**
```json
{ "message": "Logged out successfully" }
```

| Status | Condition |
|--------|-----------|
| 200 | Logged out successfully |
| 401 | Missing or invalid token |
| 500 | Server error |

### Readiness Probe

```
GET /ready
```

Returns database connectivity status. Used by container orchestrators.

**Response (200):**
```json
{ "status": "ok", "database": "connected" }
```

| Status | Condition |
|--------|-----------|
| 200 | Database is reachable |
| 503 | Database connection failed |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Server port | `4000` |
| `HOST` | Bind address | `127.0.0.1` |
| `DB_HOST` | PostgreSQL host | `127.0.0.1` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_USER` | PostgreSQL user | `postgres` |
| `DB_PASSWORD` | PostgreSQL password | `postgres` |
| `DB_NAME` | PostgreSQL database | `auth_db` |
| `REDIS_HOST` | Redis host | `127.0.0.1` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis password | (empty) |
| `REDIS_DB` | Redis database number | `0` |
| `JWT_SECRET` | JWT signing secret | `change-me-in-production` |
| `ACCESS_TOKEN_EXPIRY` | Access token TTL | `7m` |
| `REFRESH_TOKEN_EXPIRY` | Refresh token TTL | `7d` |
| `REFRESH_TOKEN_MAX_AGE` | Refresh cookie Max-Age (ms) | `604800000` (7 days) |
| `PROXY_SECRET` | HMAC shared secret with API gateway | `change-me-in-production` |
| `LOG_LEVEL` | Winston log level | `info` |

## Project Structure

```
auth_service/
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI pipeline
├── migrations/
│   └── 001_create_users.sql    # Users table schema
├── src/
│   ├── config/
│   │   ├── index.ts            # Centralized configuration + logger
│   │   ├── database.ts         # PostgreSQL connection pool
│   │   └── redis.ts            # Redis client (ioredis)
│   ├── middleware/
│   │   ├── checkProxySignature.ts  # HMAC proxy signature verification
│   │   ├── errorHandler.ts     # Global error handler
│   │   ├── getUserSession.ts   # Session cookie extraction
│   │   └── requestLogger.ts    # Incoming + completed request logging
│   ├── routes/
│   │   ├── auth.ts             # Auth route handlers
│   │   └── ready.ts            # Database readiness probe
│   ├── types/
│   │   └── index.ts            # TypeScript interfaces
│   └── server.ts               # Express app bootstrap + startup
├── tests/
│   ├── __mocks__/
│   │   ├── express.ts          # Mock request/response factories
│   │   └── redis.ts            # Mock Redis client
│   └── unit/
│       ├── middleware/
│       │   └── checkProxySignature.test.ts
│       └── routes/
│           └── auth.test.ts
├── Dockerfile                  # Multi-stage Docker build
├── .dockerignore
├── .env.example
├── .gitignore
├── jest.config.js
├── package.json
├── start.sh                    # Container entrypoint (migrations + server)
└── tsconfig.json
```

## Testing

Tests use **Jest** with **@swc/jest** for fast TypeScript compilation. External dependencies (bcrypt, Redis, PostgreSQL) are mocked in unit tests.

```bash
npm test              # Run all tests
npm run test:unit     # Run unit tests only
```

### Test Coverage

| Module | Tests |
|--------|-------|
| `checkProxySignature` middleware | 6 tests (missing headers, expired timestamp, invalid signature, valid signature) |
| `getUserSession` middleware | 3 tests (valid session, missing cookie, malformed cookie) |
| Auth routes | 12 tests (validation, proxy signature, auth headers, token verification) |
| Ready routes | 2 tests (database connected, database down) |

## Security

### Proxy Signature Verification
Every request from the API gateway is signed with HMAC-SHA256 using a shared secret (`PROXY_SECRET`). The auth service verifies:
- Both `x-proxy-signature` and `x-proxy-timestamp` headers are present
- Timestamp is within 30 seconds (replay protection)
- HMAC signature matches using constant-time comparison (`crypto.timingSafeEqual`)

### Password Storage
Passwords are hashed with **bcrypt** using **12 salt rounds** before being stored in PostgreSQL. Plaintext passwords are never logged or persisted.

### Token Security
- **Access tokens** are short-lived (7 minutes) and returned in the response body
- **Refresh tokens** are long-lived (7 days) and set as `httpOnly`, `Secure`, `SameSite=strict` cookies scoped to `/api/auth/refresh-token`
- Refresh tokens are **single-use** — each refresh rotates the session and invalidates the old token

### Session Management
Sessions are stored in Redis with a 7-day TTL. Each session contains only `{ userId, email }` — no sensitive data. Sessions are deleted on logout and rotated on refresh.

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  hash_password VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Migrations run automatically at server startup via `start.sh` in Docker or `runMigrations()` in code.

## License

ISC
