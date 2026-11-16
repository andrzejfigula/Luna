"""
onface.py — Luna inside the weather: the rain and snow of her world outside
(environment.py) land on her. Snow piles up on top of her eyes (a height
field at its angle of repose: it slides off a slanted lid and over the
sides), is left in the air when a blink takes the lid from under it, puffs
up when the lid comes back, and is thrown off by a quick move. Rain splashes
on the top edge, gathers in beads that run down the eye in fits and starts
(merging, leaving a wet track), are swept by the lids, hang from the lower
rim and drip. A shake flings them off.

All of it is a small simulation here, in screen px (y down), from the eyes'
own uniforms (gl_face.face_uniforms); gl_onface.py draws what frame() packs.
Nothing runs while the sky is dry and she is.
"""
import math
import random

NC = 20            # columns across an eye's top: the snow's height field
NP = 256           # particles gl_onface's shader takes
K_WAVE = 0.085     # a running bead's meander, radians per px down

TUNE = {
    "on": 1.0,               # 0: off
    "g": 1400.0,             # gravity px/s² (her eye is ~3 cm: slowed, so it can be seen)
    "span": 340.0,           # flakes and drops fall this far either side of her middle
    # snow: flakes a second at its heaviest, how many at once, their size px
    # and fall px/s, the px² one adds to the pile
    "flake_rate": 14.0, "flakes": 56, "flake_r": (2.0, 3.6), "flake_v": (60.0, 110.0),
    "flake_area": 16.0,
    # the pile: its depth at most (px), its steepest slope, how fast it slides
    # (1/s); a top edge falling away faster than snow_hold × g (and by
    # snow_drop px/s in a frame) leaves it in the air, a sideways change of
    # speed past snow_jolt (px/s) starts to throw it; a
    # lid rising into it faster than snow_push (px/s) carries it (scattered
    # sideways this much, px/s) rather than letting it settle; clumps in the
    # air at most (snow_shed of what a blink or a jolt frees falls past the
    # eye); it wears away in snow_life s, melts in melt_life above 0 °C
    "snow_max": 16.0, "repose": 0.9, "slide": 10.0,
    "snow_hold": 1.5, "snow_drop": 400.0, "snow_jolt": 300.0, "snow_push": 160.0, "snow_scatter": 70.0,
    "snow_shed": 0.4, "clumps": 64, "snow_life": 240.0, "melt_life": 6.0,
    # rain: drops a second near her at its heaviest, their speed and length,
    # at once; more that land on the front of an eye a second; a splash's
    # droplets; free drops and rings at once
    "rain_rate": 20.0, "rains": 20, "rain_v": (820.0, 1000.0), "rain_len": 30.0,
    "patter": 5.0, "splash": 3, "drops": 28, "rings": 12,
    # beads on an eye: at most, the radius of one drop's worth (px), the mass
    # where one starts to run, its speed per mass over that and at most, what
    # a px of track costs it, how fast it dries (mass/s), the jolt (px/s²)
    # that makes it slide; the mass that drips from the lower rim; tracks
    # drying at once, in this many s
    "beads": 14, "bead_r": 3.4, "bead_go": 2.2, "bead_v": 70.0, "bead_vmax": 380.0,
    "bead_trail": 0.006, "bead_dry": 0.035, "bead_hold": 4000.0,
    "drip_m": 5.0, "tracks": 16, "track_dry": 5.0,
}

# a bead's fields
_X, _Y, _VY, _M, _R, _XA, _Y0, _AMP, _PH, _VX, _PEND = range(11)


class _Eye:
    """An eye as the weather meets it: where it is on the screen, its top
    and bottom edges per column (in its own frame, px from its middle), how
    they move, the snow on it and the beads."""

    def __init__(self, side):
        self.side = side                  # -1 the left one, +1 the right
        self.ok = False
        self.x = self.y = 0.0
        self.c, self.s = 1.0, 0.0         # its turn (the head's and its own)
        self.bx, self.dx, self.rad = 1.0, 1.0, 0.0
        self.top = [0.0] * NC
        self.bot = [0.0] * NC
        self.vt = [0.0] * NC              # the top edge's own speed (a lid coming down: +)
        self.vs = [0.0] * NC              # …and with the eye's: what the snow stands on
        self.vx = self.vy = self.ax = self.ay = 0.0
        self.h = [0.0] * NC               # the snow's depth
        self.snow = 0.0                   # …all of it
        self.spill = [0.0, 0.0]           # px² gone over each side, not yet a clump
        self.water = 0.0                  # melted, not yet a bead
        self.beads = []

    def out(self, qx, qy):
        """Its own frame → the screen."""
        return self.x + self.c * qx - self.s * qy, self.y + self.s * qx + self.c * qy


class OnFace:
    """One per face (gl_face.GLFace.onface)."""

    def __init__(self, seed=None):
        self.rnd = random.Random(seed)
        self.eyes = (_Eye(-1.0), _Eye(1.0))
        self.flakes, self.clumps = [], []     # [x, y, vx, vy, r, its fall px/s, px², carried, seed]
        self.rain = []                        # [x, y, vx, vy]
        self.drops = []                       # [x, y, vx, vy, r, mass, the eye it left, age]
        self.rings = []                       # [x, y, age, r]
        self.tracks = []                      # [eye, xa, y0, y1, amp, phase, half width, alpha]
        self.acc = [0.0, 0.0, 0.0]            # flakes, drops, patter owed
        self.t_last = None
        self.w, self.h = 800, 480
        self.fx, self.fy = 400.0, 200.0

    def busy(self):
        return bool(self.flakes or self.clumps or self.rain or self.drops or self.rings
                    or self.tracks or any(e.beads or e.snow > 0.05 for e in self.eyes))

    # ── a frame ───────────────────────────────────────────────────────────
    def frame(self, now, u, w, h):
        """u: the face's uniforms with environment's in them. What gl_onface
        draws, or None when there is nothing."""
        T = TUNE
        wx = u.get("uEnvW")
        if (not wx or T["on"] <= 0.0 or u.get("uEnvOn", 0.0) < 0.5 or u.get("uFace", 1.0) < 0.5
                or u.get("uLens", 0.0) > 0.5 or "uEye0" not in u):
            self.t_last = None
            return None
        rain = wx[2] if wx[2] > 0.02 else 0.0
        snow = wx[3] if wx[3] > 0.02 else 0.0
        if not (rain or snow or self.busy()):
            self.t_last = None
            return None
        dt = now - self.t_last if self.t_last is not None else -1.0
        self.t_last = now
        fresh = not 0.0 < dt < 0.25           # the first frame, or back after a while
        dt = 1.0 / 60 if fresh else max(1.0 / 240, min(0.05, dt))
        self.w, self.h = w, h
        gl = u.get("uEnvGlass")               # (its melt: 1 above 0 °C)
        melt = gl[3] if gl else 0.0 if snow else 1.0
        slant = u.get("uEnvX", (0.0, 0.0))[1]
        for i, e in enumerate(self.eyes):
            self._place(e, i, u, dt, fresh)
        e0, e1 = self.eyes
        self.fx, self.fy = 0.5 * (e0.x + e1.x), 0.5 * (e0.y + e1.y)
        wind = 0.6 * slant                   # (as the snow behind her leans)
        self._flakes(snow, wind, dt)
        self.flakes = self._snow(self.flakes, dt, wind, now, melt)
        self.clumps = self._snow(self.clumps, dt, wind, now, melt)
        self._rain(rain, slant, dt)
        self._free(dt)
        self.rings = [r for r in self.rings if r[2] + dt < 0.16]
        for r in self.rings:
            r[2] += dt
        for i, e in enumerate(self.eyes):
            if e.snow > 0.0:
                self._pile(e, dt, melt)
            if e.beads:
                self._beads(e, i, dt, rain)
        self._tracks(dt)
        return self._pack()

    # ── where an eye is, and what its moves do to the snow ────────────────
    def _place(self, e, i, u, dt, fresh):
        ex, ey, ew, eh = u["uEye%d" % i]
        top, ltilt, bend, bot = u["uLidA%d" % i]
        bbend, _seam, rot, n = u["uLidB%d" % i]
        n = max(1.0, n + (2.0 - n) * u.get("uMorph", (0.0, 0.0, 0.0, 0.0))[2])
        tilt = u.get("uTilt", 0.0)
        cx, cy = self.w / 2.0, self.h / 2.0
        ct, st = math.cos(tilt), math.sin(tilt)
        x = cx + ct * (ex - cx) + st * (ey - cy)           # (as gl_face._box turns it)
        y = cy - st * (ex - cx) + ct * (ey - cy)
        th = rot * e.side - tilt                           # (the shader's eyeLocal, undone)
        bx, by = max(1.0, ew / 2.0), max(1.0, eh / 2.0)
        inv = 1.0 / n
        nt, nb = [], []
        for j in range(NC):                                # (gl_face's eyeSDF: squircle, lids)
            xn = (j + 0.5) * 2.0 / NC - 1.0
            sq = by * (1.0 - abs(xn) ** n) ** inv
            k = 2.0 * by * (1.0 - xn * xn)
            yt = -by + 2.0 * by * top - ltilt * by * e.side * xn - bend * k
            yb = by - 2.0 * by * bot - bbend * k
            t, b = max(-sq, yt), min(sq, yb)
            if b - t < 11.0:                               # shut: the seam where the lids meet
                m = min(sq, max(-sq, 0.5 * (yt + yb)))
                t, b = m - 5.5, m + 5.5
            nt.append(t)
            nb.append(b)
        if fresh or not e.ok or abs(x - e.x) + abs(y - e.y) > 120.0:
            vx = vy = e.ax = e.ay = 0.0
            vt = [0.0] * NC
            vs = [0.0] * NC
        else:
            vx, vy = (x - e.x) / dt, (y - e.y) / dt
            e.ax, e.ay = (vx - e.vx) / dt, (vy - e.vy) / dt
            vt = [(a - b) / dt for a, b in zip(nt, e.top)]
            vs = [vy + v for v in vt]
            if e.snow > 0.05:
                self._shake(e, vx, vs, dt)                  # (while e is still where it was)
        e.ok = True
        e.x, e.y, e.c, e.s = x, y, math.cos(th), math.sin(th)
        e.bx, e.dx, e.rad = bx, 2.0 * bx / NC, bx + by + 24.0
        e.top, e.bot, e.vt, e.vs, e.vx, e.vy = nt, nb, vt, vs, vx, vy

    def _shake(self, e, vx, vs, dt):
        """The edge under the snow fell away faster than it can follow (a
        blink), or jolted sideways: that snow is in the air, moving as the
        eye did a frame ago."""
        T = TUNE
        fall, drop, jolt = T["snow_hold"] * T["g"], T["snow_drop"], T["snow_jolt"]
        side = min(1.0, max(0.0, (abs(vx - e.vx) - jolt) / (2.0 * jolt)))
        h = e.h
        for j in range(NC):
            d = h[j]
            if d < 0.05:
                continue
            dv = vs[j] - e.vs[j]                # (her gaze and breath are px a frame: not a jolt)
            part = 1.0 if dv > drop and dv / dt > fall else side
            if part > 0.0 and self._clump(e, -e.bx + (j + self.rnd.uniform(0.1, 0.9)) * e.dx,
                                          e.top[j] - d * (1.0 - part), d * part, e.vx, e.vs[j],
                                          T["snow_shed"]):
                h[j] -= d * part
                e.snow -= d * part

    def _clump(self, e, qx, base, depth, vx, vy, shed=0.0):
        """A column's snow `depth` deep lying on `base` (the eye's frame)
        becomes a clump or two in the air (False: no room for it). `shed`:
        the share that tumbles forward, past the eye, and is gone."""
        T, rnd = TUNE, self.rnd
        area = depth * e.dx
        if area < 1.5 or len(self.clumps) >= T["clumps"]:
            return False
        n = 2 if area > 70.0 else 1
        for _ in range(n):
            a = area / n
            r = min(7.0, max(1.6, 1.3 * math.sqrt(a / math.pi)))
            x, y = e.out(qx, base - 1.0 - depth * rnd.random())
            self.clumps.append([x, y, vx + rnd.uniform(-25.0, 25.0), vy, r, 100.0 + 14.0 * r,
                                a, 2 if rnd.random() < shed else 0, rnd.random()])
        return True

    # ── snow in the air ───────────────────────────────────────────────────
    def _flakes(self, snow, wind, dt):
        T, rnd = TUNE, self.rnd
        self.acc[0] += T["flake_rate"] * snow * dt
        while self.acc[0] >= 1.0:
            self.acc[0] -= 1.0
            if len(self.flakes) >= T["flakes"]:
                continue
            r = rnd.uniform(*T["flake_r"])
            vt = rnd.uniform(*T["flake_v"]) * (0.7 + 0.1 * r)
            x = self.fx + rnd.uniform(-T["span"], T["span"]) - wind * (self.fy + 8.0)
            self.flakes.append([x, -8.0, wind * vt, vt, r, vt, T["flake_area"] * (r / 3.0) ** 2,
                                0, rnd.random()])

    def _snow(self, parts, dt, wind, now, melt):
        """Flakes and clumps: the air holds them (each falls at its own
        pace, drifts with the wind), an eye's top catches them."""
        if not parts:
            return parts
        T, rnd = TUNE, self.rnd
        g, push, sc = T["g"], T["snow_push"], T["snow_scatter"]
        W, H, eyes = self.w, self.h, self.eyes
        keep = []
        for p in parts:
            vt = p[5]
            k = min(1.0, g / vt * dt)
            p[2] += (wind * vt + 320.0 / p[6] ** 0.5 / (1.0 + p[4]) * math.sin(now * 1.3 + p[8] * 40.0)
                     - p[2]) * k
            p[3] += (vt - p[3]) * k
            x = p[0] = p[0] + p[2] * dt
            y = p[1] = p[1] + p[3] * dt
            if y > H + 12.0 or x < -40.0 or x > W + 40.0:
                continue
            landed = False
            for e in eyes:
                ddx, ddy = x - e.x, y - e.y
                if abs(ddx) > e.rad or abs(ddy) > e.rad or p[7] == 2:
                    continue
                qx = e.c * ddx + e.s * ddy
                if abs(qx) >= e.bx:
                    continue
                qy = e.c * ddy - e.s * ddx
                j = int((qx + e.bx) / e.dx)
                surf = e.top[j] - e.h[j]
                if qy < surf or qy > e.bot[j]:
                    continue
                vsup = e.vy + e.vt[j]
                if vsup - p[3] > push:           # the lid coming up under it: carried, not bounced
                    if not p[7]:
                        p[7] = 1
                        p[2] = e.vx + rnd.uniform(-sc, sc)
                    p[3] = vsup
                    p[0], p[1] = e.out(qx, surf - 1.0)
                elif melt > 0.6:                 # wet snow: water
                    self._wet(e, qx, e.top[j], 0.04 * p[6])
                    landed = True
                else:
                    d = p[6] / e.dx
                    h = e.h
                    h[j] += 0.5 * d
                    h[j - 1 if j else j] += 0.25 * d
                    h[j + 1 if j < NC - 1 else j] += 0.25 * d
                    e.snow += d
                    landed = True
                break
            if not landed:
                keep.append(p)
        return keep

    def _pile(self, e, dt, melt):
        """The snow on an eye: it slides where it lies steeper than it can,
        goes over the sides, wears away (melts into beads above 0 °C)."""
        T, rnd = TUNE, self.rnd
        h, top = e.h, e.top
        lim = T["repose"] * e.dx
        k = min(1.0, T["slide"] * dt)
        for j in range(NC - 1):
            d = (top[j + 1] - h[j + 1]) - (top[j] - h[j])       # > 0: j stands higher
            if d > lim:
                if h[j] > 0.0:
                    m = min(h[j], 0.5 * (d - lim) * k)
                    h[j] -= m
                    h[j + 1] += m
            elif d < -lim and h[j + 1] > 0.0:
                m = min(h[j + 1], 0.5 * (-d - lim) * k)
                h[j + 1] -= m
                h[j] += m
        for s, j in ((0, 0), (1, NC - 1)):                      # the ends: over the side
            if h[j] > 0.0:
                m = h[j] * k
                h[j] -= m
                e.spill[s] += m * e.dx
                if e.spill[s] > 14.0:
                    out = 1.0 if s else -1.0
                    self._clump(e, out * (e.bx + 2.0), top[j], e.spill[s] / e.dx,
                                e.vx + out * rnd.uniform(15.0, 40.0), e.vy)
                    e.spill[s] = 0.0
        fade = math.exp(-dt * (1.0 / T["snow_life"] + melt * melt / T["melt_life"]))
        over = T["snow_max"]
        tot = 0.0
        for j in range(NC):
            v = h[j]
            if v <= 0.0:
                continue
            e.water += v * (1.0 - fade) * e.dx * melt
            v *= fade
            if v > over:                                        # full: the rest tumbles on
                self._clump(e, -e.bx + (j + 0.5) * e.dx, top[j] - over, v - over,
                            e.vx + rnd.choice((-1.0, 1.0)) * rnd.uniform(40.0, 90.0), e.vy - 50.0)
                v = over
            if v < 0.02:
                v = 0.0
            h[j] = v
            tot += v
        e.snow = tot
        if e.water > 25.0:                                      # melt water: a bead at its foot
            e.water -= 25.0
            j = rnd.randrange(NC)
            self._wet(e, -e.bx + (j + 0.5) * e.dx, top[j], 1.0)

    # ── rain ──────────────────────────────────────────────────────────────
    def _rain(self, rain, slant, dt):
        T, rnd = TUNE, self.rnd
        eyes, H = self.eyes, self.h
        if rain:
            self.acc[1] += T["rain_rate"] * rain ** 1.3 * dt
            n = math.hypot(slant, 1.0)
            while self.acc[1] >= 1.0:
                self.acc[1] -= 1.0
                if len(self.rain) < T["rains"]:
                    v = rnd.uniform(*T["rain_v"])
                    x = self.fx + rnd.uniform(-T["span"], T["span"]) - slant * (self.fy + 20.0)
                    self.rain.append([x, -20.0, v * slant / n, v / n])
            self.acc[2] += T["patter"] * rain * dt
            while self.acc[2] >= 1.0:            # a drop on the front of an eye
                self.acc[2] -= 1.0
                e = rnd.choice(eyes)
                j = rnd.randrange(1, NC - 1)
                if e.ok and e.h[j] < 1.0:
                    qx = -e.bx + (j + rnd.random()) * e.dx
                    qy = e.top[j] + rnd.random() * (e.bot[j] - e.top[j])
                    self._wet(e, qx, qy, 0.6)
                    if len(self.rings) < T["rings"]:
                        self.rings.append([*e.out(qx, qy), 0.0, rnd.uniform(3.0, 5.0)])
        keep = []
        for p in self.rain:
            px, py = p[0], p[1]
            x = p[0] = px + p[2] * dt
            y = p[1] = py + p[3] * dt
            if y > H + 40.0:
                continue
            hit = False
            for i, e in enumerate(eyes):
                ddx, ddy = x - e.x, y - e.y
                if abs(ddx) > e.rad or ddy < -e.rad or py - e.y > e.rad:
                    continue
                qx = e.c * ddx + e.s * ddy
                if abs(qx) >= e.bx:
                    continue
                j = int((qx + e.bx) / e.dx)
                surf = e.top[j] - e.h[j]
                if e.c * ddy - e.s * ddx < surf or e.c * (py - e.y) - e.s * (px - e.x) > e.bot[j]:
                    continue                     # (still above it, or was past it already)
                self._splash(e, i, j, qx, surf)
                hit = True
                break
            if not hit:
                keep.append(p)
        self.rain = keep

    def _splash(self, e, i, j, qx, surf):
        """A drop on an eye's top edge: a ring, a few droplets thrown up, the
        rest stays as water. Into snow: a pit."""
        T, rnd = TUNE, self.rnd
        if e.h[j] > 1.0:
            e.h[j] -= 0.35
            return
        x, y = e.out(qx, surf)
        if len(self.rings) < T["rings"]:
            self.rings.append([x, y, 0.0, rnd.uniform(5.0, 8.0)])
        vs = e.vy + e.vt[j]
        for _ in range(T["splash"]):
            if len(self.drops) >= T["drops"]:
                break
            self.drops.append([x, y - 2.0, e.vx + rnd.uniform(-150.0, 150.0),
                               vs - rnd.uniform(110.0, 260.0), rnd.uniform(0.9, 1.6), 0.12, i, 0.0])
        self._wet(e, qx, e.top[j], 0.65)

    def _free(self, dt):
        """Water in the air: a splash's droplets, drips, what a shake threw."""
        if not self.drops:
            return
        g = TUNE["g"]
        W, H, eyes = self.w, self.h, self.eyes
        keep = []
        for p in self.drops:
            p[3] += g * dt
            p[2] *= 1.0 - 0.6 * dt
            x = p[0] = p[0] + p[2] * dt
            y = p[1] = p[1] + p[3] * dt
            p[7] += dt
            if y > H + 20.0 or x < -20.0 or x > W + 20.0:
                continue
            landed = False
            for i, e in enumerate(eyes):
                ddx, ddy = x - e.x, y - e.y
                if abs(ddx) > e.rad or abs(ddy) > e.rad or (i == p[6] and p[7] < 0.12):
                    continue
                qx = e.c * ddx + e.s * ddy
                if abs(qx) >= e.bx:
                    continue
                qy = e.c * ddy - e.s * ddx
                j = int((qx + e.bx) / e.dx)
                if qy < e.top[j] - e.h[j] or qy > e.bot[j]:
                    continue
                if e.h[j] <= 1.0:
                    self._wet(e, qx, max(qy, e.top[j]), p[5])
                landed = True
                break
            if not landed:
                keep.append(p)
        self.drops = keep

    # ── water on an eye ───────────────────────────────────────────────────
    def _wet(self, e, qx, qy, m):
        """Water lands on an eye at (qx, qy) of its frame: into the bead
        that is there, or a new one."""
        beads = e.beads
        best, bd = None, 1e9
        for b in beads:
            d = (b[_X] - qx) ** 2 + (b[_Y] - qy) ** 2
            if d < bd:
                best, bd = b, d
        if best is not None and (bd < (best[_R] + 5.0) ** 2 or len(beads) >= TUNE["beads"]):
            best[_M] += m
            return
        amp, ph = self.rnd.uniform(1.5, 4.5), self.rnd.uniform(0.0, math.tau)
        beads.append([qx, qy, 0.0, m, TUNE["bead_r"] * m ** 0.3333,
                      qx - amp * math.sin(K_WAVE * qy + ph), qy, amp, ph, 0.0, 0])

    def _leave(self, i, b):
        """A bead's wet track stays behind it and dries."""
        if b[_Y] - b[_Y0] > 4.0:
            self.tracks.append([i, b[_XA], b[_Y0], b[_Y], b[_AMP], b[_PH], 0.45 * b[_R], 1.0])
            if len(self.tracks) > TUNE["tracks"]:
                del self.tracks[0]
        b[_Y0] = b[_Y]

    def _beads(self, e, i, dt, rain):
        T = TUNE
        g = T["g"]
        # what a bead feels of the eye's moves, in the eye's own frame
        alx, aly = -(e.c * e.ax + e.s * e.ay), -(e.c * e.ay - e.s * e.ax)
        am = math.hypot(alx, aly)
        slip = 1.0 - T["bead_hold"] / am if am > T["bead_hold"] else 0.0
        heavy = 1.0 + max(0.0, -e.ay) / g + abs(e.ax) / (2.0 * g)     # (a jolt: a hanging drop weighs more)
        dry = T["bead_dry"] * (1.0 - 0.8 * min(1.0, rain)) * dt
        lim = e.bx - 0.5
        keep = []
        for b in e.beads:
            m = b[_M] - dry
            x, y = b[_X], b[_Y]
            if m < 0.15 or abs(x) >= lim:
                self._leave(i, b)
                if m >= 0.15:                    # off the side: into the air
                    self._fling(e, i, b, m)
                continue
            r = b[_R] = T["bead_r"] * m ** 0.3333
            j = int((x + e.bx) / e.dx)
            top, bot = e.top[j], e.bot[j]
            if slip:
                b[_VX] += alx * dt * slip
                b[_VY] += aly * dt * slip
            if b[_PEND]:                         # hanging from the lower rim: along it, downhill
                slope = (e.bot[min(NC - 1, j + 1)] - e.bot[max(0, j - 1)]) / (2.0 * e.dx)
                b[_VX] += (max(-60.0, min(60.0, 140.0 * slope)) - b[_VX]) * min(1.0, 6.0 * dt)
                x = max(-0.9 * e.bx, min(0.9 * e.bx, x + b[_VX] * dt))
                y = b[_Y0] = bot
                if m * heavy > T["drip_m"] and len(self.drops) < T["drops"]:
                    sx, sy = e.out(x, y + r)
                    self.drops.append([sx, sy, e.vx, e.vy + 20.0, T["bead_r"] * (0.75 * m) ** 0.3333,
                                       0.75 * m, i, 0.0])
                    m *= 0.25
            else:
                go = m - T["bead_go"]            # heavy enough to run: in fits and starts
                vt = (min(T["bead_vmax"], 25.0 + T["bead_v"] * go)
                      * (0.55 + 0.45 * math.sin(y * 0.11 + b[_PH]))) if go > 0.0 else 0.0
                b[_VY] += (vt - b[_VY]) * min(1.0, 8.0 * dt)
                dy = b[_VY] * dt
                y += dy
                m -= T["bead_trail"] * abs(dy)
                if abs(b[_VX]) > 1.0:            # thrown sideways: its track stays where it was
                    if abs(b[_VX]) > 40.0:
                        b[_Y] = y
                        self._leave(i, b)
                    b[_XA] += b[_VX] * dt
                    b[_VX] *= max(0.0, 1.0 - 6.0 * dt)
                x = b[_XA] + b[_AMP] * math.sin(K_WAVE * y + b[_PH])
                if y < top + r:                  # a lid comes down: swept along
                    y = top + r
                if b[_Y0] < top:
                    b[_Y0] = top
                if y >= bot - 0.3 * r:
                    b[_Y] = y = bot
                    self._leave(i, b)
                    b[_PEND], b[_VY], b[_VX] = 1, 0.0, 0.0
            b[_X], b[_Y], b[_M] = x, y, m
            keep.append(b)
        n = len(keep)
        for a in range(n - 1):                   # two that touch run together (the lower one keeps on)
            p = keep[a]
            for k in range(a + 1, n):
                q = keep[k]
                if p is None:
                    break
                if q is None:
                    continue
                rr = p[_R] + q[_R]
                if (p[_X] - q[_X]) ** 2 + (p[_Y] - q[_Y]) ** 2 < 0.7 * rr * rr:
                    lo, hi, hi_at = (q, p, a) if (q[_PEND], q[_Y]) >= (p[_PEND], p[_Y]) else (p, q, k)
                    lo[_M] += hi[_M]
                    lo[_VY] = max(lo[_VY], hi[_VY])
                    self._leave(i, hi)
                    keep[hi_at] = None
                    if hi is p:
                        p = None
        e.beads = [b for b in keep if b is not None]

    def _fling(self, e, i, b, m):
        if len(self.drops) < TUNE["drops"]:
            x, y = e.out(b[_X], b[_Y])
            self.drops.append([x, y, e.vx + e.c * b[_VX] - e.s * b[_VY], e.vy + e.s * b[_VX] + e.c * b[_VY],
                               b[_R], m, i, 0.0])

    def _tracks(self, dt):
        if not self.tracks:
            return
        k = dt / TUNE["track_dry"]
        keep = []
        for t in self.tracks:
            t[7] -= k
            e = self.eyes[t[0]]
            j = max(0, min(NC - 1, int((t[1] + e.bx) / e.dx)))
            if t[2] < e.top[j]:                  # a lid wipes it
                t[2] = e.top[j]
            if t[7] > 0.0 and t[3] - t[2] > 2.0:
                keep.append(t)
        self.tracks = keep

    # ── what gl_onface draws ──────────────────────────────────────────────
    def _pack(self):
        """Two vec4 a particle (A, B), in the order drawn, and the runs of
        each kind: 1 a wet track (in its eye's frame), 2 water, 5 snow,
        3 rain, 4 a splash's ring; 0 marks where the snow caps go."""
        A, B, runs = [], [], []
        eyes = self.eyes
        for t in self.tracks:
            A += (t[1], t[2], t[3], t[0])
            B += (t[4], t[5], t[6], 0.8 * t[7])
        for i, e in enumerate(eyes):
            for b in e.beads:
                if b[_Y] - b[_Y0] > 3.0:
                    A += (b[_XA], b[_Y0], b[_Y], i)
                    B += (b[_AMP], b[_PH], 0.45 * b[_R], 0.8)
        n1 = len(A) // 4
        runs.append((1, 0, n1))
        for e in eyes:
            dx, dy = -e.s, e.c                   # down the eye
            for b in e.beads:
                x, y = e.out(b[_X], b[_Y])
                A += (x, y, b[_R], 1.0)
                B += (1.3 if b[_PEND] else 1.0 + min(0.8, b[_VY] / 300.0), dx, dy, 0.0)
        n2 = len(A) // 4
        runs.append((2, n1, n2 - n1))
        runs.append((0, 0, 0))
        for p in self.flakes:
            A += (p[0], p[1], p[4], 0.95)
            B += (p[8], 0.0, 0.0, 0.0)
        for p in self.clumps:
            A += (p[0], p[1], p[4], 0.95)
            B += (p[8], 1.0, 0.0, 0.0)
        n3 = len(A) // 4
        runs.append((5, n2, n3 - n2))
        ln = TUNE["rain_len"]
        for p in self.rain:
            v = math.hypot(p[2], p[3]) or 1.0
            A += (p[0], p[1], ln, 0.55)
            B += (p[2] / v, p[3] / v, 1.5, 0.0)
        n4 = len(A) // 4
        runs.append((3, n3, n4 - n3))
        for p in self.drops:
            v = math.hypot(p[2], p[3]) or 1.0
            A += (p[0], p[1], p[4], 1.0)
            B += (1.0 + min(1.2, v / 500.0), p[2] / v, p[3] / v, 0.0)
        n5 = len(A) // 4
        runs.append((2, n4, n5 - n4))
        for r in self.rings:
            k = r[2] / 0.16
            A += (r[0], r[1], r[3] * (0.4 + k), 1.0 - k)
            B += (0.0, 0.0, 0.0, 0.0)
        n6 = len(A) // 4
        runs.append((4, n5, n6 - n5))
        if n6 > NP:                              # (the caps above keep it under; never over)
            A, B, n6 = A[:4 * NP], B[:4 * NP], NP
            runs = [(k, f, max(0, min(c, NP - f))) for k, f, c in runs]
        cap = []
        for e in eyes:
            h, top = e.h, e.top
            for j in range(NC):                  # (drawn a little smoother than it lies)
                cap += (top[j], 0.5 * h[j] + 0.25 * (h[j - 1 if j else j] + h[j + 1 if j < NC - 1 else j]))
        return {"A": A, "B": B, "n": n6, "runs": runs, "cap": cap,
                "snow": tuple(e.snow > 0.05 for e in eyes),
                "eyeT": [v for e in eyes for v in (e.x, e.y, e.c, e.s)],
                "eyeK": [v for e in eyes for v in (e.bx, e.dx, 0.0, 0.0)]}
