# Luna — backlog ("surprise pack")

Built autonomously on the `surprise-pack` branch, one item at a time, each
tested on the Pi before the next. Ground rules carried over from earlier
decisions: no idle animations (she does nothing on her own), Polish first,
voice is the scarce resource (rate limits, quiet hours, "Luna, cicho").

Status: ✅ done · 🚧 in progress · ⏳ queued · 💤 parked (with the reason)

**Where it stands (2026-10-04):** 48 items done, plus the fixes in "Found while
reviewing / testing". 53 commits on `surprise-pack`, not merged into `main`.
38 logic tests (`python -X utf8 -m unittest discover -s tests`) pass on Windows
and on the Pi; `tests/soak_pi.py` (40 conversations through the real
pipeline) runs clean. Not tested with a real person in front of the camera:
the game's hand reading, photos, the mood read from a face.

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
| 23 | **Photo booth & mirror** — "zrób mi zdjęcie": 3-2-1, flash, the photo shown on her screen and saved to `photos/`; "pokaż lustro": the camera as a mirror for 15 s | Fun, and the camera is right there | ✅ photos stay on the Pi in `photos/` (last 50) |
| 24 | **"Pokaż zegar"** — a big clock on her screen for 10 s | Quick glance from across the room | ✅ |

## Batch 5

| # | Item | Why | Status |
|---|------|-----|--------|
| 25 | **She waits for your answer** — when her reply ends with a question, the conversation window stays open longer | Otherwise a slow, thoughtful answer misses the 10 s window | ✅ +8 s after a question |
| 26 | **Recurring alarms & reminders** — "budzik w dni robocze o 6:30", "codziennie o 21 przypomnij o tabletkach" | A wake-up alarm you have to set every evening isn't one | ✅ |
| 27 | **"Pokaż przypomnienia"** — the list of timers, reminders and alarms on her screen | See at a glance what's set | ✅ |
| 28 | **Focus mode (pomodoro)** — "tryb skupienia": 25 min of quiet (no small talk, a calm face), then a break reminder | A desk companion that helps you work | ✅ |
| 29 | **Breathing exercise** — "ćwiczenie oddechowe": a circle on her screen grows and shrinks, she guides "wdech… wydech" | Calm-down moment on request — only when asked | ✅ 4-2-6 breathing, 5 cycles; her "wdech / wydech" recorded once so they land on time |

## Batch 6

| # | Item | Why | Status |
|---|------|-----|--------|
| 30 | **Lists** — "dopisz mleko do listy zakupów", "co mam na liście?", "skreśl chleb", "pokaż listę zakupów" (on screen); kept in `data/lists.json` | The most common thing people ask a kitchen/desk assistant | ✅ |
| 31 | **"Powtórz"** — replays her last answer instantly from the audio she already has (no new request) | Missed a word? Don't make her think again | ✅ starts in 0.04 s |

## Batch 7

| # | Item | Why | Status |
|---|------|-----|--------|
| 32 | **Auto-brightness from the camera** — the room's light (mean brightness of the camera picture) sets the screen level: dimmer in a dark room, full in daylight | Quiet hours are a guess; the camera *knows* the lights are off | ✅ light = brightness ÷ exposure (daylight measured −0.14). The dark threshold (−2.2) is a guess — check the `light` value in the hourly `[health]` line one evening and tune `AMBIENT_LOG_*` |
| 33 | **Photo gallery** — "pokaż zdjęcia": the photos she took, a tap shows the next one | Photos nobody can see again are lost | ✅ |
| 34 | **Soak test** — 40 mixed conversations through the real pipeline (model, TTS, audio, renderer) in a row: memory growth, errors, audio underruns | Many features landed in one day; find what breaks only after a while | ✅ 40 utterances: 0 exceptions, RSS flat at ~270 MB, 0 audio underruns. Found: 2 empty streamed answers (not reproducible alone) → now retried plainly, or what was already said is kept (`tests/soak_pi.py`) |

## Batch 8

| # | Item | Why | Status |
|---|------|-----|--------|
| 35 | **Night light** — "włącz lampkę": her whole screen becomes a warm, dim glow until "wyłącz lampkę" (or a tap) | A glowing screen next to the bed is a lamp already | ✅ |
| 36 | **The last seconds of a timer** — 5, 4, 3, 2, 1 counted big between her eyes | You see it coming from across the room | ✅ |
| 37 | **High five** — "przybij piątkę": her hand comes up big; tap it within 4 s | A touch game a kid gets instantly | ✅ |
| 38 | **Dice and coin** — "rzuć kostką", "rzuć monetą": rolled / flipped on her screen, result out loud | Settles who does the dishes | ✅ |

## Found while reviewing / testing (fixed)

| Problem | Effect it would have had | Fix |
|---|---|---|
| Questions matched local commands ("dlaczego w nocy jest ciszej?", "ile trwa pomodoro?", "co jest mocniejsze, papier czy kamień?", "co to jest lustro?", "powiedz dobranoc mojej córce") | volume down, focus mode on, a game started, the mirror shown, Luna asleep | volume/speed must be bare commands; one `is_question()` guard for all local commands; "dobranoc" must be the whole utterance — all in `tests/test_routing.py` |
| A timer cancel with an unmatched or empty label cleared everything | "wyłącz minutnik" deleted the weekday alarm too | cancel by exact label → word stem → kind; empty = kitchen timers; nothing on no match |
| Empty streamed model answer (2 of 40 in the soak test) | she would have played the offline apology | root cause found in a second soak run: the model sometimes puts an ordinary answer into the structured-output **refusal** channel and leaves the content empty — she now speaks the refusal text; otherwise retry plainly, or keep what was said |
| pw-play dying mid-sentence | the speaking call could hang on the old stream's clock | resync on restart, back-off, quiet logs |
| Wake-up alarm at 7:00 is inside the quiet hours | the night voice would have halved the alarm | timers ring at full volume |
| The "you are female" rule leaked onto the user | "rozbudziłaś" to a male user | address the user by the gender their name/memory implies, else neutrally |
| No weather data, yet asked | she invented sunshine | told explicitly she doesn't know |
| Mouth flag set from a late thread | mouth could keep flapping after a very short clip | set synchronously |

## Batch 9

| # | Item | Why | Status |
|---|------|-----|--------|
| 39 | **Local actions in the conversation** — what she did herself (dice, photo, volume, lists shown, game score…) goes into the chat history, so "co wypadło?" or "a jak teraz?" make sense to the model | Otherwise the model doesn't know half of what just happened | ✅ "rzuć kostką" → "co wypadło?" → "Wypadło trzy." |
| 40 | **She knows her settings** — volume, speech speed, screen brightness, night/focus/sleep state in the prompt | "Jak głośno teraz mówisz?" | ✅ |

## Batch 10 — shaving latency

| # | Item | Why | Status |
|---|------|-----|--------|
| 41 | **Quicker end of your sentence** — Vosk waits ~1.05 s of silence (measured); now 0.75 s of silence after real speech ends the utterance (`STT_END_SILENCE`) | Measured speaker→mic: text ready 1.28–1.46 s after the sentence instead of 1.50–1.90 s, transcripts complete | ✅ |
| 42 | **No silence queued in front of a reply** — the always-open player keeps only 0.08 s of silence queued between utterances (0.4 s margin only once speech flows) | First speech byte heard ~75 ms after the call instead of ~400 ms | ✅ |

## Batch 11

| # | Item | Why | Status |
|---|------|-----|--------|
| 43 | **Instant kitchen timer** — "minutnik na 10 minut" / "nastaw minutnik na pół godziny" handled locally (digits and Polish number words): no model round trip, works offline | The most common timer phrase doesn't need a language model | ✅ digits, number words, "pół godziny", "kwadrans"; with a label ("na makaron") it still goes to the model |
| 44 | **Translator mode** — "tłumacz na angielski" (or niemiecki, hiszpański…): every sentence comes back translated, spoken in that language, until "koniec tłumaczenia" | A desk robot that interprets for a visitor | ✅ the rule in the system prompt alone was ignored — the instruction now sits next to each utterance; ends itself after 10 idle minutes |

## Batch 12 — for the maker

| # | Item | Why | Status |
|---|------|-----|--------|
| 45 | **Cheaper idle listening** — the cloud check for a misheard "Luna" only runs when the first words sound like her name (or the utterance is 1–2 words), max 60/h | With a TV on, every sentence used to be a paid transcription | ✅ 2 of 9 TV-like sentences pass instead of 9; all tried mishearings still do |
| 46 | **API calls in the health line** — chat / tts / stt counted at the HTTP layer | The day's cost at a glance | ✅ |
| 47 | **"Pokaż status"** — temperature, load, uptime, network, memory size, API calls, audio health on her screen | A hobbyist's dashboard without SSH | ✅ |
| 48 | **"Luna, zrestartuj się"** — she says so, exits, and the autostart watchdog brings her back | After changing `.env`, no SSH needed | ✅ |

## Batch 13

| # | Item | Why | Status |
|---|------|-----|--------|
| 49 | **Snooze** — right after an alarm or timer rings, "jeszcze 5 minut" / "drzemka" sets it again (default 9 min) | The most natural thing to say to an alarm | ✅ the ring also opens the conversation window, so no "Luna" needed |
| 50 | **Extend a timer** — "dodaj 5 minut do minutnika", "przedłuż o minutę" | Cooking never goes to plan | ✅ |
| 51 | **Weekly, monthly, yearly** — "w każdy wtorek o 18 trening", "przypomnij o urodzinach mamy 12 maja co roku" | Birthdays and routines | ✅ found: a date in the past ("12 maja" in October) moved by one day and rang at once as missed — now the next year / an ignored one-off |
| 52 | **Bedtime story** — "bajka na dobranoc": a calm story, then she falls asleep herself | A kid's evening ritual | ✅ |
| 53 | **Captions** — what she says, and what she understood from you, as text at the bottom of the screen ("włącz napisy") | Noisy room, hard of hearing, or just checking she heard right | ✅ off by default, "włącz napisy" (kept in settings) |

## Batch 14

| # | Item | Why | Status |
|---|------|-----|--------|
| 54 | **"Która godzina?" answered instantly** — time and date in proper spoken Polish ("piętnasta dwadzieścia sześć"), locally | The most frequent question shouldn't wait 2 s for a language model | ✅ "Jest siedemnasta cztery.", "Dziś jest niedziela, czwarty października."; "która godzina w Tokio?" still goes to the model |
| 55 | **Live captions while you speak** — with captions on, the words appear as you say them (Vosk's partials), then the cloud's clean version | You see she's hearing you before she answers | ✅ |
| 56 | **A sleepy voice for the bedtime story** | A cheerful voice doesn't put anyone to sleep | ✅ |

