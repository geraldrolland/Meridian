# MERIDIAN — UI/UX Flow & Frontend Contract

**Document type:** Product UI flow + frontend integration specification  
**Audience:** Product designers, frontend engineers  
**Author roles:** Senior UI/UX Designer · Senior Frontend Engineer  
**Status:** Implementation-ready (no app code in this repo yet)

---

## 1. Product overview

MERIDIAN is a video platform: users register, upload source video, watch async processing complete in real time, then play adaptive DASH renditions.

**Happy path**

```
Register / Login → Library → Upload → Track status (WebSocket) → Play (DASH) → Logout
```

### Personas

| Persona | Goals | Primary screens |
|---------|-------|-----------------|
| **Creator** | Upload video, confirm processing finished, retry failures | Login, Upload, Detail |
| **Viewer** | Watch completed videos | Library, Detail (player) |

Same user can be both; there is no separate role model in the backend (`role` appears only in session payload defaults).

---

## 2. Information architecture

All browser traffic goes through the **API Gateway** (`http://localhost:3001` local). Do not call auth/video services directly from the SPA (HMAC proxy signatures are gateway-only).

### App routes (SPA)

| Route | Screen | Auth |
|-------|--------|------|
| `/login` | Sign in | Public |
| `/register` | Create account | Public |
| `/` | Video library (list) | Required |
| `/upload` | Upload wizard / dropzone | Required |
| `/video/:id` | Video detail + player | Required |
| `*` | 404 | Any |

### Gateway surface used by the UI

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Login → access token + refresh cookie |
| POST | `/api/auth/refresh-token` | Rotate tokens |
| POST | `/api/auth/logout` | End session |
| GET | `/api/auth/me` | Bootstrap session |
| POST | `/api/video/upload` | Create video + presigned/multipart plan |
| GET | `/api/video/{id}` | Poll/fetch one video |
| POST | `/api/video/{id}/upload/complete` | Finish multipart |
| POST | `/api/video/{id}/upload/abort` | Cancel multipart |
| POST | `/api/video/{id}/retry` | Requeue (`RETRY` only) |
| WS | `/ws/video/notification` | Real-time status |
| GET | `/health`, `/ready` | Ops only (not product UI) |

**Auth exclude paths (gateway):** `/health`, `/ready`, `/api/auth/login`, `/api/auth/register` (plus refresh handled at gateway). Everything else requires `Authorization: Bearer <accessToken>`.

---

## 3. Screen inventory

### 3.1 Login (`/login`)

**Layout:** Centered card; email + password; primary **Sign in**; link **Create account**.

**Client validation (align with auth service):**

| Field | Rule | Message |
|-------|------|---------|
| Email | Required, contains `@` | “Enter a valid email” |
| Password | Required | “Password is required” |

**Server mapping:**

| Status | Body | UI |
|--------|------|-----|
| 200 | `{ user, accessToken }` | Store token; route `/` |
| 400 | `{ error }` | Field-level / form error |
| 401 | `{ error: "Invalid credentials" }` | “Email or password is incorrect” (do not reveal which) |
| 409 | n/a on login | — |
| 429 | rate limit | “Too many attempts — try later” |
| 500 | `{ error }` | “Something went wrong” |

**On success:** persist access token (memory preferred; sessionStorage acceptable), navigate to intended route or `/`. Refresh cookie is set httpOnly by the browser — never read it in JS.

---

### 3.2 Register (`/register`)

**Layout:** Email, password, confirm password (client-only), **Create account**, link **Sign in**.

| Rule | Source |
|------|--------|
| Email required + `@` | API 400 |
| Password ≥ 6 chars | API 400 |
| Passwords match | Client only |
| Duplicate email | API 409 `{ error: "Email already registered" }` |

**Post-success:** Registration does **not** issue tokens. UX options:

1. **Recommended:** toast “Account created — sign in” → redirect `/login` with email prefilled.  
2. Alternative: auto-submit login with same credentials (still explicit API calls).

---

### 3.3 Library (`/`)

**Purpose:** Entry after auth; list of the user’s videos with status and thumbnail.

**API gap:** Video service exposes `GET /api/video/{id}` only — **no list endpoint**.

**Design decision (until backend adds list):**

- Maintain a client-side **upload/session library**: video IDs from this browser session (localStorage key e.g. `meridian.videos`).
- On load, hydrate each id via `GET /api/video/{id}` (parallel, cap ~10).
- Show empty state if no ids: **“No videos yet”** + CTA **Upload video**.
- Optional future API: `GET /api/video?user=me` — document as backlog, do not block UI.

**Card anatomy:**

```
┌─────────────────────────────┐
│ [thumbnail 16:9]      badge │  ← status chip
│ filename.mp4                │
│ created_at · retries        │
│ [Open]                      │
└─────────────────────────────┘
```

**Thumbnail:** use `thumbnail_url` when non-null; placeholder gradient + film icon otherwise (PROCESSING may not have thumbnail yet).

**Status badge:** see §5.

---

### 3.4 Upload (`/upload`)

**Layout:** Dropzone + file picker; selected file summary (name, size, type); **Start upload**; progress; cancel.

**Client pre-checks (before API):**

| Check | Allowed |
|-------|---------|
| Extension | `mp4`, `mov`, `avi`, `mkv`, `webm`, `flv`, `wmv` |
| Size | > 0; show warning if huge (multipart path) |
| Content type | Prefer `video/*`; API default `video/mp4` |

**Mode selection (server-driven):** After `POST /api/video/upload`, response includes `upload.mode`:

| Mode | When | Client behavior |
|------|------|-----------------|
| `presigned_post` (or single PUT plan) | `file_size ≤ multipart_threshold` (100 MB) | Single direct POST/PUT to MinIO using returned `url` + `fields` |
| `multipart` | larger | Split file by `part_size`; PUT each `parts[i].url`; collect `ETag`; then `POST /api/video/{id}/upload/complete` |

**Multipart complete body:**

```json
{
  "upload_id": "...",
  "parts": [{ "part_number": 1, "etag": "..." }]
}
```

**Abort:** `POST /api/video/{id}/upload/abort` with `{ "upload_id": "..." }` → status becomes `FAILED` (server). Confirm dialog before abort.

**UX progress:**

- Phase A: “Preparing upload…” (create video record)  
- Phase B: bytes uploaded / total (client-computed; no server progress API)  
- Phase C: “Finalizing…” (complete multipart or waiting on bucket notification)  
- Phase D: status `AWAITING_UPLOAD` → navigate to `/video/:id`

**On 422** (`extension not allowed`): show exact allowed list from `detail`.

**After upload:** append `id` to client library; route to detail; open WebSocket if not already connected.

---

### 3.5 Video detail (`/video/:id`)

**Load:** `GET /api/video/{id}` → render status; 403/404 → friendly error + back to library.

**Response fields used by UI:**

```json
{
  "id": "uuid",
  "filename": "clip.mp4",
  "status": "PROCESSING",
  "user_id": 1,
  "published": false,
  "num_of_retries": 0,
  "notif_reference_id": null,
  "thumbnail_url": null,
  "manifest_url": null,
  "created_at": "ISO-8601"
}
```

**Sections:**

1. **Header:** filename, created date, status chip, retry count (if > 0).  
2. **Stepper / progress:** see §5 — primary feedback for non-terminal states.  
3. **Actions by status:**  
   - `AWAITING_UPLOAD` / `QUEUED` / `PROCESSING` / `GENERATING_MANIFEST`: no primary action; optional **Refresh**.  
   - `COMPLETED`: **Play** (player expands or dedicated panel).  
   - `FAILED`: error panel + **Contact support** copy (no API retry from FAILED — retry endpoint requires `RETRY`).  
   - `RETRY`: primary **Retry processing** → `POST /api/video/{id}/retry` → optimistic status `QUEUED`.  
4. **Player (COMPLETED only):** requires non-null `manifest_url`.

**Player notes (frontend eng):**

- Use an MPEG-DASH client (e.g. dash.js) pointed at `manifest_url`.  
- Representations may include `360p`, `480p`, `720p`, `1080p` — expose quality selector if player supports ABR.  
- If `manifest_url` missing while `COMPLETED`, show “Playback not ready — refresh”.  
- Rewrite in-cluster MinIO hosts (`http://minio:9000`) to host-reachable URL if needed in local dev (same as e2e helper).

---

### 3.6 Global chrome

| Element | Spec |
|---------|------|
| Nav | Logo → Library; Upload; user email + **Log out** |
| Auth guard | No token + failed refresh → `/login` |
| Toast system | Success / error / info; 4–6s; stack top-right |
| Loading | Skeleton cards on library; spinner on primary buttons |
| 401 interceptor | On 401: try one `POST /api/auth/refresh-token`; retry original once; else logout |
| 429 | Global rate-limit toast |
| Offline | Banner “You’re offline — reconnecting” when `navigator.onLine` false |

---

## 4. User journeys

### 4.1 Sign in

```
User → /login → POST /api/auth/login
  ← 200 { user, accessToken }  + Set-Cookie refresh
Store accessToken → GET /api/auth/me (Bearer) verify
Connect WS → navigate /
```

### 4.2 Token refresh (silent)

```
Access token near expiry (7 min) or API 401
  → POST /api/auth/refresh-token  (credentials: include; cookie path-scoped)
  ← 200 { accessToken }  + new refresh cookie
Retry failed request with new Bearer
  ← 401 → clear session → /login
```

Refresh tokens are **single-use** (rotation). Do not parallelize multiple refreshes — queue them behind one in-flight promise.

### 4.3 Upload (small file)

```
Select file → validate extension/size
POST /api/video/upload { filename, content_type, file_size }
  ← 201 { id, status: AWAITING_UPLOAD, upload: { mode, url, fields, ... } }
Browser PUT/POST file bytes → MinIO (presigned)
Show “Processing will start automatically”
Navigate /video/:id
Backend: bucket notification → QUEUED → … → COMPLETED
```

### 4.4 Upload (multipart, large)

```
POST /api/video/upload
  ← upload.mode = multipart, part_size, total_parts, parts[].url
For each part: PUT slice → capture ETag
POST /api/video/{id}/upload/complete { upload_id, parts[] }
Navigate /video/:id
On cancel: POST /api/video/{id}/upload/abort { upload_id }
```

### 4.5 Real-time status

```
WS connect: ws://localhost:3001/ws/video/notification
  Header: Authorization: Bearer <accessToken>
On message: { video_id, status, user_id }
  if current route is /video/:video_id → GET /api/video/{id} → re-render
  if library visible → update card chip
On close: exponential backoff reconnect; while down, poll detail every 10s
```

Gateway validates JWT + Redis session, then proxies to video service with HMAC headers. Client never sends HMAC.

**Close codes to handle:**

| Code | Meaning | UX |
|------|---------|-----|
| 4001 | Missing/invalid token | Refresh then reconnect; else login |
| 4003 | Invalid proxy signature | Should not happen via gateway — log |
| 1011 | Backend unavailable | Retry with backoff + banner |

### 4.6 Playback

```
status === COMPLETED && manifest_url
  → load DASH player(manifest_url)
  → player fetches MPD + init + .m4s segments (360p–1080p)
User can switch quality if exposed
```

### 4.7 Retry

```
status === RETRY
  → POST /api/video/{id}/retry
  ← 200 status QUEUED, num_of_retries++
  → stepper resets to Queued; WS continues
```

### 4.8 Logout

```
POST /api/auth/logout (Bearer)
  ← 200 + clear refresh cookie
Close WS → clear memory token + localStorage library keys → /login
```

---

## 5. Status lifecycle → UI

Source of truth: `VideoStatus` in `video_service/app/models/video.py`.

```
AWAITING_UPLOAD → QUEUED → PROCESSING → GENERATING_MANIFEST → COMPLETED
                        ↘ RETRY ↺ (client)     ↘ FAILED
```

| Status | Chip label | Tone | Stepper step | Primary action |
|--------|------------|------|--------------|----------------|
| `AWAITING_UPLOAD` | Uploading | Info | 0 · Upload | Wait / view upload tips |
| `QUEUED` | Queued | Neutral | 1 · Queued | None |
| `PROCESSING` | Processing | Progress | 2 · Transcoding | None (copy: multi-quality 360p–1080p) |
| `GENERATING_MANIFEST` | Finalizing | Progress | 3 · Manifest | None |
| `COMPLETED` | Ready | Success | 4 · Done | **Play** |
| `FAILED` | Failed | Danger | — | Support copy (no retry API) |
| `RETRY` | Needs attention | Warning | — | **Retry processing** |

**Progress bar heuristic (client-only):** optional mapping while `PROCESSING`: not server-accurate — prefer **determinate steps** over fake %.

**Suggested stepper copy:**

1. Upload received  
2. Queued for pipeline  
3. Transcode & thumbnail  
4. DASH manifest  
5. Ready to watch  

---

## 6. Frontend engineering contract

### 6.1 Environment

| Name | Local value |
|------|-------------|
| `API_BASE` | `http://localhost:3001` |
| `WS_URL` | `ws://localhost:3001/ws/video/notification` |
| CORS | Gateway must allow SPA origin + `credentials: true` |

### 6.2 Auth storage

| Data | Where | Lifetime |
|------|-------|----------|
| `accessToken` | JS memory (module scope) | ~7 minutes |
| Refresh token | httpOnly cookie `refresh` | 7 days; path `/api/auth/refresh-token` |
| Session profile | Memory after `GET /api/auth/me` | Until logout |
| Client video id list | `localStorage` | Until logout/clear |

Never put refresh JWT in JS-accessible storage.

### 6.3 HTTP client defaults

```http
Content-Type: application/json
Authorization: Bearer <accessToken>
```

- `credentials: 'include'` on all auth/video calls (cookie for refresh).  
- Single `fetch` wrapper: attach Bearer, on 401 refresh-once-retry, map errors.

### 6.4 Error envelope mapping

| Layer | Success | Error body |
|-------|---------|------------|
| Auth / gateway | `{ user, accessToken }` etc. | `{ "error": "..." }` |
| Video (FastAPI) | video JSON / upload plan | `{ "detail": "..." }` |

UI helper: `message = body.error || body.detail || fallback`.

| HTTP | UI treatment |
|------|----------------|
| 400 | Inline form / detail toast |
| 401 | Refresh or login |
| 403 | “Not yours” / forbidden screen |
| 404 | Missing video screen |
| 409 | Register conflict |
| 422 | Validation (extensions) |
| 429 | Rate limit toast |
| 500 | Generic error + retry |

### 6.5 WebSocket client sketch

```text
connect():
  new WebSocket(WS_URL)
  ws.onopen → status "live"
  ws.onmessage → parse { video_id, status, user_id }
                 → invalidate video query → re-fetch
  ws.onclose(code) → if 4001: refresh; else backoff reconnect
```

Payload (server → client):

```json
{
  "video_id": "uuid",
  "status": "PROCESSING",
  "user_id": 1
}
```

Client does not need to send application messages; connection is push-only (server loop is idle keep-alive).

### 6.6 Upload client algorithm

```text
validate(file)
res = POST /api/video/upload { filename, content_type, file_size }
if res.upload.mode == "multipart":
  parts = split(file, res.upload.part_size)
  etags = parallel PUT (limit concurrency ~3–4)
  POST /api/video/{id}/upload/complete { upload_id, parts: etags }
else:
  POST/PUT res.upload.url with fields + file  # MinIO direct
trackId(res.id)  // localStorage
router.push(/video/:id)
```

Collect ETags from response headers (`ETag`) on each part PUT.

### 6.7 Suggested SPA module layout (future app)

```text
src/
  api/          # client, authApi, videoApi
  auth/         # token store, refresh mutex, guards
  features/
    login/ register/ library/ upload/ video-detail/
  realtime/     # wsClient, reconnect
  components/   # StatusChip, Stepper, Dropzone, VideoCard, Player
  routes/
```

Stack recommendation: React + TypeScript + router; data layer TanStack Query (or equivalent) for `video_id` cache invalidation on WS events.

---

## 7. Component & visual system (starter)

Not a full design system — enough for consistent build-out.

| Token | Recommendation |
|-------|----------------|
| Radius | 8px controls, 12px cards |
| Status success | Green — COMPLETED |
| Status progress | Blue — PROCESSING / GENERATING_MANIFEST |
| Status neutral | Gray — QUEUED |
| Status warning | Amber — RETRY |
| Status danger | Red — FAILED |
| Status info | Cyan — AWAITING_UPLOAD |

**Core components:** `Button`, `Input`, `FormError`, `StatusChip`, `PipelineStepper`, `Dropzone`, `UploadProgress`, `VideoCard`, `EmptyState`, `ErrorState`, `Toast`, `DashPlayer`, `AppShell` (nav).

**Accessibility:**

- All form controls labeled; errors linked via `aria-describedby`.  
- Status chips include text (not color alone).  
- Stepper uses ordered list / `aria-current="step"`.  
- Dropzone keyboard-operable (Enter/Space opens file dialog).  
- Player controls keyboard-reachable; captions optional backlog.  
- Focus ring visible on dark/light themes.

**Responsive:**

- Mobile: single-column library; sticky upload CTA; player full-bleed.  
- Desktop: card grid; detail two-column (meta | player).

---

## 8. Empty, loading, error states

| Context | Empty / loading | Error |
|---------|-----------------|-------|
| Library | Skeleton ×3; empty “No videos yet” | List hydrate failed → Retry |
| Detail | Full-page spinner | 404/403 copy + Back |
| Upload | Dropzone idle | 422 extension list; network fail → resume/retry |
| WS | “Live updates on/off” indicator | Reconnecting… + poll fallback |
| Player | Poster / thumbnail | Manifest missing → Refresh |

---

## 9. Known API/product gaps (do not block v1)

| Gap | Impact | Mitigation | Backlog |
|-----|--------|------------|---------|
| No video **list** API | Library only knows client-created ids | localStorage ids + GET by id | `GET /api/video` |
| No **delete** API | Cannot remove library entries | Hide delete UI | `DELETE /api/video/{id}` |
| FAILED not retryable via API | Retry button only on RETRY | Show support message | Policy or extend retry |
| No server upload progress | Cannot show true % across tab close | Client-side byte progress | Optional |
| WS documented as query JWT in root README vs Bearer in gateway code | Confusion | **Use Bearer header** via gateway (matches `ws.ts`) | Docs align |
| Thumbnail may be null until media pipeline runs | Card art | Placeholder | — |

---

## 10. Acceptance checklist (design QA)

- [ ] Register validation matches API (6-char password, 409 email).  
- [ ] Login stores access token; refresh cookie never read by JS.  
- [ ] Silent refresh serializes concurrent 401s.  
- [ ] Upload blocks disallowed extensions with API `detail` text.  
- [ ] Multipart sends ETags and complete/abort correctly.  
- [ ] Detail re-renders on every WS status for current `video_id`.  
- [ ] Stepper labels match §5 for all seven statuses.  
- [ ] Play only when `COMPLETED` + `manifest_url`.  
- [ ] Retry only when `RETRY`.  
- [ ] Logout clears token, WS, and client library.  
- [ ] All interactive controls keyboard accessible.  
- [ ] SPA origin configured in gateway `CORS_ORIGIN` with credentials.

---

## 11. Reference map (code → UX)

| Concern | Source |
|---------|--------|
| Auth endpoints & validation | `auth_service/src/routes/auth.ts` |
| Gateway auth excludes & CORS | `api_gateway_service/src/config/index.ts` |
| Gateway JWT middleware | `api_gateway_service/src/middleware/auth.ts` |
| WS proxy (Bearer + HMAC) | `api_gateway_service/src/proxy/ws.ts` |
| Video upload / complete / abort / retry | `video_service/app/routes/video.py` |
| Status enum & video DTO | `video_service/app/models/video.py` |
| WS payload & pubsub | `video_service/app/websocket.py` |
| Pipeline & reliability | root `README.md` (Video Processing Pipeline) |
| End-to-end contract | `e2e_test.py` |

---

*This document is the source of truth for UI flow and frontend integration until a Figma file supersedes visual details. Backend contract changes require updating §2, §6, and §5 together.*
