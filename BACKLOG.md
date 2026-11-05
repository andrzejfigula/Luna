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
| 872 | **Telefon przez Bluetooth: SMS-y** — parowanie (kod na ekranie, okno 2 min), MAP: lista, odczyt, wysyłanie po „tak”, PBAP: nazwy; strony na ekranie, głos, odłączanie; treść SMS-ów tylko w pamięci, nigdy w logu ani dla modelu | Andrzej chciał czytać i wysyłać SMS-y z telefonu przez Lunę. Prawdziwy telefon jeszcze nie sprawdzony (potrzebny bluez-obexd) | ⏳ |
| 875 | **Telefon: „Napisz coś miłego do Mai” to SMS bez modelu czatu; niedosłyszana odpowiedź nie gubi szkicu** — phone.py rozpoznaje prośbę lokalnie, tekst pisze CRAFT_MODEL, potem czyta i pyta; po „Weź” pyta jeszcze raz; gdy model już powiedział tekst, tylko pyta | Model czatu recytował tekst zamiast tworzyć SMS, a „Wyślij” rozpoznane jako „Weź” kasowało szkic i były dwa pytania | ⏳ |
