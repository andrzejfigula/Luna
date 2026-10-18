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
