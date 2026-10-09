# Pulse Web Backend 2.0

This backend is the web music engine for Pulse.

## Important difference from the old build

`/music/search` **does not use generic YouTube search**. It uses `ytmusicapi` with the YouTube Music `songs` filter, so results are music tracks instead of random YouTube videos, lyrics uploads, news, reactions, etc.

Playback is separate: `/music/stream/{video_id}` resolves an audio-only stream with `yt-dlp` and proxies it to the browser.

Recommendations use YouTube Music watch-next candidates plus Pulse taste seeds (recent/liked artists) and are exposed at `/music/recommendations`.

## Windows

Double-click `run.bat`, or from CMD:

```bat
run.bat
```

The script automatically uses the installed Python 3.14 executable at `%LocalAppData%\Programs\Python\Python314\python.exe` when `python` is not on PATH.

## Endpoints

- `GET /health`
- `POST /music/search`
- `GET /music/search?q=...`
- `POST /music/metadata`
- `POST /music/recommendations`
- `GET /music/resolve/{video_id}`
- `GET /music/stream/{video_id}`
- `GET /lyrics`
