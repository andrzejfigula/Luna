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

## Batch 15

| # | Item | Why | Status |
|---|------|-----|--------|
| 57 | **Hold to interrupt** — holding a finger while she talks stops her and listens to you at once | Barge-in without shouting over her | ✅ |
| 58 | **Voice messages** — "nagraj wiadomość": your next sentence is recorded as-is; whoever comes by next hears "masz wiadomość", and "odtwórz wiadomość" plays it in your own voice | A family message board that talks | ✅ found while testing: Vosk ends an utterance at a ~1 s pause, cutting messages — while recording, its endpoints are ignored until 2 s of silence; an envelope shows while a message waits |

## Batch 16

| # | Item | Why | Status |
|---|------|-----|--------|
| 59 | **The morning hello knows your to-do list** — it may mention one item in passing | Lists are in real use already (a to-do list appeared on the Pi while I worked) | ✅ |
| 60 | **Safe restarts** — `restart.sh` waits for 3 quiet minutes and appends the log | My deploys were interrupting real conversations and erasing their log | ✅ |


## Batch 17

| # | Item | Why | Status |
|---|------|-----|--------|
| 61 | **Calculator** — "ile to jest 17 razy 23?", "15% z 80", "pierwiastek z 144", "dwa do potęgi dziesięć", answered locally (`calc.py`) | Kitchen and homework maths in 0 s instead of 2, and it works offline (Vosk's "dwanaście razy siedem" too) | ✅ strict: every word must be a number, an operator or a filler, so "ile razy dziennie podlewać kwiatki?" still goes to the model |
| 62 | **Days until** — "ile dni do Wigilii / weekendu / piątku / 15 marca / Wielkanocy?" | Kids ask it every December; Easter is computed, not looked up | ✅ "Do Wigilii zostało 81 dni, czyli około 12 tygodni." |
| 63 | **Good night mentions tomorrow's alarm** — "Dobranoc! Budzik masz na siódmą trzydzieści." | The last thing you want to know before sleep is that the alarm is set | ✅ only alarms within 16 h |
| — | **Web panel on the home network** (lists, reminders, messages, photos, "say it out loud" from a phone) | Managing her from the sofa | ⏸ written but parked: it opens a network port, so it waits for your OK |

## Batch 18 — for kids (and forgetful grown-ups)

| # | Item | Why | Status |
|---|------|-----|--------|
| 64 | **Maths quiz** — "przepytaj mnie z tabliczki mnożenia" / "quiz z dodawania do dwudziestu" / "pobawmy się w rachunki": 5 questions, big on her screen, a second try, a score | Loona-style play that is also homework | ✅ answers in words or digits; "nie wiem" moves on, "koniec" stops, anything else ends it and goes to the model |
| 65 | **"Zapamiętaj, że…"** — stored at once as a fact, with a "remember" gesture | Facts used to wait for the end of the conversation, and the summariser could drop "klucze są w szufladzie" as trivia | ✅ "jestem uczulony…" is kept as a quote (not about Luna), "jutro…" keeps the date it was said; survives a consolidation running at the same time |
| 66 | **Spelling** — "jak się pisze żółw?": the word big on the screen, then letter by letter, with a tip for ó / rz / ż / ch | Polish spelling is the classic kid question | ✅ "jak się pisze po angielsku pies" still goes to the model |
| 67 | **"Co potrafisz?" is up to date** — the system prompt's list knew nothing of lists, photos, translator, messages… | She undersold herself | ✅ |

## Batch 19

| # | Item | Why | Status |
|---|------|-----|--------|
| 68 | **Guess the number** — "zagrajmy w zgadywankę": she thinks of 1–100, you guess, "więcej!" / "mniej!", the remaining range on her screen | The classic car-trip game, and it teaches halving | ✅ |
| 69 | **English words quiz** — "przepytaj mnie ze słówek angielskich": 70 first words (animals, colours, food, family…), "pies = ?" on the screen | Kids learn English early in Poland; the same quiz engine as the maths | ✅ "It's a dog!" counts, small mishearings too (fuzzy match) |
| 70 | **The log never fills the SD card** — rotated to `luna.log.1` beyond 5 MB, and a reboot no longer erases it (autostart now appends) | She runs for months; after a crash the log is the only witness | ✅ the autostart line on the Pi was changed from `>` to `>>` (`install_autostart.sh` does it too) |

## Batch 20

| # | Item | Why | Status |
|---|------|-----|--------|
| 71 | **Counting for hide and seek** — "policz do dwudziestu": "Chowajcie się!", the numbers in her own voice with each one big on the screen, then "Kto się nie schował, ten kryje! Szukam!"; "odliczaj od dziesięciu" counts down to "Start!" | The game every child plays, and a robot that counts fairly | ✅ numbers are made once and cached (`sounds.clip`), so the beat is steady and it works offline; up to 30; a tap stops it. Found: numbers above ten take 1–2 s to say, so the beat follows the voice instead of a fixed second |
| 72 | **Stopwatch** — "włącz stoper", "ile na stoperze?", "zatrzymaj stoper" → "Stop! 2 minuty i 14 sekund." Counts up in the corner of the screen | Planks, eggs, races around the house | ✅ |

## Batch 21

| # | Item | Why | Status |
|---|------|-----|--------|
| 73 | **Tooth-brushing coach** — "myjemy zęby": 2:00 counting down on her screen, a nudge every 30 s (top left → top right → bottom right → bottom left), a chime and praise at the end | Two minutes is forever for a child; a friend who counts makes it a game | ✅ a tap stops it; the nudges are spoken while the clock keeps running |
| 74 | **Routines step by step** — "zacznij poranek" walks through the list "poranek" ("dopisz umyj zęby do listy poranek"): one step big on the screen, "gotowe" → praise and the next one | Morning chaos, made into a checklist that talks back | ✅ the list stays as it is for tomorrow; "koniec" stops; anything else ends it and goes to the model |
| 75 | **"Co potrafisz?" knows the games and helpers** | — | ✅ |

## Batch 22

| # | Item | Why | Status |
|---|------|-----|--------|
| 76 | **Internet radio** — "włącz radio", "włącz Trójkę", "puść radio Nowy Świat", "wyłącz radio", "jakie to radio?"; a little note sways on her screen while it plays | Every Loona-like robot plays music; Polish radio is the household default | ✅ 7 stations built in (RMF FM, ZET, Jedynka, Dwójka, Trójka, 357, Nowy Świat), any other name found in the radio-browser.info directory and remembered; music ducks ~10× while she listens or speaks; reconnects if the stream drops |
| 77 | **Radio sleep timer** — "wyłącz radio za 30 minut", "radio na 20 minut" | Falling asleep to the radio | ✅ |
| 78 | **The music can't outlive her** — ffmpeg and pw-play die with Luna's process (PR_SET_PDEATHSIG), even after kill -9 | Otherwise a restart or crash would leave the radio playing with no way to stop it by voice | ✅ tested with kill -9 |

## Batch 23

| # | Item | Why | Status |
|---|------|-----|--------|
| 79 | **Wake up to the radio** — "budź mnie radiem": a wake-up alarm says good morning and starts your last station, fading in from a whisper over a minute ("budź mnie dzwonkiem" switches back) | Gentler than a chime, together with the sunrise on her screen | ✅ "jeszcze 5 minut" snoozes and stops the music; "obudź mnie radiem o siódmej" also goes to the model, which sets the alarm |
| 80 | **"Dobranoc" turns the radio off** — unless you set a sleep timer on purpose ("radio na 30 minut") | Good night means quiet | ✅ |

## Batch 24 — fixes from real use (4 Oct evening)

| # | Item | What was wrong | Status |
|---|------|----------------|--------|
| 81 | **Radio: she no longer answers the radio** | After "włącz radio" the conversation window stayed open; she answered an IKEA ad and put "kawa, płyn do prania" from a radio voice on the shopping list | ✅ while the radio plays, the window closes after every answer — each command needs "Luna" (a bare "Luna" still opens it for one sentence); no "late start" grace with the radio on |
| 82 | **Clipped words** | The TTS API sends a first burst, then pauses 0.2–0.35 s; with a 0.15 s prebuffer EVERY reply had a hole after its first syllables (measured: 179 ms of natural silence played as 441 ms) | ✅ prebuffer 0.35 s (played audio now matches the TTS exactly); if the network still falls behind mid-sentence: one clean 0.25 s rebuffer instead of chopped syllables, counted in the hourly health line |
| 83 | **Her voice player had low priority** | `nice -n 10` on the whole process was inherited by pw-play: her own face renderer outranked her voice; pygame also kept an unused 3 ms audio stream open; OpenCV's 4 worker threads busy-waited at ~20 % each | ✅ only renderer, camera and vision are niced (prio.py), players run at normal priority; SDL audio off; OpenCV on 1 thread |
| 84 | **"She just looks at me"** | (1) after every answer the mic was deaf for 1.4 s (echo guard 0.6 + settle 0.8, audio thrown away) — the first words of a quick reply were lost; (2) the 10 s window counted from the end of her answer, and a sentence started as it closed was dropped as "no wake word" | ✅ deaf time 0.65 s (the persistent player knows when her last sample plays); a sentence that BEGAN inside the window, or up to 4 s after, is still answered (not after "pa!", "dobranoc" or with the radio on); log lines carry the time |
| 85 | **Half the CPU** — Luna used ~145 % of the Pi (70 °C); face detection alone 54 % | The cheap search near the last face missed often (Haar drops frames) and every miss fell back to a 123 ms whole-frame search | ✅ two misses allowed before searching everywhere, coarser scales for the whole-frame search (71 ms), and with nobody in view it searches 3× a second: vision 54 % → 24 %, Luna ~145 % → ~84 %. `kill -USR1 <pid>` logs CPU per thread and the detector's costs |

## Batch 25 — radio, round two

| # | Item | Why | Status |
|---|------|-----|--------|
| 86 | **"Co teraz gra?"** — the song's title, read from the stream (ICY metadata: Luna reads the stream herself, strips the titles and feeds ffmpeg) | The first thing you ask a radio | ✅ RMF FM, 357, Nowy Świat send titles; ZET sends empty ones, Polskie Radio none — then she says so |
| 87 | **"Ciszej" / "głośniej" while music plays changes the music**, not her voice ("mów ciszej" still means her voice); remembered | Turning the music down shouldn't make her whisper | ✅ |
| 88 | **"Następna stacja"** — through the built-in stations | — | ✅ |
| 89 | **Backup addresses** — when a stream won't start, the next address, and as a last resort the directory | Trójka's MP3 stream died tonight (ICY 401) while its HLS stream worked | ✅ a refused address is skipped at once instead of waiting for ffmpeg's retries |

## Batch 26

| # | Item | Why | Status |
|---|------|-----|--------|
| 90 | **Calm frame rate** — the face is drawn at 20 fps while she is awake but calm (not speaking, no gesture, scene, touch or countdown), 30 fps otherwise | A frame costs ~18 ms on the Pi (face 9 ms, full-screen head-tilt rotation 6 ms, flip 3 ms): 30 fps was over half a core | ✅ renderer ~55 % → ~38 % of a core; tilts under 0.4° (invisible) skip the rotation. Frame timing is in the SIGUSR1 dump |
| 91 | **How much she says** — "mów krócej" (one sentence, ≤12 words), "odpowiadaj dłużej" (4–6 sentences), "normalne odpowiedzi"; remembered | Some people want an assistant that answers and stops, kids want more | ✅ measured on "dlaczego niebo jest niebieskie?": 7–8 / 16–23 / 45–58 words. A soft "1–2 sentences" rule changed nothing — it needs the word count and "this overrides" |
| 92 | **A test that compiles every module** | A mangled escape in brain.py (which tests can't import on Windows) would only have shown up as a crash on the Pi | ✅ also rejects stray control characters from mangled "\b" |
| 93 | **Coloured lamp** — "lampka na niebiesko", "zmień kolor lampki na zielony" (red, green, blue, purple, pink, yellow, orange, white, warm) | A night light for a child's room, mood light for the evening | ✅ |
| 94 | **Lamp timer** — "lampka na 20 minut" / "włącz lampkę na pół godziny" goes out by itself | Falling asleep with the light on | ✅ said while the lamp is on: keeps its colour |
| 95 | **More ways to say goodbye and good night** — "super, to na razie wszystko", "dobra, to by było na tyle", "to teraz idziemy spać", "pora spać" | From tonight's log: "tutaj idziemy spać" didn't put her to sleep, and "super to na razie wszystko" went to the model — she answered nicely but kept listening | ✅ still whole-utterance only: "na razie nie", "dlaczego dzieci idą spać wcześniej?" go to the model |
| 96 | **Real news** — "jakie są wiadomości?", "co słychać na świecie / w sporcie?": the latest headlines from RMF24 (Polsat News as a fallback) summarised in 3 sentences, with the source | From the log: asked for "trzy najważniejsze wiadomości na dzisiaj" she invented some from her memory of the day | ✅ headlines go into the prompt for that one question only (not the history, not her memory); the system prompt now says she has no other news and must never invent any |
| 97 | **Weather switched on by voice** — "Luna, pogoda dla Krakowa", "ustaw pogodę na Gdańsk", "mieszkam w Zakopanem"; "wyłącz pogodę" | The forecast needed coordinates typed into .env — nobody did it, so "jaka pogoda?" never worked | ✅ the town is put into the nominative by one small model call (the geocoder only knows "Kraków", not "Krakowa"), Polish places first but only on an exact name (the Polish search turned "Berlin" into "Barlinek"); still opt-in — nothing is fetched until someone names a place. "Pogoda w Berlinie?" is a question and goes to the model |
| 98 | **Weather anywhere** — "jaka jest pogoda w Berlinie?", "czy jutro pada w Zakopanem?", "jak tam pogoda na Teneryfie?" | Trips, family elsewhere | ✅ fetched for that one question, the home place stays |

## Batch 27 — who's who, and a character of her own

| # | Item | Why | Status |
|---|------|-----|--------|
| 99 | **YuNet face detection** — a small neural net (OpenCV Zoo, 232 KB) instead of the Haar cascade, when its model is in `data/models/` | Steadier (Haar dropped frames), cheaper (45 ms vs 71 ms a look), and it gives the five landmarks recognition needs | ✅ Haar stays as the fallback; with nobody in view it looks 3× a second |
| 100 | **Recognising the people at home** — "Luna, to jest Kasia", "jestem Andrzej", "poznaj Olę", "zapamiętaj moją twarz, mam na imię Ola": 4 s of samples of the one face in view (SFace, 38.7 MB; numbers only, never a picture, `data/people.json`); "zapomnij moją twarz" / "zapomnij twarz Kasi" | Greeting people by name, remembering whose plans are whose | ✅ she greets the person by name right after learning them (vocative from the model); the model is told who is in front of her; memory lines are tagged "[Kasia] …" so facts get the right name. Names must be capitalised as the cloud writes them ("to jest problem" is nobody); the name is put in the nominative ("Olę" → "Ola") by one small model call. Recognition runs at most every 2.5 s — an unknown face checked every frame took a whole core |
| 101 | **A character of her own** (`data/persona.txt`) — curious about the sky and the Moon, dry cheeky humour, her own opinions (violet, radio, smug cats, thunderstorms), proud of being a robot | So far she was "warm, playful, a bit cheeky" — pleasant, but nobody in particular | ✅ |
| 102 | **Reciprocity** — every answer the model also rates how the words treated HER (kind / neutral / rude / insulting / apologetic); a score per person (by face) moves with it and heals over time; kind people get warmth and affection, rudeness gets coolness and sarcasm, an insult makes her offended — curt, dignified, no small favours until an apology | You asked for it: polite to the polite, impolite to those who insult her | ✅ tested on the model: compliments → "love"; "zamknij się, głupia maszyno" → hurt, then cool; a timer still set while offended; "opowiedz dowcip" → "Najpierw może jakieś przeprosiny?"; after "przepraszam" she warms up. Limits in the prompt: never vulgar, hateful, threatening or cruel; timers, alarms, safety always; gentle with children |
| 103 | **The family, learned from photos** — Andrzej, Emilka and Maja: one photo each, 8 webcam-like variants (mirror, darker/brighter, blur, low resolution, JPEG, warm light) → 8 samples per person; a note per person in `people.json` goes into the prompt ("Maja — 8 lat, dziecko: mów prosto, ciepło…") | You asked for it | ✅ same person 0.88–0.99, different people 0.02–0.25 (threshold 0.40); live, through the C270: "this is Andrzej (0.62)". Saying "Luna, jestem …" in front of her adds webcam samples (up to 30 per person) and makes it surer. The photos were deleted from the Pi after use; only the numbers stay |
| 104 | **Hello by name, for each person** — everyone gets their own first hello of the day (weather, plans, memory) and later short ones by name ("Cześć, Maju, jeszcze nie śpisz?"); she waits a moment for recognition before speaking | One "first today" for the whole house meant Emilka never got her morning briefing after Andrzej; and the fixed phrases were masculine ("Wyspałeś się?", "wróciłeś") | ✅ fixed phrases (for strangers) now need no gender |
| 105 | **Voice messages for a person** — "nagraj wiadomość dla Emilki": she tells Emilka when she sees her ("Masz wiadomość głosową od: Andrzej"); "odtwórz wiadomość" plays that person's messages, with who left them | A family message board that knows who is who | ✅ the sender's own messages don't nag them |
| 106 | **Child-safe news** — when the person in front of her is marked as a child (Maja), only headlines without violence, crime, fires, accidents, war or death | An 8-year-old asking "jakie są wiadomości?" shouldn't get a warehouse fire and a vandalised memorial | ✅ found while testing: one extra sentence at the end lost to "pick the 3 most important" — for a child the whole instruction is replaced. Maja: a football match, a new footbridge, a diver found safe; Andrzej: the full news |
| 107 | **Records per person** — guess-the-number: "Nowy rekord! Poprzedni: 9 prób."; maths quiz: "To już 3. bezbłędna runda!" | Something to beat, and it knows whose record it is | ✅ kept in settings by face |

## Batch 28

| # | Item | Why | Status |
|---|------|-----|--------|
| 108 | **Fewer phantom waves** — a wave must travel ≥ 0.8 face widths (was 0.35); she still waves back every time but says hello at most every 2 minutes | Tonight's log: "Hejka!", "Hej, hej!" seven times while Andrzej sat at the desk — hand movements of 14–27 px with a 40 px face; the real waves in the same log were 107–151 px | ✅ |
| 109 | **She learns faces by herself** — a sure recognition (≥ 0.50, ≥ 0.25 ahead of anyone else) adds one webcam sample a minute, up to 15 per person, kept apart from the photo/enrolment samples | The photos came from a phone in other light; through the C270 Andrzej scored 0.41–0.62, near the 0.40 line | ✅ live: one webcam sample later he scored 0.67 |
| 110 | **Homework help for a child** — when Maja asks a sum or a school task, she asks what Maja thinks and gives a hint instead of the answer; the local calculator steps aside for a child | Help that teaches, not a cheat sheet | ✅ found: the persona's "with a child" rules lost to a plain question (56 : 7 → "8" at once); said in the live prompt line for a recognised child it works: "ile razy 7 mieści się w 56?" |
| 111 | **A child's voice and stories** — slower, clearer, warmer delivery when a child is in front of her; bedtime stories may star the child ("…A teraz, Maju, zamknij oczka") | — | ✅ |
| 112 | **Everyone's own radio station** — "włącz radio" plays the station that person listened to last | Andrzej's RMF FM isn't Maja's music | ✅ |
| 113 | **She asks a stranger's name** — a face she doesn't know, in a home whose faces she does, gets "Cześć! Nie znam jeszcze twojej twarzy — jak masz na imię?" (at most every 30 min); the answer needs no "Luna", and a bare "Ola." counts for 20 s | Guests get to know her; and a family member she misses in poor light just says "Jestem Andrzej" and she learns that light too | ✅ one-word replies that aren't names ("Cześć", "Dzięki", "Ciszej"…) don't count — found by a test |
| 114 | **Her own day and mood** — a small diary of today (who she talked with and how often, kind and rude words, when the last chat was; `data/day.json`, new each day) goes into the prompt and colours her mood a little: livelier after a nice day, glad of company after hours alone, sleepy late at night | "Jak minął ci dzień?" used to get an invented answer; now: "Dziś rozmawiałam z Andrzejem, Mają i Emilką, było całkiem miło…" | ✅ found while testing: a local variable "mood" (the user's mood) inside the answer function shadowed the new module — every answer would have failed. A new test now flags any local that shadows an imported module |
| 115 | **Photos know who is in them** — after "zrób nam zdjęcie" she recognises the faces ("Pięknie wyszło! Andrzej i Maja na zdjęciu."), keeps it in `photos/people.json`; "pokaż zdjęcia Mai" shows only those; the gallery shows the names under each photo | A photo album that knows the family | ✅ the detector is shared with vision under a lock (a photo being tagged would have resized it mid-frame) |
| 116 | **A restart can no longer leave two Lunas** — the shutdown handler starts a 2 s hard-exit watchdog first, stops the radio before pygame; `restart.sh` kills a Luna still alive 5 s after stop | Tonight a process hung inside its shutdown (after "Shutting down", waiting on a lock), outlived two restarts and kept the microphone: the new Luna came up with "No input device matching 'C270'" — deaf. Between 23:00 and 23:10 two Lunas ran at once | ✅ the stuck one was killed (logged "restart: killed a stuck Luna") and the mic is back on the C270 |
| 117 | **Fixed: Luna froze when she started to speak** — the child-voice check (item 111) took `state.lock` while the speaking code already held it; a plain Lock waits for itself forever, and every other thread waiting for it stopped too: face, hearing, everything | "Luna hangs when I call her" — the log stopped at her first word after the 23:10 restart | ✅ the style is worked out outside the lock, and `state.lock` is now re-entrant (RLock) so such a helper can never freeze her again; a test checks it. The frozen process went away by itself thanks to item 116's watchdog |

## Batch 29 — never frozen again

| # | Item | Why | Status |
|---|------|-----|--------|
| 118 | **Freeze watchdog** (`watchdog.py`) — every 5 s: can `state.lock` be taken, does the face still draw frames? Stuck for 30 s → every thread's stack goes to the log (faulthandler) and the process ends; lwrespawn starts her again. `kill -USR2 <pid>` logs the stacks without stopping her | The 23:11 freeze lasted until someone noticed; and the log said nothing about where it was stuck | ✅ tested with a thread that keeps the lock: caught in 7 s (test settings), the culprit's line in the log |
| 119 | **Smoke test before every restart** (`tests/smoke_pi.py`) — imports the real modules on the Pi, starts speaking (silently) with nobody, an adult and a child recognised, builds the full prompt under the lock, runs local commands, checks the calculator steps aside for a child — each under a time limit. `restart.sh` refuses to restart when it fails, the running Luna stays | The unit tests can't import the Pi-only parts; the freeze passed them all. This would have hung on "start speaking, person=Maja" | ✅ |
| 120 | **Riddles** — "zadaj mi zagadkę", "pobawmy się w zagadki", "zagadka!": a round of 3, a hint after a wrong guess ("Hmm, nie krzesło. Podpowiedź: …"), the answer after the second; "kotek" counts for "kot" | Maja is 8 — the age of riddles | ✅ 31 riddles written by hand (`riddles.py`): the model's Polish riddles were too often untrue ("wiewiórka… nie jest zwierzęciem", "małpa ma długi nos") or gave the answer away. Rotate across rounds; work offline; "to zagadkowe" / "lubisz zagadki?" don't start a round |

## Batch 30

| # | Item | Why | Status |
|---|------|-----|--------|
| 121 | **Everyone in view** — up to two more faces besides the closest one are recognised every 2.5 s; the model hears "Also in view: Maja" and may talk to both ("Dobry wieczór, Andrzeju, Maju, jeszcze nie śpicie?") | A family sits together; she only ever knew about the biggest face | ✅ unknown ones count as "1 unknown" |
| 122 | **The right vocative** — "Maju", not "Majo" (the model's guess); kept per person in `people.json` (set for Andrzej, Emilka, Maja), found by a small model call for anyone new she learns; told to the model as "only when calling them directly" | "Majo" in a greeting, then "Co u Ciebie i Maju?" when the first fix was too blunt | ✅ Olu, Kasiu, Zosiu, Piotrze, Tomku, Aniu |
| 123 | **Self-learning keeps variety** — a webcam sample nearly identical (≥ 0.92) to one already kept is skipped | Sitting at the desk, a near-copy came every minute and pushed out the samples from other light | ✅ |
| 124 | **A backup a day** — memory, faces, lists, timers, settings, relations, her day, photo tags and the message index copied to `data/backups/YYYY-MM-DD/`, 7 days kept (`backup.py`; how to restore in SETUP.md) | All of it is learned over weeks and lives on one SD card | ✅ a day's folder is written under a temporary name and renamed, so it is complete or absent |
| 125 | **Reading aloud from the camera** — "przeczytaj mi tę stronę" with a book held up: the whole visible text, word for word, up to ~200 words, no comment | A bedtime book read by Luna; letters, labels | ✅ a rendered book page: 33 of 33 words read exactly. The "1–3 sentences" rule would have cut it short |
| 126 | **Homework held up to the camera** — "pomóż mi z tym zadaniem", "co jest w zeszycie", "zobacz mój rysunek" now send the high-detail picture | A sum in an exercise book is unreadable in the low-detail one | ✅ |
| 127 | **Birthdays** — "Maja ma urodziny 12 maja 2018", "moje urodziny są 14 lutego": kept with the person; "ile dni do urodzin Mai?" counted exactly ("…Skończy 9 lat."); on the day the first hello is a birthday wish ("Witaj, Maju! Wszystkiego najlepszego z okazji ósmych urodzin…"), a week before she knows it's coming | Family dates; models are bad at calendar sums | ✅ only for people she knows by face |
| 128 | **Names in any case** — "Mai", "Maję", "Emilki", "Emilce", "Andrzeja"… matched to the known person locally (`faces.match_name`) | The model turned "Mai" into "Mai", not "Maja"; and the month "3 maja" must not be Maja | ✅ used by birthdays and "pokaż zdjęcia Mai" |

## Batch 31

| # | Item | Why | Status |
|---|------|-----|--------|
| 129 | **"Cześć, która godzina?" answered at once** — a greeting before the time/date question no longer sends it to the model | From the log: "Cześć, która godzina?" took the 2-second route | ✅ "Która godzina w Tokio?" still goes to the model |
| 130 | **Her face greets you the way she feels** — a heart and loving eyes for someone she likes a lot (score ≥ 3), no wave and a neutral face for someone who was rude, the usual happy wave otherwise | Reciprocity should show before she says a word | ✅ |
| 131 | **Reply length per person** — "mów krócej" said by Andrzej is his setting; Maja keeps hers | One house, different tastes | ✅ an unrecognised speaker sets the house default |
| 132 | **Her diary** — at midnight her day (who she talked with, kind and rude words) goes to `data/diary.json` (14 days, in the daily backup); the last three days are in the prompt, so "co robiłaś wczoraj?" has a true answer | Her day used to vanish at midnight | ✅ also fixed a test that failed only between 23:49 and 23:59 |
| 133 | **No more silent xruns** — 0.15 s of silence queued between utterances (was 0.08) | The night's health lines: PipeWire xruns on her voice stream rising ~38 000 an hour while she slept. Turning pygame's audio off (item 83) let the graph run at 2048 samples (43 ms); pw-play keeps ~100 ms plus a cycle, so 80 ms starved it ~10× a second — inaudible in silence, but busy-looping the player (30 ms a cycle) | ✅ 0 xruns in 60 s after, player busy 0.13 ms a cycle |
| 134 | **"Przekaż Mai, żeby posprzątała pokój"** — a note for a person she knows by face; when she recognises them and all is quiet, she says it to them in words for them: "Maju, tata prosi, żebyś posprzątała swój pokój." Also "jak zobaczysz Emilkę, powiedz jej, że dzwoniła babcia" (`errands.py`, kept 7 days, in the backup) | A family message board without recording anything | ✅ phrased by the model with the vocative and who asked; a note from someone unknown doesn't guess who |
| 135 | **Files changed by someone else are no longer overwritten** — `faces` and `settings` re-read their file when it changed on disk before writing | The vocatives set by a script were lost at Luna's next self-learned face sample: she wrote her cached copy back over the file | ✅ tests for both; vocatives restored |
| 136 | **Person reminders with a time** — "o 18 powiedz Emilce, żeby zadzwoniła do mamy" (said when she sees Emilka after six), "codziennie o 20:30 przypominaj Mai, że pora spać" (every evening, once, when Maja is around); "usuń przypomnienia dla Mai", "nie przypominaj już Mai" | A timer rings for whoever is in the room; this finds the right person | ✅ digits and spoken hours ("o dwudziestej trzydzieści"); daily ones don't expire |
| 137 | **A test for names defined nowhere** — symtable checks every function's global names across all modules (a typo or a forgotten import fails only when that line runs, on the Pi) | After the freeze and the shadowed import, the Pi-only modules needed more than a compile check | ✅ none found in the code base; a planted one is caught |
| 138 | **A test that every `state.X` exists** in shared_state's slots | A missing slot fails only when its line runs | ✅ all present |

## Batch 32

| # | Item | Why | Status |
|---|------|-----|--------|
| 139 | **Dictation with the camera** — "zróbmy dyktando": she says a word with a spelling trap (żółw, rzeka, chmura, herbata, książka… 30 of them), Maja writes it on paper, holds it up and says "gotowe"; Luna reads the handwriting (high-detail picture, mistakes kept) and praises, or says what she sees ("Na kartce widzę „gura”. Podpowiem: piszemy przez ó z kreską.") and finally spells it ("…piszemy tak: g, o z kreską, r, a") | Polish spelling is THE homework of an 8-year-old; the camera makes it a game | ✅ rendered papers: 7 of 8 read exactly with the mistakes kept; one missed dot ("żeka" → "zeka") — when only dots and strokes differ she takes a second look before calling it wrong |
| 140 | **"Co potrafisz?" knows the newest things** — faces, birthdays, notes for a person, riddles, dictation, reading aloud, weather and news | The list stopped at the radio | ✅ |
| 141 | **Game results for the parents** — every quiz round (who, which game, score, the words or sums missed) goes into her day and diary; "jak Mai poszło dyktando?" → "3 na 5, pomyliła się w słowach rzeka i góra" | Parents want to know what to practise | ✅ |
| 142 | **Practice what went wrong** — in dictation and the multiplication table about half of the questions are ones this person missed lately (today and the 14-day diary) | Learning sticks where the mistakes were | ✅ per person, by face |
| 143 | **English words come back too** — words missed lately are asked again | — | ✅ |
| 144 | **Stars** — a perfect round (quiz, riddles, dictation) earns a gold star, shown popping in on her screen ("Dostajesz gwiazdkę! Masz już 4."); "pokaż moje gwiazdki" shows the collection; per person | Something to collect makes practice a game | ✅ drawn as polygons (the screen font has no ★) |
| 145 | **Sounds to fall asleep to** — "włącz szum deszczu", "szum morza", "biały szum" (+ "na 30 minut"; by default off after 45 min with a 20 s fade); "wyłącz szum". Made right here: a 30 s seamless noise loop shaped with one FFT, waves swelling every ~9.5 s, raindrops as decaying clicks (`ambience.py`) | For Maja's bedtime, and for anyone who sleeps better with rain | ✅ 0.2–1.4 % CPU; ducks while she listens or speaks; radio and sleep sounds don't play at once; "dobranoc" keeps it playing. Not yet heard on the speaker (it's night) |
| 146 | **She knows everyone's age** — the birthday and age (from "Maja urodziła się 12 maja 2018") are in each person's line of the prompt, all year round | "Ile lat ma Maja?" | ✅ also: "2 na 3 punktów" → "2 na 3" |
| 147 | **"Luna, nie słuchaj"** — the microphone really off for an hour (or "na 30 minut"): the audio is thrown away unheard, no Vosk, no cloud; a crossed-out microphone on her screen; a finger held on the screen turns it back on ("Znowu słucham!") | An always-listening device needs a real off switch — "Luna, cicho" only stops her talking | ✅ |
| 148 | **Learning the clock** — "pobawmy się w zegar", "naucz mnie zegara": a clock face with hands on her screen, "Która godzina jest na zegarze?"; any Polish way of saying it counts — "siódma trzydzieści", "wpół do ósmej", "kwadrans po siódmej", "za piętnaście ósma", "dwadzieścia przed ósmą", "7:30"; 7:30 and 19:30 are the same on a clock; full/half/quarter hours first, five-minute steps after two right in a row; she says it back both ways ("wpół do ósmej, czyli siódma trzydzieści") (`clockgame.py`) | Reading an analogue clock is second-grade homework | ✅ 13 phrasings parsed in the tests; results go to the diary and stars like the other quizzes |
| 149 | **Word problems** — "przepytaj mnie z zadań z treścią": a short story sum from the model ("Na podwórku bawi się 36 dzieci. Dołączyło 27…"), kept only when the model's own arithmetic checks out here (its expression is evaluated by a tiny safe evaluator) (`quizdata.py`) | The next step after the multiplication table | ✅ 4 of 4 generated problems correct and checked |
| 150 | **Capitals quiz** — "quiz ze stolic": 34 countries written by hand, answers in any form ("Paryż", "paris") | For kids and grown-ups | ✅ |
| 151 | **The conversation history knows who said what** — earlier turns are kept as "[Maja] …" | One history for the whole house: after Andrzej, Maja's "a ja?" was ambiguous to the model | ✅ |
