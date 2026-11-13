# Luna — backlog

Only what is open or parked. Everything finished is in `docs/backlog-done.md`
(history, 400 KB: never read it whole). Use the tool, it needs nothing read first:

    python -X utf8 tools/backlog.py find radio piosenk    # built already?
    python -X utf8 tools/backlog.py add "**Title** — what changed" "why" [status]
    python -X utf8 tools/backlog.py done N                # an open row is finished

Status: ✅ done · 🚧 in progress · ⏳ queued · 💤 parked (with the reason)

Ideas nobody has agreed to yet are in `docs/ideas.md`, sifted with `tools/ideas.py`.

## Parked

- **Interrupting her by voice or camera** (#292, #295–#300, #738) — needs a USB
  speakerphone with hardware echo cancelling; see `docs/voice-interrupt.md`.
- **Web panel on the LAN** — parked until Andrzej explicitly says so.

## Items

| # | Item | Why | Status |
|---|------|-----|--------|
| 896 | **Face freezes: the GPU, not her code** — all three watchdog restarts (24 Oct ×2, 8 Nov) had the render thread inside a GL draw call (gl_chars.soft, gl_face._quad, gl_face._rows in render_lamp), every other thread idle; nothing to fix in Python, the watchdog restart is the remedy. Open: do they follow a pattern (uptime, a scene) once log_report counts them | read from the stack dumps, 13 Nov | ⏳ |
