# MERIDIAN UI

Production-grade Next.js frontend for the MERIDIAN video platform.

## Stack

- **Next.js 16** (App Router) + TypeScript
- **Tailwind CSS v4** + shadcn-style components
- **Framer Motion** animations
- **dash.js** custom adaptive player
- **TanStack Query** + **Zustand**
- Brand: Space Grotesk · Inter · JetBrains Mono · `#EF192A`

## Quick start

```bash
cd ui
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Environment

Create `ui/.env.local` (defaults shown):

```env
NEXT_PUBLIC_API_BASE=http://localhost:3001
NEXT_PUBLIC_MINIO_HOST=http://localhost:9000
```

Gateway must allow this origin with credentials:

```env
CORS_ORIGIN=http://localhost:3000
CORS_CREDENTIALS=true
```

(Already set for local Docker in root `docker-compose.yml`.)

## Docker

The UI is containerized and starts with the root stack:

```bash
docker compose up -d ui
```

`output: "standalone"` in `next.config.ts` produces a self-contained server image
(`ui/Dockerfile`, multi-stage `node:20-alpine`), served by `node server.js` on port 3000.

`NEXT_PUBLIC_*` values are inlined into the client bundle at **build time**, so pass them as
build args rather than runtime `environment`:

```yaml
build:
  context: ./ui
  args:
    - NEXT_PUBLIC_API_BASE=http://localhost:3001
    - NEXT_PUBLIC_MINIO_HOST=http://localhost:9000
```

Both point at the **host**-mapped ports, because the browser — not the container — makes the
requests. Override with `NEXT_PUBLIC_API_BASE` / `NEXT_PUBLIC_MINIO_HOST` build args if your
gateway or MinIO is exposed elsewhere.

## Routes

| Route | Description |
|-------|-------------|
| `/` | Landing + product demo |
| `/login`, `/register` | Auth |
| `/dashboard` | Video library |
| `/upload` | Presigned / multipart upload |
| `/video/[id]` | Status pipeline + DASH player |

## Demo tour

`components/demo/` renders the landing page demo as a scripted animation (no video asset): it
replays the real product flow — sign in, upload, pipeline status, DASH playback — inside a scaled
960×600 mock canvas. Beats live in `components/demo/demo-timeline.ts`, screen replicas in
`components/demo/demo-screens.tsx`, and the cursor/loop/controls in `components/demo/demo-tour.tsx`.
