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
| 5 | **Faster answers: speak the first sentence while the rest is still being written** — streamed model output, sentence-by-sentence TTS | Latency is the biggest enemy of a natural conversation | ⏳ |
| 6 | **Self-awareness** — she knows her own CPU temperature, uptime, how long you've been talking today; "jak się czujesz?" gets a real answer | Cheap, charming, true | ⏳ |
| 7 | **Rock, paper, scissors** with the camera — she counts, shows her hand on screen, looks at yours, keeps score | A game is the best "someone on the desk" moment | ⏳ |
| 8 | **Weather** (opt-in: `LUNA_LAT` / `LUNA_LON`) — open-meteo, no key; she knows the forecast when you ask or say good morning | Nothing leaves the Pi unless you set your location | ⏳ |
| 9 | **Night mode** — screen dims automatically during quiet hours, full brightness in the morning | The panel at full brightness at 2 a.m. is a lamp | ⏳ |
| 10 | **Health & resilience** — offline indicator on the face when the network/model is down, auto-recovery, a short "[health]" line in the log every hour | Today a dead network looks like a dead Luna | ⏳ |
