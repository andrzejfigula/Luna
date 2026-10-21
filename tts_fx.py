"""
tts_fx.py — a theme's voice changed on the Pi, as it streams (themes.py "fx").

  "robot" (HAL) — monotone and faster: each 32 ms frame rebuilt with zero
                  phase every 10 ms (the classic "robotization": one steady
                  75 Hz buzz instead of the voice's melody, its resonances
                  moved down by FORMANT: a bigger machine), read TEMPO× faster
                  than it is written; then a metallic comb (a short echo feeding
                  back: a ringing tube), a light ring modulator, an overdrive
                  (DRIVE), a bit crusher (CRUSH bits) and a reverb (REVERB
                  wet: a big metal room — 4 combs and 2 allpasses, Schroeder)
  "deep"  (Ice) — pitch down, TEMPO× faster: WSOLA squeezes the time by
                  PITCH·TEMPO (overlapping 40 ms pieces, each placed where it
                  matches best), then resampling stretches it by PITCH, lower.
                  (Asking the voice for a faster speed and stretching does
                  not work: 20 Oct, speed 1.1 and 1.28 gave the same length.)

Each spoken take gets a fresh Chain; process() takes 24 kHz s16 mono chunks of
any size and keeps its state between them, so it runs on the stream itself;
flush() returns what is still held back at the end of the take.
"""

import numpy as np

RATE = 24000
PRESETS = {
    # (21 Oct: 60 Hz with formants down 27% was hard to understand — back to 75 / 15%)
    "robot": {"robot_hz": 75.0, "formant": 1.15, "tempo": 1.2,
              "comb_ms": 4.5, "feedback": 0.4, "ring_hz": 52.0, "ring": 0.15,
              "drive": 2.5, "crush": 8, "reverb": 0.3},
    "deep": {"pitch": 1.3, "tempo": 1.2},     # ~4.5 semitones down, 20% faster
}
N, HS, SEEK = 960, 480, 240        # WSOLA: piece, output hop, search ±10 ms
_WIN = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / N)).astype(np.float32)
RN = 768                           # robotization frame (32 ms)
REV_COMBS = ((677, 0.70), (797, 0.68), (911, 0.66), (1031, 0.64))   # 28–43 ms
REV_ALLPASS = ((241, 0.6), (83, 0.6))
REV_TAIL = int(0.15 * RATE)        # the room's ring kept after the last word
_RWIN = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(RN) / RN)).astype(np.float32)


def preset(name):
    return PRESETS.get(name or "")


class Chain:
    def __init__(self, name):
        self.p = preset(name) or {}
        self.n = 0                                  # samples seen (ring phase)
        d = int(RATE * self.p.get("comb_ms", 0) / 1000)
        self.tail = np.zeros(d, np.float32)         # the comb's last d outputs
        self.pos = 0.0                              # stretch: read position in prev
        self.prev = np.zeros(0, np.float32)
        self.ibuf = np.zeros(0, np.float32)         # WSOLA input, from absolute ibase
        self.ibase, self.m, self.last = 0, 0, None
        self.ola = np.zeros(N, np.float32)
        self.rbuf = np.zeros(0, np.float32)         # robotization input, from rbase
        self.rbase, self.rk = 0, 0
        self.rola = np.zeros(RN, np.float32)
        self.rcomb = [np.zeros(d, np.float32) for d, _ in REV_COMBS]
        self.rap = [(np.zeros(d, np.float32), np.zeros(d, np.float32)) for d, _ in REV_ALLPASS]

    def process(self, pcm):
        if not self.p or not pcm:
            return pcm
        a = np.frombuffer(pcm[:len(pcm) // 2 * 2], np.int16).astype(np.float32)
        return self._run(a)

    def flush(self):
        if "pitch" in self.p:
            ha = HS * self.p["pitch"] * self.p.get("tempo", 1.0)
            return self._run(np.zeros(N + 2 * SEEK + int(ha), np.float32))
        if "robot_hz" in self.p:
            pad = RN + int(RATE / self.p["robot_hz"] * 2) + (REV_TAIL if self.p.get("reverb") else 0)
            a = np.frombuffer(self._run(np.zeros(pad, np.float32)), np.int16).astype(np.float32)
            fade = min(a.size, REV_TAIL)            # the room fades out, no click
            a[a.size - fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
            return a.astype(np.int16).tobytes()
        return b""

    def _run(self, a):
        if "robot_hz" in self.p:
            a = self._robotize(a)
        if "comb_ms" in self.p:
            a = self._robot(a)
        if self.p.get("reverb") and a.size:
            a = self._reverb(a)
        if "pitch" in self.p:
            a = self._stretch(self._wsola(a))
        return np.clip(a, -32768, 32767).astype(np.int16).tobytes()

    def _robotize(self, x):
        """Zero-phase frames laid every RATE/robot_hz samples: a flat buzz at
        robot_hz shaped by the words; taken every hop·TEMPO input samples."""
        hs = int(RATE / self.p["robot_hz"])
        ha = hs * self.p.get("tempo", 1.0)
        self.rbuf = np.concatenate([self.rbuf, x])
        end, out = self.rbase + self.rbuf.size, []
        while True:
            at = int(round(self.rk * ha))
            if at + RN > end:
                break
            fr = self.rbuf[at - self.rbase:at - self.rbase + RN] * _RWIN
            mag = np.abs(np.fft.rfft(fr))
            if self.p.get("formant", 1.0) != 1.0:   # bin k takes what was at k·FORMANT
                k = np.arange(mag.size)
                mag = np.interp(k * self.p["formant"], k, mag, right=0.0)
            y = np.fft.fftshift(np.fft.irfft(mag, RN)) * _RWIN
            self.rola += y.astype(np.float32) * (1.4 * hs / (RN * 0.375))   # Hann² overlap = 1; a buzz sounds quieter
            out.append(self.rola[:hs].copy())
            self.rola = np.concatenate([self.rola[hs:], np.zeros(hs, np.float32)])
            self.rk += 1
            keep = int(round(self.rk * ha))
            if keep > self.rbase:
                self.rbuf = self.rbuf[keep - self.rbase:]
                self.rbase = keep
        return np.concatenate(out) if out else np.zeros(0, np.float32)

    def _robot(self, x):
        g, d = self.p["feedback"], self.tail.size
        if x.size == 0:
            return x
        y = np.concatenate([self.tail, np.zeros(x.size, np.float32)])
        for i in range(0, x.size, d):               # y[n] = x[n] + g·y[n−d], d at a time
            j = min(i + d, x.size)
            y[d + i:d + j] = x[i:j] + g * y[i:j]
        self.tail = y[-d:].copy()
        y = y[d:] * (1 - g) * 1.4                   # back to about the input's loudness
        t = (self.n + np.arange(x.size)) / RATE
        self.n += x.size
        m = self.p["ring"]
        y = y * ((1 - m) + m * np.sin(2 * np.pi * self.p["ring_hz"] * t))
        dr = self.p.get("drive", 1.0)               # overdrive: soft, never a hard clip
        y = 22000 * np.tanh(dr * y / 30000) / np.tanh(dr)    # (louder when driven: kept level)
        if self.p.get("crush"):
            q = 32768 / 2 ** (self.p["crush"] - 1)  # fewer levels: a gritty, digital edge
            y = np.round(y / q) * q
        return y

    def _reverb(self, x):
        wet = 0.0
        for k, (d, g) in enumerate(REV_COMBS):     # parallel feedback combs: the decay
            y = np.concatenate([self.rcomb[k], np.zeros(x.size, np.float32)])
            for i in range(0, x.size, d):
                j = min(i + d, x.size)
                y[d + i:d + j] = x[i:j] + g * y[i:j]
            self.rcomb[k] = y[-d:].copy()
            wet = wet + y[d:]
        wet = wet * 0.25
        for k, (d, g) in enumerate(REV_ALLPASS):   # in series: the echoes diffused
            xt, yt = self.rap[k]
            xs = np.concatenate([xt, wet])
            y = np.concatenate([yt, np.zeros(wet.size, np.float32)])
            for i in range(0, wet.size, d):         # y[n] = −g·x[n] + x[n−d] + g·y[n−d]
                j = min(i + d, wet.size)
                y[d + i:d + j] = -g * wet[i:j] + xs[i:j] + g * y[i:j]
            self.rap[k] = (xs[-d:].copy(), y[-d:].copy())
            wet = y[d:]
        r = self.p["reverb"]
        return x * (1 - r * 0.5) + wet * r

    def _wsola(self, x):
        """Shorter by PITCH·TEMPO, same pitch: 50%-overlapped Hann pieces taken
        every HS·PITCH·TEMPO input samples, each nudged ±SEEK to continue the last."""
        ha = HS * self.p["pitch"] * self.p.get("tempo", 1.0)
        self.ibuf = np.concatenate([self.ibuf, x])
        end, out = self.ibase + self.ibuf.size, []
        while True:
            p = int(round(self.m * ha))
            if p + SEEK + N > end:
                break
            b = self.ibase
            if self.last is None:
                at = p
            else:
                nat = self.last + HS                # where the last piece would go on
                tpl = self.ibuf[nat - b:nat - b + HS]
                lo = max(p - SEEK, b)
                reg = self.ibuf[lo - b:p + SEEK + HS - b]
                c = np.correlate(reg, tpl, "valid")
                e = np.sqrt(np.convolve(reg * reg, np.ones(HS, np.float32), "valid")) + 1.0
                at = lo + int(np.argmax(c / e))
            self.ola += self.ibuf[at - b:at - b + N] * _WIN
            out.append(self.ola[:HS].copy())
            self.ola = np.concatenate([self.ola[HS:], np.zeros(HS, np.float32)])
            self.last, self.m = at, self.m + 1
            keep = min(int(round(self.m * ha)) - SEEK, at + HS)
            if keep > self.ibase:                   # drop what no piece needs again
                self.ibuf = self.ibuf[keep - self.ibase:]
                self.ibase = keep
        return np.concatenate(out) if out else np.zeros(0, np.float32)

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
    """The chunks of one take with the effect on (as they come, then the tail)."""
    ch = Chain(name)
    for c in chunks:
        yield ch.process(c)
    yield ch.flush()
