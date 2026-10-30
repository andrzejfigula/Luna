"""
environment.py — the world outside, as Luna's background: the time of day,
the season and the weather, blended into a few numbers for gl_face's shader
(the soft pass: the sky's gradient, the arc's glow, the sun's haze, clouds,
fog; the ENV stretch: the arc's fine line, rain, snow and a few stars).

Data only, no GL. The targets are worked out every 20 s (the sun's height
from the clock and the weather's place, the season by the hemisphere,
weather.sky_now()); frame() only eases toward them over real time and steps
the particles' clocks, so a weather refresh never resets the rain. Without a
forecast there is no weather — the sky alone, nothing made up.

A simulated state wins over the real one and says so (label()):
tools/env_sim.py writes SIM_FILE on the Pi; the preview calls simulate().
"""

import math
import os
import random
import time

import moon
import settings

SIM_FILE = "/tmp/luna_env_sim"
HOME = (52.0, 19.0)          # no place set: the sun over Poland's middle
CLOCK_WRAP = 600.0           # the particles' clocks wrap here (the shader's per())

# ── everything tunable ────────────────────────────────────────────────────
TUNE = {
    "brightness": 1.0,       # the whole sky
    "face_shade": 0.38,      # darker behind her face (her features stay the brightest)
    "horizon": 0.66,         # the haze band's height, a fraction of the height
    # the one arc: three points it passes (fractions of the screen), its
    # line's width and glow (px), how far it drifts (px) over minutes
    "arc_pts": ((0.985, -0.03), (0.935, 0.20), (0.815, 0.37)),
    "arc_width": 1.4, "arc_glow": 9.0, "arc_drift": 5.0,
    "sun_x": 0.83,           # the sun's haze: across, its size × the height
    "sun_size": 0.30,
    # rain at its heaviest: drops on screen, their opacity, length px, speed px/s
    "rain_count": 340, "rain_alpha": 0.32, "rain_len": 24.0, "rain_speed": 620.0,
    # snow at its heaviest: flakes, opacity, size px, speed px/s
    "snow_count": 230, "snow_alpha": 0.75, "snow_size": 1.6, "snow_speed": 34.0,
    "stars": 1.0, "star_count": 110,    # clear nights: many, a few big bright ones
    "moon": 0.95, "moon_pos": (0.12, 0.16), "moon_r": 22.0,   # its real phase (at least a sliver)
    # the clouds: soft layers of one noise field (gl_face's envLayer), back to
    # front — their band's middle and half height (× the height), how far a
    # noise tile spans across (× the width) and up (× the height: their
    # stretch), drift px/s, the cloud amount they fill over, their cover and
    # opacity, how much of that shows on a clear day
    "cloud_layers": ((0.15, 0.10, 0.95, 0.11, 1.0, (0.00, 0.70), 0.35, 0.32, 1.00),   # wisps high up
                     (0.40, 0.13, 1.50, 0.30, 0.5, (0.10, 0.85), 0.15, 0.40, 0.35),   # a far layer
                     (0.86, 0.20, 1.25, 0.42, 1.4, (0.05, 0.85), 0.20, 0.80, 0.55),   # the low bank
                     (0.66, 0.08, 0.70, 0.10, 2.6, (0.15, 0.80), 0.25, 0.26, 0.60)),  # thin wisps, near
    "motion": 1.0,           # every animation's pace (0: still)
    "ease": 7.0, "ease_weather": 10.0, "ease_sim": 2.5,      # seconds
    "asleep_dim": 0.62,      # her asleep: the sky dims to this
}

# the sky by the sun's height (degrees): evening and morning keys, eased between
# zen: the top, mid: behind her, hor: the horizon, sun: its haze (rgb, a),
# arc: the arc's colour and strength, low: the bottom of the screen;
# clouds: cl lit, cs shaded, cr the faint light on some of their tops (rgb, a)
def _k(zen, mid, hor, sun, sun_a, arc, arc_a, low, cl, cs, cr, cr_a):
    return {"zen": zen, "mid": mid, "hor": hor, "sun": sun, "sun_a": sun_a,
            "arc": arc, "arc_a": arc_a, "low": low, "cl": cl, "cs": cs, "cr": cr, "cr_a": cr_a}


NIGHT = _k((5, 8, 32), (14, 19, 60), (34, 34, 92), (60, 70, 130), 0.08,
           (240, 170, 100), 0.50, (4, 6, 20),
           (62, 68, 108), (30, 34, 68), (96, 110, 160), 0.40)
DAY = _k((30, 98, 190), (80, 148, 216), (172, 208, 232), (255, 248, 230), 0.30,
         (255, 226, 160), 0.80, (52, 98, 152),
         (226, 233, 244), (150, 166, 194), (255, 252, 240), 0.25)
EVENING = [
    (-18.0, NIGHT),
    (-10.0, _k((6, 8, 30), (24, 24, 72), (80, 56, 110), (150, 90, 140), 0.20,
               (250, 170, 95), 0.60, (6, 6, 20),
               (62, 56, 98), (22, 22, 50), (170, 120, 140), 0.35)),          # dusk
    (-3.0, _k((14, 16, 52), (64, 40, 96), (196, 92, 94), (255, 120, 80), 0.45,
              (255, 160, 80), 0.85, (14, 10, 26),
              (128, 88, 112), (44, 34, 68), (240, 140, 104), 0.55)),         # late sunset
    (1.0, _k((28, 30, 84), (122, 70, 112), (252, 140, 92), (255, 150, 80), 0.65,
             (255, 175, 90), 1.00, (30, 20, 40),
             (196, 134, 122), (78, 56, 94), (255, 160, 110), 0.60)),         # sunset
    (7.0, _k((36, 70, 140), (130, 120, 150), (250, 184, 120), (255, 196, 110), 0.55,
             (255, 200, 115), 0.95, (40, 42, 72),
             (232, 200, 172), (110, 100, 134), (255, 196, 130), 0.50)),      # golden hour
    (20.0, DAY),
]
MORNING = [
    (-18.0, NIGHT),
    (-10.0, _k((6, 9, 32), (30, 34, 90), (96, 80, 136), (150, 120, 170), 0.20,
               (250, 180, 120), 0.60, (6, 7, 20),
               (68, 66, 108), (24, 26, 54), (200, 160, 170), 0.35)),         # dawn
    (-3.0, _k((14, 20, 62), (72, 64, 128), (220, 140, 136), (255, 160, 120), 0.45,
              (255, 190, 130), 0.80, (12, 12, 28),
              (150, 118, 140), (50, 44, 82), (250, 176, 140), 0.55)),
    (1.0, _k((24, 36, 92), (100, 86, 140), (248, 176, 136), (255, 196, 150), 0.60,
             (255, 200, 140), 0.95, (24, 22, 44),
             (222, 180, 162), (90, 82, 122), (255, 206, 160), 0.60)),        # sunrise
    (7.0, _k((34, 76, 150), (110, 130, 180), (244, 200, 160), (255, 220, 170), 0.50,
             (255, 214, 150), 0.90, (36, 50, 84),
             (238, 222, 206), (122, 124, 154), (255, 220, 170), 0.50)),      # morning gold
    (20.0, DAY),
]

# a season's touch on the sky (not the weather's): a tint, warmth (+ amber,
# − blue), brightness; the arc takes a third of it (it stays her warm gold)
SEASONS = {
    "spring": {"tint": (1.03, 0.98, 1.02), "warm": 0.04, "bright": 1.04},
    "summer": {"tint": (1.05, 1.00, 0.92), "warm": 0.14, "bright": 1.06},
    "autumn": {"tint": (1.08, 0.93, 0.86), "warm": 0.22, "bright": 0.94},
    "winter": {"tint": (0.88, 0.95, 1.12), "warm": -0.22, "bright": 0.92},
}
SEASON_DAY = (("winter", 15), ("spring", 105), ("summer", 197), ("autumn", 288))

# WMO code → cloud, fog, rain, snow, storm (0..1)
WEATHER = {0: (0, 0, 0, 0, 0), 1: (0.15, 0, 0, 0, 0), 2: (0.45, 0, 0, 0, 0),
           3: (0.85, 0, 0, 0, 0), 45: (0.5, 0.8, 0, 0, 0), 48: (0.5, 0.9, 0, 0, 0),
           51: (0.7, 0.1, 0.18, 0, 0), 53: (0.75, 0.1, 0.28, 0, 0), 55: (0.8, 0.1, 0.38, 0, 0),
           56: (0.75, 0.1, 0.28, 0.1, 0), 57: (0.8, 0.1, 0.38, 0.15, 0),
           61: (0.75, 0, 0.40, 0, 0), 63: (0.85, 0, 0.62, 0, 0), 65: (0.95, 0, 0.90, 0, 0),
           66: (0.8, 0, 0.45, 0.15, 0), 67: (0.9, 0, 0.75, 0.2, 0),
           71: (0.7, 0, 0, 0.35, 0), 73: (0.8, 0, 0, 0.6, 0), 75: (0.9, 0.1, 0, 0.9, 0),
           77: (0.75, 0, 0, 0.3, 0),
           80: (0.65, 0, 0.42, 0, 0), 81: (0.8, 0, 0.65, 0, 0), 82: (0.95, 0, 0.95, 0, 0),
           85: (0.7, 0, 0, 0.5, 0), 86: (0.9, 0, 0, 0.85, 0),
           95: (0.95, 0, 0.75, 0, 0.8), 96: (1.0, 0, 0.85, 0, 1.0), 99: (1.0, 0, 0.9, 0, 1.0)}

# the simulated words (tools/env_sim.py): the sun's height (° , rising?)
SIM_TIME = {"night": (-25.0, False), "dawn": (-9.0, True), "sunrise": (0.0, True),
            "morning": (12.0, True), "day": (35.0, True), "noon": (50.0, False),
            "golden": (6.0, False), "sunset": (0.0, False), "dusk": (-8.0, False)}
SIM_WEATHER = {"clear": 0, "partly": 2, "cloudy": 3, "fog": 45, "drizzle": 53,
               "light-rain": 61, "rain": 63, "heavy-rain": 65, "light-snow": 71,
               "snow": 73, "heavy-snow": 75, "storm": 95}
SIM_SEASON = dict(SEASON_DAY)


def _c(rgb):
    return tuple(v / 255.0 for v in rgb)


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


# ── the sun ───────────────────────────────────────────────────────────────
def sun_elevation(t, lat, lon):
    """The sun's height above the horizon (degrees) at epoch t (a standard
    low-precision formula, within a fraction of a degree)."""
    d = t / 86400.0 + 2440587.5 - 2451545.0
    g = math.radians((357.529 + 0.98560028 * d) % 360.0)
    q = (280.459 + 0.98564736 * d) % 360.0
    lam = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.00000036 * d)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = (18.697374558 + 24.06570982441908 * d) % 24.0
    ha = math.radians(gmst * 15.0 + lon) - ra
    la = math.radians(lat)
    s = math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def sky_key(elev, rising):
    """The palette at this height: the morning's and the evening's keys,
    each eased between its neighbours, blended by `rising` (0..1)."""
    def along(keys):
        if elev <= keys[0][0]:
            return keys[0][1]
        for (e0, k0), (e1, k1) in zip(keys, keys[1:]):
            if elev <= e1:
                t = _smooth((elev - e0) / (e1 - e0))
                return {n: (k0[n] + (k1[n] - k0[n]) * t) if isinstance(k0[n], float)
                        else _mix(k0[n], k1[n], t) for n in k0}
        return keys[-1][1]
    ev, mo = along(EVENING), along(MORNING)
    return {n: (ev[n] + (mo[n] - ev[n]) * rising) if isinstance(ev[n], float)
            else _mix(ev[n], mo[n], rising) for n in ev}


# ── the season ────────────────────────────────────────────────────────────
def season_weights(doy, south=False):
    """{season: weight} on day of the year `doy`, eased between the seasons'
    middles (the south: half a year on)."""
    if south:
        doy = (doy + 182) % 365
    marks = list(SEASON_DAY) + [(SEASON_DAY[0][0], SEASON_DAY[0][1] + 365)]
    if doy < marks[0][1]:
        doy += 365
    for (a, da), (b, db) in zip(marks, marks[1:]):
        if da <= doy < db:
            t = _smooth((doy - da) / (db - da))
            return {a: 1.0 - t, b: t} if a != b else {a: 1.0}
    return {"winter": 1.0}


def _season_mod(weights):
    tint, warm, bright = [0.0, 0.0, 0.0], 0.0, 0.0
    for name, w in weights.items():
        s = SEASONS[name]
        tint = [x + y * w for x, y in zip(tint, s["tint"])]
        warm += s["warm"] * w
        bright += s["bright"] * w
    return tuple(tint), warm, bright


def _warm(c, w):
    m = (1.0 + 0.10 * w, 1.0 + 0.01 * w, 1.0 - 0.16 * w) if w >= 0 else \
        (1.0 + 0.12 * w, 1.0 + 0.04 * w, 1.0 - 0.14 * w)
    return tuple(x * y for x, y in zip(c, m))


# ── the weather ───────────────────────────────────────────────────────────
def weather_of(sky):
    """weather.sky_now() → cloud, fog, rain, snow, storm, wind (km/h, its
    direction °, from); all 0 without one."""
    if not sky or sky.get("code") is None:
        return {"cloud": 0.0, "fog": 0.0, "rain": 0.0, "snow": 0.0, "storm": 0.0,
                "wind": 0.0, "wind_dir": 270.0}
    code = int(sky["code"])
    w = WEATHER.get(code)
    if w is None:
        w = (0.8, 0, 0, 0.5, 0) if 70 <= code < 80 else (0.8, 0, 0.5, 0, 0) if code >= 50 else (0.5, 0, 0, 0, 0)
    cloud, fog, rain, snow, storm = map(float, w)
    mm = sky.get("precip")
    if rain and mm:                           # a measured downpour: a little more
        rain = min(1.0, max(rain, 0.25 + mm / 6.0))
    return {"cloud": cloud, "fog": fog, "rain": rain, "snow": snow, "storm": storm,
            "wind": float(sky.get("wind") or 0.0), "wind_dir": float(sky.get("wind_dir") or 270.0)}


def compose(elev, rising, weights, wx):
    """The sun's height, the season's weights and the weather → the target
    (colours 0..1 and intensities), the one blend every combination comes from."""
    k = sky_key(elev, rising)
    tint, warm, bright = _season_mod(weights)
    b = TUNE["brightness"] * bright
    cloud, fog, rain, snow, storm = (wx[n] for n in ("cloud", "fog", "rain", "snow", "storm"))
    lum = lambda c: 0.30 * c[0] + 0.59 * c[1] + 0.11 * c[2]    # noqa: E731

    day = _smooth((elev + 4.0) / 14.0)

    def sky(c, amt=1.0):
        c = _c(c)
        c = _mix(c, tuple(x * y for x, y in zip(c, tint)), amt)
        c = _warm(c, warm * amt)
        g = lum(c)
        c = _mix(c, (g * 0.96, g * 0.98, g * 1.04),
                 (0.45 * cloud + 0.30 * rain) * (0.35 + 0.65 * day))               # muted
        c = tuple(x * (1.0 - 0.20 * cloud - 0.32 * rain ** 1.3 - 0.35 * storm) for x in c)
        c = _mix(c, tuple(x * y for x, y in zip(c, (0.84, 0.92, 1.16))),
                 0.55 * snow + 0.35 * storm + 0.25 * rain)                  # cool
        c = _mix(c, (g * 0.9 + 0.03, g * 0.92 + 0.035, g * 0.95 + 0.045), 0.35 * fog)
        return tuple(max(0.0, x * b) for x in c)

    def cloudc(c):                            # rain clouds darker, snow's cooler
        c = _c(c)
        c = _mix(c, tuple(x * y for x, y in zip(c, tint)), 0.5)
        g = lum(c)
        c = tuple(x * (1.0 - 0.80 * rain ** 1.3 - 0.30 * storm - 0.08 * cloud) for x in c)
        c = _mix(c, (g * 0.92, g * 0.97, g * 1.08), 0.35 * rain + 0.40 * snow)
        return tuple(max(0.0, x * b) for x in c)

    return {
        "cl": cloudc(k["cl"]), "cs": cloudc(k["cs"]), "cr": cloudc(k["cr"]),
        "cr_a": k["cr_a"] * (1.0 - 0.6 * rain) * (1.0 - 0.5 * fog) * (1.0 - 0.5 * _smooth((cloud - 0.6) / 0.3)),
        "zen": sky(k["zen"]), "mid": sky(k["mid"]), "hor": sky(k["hor"]),
        "sun": sky(k["sun"]), "sun_a": k["sun_a"] * (1.0 - 0.65 * cloud) * (1.0 - 0.4 * fog),
        "arc": sky(k["arc"], 0.33), "arc_a": k["arc_a"] * (1.0 - 0.30 * cloud) * (1.0 - 0.45 * fog)
        * (1.0 + 0.12 * (1.0 - cloud) * day),
        "low": sky(k["low"]),
        "cloud": cloud, "fog": fog, "rain": rain, "snow": snow, "storm": storm,
        "stars": TUNE["stars"] * (1.0 - _smooth((elev + 14.0) / 8.0)) * (1.0 - 0.7 * cloud) * (1.0 - fog),
        "elev": elev,
    }


def _wind_slant(wx):
    """Rain's lean: dx per px down (+ right), from the wind (blowing from
    `wind_dir`: from the west it leans right)."""
    s = max(0.0, min(1.0, wx["wind"] / 45.0)) * 0.38
    return -math.sin(math.radians(wx["wind_dir"])) * s


# ── the live state ────────────────────────────────────────────────────────
_EASED = ("zen", "mid", "hor", "sun", "sun_a", "arc", "arc_a", "low", "stars", "elev",
          "cl", "cs", "cr", "cr_a")
_WX = ("cloud", "fog", "rain", "snow", "storm", "slant", "drift")


class Env:
    """The eased state and the particles' clocks; one per face."""

    def __init__(self, wall=time.time):
        self.wall = wall
        self.cur = None
        self.target = None
        self.next_t = 0.0
        self.sim = None                    # (label, words) while simulated
        self.sim_mtime = None
        self.sim_check = 0.0
        self.sim_t0 = 0.0
        self.clk = [0.0, 0.0, 0.0, 0.0]    # rain, snow, haze, ripples (wrap at CLOCK_WRAP)
        self.phase = random.uniform(0.0, 300.0)
        self.asleep = 0.0
        self.flash, self.flash_t, self.flash_x, self.flash_next = 0.0, -99.0, 0.6, 0.0
        self.t_last = None
        n = len(TUNE["cloud_layers"])
        self.cdrift = [0.37 * i for i in range(n)]   # the cloud layers' drift, change (noise tiles)
        self.cev = [0.5 * i for i in range(n)]

    # the simulated state -------------------------------------------------
    def simulate(self, words):
        """A simulated state from words (SIM_TIME / SIM_WEATHER / SIM_SEASON,
        "HH:MM", "wind=30", "dir=270", "cycle=120": a day in 120 s); None or
        "" back to the real world. Returns the label it shows."""
        ws = (words or "").replace(",", " ").split() if isinstance(words, str) else list(words or ())
        self.sim = (" ".join(ws), ws) if ws else None
        self.sim_t0 = self.wall()
        self.next_t = 0.0
        return self.sim and self.sim[0]

    def _check_sim_file(self, mono):
        if mono < self.sim_check:
            return
        self.sim_check = mono + 2.0
        try:
            m = os.stat(SIM_FILE).st_mtime
        except OSError:
            if self.sim_mtime is not None:
                self.sim_mtime = None
                self.simulate(None)
                print("[env] back to the real time and weather", flush=True)
            return
        if m != self.sim_mtime:
            self.sim_mtime = m
            try:
                with open(SIM_FILE, encoding="utf-8") as f:
                    words = f.read().strip()
            except OSError:
                return
            print(f"[env] SIMULATED: {words or '(none)'}", flush=True)
            self.simulate(words)

    def label(self):
        """"SYMULACJA: noc deszcz" while simulated (the face shows it), else None."""
        return f"SYMULACJA: {self.sim[0]}" if self.sim else None

    # the targets ---------------------------------------------------------
    def _place(self):
        try:
            import weather
            p = weather._place()
            if p:
                return float(p[0]), float(p[1])
        except Exception:
            pass
        return HOME

    def _real_sky(self, t):
        try:
            import weather
            return weather.sky_now(t)
        except Exception:
            return None

    def _targets(self):
        t = self.wall()
        lat, lon = self._place()
        sky = None
        doy = time.localtime(t).tm_yday
        elev = rising = None
        if self.sim:
            for w in self.sim[1]:
                w = w.lower()
                if any(w.startswith(p) for p in ("wind=", "dir=", "cycle=")) or ":" in w:
                    try:
                        float(w.split("=")[1]) if "=" in w else [int(x) for x in w.split(":")]
                    except (ValueError, IndexError):
                        continue                  # (a mistyped word: left out)
                if w in SIM_TIME:
                    elev, r = SIM_TIME[w]
                    rising = 1.0 if r else 0.0
                elif w in SIM_WEATHER:
                    sky = dict(sky or {}, code=SIM_WEATHER[w])
                elif w in SIM_SEASON:
                    doy = SIM_SEASON[w]
                elif w.startswith("wind="):
                    sky = dict(sky or {}, wind=float(w[5:]))
                elif w.startswith("dir="):
                    sky = dict(sky or {}, wind_dir=float(w[4:]))
                elif w.startswith("cycle="):      # a whole day in this many seconds
                    per = max(10.0, float(w[6:]))
                    lt = time.localtime(t)
                    midnight = t - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
                    t = midnight + ((t - self.sim_t0) / per % 1.0) * 86400.0
                elif ":" in w:
                    h, m = w.split(":")
                    lt = time.localtime(t)
                    t = t - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec) + int(h) * 3600 + int(m) * 60
            if sky and sky.get("code") is None:
                sky["code"] = 0
        else:
            sky = self._real_sky(t)
        if elev is None:
            elev = sun_elevation(t, lat, lon)
            rising = 1.0 if sun_elevation(t + 600, lat, lon) > elev else 0.0
        wx = weather_of(sky)
        tg = compose(elev, rising, season_weights(doy, south=lat < 0), wx)
        tg["slant"] = _wind_slant(wx)
        # the clouds' drift: with the wind across (+ right), slow without one
        tg["drift"] = -math.sin(math.radians(wx["wind_dir"])) * (0.5 + min(1.5, wx["wind"] / 20.0))
        tg["moon_age"] = moon.age_at(t) / moon.SYNODIC         # 0 new, 0.5 full
        return tg

    # per frame ------------------------------------------------------------
    def frame(self, mono, w, h, fcx, fcy, asleep=False):
        """The shader's uniforms for this frame (cheap: easing and a few sines)."""
        dt = 0.0 if self.t_last is None else max(0.0, min(0.5, mono - self.t_last))
        self.t_last = mono
        self._check_sim_file(mono)
        cycling = bool(self.sim) and any(x.startswith("cycle=") for x in self.sim[1])
        if mono >= self.next_t:
            self.target = self._targets()
            self.next_t = mono + (0.25 if cycling else 20.0)
            if self.cur is None:
                self.cur = dict(self.target)
        tg, cur = self.target, self.cur
        sim = self.sim is not None
        kc = 1.0 - math.exp(-dt / (TUNE["ease_sim"] if sim or cycling else TUNE["ease"]))
        kw = 1.0 - math.exp(-dt / (TUNE["ease_sim"] if sim else TUNE["ease_weather"]))
        for n in _EASED:
            cur[n] = (cur[n] + (tg[n] - cur[n]) * kc) if isinstance(tg[n], float) \
                else _mix(cur[n], tg[n], kc)
        for n in _WX:
            cur[n] += (tg[n] - cur[n]) * kw
        self.asleep += ((1.0 if asleep else 0.0) - self.asleep) * (1.0 - math.exp(-dt / 3.0))
        mo = TUNE["motion"]
        # the clocks: rain falls faster as it pours (stepped here, so a change
        # of pace never moves a drop); they wrap where the shader's sway repeats
        for i, rate in enumerate((0.85 + 0.35 * cur["rain"], 0.9 + 0.2 * cur["snow"], 1.0, 1.0)):
            self.clk[i] = (self.clk[i] + dt * rate * mo) % CLOCK_WRAP
        self.phase += dt * mo
        ph = self.phase
        self._storm(mono, cur["storm"])
        dim = 1.0 - (1.0 - TUNE["asleep_dim"]) * self.asleep
        hy = h * TUNE["horizon"]
        # the arc: a circle through three points, breathing a few px over minutes
        (x1, y1), (x2, y2), (x3, y3) = ((x * w, y * h) for x, y in TUNE["arc_pts"])
        cx, cy, r = _circle((x1, y1), (x2, y2), (x3, y3))
        dr = TUNE["arc_drift"]
        cx += dr * math.sin(ph * 0.021)
        cy += dr * 0.6 * math.sin(ph * 0.017 + 1.3)
        r += dr * 0.5 * math.sin(ph * 0.013 + 2.1)
        a0 = math.atan2(y1 - cy, x1 - cx)
        a1 = math.atan2(y3 - cy, x3 - cx)
        if a1 < a0:                           # (one way round, through the middle point)
            a1 += math.tau
        # the sun's haze: at the horizon at sunrise and sunset, higher with the sun
        e = cur["elev"]
        sx, sy = w * TUNE["sun_x"], hy - (hy - 0.10 * h) * _smooth(e / 40.0)
        sun_a = cur["sun_a"] * _smooth((e + 9.0) / 9.0)
        night_glow = 0.10 * (1.0 - _smooth((e + 9.0) / 9.0))
        c = lambda v: tuple(x * dim for x in v)        # noqa: E731
        T = TUNE
        rain, snow = max(0.0, cur["rain"]), max(0.0, cur["snow"])
        hor = cur["hor"]
        rain_c = tuple((0.7 * a + 0.3 * b) * dim for a, b in zip((0.70, 0.76, 0.88), hor))
        night = 1.0 - _smooth((e + 10.0) / 6.0)
        mx, my = w * T["moon_pos"][0], h * T["moon_pos"][1]
        deck = _smooth((cur["cloud"] - 0.6) / 0.3)       # overcast
        clouds = self._clouds(dt * mo, w, h, cur, deck)
        moon_a = T["moon"] * night * (1.0 - cur["fog"]) * (1.0 - 0.7 * deck)
        out = {
            "uEnvOn": 1.0,
            "uEnvZen": c(cur["zen"]), "uEnvMid": c(cur["mid"]), "uEnvHor": c(cur["hor"]),
            "uEnvLow": c(cur["low"]),
            "uEnvSun": (*c(cur["sun"]), sun_a + night_glow),
            "uEnvSunP": (sx, sy, h * TUNE["sun_size"],
                         TUNE["face_shade"] * (1.0 - 0.45 * _smooth((e + 2.0) / 14.0))),
            "uEnvArc": (*c(cur["arc"]), cur["arc_a"] * (0.85 + 0.15 * math.sin(ph * 0.05))),
            "uEnvArcG": (cx, cy, r, ph * 0.045 % math.tau),
            "uEnvArcA": (a0, a1, TUNE["arc_width"], TUNE["arc_glow"]),
            "uEnvW": (cur["cloud"], cur["fog"], cur["rain"], cur["snow"]),
            "uEnvX": (self.flash, cur["slant"], self.flash_x * w, hy),
            # (with the sun low, clouds are lit from the side, not from above)
            "uEnvCl": (*c(cur["cl"]), 0.12 + 0.33 * _smooth((e - 3.0) / 15.0)),
            "uEnvCs": (*c(cur["cs"]), night),      # (at night the light on their tops only by the moon)
            "uEnvCr": (*c(cur["cr"]), cur["cr_a"]),
            "uEnvMoon": (mx, my, T["moon_r"], moon_a),
            "uEnvMoonC": c((0.94, 0.91, 0.80)),
            "uEnvMoonP": self._moon_phase(tg.get("moon_age", 0.3)),
            "uEnvClk": (*self.clk[:3], (0.35 + 0.55 * night) * (1.0 - deck)),   # (w: her middle cleared)
            # (gl_env.py: how many, opacity, length / size, speed)
            "uEnvRain": (T["rain_count"] * rain ** 1.3, T["rain_alpha"] * (0.6 + 0.4 * rain),
                         T["rain_len"], T["rain_speed"] * (0.85 + 0.3 * rain)),
            "uEnvRainC": rain_c,
            "uEnvSnow": (T["snow_count"] * snow ** 1.2, T["snow_alpha"], T["snow_size"],
                         T["snow_speed"]),
            "uEnvSnowC": c((0.86, 0.90, 1.0)),
            "uEnvStars": (T["star_count"] * min(1.0, cur["stars"] * 2.0), 0.95 * cur["stars"],
                          0.0, 0.0),
            "uEnvStarsC": c((0.85, 0.88, 1.0)),
            "uEnvMask": (fcx, fcy + 20.0, 330.0, 190.0),
        }
        out.update(clouds)
        return out

    @staticmethod
    def _moon_phase(age):
        """(the terminator: cos of its age, the lit side: +1 right waxing,
        -1 left waning, how full) — at least a sliver, never a new moon."""
        age = min(0.90, max(0.10, age))
        return (math.cos(math.tau * age), 1.0 if age < 0.5 else -1.0,
                0.5 - 0.5 * math.cos(math.tau * age))

    def _clouds(self, dt, w, h, cur, deck):
        """The cloud layers (gl_face's envLayer): each drifting at its own
        pace, its field changing slowly; more cover with more cloud, broad
        and denser when overcast, never one even grey."""
        cloud, fog = cur["cloud"], cur["fog"]
        out = {}
        for i, (y, hh, tx, ty, v, (lo, hi), c0, op, a0) in enumerate(TUNE["cloud_layers"]):
            self.cdrift[i] = (self.cdrift[i] - dt * v * cur["drift"] / (tx * w)) % 2.0
            self.cev[i] = (self.cev[i] + dt * 0.0010 * (1.0 + 0.25 * i)) % 2.0
            on = _smooth((cloud - lo) / (hi - lo))
            op = op * (a0 + (1.0 - a0) * on)
            op += max(0.0, 0.85 - op) * deck * (0.5 if i in (0, 3) else 1.0)
            out[f"uEnvCa[{i}]"] = (y * h, hh * h * (1.0 + 0.9 * deck), tx * w, ty * h)
            out[f"uEnvCb[{i}]"] = (self.cdrift[i], self.cev[i], c0 + (1.0 - c0) * on,
                                   op * (1.0 - 0.6 * fog))
        return out

    def _storm(self, mono, storm):
        """A rare, soft, far-away light at the horizon: rises in 0.2 s, fades in ~1.5 s."""
        if storm < 0.4:
            self.flash = 0.0
            return
        if mono >= self.flash_next:
            if self.flash_next:
                self.flash_t, self.flash_x = mono, random.uniform(0.1, 0.9)
            self.flash_next = mono + random.uniform(25.0, 70.0)
        el = mono - self.flash_t
        f = min(1.0, el / 0.2) * math.exp(-max(0.0, el - 0.2) / 0.6) if el < 3.0 else 0.0
        f += 0.5 * (min(1.0, (el - 0.45) / 0.15) * math.exp(-(el - 0.6) / 0.5) if 0.45 < el < 3.0 else 0.0)
        self.flash = 0.30 * storm * f


def _circle(a, b, c):
    (x1, y1), (x2, y2), (x3, y3) = a, b, c
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1)
          + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
    uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3)
          + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
    return ux, uy, math.hypot(x1 - ux, y1 - uy)


def _wrap(x, lo, hi):
    return lo + (x - lo) % (hi - lo)


_env = None


def enabled():
    """The sky behind her: Ustawienia → Asystent → Niebo w tle (on unless
    switched off there or by LUNA_ENV_BG=0)."""
    return os.environ.get("LUNA_ENV_BG", "1") != "0" and settings.get("sky_bg", True) is not False


def get():
    global _env
    if _env is None:
        _env = Env()
    return _env


def backdrop_light():
    """0..1: how light the sky is along the bottom of the screen (the dock's
    icons go bolder over it); 0 while no sky is on screen."""
    e = _env
    if e is None or e.cur is None or e.t_last is None or time.monotonic() - e.t_last > 1.0:
        return 0.0
    cur = e.cur
    lum = lambda c: 0.30 * c[0] + 0.59 * c[1] + 0.11 * c[2]    # noqa: E731
    sky = 0.7 * lum(cur["low"]) + 0.3 * lum(cur["hor"])
    sky += (lum(cur["cl"]) - sky) * min(1.0, 0.7 * cur["cloud"] + 0.5 * cur["fog"])
    return _smooth((sky - 0.12) / 0.25)


def sim_label():
    """The "SYMULACJA: …" line while a simulated sky is on screen, else None."""
    e = _env
    if e is None or e.t_last is None or time.monotonic() - e.t_last > 1.0:
        return None
    return e.label()
