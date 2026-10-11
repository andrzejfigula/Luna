"""
voicecheck.py — is this take of her voice in her own register?

The voice model (gpt-4o-mini-tts) now and then drifts into a deep, almost
male voice (11 Oct: "sounds creepy"). openai_tts checks the start of every
take with pitch() and asks again for one below DEEP_HZ.
"""

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
        ac = np.correlate(w, w, "full")[fr - 1:]
        seg = ac[lo:hi]
        # the shortest period nearly as strong as the best: twice the period
        # scores as well and would read an octave too deep
        k = lo + int(np.argmax(seg >= 0.85 * seg.max()))
        while k + 1 < hi and ac[k + 1] > ac[k]:
            k += 1                                     # up to that peak's top
        if ac[k] > 0.3 * ac[0]:
            out.append(sr / k)
    return float(np.median(out)) if len(out) >= 5 else None
