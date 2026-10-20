"""
face_spec.py — what each of Luna's moods looks like, as numbers.

The GPU face (gl_face.py) draws one character: two eyes with real lids, an
iris and a pupil, two brows and a mouth. A mood is not a drawing but a set of
settings for those parts — how far each upper lid comes down and at what
angle, how far the lower lid pushes up (a smile reaches the eyes), where the
brows sit, which mouth. gl_face eases from one set to the next, and the live
animation (blinks, gaze, squints from reply scenes, the mouth while she
talks) is laid on top. Pure Python: no pygame, no GL — the unit tests read it.

Layers, bottom to top: the mood (MOODS, neutral for an unknown one);
listening, over a calm mood; what the reply scene playing sets
(reply_scenes' face(), into face._spec_mod); a costume's (gl_face's
COSTUME_SPEC — googly eyes). Then the live animation: blinks and squints
close the lids, the gaze moves the irises, her voice opens the mouth.

Per-eye values are (left, right) pairs — that is where a mood is lopsided
(thinking: one brow up, one eye narrowed). Units: eye sizes and brow / mouth
offsets in screen pixels (the 800×480 face); lids as a share of the eye's
height; the lid tilt as a share of the height (+: the inner corner lower).
"""

import math

# mouth kinds (the shader's uMouthK.w)
LINE, OPEN, O, GRIN, GRIT, WAVY = 0, 1, 2, 3, 4, 5

# ── the layout: one face, every mood ───────────────────────────────────────
# Relative to the face's centre (robot_face: fcx, fcy — 400, 212 on the
# 800×480 panel, moving with the head). Everything is placed from here: the
# eyes (and the brows over them), the mouth, and the anchors the props and
# costumes hang from. No plate behind them: they float (15 Oct, pass 3).
LAYOUT = {
    "eye_x": 158.0,               # each eye's centre, left and right of the middle
    "eye_y": -30.0,               # …and their baseline
    "mouth_y": 120.0,             # the mouth's centre
    "nose_y": 84.0,               # costumes: the nose between the eyes and the mouth
    "prop": (232.0, -150.0),      # props of a reply (weather, an idea): above, right
    "chin": (112.0, 196.0),       # a finger on the chin (thinking)
}

BASE = {
    "eye_w": 232.0, "eye_h": 172.0, "eye_dy": 0.0,
    "eye_n": 3.4,                 # the eye's shape: a squircle, 2 round … 4 squarer
    "lid_top": (0.0, 0.0),        # how far the upper lid is down (0..1 of the height)
    "lid_tilt": (0.0, 0.0),       # + its inner end lower (cross), − its outer end (sad)
    "lid_bend": (0.08, 0.08),     # + its edge arched up in the middle
    "lid_bot": (0.0, 0.0),        # how far the lower lid is up
    "lid_bot_bend": (0.0, 0.0),   # + pushed up in the middle (a smile reaching the eyes)
    "rot": (0.0, 0.0),            # the eye turned (degrees, + the inner end down)
    "pupil": (1.0, 1.0),          # the iris's size
    "gaze_x": 0.0, "gaze_y": 0.0,  # where she looks, on top of the face tracking (px)
    "star": 0.0, "heart": 0.0, "wet": 0.0, "round": 0.0,
    "brow_y": (0.0, 0.0),         # px up
    "brow_tilt": (0.0, 0.0),      # px: + the inner end down
    "brow_bend": 6.0, "brow_a": 1.0, "brow_gap": 24.0,
    "mouth": LINE, "mouth_w": 160.0, "mouth_h": 17.0, "mouth_bend": 14.0,
    "mouth_slant": 0.0, "mouth_dx": 0.0, "mouth_dy": 0.0, "mouth_a": 1.0,
    "blush": 0.0, "tint": 0.0,
}

MOODS = {
    # relaxed, open, a small smile
    "neutral": {},
    # the cheeks lift the lower lids, a broad open smile
    "happy": {"eye_w": 238.0, "eye_h": 178.0, "eye_n": 3.0,
              "lid_top": (0.04, 0.04), "lid_bot": (0.20, 0.20), "lid_bot_bend": (0.22, 0.22),
              "gaze_y": -8.0, "brow_y": (10.0, 10.0), "brow_bend": 12.0,
              "mouth": GRIN, "mouth_w": 192.0, "mouth_h": 50.0,
              "blush": 0.55},
    # bigger, rounder eyes with a star in each, brows up, a wide open grin
    "excited": {"eye_w": 248.0, "eye_h": 200.0, "eye_n": 2.6,
                "lid_bot": (0.06, 0.06), "lid_bot_bend": (0.12, 0.12),
                "pupil": (1.2, 1.2), "star": 1.0, "gaze_y": -6.0,
                "brow_y": (18.0, 18.0), "brow_bend": 14.0,
                "mouth": GRIN, "mouth_w": 204.0, "mouth_h": 76.0,
                "blush": 0.6},
    # hearts for eyes, soft raised brows, a smile, rosy cheeks
    "love": {"eye_w": 236.0, "eye_h": 192.0, "heart": 1.0, "eye_n": 3.0,
             "brow_y": (12.0, 12.0), "brow_bend": 10.0, "brow_a": 0.8,
             "mouth_w": 182.0, "mouth_h": 17.0, "mouth_bend": 28.0,
             "blush": 0.95},
    # the outer lids droop, the inner brows go up, big wet eyes looking down,
    # the mouth turned right down
    "sad": {"eye_w": 214.0, "eye_h": 166.0,
            "lid_top": (0.28, 0.28), "lid_tilt": (-0.32, -0.32), "lid_bend": (0.02, 0.02),
            "pupil": (1.14, 1.14), "wet": 1.0, "gaze_y": 14.0,
            "brow_y": (4.0, 4.0), "brow_tilt": (-22.0, -22.0), "brow_bend": -2.0,
            "mouth_w": 156.0, "mouth_h": 17.0, "mouth_bend": -26.0, "mouth_dy": 10.0},
    # narrowed: the lids come down at the inner corners, the brows a steep
    # "\ /" pressed onto them, the teeth gritted, a red heat
    "angry": {"eye_w": 230.0, "eye_h": 152.0, "eye_n": 4.0,
              "lid_top": (0.26, 0.26), "lid_tilt": (0.44, 0.44), "lid_bend": (0.0, 0.0),
              "lid_bot": (0.10, 0.10), "pupil": (0.84, 0.84),
              "brow_y": (-12.0, -12.0), "brow_tilt": (28.0, 28.0), "brow_bend": -3.0,
              "brow_gap": 16.0,
              "mouth": GRIT, "mouth_w": 146.0, "mouth_h": 34.0,
              "tint": 0.55},
    # round wide eyes with small pupils, brows high, a round open mouth
    "surprised": {"eye_w": 214.0, "eye_h": 214.0, "round": 1.0, "pupil": (0.72, 0.72),
                  "brow_y": (16.0, 16.0), "brow_bend": 12.0, "brow_gap": 20.0,
                  "mouth": O, "mouth_w": 74.0, "mouth_h": 74.0},
    # lopsided: one eye narrowed, the other open under a raised brow, eyes up
    # and to the side, a small mouth pulled to one side
    "thinking": {"eye_w": 222.0, "eye_h": 170.0,
                 "lid_top": (0.30, 0.0), "lid_bend": (0.0, 0.08), "lid_bot": (0.12, 0.0),
                 "gaze_x": 28.0, "gaze_y": -24.0,
                 "brow_y": (-6.0, 20.0), "brow_tilt": (8.0, -6.0), "brow_bend": 8.0,
                 "mouth_w": 88.0, "mouth_h": 15.0, "mouth_bend": -2.0, "mouth_slant": 6.0,
                 "mouth_dx": -40.0},              # (the finger is on the right)
    # the lids shut in a soft "‿", relaxed low brows, a small calm mouth
    "sleeping": {"eye_w": 222.0, "eye_h": 140.0, "eye_dy": 10.0,
                 "lid_top": (0.62, 0.62), "lid_bend": (-0.28, -0.28),
                 "lid_bot": (0.38, 0.38), "lid_bot_bend": (-0.28, -0.28),
                 "brow_a": 0.45, "brow_y": (-12.0, -12.0), "brow_bend": 2.0,
                 "mouth_w": 82.0, "mouth_h": 13.0, "mouth_bend": 6.0, "mouth_a": 0.6,
                 "blush": 0.25},
    # attentive: a touch wider, looking straight at you, brows up a little
    "listening": {"eye_w": 236.0, "eye_h": 182.0, "pupil": (1.08, 1.08), "gaze_y": -4.0,
                  "brow_y": (10.0, 10.0), "brow_bend": 8.0,
                  "mouth_w": 112.0, "mouth_h": 16.0, "mouth_bend": 10.0, "mouth_a": 0.9},
}


def spec(mood, listening=False):
    """The full settings for a mood (unknown moods: neutral). Listening is
    laid over a calm face (neutral / thinking), not over a strong mood."""
    s = dict(BASE)
    s.update(MOODS.get(mood) or {})
    if listening and mood in ("neutral", "listening", None):
        s.update(MOODS["listening"])
    return s


def eye_size(mood, listening=False):
    """(w, h) of her eyes in this mood — robot_face sizes the eyes with it,
    so the props of the reply scenes sit on them."""
    s = spec(mood, listening)
    return s["eye_w"], s["eye_h"]


def ease(cur, target, k):
    """cur moved toward target by k (0..1); pairs move side by side."""
    if isinstance(target, tuple):
        return tuple(c + (t - c) * k for c, t in zip(cur, target))
    return cur + (target - cur) * k


def spring(x, v, target, w, dt):
    """One exact step of a critically damped spring (w: 1/s): (x, v) after dt.
    It keeps its speed, so a glide starts and ends softly — an ease that jumps
    a share of the way each frame starts at full speed (a jerk on a new mood)."""
    e = x - target
    c = v + w * e
    k = math.exp(-w * dt)
    return target + (e + c * dt) * k, (c - w * (e + c * dt)) * k


class Springs:
    """Named values (numbers or tuples) on springs; a new name starts at its target."""

    def __init__(self):
        self.x, self.v = {}, {}

    def step(self, key, target, w, dt):
        dt = max(0.0, min(dt, 0.5))
        if key not in self.x:
            self.x[key] = target
            self.v[key] = tuple(0.0 for _ in target) if isinstance(target, tuple) else 0.0
            return target
        x, v = self.x[key], self.v[key]
        if isinstance(target, tuple):
            pairs = [spring(a, b, t, w, dt) for a, b, t in zip(x, v, target)]
            self.x[key] = tuple(p[0] for p in pairs)
            self.v[key] = tuple(p[1] for p in pairs)
        else:
            self.x[key], self.v[key] = spring(x, v, target, w, dt)
        return self.x[key]


class Eased:
    """The settings on screen: they glide toward the mood's on springs, the
    same whatever the frame rate (8 fps asleep, 30 awake). The mouth's kind
    can't glide — it fades out, switches, and fades back in."""
    RATE = 14.0                    # the springs' 1/s: ~90 % of the way in 0.28 s

    def __init__(self):
        self.cur = dict(BASE)
        self.springs = Springs()
        for key, val in BASE.items():
            self.springs.step(key, val, self.RATE, 0.0)
        self.mouth = LINE
        self.mouth_fade = 1.0

    def step(self, target, dt):
        for key, val in target.items():
            if key == "mouth":
                continue
            self.cur[key] = self.springs.step(key, val, self.RATE, dt)
        want = target["mouth"]
        if want != self.mouth:
            self.mouth_fade = max(0.0, self.mouth_fade - dt * 8.0)
            if self.mouth_fade <= 0.0:
                self.mouth = want
        else:
            self.mouth_fade = min(1.0, self.mouth_fade + dt * 8.0)
        return self.cur
