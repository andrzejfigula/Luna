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


class _Jelly:
    def __init__(self, rng, w, h, y=None):
        self.rng = rng
        self.z = rng.uniform(0.35, 1.0)
        self.size = 40 + 55 * self.z
        self.x = rng.uniform(0.12, 0.88) * w
        self.y = y if y is not None else h + self.size * 0.9
        self.period = rng.uniform(3.6, 5.6)
        self.ph = rng.random()
        self.hue = rng.random()
        self.L = rng.uniform(2.4, 3.4)
        self.seed = rng.random()
        self.sway = rng.uniform(0, 2 * math.pi)
        self.vy = -0.1 * self.size
        self.lean = self.tilt = self.c = 0.0

    def contraction(self, t):
        ph = (t / self.period + self.ph) % 1.0
        if ph < 0.3:                                         # quick squeeze
            k = ph / 0.3
            return k * k * (3 - 2 * k), ph
        k = (ph - 0.3) / 0.7                                 # slow relaxing
        return 1.0 - k * k * (3 - 2 * k), ph

    def step(self, t, dt):
        c, ph = self.contraction(t)
        push = math.sin(math.pi * ph / 0.3) if ph < 0.3 else -0.06
        want = -self.size * (0.06 + 0.40 * push) * (0.7 + 0.3 * self.z)
        self.vy += (want - self.vy) * min(1.0, dt * 3.0)
        vx = 7 * self.z * math.sin(t / 15.0 + self.sway) + 3 * math.sin(t / 6.3 + 2 * self.sway)
        self.x += vx * dt
        self.y += self.vy * dt
        self.tilt = 0.12 * math.sin(t / 9.0 + self.sway) - vx * 0.01
        # the tentacles trail behind, late: opposite to the way it goes
        target = -vx / self.size * 1.4 + self.tilt * 0.8
        self.lean += (target - self.lean) * min(1.0, dt / 1.5)
        self.c = c

    def gone(self):
        return self.y + self.L * 1.25 * self.size < -10

    def item(self, t):
        s = self.size
        m = (self.L * 1.25 + 0.5) * s
        box = (self.x - 1.6 * s - abs(self.lean) * s, self.y - 1.1 * s,
               self.x + 1.6 * s + abs(self.lean) * s, self.y + m)
        return (2.0, box, (self.x, self.y, s, (0.35 + 0.65 * self.z) * (0.9 + 0.1 * self.c)),
                (math.cos(self.tilt), math.sin(self.tilt), self.c, self.lean),
                (t + self.seed * 50, self.hue, self.L, self.seed))


class _Jellies:
    def __init__(self, rng, w, h):
        self.rng, self.w, self.h = rng, w, h
        self.all = [_Jelly(rng, w, h, y=h * k) for k in (0.2, 0.5, 0.8, 1.05, 1.3)]
        self.t = None

    def uniforms(self, now):
        dt = 0.0 if self.t is None else min(0.2, now - self.t)
        self.t = now
        for i, j in enumerate(self.all):
            j.step(now, dt)
            if j.gone():                                     # a new one from the deep
                self.all[i] = _Jelly(self.rng, self.w, self.h)
        return {"items": [j.item(now) for j in sorted(self.all, key=lambda j: j.z)]}


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
