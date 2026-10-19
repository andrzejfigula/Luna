# Luna — backlog

Open and parked items only. Everything done (#1–#741, 18 Sep – 18 Oct 2026)
is in `docs/backlog-done.md` — history, read it only when asked.
Add a row with `python tools/backlog_add.py "title — what changed" "why" [status]`
(numbers continue across both files; nothing needs to be read first).

Status: ✅ done · 🚧 in progress · ⏳ queued · 💤 parked (with the reason)

## Parked

- **Interrupting her by voice or camera** (#292, #295–#300, #738) — needs a USB
  speakerphone with hardware echo cancelling; see `docs/voice-interrupt.md`.
- **Web panel on the LAN** — parked until Andrzej explicitly says so.

## Items

| # | Item | Why | Status |
|---|------|-----|--------|
| 742 | **CLAUDE.md, a short backlog, tools/lastlog.sh** — notes loaded every session (module map, ship, rules, pitfalls); the done rows moved to docs/backlog-done.md; tools/backlog_add.py adds a row without reading; lastlog.sh prints only the useful log lines since the restart | Andrzej 18 Oct: save tokens in further development | ✅ |
| 743 | **Performance pass** — prompt_cache_key + cached-token log (78% of the prompt cached from the 2nd answer); a reply claiming a switch/list change with nothing done now says so; speculative transcription at 0.2 s silence (was 0.3); cloud warm-up in parallel (was 7.5 s serial); throttle bits in the hourly health line; local unit run skips Pi-only modules (OK in 6 s instead of 57 errors) | Andrzej 18 Oct: work on the performance proposals | ✅ |
| 744 | **Favourite stations by voice** — "włączyć ulubionych", "coś z ulubionych", "przełącz na ulubioną" handled locally; the model's "włącz moją ulubioną stację" and "włącz <a station she has>" no longer refused; favourites/catalog played from their own stream (not a web lookup); a refused "włącz…" no longer counts as tuned, so the poprawka line fires | Andrzej 18 Oct 18:58: three tries, no music | ✅ |
| 745 | **Lamp with a living picture** — "lampka meduzy", "włącz zorzę", "lampka zegar", "włącz świetliki", "lampa lawa", "lampka kominek": GPU scenes (gl_lamp.py, lamp_scenes.py) instead of the plain glow; "zmień lampkę" or a swipe for the next, timers kept | Andrzej asked for a screensaver-style ambient lamp next to plain light | ✅ |
| 746 | **Face at 45 fps, same pace; half the CPU per frame** — GPU face: numpy in-place layer uploads, layers in pygame's own byte order (shader swaps), partial clears, cached uniforms, small shaders for the stretch/layer passes, rows-only layer passes; per-frame animation steps scaled by frame length (robot_face._K, face.anim_fps) so DRAW_FPS=45 keeps today's pace; tools/render_bench.py (offscreen, fake clock, pixel diff, --trace) | Andrzej asked for 45 fps without losing quality: CPU per frame 15.9 -> ~8 ms (bench), frames at 30 fps pixel-identical to main, at 45 the blinks/eases/breathing time the same | ✅ |
| 747 | **Camera preview on request** — „pokaż podgląd kamery” / „ukryj podgląd” (also „pokaż / schowaj kamerę”, „nie pokazuj obrazu z kamery”, English) toggle the bottom-right camera picture; kept in settings camera_preview, LUNA_CAMERA_PREVIEW is only the default. With the camera off the preview disappears instead of freezing on the last frame. | Andrzej wanted the preview optional, switched by asking Luna, not by editing .env | ✅ |
| 748 | **Portraits only of a sure match** — a new portrait over an old one needs 0.60 and 0.20 ahead of the second-best person | Andrzej side-on in the dark became Emilka's portrait at 0.51 (her learned samples were clean) | ✅ |
| 749 | **Settings page: „pokaż ustawienia”** — settings_page.py + ui_screens.draw_settings: four tabs (Ogólne: default language pl/en, speech speed, reply length, captions, status bar; Ekran: camera preview, face fps 30/45/60 (face_renderer reads it live); Koszty: calls and an estimated PLN cost for today / yesterday / 7 days / this month from usage.json (now 62 days kept; config.API_COST_USD, USD_PLN); Reset: factory reset — memories, history, relations, mood, people, portraits, photo tags MOVED to data/reset-<stamp>/, then a restart; asks first, refused with a child in view). English as the default language: brain.english_wanted() and the STT short-sentence hint; „mów po polsku” still overrides for 2 h | Andrzej, 19 Oct: a settings page to change the language, reset memories and people, see running costs, switch flags like fps and the camera preview | ✅ |
