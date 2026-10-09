from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any

import httpx
import yt_dlp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from ytmusicapi import YTMusic

load_dotenv()

APP_VERSION = "3.6.0"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
CACHE_SECONDS = int(os.getenv("STREAM_URL_CACHE_SECONDS", "300"))
LRCLIB_BASE_URL = os.getenv("LRCLIB_BASE_URL", "https://lrclib.net").rstrip("/")
_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://192.168.1.4:5173").split(",") if x.strip()]

app = FastAPI(title="Pulse API", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _upgrade_thumb_url(url: str) -> str:
    url = str(url or "")
    # Music artwork URLs often arrive with tiny 120px dimensions. Ask the same
    # image host for a larger rendition when it supports size parameters.
    url = re.sub(r"=w\d+-h\d+(-[^&]*)?", "=w1200-h1200", url)
    url = re.sub(r"/w\d+-h\d+/", "/w1200-h1200/", url)
    return url


def _thumbs(item: dict[str, Any]) -> str:
    thumbs = item.get("thumbnails") or item.get("thumbnail") or item.get("thumb") or item.get("image") or ""
    if isinstance(thumbs, dict):
        return _upgrade_thumb_url(thumbs.get("url") or thumbs.get("src") or "")
    if isinstance(thumbs, list) and thumbs:
        candidates = [x for x in thumbs if isinstance(x, dict) and (x.get("url") or x.get("src"))]
        if candidates:
            def resolution(x):
                return int(x.get("width") or 0) * int(x.get("height") or 0)
            best = max(candidates, key=resolution)
            return _upgrade_thumb_url(best.get("url") or best.get("src") or "")
        for value in reversed(thumbs):
            if isinstance(value, str) and value:
                return _upgrade_thumb_url(value)
    return _upgrade_thumb_url(thumbs) if thumbs else ""


def _artists(item: dict[str, Any]) -> list[str]:
    vals = []
    for a in item.get("artists") or []:
        if isinstance(a, dict):
            name = _clean(a.get("name"))
        else:
            name = _clean(a)
        if name:
            vals.append(name)
    if not vals and item.get("artist"):
        vals = [_clean(item.get("artist"))]
    return vals


def normalize_ytmusic(item: dict[str, Any]) -> dict[str, Any]:
    video_id = item.get("videoId") or item.get("video_id") or item.get("id")
    artists = _artists(item)
    album = item.get("album")
    if isinstance(album, dict):
        album = album.get("name", "")
    duration = item.get("duration_seconds") or item.get("duration")
    thumb = _thumbs(item)
    if not thumb and video_id:
        thumb = f"https://i.ytimg.com/vi/{video_id}/hq720.jpg"
    return {
        "id": video_id,
        "video_id": video_id,
        "youtubeId": video_id,
        "title": _clean(item.get("title") or item.get("name")),
        "artist": artists[0] if artists else "Unknown Artist",
        "artists": artists,
        "album": _clean(album),
        "duration": duration,
        "thumb": thumb,
        "thumbnail": thumb,
        "source": "pulse",
        "is_music": True,
    }


# One unauthenticated YouTube Music client. ytmusicapi talks to music.youtube.com's
# internal music search endpoints, which is what we want here; generic ytsearch is
# deliberately not used for search.
yt_music = YTMusic()

_stream_cache: dict[str, tuple[float, str, dict[str, Any]]] = {}
_stream_locks: dict[str, asyncio.Lock] = {}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=50)


class MetadataRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=128)


class RecommendationRequest(BaseModel):
    seed_ids: list[str] = Field(default_factory=list, max_length=10)
    seed_artists: list[str] = Field(default_factory=list, max_length=20)
    exclude_ids: list[str] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=20, ge=1, le=50)


class PlaylistImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    limit: int = Field(default=100, ge=1, le=200)


class AuthRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=6, max_length=200)
    display_name: str = Field(default="", max_length=100)
    supabase_url: str = Field(min_length=10, max_length=500)
    supabase_key: str = Field(min_length=10, max_length=1000)


def _search_sync(query: str, limit: int) -> list[dict[str, Any]]:
    q = _clean(query)
    q_fold = q.casefold()
    tokens = [x.casefold() for x in re.findall(r"[\w']+", q)]
    rows = yt_music.search(q, filter="songs", limit=min(50, max(limit * 2, 40)))

    def score(row: dict[str, Any]) -> float:
        title = _clean(row.get("title") or row.get("name")).casefold()
        artist_text = " ".join(_artists(row)).casefold()
        combined = f"{title} {artist_text}"
        # Relevance gate: never pad a search for one title with unrelated songs.
        if not tokens or not all(token in combined for token in tokens):
            return -1
        points = 0.0
        if title == q_fold:
            points += 150
        if q_fold in title:
            points += 90
        if q_fold in artist_text:
            points += 70
        title_tokens = set(re.findall(r"[\w']+", title))
        artist_tokens = set(re.findall(r"[\w']+", artist_text))
        points += 12 * sum(1 for token in tokens if token in title_tokens)
        points += 7 * sum(1 for token in tokens if token in artist_tokens)
        if row.get("videoId"):
            points += 1
        return points

    ranked = [(score(row), row) for row in rows]
    ranked = [(points, row) for points, row in ranked if points >= 0]
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    out, seen = [], set()
    for _, row in ranked:
        item = normalize_ytmusic(row)
        vid = item["video_id"]
        if vid and vid not in seen and item["title"]:
            seen.add(vid)
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _metadata_sync(video_id: str) -> dict[str, Any]:
    # get_song provides Music metadata. If a result is not available, fall back
    # to a song-filter search using the video id as the last-resort lookup key.
    data = yt_music.get_song(video_id)
    video_details = data.get("videoDetails") or {}
    micro = data.get("microformat", {}).get("microformatDataRenderer", {})
    artists = []
    author = _clean(video_details.get("author"))
    if author:
        artists.append(author)
    return normalize_ytmusic({
        "videoId": video_id,
        "title": video_details.get("title") or micro.get("title"),
        "artists": [{"name": a} for a in artists],
        "album": "",
        "duration_seconds": int(video_details.get("lengthSeconds") or 0),
        "thumbnails": video_details.get("thumbnail", {}).get("thumbnails") or micro.get("thumbnail", {}).get("thumbnails"),
    })


def _recommend_sync(payload: RecommendationRequest) -> list[dict[str, Any]]:
    excluded = set(payload.exclude_ids)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    # YouTube Music's watch-next/autoplay candidate list is the closest web
    # equivalent to Pulse's seed -> recommendation -> queue flow.
    for seed in payload.seed_ids[:5]:
        try:
            watch = yt_music.get_watch_playlist(videoId=seed, limit=25)
            for row in watch.get("tracks", []) if isinstance(watch, dict) else []:
                item = normalize_ytmusic(row)
                vid = item.get("video_id")
                if vid and vid not in excluded and vid not in seen and item.get("title"):
                    seen.add(vid)
                    candidates.append(item)
        except Exception:
            continue

    # Add artist taste candidates. Artist signals are intentionally only a
    # secondary source so a single artist does not dominate recommendations.
    for artist in payload.seed_artists[:8]:
        try:
            rows = yt_music.search(f"{artist}", filter="songs", limit=8)
            for row in rows:
                item = normalize_ytmusic(row)
                vid = item.get("video_id")
                if vid and vid not in excluded and vid not in seen and item.get("title"):
                    seen.add(vid)
                    candidates.append(item)
        except Exception:
            continue

    # Stable reranking: exact seed-artist matches first, then preserve Music
    # service ordering. This gives us a deterministic taste layer on the web.
    artists = {a.casefold() for a in payload.seed_artists if a}
    candidates.sort(key=lambda x: (0 if any(a.casefold() in artists for a in x.get("artists", [])) else 1))
    return candidates[:payload.limit]


def _ydl_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
        "nocheckcertificate": True,
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }


def _resolve_sync(video_id: str) -> tuple[str, dict[str, Any]]:
    opts = _ydl_opts()
    opts.update({"format": "bestaudio[acodec!=none]/bestaudio/best"})
    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.extract_info(f"https://music.youtube.com/watch?v={video_id}", download=False)
    url = data.get("url")
    if not url:
        raise RuntimeError("No playable audio stream returned")
    meta = normalize_ytmusic({
        "videoId": video_id,
        "title": data.get("track") or data.get("title"),
        "artists": [{"name": data.get("artist") or data.get("uploader")}],
        "album": data.get("album"),
        "duration_seconds": data.get("duration"),
        "thumbnails": data.get("thumbnails"),
    })
    return url, meta


async def _resolve(video_id: str) -> tuple[str, dict[str, Any]]:
    now = time.time()
    cached = _stream_cache.get(video_id)
    if cached and cached[0] > now:
        return cached[1], cached[2]
    lock = _stream_locks.setdefault(video_id, asyncio.Lock())
    async with lock:
        cached = _stream_cache.get(video_id)
        if cached and cached[0] > time.time():
            return cached[1], cached[2]
        url, meta = await asyncio.to_thread(_resolve_sync, video_id)
        _stream_cache[video_id] = (time.time() + CACHE_SECONDS, url, meta)
        return url, meta



async def _supabase_auth(path: str, payload: AuthRequest) -> dict[str, Any]:
    base = payload.supabase_url.rstrip("/")
    headers = {"apikey": payload.supabase_key, "Authorization": f"Bearer {payload.supabase_key}", "Content-Type": "application/json"}
    body = {"email": payload.email, "password": payload.password}
    if path.endswith("signup") and payload.display_name:
        body["data"] = {"display_name": payload.display_name}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.post(f"{base}/auth/v1/{path}", headers=headers, json=body)
    try:
        data = r.json()
    except Exception:
        data = {"error": r.text}
    if r.status_code >= 400:
        detail = data.get("msg") or data.get("message") or data.get("error_description") or data.get("error") or f"Supabase returned {r.status_code}"
        raise HTTPException(r.status_code, detail)
    return data


@app.post("/auth/signup")
async def auth_signup(payload: AuthRequest):
    return await _supabase_auth("signup", payload)


@app.post("/auth/signin")
async def auth_signin(payload: AuthRequest):
    return await _supabase_auth("token?grant_type=password", payload)

@app.get("/")
async def root():
    return {"name": "Pulse API", "version": APP_VERSION, "status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pulse-api", "version": APP_VERSION, "search": "music", "stream": "audio"}


@app.post("/music/search")
async def music_search(payload: SearchRequest):
    try:
        results = await asyncio.to_thread(_search_sync, payload.query.strip(), payload.limit)
        return {"query": payload.query, "results": results, "items": results}
    except Exception as exc:
        raise HTTPException(502, f"YouTube Music search failed: {exc}") from exc


@app.get("/music/search")
async def music_search_get(q: str = Query(min_length=1, max_length=200), limit: int = Query(20, ge=1, le=50)):
    return await music_search(SearchRequest(query=q, limit=limit))


@app.get("/music/thumb/{video_id}")
async def music_thumb(video_id: str):
    url = f"https://i.ytimg.com/vi/{video_id}/hq720.jpg"
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent":"Mozilla/5.0"})
    if r.status_code >= 400:
        raise HTTPException(404, "Thumbnail unavailable")
    from fastapi.responses import Response
    return Response(content=r.content, media_type=r.headers.get("content-type","image/jpeg"), headers={"Cache-Control":"public, max-age=86400"})

@app.get("/music/download/{video_id}")
async def music_download(video_id: str):
    try:
        url, meta = await _resolve(video_id)
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code >= 400:
            raise HTTPException(502, "Audio download failed")
        name = re.sub(r"[^A-Za-z0-9 _.-]+", "", meta.get("title") or "Pulse track").strip() or "Pulse track"
        from fastapi.responses import Response
        return Response(content=r.content, media_type="audio/mpeg", headers={"Content-Disposition":f'attachment; filename="{name}.mp3"'})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Download failed: {exc}") from exc

@app.post("/music/metadata")
async def music_metadata(payload: MetadataRequest):
    try:
        data = await asyncio.to_thread(_metadata_sync, payload.video_id.strip())
        return {"track": data, "result": data}
    except Exception as exc:
        raise HTTPException(502, f"Music metadata failed: {exc}") from exc


@app.get("/music/metadata/{video_id}")
async def music_metadata_get(video_id: str):
    return await music_metadata(MetadataRequest(video_id=video_id))


@app.get("/music/discovery")
async def music_discovery(limit: int = Query(24, ge=1, le=50)):
    try:
        def collect():
            rows = []
            seen = set()
            # Prefer current charts, then home/discovery shelves.
            try:
                charts = yt_music.get_charts(countryCode="IN")
                for row in (charts.get("songs") or []) if isinstance(charts, dict) else []:
                    item = normalize_ytmusic(row)
                    if item.get("video_id") and item["video_id"] not in seen and item.get("title"):
                        seen.add(item["video_id"]); rows.append(item)
            except Exception:
                pass
            try:
                home = yt_music.get_home()
                for shelf in home if isinstance(home, list) else []:
                    contents = shelf.get("contents", []) if isinstance(shelf, dict) else []
                    for row in contents:
                        item = normalize_ytmusic(row)
                        if item.get("video_id") and item["video_id"] not in seen and item.get("title"):
                            seen.add(item["video_id"]); rows.append(item)
                        if len(rows) >= limit: return rows[:limit]
            except Exception:
                pass
            if len(rows) < limit:
                for q in ("new music", "popular songs", "indie music", "Hindi songs"):
                    try:
                        for row in yt_music.search(q, filter="songs", limit=8):
                            item = normalize_ytmusic(row)
                            if item.get("video_id") and item["video_id"] not in seen and item.get("title"):
                                seen.add(item["video_id"]); rows.append(item)
                            if len(rows) >= limit: return rows[:limit]
                    except Exception:
                        continue
            return rows[:limit]
        rows = await asyncio.to_thread(collect)
        return {"results": rows, "items": rows}
    except Exception as exc:
        raise HTTPException(502, f"Discovery failed: {exc}") from exc


@app.post("/music/recommendations")
async def music_recommendations(payload: RecommendationRequest):
    try:
        results = await asyncio.to_thread(_recommend_sync, payload)
        return {"results": results, "items": results}
    except Exception as exc:
        raise HTTPException(502, f"Recommendation generation failed: {exc}") from exc



def _walk_spotify_tracks(value: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        name = value.get("name") or value.get("title")
        artists = value.get("artists") or value.get("artist")
        uri = value.get("uri") or value.get("id")
        if name and artists and isinstance(artists, (list, str)):
            if isinstance(artists, str):
                artist_names = [artists]
            else:
                artist_names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in artists]
            artist_names = [_clean(a) for a in artist_names if _clean(a)]
            if artist_names and not value.get("isLocal"):
                out.append({"title": _clean(name), "artist": artist_names[0], "artists": artist_names, "spotify_uri": uri})
        for child in value.values():
            _walk_spotify_tracks(child, out)
    elif isinstance(value, list):
        for child in value:
            _walk_spotify_tracks(child, out)


def _spotify_playlist_tracks(url: str, limit: int) -> tuple[str, list[dict[str, Any]]]:
    match = re.search(r"(?:playlist/|embed/playlist/)([A-Za-z0-9]+)", url)
    if not match:
        raise ValueError("That Spotify link does not look like a playlist URL.")
    playlist_id = match.group(1)
    response = httpx.get(f"https://open.spotify.com/embed/playlist/{playlist_id}", timeout=18, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    html = response.text
    title_match = re.search(r'"name"\s*:\s*"([^"]{1,160})"\s*,\s*"(?:uri|type)"', html)
    name = "Spotify playlist"
    try:
        scripts = re.findall(r'<script[^>]+(?:id="__NEXT_DATA__"|type="application/json")[^>]*>(.*?)</script>', html, re.S)
        parsed_any = False
        found: list[dict[str, Any]] = []
        for script in scripts:
            try:
                data = json.loads(script)
            except Exception:
                continue
            parsed_any = True
            if isinstance(data, dict):
                props = data.get("props", {}).get("pageProps", {})
                page_name = props.get("name") or props.get("title")
                if page_name:
                    name = _clean(page_name)
            _walk_spotify_tracks(data, found)
        if not found:
            # Spotify embeds sometimes serialize track metadata in a JSON blob
            # without a conventional Next.js data script.
            for raw in re.findall(r'\{[^{}]{0,2500}"(?:artists|artist)"[^{}]{0,2500}\}', html):
                try:
                    item = json.loads(raw.replace("&quot;", '"'))
                    _walk_spotify_tracks(item, found)
                except Exception:
                    continue
        seen = set()
        clean = []
        for item in found:
            key = (_clean(item.get("title")).casefold(), _clean(item.get("artist")).casefold())
            if key not in seen and all(key):
                seen.add(key)
                clean.append(item)
            if len(clean) >= limit:
                break
        if not clean:
            raise ValueError("Spotify did not expose public track metadata for this playlist. Make sure it is public, then try its YouTube Music equivalent.")
        # Resolve the Spotify track list to playable YouTube Music song IDs.
        resolved = []
        for track in clean:
            try:
                rows = yt_music.search(f"{track['title']} {track['artist']}", filter="songs", limit=5)
                best = rows[0] if rows else None
                if best:
                    item = normalize_ytmusic(best)
                    if item.get("video_id"):
                        resolved.append(item)
            except Exception:
                continue
        return name, resolved
    except Exception:
        raise


@app.post("/music/import-playlist")
async def music_import_playlist(payload: PlaylistImportRequest):
    url = payload.url.strip()
    if not url.startswith(("https://", "http://")):
        raise HTTPException(400, "Paste a full public YouTube or Spotify playlist URL.")
    try:
        if "open.spotify.com/" in url:
            name, results = await asyncio.to_thread(_spotify_playlist_tracks, url, payload.limit)
        elif any(domain in url for domain in ("youtube.com/", "youtu.be/", "music.youtube.com/")):
            playlist_id = ""
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            playlist_id = parse_qs(parsed.query).get("list", [""])[0]
            if not playlist_id and parsed.netloc.endswith("youtu.be"):
                raise ValueError("That YouTube link is a video, not a playlist. Paste a playlist link.")
            if not playlist_id:
                raise ValueError("Could not find a playlist ID in that YouTube URL.")
            def get_youtube_playlist():
                try:
                    data = yt_music.get_playlist(playlist_id, limit=payload.limit)
                    rows = [normalize_ytmusic(row) for row in data.get("tracks", [])]
                    rows = [row for row in rows if row.get("video_id") and row.get("title")]
                    return _clean(data.get("title")) or "YouTube playlist", rows
                except Exception:
                    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist", "playlistend": payload.limit}
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        data = ydl.extract_info(url, download=False)
                    rows = []
                    for entry in data.get("entries") or []:
                        if not entry:
                            continue
                        vid = entry.get("id") or entry.get("url")
                        if not vid:
                            continue
                        rows.append(normalize_ytmusic({"videoId": vid, "title": entry.get("title"), "artists": [{"name": entry.get("uploader") or entry.get("channel") or "Unknown Artist"}], "thumbnails": entry.get("thumbnails")}))
                    return _clean(data.get("title")) or "YouTube playlist", [row for row in rows if row.get("video_id") and row.get("title")]
            name, results = await asyncio.to_thread(get_youtube_playlist)
        else:
            raise HTTPException(400, "Supported links: public Spotify playlists and YouTube playlists.")
        if not results:
            raise HTTPException(422, "No playable tracks were found in that playlist.")
        return {"name": name, "results": results, "items": results, "count": len(results)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Playlist import failed: {exc}") from exc


@app.get("/music/resolve/{video_id}")
async def music_resolve(video_id: str):
    try:
        url, meta = await _resolve(video_id)
        return {"video_id": video_id, "url": url, "track": meta, "expires_in": CACHE_SECONDS}
    except Exception as exc:
        raise HTTPException(502, f"Stream resolution failed: {exc}") from exc


@app.get("/music/stream/{video_id}")
async def music_stream(video_id: str, request: Request):
    try:
        url, _ = await _resolve(video_id)
    except Exception as exc:
        raise HTTPException(502, f"Stream resolution failed: {exc}") from exc

    headers = {"User-Agent": "Mozilla/5.0"}
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]
    client = httpx.AsyncClient(follow_redirects=True, timeout=None, headers=headers)
    try:
        upstream = await client.send(client.build_request("GET", url), stream=True)
        if upstream.status_code == 403:
            await upstream.aclose()
            cached = _stream_cache.pop(video_id, None)
            try:
                url, _ = await _resolve(video_id)
                upstream = await client.send(client.build_request("GET", url), stream=True)
            except Exception:
                await client.aclose()
                raise HTTPException(502, "Audio source refused playback; refresh the song or choose another version.")
        if upstream.status_code >= 400:
            status_code = upstream.status_code
            await upstream.aclose(); await client.aclose()
            raise HTTPException(status_code, "Upstream audio stream failed")
        response_headers = {k: upstream.headers[k] for k in ("content-type", "content-length", "content-range", "accept-ranges", "etag") if k in upstream.headers}
        response_headers["cache-control"] = "no-store"
        async def iterator():
            try:
                async for chunk in upstream.aiter_bytes(64 * 1024):
                    yield chunk
            finally:
                await upstream.aclose(); await client.aclose()
        return StreamingResponse(iterator(), status_code=upstream.status_code, headers=response_headers, media_type=upstream.headers.get("content-type"))
    except HTTPException:
        raise
    except Exception:
        await client.aclose()
        raise


@app.get("/lyrics")
async def lyrics(track_name: str = Query(min_length=1), artist_name: str = Query(default=""), album_name: str = Query(default=""), duration: float | None = Query(default=None)):
    params = {"track_name": track_name, "artist_name": artist_name}
    if album_name: params["album_name"] = album_name
    if duration is not None: params["duration"] = duration
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{LRCLIB_BASE_URL}/api/get", params=params)
    if r.status_code == 404:
        return {"found": False, "lyrics": None, "synced_lyrics": None}
    if r.status_code >= 400:
        raise HTTPException(502, "Lyrics provider failed")
    data = r.json()
    return {"found": True, "lyrics": data.get("plainLyrics"), "synced_lyrics": data.get("syncedLyrics"), "source": "lrclib"}
