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
| 15 | **Always-open audio stream** — one long-lived player fed with silence, so a reply starts without the 0.25 s pop-guard and player start-up | Another ~0.3 s off every answer, and no pop risk | ✅ sounds start at once; 0 underruns under load, max writer stall 205 ms vs 400 ms margin; CPU unchanged (158 % vs 161 %) |

## Batch 3

| # | Item | Why | Status |
|---|------|-----|--------|
| 16 | **Warm start** — the first cloud call in a process paid ~2 s extra (lazy SDK imports + handshake); now each client is warmed with a free request at start-up | Measured: first TTS byte 2.5 s cold → 0.4–0.6 s. Idle connections turned out NOT to go cold (0.6 s after 130 s idle), so no keep-alive pinging was needed | ✅ |
| 17 | **CPU diet** — Luna uses ~160 % of the Pi's 4 cores and the CPU sits at ~70 °C; find the hungry threads and trim them without making her look or listen worse | Cooler Pi, no throttling, more headroom for audio | ✅ empty room: 158 % → 51 % CPU, 70 → 63 °C. Face detection searches around the last face and slows to 2/s when nobody is there; the sleeping face is drawn at 12 fps |
| 18 | **Stories** — "opowiedz mi bajkę", "wyjaśnij dokładnie": longer answers when you ask for them (streaming makes them start just as fast; a tap stops them) | 1–3 sentences is right for chat, wrong for a bedtime story | ✅ a fairy tale starts after 2.6 s and flows in ~180-character pieces |
| 19 | **Sunrise alarm** — "obudź mnie o 7": the screen slowly brightens over the last 10 minutes like a sunrise, then a gentle chime and a good-morning with the weather | A wake-up light is a perfect job for a glowing face | ✅ tested with a compressed dawn: 3 % → 60 %, then chime and a waking good-morning. Found on the way: with no weather data she *invented* sunshine — now told explicitly she doesn't know |

## Batch 4

| # | Item | Why | Status |
|---|------|-----|--------|
| 20 | **"Co potrafisz?"** — the persona learns her own features (timers, alarm, game, volume, sleep, stories, hold-to-talk, tap-to-stop…) so she can explain them, in her own words | Features nobody knows about don't exist | ✅ |
| 21 | **"Pa!" ends the conversation** — goodbye phrases close the conversation window at once, with a wave | Otherwise she keeps listening for 10 s and may answer the next thing said in the room | ✅ |
| 22 | **Night voice** — during quiet hours she speaks at a lower volume | Full volume at midnight is rude | ✅ half volume in the quiet hours (`NIGHT_VOICE_GAIN`) |
| 23 | **Photo booth & mirror** — "zrób mi zdjęcie": 3-2-1, flash, the photo shown on her screen and saved to `photos/`; "pokaż lustro": the camera as a mirror for 15 s | Fun, and the camera is right there | ⏳ |
| 24 | **"Pokaż zegar"** — a big clock on her screen for 10 s | Quick glance from across the room | ⏳ |

