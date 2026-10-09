# Pulse — Voroa-ready Music Web App

This is the web/PWA counterpart of Pulse. It uses React + Vite and can run without a backend, but now supports optional **Pulse accounts and cloud library sync through Supabase**.

## Stack

- React 18
- Vite 6
- Lucide icons
- Supabase Auth + Postgres (optional but recommended for production)
- Optional Pulse music API adapter (`VITE_PULSE_API_URL`) for real search
- Browser localStorage fallback
- YouTube embedded playback
- Optional YouTube Data API v3 search
- Responsive mobile/desktop UI

## First-time account setup

1. Create a Supabase project.
2. Open the Supabase SQL Editor.
3. Run `supabase/schema.sql` once.
4. In Supabase Auth settings, configure the email provider and site/redirect URL for your Voroa deployment.
5. Copy `.env.example` to `.env` for local development and set:

```text
VITE_SUPABASE_URL=your-project-url
VITE_SUPABASE_ANON_KEY=your-anon-key
```

Only the Supabase **anon/publishable key** belongs in the browser. Never expose a service-role key.

## What account sync now stores

- Account identity/profile
- Liked songs
- Playlists and playlist songs
- Listening events (play/like/unlike/search)
- Interest signals based on artists/albums

The app still falls back to local browser storage when Supabase is not configured, so the existing UI remains usable during setup.

## Voroa deployment

1. Push this folder to GitHub.
2. In Voroa, choose **New service → Web Service**.
3. Connect the repository and `main` branch.
4. Root directory: `/`.
5. Build command: `npm run build` (or leave empty if Voroa auto-detects Vite).
6. Start command: leave empty if Voroa serves the Vite `dist` output.
7. Add `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` as Voroa environment variables.
8. Deploy.

## Local development

```bash
npm install
npm run dev
```

Production build:

```bash
npm run build
```

## Product behavior

A logged-out user can still browse and use the local/demo library. A logged-in user gets a persistent Pulse identity, with likes and playlists synced to the cloud. Pulse also records lightweight listening signals so a later recommendation engine can use the user's interests.

This is still a browser implementation, not a binary conversion of Android code. Native Android background audio/equalizer/filesystem capabilities require web-specific implementations.

## Real music search

For local development, set `VITE_PULSE_API_URL=http://localhost:8000` when your Pulse music API is running. The web client calls `POST /music/search` with `{ "query": "..." }` and accepts common `results`, `tracks`, `items`, or `data` response envelopes. YouTube Data API search remains available as a fallback. Playback uses an official YouTube embed when the result includes a YouTube/video ID or embed URL.
