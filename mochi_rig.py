"""
mochi_rig.py — Mochi's body language: the plush bunny's ears, paws, eye
glyphs, mouths and little symbols (gl_chars.py draws them).

One expression at a time, picked from what the app is doing — asleep, the
reply scene playing, robot_face's gesture (a wave, a thumbs up, the heart),
a CharLife gesture (curious, confused), her mood, listening — and a look for
each in LOOKS: how far each ear leans out and how far its tip flops over,
where the paws go, a glyph for the eyes (◠ happy, > < laughing, — asleep, a
flat top when pouting), a mouth, a head tilt, and the symbols that pop once
when it starts (a heart, a "?", sparkles) — not a stream of them — and
how big her iris and pupil are and where they look.

Each part moves on its own clock: the ears on a loose spring that lags the
head (follow-through: a nod flops them), the paws on a firmer one with a
small dip before they rise (anticipation), the glyphs and the mouth cross-
fade (one fades out before the next fades in). robot_face's own hands (a
wave, a clap, rock-paper-scissors, a paw on the chin) take the paws over as
they rise and give them back as they sink. "Spokojne" effects: half the
sway, springs that don't overshoot; "wyłączone": none at all.

Her eyes hop on their own: a new spot every 0.6–2.4 s, now and then a
glance aside and back; with someone there, between their eyes and mouth;
darting when excited, still asleep. Her pupils breathe and open at a new look.

Pure Python, no pygame or GL; deterministic on a fake clock (the tests).
"""

import math
import random

# the shader's numbers for the eye glyphs and the mouths
EYE_GLYPHS = {None: 0, "arc": 1, "squeeze": 2, "line": 3, "half": 4, "heart": 5}
MOUTHS = {None: 0, "smile": 1, "open": 2, "o": 3, "pout": 4, "tongue": 5,
          "flat": 6, "frown": 7, "tiny": 8}

# where the right paw goes (x, y from the face's centre, turn in rad: +
# its top leans out; size px); the left one mirrored. Paws only, no arms
# (an arm sliding up from the screen's edge looked wrong)
PAWS = {
    "rest": (164.0, 156.0, 0.16, 102.0),
    "low": (80.0, 160.0, -0.10, 100.0),
    "cheeks": (126.0, 150.0, -0.36, 110.0),
    "up": (236.0, 112.0, 0.30, 112.0),
    "startle": (188.0, 132.0, 0.08, 108.0),
}
PAW_BOTTOM = 0.47       # a paw's lowest point below its centre (× its size)

# robot_face's hand poses → the paw's: 1 open (pads to you), 4 curled (the
# back of the paw, toes tucked), 6 two round toes up (scissors). A thumb,
# an OK ring or a pointing finger aren't a bunny's: an open paw or a curl.
POSES = {"open": 1, "paper": 1, "hourglass": 1, "thumb": 1, "ok": 1,
         "thumb_down": 4, "fist": 4, "point": 4, "scissors": 6}

# ears: (lean L, lean R, flop L, flop R) — lean out in rad, flop 0..1; iris:
# (the iris's size, the pupil's) × 1; look: where the iris looks in the eye
# (× its radius, + down)
LOOKS = {
    "neutral": {"ears": (0.16, 0.16, 0.0, 0.0), "mouth": ("smile", 18.0)},
    "listening": {"ears": (-0.03, -0.03, 0.0, 0.0), "mouth": ("smile", 16.0), "pods": 1.0,
                  "iris": (1.0, 1.06)},
    "happy": {"ears": (0.07, 0.07, 0.0, 0.0), "eyes": "arc", "hold": 2.4,
              "mouth": ("open", 24.0), "blush": 0.35},
    "excited": {"ears": (-0.04, -0.04, 0.0, 0.0), "paws": "up", "mouth": ("open", 30.0),
                "sparkle": 1.0, "blush": 0.4, "iris": (1.08, 1.06),
                "pops": ((4, -250.0, -104.0, 24.0, 0.0), (4, 262.0, -52.0, 17.0, 0.14),
                         (4, 214.0, -164.0, 13.0, 0.28))},
    "laugh": {"ears": (0.02, 0.02, 0.0, 0.0), "paws": "up", "eyes": "squeeze",
              "mouth": ("open", 32.0), "blush": 0.5,
              "pops": ((4, -250.0, -104.0, 22.0, 0.05), (4, 258.0, -60.0, 16.0, 0.2))},
    "success": {"ears": (-0.02, -0.02, 0.0, 0.0), "eyes": "arc", "hold": 1.8,
                "mouth": ("open", 26.0),
                "pops": ((3, 250.0, -132.0, 30.0, 0.12), (4, 302.0, -78.0, 15.0, 0.32))},
    "greeting": {"ears": (-0.05, -0.05, 0.0, 0.0), "eyes": "arc", "hold": 1.6,
                 "mouth": ("open", 24.0)},
    "curious": {"ears": (-0.02, 0.36, 0.0, 0.18), "scale": (1.12, 0.9), "tilt": 0.05,
                "iris": (1.04, 1.12), "look": (0.10, -0.08),
                "mouth": ("o", 9.0), "pops": ((2, 266.0, -112.0, 34.0, 0.18),)},
    "confused": {"ears": (0.14, 0.5, 0.0, 0.62), "scale": (1.0, 0.82), "tilt": -0.06,
                 "mouth": ("flat", 14.0), "pops": ((2, 266.0, -112.0, 36.0, 0.12),)},
    "thinking": {"ears": (0.3, 0.3, 0.12, 0.12), "mouth": ("flat", 13.0), "look": (0.10, -0.14)},
    "sleepy": {"ears": (0.45, 0.45, 0.6, 0.6), "eyes": "line", "mouth": ("tiny", 11.0),
               "pods": 0.0, "paws": "rest", "iris": (1.0, 0.92)},
    "shy": {"ears": (0.38, 0.38, 0.12, 0.12), "paws": "cheeks", "gaze": (-18.0, 14.0),
            "look": (-0.12, 0.10),
            "tilt": 0.05, "mouth": ("smile", 14.0), "blush": 1.0},
    "affection": {"ears": (0.1, 0.1, 0.0, 0.0), "paws": "cheeks", "mouth": ("smile", 20.0),
                  "blush": 1.0, "iris": (1.0, 1.1),
                  "pops": ((1, -262.0, -40.0, 28.0, 0.2), (1, 270.0, 6.0, 19.0, 0.55))},
    "hearts": {"ears": (0.06, 0.06, 0.0, 0.0), "paws": "cheeks", "eyes": "heart",
               "mouth": ("open", 22.0), "blush": 1.0,
               "pops": ((1, -262.0, -40.0, 26.0, 0.1), (1, 270.0, 6.0, 18.0, 0.4),
                        (1, 236.0, -150.0, 14.0, 0.75))},
    "surprised": {"ears": (-0.08, -0.08, 0.0, 0.0), "paws": "startle", "mouth": ("o", 15.0),
                  "scale": (1.06, 1.06), "iris": (1.04, 1.12),
                  "pops": ((7, -262.0, -96.0, 34.0, 0.0),)},
    "sad": {"ears": (0.72, 0.72, 0.45, 0.45), "paws": "low", "mouth": ("frown", 16.0),
            "iris": (1.02, 1.08)},
    "playful": {"ears": (0.02, 0.34, 0.0, 0.0), "tilt": -0.04, "mouth": ("tongue", 20.0),
                "pops": ((4, 214.0, -86.0, 15.0, 0.25),)},
    "pout": {"ears": (0.55, 0.55, 0.22, 0.22), "eyes": "half", "mouth": ("pout", 13.0),
             "puff": 1.0, "blush": 0.7, "look": (0.0, 0.10)},
    "disagree": {"ears": (0.42, 0.42, 0.1, 0.1), "eyes": "half", "mouth": ("pout", 13.0),
                 "puff": 0.6},
}

# what picks the look: a reply scene, robot_face's gesture, her mood
SCENE_LOOK = {
    "laugh": "laugh", "dance": "excited", "clap": "excited", "sparkle_eyes": "excited",
    "proud": "success", "lightbulb": "success", "ok_sign": "success", "salute": "success",
    "snap": "success", "wave_both": "greeting", "music_notes": "happy", "relief": "happy",
    "sunny": "happy", "slow_blink": "happy",
    "shy": "shy", "please": "shy", "flutter": "affection", "heart_eyes": "hearts",
    "air_heart": "affection",
    "smirk": "playful", "wink": "playful", "cross_eyes": "playful",
    "curious": "curious", "suspicious": "curious", "big_pupils": "curious",
    "scratch_head": "confused", "dizzy": "confused",
    "think_bubble": "thinking", "chin_rest": "thinking", "remember": "thinking",
    "thumbs_down": "disagree", "impatient": "disagree", "eye_roll": "disagree",
    "scared": "surprised", "lost_signal": "surprised",
    "sigh": "sad", "tear_wipe": "sad", "rainy": "sad",
}
GESTURE_LOOK = {"wave": "greeting", "thumbs_up": "success", "heart": "affection",
                "shake": "disagree"}
MOOD_LOOK = {"happy": "happy", "excited": "excited", "love": "affection", "sad": "sad",
             "angry": "pout", "surprised": "surprised", "thinking": "thinking",
             "sleeping": "sleepy"}


# CharLife's gestures (characters.GESTURES) that bring their own look
GESTURE_OWN = (("confused", "confused"), ("curious", "curious"), ("alert", "surprised"),
               ("celebrate", "excited"), ("think", "thinking"))


def pick(face, ch, gestures=()):
    """The look for now (a LOOKS key); gestures: CharLife's running."""
    emo = getattr(face, "_emotion", "neutral")
    if emo == "sleeping":
        return "sleepy"
    scene = getattr(face, "_scene_name", None)
    if scene in SCENE_LOOK:
        return SCENE_LOOK[scene]
    gest = getattr(face, "_gesture", None)
    if gest in GESTURE_LOOK:
        return GESTURE_LOOK[gest]
    for name, look in GESTURE_OWN:
        if name in gestures:
            return look
    if emo in MOOD_LOOK:
        return MOOD_LOOK[emo]
    if getattr(face, "_listen", False) and not getattr(face, "_speaking", False):
        return "listening"
    return "neutral"


def hand_at(hx, hy):
    """robot_face's hand (Luna's face: eyes at ±158, -30, the mouth at 120,
    the chin 196) → where Mochi's paw goes (her eyes at ±100, 38, the mouth
    at 96, the top of her head -80): inside the face it shrinks to hers,
    beside it it stays beside it."""
    ax = abs(hx)
    x = ax * 0.64 if ax < 158.0 else 101.0 + (ax - 158.0) * 1.45
    y = 38.0 + (hy + 30.0) * (0.42 if hy > -30.0 else 0.85)
    return math.copysign(min(x, 316.0), hx), max(-96.0, min(250.0, y))


class _Spring:
    """A value on a damped spring; zeta < 1 overshoots."""
    __slots__ = ("x", "v")

    def __init__(self, x):
        self.x, self.v = x, 0.0

    def step(self, target, k, zeta, dt):
        c = 2.0 * math.sqrt(k) * zeta
        n = max(1, int(math.ceil(dt / 0.008)))
        h = dt / n
        for _ in range(n):
            self.v += ((target - self.x) * k - self.v * c) * h
            self.x += self.v * h
        return self.x


class _Fade:
    """A glyph or a mouth: cross-fades — the old one out before the new one in."""
    __slots__ = ("kind", "amt")

    def __init__(self):
        self.kind, self.amt = None, 0.0

    def step(self, kind, want, dt, rate=9.0):
        k = 1.0 - math.exp(-rate * dt)
        if kind != self.kind and self.amt > 0.02:
            self.amt += (0.0 - self.amt) * min(1.0, k * 1.6)
            return
        if kind != self.kind:
            self.kind = kind
        self.amt += ((want if kind else 0.0) - self.amt) * k


def _ease_back(x):
    """0 → 1 with a little overshoot (a pop)."""
    x = max(0.0, min(1.0, x))
    s = 1.9
    x -= 1.0
    return 1.0 + x * x * ((s + 1.0) * x + s)


class MochiRig:
    """Mochi's parts, frame by frame. step() → the shader's numbers."""

    def __init__(self, now):
        self.look, self.look_t = None, now
        self.ears = [_Spring(v) for v in LOOKS["neutral"]["ears"]]
        self.tilt = _Spring(0.0)
        self.squash = _Spring(0.0)
        self.paw = {}
        for s in (-1.0, 1.0):
            x, y, turn, size = PAWS["rest"]
            self.paw[s] = {"x": _Spring(s * x), "y": _Spring(y), "turn": _Spring(s * turn),
                           "place": "rest", "dip": -9.0, "from_y": y}
        self.eye = [_Fade(), _Fade()]
        self.mouth = _Fade()
        self.pops = []                       # (kind, t0, dur, x, y, size)
        self.head = None                     # where the head was, its velocity
        self.hv = [0.0, 0.0]
        self.vals = {"pods": 0.15, "blush": 0.0, "puff": 0.0, "sparkle": 0.0,
                     "s0": 1.0, "s1": 1.0, "gx": 0.0, "gy": 0.0, "msize": 18.0,
                     "is": 1.0, "ps": 1.0, "lx": 0.0, "ly": 0.0}
        self.rng = random.Random(7)          # (the same hops every run: the tests)
        self.fix, self.fix_home, self.fix_back = (0.0, 0.0), (0.0, 0.0), False
        self.fix_t = now + 0.8
        self.fix_sp = (_Spring(0.0), _Spring(0.0))
        self.dil_t = -1e9                    # a new look: her pupils open

    # ── the parts ──
    def _start(self, look, now):
        if self.look is not None:
            self.dil_t = now
        self.look, self.look_t = look, now
        # the last look's symbols fade out now, not over the new one's
        self.pops = [(k, t0, min(dur, max(now - t0, 0.0) + 0.3) if t0 <= now else 0.0, x, y, s)
                     for k, t0, dur, x, y, s in self.pops]
        for kind, x, y, size, delay in LOOKS[look].get("pops", ()):
            self.pops.append((kind, now + delay, 2.0 if kind in (1, 2) else 1.4, x, y, size))
        self.pops = self.pops[-6:]

    def _hops(self, look, seen, now, dt, lvl):
        """Where her eyes rest now (× the eye's radius, + down), on a stiff
        spring with a hair of overshoot: a saccade, not a slide."""
        if look == "sleepy":
            tgt = (0.0, 0.0)
        else:
            if now >= self.fix_t:
                r = self.rng
                if self.fix_back:                     # back from a glance
                    self.fix, self.fix_back = self.fix_home, False
                    gap = r.uniform(0.5, 1.6)
                elif seen:                            # someone there: their eyes, their mouth
                    self.fix = r.choice(((-0.08, -0.02), (0.08, -0.02), (0.0, 0.09), (0.0, 0.0)))
                    gap = r.uniform(0.4, 1.4)
                elif r.random() < 0.2:                # a glance aside, and back
                    self.fix_home, self.fix_back = self.fix, True
                    self.fix = (r.choice((-1.0, 1.0)) * r.uniform(0.3, 0.42), r.uniform(-0.2, 0.12))
                    gap = r.uniform(0.5, 1.0)
                else:
                    self.fix = (r.uniform(-0.2, 0.2), r.uniform(-0.13, 0.11))
                    gap = r.uniform(0.6, 2.4)
                if look == "excited":                 # darting
                    gap *= 0.35
                elif look in ("sad", "thinking"):     # slow, lost in it
                    gap *= 1.7
                self.fix_t = now + gap
            amp = 0.5 + 0.5 * lvl
            tgt = (self.fix[0] * amp, self.fix[1] * amp)
        return tuple(sp.step(t, 900.0, 0.7, dt) for sp, t in zip(self.fix_sp, tgt))

    def _ears(self, L, ch, dt, lvl, head):
        if self.head is None:
            self.head = head
        vx = (head[0] - self.head[0]) / max(dt, 1e-3)
        vy = (head[1] - self.head[1]) / max(dt, 1e-3)
        self.head = head
        kk = 1.0 - math.exp(-14.0 * dt)               # (a frame's jitter smoothed out)
        self.hv[0] += (max(-700.0, min(700.0, vx)) - self.hv[0]) * kk
        self.hv[1] += (max(-700.0, min(700.0, vy)) - self.hv[1]) * kk
        lean_l, lean_r, flop_l, flop_r = L["ears"]
        lag = 0.00055 * lvl
        swing = self.hv[0] * lag                      # the tips trail the head
        lift = self.hv[1] * lag                       # going up: they flop; down: they lift
        mic = ch.get("mic", 0.0) * ch.get("listen", 0.0)
        tgt = (lean_l + swing - 0.05 * mic, lean_r - swing - 0.05 * mic,
               max(0.0, flop_l - lift), max(0.0, flop_r - lift))
        zeta = 1.0 - 0.58 * lvl                       # loose, a little overshoot
        return [sp.step(t, 110.0, zeta, dt) for sp, t in zip(self.ears, tgt)]

    def _paws(self, L, face, now, dt, lvl, floor):
        """Two paws: the look's place on a spring, robot_face's hand over it
        as it rises; never below `floor` (the dock's icons). → [(x, y,
        turn, pose, size)] left, right."""
        hands = getattr(face, "hand", None) or {}
        poses = getattr(face, "hand_pose", None) or {}
        place = L.get("paws", "rest")
        own = getattr(face, "_gesture", None) == "heart"   # paws to her cheeks, not Luna's heart
        out = []
        for s, side in ((-1.0, "L"), (1.0, "R")):
            p = self.paw[s]
            x, y, turn, size = PAWS[place]
            if place != p["place"]:
                if y < p["y"].x - 30.0:               # rising: a little dip first
                    p["dip"], p["from_y"] = now, p["y"].x
                p["place"] = place
            ty = y
            if now - p["dip"] < 0.14 * (lvl > 0.0):
                ty = p["from_y"] + 14.0
            zeta = 1.0 - 0.36 * lvl
            ox = p["x"].step(s * x, 95.0, zeta, dt)
            oy = p["y"].step(ty, 95.0, zeta, dt)
            ot = p["turn"].step(s * turn, 95.0, zeta, dt)
            pose = 1
            h = hands.get(side)
            if h and h[1] < 330.0 and not own:        # robot_face's hand rising: it takes over
                k = min(1.0, (330.0 - h[1]) / 110.0)
                k = k * k * (3.0 - 2.0 * k)
                hx, hy = hand_at(h[0], h[1])
                ox, oy = ox + (hx - ox) * k, oy + (hy - oy) * k
                ot += (-math.radians(h[2]) - ot) * k  # (its angle: the other way round)
                size += (114.0 - size) * k
                if k > 0.5:
                    pose = POSES.get(poses.get(side), 1)
            oy = min(oy, floor - PAW_BOTTOM * size)
            out.append((ox, oy, ot, pose, size))
        return out

    def step(self, face, ch, now, dt, lvl=1.0, closed=(0.0, 0.0), head=(0.0, 0.0), gestures=(),
             floor=1e9):
        """This frame's parts. ch: CharLife's channels; closed: how shut each
        eye's lids are (a wink); head: where the head is (px); gestures:
        CharLife's running; floor: no paw lower than this (from the face's
        centre: the dock's icons wherever her head is)."""
        dt = max(0.0, min(dt, 0.25))
        look = pick(face, ch, gestures)
        if look != self.look:
            self._start(look, now)
        L = LOOKS[look]
        el = now - self.look_t
        talking = bool(getattr(face, "_speaking", False))
        ears = self._ears(L, ch, dt, lvl, head)
        paws = self._paws(L, face, now, dt, lvl, floor)
        tilt = self.tilt.step(L.get("tilt", 0.0) * max(0.3, lvl), 60.0, 0.9, dt)
        # plush: pressed down as the head drops, stretched as it rises, a jiggle after
        squash = self.squash.step(max(-0.025, min(0.035, self.hv[1] * 0.0003 * lvl)), 160.0,
                                  1.0 - 0.5 * lvl, dt)
        # the eyes: the look's glyph (a smile's ◠ only at first), a wink's > <
        glyph = L.get("eyes")
        if glyph and el > L.get("hold", 1e9):
            glyph = None
        if talking and glyph in ("arc", "half"):     # talking: her eyes open
            glyph = None
        for i in (0, 1):
            g, want, rate = glyph, 1.0, 9.0
            if closed[i] > 0.55 and closed[1 - i] < 0.25 and look != "sleepy":
                g, rate = "squeeze", 20.0             # a wink: one eye a chevron
            self.eye[i].step(g, want, dt, rate)
        # the mouth: the look's own; talking, the voice's shapes
        mk, msize = L.get("mouth", (None, 0.0))
        self.mouth.step(None if talking else mk, 1.0, dt, 20.0 if talking else 10.0)
        v, k = self.vals, 1.0 - math.exp(-6.0 * dt)
        mic = ch.get("mic", 0.0) * ch.get("listen", 0.0)
        tgt = {"pods": 0.05 if look == "sleepy" else 0.32 + 0.68 * mic if L.get("pods") else
               0.4 if talking else 0.15,
               "blush": L.get("blush", 0.0), "puff": L.get("puff", 0.0),
               "sparkle": L.get("sparkle", 0.0),
               "s0": L.get("scale", (1.0, 1.0))[0], "s1": L.get("scale", (1.0, 1.0))[1],
               "gx": L.get("gaze", (0.0, 0.0))[0], "gy": L.get("gaze", (0.0, 0.0))[1],
               "msize": msize if mk else v["msize"],
               "is": L.get("iris", (1.0, 1.0))[0], "ps": L.get("iris", (1.0, 1.0))[1],
               "lx": L.get("look", (0.0, 0.0))[0], "ly": L.get("look", (0.0, 0.0))[1]}
        for key, t in tgt.items():
            v[key] += (t - v[key]) * k
        hx, hy = self._hops(look, bool(getattr(face, "_face_seen", False)) or talking, now, dt, lvl)
        dil = (1.0 + 0.035 * math.sin(now * 0.9)) * (1.0 + 0.14 * math.exp(-(now - self.dil_t) / 0.5))
        pops = []
        for kind, t0, dur, x, y, size in self.pops:
            el = now - t0
            if el < 0.0 or el >= dur - 1e-3:
                continue
            fade = min(1.0, (dur - el) / 0.3)
            rise = (20.0 if kind == 1 else 11.0) * el * max(0.3, lvl)   # px/s: hearts float up
            sc = _ease_back(el / 0.32) if lvl > 0.0 else 1.0
            pops.append((x, y - rise, size * sc, kind + 0.98 * fade * min(1.0, el / 0.12)))
        self.pops = [p for p in self.pops if now - p[1] < p[2]]
        return {
            "look": look, "ears": ears, "paws": paws, "tilt": tilt, "squash": squash,
            "eyes": (EYE_GLYPHS[self.eye[0].kind], self.eye[0].amt,
                     EYE_GLYPHS[self.eye[1].kind], self.eye[1].amt),
            "mouth": (MOUTHS[self.mouth.kind], self.mouth.amt, v["msize"]),
            "pods": v["pods"], "blush": v["blush"], "puff": v["puff"], "sparkle": v["sparkle"],
            "scale": (v["s0"], v["s1"]), "gaze": (v["gx"], v["gy"]), "pops": pops[:4],
            "iris": (v["is"], v["ps"] * dil, v["lx"] + hx, v["ly"] + hy),
        }
