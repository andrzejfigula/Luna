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
