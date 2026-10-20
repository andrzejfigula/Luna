"""
tts_fx.py — a theme's voice changed on the Pi, as it streams (themes.py "fx").

  "robot" (HAL) — a metallic comb (a short echo feeding back: a ringing
                  tube) and a slow ring modulator; still easy to understand
  "deep"  (Ice) — pitch down without slowing: the line is asked for
                  PITCH× faster (speed_factor) and stretched back here

Each spoken take gets a fresh Chain; process() takes 24 kHz s16 mono chunks of
any size and keeps its state between them, so it runs on the stream itself.
"""

import numpy as np

RATE = 24000
PRESETS = {
    "robot": {"comb_ms": 4.5, "feedback": 0.55, "ring_hz": 52.0, "ring": 0.35},
    "deep": {"pitch": 1.16},       # ~2.5 semitones down
}


def preset(name):
    return PRESETS.get(name or "")


def speed_factor(name):
    """How much faster to ask the voice for, so the stretch keeps the tempo."""
    p = preset(name)
    return p.get("pitch", 1.0) if p else 1.0


class Chain:
    def __init__(self, name):
        self.p = preset(name) or {}
        self.n = 0                                  # samples seen (ring phase)
        d = int(RATE * self.p.get("comb_ms", 0) / 1000)
        self.tail = np.zeros(d, np.float32)         # the comb's last d outputs
        self.pos = 0.0                              # stretch: read position in prev+cur
        self.prev = np.zeros(0, np.float32)

    def process(self, pcm):
        if not self.p or not pcm:
            return pcm
        a = np.frombuffer(pcm[:len(pcm) // 2 * 2], np.int16).astype(np.float32)
        if "comb_ms" in self.p:
            a = self._robot(a)
        if "pitch" in self.p:
            a = self._stretch(a)
        return np.clip(a, -32768, 32767).astype(np.int16).tobytes()

    def _robot(self, x):
        g, d = self.p["feedback"], self.tail.size
        y = np.concatenate([self.tail, np.zeros(x.size, np.float32)])
        for i in range(0, x.size, d):               # y[n] = x[n] + g·y[n−d], d at a time
            j = min(i + d, x.size)
            y[d + i:d + j] = x[i:j] + g * y[i:i + j - i]
        self.tail = y[-d:].copy()
        y = y[d:] * (1 - g) * 1.4                   # back to about the input's loudness
        t = (self.n + np.arange(x.size)) / RATE
        self.n += x.size
        m = self.p["ring"]
        y = y * ((1 - m) + m * np.sin(2 * np.pi * self.p["ring_hz"] * t))
        return 30000 * np.tanh(y / 30000)           # soft, never a hard clip

    def _stretch(self, x):
        """Resample by 1/pitch (longer, lower) with linear interpolation,
        continuous across chunks."""
        step = 1.0 / self.p["pitch"]
        buf = np.concatenate([self.prev, x])
        if buf.size < 2:
            self.prev = buf
            return np.zeros(0, np.float32)
        idx = np.arange(self.pos, buf.size - 1, step)
        i = idx.astype(np.int64)
        f = (idx - i).astype(np.float32)
        out = buf[i] * (1 - f) + buf[i + 1] * f
        nxt = (idx[-1] + step) if idx.size else self.pos
        keep = int(nxt)                             # drop what is fully read
        self.prev = buf[keep:]
        self.pos = nxt - keep
        return out


def wrap(chunks, name):
    """The chunks of one take with the effect on (unchanged without one)."""
    if not preset(name):
        yield from chunks
        return
    ch = Chain(name)
    for c in chunks:
        out = ch.process(c)
        if out:
            yield out
