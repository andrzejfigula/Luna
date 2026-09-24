
"""
text_to_speech.py — Luna TTS system

Voice output is produced by OpenAI TTS via openai_tts.py (streamed PCM into
a blocking player). The player subprocess blocks until playback actually
completes, which keeps the mic-blocking + echo protection correct.

Everything around the engine:
  - speaking state lock          - talking mouth animation
  - microphone blocking          - echo protection
"""

import sys
import threading
import time
import random
import math
import subprocess
from openai_tts import tts, envelope
import sounds

from shared_state import state
from config import (
    TTS_RATE,
    MIC_BLOCK_AFTER_SPEAK,
    LIPSYNC_LATENCY_MS,
    LIPSYNC_GAIN,
    LIPSYNC_ATTACK,
    LIPSYNC_RELEASE,
)


# ============================================================================
# TTS ENGINE
# ============================================================================
#
#   OpenAI pcm stream  ->  player (raw stdin)
#        |
#        v
#   playback starts on the FIRST streamed chunk, and on_audio_start fires
#   at that exact moment so the mouth begins in sync with the sound.
#
# ============================================================================


def _on_audio_start():
    """Called by the TTS engine the instant real audio begins playing."""
    with state.lock:
        state.audio_playing = True


def _engine_speak(text):

    tts.speak(text, on_audio_start=_on_audio_start)

# ============================================================================
# Talking mouth energy animation
# ============================================================================

_energy_phase = 0.0


def _synthetic_energy():
    """Fallback when the engine gives no loudness envelope: a plausible
    talking rhythm from a few sines plus jitter."""
    global _energy_phase
    _energy_phase += 0.18
    slow = abs(math.sin(_energy_phase * 0.9))
    mid  = abs(math.sin(_energy_phase * 2.3)) * 0.5
    fast = abs(math.sin(_energy_phase * 5.1)) * 0.2
    raw  = (slow + mid + fast) / 1.7
    return max(0.0, min(1.0, raw + random.uniform(-0.08, 0.08)))


def _energy_loop():

    global _energy_phase
    smoothed = 0.0

    while True:

        # Key the mouth on audio_playing (real sound), not speaking (the whole
        # call incl. synth time) — lips no longer flap during silent synth.
        with state.lock:
            speaking = state.audio_playing

        if speaking:

            # Real lip sync: loudness of the frame the speaker is playing
            # right now (the envelope is stamped when playback started; the
            # latency offset covers the pipe + PipeWire + DAC delay).
            e = envelope.energy_at(time.time() - LIPSYNC_LATENCY_MS / 1000.0)
            if e is None:
                e = _synthetic_energy()
            e = max(0.0, min(1.0, e * LIPSYNC_GAIN))

            # asymmetric smoothing — snappy open, softer close
            k = LIPSYNC_ATTACK if e > smoothed else LIPSYNC_RELEASE
            smoothed += (e - smoothed) * k

            with state.lock:
                state.audio_energy = smoothed

            time.sleep(0.016)   # ~60 fps mouth animation while speaking

        else:

            _energy_phase = 0.0
            smoothed = 0.0

            with state.lock:
                state.audio_energy = 0.0

            time.sleep(0.05)    # idle — poll slower, saves CPU on the Pi



threading.Thread(
    target=_energy_loop,
    daemon=True
).start()



# ============================================================================
# Speech lock
# ============================================================================
#
# Prevents two voices talking together.
#
# Brain responses:
#     wait until Luna finishes
#
# Gesture reactions:
#     may be skipped
#
# ============================================================================

_speak_lock = threading.Lock()



def speak(text, can_drop=False):

    """
    Speak text.

    can_drop=False:
        Important replies always play.

    can_drop=True:
        Optional reactions can be skipped.
    """

    if not text:
        return


    if can_drop:

        if not _speak_lock.acquire(blocking=False):
            return

    else:

        _speak_lock.acquire()



    # Defined before the try so the finally block can always measure elapsed
    # time, even if something throws before the real speech starts.
    speech_start = time.time()

    try:

        with state.lock:

            state.speaking = True
            state.luna_mode = "speaking"
            state.frozen_emotion = state.emotion



        print(f"[Luna] {text}")



        # ------------------------------------------------------------
        # ACTUAL SPEECH — streamed; playback starts on the first chunk.
        # The mouth animation is started from _on_audio_start() at the
        # exact moment sound begins, so there's no silent lip-flap.
        # ------------------------------------------------------------

        speech_start = time.time()

        _engine_speak(text)



    finally:

        elapsed = time.time() - speech_start



        with state.lock:


            state.speaking = False

            state.audio_playing = False

            state.audio_energy = 0.0

            state.frozen_emotion = None

            state.luna_mode = "idle"



            # Since the player blocks until playback finishes,
            # only normal echo protection is needed.
            state.mic_unblock_time = (
                time.time()
                +
                MIC_BLOCK_AFTER_SPEAK
            )


            state.last_spoken_text = text.lower()

            state.last_spoken_time = time.time()



            # Do not consume conversation timeout
            # while Luna is speaking.

            if state.conversation_active:

                state.last_activity_time = time.time()



        print(
            f"[TTS] finished in {elapsed:.1f}s"
        )


        _speak_lock.release()


def play_sound(name, can_drop=True):
    """Play a non-verbal sound (see sounds.py). Shares the speech lock, so it
    never talks over a sentence; can_drop=True skips it when she is busy.
    Returns False when nothing was played (busy, or sound not ready).

    Unlike speak() it leaves luna_mode alone: a "hmm" while the answer is
    being fetched must not knock the face out of "processing"."""
    pcm = sounds.get(name)
    if not pcm:
        return False
    if not _speak_lock.acquire(blocking=not can_drop):
        return False
    try:
        with state.lock:
            state.speaking = True     # the mic aborts a listen while True
        print(f"[Luna] ({name})")
        tts.play_pcm(pcm, on_audio_start=_on_audio_start)
    finally:
        with state.lock:
            state.speaking = False
            state.audio_playing = False
            state.audio_energy = 0.0
            state.mic_unblock_time = time.time() + MIC_BLOCK_AFTER_SPEAK
            if state.conversation_active:
                state.last_activity_time = time.time()
        _speak_lock.release()
    return True


def play_sound_async(name):
    """play_sound() without blocking the caller (touch, idle scenes)."""
    threading.Thread(target=play_sound, args=(name,), daemon=True).start()
