# Side talk in an open conversation: measured, left as it is

**Status (29 Oct 2026):** looked into, nothing changed. Re-measure with `tools/mouth_stats.py` if the camera or its place changes.

## The problem

After she answers, the conversation window stays open and she replies without "Luna".
If the family talks among themselves in that window, she sometimes answers them.
29 Oct, printing dolls: "Blokujesz. Lego blokuje." → "Nie blokuję, tylko próbuję zrozumieć…",
then "Weź się zacina, bo masz zły sterownik do drukarki." → "Może i sterownik ma swoje humory…".

## What already guards it

- `speech_to_text._addressed_to_luna`: inside the window, speech is ignored when no face was seen recently ("Ignored (nobody facing me)").
- The model's `to_luna` field: false for words clearly said to someone else. That kept her quiet 15 times in the last day of the log.
- `brain._to_someone`: "Tato, pomożesz mi…" overheard is settled without a model call.

## How often it goes wrong

13–29 Oct, ~580 answers: she replied to side talk about **4 times**.
In all that time she gave six "I didn't understand" replies. Two of them came after her name ("Wygląduj, Luna.", "Czy pracujączek?"), so they were real requests that she misheard.

## Idea 1: the mouth of the face in front of her (mouth.py)

In the printer exchange the face she saw read "mouth talking 0%": someone off camera was talking.
So: inside the window, ignore speech when the face in view isn't moving its lips?

Measured over every "heard=" line with a face in view ≥ 80% of the time (`tools/mouth_stats.py`):

| What was said | n | Mouth read ≤ 2% "talking" |
|---|---|---|
| With her name ("Luna…", "Hal…", "Moki…"), certainly to her | 436 | 51% |
| Answered by her | 209 | 55% |
| Everything else | 2470 | 53% |

Per day it was 40–77% low, 49% already on the first day (17 Oct), so it hasn't got worse; it never worked here.
At desk distance with the C270, a still-looking mouth means nothing:
"Luna, pokaż plan lekcji" and "Hal, o której Maja kończy szkołę?" both read 0%.
A gate on it would make her deaf to about half of real requests.
The "best ×" ratio doesn't separate the groups either.

It stays only where it is harmless: one extra reason to check for her name while the radio plays (`_mouth_talked`, an "or" with loudness and name-likeness).

## Idea 2: stay quiet instead of "nie zrozumiałam"

Inside the window, with no name: if her reply would only be "I didn't understand", say nothing.
Not done. Two of the six confused replies were misheard requests that needed exactly that reply.
Only ~4 side-talk replies in 16 days would be saved.

## What could work later

- A better view of the mouth: a closer or higher-resolution camera, or a face-landmark model with lip points (YuNet gives only the mouth corners).
- Knowing who is speaking from the voice (speaker direction from a mic array, or a voice match); that needs new hardware.
- Closing the window sooner after a reply that asked nothing; a trade-off with follow-ups said without "Luna".
