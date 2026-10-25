"""
characters.py — the four drawn characters (PIP, RETRO, PIXEL, MOCHI) as
data, and the layer of expressions and gestures they share.

Luna and HAL are one face in two skins (gl_face's shader). These four are
built differently — a CRT console, a matrix of cells, a plush, neon
outlines — each by its own small shader in
gl_chars.py. They are driven by the same pose as Luna: face_spec's moods,
her blinks, gaze, saccades, reply scenes and her voice's visemes all arrive
as gl_face's uniforms (lids, pupils, mouth); a character only reinterprets
them. What this file adds on top, per character, from data:

  layout   — where its eyes and mouth sit and how big (gl_chars remaps them)
  spec     — face_spec settings over every mood (themes' "spec": the baseline)
  blink    — (pace, speed): ×how long between blinks, ×how fast a blink is
  gaze     — (range, spring, damping): how far and how bouncily the eyes move
  react    — 1/s: how fast its expression channels follow the mood
  stepped  — Hz: expression and mouth changes held in steps (pixel hardware)
  mouth    — (width, height, open) × the viseme's mouth; "levels": stepped
  accessories / acc_default — optional pieces, each on or off on its own

And the shared layer (CharLife): expression channels eased one by one
(happy, sad, angry, surprise, think, sleep, celebrate, alert, curious,
confused, listen, speak), gestures that drive their own channels with a
priority (an alert beats a nod; a nod doesn't touch the gaze), and each
character's signature habits. Deterministic with seed() and a fake clock.

Pure Python: no pygame, no GL — the unit tests read it.
"""

import math
import random
import re
import time

import settings

KINDS = ("retro", "pixel", "mochi", "pip")

# the expressions the characters show (the app's moods map onto them; the
# last five come from gestures: reply scenes, a touch, trigger())
EXPRESSIONS = ("neutral", "happy", "curious", "listening", "thinking", "speaking",
               "confused", "sad", "angry", "surprised", "celebrating", "sleeping",
               "processing", "alert")

CHARS = {
    # ── a 1980s console: amber pixel eyes on a dark CRT in a beige case ──
    "retro": {
        "pal": ((1.0, 0.62, 0.14), (0.93, 0.86, 0.72), (0.15, 0.14, 0.13), (0.86, 0.20, 0.14)),
        "layout": {"eye_x": 104.0, "eye_y": -40.0, "eye_s": 0.66, "mouth_y": 66.0, "mouth_s": 0.78},
        "layout_face": {"eye_x": 145.0, "eye_y": -40.0, "eye_s": 0.86, "mouth_y": 98.0,
                        "mouth_s": 1.0},
        "spec": {"eye_n": 8.0, "brow_a": 0.0, "blush": 0.0, "round": 0.0},
        "blink": (1.1, 1.4), "gaze": (0.9, 0.0, 0.0), "react": 10.0, "stepped": 12.0,
        "mouth": {"w": 0.9, "h": 0.9, "levels": 4},
        "accessories": ("cartridge", "glasses", "rocket"),
        "acc_default": ("cartridge",),
    },
    # ── a pure matrix of luminous cells ──
    "pixel": {
        "pal": ((0.20, 0.85, 1.0), (0.18, 0.36, 1.0), (1.0, 0.22, 0.62), (1.0, 0.70, 0.18)),
        "layout": {"eye_x": 150.0, "eye_y": -40.0, "eye_s": 0.80, "mouth_y": 100.0, "mouth_s": 0.9},
        "spec": {"eye_n": 6.0, "brow_a": 0.0, "blush": 0.0},
        "blink": (1.0, 1.3), "gaze": (1.0, 0.0, 0.0), "react": 12.0, "stepped": 10.0,
        "mouth": {"w": 1.0, "h": 1.0, "levels": 4},
        "accessories": ("hearts", "stars", "bubble", "headphones"),
        "acc_default": ("hearts", "stars", "bubble", "headphones"),
    },
    # ── a plush bunny round a dark display (her ears, paws, glyphs: mochi_rig.py) ──
    "mochi": {
        "pal": ((0.99, 0.78, 0.85), (0.90, 0.54, 0.66), (1.0, 0.96, 0.98), (1.0, 0.42, 0.64)),
        # her eyes: soft ovals ~1.2× taller than wide; a mood's taller eyes
        # only partly taller (eye_h_give), never past eye_h_max (the glass's edge)
        "layout": {"eye_x": 100.0, "eye_y": 40.0, "eye_s": 0.485, "eye_sy": 0.79,
                   "eye_h_give": 0.6, "eye_h_max": 1.08, "mouth_y": 98.0, "mouth_s": 0.36},
        "spec": {"eye_n": 2.1, "brow_a": 0.0, "pupil": (0.0, 0.0)},
        "blink": (1.0, 0.9), "gaze": (0.7, 0.0, 0.0), "react": 7.0,
        "mouth": {"w": 0.6, "h": 0.7},
        "accessories": ("ears", "flower", "hat", "hearts"),
        "acc_default": ("ears", "flower", "hat", "hearts"),
    },
    # ── an energetic neon mascot: outlined eyes, dot pupils ──
    "pip": {   # (a wrist computer's phosphor green, nearly one hue; its sync slips)
        "pal": ((0.22, 1.0, 0.42), (0.55, 1.0, 0.62), (0.12, 0.72, 0.34), (0.86, 1.0, 0.72)),
        "layout": {"eye_x": 150.0, "eye_y": -32.0, "eye_s": 0.84, "mouth_y": 112.0, "mouth_s": 0.7},
        "spec": {"eye_n": 4.0, "brow_a": 0.0, "blush": 0.0},
        "blink": (0.9, 1.2), "gaze": (1.1, 260.0, 9.0), "react": 14.0,
        "mouth": {"w": 0.8, "h": 0.9},
        "accessories": ("sprout", "cap", "bowtie"),
        "acc_default": ("sprout",),
    },
}

# the settings page's choices for a character's accessories (each a set
# that can be on alone): all of them, one at a time, none
def acc_choices(kind):
    acc = CHARS[kind]["accessories"]
    out = [tuple(CHARS[kind]["acc_default"]), acc]
    out += [(a,) for a in acc]
    out.append(())
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


ACC_LABELS = {"cartridge": "kartridż", "glasses": "okulary", "rocket": "rakieta",
              "hearts": "serca", "stars": "gwiazdki", "bubble": "dymek",
              "headphones": "słuchawki", "ears": "uszy", "flower": "kwiatek",
              "hat": "czapka do snu", "sprout": "kiełek", "cap": "czapka",
              "bowtie": "muszka"}

FX_LEVELS = (("full", "pełne", 1.0), ("calm", "spokojne", 0.5), ("off", "wyłączone", 0.0))


# ── settings (data/settings.json), read once a second: the face asks every frame
_scache = {}


def _setting(key, default, now=None):
    now = now or time.monotonic()
    hit = _scache.get(key)
    if hit and now - hit[0] < 1.0:
        return hit[1]
    v = settings.get(key, default)
    _scache[key] = (now, v)
    return v


def accessories(kind, now=None):
    """The accessories switched on for a character (a tuple of names)."""
    chosen = (_setting("char_acc", {}, now) or {}).get(kind)
    if chosen is None:
        return tuple(CHARS[kind]["acc_default"])
    return tuple(a for a in chosen if a in CHARS[kind]["accessories"])


def set_accessories(kind, names):
    acc = dict(settings.get("char_acc", {}) or {})
    acc[kind] = [a for a in names if a in CHARS[kind]["accessories"]]
    settings.put("char_acc", acc)
    _scache.clear()


# "zdejmij czapkę", "załóż okulary" — the settings page's Dodatki row by voice
# (22 Oct 23:45: a "zdejmij …" got "Gotowe." and nothing changed)
_ACC_ON = re.compile(r"^(?:załóż|zaloz|włóż|wloz|nałóż|naloz|ubierz|dodaj|daj)\s+(?:sobie\s+)?(.{3,40})$")
_ACC_OFF = re.compile(r"^(?:zdejmij|zdejm|ściągnij|sciagnij|schowaj|zabierz|usuń|usun)\s+(?:sobie\s+)?(.{3,40})$")
_ALL = re.compile(r"^(?:wszystko|wszystkie(?:\s+dodatki)?|dodatki|ozdoby)$")


def _same_word(a, b):
    n = max(3, min(len(a), len(b), 6) - 1)
    return a[:n] == b[:n]


def voice_accessory(kind, text):
    """What "zdejmij czapkę" asks of the character `kind`: (new set, what to
    say), or None when it isn't about its accessories."""
    low = re.sub(r"^(?:a\s+|no\s+|to\s+)?(?:\w+,\s+)?", "", (text or "").lower().strip(" .!?"))
    on, off = _ACC_ON.match(low), _ACC_OFF.match(low)
    if not (on or off) or kind not in CHARS or re.search(r"list|zakup|plan|ulubion", low):
        return None                        # "dodaj czapkę do listy zakupów"
    what = (on or off).group(1)
    have = CHARS[kind]["accessories"]
    cur = list(accessories(kind))
    if _ALL.match(what):
        return (list(have), "Proszę, wszystkie dodatki.") if on else ([], "Gotowe, bez dodatków.")
    words = re.findall(r"[^\W\d_]{3,}", what)
    hit = [a for a in have if words and any(_same_word(w, l) for w in words
                                            for l in ACC_LABELS[a].split() if len(l) > 3)]
    if not hit:
        anyone = any(any(_same_word(w, l) for w in words for l in ACC_LABELS[a].split() if len(l) > 3)
                     for c in CHARS.values() for a in c["accessories"])
        if not anyone:
            return None                    # "zdejmij buty", "usuń listę" — not hers
        return cur, "Tego nie noszę. Mogę mieć: " + ", ".join(ACC_LABELS[a] for a in have) + "."
    if on:
        new = cur + [a for a in hit if a not in cur]
        return new, ("Już mam." if new == cur else "Proszę!")
    new = [a for a in cur if a not in hit]
    return new, ("Gotowe." if new != cur else "Przecież tego nie mam.")


def retro_console(now=None):
    """RETRO in its whole console (True) or just its screen's face."""
    return _setting("retro_mode", "console", now) != "face"


def fx_level(now=None):
    """Motion, glow and particles: 1 full, 0.5 calm, 0 off."""
    want = _setting("char_fx", "full", now)
    return next((v for k, _, v in FX_LEVELS if k == want), 1.0)


def kind_of(theme):
    """The character's kind for a theme's dict (None: Luna's skins)."""
    k = (theme or {}).get("char")
    return k if k in CHARS else None


def theme_spec(kind):
    """What themes.py lays over every mood for this character."""
    return dict(CHARS[kind]["spec"])


# ── gestures: (seconds, priority, the channels they drive) ────────────────
GESTURES = {
    "nod": (0.9, 1, ("body_y",)),
    "shake": (0.9, 1, ("body_x",)),
    "celebrate": (1.8, 1, ("body_y", "celebrate")),
    "confused": (2.4, 1, ("body_rot", "confused")),
    "curious": (2.2, 1, ("body_rot", "curious", "gaze")),
    "think": (2.5, 0, ("think",)),
    "look_around": (2.6, 0, ("gaze",)),
    "alert": (1.6, 3, ("body_y", "alert", "gaze")),
    "interrupt": (0.7, 2, ("body_y", "alert")),
    "glitch": (0.45, 1, ("glitch",)),
}

# the app's reply scenes (reply_scenes.py) → the gesture a character makes
SCENE_GESTURE = {
    "laugh": "celebrate", "dance": "celebrate", "clap": "celebrate", "proud": "celebrate",
    "sparkle_eyes": "celebrate", "music_notes": "celebrate", "wave_both": "celebrate",
    "lightbulb": "nod", "ok_sign": "nod", "salute": "nod", "relief": "nod", "remember": "nod",
    "thumbs_down": "shake", "impatient": "shake", "eye_roll": "shake",
    "curious": "curious", "suspicious": "curious",
    "think_bubble": "think", "chin_rest": "think",
    "scratch_head": "confused", "dizzy": "confused",
    "scared": "alert", "snap": "alert", "lost_signal": "alert",
    "glitch": "glitch",
}

_pending = []                    # gestures asked for from outside (trigger)


def trigger(name):
    """Ask the drawn character for a gesture (tests, the demo, other modules).
    Kept a second: one asked for while Luna's own face is up doesn't wait
    for the next character."""
    if name in GESTURES:
        _pending.append((name, time.monotonic()))


def _bump(el, dur):
    """0 → 1 → 0 over dur, smooth at both ends."""
    if not 0.0 <= el < dur:
        return 0.0
    return math.sin(math.pi * el / dur) ** 2


def gesture_value(name, el):
    """(channel → value) of a gesture el seconds in."""
    dur = GESTURES[name][0]
    env = _bump(el, dur)
    if env <= 0.0:
        return {}
    x = el / dur
    if name == "nod":
        return {"body_y": 12.0 * math.sin(x * 4.0 * math.pi) * env}
    if name == "shake":
        return {"body_x": 16.0 * math.sin(x * 6.0 * math.pi) * env}
    if name == "celebrate":
        return {"body_y": -18.0 * abs(math.sin(x * 3.0 * math.pi)) * env, "celebrate": env}
    if name == "confused":
        return {"body_rot": 0.07 * env, "confused": env}
    if name == "curious":
        return {"body_rot": -0.045 * env, "curious": env, "gaze": (10.0 * env, -12.0 * env)}
    if name == "think":
        return {"think": env}
    if name == "look_around":
        return {"gaze": (46.0 * math.sin(x * 2.0 * math.pi) * env, -6.0 * env)}
    if name == "alert":
        jolt = math.exp(-el * 9.0) * min(1.0, el * 30.0)
        return {"body_y": -10.0 * jolt, "alert": env, "gaze": (0.0, -4.0 * env)}
    if name == "interrupt":
        return {"body_y": 7.0 * env, "alert": 0.6 * env}
    if name == "glitch":
        return {"glitch": 1.0 if env > 0.05 else 0.0}
    return {}


class CharLife:
    """The shared expression and gesture state of the drawn character on
    screen: channels eased one by one, gestures in their own channels,
    the character's signature habits. One per GLFace; reset on a switch."""

    CHANNELS = ("happy", "sad", "angry", "surprise", "think", "sleep", "celebrate",
                "alert", "curious", "confused", "listen", "speak", "glitch")

    def __init__(self, kind, now, rng=None):
        self.kind = kind
        self.cfg = CHARS[kind]
        self.rng = rng or random.Random()
        self.ch = dict.fromkeys(self.CHANNELS, 0.0)
        self.active = {}                     # gesture → its start
        self.scene_prev = None
        self.emo_prev = None
        self.boot_t = now                    # RETRO: the CRT starts up
        self.step_t = -9.0                   # stepped characters: the last step
        self.held = dict(self.ch)
        self.gaze = [[0.0, 0.0], [0.0, 0.0]]     # PIP's springs: per eye
        self.gaze_v = [[0.0, 0.0], [0.0, 0.0]]
        self.roll_t = now + self.rng.uniform(15.0, 30.0)  # RETRO: a rolling scanline
        self.sync_t = now + self.rng.uniform(4.0, 9.0)    # PIP: the sync slips now and then
        self.sync_at = -9.0
        self.sync_seed = 0.0
        self.roll_at = -9.0
        self.glitch_t = now + self.rng.uniform(2.0, 4.0)  # PIXEL: cross → glitches
        self.slow = 0.0                      # frame time too long: effects step down
        self.quality = 1.0
        self.was_asleep = False
        self.mouth_lvl = 0.0

    # ── gestures ──
    def start(self, name, now):
        """Start a gesture. One already running in the same channel with a
        higher priority wins those channels; the rest go on untouched."""
        if name in GESTURES:
            self.active[name] = now

    def resolve(self, now):
        """channel → value from the gestures running: the highest priority
        (then the newest) per body/gaze channel; expression channels: the
        largest."""
        best, out = {}, {}
        for name, t0 in list(self.active.items()):
            dur, prio, _ = GESTURES[name]
            if now - t0 >= dur:
                del self.active[name]
                continue
            for k, v in gesture_value(name, now - t0).items():
                if k in ("body_x", "body_y", "body_rot", "gaze"):
                    cur = best.get(k)
                    if cur is None or (prio, t0) > cur[0]:
                        best[k] = ((prio, t0), v)
                else:
                    out[k] = max(out.get(k, 0.0), v)
        for k, (_, v) in best.items():
            out[k] = v
        return out

    def events(self, face, now):
        """Gestures from what the app is doing: a reply scene starting, a
        mood arriving, a poke while she talks, a trigger()."""
        scene = getattr(face, "_scene_name", None)
        if scene and scene != self.scene_prev and scene in SCENE_GESTURE:
            self.start(SCENE_GESTURE[scene], now)
        self.scene_prev = scene
        emo = getattr(face, "_emotion", "neutral")
        if emo != self.emo_prev:
            if emo == "excited" and self.emo_prev is not None:
                self.start("celebrate", now)
            self.emo_prev = emo
        gest = getattr(face, "_gesture", None)        # robot_face's own nod / shake
        if gest != getattr(self, "gest_prev", None) and gest in ("nod", "shake"):
            self.start(gest, now)
        self.gest_prev = gest
        if (getattr(face, "_touch_kind", None) == "multi" and getattr(face, "_speaking", False)
                and time.time() - getattr(face, "_touch_react_t", -99.0) < 0.1):
            self.start("interrupt", now)
        while _pending:
            name, at = _pending.pop(0)
            if time.monotonic() - at < 1.0:
                self.start(name, now)

    # ── per frame ──
    def step(self, face, cur, now, dt):
        """The expression channels and the gestures' values for this frame."""
        self.events(face, now)
        g = self.resolve(now)
        emo = getattr(face, "_emotion", "neutral")
        talking = bool(getattr(face, "_speaking", False))
        tgt = {
            "happy": 1.0 if emo in ("happy", "excited", "love") else 0.0,
            "sad": 1.0 if emo == "sad" else 0.0,
            "angry": max(1.0 if emo == "angry" else 0.0, min(1.0, cur.get("tint", 0.0) * 1.6)),
            "surprise": 1.0 if emo == "surprised" else 0.0,
            "think": max(1.0 if emo == "thinking" else 0.0, g.get("think", 0.0)),
            "sleep": 1.0 if emo == "sleeping" else 0.0,
            "celebrate": max(0.6 if emo == "excited" else 0.0, g.get("celebrate", 0.0)),
            "alert": g.get("alert", 0.0),
            "curious": g.get("curious", 0.0),
            "confused": g.get("confused", 0.0),
            "listen": 1.0 if getattr(face, "_listen", False) and not talking else 0.0,
            "speak": 1.0 if talking else 0.0,
            "glitch": g.get("glitch", 0.0),
        }
        if self.kind == "pixel" and now > self.glitch_t:     # cross or giggling: glitches
            self.glitch_t = now + self.rng.uniform(2.0, 4.5)
            if emo == "angry" or getattr(face, "_scene_name", None) in ("laugh", "dance"):
                self.start("glitch", now)
        k = 1.0 - math.exp(-self.cfg["react"] * max(0.0, min(dt, 0.25)))
        for c, v in tgt.items():
            fast = c in ("glitch", "speak")
            self.ch[c] += (v - self.ch[c]) * (1.0 if fast else k)
        hz = self.cfg.get("stepped")
        if hz:                                    # pixel hardware: changes in steps
            if now - self.step_t >= 1.0 / hz:
                self.step_t = now
                self.held = dict(self.ch)
            out = dict(self.held)
            out["glitch"], out["speak"] = self.ch["glitch"], self.ch["speak"]
        else:
            out = dict(self.ch)
        lvl = fx_level(now)
        out["motion"] = lvl * (1.0 - 0.6 * out["alert"])     # an alert stills the idle sway
        out["body_x"] = g.get("body_x", 0.0) * max(0.3, lvl)
        out["body_y"] = g.get("body_y", 0.0) * max(0.3, lvl)
        out["body_rot"] = g.get("body_rot", 0.0) * max(0.3, lvl)
        out["gaze"] = g.get("gaze", (0.0, 0.0))
        self.quality_step(dt, getattr(face, "fps", 30) or 30)
        out["fx"] = lvl * self.quality
        # RETRO: its CRT starts up when chosen and on waking; a scanline rolls now and then
        asleep = emo == "sleeping"
        if self.was_asleep and not asleep:
            self.boot_t = now
        self.was_asleep = asleep
        out["crt"] = max(0.0, min(1.0, (now - self.boot_t) / 1.1)) if self.kind == "retro" else 1.0
        if self.kind == "retro" and now > self.roll_t:
            self.roll_t = now + self.rng.uniform(15.0, 30.0)
            if not asleep and lvl > 0.0:
                self.roll_at = now
        out["roll"] = max(0.0, 1.0 - (now - self.roll_at) / 0.5) if now >= self.roll_at else 0.0
        out["mic"] = max(0.0, min(1.0, float(getattr(face, "_mic", 0.0) or 0.0)))
        waking = getattr(face, "wake_anim", 0) and getattr(face, "wake_anim", 0) == getattr(
            face, "_WAKE_ACTIVE", -1)
        out["wake"] = max(0.0, min(1.0, float(getattr(face, "wake_ripple", 1.0)))) if waking else 1.0
        if self.kind == "pip":
            out["sync"], out["seed"] = self.sync(now, out, lvl)
        return out

    def quality_step(self, dt, fps):
        """Frames coming much slower than asked for 4 s: drop the optional
        effects (they come back after 20 s of good frames)."""
        late = dt > 1.6 / max(8, fps) and dt < 0.5
        self.slow = max(-20.0, min(4.0, self.slow + (dt if late else -dt * 0.2)))
        if self.slow >= 4.0:
            self.quality = 0.0
        elif self.slow <= -20.0 + 1e-6:
            self.quality = 1.0

    def gaze_filter(self, i, dx, dy, dt, asleep):
        """A character's own gaze: PIP's bouncy spring."""
        rng, spring, damp = self.cfg["gaze"]
        dx, dy = dx * rng, dy * rng
        gz, gv = self.gaze[i], self.gaze_v[i]
        if spring > 0.0:
            n = max(1, min(40, int(math.ceil(min(dt, 0.25) / 0.005))))
            h = min(dt, 0.25) / n
            sp = spring * (0.35 if asleep else 1.0)
            for _ in range(n):
                for j, t in ((0, dx), (1, dy)):
                    gv[j] += ((t - gz[j]) * sp - gv[j] * damp) * h
                    gz[j] += gv[j] * h
            return gz[0], gz[1]
        return dx, dy

    SYNC_SECS = 0.42

    def sync(self, now, ch, lvl):
        """PIP: (how badly the sync slips, a seed for where). Every 8-20 s,
        every 2-4 s when cross; at once on an alert, a surprise, a glitch,
        waking. Half as much on "spokojne", none with the effects off."""
        if lvl <= 0.0:
            return 0.0, 0.0
        if now - self.sync_at > self.SYNC_SECS and (
                ch["alert"] > 0.5 or ch["glitch"] > 0.5 or 0.0 < ch["wake"] < 0.2
                or (ch["surprise"] > 0.6 and now - self.sync_at > 3.0)):
            self.sync_at = now
        if now > self.sync_t:
            cross = ch["angry"] > 0.5
            self.sync_t = now + (self.rng.uniform(2.0, 4.0) if cross else self.rng.uniform(8.0, 20.0))
            if ch["sleep"] < 0.5:
                self.sync_at = now
        el = now - self.sync_at
        if not 0.0 <= el < self.SYNC_SECS:
            return 0.0, self.sync_seed
        step = math.floor(el / 0.06)                       # it jumps in steps, like a signal
        self.sync_seed = float((int(self.sync_at * 100) * 31 + step * 7) % 997)
        env = math.sin(math.pi * el / self.SYNC_SECS) ** 0.5
        flick = 0.45 + 0.55 * ((step * 0.618) % 1.0)
        return min(1.0, env * flick) * (1.0 if lvl >= 1.0 else 0.5), self.sync_seed

    def mouth_step(self, open_):
        """RETRO and PIXEL: the mouth opens in a few steps, not smoothly."""
        n = self.cfg.get("mouth", {}).get("levels")
        if not n:
            return open_
        return math.floor(max(0.0, min(1.0, open_)) * n + 0.5) / n


def mouth_scale(kind):
    m = CHARS[kind].get("mouth", {})
    return m.get("w", 1.0), m.get("h", 1.0), m.get("open", 1.0)


def blink_pace(kind):
    """(×time between blinks, ×blink speed) — robot_face's blinks."""
    return CHARS[kind]["blink"] if kind in CHARS else (1.0, 1.0)


def current_kind():
    """The drawn character now, or None (Luna, HAL)."""
    import themes
    return kind_of(themes.get())
