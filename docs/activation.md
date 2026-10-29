# Activation firewall (activation.py)

Every call of her name gets one verdict and one log line, without the words:

    [wake] REJECT about_her src=cloud conf=- mode=idle radio=0 tts_ago=41s words=7 ms=830

## Flow

    Vosk word / cloud wake check / radio-on face
            │  speech_to_text._wake(src, …) → activation.judge(Candidate)
            ▼
    REJECT  muted · cooldown · about_her            → silent, no window, cooldown 3 s
            no_face · not_her_name · english_side_talk (decided in STT, same line)
    ACCEPT  request     → the sentence goes on (commands → brain)
            bare        → "hm?" / "Tak?", 10 s window, brain knows she was called
            bare_unsure → no sound, the listening face, 5 s window, NOT "called"
            radio_face  → scope local: a command runs; anything else is dropped
                          (main: [wake] REJECT not_a_command), never the model
    EXPIRE  a bare_unsure call nobody followed (window ran out)
    CANCEL  muted · closed from outside · touch while she thinks — the pending
            call, and the answer being prepared: brain drops the reply, the
            streamed sentences stop, _speaking says nothing for that turn

Inside the open window nothing new: the brain's `_to_someone` and the model's
`to_luna` already close the window on speech not meant for her, so rejected
speech never extends it.

## Settings (config.py, Conversation)

| Setting | Default | |
|---|---|---|
| `WAKE_SURE_CONF` | 0.8 | Vosk's confidence for a sure bare "Luna" |
| `WAKE_UNSURE_QUIET` | True | unsure bare call: face only, no "hm?" |
| `WAKE_UNSURE_WINDOW` | 5 | seconds the unsure call waits for the request |
| `WAKE_REJECT_COOLDOWN` | 3.0 | no cloud-only wakes this long after a reject |
| `RADIO_FACE_LOCAL_ONLY` | True | radio on, no name: local commands only |
| `FOLLOWUP_NEEDS_NAME` | False | True: after an answer the next sentence needs "Luna" (not in a game, a page or when she asked) |
| `CONVO_TIMEOUT` | 10 | the follow-up window (unchanged) |
| `STT_SAVE_UTTERANCES` | env `LUNA_STT_SAVE` | opt-in: audio + words of each utterance, rejects marked |

## Measuring

`python3 tools/wake_replay.py luna.log luna.log.1` — old wakes through the new
rules, and a tally of the `[wake]` lines. 29 Oct, 950 wakes: 1 about her,
15 radio-face (6 of them went to the model, ~5 were side talk).

## Limits

- Her own voice: the mic is closed while she speaks (`state.speaking`,
  `mic_unblock_time`) and `echo.py` drops what comes back; there is no
  playback reference or AEC, so barge-in stays parked (`voice-interrupt.md`).
- Background audio (TV, radio voices): Vosk and the cloud can't tell a voice
  in the room from a speaker's. Covered only by the name being required and
  the radio-face rule; a TV saying "Luna" clearly still wakes her.
- Who is spoken to: with this camera the mouth carries no signal
  (`side-talk.md`); in the window it's the model's `to_luna`.
- No speaker verification: one C270 mic, kids' voices change — not worth it.
- Cancel can't stop the model request already sent, nor an action it ran
  (a timer it set stays) — only what she would say.
- The older log lines (`[Luna heard]`, `[STT] cloud …`) still carry the words.
