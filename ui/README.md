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

## Routes

| Route | Description |
|-------|-------------|
| `/` | Landing + product demo |
| `/login`, `/register` | Auth |
| `/dashboard` | Video library |
| `/upload` | Presigned / multipart upload |
| `/video/[id]` | Status pipeline + DASH player |

## Demo video

`public/demo/meridian-demo.mp4` — replace with a full product recording when available.
