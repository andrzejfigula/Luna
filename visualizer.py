"""
visualizer.py — the radio, seen: the face reacts to the music playing.

radio._play hands every decoded 0.1 s chunk to tap(): four 25 ms frames of
16 bands (60 Hz – 12 kHz, bass first) and a level per channel, each stamped
with when it will be heard (the pipe to pw-play holds a few tenths of a
second). gl_face reads uniforms() every frame and draws, by settings
"radio_vis":
  "fala"    — glowing waves behind the face (the default)
  "slupki"  — a soft spectrum, mirrored from the middle, along the bottom
  "oczy"    — a VU meter in her eyes (left / right channel), nothing behind
  "wszystko"— the waves and the eyes
  "off"     — nothing (she still sways with the beat)
Voice: "włącz / wyłącz efekty", "zmień efekt" (the next one), "pokaż
falę / słupki / wskaźnik w oczach" (commands.handle, before ambience: "fale"
is not the sea).
"""

import collections
import os
import re
import threading
import time

import numpy as np

STYLES = ("fala", "slupki", "oczy", "wszystko", "off")
NAMES = {"fala": "fala", "slupki": "słupki", "oczy": "wskaźnik w oczach",
         "wszystko": "fala i oczy", "off": "bez efektów"}
BANDS = 16
RATE = 44100
HOP = RATE // 40                          # a frame every 25 ms
WIN = 1024
PW_LAG = float(os.environ.get("LUNA_VIS_LAG", "0.12"))   # pw-play's own buffer

_lock = threading.Lock()
_frames = collections.deque(maxlen=64)    # (when heard, bands, left, right)
_ref = np.zeros(BANDS, np.float32)        # each band's usual loudness (dB), slow
_last_tap = [0.0]
_cur = {"bands": np.zeros(BANDS, np.float32), "l": 0.0, "r": 0.0,
        "on": 0.0, "t": 0.0}
_style = [None, 0.0]                      # (cached setting, when read)


def _edges():
    f = np.geomspace(60.0, 12000.0, BANDS + 1)
    e = np.round(f * WIN / RATE).astype(int)
    for i in range(1, len(e)):            # at least one FFT bin per band
        e[i] = max(e[i], e[i - 1] + 1)
    return e


_EDGES = _edges()
_TILT = np.geomspace(60.0, 12000.0, BANDS) / 1000.0   # +3 dB/octave: treble shows too
_HANN = np.hanning(WIN).astype(np.float32)


def _pipe_lag(fd):
    """Seconds of audio waiting in the pipe to pw-play (Linux), else a guess."""
    try:
        import fcntl
        import termios
        n = np.zeros(1, np.int32)
        fcntl.ioctl(fd, termios.FIONREAD, n, True)
        return int(n[0]) / (RATE * 4.0)
    except Exception:
        return 0.35


def tap(a, level, fd=None, channels=2):
    """A decoded chunk (float32, interleaved s16 values) before it is written.
    level: the station's usual RMS (radio's loudness levelling)."""
    if a.size < WIN * channels:
        return
    now = time.time()
    st = a.reshape(-1, channels)
    lag = now + (_pipe_lag(fd) if fd is not None else 0.35) + PW_LAG
    mono = st.mean(axis=1)
    norm = 1.0 / max(level, 1.0)
    out = []
    for i, s in enumerate(range(0, len(mono) - WIN + 1, HOP)):
        blk = mono[s:s + WIN]
        if float(np.abs(blk).max()) < 60.0:          # a quiet moment
            bands = np.zeros(BANDS, np.float32)
        else:
            spec = np.abs(np.fft.rfft(blk * _HANN)) ** 2
            p = np.add.reduceat(spec, _EDGES[:-1])[:BANDS] / np.diff(_EDGES)
            db = 10.0 * np.log10(p * _TILT * norm * norm + 1e-9)
            with _lock:
                _ref[:] += (db - _ref) * 0.01                    # ~2.5 s to learn a station
                bands = np.clip((db - _ref + 6.0) / 20.0, 0.0, 1.0).astype(np.float32)
        lr = st[s:s + HOP]
        rms = np.sqrt((lr * lr).mean(axis=0)) * norm
        left = float(rms[0])
        right = float(rms[1]) if channels > 1 else left
        out.append((lag + i * HOP / RATE, bands, left, right))
    with _lock:
        _frames.extend(out)
        _last_tap[0] = now


def reset():
    """The radio stopped: forget what was queued."""
    with _lock:
        _frames.clear()
        _last_tap[0] = 0.0


def style():
    now = time.time()
    if _style[0] is None or now - _style[1] > 2.0:
        env = os.environ.get("LUNA_RADIO_VIS")
        if env in STYLES:
            _style[0] = env
        else:
            import settings
            s = settings.get("radio_vis", "fala")
            _style[0] = s if s in STYLES else "fala"
        _style[1] = now
    return _style[0]


def _advance(now):
    """The frame being heard now, smoothed for the eye: quick up, slower down."""
    c = _cur
    dt = min(0.2, max(0.0, now - c["t"])) if c["t"] else 0.03
    c["t"] = now
    target = None
    with _lock:
        while _frames and _frames[0][0] <= now:
            target = _frames.popleft()
        live = now - _last_tap[0] < 0.6
    c["on"] += ((1.0 if live else 0.0) - c["on"]) * min(1.0, dt * (3.0 if live else 1.5))
    if target is not None:
        _, b, lt, rt = target
        up = b > c["bands"]
        c["bands"] = np.where(up, c["bands"] + (b - c["bands"]) * min(1.0, dt * 30.0),
                              c["bands"] + (b - c["bands"]) * min(1.0, dt * 9.0))
        for k, v in (("l", lt), ("r", rt)):
            c[k] += (v - c[k]) * min(1.0, dt * (25.0 if v > c[k] else 6.0))
    elif not live:
        c["bands"] *= max(0.0, 1.0 - dt * 4.0)
        c["l"] *= max(0.0, 1.0 - dt * 4.0)
        c["r"] *= max(0.0, 1.0 - dt * 4.0)
    return c


def _vu(x):
    """A channel's RMS over the station's usual RMS → 0..1, the way a VU reads."""
    if x <= 1e-4:
        return 0.0
    return float(min(1.0, max(0.0, (20.0 * np.log10(x) + 12.0) / 24.0)))


def uniforms(talking=False, night=False):
    """For gl_face: the bands, the style and how strongly to show it."""
    now = time.time()
    c = _advance(now)
    sty = style()
    on = c["on"]
    if on < 0.01 or sty == "off":
        return {"uVisK": (0.0, 0.0, 0.0, 0.0), "uVisEye": (0.0, 0.0, 0.0)}
    k = on * (0.35 if talking else 1.0) * (0.6 if night else 1.0)
    b = c["bands"]
    lv, rv = _vu(c["l"]), _vu(c["r"])
    mode = {"fala": 1.0, "wszystko": 1.0, "slupki": 2.0}.get(sty, 0.0)
    eyes = k if sty in ("oczy", "wszystko") else 0.0
    return {"uVis0": tuple(b[0:4]), "uVis1": tuple(b[4:8]),
            "uVis2": tuple(b[8:12]), "uVis3": tuple(b[12:16]),
            "uVisK": (mode, k if mode else 0.0, max(lv, rv), now % 600.0),
            "uVisEye": (lv, rv, eyes)}


def music_energy():
    """0..1, the music's level now (the eyes glow with it a little)."""
    c = _cur
    return c["on"] * max(_vu(c["l"]), _vu(c["r"]))


_WORD = re.compile(r"\befekt|\bwizualiz|\bwizualn")
_KINDS = ((re.compile(r"\bfal[aęeiy]?\b|\bfalk"), "fala"),
          (re.compile(r"s[łl]up|korektor|equali[sz]er|\bwidmo"), "slupki"),
          (re.compile(r"\boczach\b|\boczy\b|wska[źz]nik|\bvu\b"), "oczy"))
_VERB = re.compile(r"\b(?:poka[żz]|w[łl][aą]cz|daj|ustaw|zr[oó]b|chc[eę]|wr[oó][ćc])")
_NEXT = re.compile(r"\b(?:zmie[ńn]|inn[ya]|nast[eę]pn[ya])\b")
_OFFW = re.compile(r"\b(?:wy[łl][aą]cz|bez\b|schowaj|zga[śs]|nie\s+chc|wystarczy|koniec)")
_NOT_US = re.compile(r"\bszum|\bmorz|\bdeszcz|\bocean")      # sea waves: ambience.py


def handle(low, speak, radio_on=True):
    """'włącz / wyłącz efekty', 'zmień efekt', 'pokaż falę / słupki /
    wskaźnik w oczach' — True when handled. Without the word "efekt" /
    "wizualizacja" only while the radio plays."""
    import settings
    if _NOT_US.search(low):
        return False
    word = bool(_WORD.search(low))
    named = next((k for rx, k in _KINDS if rx.search(low)), None)
    if not word and not (radio_on and named and (_VERB.search(low) or _OFFW.search(low))):
        return False
    cur = style()
    if _OFFW.search(low):
        new = "off"
    elif named:
        new = named
    elif _NEXT.search(low):
        new = STYLES[(STYLES.index(cur) + 1) % len(STYLES)]
    elif cur == "off":
        last = settings.get("radio_vis_last", "fala")
        new = last if last in STYLES and last != "off" else "fala"
    else:
        speak(f"Efekty są włączone — teraz {NAMES[cur]}. Powiedz „zmień efekt”, "
              "a pokażę inny.")
        return True
    settings.put("radio_vis", new)
    if new != "off":
        settings.put("radio_vis_last", new)
    _style[0] = None
    print(f"[vis] style: {new}", flush=True)
    if new == "off":
        speak("Dobrze, bez efektów. Powiedz „włącz efekty”, gdy zechcesz je z powrotem.")
    else:
        speak(f"Dobrze — {NAMES[new]}." + ("" if radio_on else " Zobaczysz, gdy włączysz radio."))
    return True
