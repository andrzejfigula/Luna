
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
from openai_tts import tts

from shared_state import state
from config import (
    TTS_RATE,
    MIC_BLOCK_AFTER_SPEAK,
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


def _energy_loop():

    global _energy_phase

    while True:

        # Key the mouth on audio_playing (real sound), not speaking (the whole
        # call incl. synth time) — lips no longer flap during silent synth.
        with state.lock:
            speaking = state.audio_playing

        if speaking:

            _energy_phase += 0.18

            slow = abs(math.sin(_energy_phase * 0.9))
            mid = abs(math.sin(_energy_phase * 2.3)) * 0.5
            fast = abs(math.sin(_energy_phase * 5.1)) * 0.2

            raw = (slow + mid + fast) / 1.7

            jitter = random.uniform(-0.08, 0.08)

            energy = max(
                0.0,
                min(1.0, raw + jitter)
            )

            with state.lock:
                state.audio_energy = energy

            time.sleep(0.016)   # ~60 fps mouth animation while speaking

        else:

            _energy_phase = 0.0

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
