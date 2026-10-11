"""
voicecheck.py — is this take of her voice in her own register?

The voice model (gpt-4o-mini-tts) now and then drifts into a deep, almost
male voice (11 Oct: "sounds creepy"). openai_tts checks the start of every
take with pitch() and asks again for one below DEEP_HZ. A short line it is
about to keep in its cache is first heard back (transcribe / sounds_like):
some takes come out half Slovak, and a cached one is said so every time.
"""

import difflib
import io
import re
import wave

import numpy as np

PCM_RATE = 24000


def pitch(pcm, sr=PCM_RATE):
    """The median pitch (Hz) of 24 kHz s16 speech, or None when there is too
    little voiced sound to tell (a plain autocorrelation over 40 ms frames)."""
    x = np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    fr, lo, hi, out = int(0.04 * sr), sr // 400, sr // 70, []
    for i in range(0, len(x) - fr, fr):
        w = x[i:i + fr] - x[i:i + fr].mean()
        if np.sqrt((w * w).mean()) < 800:
            continue                                   # silence or a breath
        spec = np.fft.rfft(w, 2 * fr)                  # (np.correlate: 5x slower on the Pi)
        ac = np.fft.irfft(spec * np.conj(spec))[:fr]
        seg = ac[lo:hi]
        # the shortest period nearly as strong as the best: twice the period
        # scores as well and would read an octave too deep
        k = lo + int(np.argmax(seg >= 0.85 * seg.max()))
        while k + 1 < hi and ac[k + 1] > ac[k]:
            k += 1                                     # up to that peak's top
        if ac[k] > 0.3 * ac[0]:
            out.append(sr / k)
    return float(np.median(out)) if len(out) >= 5 else None


CHECK_MODEL = "gpt-4o-transcribe"   # (the mini one heard Slovak in good Polish too)


def transcribe(client, pcm, sr=PCM_RATE):
    """What a listener hears in this 24 kHz s16 take (Polish)."""
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    b.seek(0)
    b.name = "take.wav"
    return client.audio.transcriptions.create(model=CHECK_MODEL, file=b, language="pl").text


def _words(text):
    return re.findall(r"[a-ząćęłńóśźż]+|\d+", (text or "").lower())


def sounds_like(text, heard, least=0.5):
    """The take was heard as (mostly) the words meant. Digits and number words
    both count ("0 do 0" / "zero do zera"); a take heard with Czech/Slovak
    letters ("Súham") is not."""
    if re.search(r"[áéíýůúšěřčžďťňőűöüä]", heard or "", re.I):
        return False
    want = [w for w in _words(text) if not w.isdigit()]
    got = [w for w in _words(heard) if not w.isdigit()]
    if not want:
        return True                     # only numbers: nothing to compare
    return difflib.SequenceMatcher(None, want, got).ratio() >= least
