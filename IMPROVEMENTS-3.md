# Branch improvements-3 — summary

Autonomous run, 31 Oct 2026. Each improvement was done in its own session,
taken from what went wrong in today's conversations (`tools/log_report.py`).

| # | Improvement | Commit | Status |
|---|-------------|--------|--------|
| 1 | Restart is not a return: last talk before a restart counts as a hello; later-morning fixed hellos no longer ask "Jak się spało?" | cdbcc96 | ✅ shipped |
| 2 | Pet names ("kochanie") for Andrzej only when he is alone with her (camera + last minute), stripped otherwise; "mówisz do mnie…" remarks are answered, not dropped as side talk | 37cf5b4 | ✅ shipped |
| 3 | Past-day questions ("o której … wczoraj", "w czwartek") answered from that day's talks, dated facts and plan, else "nie mam tego"; morning hello no longer invents "rozmowa o pracę" (prompt example); tidy keeps times; "…łeś" side talk stays quiet | f113f88 | ✅ shipped |
| 4 | "Poznałaś kogoś nowego?": nobody was met — the diary's unrecognised speaker ("ktoś nieznajomy") read as a new person; now labelled as such, plus facts on faces learnt/recognised today and stored face pictures; "masz jej zdjęcie?" gets no camera frame | 4ea7555 | ✅ shipped |
| 5 | Short second-person question ("Co robisz?", "Jak się masz?", "Słyszysz mnie?") with only the speaker in view is answered, not judged side talk; someone else in view → still quiet. Today's other quiet verdicts were already fixed by 2/3 | 87af397, 8169333 | ✅ shipped |

## Round 2 — "Ojej, poprawka — tego jednak nie zrobiłam" (14× in 2 days)

| # | Improvement | Commit | Status |
|---|-------------|--------|--------|
| 6 | A past-tense answer to "dodałaś?" ("Tak, dodałam…") no longer gets "poprawka"; fresh false claims still do | bf77d8e | ✅ shipped |
| 7 | "Jasne, włączam X" with a wrong or missing command now runs X when it is her switch; else "Co mam włączyć?" (the 4 logged cases were already fixed 23–30 Oct) | 8c5a169 | ✅ shipped |
| 8 | "Usuń plan lekcji Mai" (26 Oct, before clearing existed) works; added "przywróć plan" undo for clears/removals and "usuń X z planu (lekcji) Mai" | 684c7ad | ✅ shipped |

## Round 3 — she refuses things she can do (29–31 Oct logs)

| # | Improvement | Commit | Status |
|---|-------------|--------|--------|
| 9 | "otwórz/uruchom zegar(ek)" and the STT's "włączyć zegarek" open the clock; prompt names radio effects + night mode (settings/visualiser/night mode were already local) | 781fc15 | ✅ shipped |
| 10 | Theme switches: the 23–25 Oct refusals were already fixed; the one left (30 Oct) — "przełącz na retro" right after a theme switch is the character, not the oldies radio; prompt: a switch is never refused | 0df3f7e | ✅ shipped |

## Round 4 — branch improvements-4 (after v0.1), afternoon of 31 Oct

| # | Improvement | Commit | Status |
|---|-------------|--------|--------|
| 11 | No "kochanie" if an unnamed face or other family were seen in the last 3 min, or he's out of view (15:20 slip: unknown face "closest Emilka" right before) | 2ac31bf | ✅ shipped |
| 12 | Model's non-words fixed before TTS/screen (`polish.fix_nonwords`): zrobę→zrobię, odpalię→odpalę, brokułam→brokułami, nadawam→nadaję — only changes those 4 across 4119 logged lines | 02b2404 | ✅ shipped |

## Round 5 — branch improvements-5 (cut from improvements-4): robustness and speed from the logs

| # | Improvement | Commit | Status |
|---|-------------|--------|--------|
| 13 | Out of OpenAI credits: cloud skipped (re-checked every 3 min), recorded line, 'brak środków' on the status bar, NO CREDITS in the hourly line, clears itself | 3924d62 | ✅ shipped |
| 14 | Slow first sentence isn't the splitter: replay of 1355 answers — first sentence 0.02 s after the reply starts streaming, a clause cut would gain a mean 0.02 s; latency line now shows a "reply" stage (the model's wait: 2.5 s median in slow turns, hedge won 4 of 40) | b2f9b10 | ✅ shipped |
| 15 | Voice long after 'audio' (28 answers, up to 13.3 s): the tts/audio stages came from a filler/'Uśmiech!' or sentence 2's parallel fetch; now only sentence 1 marks them. 11 of 28 had both requests of sentence 1 stuck → a third TTS request at 4 s | 9969466 | ✅ shipped |

## Round 6 — branch improvements-6

| # | Improvement | Commit | Status |
|---|-------------|--------|--------|
| 16 | "Co robisz?" / "Co tam?": one connected sentence — no tacked-on mood, CPU heat or desk (per-message hint + prompt rule; "Jak się masz?" still says how she is) | (this commit) | ✅ shipped |
