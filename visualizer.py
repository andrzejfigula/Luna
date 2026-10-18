"""
visualizer.py — the radio, seen: the face reacts to the music playing.

radio._play hands every decoded 0.1 s chunk to tap(): four 25 ms frames of
16 bands (60 Hz – 12 kHz, bass first), a level per channel and a beat (the
bass jumping over its recent average), each stamped with when it will be
heard (the pipe to pw-play holds a few tenths of a second). gl_face reads
uniforms() every frame and draws it full-size behind the face (pass 4), in
the station kind's colours (set_kind). Styles, settings "radio_vis":
  "wstegi"      — glowing ribbons with sparkles (the default)
  "pierscienie" — rings of sound round her head, a new one on each beat
  "iskry"       — glowing bokeh and sparks rising, flashing on the beat
  "slupki"      — spectrum bars either side, LED segments
  "oscyloskop"  — stereo waves either side, a heart beating in the middle
  "nutki"       — musical notes floating up over a staff of light
  "losowo"      — another of them with each new song
  "off"         — nothing (she still sways with the beat)
Voice: "włącz / wyłącz efekty", "zmień efekt" (the next one), "pokaż
wstęgi / pierścienie / iskry / słupki / oscyloskop / nutki", "efekty
losowo" (commands.handle, before ambience: "fale" is not the sea).
"""

import collections
import os
import random
import re
import threading
import time

import numpy as np

SHOWN = ("wstegi", "pierscienie", "iskry", "slupki", "oscyloskop", "nutki")
STYLES = SHOWN + ("losowo", "off")
NAMES = {"wstegi": "świecące wstęgi", "pierscienie": "pierścienie dźwięku",
         "iskry": "iskry", "slupki": "słupki", "oscyloskop": "fale stereo z serduszkiem",
         "nutki": "nutki", "losowo": "co piosenkę inny efekt", "off": "bez efektów"}
_OLD = {"fala": "wstegi", "wszystko": "wstegi", "oczy": "wstegi"}   # (taken out since)
_MODE = {"wstegi": 1.0, "pierscienie": 2.0, "iskry": 3.0, "slupki": 4.0,
         "oscyloskop": 5.0, "nutki": 6.0}
# colour pairs (main, accent); settings "radio_vis_col": one of them, or "auto"
# (the station kind's at its start, then another with each song)
COLORS = {"pomaranczowe": ((1.0, 0.52, 0.12), (1.0, 0.80, 0.35)),
          "fioletowe": ((0.62, 0.30, 1.0), (0.25, 0.55, 1.0)),
          "neonowe": ((1.0, 0.25, 0.75), (0.20, 0.85, 1.0)),
          "zielone": ((0.20, 1.0, 0.55), (0.15, 0.70, 1.0)),
          "rozowe": ((1.0, 0.45, 0.70), (1.0, 0.85, 0.25)),
          "niebieskie": ((0.20, 0.55, 1.0), (0.65, 0.95, 1.0)),
          "zachod": ((1.0, 0.35, 0.40), (0.60, 0.30, 1.0)),
          "czerwone": ((1.0, 0.28, 0.06), (1.0, 0.62, 0.10)),
          "zlote": ((1.0, 0.76, 0.32), (1.0, 0.93, 0.78))}
COLOR_NAMES = {"pomaranczowe": "pomarańczowe", "fioletowe": "fioletowe", "neonowe": "neonowe",
               "zielone": "zielone", "rozowe": "różowe", "niebieskie": "niebieskie",
               "zachod": "jak zachód słońca", "czerwone": "czerwone", "zlote": "złote"}
_KIND_COLORS = {"calm": "zielone", "jazz": "fioletowe", "classic": "zlote", "rock": "czerwone",
                "electronic": "neonowe", "kids": "rozowe",
                # ambience.py's sleep sounds
                "sea": "niebieskie", "rain": "niebieskie", "fire": "czerwone",
                "forest": "zielone", "noise": "fioletowe"}
PALETTES = {k: COLORS[v] for k, v in _KIND_COLORS.items()}
PALETTES[None] = COLORS["pomaranczowe"]
BANDS = 16
RATE = 44100
HOP = RATE // 40                          # a frame every 25 ms
WIN = 1024
PW_LAG = float(os.environ.get("LUNA_VIS_LAG", "0.12"))   # pw-play's own buffer

_lock = threading.Lock()
_frames = collections.deque(maxlen=64)    # (when heard, bands, left, right, beat)
_ref = np.zeros(BANDS, np.float32)        # each band's usual loudness (dB), slow
_bass = {"avg": 0.0, "last": 0.0}         # the bass's recent average, the last beat
_beats = collections.deque([-99.0] * 4, maxlen=4)   # when the last beats were heard
_last_tap = [0.0]
_cur = {"bands": np.zeros(BANDS, np.float32), "l": 0.0, "r": 0.0,
        "on": 0.0, "t": 0.0}
_style = [None, 0.0]                      # (cached setting, when read)
_kind = [None]
_pal = ["pomaranczowe"]                   # "auto": the colours showing now
_colset = [None]                          # (cached setting "radio_vis_col", read with the style)
_col = [np.array(PALETTES[None][0]), np.array(PALETTES[None][1])]
_rand = [None]                            # "losowo": the one showing now


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
        when = lag + i * HOP / RATE
        beat = False
        if float(np.abs(blk).max()) < 60.0:          # a quiet moment
            bands = np.zeros(BANDS, np.float32)
        else:
            spec = np.abs(np.fft.rfft(blk * _HANN)) ** 2
            p = np.add.reduceat(spec, _EDGES[:-1])[:BANDS] / np.diff(_EDGES)
            db = 10.0 * np.log10(p * _TILT * norm * norm + 1e-9)
            with _lock:
                _ref[:] += (db - _ref) * 0.01                    # ~2.5 s to learn a station
                rel = db - _ref
                bands = np.clip((rel + 6.0) / 20.0, 0.0, 1.0).astype(np.float32)
                bass = float(rel[:3].mean())
                if bass - _bass["avg"] > 3.0 and bass > 0.0 and when - _bass["last"] > 0.25:
                    beat = True
                    _bass["last"] = when
                _bass["avg"] += (bass - _bass["avg"]) * 0.12
        lr = st[s:s + HOP]
        rms = np.sqrt((lr * lr).mean(axis=0)) * norm
        left = float(rms[0])
        right = float(rms[1]) if channels > 1 else left
        out.append((when, bands, left, right, beat))
    with _lock:
        _frames.extend(out)
        _last_tap[0] = now


def reset():
    """The radio stopped: forget what was queued."""
    with _lock:
        _frames.clear()
        _last_tap[0] = 0.0


def _other_colors():
    return random.choice([c for c in COLORS if c != _pal[0]])


def set_kind(kind):
    """A station starts — its kind (radio.CATALOG key, or None): "auto" colours
    are the kind's own, or any (18 Oct: most stations had none — all orange)."""
    _kind[0] = kind if kind in PALETTES else None
    _pal[0] = _KIND_COLORS.get(_kind[0]) or _other_colors()


def new_song(title=None):
    """A new song began (the stream's title): "losowo" picks another style,
    "auto" colours other colours."""
    choices = [s for s in SHOWN if s != _rand[0]]
    _rand[0] = random.choice(choices)
    if title is not None:
        _pal[0] = _other_colors()


def colors():
    """The colours showing: the one set, or with "auto" today's pick."""
    style()
    c = _colset[0]
    return c if c in COLORS else _pal[0]


def style():
    """The style set (a "losowo" setting stays "losowo"; shown() says which)."""
    now = time.time()
    if _style[0] is None or now - _style[1] > 2.0:
        env = os.environ.get("LUNA_RADIO_VIS")
        if env in STYLES:
            _style[0] = env
        else:
            import settings
            s = settings.get("radio_vis", "wstegi")
            s = _OLD.get(s, s)
            _style[0] = s if s in STYLES else "wstegi"
            _colset[0] = settings.get("radio_vis_col", "auto")
        _style[1] = now
    return _style[0]


def shown():
    """The style on the screen now."""
    s = style()
    if s == "losowo":
        if _rand[0] is None:
            new_song()
        return _rand[0]
    return s


def _advance(now):
    """The frame being heard now, smoothed for the eye: quick up, slower down."""
    c = _cur
    dt = min(0.2, max(0.0, now - c["t"])) if c["t"] else 0.03
    c["t"] = now
    target = None
    with _lock:
        while _frames and _frames[0][0] <= now:
            target = _frames.popleft()
            if target[4]:
                _beats.appendleft(target[0])
        live = now - _last_tap[0] < 0.6
    c["on"] += ((1.0 if live else 0.0) - c["on"]) * min(1.0, dt * (3.0 if live else 1.5))
    if target is not None:
        b, lt, rt = target[1], target[2], target[3]
        up = b > c["bands"]
        c["bands"] = np.where(up, c["bands"] + (b - c["bands"]) * min(1.0, dt * 30.0),
                              c["bands"] + (b - c["bands"]) * min(1.0, dt * 9.0))
        for k, v in (("l", lt), ("r", rt)):
            c[k] += (v - c[k]) * min(1.0, dt * (25.0 if v > c[k] else 6.0))
    elif not live:
        c["bands"] *= max(0.0, 1.0 - dt * 4.0)
        c["l"] *= max(0.0, 1.0 - dt * 4.0)
        c["r"] *= max(0.0, 1.0 - dt * 4.0)
    want = COLORS[colors()]
    for i in (0, 1):                      # new colours, over a second
        _col[i] = _col[i] + (np.array(want[i]) - _col[i]) * min(1.0, dt * 3.0)
    return c


def _vu(x):
    """A channel's RMS over the station's usual RMS → 0..1, the way a VU reads."""
    if x <= 1e-4:
        return 0.0
    return float(min(1.0, max(0.0, (20.0 * np.log10(x) + 12.0) / 24.0)))


_RNG = np.random.default_rng(7)
_SPARK = _RNG.random((26, 3))             # each spark's own place, speed, size
_NOTE = _RNG.random((9, 3))


def _sparks(t, b, bt, w, h):
    """26 bokeh rising: (x, y, radius, brightness) each."""
    h1, h2, h3 = _SPARK.T
    i = np.arange(26)
    life = (h2 + t * (0.035 + 0.06 * h3)) % 1.0
    x = h1 * w + 40.0 * np.sin(t * (0.3 + h3) + i)
    y = h * (1.05 - 1.15 * life)
    band = b[i % 16]
    rad = 5.0 + 14.0 * h3 * h3 + 10.0 * band + 6.0 * bt * h1
    fade = np.clip(life / 0.15, 0, 1) * np.clip((1.0 - life) / 0.3, 0, 1)
    br = (0.45 + 1.0 * band + 0.7 * bt) * fade
    return [tuple(map(float, v)) for v in np.stack([x, y, rad, br], 1)]


def _notes(t, b, bt, w, h):
    """9 notes floating up beside her: (x, y, scale, brightness) and (cos,
    sin of the tilt, a beamed pair, colour) each."""
    h1, h2, h3 = _NOTE.T
    i = np.arange(9)
    life = (h2 + t * (0.04 + 0.04 * h3)) % 1.0
    sx = np.where(h1 < 0.5, h1 * 0.60, 0.70 + (h1 - 0.5) * 0.60)
    x = sx * w + 25.0 * np.sin(t * 1.3 + i * 2.0)
    y = h * (1.0 - 1.1 * life) + 30.0
    bn = b[(i * 3) % 16]
    sc = 0.9 + 0.5 * h3 + 0.3 * bn + 0.25 * bt
    ang = 0.25 * np.sin(t * 1.7 + i)
    fade = np.clip(life / 0.12, 0, 1) * np.clip((1.0 - life) / 0.25, 0, 1)
    br = fade * (0.5 + 0.6 * bn)
    a = [tuple(map(float, v)) for v in np.stack([x, y, sc, br], 1)]
    k = [tuple(map(float, v)) for v in np.stack([np.cos(ang), np.sin(ang),
                                                 (h3 > 0.6).astype(float), h2], 1)]
    return a, k


def uniforms(talking=False, night=False, w=800, h=480):
    """For gl_face / gl_vis: the bands, beats, colours, the style and how
    strongly; sparks and notes placed."""
    now = time.time()
    c = _advance(now)
    sty = shown()
    on = c["on"]
    if on < 0.01 or sty == "off":
        return {"uVisK": (0.0, 0.0, 0.0, 0.0)}
    k = on * (0.35 if talking else 1.0) * (0.6 if night else 1.0)
    b = c["bands"]
    lv, rv = _vu(c["l"]), _vu(c["r"])
    mode = _MODE.get(sty, 0.0)
    with _lock:
        ages = tuple(min(99.0, max(0.0, now - t)) for t in _beats)
    t = now % 600.0
    u = {"uVis0": tuple(map(float, b[0:4])), "uVis1": tuple(map(float, b[4:8])),
         "uVis2": tuple(map(float, b[8:12])), "uVis3": tuple(map(float, b[12:16])),
         "uVisK": (mode, k if mode else 0.0, max(lv, rv), t),
         "uVisLR": (lv, rv),
         "uVisBeat": ages,
         "uVisCol": tuple(map(float, _col[0])), "uVisCol2": tuple(map(float, _col[1]))}
    bt = float(np.exp(-ages[0] * 5.0))
    if sty == "iskry":
        u["uPart"] = _sparks(t, b, bt, w, h)
    elif sty == "nutki":
        u["uNote"], u["uNoteK"] = _notes(t, b, bt, w, h)
    return u


def music_energy():
    """0..1, the music's level now (the eyes glow with it a little)."""
    c = _cur
    return c["on"] * max(_vu(c["l"]), _vu(c["r"]))


_WORD = re.compile(r"\befekt|\bwizualiz|\bwizualn")
# (words, style, said alone too while the radio plays — else only with "efekt")
_KINDS = ((re.compile(r"losow|piosenk|na\s+zmian|r[oó][żz]n[eya]"), "losowo", False),
          (re.compile(r"pier[śs]cie|kr[ęe]g|\bk[oó][łl]ka\b"), "pierscienie", True),
          (re.compile(r"wst[ęe]g|\bfal[aęeiy]?\b|\bfalk"), "wstegi", True),
          (re.compile(r"\biskr|\biskier|b[ąa]bel|kropk|bokeh|[śs]wietlik|cz[ąa]stecz"), "iskry", True),
          (re.compile(r"s[łl]up|korektor|equali[sz]er|\bwidmo"), "slupki", True),
          (re.compile(r"oscylo|stereo|serc|serduszk|\bekg\b"), "oscyloskop", False),
          (re.compile(r"\bnut(?:k|y\b|a\b|ek\b)"), "nutki", True))
_VERB = re.compile(r"\b(?:poka[żz]|w[łl][aą]cz|daj|ustaw|zr[oó]b|chc[eę]|wr[oó][ćc])")
_NEXT = re.compile(r"\b(?:zmie[ńn]|inn[ya]|nast[eę]pn[ya])\b")
_OFFW = re.compile(r"\b(?:wy[łl][aą]cz|bez\b|schowaj|zga[śs]|nie\s+chc|wystarczy|koniec)")
_NOT_US = re.compile(r"\bszum|\bmorz|\bdeszcz|\bocean|\blamp")   # sea: ambience; lamp: fun.py
_COLW = re.compile(r"\bkolor(?:y|[óo]w)?\b|\bbarw[yaę]?\b|\bkolorow\w*\s+efekt|\befekt\w*\s+kolorow")
_PALW = ((re.compile(r"pomara[ńn]cz"), "pomaranczowe"), (re.compile(r"fiolet"), "fioletowe"),
         (re.compile(r"\bneon"), "neonowe"), (re.compile(r"zielon"), "zielone"),
         (re.compile(r"r[oó][żz]ow"), "rozowe"), (re.compile(r"niebiesk"), "niebieskie"),
         (re.compile(r"zach[oó]d"), "zachod"), (re.compile(r"czerwon"), "czerwone"),
         (re.compile(r"z[łl]ot"), "zlote"))
_AUTOW = re.compile(r"losow|piosenk|automat|same|sam[eio]\b|r[oó][żz]n|zmienn")


def _colour(low, settings):
    """'zmień kolory' (the next, kept), 'fioletowe efekty', 'kolory losowo'
    (another with each song) → what to say."""
    pal = next((k for rx, k in _PALW if rx.search(low)), None)
    if pal:
        new = pal
    elif _AUTOW.search(low):
        new = "auto"
    else:
        names = list(COLORS)
        new = names[(names.index(colors()) + 1) % len(names)]
    settings.put("radio_vis_col", new)
    _style[0] = None
    if new != "auto":
        _pal[0] = new
    print(f"[vis] colours: {new}", flush=True)
    if new == "auto":
        return "Dobrze, kolory będą się zmieniać z każdą piosenką."
    return f"Dobrze — kolory {COLOR_NAMES[new]}."


def handle(low, speak, radio_on=True):
    """'włącz / wyłącz efekty', 'zmień efekt', 'pokaż wstęgi / iskry / nutki…',
    'efekty losowo', 'zmień kolory', 'fioletowe efekty' — True when handled.
    Without the word "efekt" / "wizualizacja" only while the radio plays, and
    only the plain names."""
    import settings
    if _NOT_US.search(low):
        return False
    word = bool(_WORD.search(low))
    found = next(((k, strong) for rx, k, strong in _KINDS if rx.search(low)), None)
    named = found[0] if found and (word or found[1]) else None
    pal = any(rx.search(low) for rx, _ in _PALW)
    asked = word or _VERB.search(low) or _NEXT.search(low) or pal or _AUTOW.search(low)
    if ((_COLW.search(low) and asked) or (pal and (word or named))) and (word or radio_on):
        said = _colour(low, settings)
        if named and named != "losowo":               # "fioletowe iskry"
            settings.put("radio_vis", named)
            settings.put("radio_vis_last", named)
            _style[0] = None
        speak(said)
        return True
    if not word and not (radio_on and named and (_VERB.search(low) or _OFFW.search(low))):
        return False
    cur = style()
    if _OFFW.search(low):
        new = "off"
    elif named:
        new = named
    elif _NEXT.search(low):
        now = shown() if cur != "off" else SHOWN[-1]
        new = SHOWN[(SHOWN.index(now) + 1) % len(SHOWN)] if now in SHOWN else SHOWN[0]
    elif cur == "off":
        last = _OLD.get(settings.get("radio_vis_last", "wstegi"), settings.get("radio_vis_last", "wstegi"))
        new = last if last in STYLES and last != "off" else "wstegi"
    else:
        speak(f"Efekty są włączone — teraz {NAMES[shown()]}. Powiedz „zmień efekt”, "
              "a pokażę inny.")
        return True
    settings.put("radio_vis", new)
    if new != "off":
        settings.put("radio_vis_last", new)
    if new == "losowo":
        new_song()
    _style[0] = None
    print(f"[vis] style: {new}", flush=True)
    if new == "off":
        speak("Dobrze, bez efektów. Powiedz „włącz efekty”, gdy zechcesz je z powrotem.")
    else:
        speak(f"Dobrze — {NAMES[new]}." + ("" if radio_on else " Zobaczysz, gdy włączysz radio."))
    return True
