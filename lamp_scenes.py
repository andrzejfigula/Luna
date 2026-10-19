"""
lamp_scenes.py — the night lamp as a living picture instead of plain light
("lampka meduzy", "lampka lawa"…; fun.py takes the words). gl_lamp.py draws
them on the GPU; this file moves what moves (the jellyfish, the fireflies,
the wax) and draws the clock's digits with pygame, over the ring.

  meduzy     — a few bioluminescent jellyfish drifting up in the deep
  zorza      — aurora curtains over a dark starry sky
  zegar      — the time, large and thin, in a slowly flowing ring of light
  swietliki  — fireflies blinking each at its own pace, now and then a trail
  lawa       — a lava lamp: one field of wax that stretches, merges, splits
  kominek    — a small fire on two logs, embers rising

Without the GPU face: the plain lamp's glow in the scene's colours.
"""

import math
import random
import time

import numpy as np

SCENES = ("meduzy", "zorza", "zegar", "swietliki", "lawa", "kominek")
NAMES = {"meduzy": "meduzy", "zorza": "zorza polarna", "zegar": "zegar",
         "swietliki": "świetliki", "lawa": "lampa lawa", "kominek": "kominek"}
_ID = {s: i + 1 for i, s in enumerate(SCENES)}
FPS = {"meduzy": 20, "zorza": 20, "zegar": 15, "swietliki": 24, "lawa": 20, "kominek": 24}
# (no GPU) the plain glow: centre, edge
FALLBACK = {"meduzy": ((90, 140, 255), (10, 15, 60)), "zorza": ((90, 230, 170), (5, 40, 50)),
            "zegar": ((110, 150, 255), (10, 15, 50)), "swietliki": ((255, 190, 90), (40, 25, 5)),
            "lawa": ((190, 80, 255), (40, 5, 70)), "kominek": ((255, 140, 50), (90, 25, 5))}
FADE = 1.5                     # s: in at the start and when switching, out at the end

# words → scene ("lampka z meduzami", "włącz zorzę polarną", "lampa lawa")
_STEMS = (("meduz", "meduzy"), ("zorz", "zorza"), ("aurora", "zorza"), ("zegar", "zegar"),
          ("świetlik", "swietliki"), ("swietlik", "swietliki"), ("robaczk", "swietliki"),
          ("lawa", "lawa"), ("lawą", "lawa"), ("lawę", "lawa"), ("lawe", "lawa"),
          ("lawow", "lawa"), ("lava", "lawa"), ("kominek", "kominek"), ("kominka", "kominek"),
          ("kominkiem", "kominek"), ("jellyfish", "meduzy"), ("firefl", "swietliki"),
          ("fireplace", "kominek"))


def scene_in(low):
    """The scene named in the words, or None."""
    for stem, scene in _STEMS:
        if stem in low:
            return scene
    return None


def next_scene(scene, step=1):
    i = SCENES.index(scene) if scene in SCENES else -1
    return SCENES[(i + step) % len(SCENES)]


# ── the simulations (one per lamp shown: keyed by its data dict) ──────────

class _Lava:
    # each blob: x centre, x swing, its period, y period, phase, radius, hue
    BLOBS = ((-0.36, 0.08, 83.0, 71.0, 0.0, 0.25, 0.2), (-0.14, 0.10, 61.0, 97.0, 2.1, 0.30, 0.8),
             (0.06, 0.09, 101.0, 64.0, 4.0, 0.22, 0.5), (0.24, 0.10, 73.0, 88.0, 1.0, 0.28, 0.1),
             (0.40, 0.07, 91.0, 76.0, 5.2, 0.21, 0.9), (-0.02, 0.16, 113.0, 109.0, 3.3, 0.26, 0.6))

    def __init__(self, rng):
        self.t0 = rng.uniform(0, 500)

    @staticmethod
    def _ease(s):                    # lingers at the top and the bottom, as wax does
        return math.copysign(abs(s) ** 0.7, s)

    def _pos(self, b, t):
        x0, sw, px, py, ph, r, hue = b
        x = x0 + sw * math.sin(2 * math.pi * t / px + ph) + 0.03 * math.sin(t / (px * 0.06) + ph)
        y = 0.5 + 0.40 * self._ease(math.sin(2 * math.pi * t / py + ph * 1.7))
        return x, y

    def uniforms(self, now):
        t = now + self.t0
        blobs, axes = [], []
        for i, b in enumerate(self.BLOBS):
            x, y = self._pos(b, t)
            x1, y1 = self._pos(b, t + 0.5)
            x2, y2 = self._pos(b, t - 0.5)
            vx, vy = x1 - x2, y1 - y2
            sp = math.hypot(vx, vy)
            st = 1.0 + 0.55 * min(1.0, sp / 0.03)            # stretched along its way
            a = math.atan2(vy, vx) if sp > 1e-6 else math.pi / 2
            r = 0.85 * b[5] * (1.0 + 0.08 * math.sin(t / 13.0 + i * 1.9))
            blobs.append((x, y, r, b[6]))
            axes.append((math.cos(a), math.sin(a), st, 1.0 / math.sqrt(st)))
        # the pools of wax at the bottom and the top, half out of sight
        blobs.append((0.05 * math.sin(t / 37.0), -0.19, 0.42, 0.35))
        axes.append((1.0, 0.0, 1.55 + 0.1 * math.sin(t / 23.0), 0.8))
        blobs.append((-0.08 + 0.05 * math.sin(t / 41.0), 1.19, 0.32, 0.7))
        axes.append((1.0, 0.0, 1.5, 0.8))
        return {"uBlob": blobs, "uBlobA": axes}


def _smooth(k):
    k = min(1.0, max(0.0, k))
    return k * k * (3 - 2 * k)


def _squeeze(ph):
    """The bell's pulse, as gl_lamp's squeeze(): a quick squeeze, slow relaxing."""
    ph %= 1.0
    return _smooth(ph / 0.28) if ph < 0.28 else 1.0 - _smooth((ph - 0.28) / 0.72)


ROPE = 12                     # points along each tentacle (gl_lamp's uRope)
_TENT, _ARMS = 8, 3


class _Jelly:
    """Swims in pulses along its bell's axis, which follows a slowly wandering
    heading (mostly up), sinks a little between pulses, turns about its axis.
    Its tentacles are chains of points in the water: each point follows the
    one before it (the first one is on the rim), with drag, a slight sinking
    and a gentle current - so the bell's moves run down them late, and they
    drape and curl when it glides."""

    def __init__(self, rng, w, h, y=None, x=None):
        self.rng, self.w, self.h = rng, w, h
        self.z = rng.uniform(0.35, 1.0)
        self.size = 40 + 55 * self.z
        self.x = x if x is not None else rng.uniform(0.12, 0.88) * w
        self.y = y if y is not None else h + self.size * 0.9
        self.period = rng.uniform(2.8, 4.4)
        self.ph0 = rng.random()
        self.hue = rng.random()
        self.L = rng.uniform(2.4, 3.4)
        self.seed = rng.random()
        self.heading = self.axis = rng.gauss(0.0, 0.2)       # rad from straight up, + right
        self.turn = 0.0
        self.vx, self.vy = 0.0, -0.15 * self.size
        self.yaw = rng.uniform(0, 2 * math.pi)
        self.spin = rng.choice((-1, 1)) * rng.uniform(0.08, 0.25)
        self.ph = 0.0
        self.tilt = -self.axis
        i = np.arange(_TENT + _ARMS)
        frac = (i * 0.618 + self.seed * 7.0) % 1.0
        self.rest = np.where(i < _TENT, self.L * (0.75 + 0.5 * frac),
                             self.L * 0.5 * (0.9 + 0.2 * frac)) * self.size
        self.phase = np.array([rng.uniform(0, 2 * math.pi) for _ in i])
        self.pts = self.prev = self.a1 = None

    def _anchors(self):
        """Where each tentacle (and oral arm) starts, on the screen."""
        s, ph = self.size, self.ph
        c_rim, c_top = _squeeze(ph - 0.07), _squeeze(ph)
        flare = 0.07 * (1.0 - c_rim) * _smooth((((ph - 0.07) % 1.0) - 0.5) / 0.4)
        w_rim = 1.0 - 0.30 * c_rim + flare
        bh = 0.70 + 0.20 * c_top
        lg = self.yaw + 0.7854 * np.arange(_TENT) + self.seed
        lx = np.sin(lg) * w_rim * 0.94
        ly = (0.20 + 0.14 * c_rim) * bh * (1.0 - (lx / w_rim) ** 2) - 0.05
        la = self.yaw * 0.5 + 2.1 * np.arange(-1, 2)
        lx = np.concatenate([lx, np.sin(la) * 0.14])
        ly = np.concatenate([ly, np.full(_ARMS, 0.10)])
        c, sn = math.cos(self.tilt), math.sin(self.tilt)
        return np.stack([self.x + (c * lx - sn * ly) * s, self.y - (sn * lx + c * ly) * s], -1)

    def _hang(self):
        """Its tentacles hanging straight behind it (a new one)."""
        st, ct = math.sin(self.tilt), math.cos(self.tilt)
        k = np.arange(ROPE)[None, :, None] * self.seg[:, :, None]
        self.pts = self.a1[:, None, :] + k * np.array([st, ct])
        self.prev = self.pts.copy()

    def step(self, t, dt):
        rng, w = self.rng, self.w
        self.ph = ph = (t / self.period + self.ph0) % 1.0
        push = math.sin(math.pi * ph / 0.28) if ph < 0.28 else 0.0
        thrust = self.size * 1.25 * push * (0.7 + 0.3 * self.z)
        self.vx += math.sin(self.axis) * thrust * dt
        self.vy -= math.cos(self.axis) * thrust * dt
        drag = math.exp(-dt * 1.1)
        self.vx *= drag
        self.vy = self.vy * drag + 4.0 * dt                   # sinking a little meanwhile
        self.x += self.vx * dt
        self.y += self.vy * dt
        # the heading wanders, back toward up, away from the sides
        self.turn += rng.gauss(0.0, 0.16) * math.sqrt(max(dt, 1e-6)) - self.turn * 0.5 * dt
        side = (min(1.0, max(0.0, (0.15 * w - self.x) / (0.12 * w)))
                - min(1.0, max(0.0, (self.x - 0.85 * w) / (0.12 * w))))
        self.heading += (self.turn - 0.25 * self.heading + 0.5 * side) * dt
        self.heading = max(-0.6, min(0.6, self.heading))
        self.axis += (self.heading - self.axis) * min(1.0, dt * 0.6)   # the body turns late
        self.tilt = -(self.axis + 0.05 * math.sin(2 * math.pi * ph))
        self.spin += rng.gauss(0.0, 0.05) * math.sqrt(max(dt, 1e-6))
        self.spin = max(-0.3, min(0.3, self.spin))
        self.yaw += self.spin * dt
        self.a0 = self.a1 if self.pts is not None else None   # (the rim a step ago)
        self.a1 = self._anchors()
        self.seg = (self.rest * (1.0 - 0.14 * _squeeze(ph - 0.18)) / (ROPE - 1))[:, None]
        if self.pts is None:
            self._hang()

    def gone(self):
        reach = (self.L * 1.25 + 1.5) * self.size
        return (self.y < -reach or self.y > self.h + reach
                or self.x < -reach or self.x > self.w + reach)

    def items(self, t):
        s = self.size
        st, ct = math.sin(self.tilt), math.cos(self.tilt)
        bright = 0.35 + 0.65 * self.z
        clock = t + self.seed * 50
        out = [(2.0, (self.x - 1.5 * s, self.y - 1.5 * s, self.x + 1.5 * s, self.y + 1.5 * s),
                (self.x, self.y, s, bright), (ct, st, self.ph, 0.0),
                (clock, self.hue, self.L, self.seed), (self.yaw, 0.0, 0.0, 0.0))]
        glow = 0.85 + 0.35 * _squeeze(self.ph)
        h = self.hue
        rim = (0.22 + 0.16 * h, 0.85 - 0.30 * h, 1.0)
        top = (0.32 + 0.30 * h, 0.30 + 0.02 * h, 1.0)
        lo, hi = self.pts.min(1).tolist(), self.pts.max(1).tolist()
        ropes = self.pts.reshape(_TENT + _ARMS, -1, 4).tolist()
        for i in range(_TENT + _ARMS):
            arm = i >= _TENT
            if arm:
                depth = 0.6 + 0.4 * math.cos(self.yaw * 0.5 + 2.1 * (i - _TENT - 1))
                wd, b, col = 0.024 * s, 0.24 * depth * bright * glow, top
            else:
                depth = 0.55 + 0.45 * math.cos(self.yaw + 0.7854 * i + self.seed)   # far: dimmer
                wd, b, col = 0.026 * s, 0.50 * depth * bright * glow, rim
            m = wd * (3.0 if arm else 7.0) + 2.0
            box = (lo[i][0] - m, lo[i][1] - m, hi[i][0] + m, hi[i][1] + m)
            out.append((3.0, box, None, (wd, b, 1.0 if arm else 0.0, (self.seed + i * 0.37) % 1.0),
                        col + (clock,), None, ropes[i]))
        return out


def _sim_ropes(jellies, t, dt):
    """Every tentacle at once: each point follows the one before it (the first
    is on the rim), with water drag, a slight sinking, a gentle current and a
    wave running down it — the bell's moves reach the tips late."""
    if dt <= 0:
        return
    n_r = _TENT + _ARMS
    P = np.concatenate([j.pts for j in jellies])
    prev = np.concatenate([j.prev for j in jellies])
    a0 = np.concatenate([j.a0 for j in jellies])
    a1 = np.concatenate([j.a1 for j in jellies])
    seg = np.concatenate([j.seg for j in jellies])
    size = np.repeat([j.size for j in jellies], n_r)[:, None]
    ph = np.concatenate([j.phase for j in jellies])[:, None]
    n = max(1, int(math.ceil(dt / (1 / 40))))
    h = dt / n
    damp = math.exp(-3.0 * h)
    amp = 0.20 * size                                         # the current, px/s^2
    along = np.arange(ROPE)[None, :] * 0.75
    wave = 1.6 * size * np.linspace(0.2, 1.4, ROPE)[None, :]
    for i in range(n):
        vel = (P - prev) * damp
        prev = P
        tt = t - dt + (i + 1) * h
        acc_x = amp * np.sin(P[..., 1] * 0.012 + tt * 0.8 + ph) + wave * np.sin(along - tt * 1.7 + ph)
        acc_y = 0.12 * size + 0.5 * amp * np.cos(P[..., 0] * 0.010 + tt * 0.6 + ph)
        P = P + vel + np.stack([acc_x, acc_y], -1) * (h * h)
        P[:, 1:-1] += 0.03 * (P[:, :-2] + P[:, 2:] - 2 * P[:, 1:-1])   # (a little stiff)
        P[:, 0] = a0 + (a1 - a0) * ((i + 1) / n)
        for k in range(1, ROPE):                              # each follows the one before
            d = P[:, k] - P[:, k - 1]
            ln = np.hypot(d[:, 0], d[:, 1])[:, None] + 1e-6
            P[:, k] = P[:, k - 1] + d * (seg / ln)
    for i, j in enumerate(jellies):
        j.pts, j.prev = P[i * n_r:(i + 1) * n_r], prev[i * n_r:(i + 1) * n_r]


class _Jellies:
    def __init__(self, rng, w, h):
        self.rng, self.w, self.h = rng, w, h
        xs = [(0.14 + 0.18 * i + rng.uniform(-0.05, 0.05)) * w for i in range(5)]
        rng.shuffle(xs)                                       # spread across, not bunched
        self.all = [_Jelly(rng, w, h, y=h * k, x=x)
                    for k, x in zip((0.2, 0.5, 0.8, 1.05, 1.3), xs)]
        self.t = None

    def uniforms(self, now):
        dt = 0.0 if self.t is None else min(0.2, now - self.t)
        self.t = now
        moving = []
        for i, j in enumerate(self.all):
            if j.gone():                                     # a new one from the deep
                others = [o.x for o in self.all if o is not j]   # where there is room
                x = max((self.rng.uniform(0.12, 0.88) * self.w for _ in range(6)),
                        key=lambda x: min(abs(x - o) for o in others))
                self.all[i] = j = _Jelly(self.rng, self.w, self.h, x=x)
            new = j.pts is None
            j.step(now, dt)
            if not new:
                moving.append(j)
        if moving:
            _sim_ropes(moving, now, dt)
        return {"items": [it for j in sorted(self.all, key=lambda j: j.z)
                          for it in j.items(now)]}


_AMBER, _GOLD, _CYAN = (1.0, 0.62, 0.18), (1.0, 0.82, 0.42), (0.30, 0.85, 1.0)


class _Fly:
    def __init__(self, rng, w, h, now):
        self.rng = rng
        self.z = rng.uniform(0.3, 1.0)
        self.x, self.y = rng.uniform(0.08, 0.92) * w, rng.uniform(0.25, 0.92) * h
        self.head = rng.uniform(0, 2 * math.pi)
        self.turn = 0.0
        self.vx = self.vy = 0.0
        self.col = rng.choices((_AMBER, _GOLD, _CYAN), (0.5, 0.32, 0.18))[0]
        self.home = rng.randrange(3)
        self.flash_t = -99.0
        self.next = now + rng.uniform(0.3, 6.0)
        self.peak, self.trail = 1.0, False

    def glow(self, now):
        tau = now - self.flash_t
        if tau < 0.35:
            k = tau / 0.35
            env = k * k * (3 - 2 * k)
        else:
            env = math.exp(-(tau - 0.35) / 0.6)
        return 0.08 + 0.92 * self.peak * env, env

    def step(self, now, dt, w, h, homes):
        rng = self.rng
        if now >= self.next:                                 # a flash, at its own time
            self.flash_t = now
            self.peak = rng.uniform(0.55, 1.0)
            self.trail = rng.random() < 0.35
            self.next = now + (0.9 if rng.random() < 0.2 else rng.uniform(2.5, 8.0))
        self.turn += rng.gauss(0, 1.4) * dt - self.turn * 0.6 * dt
        self.head += self.turn * dt
        sp = 8 + 14 * self.z
        hx, hy = homes[self.home]
        dx, dy = hx * w - self.x, hy * h - self.y
        d = math.hypot(dx, dy) or 1.0
        pull = min(1.0, d / 250.0) * 0.6                     # drifting toward their cluster
        wx = math.cos(self.head) * (1 - pull) + dx / d * pull
        wy = math.sin(self.head) * (1 - pull) + dy / d * pull
        # soft walls (and they keep off the very top)
        wx += max(0, 0.06 * w - self.x) / 40 - max(0, self.x - 0.94 * w) / 40
        wy += max(0, 0.18 * h - self.y) / 40 - max(0, self.y - 0.95 * h) / 40
        k = min(1.0, dt * 0.8)
        self.vx += (wx * sp - self.vx) * k
        self.vy += (wy * sp * 0.7 - self.vy) * k
        self.x += self.vx * dt
        self.y += self.vy * dt
        if rng.random() < dt / 40.0:
            self.home = rng.randrange(3)

    def item(self, now):
        b, env = self.glow(now)
        r = 3.0 + 4.0 * self.z
        tl = 0.7 * env if self.trail else 0.0                 # a short trail while it shines
        tx, ty = self.x - self.vx * tl, self.y - self.vy * tl
        m = r * 12
        box = (min(self.x, tx) - m, min(self.y, ty) - m, max(self.x, tx) + m, max(self.y, ty) + m)
        return (1.0, box, (self.x, self.y, tx, ty), (r, b * (0.4 + 0.6 * self.z), 0.0, 0.0),
                self.col + (0.0,))


class _Fireflies:
    def __init__(self, rng, w, h, now):
        self.rng, self.w, self.h = rng, w, h
        self.flies = [_Fly(rng, w, h, now) for _ in range(16)]
        self.seed = rng.uniform(0, 100)
        self.t = None

    def homes(self, now):
        t = now + self.seed
        return [(0.5 + 0.32 * math.sin(t / (23.0 + 7 * i) + i * 2.1),
                 0.6 + 0.2 * math.sin(t / (31.0 + 5 * i) + i * 1.3)) for i in range(3)]

    def uniforms(self, now):
        dt = 0.0 if self.t is None else min(0.2, now - self.t)
        self.t = now
        homes = self.homes(now)
        for f in self.flies:
            f.step(now, dt, self.w, self.h, homes)
        return {"items": [f.item(now) for f in self.flies]}


_sim = {"data": None, "scene": None, "obj": None}


def _make(scene, w, h, now):
    rng = random.Random()
    if scene == "lawa":
        return _Lava(rng)
    if scene == "meduzy":
        return _Jellies(rng, w, h)
    if scene == "swietliki":
        return _Fireflies(rng, w, h, now)
    return None


def uniforms(data, now, until, w, h):
    """The lamp overlay's data ({"scene", "t0"…}) → gl_lamp's uniforms."""
    scene = data.get("scene")
    if _sim["data"] is not data or _sim["scene"] != scene:
        _sim.update(data=data, scene=scene, obj=_make(scene, w, h, now))
        data.setdefault("since", now)
        if data.get("since_scene") != scene:
            data["since_scene"], data["since"] = scene, now
    t = now - data.get("t0", now)
    fade = min(1.0, (now - data["since"]) / FADE, max(0.0, (until - now) / FADE))
    u = {"uK": (float(_ID.get(scene, 1)), t, fade * fade * (3 - 2 * fade), 0.0)}
    if _sim["obj"] is not None:
        u.update(_sim["obj"].uniforms(now))
    return u


# ── the clock's digits (pygame, over the ring) ───────────────────────────

_DAYS = ("PON", "WT", "ŚR", "CZW", "PT", "SOB", "NIEDZ")
_MONTHS = ("STY", "LUT", "MAR", "KWI", "MAJ", "CZE", "LIP", "SIE", "WRZ", "PAŹ", "LIS", "GRU")
_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf"
_clock = {"key": None, "img": None, "old": None, "t": 0.0, "fonts": None}   # img: (surface, xy)
CROSSFADE = 1.2


def _fonts():
    if _clock["fonts"] is None:
        import pygame
        try:
            big, small = pygame.font.Font(_FONT, 150), pygame.font.Font(_FONT, 24)
        except (OSError, FileNotFoundError, pygame.error):
            import ui_screens
            big, small = ui_screens.font(140, "Regular"), ui_screens.font(22, "Regular")
        _clock["fonts"] = (big, small)
    return _clock["fonts"]


def clock_text(tm):
    return (f"{tm.tm_hour}:{tm.tm_min:02d}",
            f"{_DAYS[tm.tm_wday]}, {tm.tm_mday} {_MONTHS[tm.tm_mon - 1]}")


def _render(hhmm, date, w, h):
    import pygame
    big, small = _fonts()
    img = pygame.Surface((w, h), pygame.SRCALPHA)
    txt = big.render(hhmm, True, (214, 226, 245))
    cy = h // 2 - 12
    # a soft glow behind the digits: the text shrunk and stretched back
    gw, gh = max(1, txt.get_width() // 8), max(1, txt.get_height() // 8)
    halo = pygame.transform.smoothscale(
        pygame.transform.smoothscale(big.render(hhmm, True, (80, 150, 255)), (gw, gh)),
        (txt.get_width() + 30, txt.get_height() + 30))
    halo.set_alpha(80)
    img.blit(halo, halo.get_rect(center=(w // 2, cy)))
    img.blit(txt, txt.get_rect(center=(w // 2, cy)))
    letters = [small.render(ch, True, (150, 170, 205)) for ch in date]   # letter-spaced
    total = sum(l.get_width() for l in letters) + 5 * (len(letters) - 1)
    x = w // 2 - total // 2
    for l in letters:
        img.blit(l, (x, cy + 78))
        x += l.get_width() + 5
    r = img.get_bounding_rect()                        # (only that much blitted each frame)
    return img.subsurface(r).copy(), r.topleft


def draw_clock(surface, now, w, h, fade=1.0):
    """The time and date on the (clear) screen layer, the new minute fading in."""
    hhmm, date = clock_text(time.localtime(now))
    if _clock["key"] != (hhmm, date, w, h):
        _clock["old"] = _clock["img"]
        _clock["img"] = _render(hhmm, date, w, h)
        # (a minute ago on screen: it fades into the new one; else at once)
        _clock["t"] = now if now - _clock.get("drawn", 0.0) < 2.0 else now - CROSSFADE
        _clock["key"] = (hhmm, date, w, h)
    _clock["drawn"] = now
    k = min(1.0, max(0.0, (now - _clock["t"]) / CROSSFADE))
    if k < 1.0 and _clock["old"] is not None:
        img, xy = _clock["old"]
        img.set_alpha(int(255 * (1 - k) * fade))
        surface.blit(img, xy)
    img, xy = _clock["img"]
    img.set_alpha(int(255 * k * fade))
    surface.blit(img, xy)
