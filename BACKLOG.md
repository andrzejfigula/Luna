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
| 869 | **A second Vosk hears her name** — one that knows only "luna" and 96 everyday words runs beside the general one (radio off, passive); when only it hears her, the cloud must confirm (src vosk-name) | Recorded calls at 1/2/3 m: 28 of 30 against 15 for the general Vosk, 0 false on 15 lines and 17 logged clips. Dereverberation filters gave no real gain. One voice, quiet room: watch it in the logs | ⏳ |
