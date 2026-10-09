# Pulse Web — Working Build v7

This build focuses on the Pulse product behavior requested for the web client:

- Pulse home with a clickable headphone random-play control.
- Taste-aware random playback after sign-in/listening history.
- Pulse special playlists with a refresh button that rebuilds a fresh mix.
- No separate Discovery page/section.
- Compact Recently Heard shelf.
- Music-only search with local exact-title/artist ranking.
- Proxied thumbnails with a video-thumbnail fallback.
- Full player with always-available lyrics panel, queue/equalizer/download icons, seek controls and mini-player reopen.
- Download is exposed only inside the full player.
- Supabase account signup/signin through the Pulse backend proxy.
- Likes, playlists, interests and listening events sync when authenticated.

## Run

Backend:

```bat
cd Pulse-Backend
run.bat
```

Web:

```bat
cd web
npm install
npm run dev
```

Set `web/.env` from `.env.example` with the Supabase publishable key and Pulse API URL.
