# Pulse Web v13 rebuild notes

Changes from v12:
- Mobile-first sidebar behavior: hidden by default on phone widths, with a tap-to-dismiss scrim; desktop sidebar behavior remains.
- Responsive header, cards, library, player, lyrics, queue, and mini-player refinements for narrow screens and safe-area insets.
- Added an Import from link action in Library for public YouTube and Spotify playlist URLs. YouTube playlists use YouTube Music metadata; Spotify import depends on the public embed exposing track metadata and maps imported tracks to playable YouTube Music results.
- Pulse home playlists can show up to 24 tracks, and generated Pulse mixes retain up to 30 tracks rather than being truncated to 8/12.
- Queue now attempts to top itself up when fewer than four tracks remain, and uses discovery as a fallback when recommendations are sparse.
- Stream endpoint retries once after an upstream 403 by refreshing its cached media URL. If a specific video is still unavailable, the frontend searches for an alternate playable version of the same title.
- Added a hide button for the mini-player.
- Vite and the backend listen on the local network so a phone on the same Wi-Fi can test the site. The included web/.env uses the current PC LAN address `192.168.1.4`; update it if the PC's IPv4 address changes.
- Included the provided `web/.env` as requested.

Important limitations:
- This is a local development build. For a public deployment, set `VITE_PULSE_API_URL` to the deployed HTTPS API URL and configure production CORS.
- Spotify playlist import is best-effort and only works for public playlists whose embed exposes track metadata; Spotify may change that page format or limit access. YouTube playlist imports are the preferred path.
- Some YouTube videos are blocked or unavailable for streaming; the web app now retries once and then attempts a playable alternative, but cannot guarantee every source is playable.
- The frontend production build could not be run in this environment because this archive has no `node_modules` and package installation was unavailable here. Run `npm install` then `npm run build` in `web` on your PC before deploying.
- Keep the `.env` file local; do not publish it in a public repository or share the Supabase key unnecessarily.
