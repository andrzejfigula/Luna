# Luna — backlog ("surprise pack")

Built autonomously on the `surprise-pack` branch, one item at a time, each
tested on the Pi before the next. Ground rules carried over from earlier
decisions: no idle animations (she does nothing on her own), Polish first,
voice is the scarce resource (rate limits, quiet hours, "Luna, cicho").

Status: ✅ done · 🚧 in progress · ⏳ queued · 💤 parked (with the reason)

| # | Item | Why | Status |
|---|------|-----|--------|
| 1 | **Emotional voice** — the reply's emotion goes into the TTS instructions (warmer when happy, softer when sad, bouncier when excited) | The face already shows the mood; the voice stayed flat | ✅ |
| 2 | **Hold to talk, tap to interrupt** — press and hold the screen to start listening without the wake word; tap while she talks to stop her mid-sentence | Vosk still misses "Luna" sometimes; and there was no way to stop a long answer | ✅ |
| 3 | **Local voice commands** — "głośniej / ciszej / głośność na 50", "dobranoc" (sleep: dim screen, eyes shut, quiet until morning), "dzień dobry" wakes her | Instant, offline, no model round trip for things that don't need one | ✅ |
| 4 | **Timers & reminders** — "minutnik na 10 minut", "przypomnij mi o 18 żeby zadzwonić do mamy"; persisted, survive restarts, a countdown on her face, she calls you when it's time | Makes her useful, not only nice | ✅ |
| 5 | **Faster answers: speak the first sentence while the rest is still being written** — streamed model output, sentence-by-sentence TTS | Latency is the biggest enemy of a natural conversation. Measured: first sound 1.8–1.9 s (was 2.3–3.5 s, outliers to 8 s) | ✅ |
| 6 | **Self-awareness** — she knows her own CPU temperature, uptime, how long you've been talking today; "jak się czujesz?" gets a real answer | Cheap, charming, true | ✅ |
| 7 | **Rock, paper, scissors** with the camera — she counts, shows her hand on screen, looks at yours, keeps score | A game is the best "someone on the desk" moment | ✅ |
| 8 | **Weather** (opt-in: `LUNA_LAT` / `LUNA_LON`) — open-meteo, no key; she knows the forecast when you ask or say good morning | Nothing leaves the Pi unless you set your location | ✅ (set `LUNA_LAT`/`LUNA_LON` to switch on) |
| 9 | **Night mode** — screen dims automatically during quiet hours, full brightness in the morning | The panel at full brightness at 2 a.m. is a lamp | ✅ |
| 10 | **Health & resilience** — offline indicator on the face when the network/model is down, auto-recovery, a short "[health]" line in the log every hour | Today a dead network looks like a dead Luna | ✅ |

## Batch 2

| # | Item | Why | Status |
|---|------|-----|--------|
| 11 | **Morning briefing** — the first greeting of the day is written by the model with real context: weather, today's reminders, an open thread from memory ("Dzień dobry! Dziś 14 stopni i deszcz — weź parasol. Jak poszła wczoraj rozmowa?") | The static "Dzień dobry!" knows nothing about your day | ✅ |
| 12 | **Talking props** — reply scenes the model can pick when it fits the topic: sun / rain / snow / cloud for the weather, a lightbulb for an idea, a question mark cloud, a musical note | She can *show* what she talks about, only while answering | ✅ |
| 13 | **"Mów wolniej / szybciej"** and settings that survive a restart (`data/settings.json`: speech speed, volume) | Small comfort, very noticeable | ✅ (speed persisted; volume is already kept by WirePlumber) |
| 14 | **Tests that run on any PC** — the streaming JSON parser, local commands, timers, memory dates — no Pi, no network | The parts most likely to break quietly | ✅ 25 tests, pass on Windows and on the Pi |
| 15 | **Always-open audio stream** — one long-lived player fed with silence, so a reply starts without the 0.25 s pop-guard and player start-up | Another ~0.3 s off every answer, and no pop risk | ⏳ |

