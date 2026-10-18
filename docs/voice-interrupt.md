# Interrupting Luna while she speaks: parked until better audio hardware

**Status (18 Oct 2026):** dropped. The voice and camera interruption code has been removed from main.
A finger held on the screen still stops her and she listens at once (BACKLOG #57). That is the only way to interrupt her for now.
We come back to this with a microphone that cancels her own voice. See "What to buy" below.

## The goal

You say "stop", "przestań", "cicho" or "Luna" while she is talking. She stops at once and listens, without "Luna" first.
She must never stop by herself.

## Why it is hard on this hardware

The microphone (C270 webcam) is on the desk next to the speaker. While she talks, the loudest thing in the microphone is **her own voice**.
Nothing removes it: there is no echo cancelling. A word said over her is a quieter voice mixed into a louder one.
Everything below tried to work around that, and none of it was good enough.

## What we tried

| When | Approach | Result |
|---|---|---|
| 6 Oct | Small Vosk recogniser that knows only the stop words, listening while she speaks (bargein.py) | Stopped her by herself in about 1 reply in 15. Caught "stop!" over her voice only 1–2 times in 8. Kept in log-only mode. |
| 6–17 Oct | Same, log only | 74 "would stop" in 915 replies, mostly her own voice ("Hejka!" heard as "stop", "piętnaście stopni" heard as "stop"). |
| 7 Oct | PipeWire's WebRTC echo canceller (pi/60-luna-echo-cancel.conf, tools/aec.sh) | Her voice in the mic dropped from ~4000 to ~14, so the canceller itself worked. But the audio was choppy (thousands of xruns, garbled speech). The webcam mic and the 3.5 mm jack run on two different clocks. Three tries, all parked (BACKLOG #295–#300). |
| 17 Oct | Vosk nominates a stop word, the cloud transcriber confirms it on a 1 s clip | Worked twice in a row, but needed tuning per sentence (her "stopni" vs your "stop") and a cloud call per candidate. Andrzej wasn't happy with the approach. Never merged. |
| 17 Oct | Camera: the mouth of the face in front of her changing more than the area above the nose (mouth.py) | Good with a still head (caught each talk-over 0.5–1 s in). With the head moving, talking looks exactly like a nod: mouth ≈ nose, even with the frames aligned. It also fires when you answer or smile at her greeting. |
| 17 Oct | Vosk stop word + camera agreeing; the mic's last 1.5 s replayed so your first words aren't lost | Worked in deliberate tests. In normal use (18 Oct) it stopped her greetings when Andrzej sat down or reacted. The replayed second held her own voice, she "heard" it as you and answered herself, three times in a row. |

## Why the approach is not good enough

1. **Her own voice drowns the microphone.** Without echo cancelling, any word detector hears stop words in her own speech. Every filter strict enough to stop that also misses real "stop"s said at normal volume.
2. **The camera can see a moving face, not intent.** Talking, nodding, smiling, laughing, answering a greeting and sitting down all move the mouth area. A talk-over with the head moving can't be told from a nod.
3. **Combining the two weak signals still gave false stops** in everyday use. A wrong stop (cutting a greeting, answering her own words) is worse than a missed one.
4. **Catching the first words needs the audio recorded during her speech.** Without echo cancelling, that audio is mostly her voice.

## What to buy

A **USB speakerphone with hardware echo cancelling**: the microphone and speaker in one device, on one clock. The device itself removes her voice from what the microphone sends. Examples: Jabra Speak 410/510, Anker PowerConf, EMEET M0/M2, or a ReSpeaker USB Mic Array with its AEC firmware and the speaker plugged into it.
What matters is that echo cancelling happens **in the device**. Software echo cancelling across two USB/jack clocks was the 7 Oct failure.

## When we come back to it

1. Plug in the speakerphone and point LUNA_MIC / the TTS output at it. LUNA_MIC=pw:<node> (pw-record) is still in speech_to_text.
2. Measure first: her voice level in the microphone while she speaks, with no one talking. It should be close to the room's silence.
3. Then a plain stop-word recogniser on the cleaned microphone is probably enough: the old bargein.py idea, in git history before 18 Oct.
4. Test against her own voice first (long replies, weather with "stopni", greetings) and keep it log-only until it never stops her by itself.

## What stays

- **Hold-to-stop on the screen.** It works reliably.
- **The camera's "is the person in front of me talking?" (mouth.py).** With the radio on, it quiets the radio and wakes her when you talk to her, even if the cloud missed "Luna". It is not used to interrupt her.
- **The mouth-patch recordings** in ~/mouth_dumps/ on the Pi, and `touch /tmp/mouth_dump.request` to save the last 10 minutes.
