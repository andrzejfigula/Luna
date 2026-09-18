"""
openai_tts.py — OpenAI cloud TTS for Luna (same interface the old Piper engine had).

Same shape as the Piper engine so text_to_speech.py doesn't care which one is
plugged in:  tts.speak(text, on_audio_start=callback)

  OpenAI (response_format="pcm": 24 kHz, s16le, mono, streamed)
        |
        v
  python pump  ->  TTS_PLAYER (raw PCM on stdin, blocks until played)

Playback starts on the first streamed chunk, and on_audio_start fires at that
exact moment so the mouth animation begins in sync with the sound. The player
subprocess blocks until the audio has actually finished, which is what keeps
the mic-blocking / echo protection in text_to_speech.py correct.
"""

import os
import subprocess
import threading

from openai import OpenAI

from config import (
    OPENAI_API_KEY,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    OPENAI_TTS_SPEED,
    OPENAI_TTS_INSTRUCTIONS,
    OPENAI_TTS_TIMEOUT,
    TTS_PLAYER,
)

PCM_RATE = 24000   # fixed by the API for response_format="pcm"


class OpenAITTS:

    def __init__(self):
        self.lock    = threading.Lock()
        self._client = (OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TTS_TIMEOUT,
                               max_retries=1)
                        if OPENAI_API_KEY else None)
        self._raw_cmd = self._build_raw_player_cmd()
        if self._client is None:
            print("[TTS] No OPENAI_API_KEY — replies will be printed, not spoken")
        elif self._raw_cmd is None:
            print(f"[TTS] TTS_PLAYER={TTS_PLAYER!r} can't take raw PCM on stdin — "
                  "use aplay, ffplay, pw-play or paplay")
        else:
            print(f"[TTS] OpenAI {OPENAI_TTS_MODEL}/{OPENAI_TTS_VOICE} "
                  f"→ {os.path.basename(TTS_PLAYER)} @ {PCM_RATE} Hz")

    # ── player command for raw PCM on stdin ─────────────────────────────────
    def _build_raw_player_cmd(self):
        player = os.path.basename(TTS_PLAYER).lower()
        if player.startswith("paplay"):
            return [TTS_PLAYER, "--raw", f"--rate={PCM_RATE}",
                    "--format=s16le", "--channels=1"]
        if player.startswith("pw-play") or player.startswith("pw-cat"):
            return [TTS_PLAYER, "--playback", "--raw", f"--rate={PCM_RATE}",
                    "--format=s16", "--channels=1", "-"]
        if player.startswith("aplay"):
            return [TTS_PLAYER, "-q", "-r", str(PCM_RATE),
                    "-f", "S16_LE", "-c", "1", "-t", "raw", "-"]
        if player.startswith("ffplay"):
            return [TTS_PLAYER, "-autoexit", "-nodisp", "-loglevel", "quiet",
                    "-f", "s16le", "-ar", str(PCM_RATE), "-ac", "1", "-"]
        return None

    # ── public ──────────────────────────────────────────────────────────────
    def speak(self, text, on_audio_start=None):
        with self.lock:
            if self._client is None or self._raw_cmd is None:
                # no voice available — keep the caller's state machine
                # consistent (mouth/mic logic keys off on_audio_start)
                if on_audio_start:
                    on_audio_start()
                return
            self._speak_streaming(text, on_audio_start)

    # ── streaming: OpenAI pcm → (python pump) → player(raw stdin) ───────────
    def _speak_streaming(self, text, on_audio_start):
        player  = None
        started = False
        try:
            kwargs = dict(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE,
                          input=text, response_format="pcm", speed=OPENAI_TTS_SPEED)
            if OPENAI_TTS_INSTRUCTIONS:
                kwargs["instructions"] = OPENAI_TTS_INSTRUCTIONS

            with self._client.audio.speech.with_streaming_response.create(**kwargs) as resp:
                player = subprocess.Popen(self._raw_cmd, stdin=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL)
                for chunk in resp.iter_bytes(chunk_size=4096):
                    if not chunk:
                        continue
                    if not started:
                        started = True
                        if on_audio_start:
                            on_audio_start()
                    player.stdin.write(chunk)

            player.stdin.close()
            player.wait()
        except Exception as e:
            print(f"[TTS] streaming error: {e}")
            try:
                if player and player.poll() is None:
                    player.kill()
            except Exception:
                pass
        finally:
            if not started and on_audio_start:
                on_audio_start()   # never leave the caller waiting for sync


tts = OpenAITTS()
