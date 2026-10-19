# robot_face.py
"""
robot_face.py — Luna face renderer. Industry-level interactive bot face.

Emotion animations:
  happy    — squint eyes, curved smile, pink blush, sparkles
  sad      — droopy brows, down-curve mouth, teardrop particle
  angry    — angled brows, steam wisps, red eye pulse
  surprised — wide eyes, O-mouth, starburst particles
  sleeping — closed eyes, zzz particles, peaceful blush
  listening — eye-colour pulse, raised brows (conversation mode only)
  speaking  — talking mouth (jaw shapes / robo bars), emotion frozen

Face styles (config FACE_STYLE, or press 1 / 2 on the window):
  1 — Luna classic: purple, rounded, organic mouth
  2 — Robo: cyan, sharp corners, square pupils, equalizer-bar mouth

Conversation indicator:
  a small breathing dot glows under the mouth while the wake window is
  open; on timeout the eyes dim briefly with one slow blink — the wake
  word is needed again.

Neutral: eyes only, no mouth.
All transitions smooth lerp — no snapping.
"""

import os
import sys
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # pygame must not open an audio
                                                   # stream: hers run through pw-play
import pygame
import math
import random
import time
import numpy as np
from shared_state import state
import face_spec
import gallery
import lamp_scenes
import screens
import ui_screens
from config import (RENDER_FPS, FACE_STYLE, SCREEN_WIDTH, SCREEN_HEIGHT,
                    FULLSCREEN, HIDE_CURSOR, GESTURE_DURATION,
                    CAMERA_PREVIEW, CAMERA_PREVIEW_W, TOUCH_DEBUG,
                    TOUCH_REACT_SECS, TOUCH_POKE_SECS, GAZE_FACE_PUPIL,
                    GAZE_MOTION_PUPIL, GAZE_MOTION_MAX_W, GAZE_MOTION_HOLD,
                    GAZE_MOTION_MIN, SLEEP_AFTER_FRAMES)

# The face geometry below is in absolute pixels and was drawn for a 1400x800
# window; it fits the 800x480 DSI panel as-is (~560x400 used), just larger
# relative to the screen — which suits a desktop-robot face.
WIDTH  = SCREEN_WIDTH
HEIGHT = SCREEN_HEIGHT

# the Loona face drawn by the GPU (gl_face.py) — LUNA_FACE_GL=1 in .env
FACE_GL = os.environ.get("LUNA_FACE_GL") == "1"
if FACE_GL:
    import gl_face

BG        = (0, 0, 0)
PUPIL_COL = (0, 0, 0)
# how often she blinks, by mood (× the usual 100–220 frames between blinks)
BLINK_PACE = {"sad": 1.5, "excited": 1.7, "surprised": 2.0, "love": 1.3}
LISTEN_WAVE_COL = (255, 196, 110)  # the sound waves beside her while she listens
THINK_HAND_SECS = 1.2              # thinking longer than this: a finger on her chin

# On the 800x480 panel the mouth would kiss the bottom edge: lift the face a
# little and keep the conversation-window dot (below the mouth) on-screen.
FACE_Y_OFFSET = -28 if HEIGHT < 600 else 0
AWAKE_DOT_Y   = min(265, HEIGHT - (HEIGHT // 2 + FACE_Y_OFFSET) - 25)

# ── Face styles ───────────────────────────────────────────────────────────────
# Style 1 — "luna":  the classic soft purple face (rounded, organic mouth)
# Style 2 — "robo":  modern-robot look (cyan, sharp corners, square pupils,
#                    equalizer-bar mouth while speaking)
# Style 3 — "loona": amber gradient "block" eyes without pupils, expressions
#                    carried by the eye shape (arched when happy, sloped when
#                    sad/angry), like the Loona pet robot
# Press 1 / 2 / 3 on the face window to switch at runtime — switching back to
# 1 restores the exact original face.
STYLES = {
    1: dict(
        name="luna",
        EYE_OUTER=(55, 0, 200),   EYE_MID=(90, 30, 255),
        EYE_INNER=(160, 90, 255), IRIS_SHINE=(220, 190, 255),
        GLOW_COL=(80, 20, 200),   MOUTH_COL=(70, 10, 220),
        ZZZ_COL=(120, 60, 220),   LISTEN_COL=(0, 180, 255),
        BLUSH_COL=(255, 100, 150), TEAR_COL=(100, 180, 255),
        STEAM_COL=(255, 120, 60), STAR_COL=(255, 220, 80),
        TEETH_COL=(240, 240, 255), WAVE_COL=(120, 40, 255),
        ANGRY_COL=(220, 30, 30),  HEART_COL=(255, 80, 130),
        AWAKE_COL=(0, 200, 255),
        EYE_RADIUS=20, IRIS_SQUARE=False, MOUTH_STYLE="organic",
    ),
    2: dict(
        name="robo",
        EYE_OUTER=(0, 120, 150),  EYE_MID=(0, 190, 220),
        EYE_INNER=(140, 240, 255), IRIS_SHINE=(230, 255, 255),
        GLOW_COL=(0, 110, 150),   MOUTH_COL=(0, 200, 230),
        ZZZ_COL=(0, 160, 200),    LISTEN_COL=(255, 170, 40),
        BLUSH_COL=(0, 220, 200),  TEAR_COL=(120, 220, 255),
        STEAM_COL=(255, 120, 60), STAR_COL=(180, 255, 255),
        TEETH_COL=(210, 250, 255), WAVE_COL=(0, 220, 255),
        ANGRY_COL=(255, 60, 40),  HEART_COL=(90, 240, 210),
        AWAKE_COL=(120, 255, 220),
        EYE_RADIUS=8, IRIS_SQUARE=True, MOUTH_STYLE="bars",
    ),
    3: dict(
        name="loona",
        EYE_OUTER=(255, 160, 40),  EYE_MID=(255, 185, 70),
        EYE_INNER=(255, 232, 160), IRIS_SHINE=(255, 250, 225),
        GLOW_COL=(255, 125, 20),   MOUTH_COL=(255, 170, 50),
        ZZZ_COL=(255, 205, 100),   LISTEN_COL=(255, 245, 215),
        BLUSH_COL=(255, 120, 95),  TEAR_COL=(150, 205, 255),
        STEAM_COL=(255, 110, 50),  STAR_COL=(255, 235, 130),
        TEETH_COL=(255, 246, 225),
        WAVE_COL=(255, 185, 60),   ANGRY_COL=(255, 55, 30),
        HEART_COL=(255, 115, 110), AWAKE_COL=(255, 205, 100),
        EYE_RADIUS=34, IRIS_SQUARE=False, MOUTH_STYLE="organic",
        EYE_MODE="block", EYE_SCALE=1.18, EYE_SPREAD=int(face_spec.LAYOUT["eye_x"]),
        EYE_GRAD_TOP=(255, 232, 140), EYE_GRAD_BOTTOM=(232, 96, 12),
        BLOCK_PUPIL=True, PUPIL_DARK=(28, 12, 2), IRIS_COL=(132, 58, 12),
        BROW_GRAD_TOP=(255, 214, 110), BROW_GRAD_BOTTOM=(214, 96, 18),
        HAIR=False, HANDS=True,     # hair can be switched on here
        HAIR_GRAD_TOP=(255, 196, 80), HAIR_GRAD_BOTTOM=(196, 78, 10),
        HAND_GRAD_TOP=(255, 226, 130), HAND_GRAD_BOTTOM=(238, 110, 20),
    ),
}

# active style values (module globals so particles pick them up live)
CURRENT_STYLE = 1
_HAND_CACHE = {}   # rendered hand images per (pose, side); cleared on style change


def apply_style(n):
    """Swap the whole palette + geometry at runtime. 1 = classic, 2 = robo."""
    global CURRENT_STYLE, EYE_OUTER, EYE_MID, EYE_INNER, IRIS_SHINE, GLOW_COL
    global MOUTH_COL, ZZZ_COL, LISTEN_COL, BLUSH_COL, TEAR_COL, STEAM_COL
    global STAR_COL, TEETH_COL, WAVE_COL, ANGRY_COL, HEART_COL, AWAKE_COL
    global EYE_RADIUS, IRIS_SQUARE, MOUTH_STYLE
    global EYE_MODE, EYE_GRAD_TOP, EYE_GRAD_BOTTOM, EYE_SCALE, EYE_SPREAD
    global BLOCK_PUPIL, PUPIL_DARK, BROW_GRAD_TOP, BROW_GRAD_BOTTOM, IRIS_COL
    global HAIR, HANDS, HAIR_GRAD_TOP, HAIR_GRAD_BOTTOM, HAND_GRAD_TOP, HAND_GRAD_BOTTOM

    s = STYLES.get(n)
    if s is None:
        return
    CURRENT_STYLE = n
    EYE_OUTER   = s["EYE_OUTER"];   EYE_MID    = s["EYE_MID"]
    EYE_INNER   = s["EYE_INNER"];   IRIS_SHINE = s["IRIS_SHINE"]
    GLOW_COL    = s["GLOW_COL"];    MOUTH_COL  = s["MOUTH_COL"]
    ZZZ_COL     = s["ZZZ_COL"];     LISTEN_COL = s["LISTEN_COL"]
    BLUSH_COL   = s["BLUSH_COL"];   TEAR_COL   = s["TEAR_COL"]
    STEAM_COL   = s["STEAM_COL"];   STAR_COL   = s["STAR_COL"]
    TEETH_COL   = s["TEETH_COL"];   WAVE_COL   = s["WAVE_COL"]
    ANGRY_COL   = s["ANGRY_COL"];   HEART_COL  = s["HEART_COL"]
    AWAKE_COL   = s["AWAKE_COL"]
    EYE_RADIUS  = s["EYE_RADIUS"]
    IRIS_SQUARE = s["IRIS_SQUARE"]
    MOUTH_STYLE = s["MOUTH_STYLE"]
    EYE_MODE        = s.get("EYE_MODE", "iris")     # "iris" | "block"
    EYE_SCALE       = s.get("EYE_SCALE", 1.0)       # eye size multiplier
    EYE_SPREAD      = s.get("EYE_SPREAD", 190)      # half distance between eyes
    EYE_GRAD_TOP    = s.get("EYE_GRAD_TOP", EYE_INNER)
    EYE_GRAD_BOTTOM = s.get("EYE_GRAD_BOTTOM", EYE_OUTER)
    BLOCK_PUPIL     = s.get("BLOCK_PUPIL", False)
    PUPIL_DARK      = s.get("PUPIL_DARK", PUPIL_COL)
    IRIS_COL        = s.get("IRIS_COL", (120, 52, 10))
    BROW_GRAD_TOP    = s.get("BROW_GRAD_TOP", EYE_MID)
    BROW_GRAD_BOTTOM = s.get("BROW_GRAD_BOTTOM", EYE_MID)
    HAIR             = s.get("HAIR", False)
    HANDS            = s.get("HANDS", False)
    HAIR_GRAD_TOP    = s.get("HAIR_GRAD_TOP", EYE_MID)
    HAIR_GRAD_BOTTOM = s.get("HAIR_GRAD_BOTTOM", EYE_OUTER)
    HAND_GRAD_TOP    = s.get("HAND_GRAD_TOP", EYE_INNER)
    HAND_GRAD_BOTTOM = s.get("HAND_GRAD_BOTTOM", EYE_OUTER)
    _HAND_CACHE.clear()
    _GLOW_CACHE.clear()   # cached glows are per-palette
    _GRAD_CACHE.clear()
    print(f"[face] Style {n} ({s['name']}) active")


def lerp(a, b, t):
    return a + (b - a) * t


# This frame's length in the animation's own frames: its per-frame steps
# (eases, blinks, particles, counters) were tuned at face.anim_fps — 30 a
# second, 20 when calm, 12 asleep — and keep that pace at any frame rate
# drawn (RobotFace.update sets it).
_K = 1.0


def ease(a, b, t):
    """lerp(a, b, t) once per tuned frame: the same speed at any frame rate."""
    return a + (b - a) * (t if _K == 1.0 else 1.0 - (1.0 - t) ** _K)

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _prop_hold(p, rise=0.12, fall=0.12):
    """1.0 while a prop is on screen, easing in at the start of the scene and
    out at the end (p is the scene's 0..1 progress)."""
    if p < rise:
        t = p / rise
    elif p > 1.0 - fall:
        t = (1.0 - p) / fall
    else:
        return 1.0
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ── Glow rendering — cached (was rebuilt from scratch every frame on the Pi) ──
_GLOW_CACHE = {}
_GLOW_CACHE_MAX = 220


def _cache_put(key, surf):
    if len(_GLOW_CACHE) >= _GLOW_CACHE_MAX:
        _GLOW_CACHE.clear()
    _GLOW_CACHE[key] = surf


def draw_glow_rect(surf, color, rect, radius=20, layers=5, max_alpha=70):
    # bucket to 8 px so nearby sizes share one cached surface
    bw = max(8, (rect.width  // 8) * 8)
    bh = max(8, (rect.height // 8) * 8)
    key = ("r", color, bw, bh, radius, layers, max_alpha)
    glow = _GLOW_CACHE.get(key)
    if glow is None:
        pad  = (layers + 1) * 5
        glow = pygame.Surface((bw + pad * 2, bh + pad * 2), pygame.SRCALPHA)
        for i in range(layers, 0, -1):
            alpha  = int(max_alpha * (i / layers) ** 2)
            expand = (layers - i + 1) * 5
            w, h = bw + expand * 2, bh + expand * 2
            s = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(s, (*color, alpha), s.get_rect(),
                             border_radius=radius + expand)
            glow.blit(s, (pad - expand, pad - expand))
        _cache_put(key, glow)
    surf.blit(glow, (rect.centerx - glow.get_width() // 2,
                     rect.centery - glow.get_height() // 2))


def draw_glow_circle(surf, color, center, radius, layers=4, max_alpha=55):
    br  = max(4, (radius // 4) * 4)   # bucket to 4 px
    key = ("c", color, br, layers, max_alpha)
    glow = _GLOW_CACHE.get(key)
    if glow is None:
        pad  = (layers + 1) * 5 + 2
        size = br * 2 + pad * 2
        glow = pygame.Surface((size, size), pygame.SRCALPHA)
        for i in range(layers, 0, -1):
            alpha = int(max_alpha * (i / layers) ** 2)
            r     = br + (layers - i + 1) * 5
            s     = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(s, (*color, alpha), (size // 2, size // 2), r)
            glow.blit(s, (0, 0))
        _cache_put(key, glow)
    surf.blit(glow, (center[0] - glow.get_width() // 2,
                     center[1] - glow.get_height() // 2))


# ── Gradient "block" eye (style 3) — cached per size bucket ──────────────────
_GRAD_CACHE = {}


def _lerp_col(a, b, t):
    return (int(lerp(a[0], b[0], t)), int(lerp(a[1], b[1], t)),
            int(lerp(a[2], b[2], t)))


def gradient_sheet(w, h, top, bottom, sheen=0.35, rim=0.34):
    """Unmasked domed-panel shading: vertical gradient × radial falloff +
    specular sheen. Used for the eye blocks and (via a shape mask) brows."""
    key = ("sheet", w, h, top, bottom, sheen, rim)
    surf = _GRAD_CACHE.get(key)
    if surf is None:
        if len(_GRAD_CACHE) > 400:
            _GRAD_CACHE.clear()
        ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[None, :]      # (1,h)
        xs = np.linspace(-1.0, 1.0, w, dtype=np.float32)[:, None]     # (w,1)
        t  = ys ** 1.25
        col = (np.array(top, np.float32)[None, None, :] * (1 - t[..., None])
               + np.array(bottom, np.float32)[None, None, :] * t[..., None])
        col = np.broadcast_to(col, (w, h, 3)).copy()
        dy = (ys - 0.42) * 2.0
        d2 = xs ** 2 * 0.9 + dy ** 2 * 1.1
        light = 1.06 - rim * np.clip(d2, 0.0, 1.6)
        col *= light[..., None]
        sx = xs * 1.15
        sy = (ys - 0.24) * 3.2
        col += 255.0 * (np.exp(-(sx ** 2 + sy ** 2) * 2.2) * sheen)[..., None]
        arr = np.clip(col, 0, 255).astype(np.uint8)
        surf = pygame.surfarray.make_surface(arr).convert_alpha()
        _GRAD_CACHE[key] = surf
    return surf


def gradient_block(w, h, radius, top, bottom):
    """Rounded rect that looks like a domed, back-lit amber panel:
    vertical gradient (top → bottom colour) × radial falloff (bright core,
    darker rim) + a soft specular sheen in the upper third."""
    w = max(4, (w // 2) * 2)
    h = max(4, (h // 2) * 2)
    key = (w, h, radius, top, bottom)
    surf = _GRAD_CACHE.get(key)
    if surf is None:
        if len(_GRAD_CACHE) > 400:
            _GRAD_CACHE.clear()
        ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[None, :]      # (1,h)
        xs = np.linspace(-1.0, 1.0, w, dtype=np.float32)[:, None]     # (w,1)
        t  = ys ** 1.25                                               # vertical
        col = (np.array(top, np.float32)[None, None, :] * (1 - t[..., None])
               + np.array(bottom, np.float32)[None, None, :] * t[..., None])
        col = np.broadcast_to(col, (w, h, 3)).copy()
        # radial falloff: bright a little above centre, darker toward the rim
        dy = (ys - 0.42) * 2.0
        d2 = xs ** 2 * 0.9 + dy ** 2 * 1.1
        light = 1.06 - 0.34 * np.clip(d2, 0.0, 1.6)
        col *= light[..., None]
        # specular sheen: soft bright ellipse in the upper third
        sx = xs * 1.15
        sy = (ys - 0.24) * 3.2
        sheen = np.exp(-(sx ** 2 + sy ** 2) * 2.2) * 0.35
        col += 255.0 * sheen[..., None]
        arr = np.clip(col, 0, 255).astype(np.uint8)
        surf = pygame.surfarray.make_surface(arr).convert_alpha()
        mask = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                         border_radius=min(radius, h // 2, w // 2))
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        _GRAD_CACHE[key] = surf
    return surf


def bloom(surf, layer, pos, radius=10, passes=2, max_alpha=110, grow=0.10):
    """Soft glow that follows an arbitrary SRCALPHA shape. Cheap blur:
    pad, shrink, enlarge (smoothscale both ways) — then blit behind."""
    lw, lh = layer.get_size()
    pad = radius * 3
    big = pygame.Surface((lw + pad * 2, lh + pad * 2), pygame.SRCALPHA)
    big.blit(layer, (pad, pad))
    bw, bh = big.get_size()
    small = pygame.transform.smoothscale(big, (max(2, bw // radius), max(2, bh // radius)))
    for i in range(passes, 0, -1):
        k = 1.0 + grow * i         # a halo for round shapes; 0 for text (no ghost letters)
        g = pygame.transform.smoothscale(small, (int(bw * k), int(bh * k)))
        g.set_alpha(int(max_alpha * (1.0 - (i - 1) / passes) ** 1.5))
        surf.blit(g, (pos[0] - pad - (g.get_width() - bw) // 2,
                      pos[1] - pad - (g.get_height() - bh) // 2))


_BROW_GRAD_CACHE = {}


def brow_gradient(w, h, top, bottom):
    """Vertical gradient sheet used to tint eyebrow shapes (cached)."""
    key = (w, h, top, bottom)
    g = _BROW_GRAD_CACHE.get(key)
    if g is None:
        if len(_BROW_GRAD_CACHE) > 200:
            _BROW_GRAD_CACHE.clear()
        g = pygame.Surface((w, h), pygame.SRCALPHA)
        for y in range(h):
            t = y / max(1, h - 1)
            pygame.draw.line(g, (*_lerp_col(top, bottom, t), 255), (0, y), (w, y))
        _BROW_GRAD_CACHE[key] = g
    return g


# apply the configured startup style (defines all palette globals)
apply_style(FACE_STYLE if FACE_STYLE in STYLES else 1)


# ── Font cache — SysFont was being created per particle per frame ─────────────
_FONT_CACHE = {}


def _draw_star(surf, cx, cy, r, col, shine):
    """A five-pointed star (no font has one we can trust)."""
    if r < 2:
        return
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    pygame.draw.polygon(surf, col, pts)
    pygame.draw.polygon(surf, shine, pts, max(1, int(r / 10)))


def _get_font(size):
    """Her lettering: Nunito Sans ExtraBold (assets/fonts), antialiased —
    the system monospace looked like a terminal."""
    f = _FONT_CACHE.get(size)
    if f is None:
        f = _FONT_CACHE[size] = ui_screens.font(size, "ExtraBold")
    return f


# ── Particles ─────────────────────────────────────────────────────────────────

class ZzzParticle:
    def __init__(self, x, y):
        self.x0    = x
        self.x     = x
        self.y     = y
        self.alpha = 255
        self.size  = random.randint(26, 50)
        self.vy    = random.uniform(-1.2, -0.6)
        self.age   = 0
        self.ph    = random.uniform(0, math.tau)

    def update(self):
        self.age  += _K
        self.x     = self.x0 + 14 * math.sin(self.age * 0.05 + self.ph) + self.age * 0.35
        self.y    += self.vy * _K
        self.alpha = max(0, self.alpha - 3 * _K)

    def alive(self): return self.alpha > 0

    def draw(self, surf):
        try:
            grow = 0.7 + 0.5 * min(1.0, self.age / 80.0)     # small, then bigger
            img = zzz_img(int(self.size * grow) // 2 * 2, self.size > 38)
            img.set_alpha(int(self.alpha))
            surf.blit(img, img.get_rect(center=(int(self.x), int(self.y))))
        except Exception:
            pass


def zzz_img(size, big):
    """A soft glowing "Z" (cached by size)."""
    key = ("zzz", size, big, ZZZ_COL)
    img = _SMOOTH_CACHE.get(key)
    if img is None:
        txt = _get_font(size).render("Z" if big else "z", True, ZZZ_COL)
        w, h = txt.get_width() + 24, txt.get_height() + 24
        img = pygame.Surface((w, h), pygame.SRCALPHA)
        halo = pygame.transform.smoothscale(
            pygame.transform.smoothscale(txt, (max(1, txt.get_width() // 4),
                                               max(1, txt.get_height() // 4))),
            (txt.get_width() + 16, txt.get_height() + 16))
        halo.set_alpha(110)
        img.blit(halo, (4, 4))
        img.blit(txt, (12, 12))
        _SMOOTH_CACHE[key] = img
    return img.copy()


def blush_lines(surf, fcx, fcy, k):
    """Three short slanted strokes on each cheek (gl_face's blush spots)."""
    img = _SMOOTH_CACHE.get(("blush_lines", BLUSH_COL))
    if img is None:
        def draw(s, kk):
            col = _lerp_col(BLUSH_COL, (255, 255, 255), 0.25)
            for j in range(3):
                x = (14 + j * 17) * kk
                pygame.draw.line(s, col, (x + 9 * kk, 6 * kk), (x, 30 * kk), int(4 * kk))
        img = _SMOOTH_CACHE[("blush_lines", BLUSH_COL)] = _smooth(70, 36, draw)
    img = img.copy()
    img.set_alpha(int(220 * k))
    for side in (-1, 1):
        surf.blit(img, img.get_rect(center=(int(fcx + side * 232), int(fcy + 70))))


def anger_mark(surf, x, y, r, alpha=255):
    """The cartoon anger mark: four bulging arcs in a cross (cached)."""
    r = int(r)
    key = ("anger", r, ANGRY_COL)
    img = _SMOOTH_CACHE.get(key)
    if img is None:
        def draw(s, k):
            c = (r + 4) * k
            for ang in (45, 135, 225, 315):       # one in each corner, its bulge
                a = math.radians(ang)             # toward the middle
                ox, oy = math.cos(a) * r * 1.25 * k, math.sin(a) * r * 1.25 * k
                pts = []
                for j in range(13):
                    t = math.radians(ang + 154 + 52 * j / 12)
                    pts.append((c + ox + math.cos(t) * r * 1.0 * k,
                                c + oy + math.sin(t) * r * 1.0 * k))
                pygame.draw.lines(s, _lerp_col(ANGRY_COL, (90, 0, 0), 0.4), False, pts, int(10 * k))
                pygame.draw.lines(s, ANGRY_COL, False, pts, int(6 * k))
        img = _SMOOTH_CACHE[key] = _smooth(2 * r + 8, 2 * r + 8, draw)
    if alpha < 255:
        img = img.copy()
        img.set_alpha(int(max(0, alpha)))
    surf.blit(img, img.get_rect(center=(int(x), int(y))))


class TearParticle:
    def __init__(self, x, y):
        self.x     = float(x)
        self.y     = float(y)
        self.alpha = 200
        self.r     = random.randint(6, 10)
        self.vy    = random.uniform(1.0, 2.0)
        self.vx    = random.uniform(-0.2, 0.2)

    def update(self):
        self.x    += self.vx * _K
        self.y    += self.vy * _K
        self.vy   += 0.1 * _K   # gravity
        self.alpha = max(0, self.alpha - 2 * _K)

    def alive(self): return self.alpha > 0

    def draw(self, surf):
        img = tear_img(self.r)
        img.set_alpha(int(self.alpha))
        surf.blit(img, img.get_rect(center=(int(self.x), int(self.y))))


def tear_img(r):
    """A glossy drop (antialiased, cached by size): pointed on top, a light
    rim and a highlight — the same tear wherever she cries."""
    r = max(4, int(r))
    key = ("tear", r, TEAR_COL)
    img = _SMOOTH_CACHE.get(key)
    if img is None:
        def draw(s, k, r=r):
            cx, cy = (r + 3) * k, (2 * r + 3) * k
            pts = [(cx, 3 * k)]
            for j in range(25):
                a = math.pi * (j / 24.0) - math.pi       # the round bottom half…
                pts.append((cx + math.cos(a) * r * k, cy - math.sin(a) * r * k))
            pygame.draw.polygon(s, _lerp_col(TEAR_COL, (40, 90, 160), 0.35), pts)
            pygame.draw.circle(s, TEAR_COL, (int(cx), int(cy)), int(r * 0.8 * k))
            pygame.draw.circle(s, (240, 250, 255), (int(cx - r * 0.35 * k), int(cy - r * 0.3 * k)),
                               max(1, int(r * 0.26 * k)))
        img = _SMOOTH_CACHE[key] = _smooth(2 * r + 6, 3 * r + 6, draw)
    return img


class SteamParticle:
    def __init__(self, x, y):
        self.x     = float(x)
        self.y     = float(y)
        self.alpha = 180
        self.r     = random.randint(5, 12)
        self.vx    = random.uniform(-0.5, 0.5)
        self.vy    = random.uniform(-1.5, -0.8)

    def update(self):
        self.x    += self.vx * _K
        self.y    += self.vy * _K
        self.alpha = max(0, self.alpha - 4 * _K)
        self.r     = max(1, self.r - 0.1 * _K)

    def alive(self): return self.alpha > 0

    def draw(self, surf):
        s = pygame.Surface((self.r * 2 + 4, self.r * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(s, (*STEAM_COL, int(self.alpha)),
                           (int(self.r) + 2, int(self.r) + 2), int(self.r))
        surf.blit(s, (int(self.x) - int(self.r) - 2,
                      int(self.y) - int(self.r) - 2))


class StarParticle:
    def __init__(self, x, y):
        self.x     = float(x)
        self.y     = float(y)
        self.alpha = 255
        self.size  = random.randint(8, 18)
        angle      = random.uniform(0, math.pi * 2)
        speed      = random.uniform(2.0, 5.0)
        self.vx    = math.cos(angle) * speed
        self.vy    = math.sin(angle) * speed

    def update(self):
        self.x    += self.vx * _K
        self.y    += self.vy * _K
        self.vx   *= 0.92 ** _K
        self.vy   *= 0.92 ** _K
        self.alpha = max(0, self.alpha - 6 * _K)

    def alive(self): return self.alpha > 0

    def draw(self, surf):
        if self.size < 2:
            return
        s = pygame.Surface((self.size * 4, self.size * 4), pygame.SRCALPHA)
        cx, cy = self.size * 2, self.size * 2
        for i in range(5):
            angle_out = math.pi / 2 + i * (2 * math.pi / 5)
            angle_in  = angle_out + math.pi / 5
            ox = cx + math.cos(angle_out) * self.size
            oy = cy - math.sin(angle_out) * self.size
            ix = cx + math.cos(angle_in)  * self.size * 0.4
            iy = cy - math.sin(angle_in)  * self.size * 0.4
            pygame.draw.line(s, (*STAR_COL, int(self.alpha)),
                             (int(cx), int(cy)), (int(ox), int(oy)), 2)
            pygame.draw.line(s, (*STAR_COL, int(self.alpha)),
                             (int(cx), int(cy)), (int(ix), int(iy)), 1)
        surf.blit(s, (int(self.x) - self.size * 2,
                      int(self.y) - self.size * 2))


class HeartParticle:
    """Floating heart — spawned in the 'love' state (compliments)."""
    def __init__(self, x, y):
        self.x     = float(x)
        self.y     = float(y)
        self.alpha = 235
        self.size  = random.randint(10, 22)
        self.vx    = random.uniform(-0.6, 0.6)
        self.vy    = random.uniform(-1.8, -0.9)
        self.sway  = random.uniform(0, math.pi * 2)

    def update(self):
        self.sway += 0.1 * _K
        self.x    += (self.vx + math.sin(self.sway) * 0.6) * _K
        self.y    += self.vy * _K
        self.alpha = max(0, self.alpha - 3 * _K)

    def alive(self): return self.alpha > 0

    def draw(self, surf):
        draw_heart(surf, self.x, self.y, self.size, self.alpha)


class SoundWave:
    def __init__(self, x, y):
        self.x     = x
        self.y     = y
        self.r     = 20.0
        self.alpha = 180
        self.max_r = random.randint(80, 140)

    def update(self):
        self.r    += 3.5 * _K
        self.alpha = max(0, int(180 * (1 - self.r / self.max_r)))

    def alive(self): return self.r < self.max_r

    def draw(self, surf):
        if self.r < 1 or self.alpha < 5:
            return
        s = pygame.Surface((int(self.r * 2) + 4,
                            int(self.r * 2) + 4), pygame.SRCALPHA)
        pygame.draw.circle(s, (*WAVE_COL, self.alpha),
                           (int(self.r) + 2, int(self.r) + 2),
                           int(self.r), 2)
        surf.blit(s, (self.x - int(self.r) - 2,
                      self.y - int(self.r) - 2))


# ── Blush (not a particle — persistent surface) ───────────────────────────────
class Blush:
    def __init__(self, rel_x, rel_y):
        self.rel_x = rel_x
        self.rel_y = rel_y
        self.alpha = 0.0   # 0–255

    def update(self, target_alpha):
        self.alpha = ease(self.alpha, target_alpha, 0.04)

    def draw(self, surf, fcx, fcy):
        if self.alpha < 3:
            return
        cx = fcx + self.rel_x
        cy = fcy + self.rel_y
        for r, a_mult in [(38, 0.4), (28, 0.7), (18, 1.0)]:
            s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(s, (*BLUSH_COL, int(self.alpha * a_mult)),
                                pygame.Rect(0, 0, r * 2, r * 2))
            surf.blit(s, (cx - r, cy - r))


# ── Eye ───────────────────────────────────────────────────────────────────────
class Eye:
    def __init__(self, rel_x, rel_y, w, h):
        self.rel_x       = rel_x
        self.rel_y       = rel_y
        self.w           = float(w)
        self.h           = float(h)
        self.blink_t     = 1.0
        self.pupil_ox    = 0.0
        self.pupil_oy    = 0.0
        self.pupil_scale = 1.0
        self.squint      = 0.0
        self.widen       = 0.0
        self.droop       = 0.0   # sad inner brow droop

    def update(self, target_w, target_h, blink_t, pupil_ox, pupil_oy,
               pupil_scale=1.0, squint=0.0, widen=0.0, droop=0.0):
        self.w           = ease(self.w,           target_w,    0.10)
        self.h           = ease(self.h,           target_h,    0.10)
        self.blink_t     = ease(self.blink_t,     blink_t,     0.30)
        self.pupil_ox    = ease(self.pupil_ox,    pupil_ox,    0.18)
        self.pupil_oy    = ease(self.pupil_oy,    pupil_oy,    0.18)
        self.pupil_scale = ease(self.pupil_scale, pupil_scale, 0.10)
        self.squint      = ease(self.squint,      squint,      0.08)
        self.widen       = ease(self.widen,       widen,       0.08)
        self.droop       = ease(self.droop,       droop,       0.06)

    def draw(self, surf, cx, cy, angry=False, happy=False,
             sad=False, listening=False,
             color_override=None, angry_pulse=0.0):

        eye_color = color_override if color_override else EYE_OUTER
        mid_color = EYE_MID
        inn_color = EYE_INNER

        # angry red pulse overlay
        if angry_pulse > 0.01:
            eye_color = (
                int(lerp(eye_color[0], ANGRY_COL[0], angry_pulse)),
                int(lerp(eye_color[1], ANGRY_COL[1], angry_pulse)),
                int(lerp(eye_color[2], ANGRY_COL[2], angry_pulse)),
            )

        w     = int(self.w)
        h_mod = self.h * (1.0 - self.squint * 0.4) * (1.0 + self.widen * 0.2)
        vis_h = max(4, int(h_mod * self.blink_t))
        rect  = pygame.Rect(cx - w // 2, cy - vis_h // 2, w, vis_h)

        if EYE_MODE == "block":
            self._draw_block(surf, rect, cx, cy, vis_h, eye_color,
                             angry, happy, sad, listening)
            return

        draw_glow_rect(surf, GLOW_COL, rect, radius=EYE_RADIUS + 2, layers=5)
        pygame.draw.rect(surf, eye_color, rect, border_radius=EYE_RADIUS)

        if self.squint > 0.05:
            clip_h = int(vis_h * self.squint * 0.5)
            if clip_h > 0:
                pygame.draw.rect(surf, BG,
                                 pygame.Rect(rect.x, rect.y,
                                             rect.w, clip_h),
                                 border_radius=max(4, EYE_RADIUS // 2))

        shrink   = 10
        mid_rect = pygame.Rect(rect.x + shrink, rect.y + shrink,
                               rect.w - shrink * 2, rect.h - shrink * 2)
        if mid_rect.w > 8 and mid_rect.h > 8:
            pygame.draw.rect(surf, mid_color, mid_rect,
                             border_radius=max(4, EYE_RADIUS - 6))

        iris_r  = int(min(w, vis_h) * 0.27 * self.pupil_scale)
        iris_cx = cx + int(self.pupil_ox)
        iris_cy = cy + int(self.pupil_oy)

        if iris_r > 4 and self.blink_t > 0.25:
            if IRIS_SQUARE:
                # robotic style — square sensor-like pupil
                ir = pygame.Rect(iris_cx - iris_r, iris_cy - iris_r,
                                 iris_r * 2, iris_r * 2)
                draw_glow_rect(surf, inn_color, ir, radius=6, layers=3,
                               max_alpha=45)
                pygame.draw.rect(surf, inn_color, ir, border_radius=6)
                pr = int(iris_r * 0.55)
                pygame.draw.rect(surf, PUPIL_COL,
                                 pygame.Rect(iris_cx - pr, iris_cy - pr,
                                             pr * 2, pr * 2),
                                 border_radius=4)
                sr = max(3, int(iris_r * 0.18))
                s  = pygame.Surface((sr * 2, sr * 2), pygame.SRCALPHA)
                pygame.draw.rect(s, (*IRIS_SHINE, 190), s.get_rect(),
                                 border_radius=2)
                surf.blit(s, (iris_cx - int(iris_r * 0.45) - sr,
                              iris_cy - int(iris_r * 0.45) - sr))
            else:
                draw_glow_circle(surf, inn_color, (iris_cx, iris_cy), iris_r)
                pygame.draw.circle(surf, inn_color, (iris_cx, iris_cy), iris_r)
                pygame.draw.circle(surf, PUPIL_COL, (iris_cx, iris_cy),
                                   int(iris_r * 0.50))
                sr = max(3, int(iris_r * 0.20))
                s  = pygame.Surface((sr * 2, sr * 2), pygame.SRCALPHA)
                pygame.draw.circle(s, (*IRIS_SHINE, 180), (sr, sr), sr)
                surf.blit(s, (iris_cx - int(iris_r * 0.30) - sr,
                              iris_cy - int(iris_r * 0.30) - sr))

        # ── brow ──────────────────────────────────────────────────────────
        if self.blink_t > 0.4:
            brow_y = rect.top - 16
            brow_w = int(w * 0.70)
            is_left = cx < WIDTH // 2

            if angry:
                sign = 1 if is_left else -1
                pygame.draw.line(surf, EYE_MID,
                                 (cx - brow_w // 2, brow_y + sign * 10),
                                 (cx + brow_w // 2, brow_y - sign * 10), 9)
            elif happy:
                arc_s = pygame.Surface((brow_w + 20, 30), pygame.SRCALPHA)
                pygame.draw.arc(arc_s, (*EYE_MID, 200),
                                pygame.Rect(10, 0, brow_w, 28),
                                math.radians(10), math.radians(170), 7)
                surf.blit(arc_s, (cx - brow_w // 2 - 10, brow_y - 10))
            elif sad:
                # inner corners raised — classic sad brow
                droop_amt = int(self.droop * 14)
                if is_left:
                    pygame.draw.line(surf, EYE_MID,
                                     (cx - brow_w // 2, brow_y),
                                     (cx + brow_w // 2, brow_y - droop_amt), 9)
                else:
                    pygame.draw.line(surf, EYE_MID,
                                     (cx - brow_w // 2, brow_y - droop_amt),
                                     (cx + brow_w // 2, brow_y), 9)
            elif listening:
                lift = int(10 * self.widen)
                pygame.draw.rect(surf, EYE_MID,
                                 pygame.Rect(cx - brow_w // 2,
                                             brow_y - lift, brow_w, 9),
                                 border_radius=4)
            else:
                pygame.draw.rect(surf, EYE_MID,
                                 pygame.Rect(cx - brow_w // 2, brow_y,
                                             brow_w, 9),
                                 border_radius=4)


    # ── style 3: pupil-less gradient block, expression = shape ────────────
    def _draw_block(self, surf, rect, cx, cy, vis_h, eye_color,
                    angry, happy, sad, listening):
        # the whole block glances instead of a pupil
        rect = rect.move(int(self.pupil_ox * 0.55), int(self.pupil_oy * 0.55))
        # never let the two blocks collide (surprised/excited grow them a lot)
        max_w = EYE_SPREAD * 2 - 44
        if rect.w > max_w:
            rect = pygame.Rect(rect.centerx - max_w // 2, rect.y, max_w, rect.h)
        # squint lowers the top edge (a lid coming down), rather than
        # clearing pixels and exposing the glow underneath as a dark cap
        if self.squint > 0.05:
            clip_h = int(vis_h * self.squint * 0.5)
            rect = pygame.Rect(rect.x, rect.y + clip_h, rect.w, max(4, rect.h - clip_h))
        top, bottom = EYE_GRAD_TOP, EYE_GRAD_BOTTOM
        if eye_color != EYE_OUTER:           # listening / angry / rest tints
            top    = _lerp_col(top,    eye_color, 0.45)
            bottom = _lerp_col(bottom, eye_color, 0.45)

        # Build the eye in its own layer so shape cuts (arc, slopes, squint)
        # remove eye pixels only — painting black on the canvas would also
        # erase the glow and blush behind the eye.
        block = gradient_block(rect.w, rect.h, EYE_RADIUS, top, bottom)
        eye   = block.copy()
        ew, eh = eye.get_size()
        CLEAR = (0, 0, 0, 0)
        is_left = cx < WIDTH // 2
        open_enough = self.blink_t > 0.4

        # glow: full block normally, only the upper part when the eye is a
        # smiling arc (no halo hanging under the cut-away bottom)
        glow_rect = rect
        if happy and open_enough:
            glow_rect = pygame.Rect(rect.x, rect.y, rect.w, int(rect.h * 0.55))
        draw_glow_rect(surf, GLOW_COL, glow_rect, radius=EYE_RADIUS + 4,
                       layers=5, max_alpha=60)

        if happy and open_enough:
            # bottom edge becomes an upward arc → "^ ^" smiling eyes
            pygame.draw.ellipse(eye, CLEAR,
                                pygame.Rect(-ew // 5, int(eh * 0.42),
                                            ew + (ew * 2) // 5, int(eh * 1.3)))
        elif sad and open_enough:
            # outer top corners slope down → worried eyes
            drop, span = int(eh * 0.45), int(ew * 0.70)
            pts = ([(0, 0), (span, 0), (0, drop)] if is_left
                   else [(ew, 0), (ew - span, 0), (ew, drop)])
            pygame.draw.polygon(eye, CLEAR, pts)
        elif angry and open_enough:
            # inner top corners slope down → knitted, cross look
            drop, span = int(eh * 0.50), int(ew * 0.75)
            pts = ([(ew, 0), (ew - span, 0), (ew, drop)] if is_left
                   else [(0, 0), (span, 0), (0, drop)])
            pygame.draw.polygon(eye, CLEAR, pts)

        # dark pupil: a soft rounded square that drifts with the glance,
        # with a small catch-light — sits inside the block so shape cuts
        # (smile arc, slopes) clip it too
        if BLOCK_PUPIL and self.blink_t > 0.25 and eh > 30:
            pr = int(min(ew, eh) * 0.20 * self.pupil_scale)
            px = ew // 2 + int(self.pupil_ox * 0.45)
            py = eh // 2 + int(self.pupil_oy * 0.45) - (int(eh * 0.16) if happy else 0)
            if pr > 4:
                ps = pygame.Surface((pr * 2 + 8, pr * 2 + 8), pygame.SRCALPHA)
                pygame.draw.rect(ps, (*PUPIL_DARK, 90), ps.get_rect(),
                                 border_radius=pr // 2 + 4)             # soft edge
                pygame.draw.rect(ps, (*PUPIL_DARK, 255),
                                 pygame.Rect(4, 4, pr * 2, pr * 2),
                                 border_radius=pr // 2 + 2)
                sr = max(2, pr // 4)
                pygame.draw.circle(ps, (*IRIS_SHINE, 210),
                                   (4 + pr - pr // 2, 4 + pr - pr // 2), sr)
                eye.blit(ps, (px - pr - 4, py - pr - 4))

        surf.blit(eye, (rect.centerx - ew // 2, rect.centery - eh // 2))

        self._draw_brow(surf, rect, cx, int(self.w), angry, happy, sad, listening)

    def _draw_brow(self, surf, rect, cx, w, angry, happy, sad, listening):
        """Eyebrow drawn as a white shape on a small layer, then tinted with a
        vertical gradient (BROW_GRAD_TOP → BROW_GRAD_BOTTOM) so it reads as a
        lit strip like the eyes, not a flat line."""
        if self.blink_t <= 0.4:
            return
        brow_w  = int(w * 0.70)
        is_left = cx < WIDTH // 2
        LW, LH  = brow_w + 40, 48                 # tight layer: the gradient
        by      = LH // 2                          # spans the brow itself
        ox, oy  = cx - LW // 2, rect.top - 30 - by   # brow centre 30 px above eye
        lx0, lx1 = 20, 20 + brow_w
        layer = pygame.Surface((LW, LH), pygame.SRCALPHA)
        W = (255, 255, 255, 255)
        thick = 15

        if angry:
            sign = 1 if is_left else -1
            pygame.draw.line(layer, W, (lx0, by + sign * 10), (lx1, by - sign * 10), thick)
        elif happy:
            pygame.draw.arc(layer, W, pygame.Rect(lx0, by - 16, brow_w, 34),
                            math.radians(10), math.radians(170), 11)
        elif sad:
            droop_amt = int(self.droop * 14)
            if is_left:
                pygame.draw.line(layer, W, (lx0, by), (lx1, by - droop_amt), thick)
            else:
                pygame.draw.line(layer, W, (lx0, by - droop_amt), (lx1, by), thick)
        elif listening:
            lift = int(10 * self.widen)
            pygame.draw.rect(layer, W, pygame.Rect(lx0, by - lift - 7, brow_w, thick),
                             border_radius=7)
        else:
            pygame.draw.rect(layer, W, pygame.Rect(lx0, by - 7, brow_w, thick),
                             border_radius=7)

        # same domed shading as the eyes, masked by the brow shape
        layer.blit(gradient_sheet(LW, LH, BROW_GRAD_TOP, BROW_GRAD_BOTTOM,
                                  sheen=0.30, rim=0.30), (0, 0),
                   special_flags=pygame.BLEND_RGBA_MULT)
        # bloom that follows the brow's actual shape
        glow_layer = layer.copy()
        glow_layer.fill((*GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
        bloom(surf, glow_layer, (ox, oy), radius=8, passes=2, max_alpha=120)
        surf.blit(layer, (ox, oy))


# ── Hair (style extra) ────────────────────────────────────────────────────────
# A fringe of rounded tufts above the brows + a little cowlick. Each tuft is a
# domed gradient block so it matches the eyes; it sways with the head.
HAIR_TUFTS = [   # (x offset, y offset, w, h, tilt°) — overlapping → a fringe
    (-198, -146, 118, 54, -10),
    ( -99, -158, 122, 58,  -4),
    (   0, -164, 126, 60,   0),
    (  99, -158, 122, 58,   4),
    ( 198, -146, 118, 54,  10),
]
HAIR_COWLICK = (14, -204, 22, 52, 14)


def draw_hair(surf, fcx, fcy, sway):
    for (ox, oy, w, h, tilt) in HAIR_TUFTS + [HAIR_COWLICK]:
        block = gradient_block(w, h, min(w, h) // 2, HAIR_GRAD_TOP, HAIR_GRAD_BOTTOM)
        angle = tilt + sway * (0.5 if h < 70 else 0.3)
        img   = pygame.transform.rotate(block, angle) if abs(angle) > 0.5 else block
        rect  = img.get_rect(center=(fcx + ox + int(sway * 1.5), fcy + oy))
        draw_glow_rect(surf, GLOW_COL, pygame.Rect(rect.x + 8, rect.y + 8,
                                                   rect.w - 16, rect.h - 16),
                       radius=min(w, h) // 2, layers=3, max_alpha=30)
        surf.blit(img, rect)


# ── Costume: "Pokaż mi kotka" — ears, nose and whiskers on her own face ──────
# kind → (ears, whiskers). An ear: (dx past the eye centre, dy, w, h, tilt,
# triangle?) for the right side, mirrored for the left; the screen is short
# above the brows, so the cat's sit beside them and the bunny's between them.
# The face library (15 Oct) added the rest: googly eyes (gl_face.COSTUME_EYES),
# a squirrel, steampunk goggles and a hat, a crazy robot, a party.
COSTUMES = {
    "cat":   ([(95, -142, 116, 98, -9, True)], True),
    "bunny": ([(None, -150, 46, 124, -6, False)], True),     # None: 62 px off the middle
    "dog":   ([(175, 0, 78, 165, 12, False)], False),
    "squirrel": ([(108, -150, 78, 112, -14, False)], False),
    "googly_eyes": ([], False),
    "steampunk": ([], False),
    "crazy_robot": ([], False),
    "party": ([], False),
}
_NOSE = ("cat", "bunny", "dog", "squirrel")
BRASS_TOP, BRASS_BOTTOM = (255, 226, 150), (150, 92, 30)
HAT_TOP, HAT_BOTTOM = (92, 64, 46), (34, 22, 16)


# the inside of an ear, by costume
_EAR_INNER = {"cat": (255, 150, 160), "bunny": (255, 160, 175),
              "dog": (150, 80, 30), "squirrel": (170, 92, 40)}


def _ear(w, h, triangle, kind=None):
    """An ear: antialiased, the eyes' gold lit from above, a soft inner
    colour (pink for the cat and bunny) and a highlight down its edge."""
    key = ("ear", w, h, triangle, kind, EYE_GRAD_TOP, EYE_GRAD_BOTTOM)
    if key in _SMOOTH_CACHE:
        return _SMOOTH_CACHE[key]

    def draw(s, k):
        W, H = w * k, h * k
        if triangle:
            outer = [(W * 0.5, H * 0.03), (W * 0.97, H), (W * 0.03, H)]
            inner = [(W * 0.5, H * 0.30), (W * 0.76, H), (W * 0.24, H)]
        grad = pygame.Surface((W, H), pygame.SRCALPHA)
        for y in range(H):                        # gold, darker toward the root
            grad.fill((*_lerp_col(EYE_GRAD_TOP, EYE_GRAD_BOTTOM, (y / H) ** 1.3), 255),
                      pygame.Rect(0, y, W, 1))
        mask = pygame.Surface((W, H), pygame.SRCALPHA)
        if triangle:
            pygame.draw.polygon(mask, (255, 255, 255, 255), outer)
        else:
            pygame.draw.ellipse(mask, (255, 255, 255, 255), pygame.Rect(0, 0, W, H))
        grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        s.blit(grad, (0, 0))
        ic = _EAR_INNER.get(kind)
        if ic:
            dark = _lerp_col(ic, (60, 20, 10), 0.35)
            if triangle:
                pygame.draw.polygon(s, dark, inner)
                pygame.draw.polygon(s, ic, [(x, y + 0.05 * H) for x, y in inner])
            else:
                r = pygame.Rect(W * 0.27, H * 0.16, W * 0.46, H * 0.78)
                pygame.draw.ellipse(s, dark, r)
                pygame.draw.ellipse(s, ic, r.inflate(-W * 0.06, -H * 0.06).move(0, H * 0.03))
        hl = pygame.Surface((W, H), pygame.SRCALPHA)  # light down the upper-left edge
        pygame.draw.ellipse(hl, (255, 250, 225, 90),
                            pygame.Rect(W * 0.14, H * 0.10, W * 0.16, H * 0.45))
        s.blit(hl, (0, 0))
    img = _SMOOTH_CACHE[key] = _smooth(w, h, draw)
    return img


def _ear_twitch(kind, side):
    """Now and then one ear flicks (cat, bunny) — degrees, 0 most of the time."""
    if kind not in ("cat", "bunny", "squirrel"):
        return 0.0
    t = time.time() + (0.0 if side < 0 else 3.7)
    ph = t % 7.3
    return 14.0 * math.sin(math.pi * ph / 0.35) if ph < 0.35 else 0.0


_SMOOTH_CACHE = {}


def _smooth(w, h, draw, ss=3, key=None):
    """Something drawn 3× larger and scaled down: antialiased edges (kept
    when it has a key — the hats, the bulbs)."""
    if key is not None and key in _SMOOTH_CACHE:
        return _SMOOTH_CACHE[key]
    if key is not None:
        _SMOOTH_CACHE[key] = _smooth(w, h, draw, ss)
        return _SMOOTH_CACHE[key]
    big = pygame.Surface((w * ss, h * ss), pygame.SRCALPHA)
    draw(big, ss)
    return pygame.transform.smoothscale(big, (w, h))


def _blit_rot(surf, img, center, angle):
    if abs(angle) > 0.5:
        img = pygame.transform.rotate(img, angle)
    surf.blit(img, img.get_rect(center=(int(center[0]), int(center[1]))))


_TAIL = {}


def _bez(p0, p1, p2, p3, t):
    u = 1.0 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _tail_image():
    """A squirrel's tail: a thick S rising from below and curling over at
    the top, dark fur round a lighter middle, tufts all along its edge."""
    def draw(s, k):
        P = ((70, 500), (330, 450), (360, 120), (150, 70))
        n = 90
        pts = [_bez(*P, t=j / n) for j in range(n + 1)]
        rad = [32 + 78 * math.sin(math.pi * min(1.0, (j / n) ** 0.85 * 1.08)) for j in range(n + 1)]
        rad[-1] = rad[-2] = max(rad[-3], 40)
        mid = _lerp_col(HAIR_GRAD_BOTTOM, HAIR_GRAD_TOP, 0.45)
        for j in range(0, n + 1, 3):              # the fluffy edge: tufts pointing out
            x, y = pts[j]
            x2, y2 = pts[min(n, j + 1)]
            tx, ty = x2 - x, y2 - y
            ln = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / ln, tx / ln
            for side in (-1, 1):
                r = rad[j] * 1.08
                bx, by = x + nx * side * r * 0.82, y + ny * side * r * 0.82
                ex = x + nx * side * r * 1.18 - tx / ln * 14
                ey = y + ny * side * r * 1.18 - ty / ln * 14
                pygame.draw.polygon(s, HAIR_GRAD_BOTTOM, [
                    ((bx - tx / ln * 10) * k, (by - ty / ln * 10) * k),
                    ((bx + tx / ln * 10) * k, (by + ty / ln * 10) * k), (ex * k, ey * k)])
        for col, kr, off in ((HAIR_GRAD_BOTTOM, 1.0, 0), (mid, 0.74, -6), (HAIR_GRAD_TOP, 0.40, -12)):
            for j, (x, y) in enumerate(pts):
                pygame.draw.circle(s, col, (int((x + off) * k), int((y + off * 0.5) * k)),
                                   int(rad[j] * kr * k))
        for j in range(4, n - 4, 5):              # fur strokes down the middle
            x, y = pts[j]
            x2, y2 = pts[j + 3]
            pygame.draw.line(s, _lerp_col(mid, HAIR_GRAD_TOP, 0.5),
                             (int((x - 8) * k), int((y - 4) * k)),
                             (int((x2 - 4) * k), int((y2 - 6) * k)), int(3 * k))
    return _smooth(400, 560, draw, ss=2)


def _squirrel_tail(surf, fcx, fcy, sway):
    """A big bushy tail curling up beside her on the right, wagging."""
    img = _TAIL.get(CURRENT_STYLE)
    if img is None:
        img = _TAIL[CURRENT_STYLE] = pygame.transform.smoothscale(_tail_image(), (210, 294))
    wag = 5 * math.sin(time.time() * 2.2) + sway * 0.4
    _blit_rot(surf, img, (fcx + EYE_SPREAD + 150, fcy + 30), wag)


def _gear(r, teeth, col_top, col_bot):
    """A brass cog with a hole (cached by size)."""
    key = ("gear", r, teeth, col_top)
    if key in _SMOOTH_CACHE:
        return _SMOOTH_CACHE[key]

    def draw(s, k):
        c = (r + 6) * k
        pts = []
        for j in range(teeth * 4):
            a = j * math.tau / (teeth * 4)
            rr = r if (j // 2) % 2 == 0 else r * 0.80
            pts.append((c + math.cos(a) * rr * k, c + math.sin(a) * rr * k))
        pygame.draw.polygon(s, col_bot, pts)
        pygame.draw.circle(s, col_top, (int(c), int(c)), int(r * 0.70 * k))
        pygame.draw.circle(s, col_bot, (int(c), int(c)), int(r * 0.52 * k))
        pygame.draw.circle(s, (0, 0, 0, 0), (int(c), int(c)), int(r * 0.24 * k))
        for j in range(4):                         # spokes' holes
            a = j * math.tau / 4 + math.pi / 4
            pygame.draw.circle(s, (0, 0, 0, 0), (int(c + math.cos(a) * r * 0.40 * k),
                                                 int(c + math.sin(a) * r * 0.40 * k)),
                               int(r * 0.09 * k))
    img = _SMOOTH_CACHE[key] = _smooth(2 * r + 12, 2 * r + 12, draw)
    return img


def draw_costume_back(surf, fcx, fcy, kind, sway):
    """The ears (and the squirrel's tail, the robot's antennae), behind the eyes."""
    if kind == "squirrel":
        _squirrel_tail(surf, fcx, fcy, sway)
    ears = COSTUMES.get(kind, ([], False))[0]
    for (dx, oy, w, h, tilt, tri) in ears:
        for side in (-1, 1):
            ox = side * (62 if dx is None else EYE_SPREAD + dx)
            img = _ear(w, h, tri, kind)
            swing = 0.0
            if kind == "dog":                     # floppy: they swing with the head
                swing = 6.0 * math.sin(time.time() * 2.2 + side)
            img = pygame.transform.rotate(img, side * (tilt + _ear_twitch(kind, side))
                                          + sway * 0.4 + swing)
            rect = img.get_rect(center=(fcx + ox + int(sway * 1.5), fcy + oy))
            surf.blit(img, rect)
            if kind == "squirrel":                # a tuft on the tip
                tuft = gradient_block(20, 46, 10, HAIR_GRAD_TOP, HAIR_GRAD_BOTTOM)
                _blit_rot(surf, tuft, (rect.centerx + side * 10, rect.top + 8),
                          side * (tilt - 18))
    if kind == "crazy_robot":                     # two antennae with blinking bulbs
        t = time.time()
        for side, col in ((-1, (255, 140, 40)), (1, (90, 255, 130))):
            # from the bolts on the sides of her head (the top of the screen
            # is just above her brows)
            bx, by = fcx + side * (EYE_SPREAD + 168) + sway * 1.5, fcy - 64
            wob = 8 * math.sin(t * 5 + side)
            tx, ty = bx + side * 24 + wob, by - 110
            pts = []
            for k in range(13):                   # a spring
                u = k / 12
                px = bx + (tx - bx) * u + 9 * math.sin(u * math.tau * 3) * (1 - u * 0.3)
                pts.append((px, by + (ty - by) * u))
            pygame.draw.lines(surf, BRASS_BOTTOM, False, pts, 7)
            pygame.draw.lines(surf, BRASS_TOP, False, pts, 3)
            lit = round(0.6 + 0.4 * math.sin(t * 7 + side * 2), 1)
            bulb = _smooth(44, 44, lambda s, k, c=col, lit=lit: (
                pygame.draw.circle(s, (*c, int(80 * lit)), (22 * k, 22 * k), 21 * k),
                pygame.draw.circle(s, (*c, 255), (22 * k, 22 * k), 14 * k),
                pygame.draw.circle(s, (255, 255, 255, 220), (18 * k, 17 * k), 4 * k)),
                key=("bulb", col, lit))
            surf.blit(bulb, bulb.get_rect(center=(int(tx), int(ty))))


def _eye_frames(face, fcx, fcy):
    """Each eye's centre and its full open size (goggles don't blink)."""
    out = []
    for eye in (face.left_eye, face.right_eye):
        w = min(eye.w, EYE_SPREAD * 2 - 44)
        out.append((fcx + eye.rel_x + eye.pupil_ox * 0.30,
                    fcy + eye.rel_y + eye.pupil_oy * 0.30, w, eye.h))
    return out


def _goggles(surf, face, fcx, fcy, brass=True):
    """A thick ring round each eye, a bridge, rivets."""
    frames = _eye_frames(face, fcx, fcy)
    for (x, y, w, h) in frames:
        W, H = int(w + 34), int(h + 34)
        ring = gradient_block(W, H, 52, BRASS_TOP, BRASS_BOTTOM) if brass else \
            gradient_block(W, H, 52, (200, 205, 215), (80, 86, 100))
        ring = ring.copy()
        hole = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.rect(hole, (255, 255, 255, 255), hole.get_rect().inflate(-26, -26),
                         border_radius=42)
        ring.blit(hole, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
        surf.blit(ring, ring.get_rect(center=(int(x), int(y))))
        for a in range(8):                        # rivets
            ang = a * math.tau / 8 + math.pi / 8
            rx = x + math.cos(ang) * (W / 2 - 6)
            ry = y + math.sin(ang) * (H / 2 - 6)
            pygame.draw.circle(surf, (110, 66, 24) if brass else (60, 64, 76),
                               (int(rx), int(ry)), 4)
    (x0, y0, w0, _), (x1, y1, w1, _) = frames
    bridge = gradient_block(int(x1 - x0 - (w0 + w1) / 2 - 20), 18, 9,
                            BRASS_TOP if brass else (200, 205, 215),
                            BRASS_BOTTOM if brass else (80, 86, 100))
    surf.blit(bridge, bridge.get_rect(center=(int((x0 + x1) / 2), int((y0 + y1) / 2))))


def _top_hat(surf, cx, cy, angle):
    def draw(s, k):
        W = s.get_width()
        crown = pygame.Rect(0, 0, 118 * k, 92 * k)
        crown.midbottom = (W // 2, 112 * k)
        pygame.draw.rect(s, HAT_BOTTOM, crown, border_radius=12 * k)
        pygame.draw.rect(s, HAT_TOP, crown.inflate(-16 * k, -14 * k), border_radius=9 * k)
        band = pygame.Rect(crown.x, crown.bottom - 26 * k, crown.w, 18 * k)
        pygame.draw.rect(s, BRASS_BOTTOM, band)
        pygame.draw.rect(s, BRASS_TOP, band.inflate(0, -8 * k))
        pygame.draw.circle(s, (255, 236, 170), (band.right - 22 * k, band.centery), 7 * k)
        brim = pygame.Rect(0, 0, 190 * k, 24 * k)
        brim.midtop = (W // 2, 106 * k)
        pygame.draw.ellipse(s, HAT_BOTTOM, brim)
        pygame.draw.ellipse(s, HAT_TOP, brim.inflate(-10 * k, -10 * k))
    _blit_rot(surf, _smooth(200, 140, draw, key="top_hat"), (cx, cy), angle)


def _party_hat(surf, cx, cy, angle):
    def draw(s, k):
        W = s.get_width()
        base, tip = 128 * k, 18 * k
        pts = [(W // 2, tip), (W // 2 + 54 * k, base), (W // 2 - 54 * k, base)]
        pygame.draw.polygon(s, (255, 110, 160), pts)
        for j, col in enumerate(((255, 220, 90), (110, 200, 255), (255, 220, 90))):
            y = tip + (base - tip) * (0.32 + 0.24 * j)
            half = 54 * k * (y - tip) / (base - tip)
            pygame.draw.polygon(s, col, [(W // 2 - half, y), (W // 2 + half, y),
                                         (W // 2 + half * 1.08, y + 12 * k),
                                         (W // 2 - half * 1.08, y + 12 * k)])
        pygame.draw.circle(s, (255, 250, 230), (W // 2, tip), 15 * k)      # the pompom
        pygame.draw.ellipse(s, (255, 220, 90),
                            pygame.Rect(W // 2 - 62 * k, base - 8 * k, 124 * k, 18 * k))
    _blit_rot(surf, _smooth(140, 150, draw, key="party_hat"), (cx, cy), angle)


_CONFETTI = [(0.07 * i % 1.0, (i * 0.618) % 1.0, i) for i in range(28)]
_CONFETTI_COLS = ((255, 110, 160), (255, 220, 90), (110, 200, 255), (140, 255, 150),
                  (200, 140, 255))


def _confetti(surf):
    t = time.time()
    for x0, ph, i in _CONFETTI:
        y = ((ph + t * (0.10 + 0.03 * (i % 4))) % 1.1) * HEIGHT - 20
        x = ((x0 + i * 0.137) % 1.0) * WIDTH + 22 * math.sin(t * 1.3 + i)
        a = t * (2 + i % 3) + i
        dx, dy = math.cos(a) * 9, math.sin(a) * 4
        col = _CONFETTI_COLS[i % len(_CONFETTI_COLS)]
        pygame.draw.polygon(surf, col, [(x - dx, y - dy - 3), (x + dx, y + dy - 3),
                                        (x + dx, y + dy + 3), (x - dx, y - dy + 3)])


def draw_costume_front(surf, fcx, fcy, kind, face=None):
    """The nose and the whiskers, between the eyes and the mouth — and the
    goggles, hats, bolts and confetti that sit over the face."""
    if kind not in COSTUMES:
        return
    if kind in _NOSE:
        nose = gradient_block(44, 30, 14, EYE_GRAD_TOP, EYE_GRAD_BOTTOM)
        ny = face_spec.LAYOUT["nose_y"]
        surf.blit(nose, nose.get_rect(center=(fcx, fcy + ny)))
    if COSTUMES[kind][1]:
        for side in (-1, 1):
            for dy, tip in ((-8, -26), (6, 0), (20, 26)):
                pygame.draw.line(surf, MOUTH_COL, (fcx + side * 70, fcy + ny + 8 + dy),
                                 (fcx + side * 230, fcy + ny + 8 + dy + tip), 5)
    if kind == "squirrel":                        # two big front teeth
        for side in (-1, 1):
            tooth = gradient_block(20, 28, 6, (255, 252, 240), (220, 210, 190))
            surf.blit(tooth, tooth.get_rect(
                midtop=(fcx + side * 11, fcy + face_spec.LAYOUT["mouth_y"] + 10)))
    elif kind == "steampunk" and face is not None:
        _goggles(surf, face, fcx, fcy)
        _top_hat(surf, fcx + EYE_SPREAD + 150, fcy - 140, -18)   # on the top corner
        t = time.time()                           # two cogs turning on the other corner
        for (gx, gy, r, n, spin) in ((-EYE_SPREAD - 170, -130, 44, 10, 0.6),
                                     (-EYE_SPREAD - 112, -76, 28, 7, -0.6 * 44 / 28)):
            g = _gear(r, n, BRASS_TOP, BRASS_BOTTOM)
            _blit_rot(surf, g, (fcx + gx, fcy + gy), math.degrees(t * spin))
    elif kind == "crazy_robot" and face is not None:
        _goggles(surf, face, fcx, fcy, brass=False)
        for side in (-1, 1):                      # bolts on the sides of her head
            bolt = gradient_block(46, 92, 16, (200, 205, 215), (80, 86, 100))
            surf.blit(bolt, bolt.get_rect(center=(fcx + side * (EYE_SPREAD + 168), fcy - 20)))
            pygame.draw.circle(surf, (60, 64, 76), (fcx + side * (EYE_SPREAD + 168), fcy - 20), 9)
    elif kind == "party":
        _confetti(surf)
        _party_hat(surf, fcx - EYE_SPREAD - 150, fcy - 132, 24)


# ── Hands (style extra) ───────────────────────────────────────────────────────
# Rounded "mitten" hands drawn as gradient blocks. Poses:
#   open       — palm + 4 fingers + thumb (waving, heart)
#   thumb      — fist with the thumb up;  thumb_down — the same, upside down
#   fist       — all fingers curled
#   point      — fist with the index finger up (drawing in the air)
#   ok         — thumb and index make a ring, three fingers up
#   scissors   — index and middle finger in a V (rock-paper-scissors)
def hand_surface(pose, side):
    """Cached hand image for a pose; side 'L'/'R' mirrors it. Drawn 3× and
    scaled down (smooth edges); one light across the whole hand, so the
    fingers join the palm without seams; a darker crease round each part;
    the glow and a soft shadow baked in (no bloom per frame)."""
    key = (pose, side)
    s = _HAND_CACHE.get(key)
    if s is not None:
        return s
    S, K, P = 1.6, 3, 16                      # hand scale, supersampling, padding (px)
    W_, H_ = int(120 * S), int(150 * S)
    big = pygame.Surface(((W_ + 2 * P) * K, (H_ + 2 * P) * K), pygame.SRCALPHA)
    top, bot = HAND_GRAD_TOP, HAND_GRAD_BOTTOM
    crease = _lerp_col(bot, (70, 25, 0), 0.55)

    def at(y):                                # the hand's light at height y (0..150)
        return _lerp_col(top, bot, max(0.0, min(1.0, y / 150.0)) ** 1.1)

    def block(w, h, r, cx, cy, angle=0):
        sc = S * K
        edge = gradient_block(int((w + 3) * sc), int((h + 3) * sc), int((r + 1.5) * sc),
                              crease, crease)
        fill = gradient_block(int(w * sc), int(h * sc), int(r * sc),
                              at(cy - h / 2), at(cy + h / 2))
        for b in (edge, fill):
            if angle:
                b = pygame.transform.rotate(b, angle)
            big.blit(b, b.get_rect(center=(int((cx * S + P) * K), int((cy * S + P) * K))))

    if pose == "fist":
        block(66, 76, 22, 62, 106)                 # the fist
        for i in range(4):                         # curled fingers
            block(52, 15, 7, 66, 84 + i * 15)
    elif pose == "point":
        block(17, 62, 8, 44, 60)                   # index finger (base under the fist)
        block(66, 76, 22, 62, 106)                 # fist
        for i in range(3):                         # the other three, curled
            block(52, 15, 7, 68, 99 + i * 15)
        block(18, 34, 8, 36, 104, 60)              # thumb folded across
    elif pose == "scissors":
        block(16, 60, 7, 42, 60, 14)               # index, leaning out
        block(16, 62, 7, 62, 58, -14)              # middle, the other way
        block(66, 76, 22, 62, 106)                 # fist
        for i in range(2):                         # ring + pinky, curled
            block(52, 15, 7, 68, 108 + i * 15)
        block(18, 34, 8, 36, 104, 60)              # thumb folded across
    elif pose == "ok":
        for dx, fh in ((12, 52), (28, 48), (42, 40)):   # middle, ring, pinky up
            block(16, fh, 7, 54 + dx, 80 - (fh - 40) // 2)
        block(66, 70, 26, 62, 110)                 # palm
        c = (int((36 * S + P) * K), int((68 * S + P) * K))
        pygame.draw.circle(big, (*crease, 255), c, int(24.5 * S * K))
        ring = gradient_block(int(46 * S * K), int(46 * S * K), int(23 * S * K),
                              at(45), at(91)).copy()
        big.blit(ring, ring.get_rect(center=c))
        pygame.draw.circle(big, (*crease, 255), c, int(12.5 * S * K))
        pygame.draw.circle(big, (0, 0, 0, 0), c, int(11 * S * K))   # thumb + index: the "O"
    elif pose in ("thumb", "thumb_down"):
        block(24, 62, 12, 34, 64, 6)               # thumb up (base under the fist)
        block(66, 76, 22, 62, 106)                 # fist
        for i in range(4):                         # curled fingers: horizontal
            block(52, 15, 7, 66, 84 + i * 15)      # segments stacked down the fist
    else:                                          # open palm
        # thumb first so its base sits UNDER the palm (attached, not floating)
        block(20, 50, 9, 24, 88, 30)              # base under the palm, tip leaning out
        block(66, 70, 26, 60, 108)                 # palm
        for i, (dx, fh) in enumerate(((-24, 44), (-8, 52), (8, 50), (24, 42))):
            block(16, fh, 7, 60 + dx, 78 - (fh - 40) // 2)
    BW, BH = big.get_size()
    # the glow round it and a soft shadow below-right, under the hand
    sil = big.copy()
    sil.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MIN)    # (black, its alpha)
    soft = pygame.transform.smoothscale(
        pygame.transform.smoothscale(sil, (BW // 16, BH // 16)), (BW, BH))
    glow = soft.copy()
    glow.fill((*GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)     # (colour; alpha kept)
    glow.fill((255, 255, 255, 90), special_flags=pygame.BLEND_RGBA_MULT)
    out = pygame.Surface((BW, BH), pygame.SRCALPHA)
    out.blit(glow, (0, 0))
    soft.fill((255, 255, 255, 120), special_flags=pygame.BLEND_RGBA_MULT)
    out.blit(soft, (5 * K, 9 * K))
    out.blit(big, (0, 0))
    s = pygame.transform.smoothscale(out, (BW // K, BH // K))
    if pose == "thumb_down":
        s = pygame.transform.flip(s, False, True)
    if side == "L":
        s = pygame.transform.flip(s, True, False)
    _HAND_CACHE[key] = s
    return s


_ARC_CACHE = {}


def _arc_img(r, col, side):
    """One ")" (side 1) or "(" of radius r: a crescent thickest in the
    middle, thin at the ends, in a soft glow (antialiased, cached by r)."""
    key = (r, col, side)
    img = _ARC_CACHE.get(key)
    if img is None:
        if len(_ARC_CACHE) > 300:
            _ARC_CACHE.clear()
        k, pad = 3, 14
        W, H = (r + 2 * pad) * k, (2 * r + 2 * pad) * k
        big = pygame.Surface((W, H), pygame.SRCALPHA)
        cx = pad * k if side > 0 else W - pad * k     # the arc's centre, off to one side
        cy = H / 2
        span, T = 0.80, 7.0                          # ±46°; 7 px at the middle
        outer, inner = [], []
        for j in range(41):
            u = j / 40.0
            a = -span + 2 * span * u
            t = T * (0.25 + 0.75 * math.sin(math.pi * u))
            dx, dy = math.cos(a) * side, math.sin(a)
            outer.append((cx + dx * (r + t / 2) * k, cy + dy * (r + t / 2) * k))
            inner.append((cx + dx * (r - t / 2) * k, cy + dy * (r - t / 2) * k))
        poly = outer + inner[::-1]
        glow = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.polygon(glow, (*col, 255), poly)
        glow = pygame.transform.smoothscale(
            pygame.transform.smoothscale(glow, (W // 12, H // 12)), (W, H))
        glow.set_alpha(110)
        big.blit(glow, (0, 0))
        pygame.draw.polygon(big, (*_lerp_col(col, (255, 255, 255), 0.25), 255), poly)
        img = pygame.transform.smoothscale(big, (W // k, H // k))
        img = (img, pad if side > 0 else W // k - pad)    # (and where its centre is)
        _ARC_CACHE[key] = img
    return img


def twinkle(surf, x, y, r, alpha, col=None):
    """A soft four-pointed sparkle (antialiased, cached by size): the few
    that belong to an expression, not confetti."""
    r = max(4, int(r) // 2 * 2)
    col = col or IRIS_SHINE
    key = ("twinkle", r, col)
    img = _SMOOTH_CACHE.get(key)
    if img is None:
        def draw(s, k, r=r):
            c = (r + 4) * k
            pts = []
            for j in range(8):
                a = j * math.pi / 4 - math.pi / 2
                rr = r if j % 2 == 0 else r * 0.22
                pts.append((c + math.cos(a) * rr * k, c + math.sin(a) * rr * k))
            pygame.draw.circle(s, (*GLOW_COL, 60), (int(c), int(c)), int(r * 0.55 * k))
            pygame.draw.polygon(s, (*col, 255), pts)
        img = _SMOOTH_CACHE[key] = _smooth(2 * r + 8, 2 * r + 8, draw)
    img.set_alpha(int(max(0, min(255, alpha))))
    surf.blit(img, img.get_rect(center=(int(x), int(y))))


def draw_side_arcs(surf, cx, cy, dx, arcs, col):
    """")" on the right, "(" on the left, dx from the middle — sound coming
    in, a head moving. arcs: (radius, alpha 0..1); antialiased, glowing."""
    for r, a in arcs:
        if a <= 0.01:
            continue
        r = max(8, int(r) // 2 * 2)
        for side in (-1, 1):
            img, ox = _arc_img(r, col, side)
            img.set_alpha(int(255 * min(1.0, a)))
            # its centre of curvature sits at the eye's side, dx out from the middle
            x = cx + side * dx - ox
            surf.blit(img, (int(x), int(cy - img.get_height() / 2)))


def _heart_img(size):
    """A glossy heart (antialiased, shaded, cached by size): darker below,
    a soft highlight on the upper left lobe, a thin bright rim."""
    size = max(6, int(size) // 2 * 2)
    key = ("heart", size, HEART_COL)
    img = _SMOOTH_CACHE.get(key)
    if img is not None:
        return img
    W = 2 * size + 8

    def draw(s, k):
        pts = []
        sc = size / 17.0 * k
        cx, cy = W * k / 2, (W * k) / 2 + 2 * sc
        for j in range(72):
            t = j * math.tau / 72
            x = 16 * math.sin(t) ** 3
            y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
            pts.append((cx + x * sc, cy - y * sc))
        dark = _lerp_col(HEART_COL, (120, 20, 50), 0.45)
        pygame.draw.polygon(s, dark, pts)
        inner = [(cx + (x - cx) * 0.86, cy + (y - cy) * 0.86 - 1.2 * sc) for x, y in pts]
        pygame.draw.polygon(s, HEART_COL, inner)
        pygame.draw.ellipse(s, _lerp_col(HEART_COL, (255, 255, 255), 0.55),
                            pygame.Rect(cx - 10 * sc, cy - 11 * sc, 6 * sc, 4.5 * sc))
    img = _SMOOTH_CACHE[key] = _smooth(W, W, draw)
    return img


def draw_heart(surf, cx, cy, size, alpha=255):
    """A heart whose lobes sit at (cx, cy), size ~ its half width."""
    img = _heart_img(size)
    if alpha < 255:
        img = img.copy()
        img.set_alpha(int(max(0, alpha)))
    surf.blit(img, img.get_rect(center=(int(cx), int(cy + size * 0.38))))


# ── Mouth ─────────────────────────────────────────────────────────────────────
class Mouth:
    def __init__(self, rel_x, rel_y):
        self.rel_x        = rel_x
        self.rel_y        = rel_y
        self.talk_open    = 0.0
        self.mouth_w      = 140.0
        self.visible      = 0.0
        self.speak_fade   = 0.0   # 1 while talking, decays after — without it
                                  # the mouth vanished in one frame when speech
                                  # ended (the "not speaking" branch draws
                                  # nothing at all for a neutral face)
        self.corner_lift  = 0.0   # smile corners
        self.jaw_bounce   = 0.0   # extra bounce on high energy
        self.prev_energy  = 0.0

    def update(self, energy, emotion, speaking):
        # fast to open, slow to let go — the tail is what reads as a fade
        self.speak_fade = ease(self.speak_fade, 1.0 if speaking else 0.0,
                               0.35 if speaking else 0.09)
        if speaking:
            target_visible = 1.0
        elif emotion in ("happy", "excited", "love"):
            target_visible = 0.85
        elif emotion in ("surprised", "sad", "angry"):
            target_visible = 0.7
        elif emotion == "sleeping":
            target_visible = 0.5
        else:
            target_visible = 0.0

        target_visible    = max(target_visible, self.speak_fade)
        self.visible      = ease(self.visible, target_visible, 0.20)  # faster open
        self.corner_lift  = ease(self.corner_lift,
                                    0.8 if emotion in ("happy", "excited", "love")
                                    else 0.0, 0.08)

        if speaking:
            # use energy directly but floor at 0.15 so mouth is never fully closed
            # while speaking — prevents dead mouth between words
            effective_energy = max(0.04, energy)   # real lip sync: pauses close the mouth
            target_open      = effective_energy
            self.talk_open   = ease(self.talk_open, target_open, 0.55)   # (TTS smooths it)
            self.mouth_w     = ease(self.mouth_w,
                                    190.0 if energy > 0.5 else 150.0, 0.12)
            delta = energy - self.prev_energy
            if delta > 0.15 * min(1.0, _K):         # (a jump within a tuned frame)
                self.jaw_bounce = min(1.0, self.jaw_bounce + delta * 2)
            self.jaw_bounce = ease(self.jaw_bounce, 0.0, 0.20)
        else:
            self.talk_open  = ease(self.talk_open, 0.0, 0.15)
            self.jaw_bounce = 0.0

        self.prev_energy = energy

    def _draw_bars(self, surf, cx, cy, alpha):
        """Robotic talking mouth — 7 equalizer bars driven by audio energy."""
        n, bw, gap = 7, 16, 10
        total = n * bw + (n - 1) * gap
        t = time.time() * 9.0
        e = max(0.12, self.talk_open)
        for i in range(n):
            # centre bars taller; per-bar phase offset makes it dance
            centre = 1.0 - abs(i - (n - 1) / 2) / ((n - 1) / 2) * 0.45
            h = 10 + e * 78 * centre * (0.55 + 0.45 * abs(math.sin(t + i * 0.9)))
            h = int(h)
            x = cx - total // 2 + i * (bw + gap)
            bar = pygame.Rect(x, cy - h // 2, bw, h)
            pygame.draw.rect(surf, (*MOUTH_COL[:3],), bar, border_radius=4)
            # bright tip
            tip = pygame.Rect(x, cy - h // 2, bw, max(3, h // 5))
            ts  = pygame.Surface((bw, tip.h), pygame.SRCALPHA)
            pygame.draw.rect(ts, (*TEETH_COL, int(alpha * 0.8)),
                             ts.get_rect(), border_radius=3)
            surf.blit(ts, (tip.x, tip.y))

    def draw(self, surf, cx, cy, emotion, speaking, audio_energy):
        if self.visible < 0.02:
            return

        alpha = int(clamp(self.visible * 255, 0, 255))

        # Keep drawing the talking mouth briefly after speech ends: talk_open
        # is already easing to 0, so the lips close and then fade.
        talking = speaking or self.speak_fade > 0.05

        # ── SPEAKING — robotic bars or 4-shape jaw ────────────────────────
        if talking and MOUTH_STYLE == "bars":
            self._draw_bars(surf, cx, cy, alpha)
            return

        if talking:
            mw = int(self.mouth_w)
            e  = self.talk_open

            if e > 0.55:
                # OPEN JAW — lips (outer rounded rect), dark interior inset,
                # teeth as a strip INSIDE the interior under the upper lip
                mh = max(20, int((e + self.jaw_bounce * 0.3) * 90))
                mouth_r = pygame.Rect(cx - mw // 2, cy - mh // 2, mw, mh)
                draw_glow_rect(surf, GLOW_COL, mouth_r, radius=26, layers=4,
                               max_alpha=50)
                ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
                pygame.draw.rect(ms, (*MOUTH_COL, alpha),
                                 ms.get_rect(), border_radius=22)
                # dark interior
                lip = 8
                ir  = pygame.Rect(lip, lip, mw - lip * 2, mh - lip * 2)
                if ir.w > 6 and ir.h > 4:
                    pygame.draw.rect(ms, (*PUPIL_COL, alpha), ir,
                                     border_radius=16)
                    # teeth: upper ~30 % of the interior, rounded at the
                    # bottom only, slightly inset from the interior's sides
                    th = max(6, int(ir.h * 0.30))
                    tr = pygame.Rect(ir.x + 6, ir.y, ir.w - 12, th)
                    pygame.draw.rect(ms, (*TEETH_COL, int(alpha * 0.85)), tr,
                                     border_bottom_left_radius=10,
                                     border_bottom_right_radius=10)
                    # tooth gaps
                    n = 5
                    for i in range(1, n):
                        gx = tr.x + tr.w * i // n
                        pygame.draw.line(ms, (*PUPIL_COL, int(alpha * 0.55)),
                                         (gx, tr.y + 2), (gx, tr.bottom - 3), 2)
                surf.blit(ms, (cx - mw // 2, cy - mh // 2))

            elif e > 0.28:
                # MID OPEN — rounded oval
                mh = max(14, int(e * 70))
                ms = pygame.Surface((mw, mh), pygame.SRCALPHA)
                pygame.draw.ellipse(ms, (*MOUTH_COL, alpha), ms.get_rect())
                surf.blit(ms, (cx - mw // 2, cy - mh // 2))
                # small interior
                iw, ih = max(8, mw - 24), max(4, mh - 10)
                is_ = pygame.Surface((iw, ih), pygame.SRCALPHA)
                pygame.draw.ellipse(is_, (*PUPIL_COL, alpha), is_.get_rect())
                surf.blit(is_, (cx - iw // 2, cy - ih // 2))

            elif e > 0.08:
                # PURSED — small tight oval
                pw, ph = max(40, int(mw * 0.45)), max(8, int(e * 40))
                ps = pygame.Surface((pw, ph), pygame.SRCALPHA)
                pygame.draw.ellipse(ps, (*MOUTH_COL, alpha), ps.get_rect())
                surf.blit(ps, (cx - pw // 2, cy - ph // 2))

            else:
                # CLOSED — thin line with slight curve. Drawn on its own
                # surface so it honours alpha: painted straight onto the
                # canvas it stayed at full brightness and the mouth never
                # faded out after speech.
                cl = int(self.corner_lift * 8)
                pad = 12
                ls = pygame.Surface((160, 2 * pad + 20), pygame.SRCALPHA)
                pts = [
                    (10,  pad + cl),
                    (60,  pad - cl // 2),
                    (80,  pad - cl),
                    (100, pad - cl // 2),
                    (150, pad + cl),
                ]
                pygame.draw.lines(ls, (*MOUTH_COL, alpha), False, pts, 10)
                surf.blit(ls, (cx - 80, cy - pad))
            return

        # ── NOT SPEAKING ──────────────────────────────────────────────────
        if self.visible < 0.05:
            return

        if emotion in ("happy", "excited", "love"):
            # curved smile — lerp visible
            aw, ah = 260, 130
            ar = pygame.Rect(cx - aw // 2, cy - ah // 2, aw, ah)
            smile_surf = pygame.Surface((aw, ah), pygame.SRCALPHA)
            pygame.draw.arc(smile_surf, (*MOUTH_COL, alpha),
                            pygame.Rect(0, 0, aw, ah),
                            math.radians(200), math.radians(340), 22)
            surf.blit(smile_surf, (cx - aw // 2, cy - ah // 2))

        elif emotion == "surprised":
            # small "o" of surprise (was disabled upstream, which left the
            # surprised face with no mouth at all)
            r  = 44
            os_ = pygame.Surface((r * 2 + 6, r * 2 + 6), pygame.SRCALPHA)
            draw_glow_circle(os_, GLOW_COL, (r + 3, r + 3), r)
            pygame.draw.circle(os_, (*MOUTH_COL, alpha), (r + 3, r + 3), r)
            pygame.draw.circle(os_, (*PUPIL_COL, alpha), (r + 3, r + 3),
                               int(r * 0.6))
            surf.blit(os_, (cx - r - 3, cy - r - 3))

        elif emotion == "angry":
            # flat tight line angled
            as_ = pygame.Surface((240, 40), pygame.SRCALPHA)
            pygame.draw.line(as_, (*MOUTH_COL, alpha),
                             (10, 28), (230, 12), 18)
            pygame.draw.line(as_, (*EYE_INNER, int(alpha * 0.5)),
                             (10, 28), (230, 12), 5)
            surf.blit(as_, (cx - 120, cy - 20))

        elif emotion == "sad":
            # downward curve
            aw, ah = 200, 100
            ss = pygame.Surface((aw + 4, ah + 4), pygame.SRCALPHA)
            pygame.draw.arc(ss, (*MOUTH_COL, alpha),
                            pygame.Rect(2, 2, aw, ah),
                            math.radians(20), math.radians(160), 18)
            surf.blit(ss, (cx - aw // 2 - 2, cy + 4))

        elif emotion == "sleeping":
            # small peaceful closed curve
            sw = 160
            sl = pygame.Surface((sw + 4, 30), pygame.SRCALPHA)
            pts = [(2, 20), (sw // 4, 10), (sw // 2, 6),
                   (sw * 3 // 4, 10), (sw + 2, 20)]
            pygame.draw.lines(sl, (*MOUTH_COL, int(alpha * 0.6)),
                              False, pts, 8)
            surf.blit(sl, (cx - sw // 2 - 2, cy - 10))


# ── Micro-expression engine ───────────────────────────────────────────────────
class MicroExpressions:
    def __init__(self):
        self.squint_target  = 0.0
        self.widen_target   = 0.0
        self.droop_target   = 0.0
        self.pupil_scale    = 1.0
        self.next_micro_t   = time.time() + random.uniform(3, 8)
        self.micro_end_t    = 0.0
        self.current_micro  = None

    def update(self, emotion, listening, speaking, moods=True):
        now = time.time()

        if speaking:
            self.squint_target = 0.0
            self.widen_target  = 0.0
            self.droop_target  = 0.0
            self.pupil_scale   = 1.0
            return

        if listening and moods:
            self.widen_target  = 0.6
            self.squint_target = 0.0
            self.droop_target  = 0.0
            self.pupil_scale   = 1.15
            return

        # random idle micro-expressions
        if now > self.next_micro_t:
            self.next_micro_t = now + random.uniform(4, 12)
            self.micro_end_t  = now + random.uniform(0.8, 2.0)
            self.current_micro = random.choice([
                "squint", "widen", "pupil_dilate", "neutral"
            ])

        if now < self.micro_end_t and self.current_micro:
            if self.current_micro == "squint":
                self.squint_target = 0.5
                self.widen_target  = 0.0
                self.pupil_scale   = 0.9
            elif self.current_micro == "widen":
                self.widen_target  = 0.7
                self.squint_target = 0.0
                self.pupil_scale   = 1.2
            elif self.current_micro == "pupil_dilate":
                self.pupil_scale   = 1.3
                self.squint_target = 0.0
                self.widen_target  = 0.1
            else:
                self.squint_target = 0.0
                self.widen_target  = 0.0
                self.pupil_scale   = 1.0
        else:
            self.squint_target = 0.0
            self.widen_target  = 0.0
            self.pupil_scale   = 1.0
            self.current_micro = None

        # emotion base modifiers
        if not moods:
            self.droop_target = 0.0
        elif emotion in ("happy", "love"):
            self.squint_target = max(self.squint_target, 0.35)
            self.droop_target  = 0.0
        elif emotion == "excited":
            self.widen_target  = max(self.widen_target, 0.8)
            self.pupil_scale   = max(self.pupil_scale, 1.3)
            self.droop_target  = 0.0
        elif emotion == "surprised":
            self.widen_target  = max(self.widen_target, 0.85)
            self.pupil_scale   = max(self.pupil_scale,  1.25)
            self.droop_target  = 0.0
        elif emotion == "angry":
            self.squint_target = max(self.squint_target, 0.45)
            self.droop_target  = 0.0
        elif emotion == "sad":
            self.droop_target  = 1.0
            self.squint_target = 0.0
            self.widen_target  = 0.0
            self.pupil_scale   = 0.9
        else:
            self.droop_target  = 0.0


# ── RobotFace ─────────────────────────────────────────────────────────────────
# where a frame's time goes (main.py's SIGUSR1 dump)
frame_stats = {"frames": 0, "update": 0.0, "face": 0.0, "compose": 0.0, "flip": 0.0,
               "tilted": 0, "gl": 0.0, "swap": 0.0, "fps": {}, "gaps": [0] * 6, "_t": 0.0}


def _count_present(st, now):
    """How long the last frame stayed up, in 60 Hz refreshes (1, 2, 3…) —
    uneven counts are what a judder looks like."""
    if st["_t"]:
        n = int((now - st["_t"]) * 60.03 + 0.5)
        st["gaps"][max(0, min(5, n))] += 1
    st["_t"] = now


class RobotFace:

    _WAKE_NONE   = 0
    _WAKE_ACTIVE = 1

    def __init__(self):
        pygame.init()
        flags = pygame.FULLSCREEN if FULLSCREEN else 0
        self.gl = None
        if FACE_GL:
            # the window is OpenGL's; everything pygame draws goes to a
            # transparent layer (self.screen) laid over the GPU face
            try:
                pygame.display.set_mode((WIDTH, HEIGHT),
                                        flags | pygame.OPENGL | pygame.DOUBLEBUF)
                self.gl = gl_face.GLFace(WIDTH, HEIGHT)
            except Exception as e:                     # noqa: BLE001
                print(f"[gl] no OpenGL face ({e!r}) — the usual one", flush=True)
                self.gl = None
        if self.gl:
            self.screen = gl_face.layer_surface(WIDTH, HEIGHT)
        else:
            self.screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
        pygame.display.set_caption("Luna")
        if HIDE_CURSOR:
            pygame.mouse.set_visible(False)
        self.clock  = pygame.time.Clock()
        import statusbar
        self.status_bar = statusbar.StatusBar()

        self.state        = "neutral"
        self.visual_state = "neutral"
        self.prev_state   = "neutral"

        self.face_cx   = float(WIDTH  // 2)
        self.face_cy   = float(HEIGHT // 2 + FACE_Y_OFFSET)
        self.face_ox   = 0.0
        self.face_oy   = 0.0
        self.target_ox = 0.0
        self.target_oy = 0.0

        self.breath_phase  = 0.0
        self.blink_timer   = random.randint(100, 220)
        self.blink_counter = 0
        self.blink_open    = 1.0

        self.pupil_ox = 0.0
        self.pupil_oy = 0.0

        self.head_angle  = 0.0
        self.target_tilt = 0.0

        self.curiosity_target_x = 0.0
        self.curiosity_target_y = 0.0
        self.curiosity_timer    = 0

        self.listen_pulse = 0.0
        self.listen_phase = 0.0

        self.angry_pulse       = 0.0
        self.angry_pulse_phase = 0.0

        self.idle_frames   = 0
        self.wake_anim     = self._WAKE_NONE
        self.wake_ripple   = 0.0

        # conversation-mode indicator: soft dot below the mouth while the
        # wake window is open; a slow dim blink plays when it times out
        self.awake_glow   = 0.0    # 0–1, lerps with conversation_active
        self.rest_pulse   = 0.0    # 1 → 0 decay right after a timeout
        self._last_expire = 0.0

        # reused every frame — allocating a full-screen Surface per frame
        # was measurable on the Pi
        self.base = (gl_face.layer_surface(WIDTH, HEIGHT) if self.gl
                     else pygame.Surface((WIDTH, HEIGHT)))
        # with the GPU face: what pygame draws behind it (costume ears, hair,
        # steam, sound waves) — the face goes between this and `base`
        self.back = gl_face.layer_surface(WIDTH, HEIGHT) if self.gl else None

        # particle systems
        self.zzz_particles   = []
        self.zzz_spawn_t     = 0
        self.tear_particles  = []
        self.tear_spawn_t    = 0
        self.steam_particles = []
        self.steam_spawn_t   = 0
        self.star_particles  = []
        self.star_spawned    = False
        self.sound_waves     = []
        self.wave_spawn_t    = 0
        self.heart_particles = []
        self.heart_spawn_t   = 0
        self.excite_spawn_t  = 0

        # cute bounce when turning happy/excited/love
        self.bounce_phase  = 0.0
        self.bounce_amp    = 0.0

        # hands: current (lerped) position + angle per side, and the pose
        self.hand = {"L": [-320.0, 420.0, 0.0], "R": [320.0, 420.0, 0.0]}
        self.hand_pose = {"L": "open", "R": "open"}
        self._hand_target = {"L": (-320.0, 420.0, 0.0), "R": (320.0, 420.0, 0.0)}
        self._gesture = None
        self._gesture_p = 0.0
        self._heart_pulse = 0.0

        # reply scenes + touch
        self._scene_name = None
        self._scene_p = 0.0
        self._scene = None
        self._pupil_converge = 0.0
        self._pupil_mul = 1.0            # scenes: 0 hides the pupils, 2 = huge
        self._big_text = None            # (text, until) — game countdown
        self.fps = RENDER_FPS            # frames drawn a second (face_renderer sets both)
        self.anim_fps = RENDER_FPS       # …and the pace the animation's steps were tuned at
        self._mouth_drive = 0.0
        self._wink_side = "R"
        self._scene_prev = None
        self._touch_t = 0.0
        self._touch_zone = None
        self._touch_kind = None
        self._touch_react_t = -99.0
        self._touch_pull = 0.0
        self._think_t = 0.0              # since when she has been thinking
        self._spec_mod = {}
        self._drowsy = 0.0               # 0..1 as she nods off
        self._face_seen = False
        self._costume = None             # what she wears this frame (gl_face reads it)

        # rel_x is re-applied from the active style's EYE_SPREAD every frame
        self.left_eye  = Eye(-EYE_SPREAD, -30, 175, 125)
        self.right_eye = Eye( EYE_SPREAD, -30, 175, 125)
        self.mouth     = Mouth(0, 155)
        self.micro     = MicroExpressions()

        # blush — cheeks
        self.left_blush  = Blush(-240, 80)
        self.right_blush = Blush( 240, 80)

        pygame.font.init()

    def set_state(self, new_state):
        if new_state != self.state:
            if self.state == "sleeping" and new_state != "sleeping":
                self.wake_anim   = self._WAKE_ACTIVE
                self.wake_ripple = 0.0
            # spawn starburst on surprise / excitement
            if new_state in ("surprised", "excited") and \
                    self.state not in ("surprised", "excited"):
                self.star_spawned = False
            # happy little bounce on positive transitions
            if new_state in ("happy", "excited", "love"):
                self.bounce_phase = 0.0
                self.bounce_amp   = 22.0
            # a change of face often comes with a blink — a cut between them
            if (EYE_MODE == "block" and "sleeping" not in (self.state, new_state)
                    and random.random() < 0.55 and getattr(self, "_blink_dir", 0) == 0):
                self._blink_dir, self.blink_counter = -1, 0
            self.prev_state = self.state
            self.state      = new_state

    def _spawn_stars(self, fcx, fcy):
        for _ in range(12):
            ox = random.randint(-200, 200)
            oy = random.randint(-150, 150)
            self.star_particles.append(StarParticle(fcx + ox, fcy + oy))

    def update(self):
        global _K
        mono = time.monotonic()
        last, self._update_t = getattr(self, "_update_t", 0.0), mono
        # (rounded: a steady 30 fps is exactly 1 — the steps as they always were)
        _K = round(min(4.0, (mono - last) * self.anim_fps), 3) if last else 1.0
        self.breath_phase += 0.045 * _K
        now_t = time.time()

        if self.visual_state != self.state:
            self.visual_state = self.state

        with state.lock:
            face_detected  = state.face_detected
            fx             = state.face_x
            fy             = state.face_y
            # Two speech flags with different jobs:
            #   speaking      — whole TTS call (incl. silent synth) → freezes
            #                   emotion mimicking, blink cadence, eye sizing,
            #                   so the face never flickers back to camera
            #                   emotions in the gap before audio starts
            #   audio_playing — real sound right now → drives ONLY the mouth,
            #                   so lips move exactly with the audio
            speaking       = state.speaking
            audio_playing  = state.audio_playing
            listening      = state.listening
            audio_energy   = state.audio_energy
            self._audio_shape = state.audio_shape
            mic_level      = state.mic_level
            look_dir       = state.look_dir
            motion         = state.motion
            frozen_emotion = state.frozen_emotion
            g_anim         = state.gesture_anim
            g_start        = state.gesture_anim_start
            i_anim         = state.reply_scene
            i_start        = state.reply_scene_start
            game_hand      = state.game_hand
            self._big_text = state.big_text
            touch_kind     = state.touch_kind
            touch_t        = state.touch_time
            touch_pt       = (state.touch_x, state.touch_y)
            convo_active   = state.conversation_active
            convo_expired  = state.convo_expired_time

        # ── conversation window indicator ─────────────────────────────────
        # soft glow while awake; when the window times out play a subtle
        # "rest" cue — one slow dim blink and the glow fades out
        self.awake_glow = ease(self.awake_glow, 1.0 if convo_active else 0.0,
                               0.06)
        if convo_expired > self._last_expire:
            self._last_expire = convo_expired
            self.rest_pulse   = 1.0
            self._blink_dir   = -1        # start a blink…
            self.blink_counter = 0
        self.rest_pulse *= 0.965 ** _K    # (~3 s at 30 fps)

        # emotion — frozen while speaking
        if speaking and frozen_emotion:
            emotion = frozen_emotion.lower() if frozen_emotion != "Neutral" else "neutral"
        else:
            emotion = self.visual_state

        # ── sleep / wake ──────────────────────────────────────────────────
        self._face_seen = face_detected
        # drowsy: the last 40 % before she falls asleep (gl_face droops the lids)
        self._drowsy = (clamp((self.idle_frames - 0.6 * SLEEP_AFTER_FRAMES)
                              / (0.4 * SLEEP_AFTER_FRAMES), 0.0, 1.0)
                        if emotion != "sleeping" else 0.0)
        if not face_detected and not speaking:
            self.idle_frames += _K
        else:
            if self.idle_frames > 0 and emotion == "sleeping":
                self.set_state("neutral")
            self.idle_frames = 0

        # ── eye size targets ──────────────────────────────────────────────
        if speaking:
            tw, th = 185, 118
        elif emotion == "happy":
            tw, th = 205, 150
        elif emotion == "surprised":                 # the block face: round
            tw, th = (214, 206) if EYE_MODE == "block" else (240, 190)
        elif emotion == "angry":
            tw, th = 185,  78
        elif emotion == "sad":
            tw, th = 158,  88
        elif emotion == "sleeping":
            tw, th = 155,  10
        elif emotion == "excited":
            tw, th = 230, 175
        elif emotion == "love":
            tw, th = 200, 150
        elif emotion == "thinking":
            tw, th = 168, 112
        else:
            tw, th = 175, 125
        spec_eyes = EYE_MODE == "block"
        if spec_eyes:                     # the block face: face_spec's sizes, in px
            tw, th = face_spec.eye_size(emotion, listening and not speaking)

        # ── blink — two-phase animated blink (smooth close AND open) ─────
        # blink_open: 1 = fully open. Phase "closing" eases shut fast,
        # phase "opening" eases back with a soft cubic — much cuter than
        # the old instant snap-shut.
        if emotion != "sleeping":
            self.blink_counter += _K
            trigger = self.blink_timer if not speaking else 180

            if listening and not speaking:
                trigger = int(trigger * 1.3)      # listening: she blinks less
            if (self.blink_open >= 1.0 and self.blink_counter > trigger
                    and (not speaking or self.mouth.talk_open < 0.08)):   # (in a pause)
                self.blink_counter = 0
                self._blink_dir    = -1          # start closing

            d = getattr(self, "_blink_dir", 0)
            if d == -1:
                self.blink_open -= 0.34 * _K     # fast close (~3 frames)
                if self.blink_open <= 0.0:
                    self.blink_open = 0.0
                    self._blink_dir = 1
            elif d == 1:
                # reopen slower right after a conversation timeout — reads
                # as a sleepy "back to rest" blink
                # (sad and drowsy eyes open slowly)
                slow = self.rest_pulse > 0.35 or emotion == "sad" or self._drowsy > 0.3
                self.blink_open += 0.16 * (0.45 if slow else 1.0) * _K
                if self.blink_open >= 1.0:
                    self.blink_open  = 1.0
                    self._blink_dir  = 0
                    # the mood sets the rhythm: sad and drowsy blink slower,
                    # excited and surprised eyes hardly at all
                    self.blink_timer = int(random.randint(100, 220) * BLINK_PACE.get(
                        emotion, 1.4 if self._drowsy > 0.3 else 1.0))
                    # occasionally double-blink — very lifelike
                    if random.random() < 0.18 and not speaking:
                        self.blink_counter = self.blink_timer - 8

            # ease the reopen with a smoothstep curve
            t = clamp(self.blink_open, 0.0, 1.0)
            blink_t = t * t * (3 - 2 * t)
        else:
            blink_t = 0.0

        # ── listening pulse ───────────────────────────────────────────────
        # (the waves quicken and brighten with the voice she hears)
        self._mic = ease(getattr(self, "_mic", 0.0), mic_level if listening else 0.0,
                         0.35 if mic_level > getattr(self, "_mic", 0.0) else 0.12)
        self.listen_phase += (0.08 + 0.10 * self._mic) * _K
        if listening:
            self.listen_pulse = ease(self.listen_pulse,
                                     0.5 + 0.5 * math.sin(self.listen_phase),
                                     0.15)
        else:
            self.listen_pulse = ease(self.listen_pulse, 0.0, 0.1)

        # ── angry red pulse ───────────────────────────────────────────────
        self.angry_pulse_phase += 0.06 * _K
        if emotion == "angry":
            self.angry_pulse = ease(self.angry_pulse,
                                    0.3 + 0.3 * math.sin(
                                        self.angry_pulse_phase), 0.10)
        else:
            self.angry_pulse = ease(self.angry_pulse, 0.0, 0.08)

        # ── blush ─────────────────────────────────────────────────────────
        if emotion == "love":
            blush_alpha = 210.0
        elif emotion in ("happy", "excited"):
            blush_alpha = 140.0
        elif emotion == "sleeping":
            blush_alpha = 80.0
        else:
            blush_alpha = 0.0
        self.left_blush.update(blush_alpha)
        self.right_blush.update(blush_alpha)

        # ── micro-expressions ─────────────────────────────────────────────
        # (the block face's moods set their own lids and pupils: face_spec)
        self.micro.update(emotion, listening, speaking, moods=EYE_MODE != "block")

        # ── face offset / tracking ────────────────────────────────────────
        breath_y = math.sin(self.breath_phase) * 5

        if emotion == "sleeping":
            self.target_ox = 0.0
            self.target_oy = 0.0
            self.pupil_ox  = ease(self.pupil_ox, 0.0, 0.05)
            self.pupil_oy  = ease(self.pupil_oy, 0.0, 0.05)
            self.target_tilt = 0.0

        elif emotion == "thinking":
            # pondering: pupils glance up and slowly wander side to side,
            # head tips a touch — the classic "hmm" look
            self.think_phase = getattr(self, "think_phase", 0.0) + 0.035 * _K
            tx = 26 * math.sin(self.think_phase)
            self.target_ox   = tx * 0.6
            self.target_oy   = -12.0
            self.pupil_ox    = ease(self.pupil_ox, tx, 0.08)
            self.pupil_oy    = ease(self.pupil_oy, -22.0, 0.08)
            self.target_tilt = -4.0

        elif look_dir is not None:
            FACE_SHIFT  = 60
            PUPIL_SHIFT = 28
            if look_dir == "left":
                self.target_ox = -FACE_SHIFT
                self.pupil_ox  = ease(self.pupil_ox, -PUPIL_SHIFT, 0.15)
            elif look_dir == "right":
                self.target_ox =  FACE_SHIFT
                self.pupil_ox  = ease(self.pupil_ox,  PUPIL_SHIFT, 0.15)
            elif look_dir == "up":
                self.target_oy = -FACE_SHIFT
                self.pupil_oy  = ease(self.pupil_oy, -PUPIL_SHIFT, 0.15)
            elif look_dir == "down":
                self.target_oy =  FACE_SHIFT
                self.pupil_oy  = ease(self.pupil_oy,  PUPIL_SHIFT, 0.15)
            self.target_tilt = 0.0

        elif face_detected:
            target_ox = (fx - 0.5) * 120
            target_oy = (fy - 0.5) *  60
            p_ox, p_oy = target_ox * GAZE_FACE_PUPIL, target_oy * GAZE_FACE_PUPIL
            seen = self._motion_seen(motion, now_t)
            if seen:
                # something moves beside them: a glance at it (6 Oct: "eyes
                # should move a bit more towards moving things")
                m_ox, m_oy, w = seen
                p_ox += (m_ox * GAZE_MOTION_PUPIL - p_ox) * w
                p_oy += (m_oy * GAZE_MOTION_PUPIL - p_oy) * w
                target_ox += (m_ox - target_ox) * w * 0.3
                target_oy += (m_oy - target_oy) * w * 0.3
            self.target_ox = target_ox
            self.target_oy = target_oy
            self.pupil_ox  = ease(self.pupil_ox, p_ox, 0.18)
            self.pupil_oy  = ease(self.pupil_oy, p_oy, 0.18)
            self.target_tilt = (8.0 if fx < 0.38
                                else (-8.0 if fx > 0.62 else 0.0))
        elif self._motion_seen(motion, now_t):
            # nobody in view, but something moves: the eyes follow it
            m_ox, m_oy, _ = self._motion_seen(motion, now_t)
            self.curiosity_timer = 0
            self.target_ox = m_ox * 0.7
            self.target_oy = m_oy * 0.7
            self.pupil_ox  = ease(self.pupil_ox, m_ox * GAZE_MOTION_PUPIL, 0.12)
            self.pupil_oy  = ease(self.pupil_oy, m_oy * GAZE_MOTION_PUPIL, 0.12)
            self.target_tilt = 0.0
        else:
            self.curiosity_timer += _K
            if self.curiosity_timer > 140:
                self.curiosity_timer    = 0
                # a big jump of the gaze often comes with a blink (as ours do)
                if random.random() < 0.55 and getattr(self, "_blink_dir", 0) == 0:
                    self._blink_dir, self.blink_counter = -1, 0
                self.curiosity_target_x = random.uniform(-70, 70)
                self.curiosity_target_y = random.uniform(-35, 35)
            self.target_ox = self.curiosity_target_x
            self.target_oy = self.curiosity_target_y
            self.pupil_ox  = ease(self.pupil_ox,
                                  self.curiosity_target_x * 0.20, 0.02)
            self.pupil_oy  = ease(self.pupil_oy,
                                  self.curiosity_target_y * 0.20, 0.02)
            self.target_tilt = 0.0

        if emotion == "sad":                         # sad eyes look down
            self.pupil_oy = ease(self.pupil_oy, 18.0, 0.08)

        # cute decaying bounce on positive state changes
        bounce_y = 0.0
        if self.bounce_amp > 0.5:
            self.bounce_phase += 0.28 * _K
            bounce_y = -abs(math.sin(self.bounce_phase)) * self.bounce_amp
            self.bounce_amp *= 0.94 ** _K   # decay

        # ── reply body language (see reply_scenes.py for the catalogue) ───
        i_el   = now_t - i_start
        scene  = reply_scenes.SCENES.get(i_anim) if i_anim else None
        i_dur  = scene.duration if scene else 0.0
        self._scene_name = i_anim if (scene and 0.0 <= i_el < i_dur) else None
        self._scene = scene if self._scene_name else None
        self._scene_p = (i_el / i_dur) if self._scene_name else 0.0
        if self._scene_name and self._scene_name != self._scene_prev:
            self._wink_side = random.choice(("L", "R"))   # alternate eyes
        self._scene_prev = self._scene_name
        if i_anim and i_el >= i_dur:
            with state.lock:
                if state.reply_scene == i_anim:
                    state.reply_scene = None

        # ── touch: instant visual answer, and tell the engine which zone ──
        with state.lock:
            ov_kind = state.overlay[0] if state.overlay else None
        if touch_t > self._touch_t and self._overlay_on() and ov_kind in ("ttt", "memo"):
            self._touch_t = touch_t                     # a move in a game
            if touch_kind in ("tap", "stop"):
                import importlib                        # outside state.lock: it takes it
                game = importlib.import_module("tictac" if ov_kind == "ttt" else "memo")
                if ui_screens.close_hit(*touch_pt):     # ✕: the game is over
                    screens.end_game_page(ov_kind)
                else:
                    game.tap(touch_pt[0], touch_pt[1], WIDTH, HEIGHT)
        elif touch_t > self._touch_t and self._overlay_on():
            self._touch_t = touch_t
            if ov_kind == "story" and touch_kind == "swipe":
                with state.lock:                    # the list: the next page
                    dx = state.touch_dx
                import story
                story.swipe(dx)
            elif ov_kind == "radio" and touch_kind == "swipe":
                with state.lock:                    # the next kind / the one before
                    dx = state.touch_dx
                import radio
                radio.swipe(dx)
            elif ov_kind == "settings" and touch_kind == "swipe":
                with state.lock:                    # the next tab / the one before
                    dx = state.touch_dx
                import settings_page
                settings_page.swipe(dx)
            elif ov_kind == "lamp" and touch_kind == "swipe":
                with state.lock:                    # the lamp's next picture
                    dx = state.touch_dx
                import fun
                fun.lamp_next(-1 if dx > 0 else 1)
            elif ov_kind == "schedule" and touch_kind == "swipe":
                with state.lock:                    # the next day / the one before
                    dx = state.touch_dx
                import schedule
                schedule.swipe(dx)
            elif ov_kind == "gallery":                  # ‹ › ✕, a swipe (gallery.py)
                with state.lock:
                    dx = state.touch_dx
                gallery.on_touch(touch_kind, touch_pt[0], touch_pt[1], dx)
            elif touch_kind in ("tap", "stop"):         # (a stroke or a held finger: nothing)
                if ui_screens.close_hit(*touch_pt):     # ✕ — a game's page: the game ends too
                    screens.end_game_page(ov_kind)
                elif ov_kind == "list" and screens.list_tap(*touch_pt):
                    pass                                # an item: "Usunąć?", then crossed off
                elif ov_kind == "story":                # an idea, a choice, a story
                    import story
                    story.tap(touch_pt[0] * WIDTH, touch_pt[1] * HEIGHT, WIDTH, HEIGHT)
                elif ov_kind == "schedule":             # a day, a person, an entry, "+"
                    import schedule
                    schedule.tap(touch_pt[0] * WIDTH, touch_pt[1] * HEIGHT, WIDTH, HEIGHT)
                elif ov_kind == "radio":                # a kind, a station, Stop
                    import radio
                    radio.tap(touch_pt[0] * WIDTH, touch_pt[1] * HEIGHT, WIDTH, HEIGHT)
                elif ov_kind == "settings":             # a tab, a switch, the reset
                    import settings_page
                    settings_page.tap(touch_pt[0] * WIDTH, touch_pt[1] * HEIGHT, WIDTH, HEIGHT)
                else:
                    with state.lock:                    # a tap elsewhere closes it
                        state.overlay = None
        if touch_t > self._touch_t:
            self._touch_t = touch_t
            self._touch_zone = self._zone_at(*touch_pt)
            self._touch_kind = touch_kind
            self._touch_react_t = now_t
            self._touch_pt = (touch_pt[0] * WIDTH, touch_pt[1] * HEIGHT)   # px: the eyes glance at it
            # The mood must go through face_override: face_renderer calls
            # set_state() every frame, so setting it here would last 1 frame.
            if touch_kind in ("hold", "stop"):
                mood, secs = None, 0.0          # commands, handled elsewhere
            elif touch_kind == "multi":
                mood, secs = "angry", TOUCH_POKE_SECS
            elif touch_kind == "stroke":
                mood = "love" if self._touch_zone in ("top", "eye") else "happy"
                secs = TOUCH_REACT_SECS
            elif self._touch_zone == "eye":
                mood, secs = "surprised", TOUCH_REACT_SECS
            elif self._touch_zone == "mouth":
                mood, secs = "happy", TOUCH_REACT_SECS
                self.bounce_phase, self.bounce_amp = 0.0, 26.0
            else:
                mood, secs = "happy", TOUCH_REACT_SECS
            # a touch outranks whatever scene was playing: finish it now,
            # or its eyes / mouth / props mix with the touch reaction
            if self._scene:
                self._cancel_scene(i_anim, i_start, "touch")
            with state.lock:
                state.touch_zone          = self._touch_zone
                if mood:
                    state.face_override       = mood
                    state.face_override_until = now_t + secs
            if TOUCH_DEBUG:
                print(f"[face] touched: {touch_kind} on {self._touch_zone} "
                      f"-> {mood}", flush=True)
        touch_el = now_t - self._touch_react_t

        # ── one thing drives the face at a time ──────────────────────────
        # touch > hand/head gesture > scene. A scene that loses is ended
        # outright, not blended (e.g. a wave-back starting mid-reply).
        if self._scene:
            g_live = (g_anim is not None
                      and 0.0 <= now_t - g_start < GESTURE_DURATION.get(g_anim, 0.0))
            if g_live:
                self._cancel_scene(i_anim, i_start, f"gesture {g_anim}")

        # ── gestures: head (nod / shake) and hands (wave / thumbs_up / heart)
        g_el  = now_t - g_start
        g_dur = GESTURE_DURATION.get(g_anim, 0.0) if g_anim else 0.0
        active = g_anim is not None and 0.0 <= g_el < g_dur
        self._gesture   = g_anim if active else None
        self._gesture_p = (g_el / g_dur) if active else 0.0
        env = math.sin(math.pi * self._gesture_p) if active else 0.0   # ease in/out
        head_fast = False

        rest_L = (-320.0, 420.0, 0.0)          # tucked below the screen edge
        rest_R = ( 320.0, 420.0, 0.0)
        tgt_L, tgt_R = rest_L, rest_R
        self.hand_pose["L"] = self.hand_pose["R"] = "open"

        if active and g_anim == "nod":
            self.target_oy += 16.0 * env * math.sin(g_el * 2 * math.pi * 2.0)
            head_fast = True
        elif active and g_anim == "shake":
            self.target_ox  += 22.0 * env * math.sin(g_el * 2 * math.pi * 2.2)
            self.target_tilt = -6.0 * env * math.sin(g_el * 2 * math.pi * 2.2)
            head_fast = True
        elif active and g_anim == "wave":
            tgt_R = (285.0, 60.0, 24.0 * math.sin(g_el * 2 * math.pi * 3.0))
            self.target_tilt = 5.0 * env * math.sin(g_el * 2 * math.pi * 3.0)
        elif active and g_anim == "thumbs_up":
            self.hand_pose["R"] = "thumb"
            bob = 6.0 * math.sin(g_el * 2 * math.pi * 2.0)
            tgt_R = (275.0, 95.0 + bob, -8.0)
        elif active and g_anim == "heart":
            hy = face_spec.LAYOUT["mouth_y"] + 128 if EYE_MODE == "block" else 178.0
            tgt_L = (-96.0, hy,  30.0)
            tgt_R = ( 96.0, hy, -30.0)
            self._heart_pulse = 0.5 + 0.5 * math.sin(g_el * 2 * math.pi * 1.6)

        # thinking for a while: a finger on her chin (the face library, 15 Oct)
        # — not for every short wait, the hand would pop up after each question
        if emotion == "thinking" and not active and not self._scene:
            self._think_t = getattr(self, "_think_t", 0.0) or now_t
            if now_t - self._think_t > THINK_HAND_SECS:
                tgt_R = (*face_spec.LAYOUT["chin"], -14.0)
                self.hand_pose["R"] = "point"
        else:
            self._think_t = 0.0

        # a scene may take the hands over (see reply_scenes.Hands)
        if self._scene:
            h = reply_scenes.Hands(tgt_L, tgt_R,
                                  self.hand_pose["L"], self.hand_pose["R"])
            self._scene.hands(self, self._scene_p, h)
            tgt_L, tgt_R = h.l, h.r
            self.hand_pose["L"], self.hand_pose["R"] = h.pose_l, h.pose_r

        # rock-paper-scissors: her throw, held up by her cheek
        if game_hand and now_t < game_hand[1]:
            pose = {"rock": "fist", "paper": "open", "scissors": "scissors"}.get(
                game_hand[0], "open")
            self.hand_pose["R"] = pose
            tgt_R = (232, 50 + 5 * math.sin(now_t * 9.0), -6)

        self._pupil_converge = ease(self._pupil_converge, 0.0, 0.25)
        self._pupil_mul = 1.0
        self._mouth_drive = 0.0
        # the radio playing and nothing else going on: she moves a little
        # with the music — a dip on the beat, a slow sway
        if (EYE_MODE == "block" and emotion != "sleeping" and not speaking and not listening
                and not self._scene and not getattr(self, "_gesture", None)):
            import radio
            if radio.playing():
                self._music_bob = ease(getattr(self, "_music_bob", 0.0), radio.music_pulse(), 0.35)
                self.target_oy += 6.0 * self._music_bob
                self.target_tilt += 2.0 * math.sin(now_t * 1.3)
            else:
                self._music_bob = 0.0
        self._spec_mod = {}              # a scene's face_spec settings over the mood
        self._eye_fx = (0.0, 0.0)        # …and its effects in the eyes (spiral, static)
        if self._scene:
            self._scene.motion(self, self._scene_p)
            self._scene.face(self, self._scene_p)

        self._hand_target = {"L": tgt_L, "R": tgt_R}
        # the hands on springs: quick, a little overshoot, settling — in
        # real time (4 ms steps), not "x % of the way each frame"
        tnow = time.monotonic()
        hdt = max(1.0 / 120.0, min(0.1, tnow - getattr(self, "_hand_t", tnow - 0.05)))
        self._hand_t = tnow
        vel = getattr(self, "_hand_vel", None) or {"L": [0.0, 0.0, 0.0], "R": [0.0, 0.0, 0.0]}
        self._hand_vel = vel
        n = int(math.ceil(hdt / 0.004))
        for side in ("L", "R"):
            cur, tgt, v = self.hand[side], self._hand_target[side], vel[side]
            for _ in range(n):
                for j, (kk, dd) in enumerate(((160.0, 17.0), (160.0, 17.0), (220.0, 24.0))):
                    v[j] += ((tgt[j] - cur[j]) * kk - v[j] * dd) * (hdt / n)
                    cur[j] += v[j] * (hdt / n)

        # being touched: recoil from the finger / squirm when poked
        if touch_el < 0.5 and self._touch_kind == "tap":
            k = (1.0 - touch_el / 0.5)
            self.target_oy += 20.0 * k
            self.target_ox += (self._touch_pull * 30.0) * k
        elif touch_el < 1.0 and self._touch_kind == "multi":
            k = 1.0 - touch_el / 1.0
            self.target_ox  += 26.0 * math.sin(now_t * 24.0) * k
            self.target_tilt = 9.0 * math.sin(now_t * 24.0) * k
            head_fast = True
        elif touch_el < 0.8 and self._touch_kind == "stroke":
            # leans into the hand, slow and content
            k = 1.0 - touch_el / 0.8
            self.target_oy   += 8.0 * k
            self.target_tilt += 5.0 * k * self._touch_pull

        self.face_ox = ease(self.face_ox, self.target_ox, 0.30 if head_fast else 0.12)
        self.face_oy = ease(self.face_oy,
                            self.target_oy + breath_y + bounce_y,
                            0.30 if head_fast else 0.16)
        self.head_angle = ease(self.head_angle, self.target_tilt,
                               0.35 if head_fast or self._gesture == "wave" else 0.07)

        # ── update eye/mouth ──────────────────────────────────────────────
        angry     = emotion == "angry"
        happy     = emotion in ("happy", "excited", "love")
        sad       = emotion == "sad"
        is_listen = listening and not speaking

        # per-style geometry (so 1/2/3 can be switched live)
        self.left_eye.rel_x  = -EYE_SPREAD
        self.right_eye.rel_x =  EYE_SPREAD
        if spec_eyes:                     # the block face: face_spec's layout
            self.left_eye.rel_y = self.right_eye.rel_y = face_spec.LAYOUT["eye_y"]
            self.mouth.rel_y = face_spec.LAYOUT["mouth_y"]
        else:
            self.left_eye.rel_y = self.right_eye.rel_y = -30
            self.mouth.rel_y = 155
        if not spec_eyes:
            tw, th = tw * EYE_SCALE, th * EYE_SCALE

        blink_l = blink_r = blink_t
        squint  = self.micro.squint_target
        widen   = self.micro.widen_target

        eyes = reply_scenes.Eyes(blink_t, squint, widen,
                                self.micro.droop_target)
        if self._scene:
            self._scene.eyes(self, self._scene_p, eyes)
        blink_l, blink_r = eyes.blink_l, eyes.blink_r
        squint, widen, droop = eyes.squint, eyes.widen, eyes.droop

        # poking -> screwed-up eyes; a tap on an eye shuts it then it pops
        # wide open; petting -> a slow, contented squint
        if self._touch_kind == "multi" and touch_el < 0.9:
            squint = max(squint, 0.85 * (1.0 - touch_el / 0.9))
        elif self._touch_kind == "stroke" and touch_el < 1.2:
            squint = max(squint, 0.75)
        elif self._touch_kind == "tap" and touch_el < 0.55:
            k = 1.0 - touch_el / 0.55
            if self._touch_zone == "eye":
                if touch_pt[0] < 0.5:
                    blink_l = 0.0 if touch_el < 0.2 else min(blink_l, 1.0 - k)
                else:
                    blink_r = 0.0 if touch_el < 0.2 else min(blink_r, 1.0 - k)
            widen = max(widen, 0.8 * k)      # startled, wide eyes

        conv = self._pupil_converge          # cross-eyed scenes
        self.left_eye.update(
            tw, th, blink_l, self.pupil_ox + conv, self.pupil_oy,
            pupil_scale=self.micro.pupil_scale * self._pupil_mul, squint=squint,
            widen=widen, droop=droop)
        self.right_eye.update(
            tw, th, blink_r, self.pupil_ox - conv, self.pupil_oy,
            pupil_scale=self.micro.pupil_scale * self._pupil_mul, squint=squint,
            widen=widen, droop=droop)

        # a scene may open her mouth (yawning, laughing, sighing): it sets
        # face._mouth_drive in motion(), and it plays like speech would
        if self._mouth_drive > 0.02:
            self.mouth.update(self._mouth_drive, emotion, True)
        else:
            self.mouth.update(audio_energy, emotion, speaking)

        # ── particle spawning ─────────────────────────────────────────────
        fcx = int(self.face_cx + self.face_ox)
        fcy = int(self.face_cy + self.face_oy)

        # zzz
        if emotion == "sleeping":
            self.zzz_spawn_t += _K
            if self.zzz_spawn_t > 40:
                self.zzz_spawn_t = 0
                self.zzz_particles.append(
                    ZzzParticle(fcx + random.randint(-80, 80), fcy - 120))
        else:
            self.zzz_particles.clear()

        # tears
        if emotion == "sad":
            self.tear_spawn_t += _K
            if self.tear_spawn_t > 90:
                self.tear_spawn_t = 0
                # drip from left eye
                lx = fcx + self.left_eye.rel_x
                ly = fcy + self.left_eye.rel_y + 60
                self.tear_particles.append(TearParticle(lx, ly))
        else:
            self.tear_particles.clear()

        # steam (angry)
        if emotion == "angry" and EYE_MODE != "block":
            self.steam_spawn_t += _K
            if self.steam_spawn_t > 12:
                self.steam_spawn_t = 0
                for eye_x in [fcx - 190, fcx + 190]:
                    self.steam_particles.append(
                        SteamParticle(eye_x + random.randint(-20, 20),
                                      fcy - 80))
        else:
            self.steam_particles.clear()

        # starburst (surprised / excited — spawn once on transition)
        if (emotion in ("surprised", "excited") and not self.star_spawned
                and EYE_MODE != "block"):         # (the block face: twinkles by its eyes)
            self._spawn_stars(fcx, fcy)
            self.star_spawned = True
        elif emotion not in ("surprised", "excited"):
            self.star_spawned = False
            self.star_particles.clear()

        # excited keeps sprinkling a few extra stars while it lasts
        if emotion == "excited" and EYE_MODE != "block":
            self.excite_spawn_t += _K
            if self.excite_spawn_t > 25:
                self.excite_spawn_t = 0
                self.star_particles.append(
                    StarParticle(fcx + random.randint(-260, 260),
                                 fcy + random.randint(-180, 120)))

        # floating hearts (love)
        if emotion == "love":
            self.heart_spawn_t += _K
            if self.heart_spawn_t > 18:
                self.heart_spawn_t = 0
                self.heart_particles.append(
                    HeartParticle(fcx + random.randint(-240, 240),
                                  fcy + random.randint(-60, 100)))
        else:
            self.heart_particles.clear()

        # sound waves ripple from the mouth while speaking — nice talking effect
        if speaking and audio_energy > 0.45 and EYE_MODE != "block":   # (the block face:
            self.wave_spawn_t += _K                               #  its mouth is enough)
            if self.wave_spawn_t > 14:
                self.wave_spawn_t = 0
                mx = fcx + self.mouth.rel_x
                my = fcy + self.mouth.rel_y
                self.sound_waves.append(SoundWave(mx, my))

        # update + cull all particles
        for p_list in (self.zzz_particles, self.tear_particles,
                       self.steam_particles, self.star_particles,
                       self.sound_waves, self.heart_particles):
            for p in p_list:
                p.update()

        self.zzz_particles   = [p for p in self.zzz_particles   if p.alive()]
        self.tear_particles  = [p for p in self.tear_particles  if p.alive()]
        self.steam_particles = [p for p in self.steam_particles if p.alive()]
        self.star_particles  = [p for p in self.star_particles  if p.alive()]
        self.sound_waves     = [p for p in self.sound_waves     if p.alive()]
        self.heart_particles = [p for p in self.heart_particles if p.alive()]

        # wake ripple
        if self.wake_anim == self._WAKE_ACTIVE:
            self.wake_ripple += 0.04 * _K
            if self.wake_ripple >= 1.0:
                self.wake_anim   = self._WAKE_NONE
                self.wake_ripple = 0.0

        # stash for draw
        self._angry       = angry
        self._happy       = happy
        self._sad         = sad
        self._listen      = is_listen
        # the mouth draws as "speaking" for real audio and while yawning
        self._speaking    = audio_playing or self._mouth_drive > 0.02
        if self._mouth_drive > 0.02:
            audio_energy = self._mouth_drive
        self._emotion     = emotion
        self._audio_energy = audio_energy

        # eye colour: listening pulse > awake tint > rest dim, all subtle
        eye_col = EYE_OUTER
        if self.listen_pulse > 0.05:
            p = self.listen_pulse
            eye_col = (
                int(lerp(eye_col[0], LISTEN_COL[0], p * 0.5)),
                int(lerp(eye_col[1], LISTEN_COL[1], p * 0.5)),
                int(lerp(eye_col[2], LISTEN_COL[2], p * 0.5)),
            )
        elif self.awake_glow > 0.05:
            # slightly brighter eyes while the conversation window is open
            g = self.awake_glow * 0.22
            eye_col = (
                int(lerp(eye_col[0], EYE_INNER[0], g)),
                int(lerp(eye_col[1], EYE_INNER[1], g)),
                int(lerp(eye_col[2], EYE_INNER[2], g)),
            )
        if self.rest_pulse > 0.05:
            # brief dim as she goes back to wake-word mode
            d = self.rest_pulse * 0.45
            eye_col = (int(eye_col[0] * (1 - d)),
                       int(eye_col[1] * (1 - d)),
                       int(eye_col[2] * (1 - d)))
        self._eye_color = None if eye_col == EYE_OUTER else eye_col

    def _motion_seen(self, motion, now_t):
        """(offset x, offset y, weight) toward recent movement in the camera
        picture (gesture_module), in the same units as the face offset; None
        when nothing has moved lately."""
        if not motion:
            return None
        mx, my, strength, t = motion
        if now_t - t > GAZE_MOTION_HOLD or strength < GAZE_MOTION_MIN:
            return None
        w = min(GAZE_MOTION_MAX_W, 0.25 + strength)
        return (mx - 0.5) * 120, (my - 0.5) * 60, w

    def _cancel_scene(self, name, start, why):
        """End the playing scene now. Its mood goes too — but only the mood
        the scene itself put on (same expiry), never one set by someone else."""
        sc = reply_scenes.SCENES.get(name)
        with state.lock:
            if state.reply_scene == name and state.reply_scene_start == start:
                state.reply_scene = None
            if (sc and sc.mood and state.face_override == sc.mood
                    and abs(state.face_override_until - (start + sc.duration)) < 0.05):
                state.face_override = None
        self._scene_name = self._scene = None
        self._scene_p = 0.0
        if TOUCH_DEBUG:
            print(f"[face] scene {name} cut short by {why}", flush=True)

    def _zone_at(self, nx, ny):
        """Which part of the face was touched (normalised screen coords)."""
        x, y = nx * WIDTH, ny * HEIGHT
        fcx  = self.face_cx + self.face_ox
        fcy  = self.face_cy + self.face_oy
        self._touch_pull = 1.0 if x < fcx else -1.0     # recoil away from it
        for eye in (self.left_eye, self.right_eye):
            ex, ey = fcx + eye.rel_x, fcy + eye.rel_y
            if abs(x - ex) < eye.w * 0.8 and abs(y - ey) < eye.h * 0.9:
                return "eye"
        mx, my = fcx + self.mouth.rel_x, fcy + self.mouth.rel_y
        if abs(x - mx) < 150 and abs(y - my) < 90:
            return "mouth"
        if y < fcy - 120:
            return "top"
        return "other"

    _seen_events = set()

    def draw(self):
        st = frame_stats
        for event in pygame.event.get():
            # log every kind of window event once, so an unexplained exit can
            # be traced to what actually caused it
            if event.type not in RobotFace._seen_events:
                RobotFace._seen_events.add(event.type)
                print(f"[face] window event: {pygame.event.event_name(event.type)}"
                      f" ({event.type})", flush=True)
            if event.type == pygame.QUIT:
                # main.py's finally block handles the full clean shutdown
                print("[face] QUIT from the window system -> exiting", flush=True)
                raise SystemExit
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    print("[face] ESC pressed -> exiting", flush=True)
                    raise SystemExit
                if event.key in (pygame.K_1, pygame.K_KP1):
                    apply_style(1)
                elif event.key in (pygame.K_2, pygame.K_KP2):
                    apply_style(2)
                elif event.key in (pygame.K_3, pygame.K_KP3):
                    apply_style(3)

        self.clock.tick(self.fps)
        t0 = time.perf_counter()
        self.update()
        t1 = time.perf_counter()
        if self.gl is not None and self._lamp_scene():
            self._draw_lamp_scene()          # (the whole screen: no face to draw under it)
            st["frames"] += 1
            st["update"] += t1 - t0
            st["flip"] += time.perf_counter() - t1
            _count_present(st, time.perf_counter())
            return

        base = self.base   # reused surface — no per-frame allocation
        # with the GPU face, pygame draws only what goes over it, on clear glass
        gl_face_on = self.gl is not None and EYE_MODE == "block"
        behind = base
        if self.gl:                         # (only the rows drawn on last frame)
            self.gl.clear(self.gl.face_l, base)
            self.gl.clear(self.gl.back_l, self.back)
            behind = self.back
        else:
            base.fill(BG)

        fcx = int(self.face_cx + self.face_ox)
        fcy = int(self.face_cy + self.face_oy)

        # ── hair (behind everything) ──────────────────────────────────────
        if HAIR:
            draw_hair(behind, fcx, fcy, self.head_angle)
        with state.lock:
            costume = state.costume
        if costume and time.time() > costume[1]:
            costume = None
        self._costume = costume[0] if costume else None      # (gl_face: googly eyes…)
        if costume:
            draw_costume_back(behind, fcx, fcy, costume[0], self.head_angle)

        # ── blush (behind eyes) ───────────────────────────────────────────
        if not gl_face_on:
            self.left_blush.draw(base, fcx, fcy)
            self.right_blush.draw(base, fcx, fcy)

        # ── sound waves (behind mouth) ────────────────────────────────────
        for w in self.sound_waves:
            w.draw(behind)

        # ── steam (behind eyes) ───────────────────────────────────────────
        for p in self.steam_particles:
            p.draw(behind)

        # ── listening: sound waves coming in from both sides; a nod or a
        #    shake of the head: motion marks beside it ────────────────────
        if self.listen_pulse > 0.05 or self._listen:
            k = (0.50 + 0.45 * self._mic) * max(self.listen_pulse, 0.6 if self._listen else 0.0)
            ph = self.listen_phase * 0.22
            arcs = []
            for j in range(3):                    # sound coming in: far and faint → near
                u = (ph + j / 3.0) % 1.0
                arcs.append((112 - 50 * u, k * math.sin(math.pi * u) ** 1.3))
            draw_side_arcs(base, fcx, fcy - 30, EYE_SPREAD + 95, arcs, LISTEN_WAVE_COL)
        if self._gesture in ("nod", "shake"):
            env = math.sin(math.pi * self._gesture_p)
            arcs = [(70, env)] + ([(98, env * 0.7)] if self._gesture == "shake" else [])
            draw_side_arcs(base, fcx, fcy - 30, EYE_SPREAD + 95, arcs, EYE_MID)

        # ── eyes ──────────────────────────────────────────────────────────
        lx = fcx + self.left_eye.rel_x
        ly = fcy + self.left_eye.rel_y
        rx = fcx + self.right_eye.rel_x
        ry = fcy + self.right_eye.rel_y

        if not gl_face_on:                  # (the GPU draws eyes, brows, mouth)
            self.left_eye.draw(base, lx, ly,
                               angry=self._angry, happy=self._happy,
                               sad=self._sad, listening=self._listen,
                               color_override=self._eye_color,
                               angry_pulse=self.angry_pulse)
            self.right_eye.draw(base, rx, ry,
                                angry=self._angry, happy=self._happy,
                                sad=self._sad, listening=self._listen,
                                color_override=self._eye_color,
                                angry_pulse=self.angry_pulse)

            # ── mouth ─────────────────────────────────────────────────────
            mx = fcx + self.mouth.rel_x
            my = fcy + self.mouth.rel_y
            self.mouth.draw(base, mx, my, self._emotion,
                            self._speaking, self._audio_energy)
        if costume:
            draw_costume_front(base, fcx, fcy, costume[0], self)

        # ── hands (in front of the face) ──────────────────────────────────
        if HANDS:
            for side in ("L", "R"):
                hx, hy, ha = self.hand[side]
                if fcy + hy > HEIGHT + 60:      # fully tucked away
                    continue
                img = hand_surface(self.hand_pose[side], side)
                # rotate about the WRIST (bottom of the hand), not the centre:
                # the fingers swing while the base stays put (the glow and
                # the shadow are in the image: no bloom per frame)
                h0 = img.get_height() - 32          # (the image has 16 px round it)
                pivot = pygame.math.Vector2(0, h0 * 0.42)
                if abs(ha) > 0.5:
                    img = pygame.transform.rotozoom(img, ha, 1.0)   # (filtered: no jaggies)
                    pivot = pivot.rotate(-ha)
                wrist = pygame.math.Vector2(fcx + hx, fcy + hy + h0 * 0.42)
                rect = img.get_rect(center=(int(wrist.x - pivot.x),
                                            int(wrist.y - pivot.y)))
                base.blit(img, rect)
            if self._gesture == "heart":
                sz = int(50 + 12 * self._heart_pulse)
                draw_heart(base, fcx, fcy + (face_spec.LAYOUT["mouth_y"] + 70
                                             if EYE_MODE == "block" else 112), sz)

        # ── a big glyph between the eyes (game countdown) ────────────────
        big = self._big_text
        if big and time.time() < big[1]:
            self._draw_big(base, big[0], fcx, fcy, big[1] - time.time())

        # ── whatever the current scene draws on top ───────────────────────
        if self._scene:
            self._scene.draw(self, base, fcx, fcy, self._scene_p)

        # ── excited (the block face): three twinkles by the eyes' outer
        #    corners, anchored, coming and going — not a shower of stars ──
        if EYE_MODE == "block" and self._emotion == "excited" and not self._scene:
            t = time.time()
            ex = EYE_SPREAD + self.left_eye.w * 0.5
            ey = fcy + self.left_eye.rel_y
            for (dx, dy, r, ph) in ((-ex - 6, ey - 70, 18, 0.0), (ex + 10, ey - 58, 15, 2.1),
                                    (ex + 26, ey + 30, 11, 4.0)):
                k = max(0.0, math.sin(t * 2.6 + ph))
                twinkle(base, fcx + dx, dy, r * (0.6 + 0.4 * k), 255 * k)

        gl = getattr(self, "gl", None)
        life = getattr(gl, "life", None) if gl else None
        if EYE_MODE == "block" and life and not self._scene:
            mono = time.monotonic()
            k = life.bump(mono, life.pop_t, 0.5)
            if self._emotion == "surprised" and k > 0.02:   # the take: lines burst out
                for side in (-1, 1):
                    ex = fcx + side * (EYE_SPREAD + self.left_eye.w * 0.5 - 10)
                    ey = fcy + self.left_eye.rel_y - self.left_eye.h * 0.5 - 20
                    for a in (-0.5, 0.0, 0.5):
                        ang = (math.pi / 2 - side * (0.9 + a)) if side > 0 else (math.pi / 2 + 0.9 + a)
                        r0, r1 = 14 + 22 * k, 38 + 30 * k
                        dx, dy = math.cos(ang), -math.sin(ang)
                        pygame.draw.line(base, _lerp_col((0, 0, 0), IRIS_SHINE, k),
                                         (ex + dx * r0, ey + dy * r0), (ex + dx * r1, ey + dy * r1), 5)
            blush = getattr(gl, "blush_now", 0.0)
            if blush > 0.55:                      # rosy: the "///" lines on the cheeks
                blush_lines(base, fcx, fcy, min(1.0, (blush - 0.55) / 0.3))

        # ── angry (the block face): a pulsing anger mark by the right brow ──
        if EYE_MODE == "block" and self._emotion == "angry" and not self._scene:
            k = 0.5 + 0.5 * math.sin(time.time() * 6.0)
            anger_mark(base, fcx + EYE_SPREAD + self.right_eye.w * 0.5 + 34,
                       fcy + self.right_eye.rel_y - 92, 40 + 6 * k, 200 + 55 * k)

        # ── particles (foreground) ────────────────────────────────────────
        for p in self.zzz_particles:
            p.draw(base)
        for p in self.tear_particles:
            p.draw(base)
        for p in self.star_particles:
            p.draw(base)
        for p in self.heart_particles:
            p.draw(base)

        # ── awake indicator — small breathing dot while the conversation
        #    window is open; fades out when the wake word is needed again ──
        # (not on the block face: the status bar's mic and her eyes say it)
        if self.awake_glow > 0.04 and EYE_MODE != "block":
            pulse = 0.75 + 0.25 * math.sin(self.breath_phase * 1.6)
            a     = int(150 * self.awake_glow * pulse)
            r     = 7
            dot   = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(dot, (*AWAKE_COL, a // 3),
                               (r * 2, r * 2), r * 2)          # halo
            pygame.draw.circle(dot, (*AWAKE_COL, a),
                               (r * 2, r * 2), r)              # core
            base.blit(dot, (fcx - r * 2, fcy + AWAKE_DOT_Y - r * 2))

        # ── wake ripple ───────────────────────────────────────────────────
        if self.wake_anim == self._WAKE_ACTIVE:
            r     = int(self.wake_ripple * 300)
            alpha = int((1.0 - self.wake_ripple) * 120)
            if r > 0 and alpha > 0:
                s = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(s, (*EYE_INNER, alpha),
                                   (r + 2, r + 2), r, 6)
                base.blit(s, (fcx - r - 2, fcy - r - 2))

        t2 = time.perf_counter()
        # ── head tilt ─────────────────────────────────────────────────────
        if self.gl:
            # the GPU turns `base` itself (its own texture): the screen layer
            # keeps only what stays put — status bar, captions, overlays
            self.gl.clear(self.gl.screen_l, self.screen)
        elif abs(self.head_angle) > 0.4:    # below that the rotation can't be seen,
            st["tilted"] += 1               # but it costs ~4 ms of a full-screen turn
            rotated = pygame.transform.rotate(base, self.head_angle)
            rect    = rotated.get_rect(center=(WIDTH // 2, HEIGHT // 2))
            self.screen.fill(BG)
            self.screen.blit(rotated, rect)
        else:
            self.screen.blit(base, (0, 0))

        # ── scene post-processing on the finished frame (glitch…) ────────
        if self._scene:
            self._scene.post(self, self.screen, self._scene_p)

        # ── camera preview (on top, not rotated with the head) ───────────
        import settings
        if settings.get("camera_preview", CAMERA_PREVIEW):     # "pokaż podgląd kamery"
            self._draw_camera_preview()
        else:
            self._preview_surf = None

        # ── subtitles: what she says / what she heard ─────────────────────
        self._draw_caption()

        # ── the status bar along the top (statusbar.py): clock, radio,
        #    alarms, listening… — the corner icons below are for it off ──
        with state.lock:
            asleep = state.sleep_mode
        if not self.status_bar.draw(self.screen, AWAKE_COL, asleep=asleep):
            self._draw_corner_icons()

        # ── whole-screen moments: mirror, photo, clock, flash ─────────────
        if self._overlay_on():
            self._draw_overlay()
            with state.lock:                            # every page: ✕ to close it
                ov_now = state.overlay
            if ov_now and ov_now[0] not in ("flash", "gallery"):   # (the gallery: its own)
                ui_screens.draw_close(self.screen, WIDTH)

        t3 = time.perf_counter()
        if self.gl:
            u = self.gl.face_uniforms(self, sys.modules[__name__], fcx, fcy)
            # the layer behind the face is nearly always empty: not read at
            # all then (~0.7 ms a frame), unless it still has to be wiped
            drew_back = HAIR or costume or self.sound_waves or self.steam_particles
            self.gl.render(u, face_layer=base, screen_layer=self.screen,
                           back_layer=self.back if drew_back or self.gl.back_l.runs() else None)
        t35 = time.perf_counter()
        pygame.display.flip()
        t4 = time.perf_counter()
        st["gl"] += t35 - t3
        st["swap"] += t4 - t35
        st["fps"][self.fps] = st["fps"].get(self.fps, 0) + 1
        _count_present(st, t4)
        st["frames"] += 1
        st["update"] += t1 - t0
        st["face"] += t2 - t1
        st["compose"] += t3 - t2
        st["flip"] += t4 - t3

    def _draw_corner_icons(self):
        """The status bar switched off ("ukryj pasek"): the small icons in
        the corners instead."""
        # ── a running timer: small countdown, top-right corner ───────────
        with state.lock:
            timer_text = state.timer_text
            online     = state.online
        if timer_text:
            self._draw_timer(timer_text)

        # ── no cloud: a small crossed-out cloud, top-left ─────────────────
        if not online:
            self._draw_offline()

        # ── an unheard voice message: a small envelope, top-left ─────────
        with state.lock:
            waiting = state.messages_waiting
        if waiting:
            self._draw_envelope(84 if not online else 14)

        # ── the radio is on: a small note, top-left ───────────────────────
        with state.lock:
            radio_on = state.radio
            muted = time.time() < state.mic_muted_until
            cam_off = time.time() < state.camera_off_until
        if radio_on:
            self._draw_note(14 + (70 if not online else 0) + (70 if waiting else 0))

        # ── "nie słuchaj": a crossed-out microphone, top-left ─────────────
        if muted:
            self._draw_mic_off(14 + (70 if not online else 0) + (70 if waiting else 0)
                               + (60 if radio_on else 0))

        # ── "wyłącz kamerę": a crossed-out camera, next to them ──────────
        if cam_off:
            self._draw_cam_off(14 + (70 if not online else 0) + (70 if waiting else 0)
                               + (60 if radio_on else 0) + (56 if muted else 0))

    def _draw_big(self, surf, text, fcx, fcy, left):
        """A glowing number between her eyes; it pops in and fades out."""
        font = _get_font(150)
        img = font.render(text, True, STAR_COL)
        k = min(1.0, left / 0.25)                        # fade at the end
        scale = 1.0 + 0.25 * max(0.0, (left - 0.5)) # pops in slightly large
        if abs(scale - 1.0) > 0.02:
            img = pygame.transform.smoothscale(
                img, (int(img.get_width() * scale), int(img.get_height() * scale)))
        img.set_alpha(int(255 * k))
        rect = img.get_rect(center=(int(fcx), int(fcy - 30)))
        glow = img.copy()
        glow.fill((*GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
        bloom(surf, glow, rect.topleft, radius=10, passes=1, max_alpha=int(120 * k), grow=0.0)
        surf.blit(img, rect)

    def _draw_caption(self):
        with state.lock:
            cap = state.caption
        if not cap or time.time() > cap[2]:
            return
        try:
            import settings
            if not settings.get("captions", False):
                return
        except Exception:
            return
        who, text, _ = cap
        key = (who, text)
        if getattr(self, "_cap_cache", (None,))[0] != key:
            font = _get_font(24)
            words = (("Ty: " if who == "you" else "") + text).split()
            lines, line = [], ""
            for w in words:                          # wrap to the screen width
                test = (line + " " + w).strip()
                if font.size(test)[0] > WIDTH - 40 and line:
                    lines.append(line)
                    line = w
                else:
                    line = test
            if line:
                lines.append(line)
            if len(lines) > 3:                       # three lines, from the start
                lines = lines[:3]
                lines[2] = lines[2].rstrip(".,") + "…"
            col = EYE_INNER if who == "you" else TEETH_COL
            h = 12 + 28 * len(lines)
            band = pygame.Surface((WIDTH, h), pygame.SRCALPHA)
            band.fill((0, 0, 0, 175))
            for i, ln in enumerate(lines):
                img = font.render(ln, True, col)
                band.blit(img, img.get_rect(center=(WIDTH // 2, 6 + 14 + 28 * i)))
            self._cap_cache = (key, band)
        band = self._cap_cache[1]
        self.screen.blit(band, (0, HEIGHT - band.get_height()))

    def _lamp_scene(self):
        with state.lock:
            ov = state.overlay
        if ov and ov[0] == "lamp" and time.time() < ov[1]:
            return (ov[2] or {}).get("scene")
        return None

    def _draw_lamp_scene(self):
        """The lamp's picture (lamp_scenes.py, gl_lamp.py): the GPU draws it
        all; pygame only the clock's digits."""
        with state.lock:
            kind, until, data = state.overlay
        now = time.time()
        u = lamp_scenes.uniforms(data, now, until, WIDTH, HEIGHT)
        self.gl.clear(self.gl.screen_l, self.screen)
        if data.get("scene") == "zegar":
            lamp_scenes.draw_clock(self.screen, now, WIDTH, HEIGHT, u["uK"][2])
        self.gl.render_lamp(u, self.screen)
        pygame.display.flip()

    def _overlay_on(self):
        with state.lock:
            ov = state.overlay
        return bool(ov) and time.time() < ov[1]

    def _draw_overlay(self):
        with state.lock:
            kind, until, data = state.overlay
            frame = state.frame if kind == "mirror" else None
        left = until - time.time()
        scr = self.screen
        if kind == "flash":
            scr.fill((255, 255, 255))
            self._flash_t = time.time()           # (after it: dazzled, gl_face)
            return
        if kind == "mirror":
            if frame is None:
                return
            h, w = frame.shape[:2]
            img = pygame.image.frombuffer(frame.tobytes(), (w, h), "BGR")
            img = pygame.transform.flip(img, True, False)
            sw = int(w * HEIGHT / h)
            img = pygame.transform.scale(img, (sw, HEIGHT))
            scr.fill(BG)
            scr.blit(img, ((WIDTH - sw) // 2, 0))
        elif kind == "gallery":                         # photos, drawings (gallery.py)
            now = time.time()
            with state.lock:
                going = gallery.tick(data, now)
                if not going and state.overlay and state.overlay[2] is data:
                    state.overlay = None
            if going:
                ui_screens.draw_gallery(scr, data, now, WIDTH, HEIGHT)
        elif kind == "photo":
            # one picture: a Wikipedia photo, the flag quiz ({"path", "sub"})
            path, sub = (data["path"], data.get("sub")) if isinstance(data, dict) else (data, None)
            ui_screens.draw_photo(scr, path, sub, WIDTH, HEIGHT)
        elif kind == "weather":                         # "pokaż pogodę"
            ui_screens.draw_weather(scr, data, time.time(), WIDTH, HEIGHT)
        elif kind == "lamp":
            inner, outer = (lamp_scenes.FALLBACK.get((data or {}).get("scene"))   # (no GPU)
                            or (data or {}).get("col") or ((255, 214, 150), (120, 50, 8)))
            if getattr(self, "_lamp", (None,))[0] != (inner, outer):
                lamp = pygame.Surface((WIDTH, HEIGHT))
                cx, cy = WIDTH // 2, HEIGHT // 2
                maxr = int(math.hypot(cx, cy))
                for r in range(maxr, 0, -6):                 # radial glow
                    k = r / maxr
                    col = _lerp_col(inner, outer, k ** 0.8)
                    pygame.draw.circle(lamp, col, (cx, cy), r)
                self._lamp = ((inner, outer), lamp)
            scr.blit(self._lamp[1], (0, 0))
        elif kind == "clockface":
            # an analogue clock to read (clockgame.py): numbers, ticks, two hands
            scr.fill(BG)
            cx, cy, R = WIDTH // 2, HEIGHT // 2 - 18, min(WIDTH, HEIGHT) // 2 - 50
            pygame.draw.circle(scr, (30, 26, 40), (cx, cy), R)
            pygame.draw.circle(scr, STAR_COL, (cx, cy), R, 5)
            font = _get_font(30)
            for i in range(60):
                a = math.radians(i * 6 - 90)
                r0 = R - (16 if i % 5 == 0 else 8)
                pygame.draw.line(scr, EYE_MID, (cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                                 (cx + (R - 4) * math.cos(a), cy + (R - 4) * math.sin(a)),
                                 3 if i % 5 == 0 else 1)
            for n in range(1, 13):
                a = math.radians(n * 30 - 90)
                img = font.render(str(n), True, STAR_COL)
                scr.blit(img, img.get_rect(center=(cx + (R - 42) * math.cos(a),
                                                   cy + (R - 42) * math.sin(a))))
            h, m = data["h"], data["m"]
            for ang, length, width, col in (
                    ((h % 12 + m / 60) * 30, R * 0.45, 10, (255, 240, 200)),   # hour
                    (m * 6, R - 66, 6, STAR_COL)):                           # minute
                a = math.radians(ang - 90)
                pygame.draw.line(scr, col, (cx, cy),
                                 (cx + length * math.cos(a), cy + length * math.sin(a)), width)
            pygame.draw.circle(scr, (255, 240, 200), (cx, cy), 9)
            if data.get("sub"):
                sub = _get_font(26).render(data["sub"], True, EYE_MID)
                scr.blit(sub, sub.get_rect(center=(WIDTH // 2, HEIGHT - 22)))
        elif kind == "stars":
            # stars collected for perfect rounds (quiz.py): a grid of gold stars,
            # the newest one pops in; the name and the count below
            scr.fill(BG)
            n, t = data["n"], time.time() - data["t0"]
            shown = min(n, 24)
            cols = min(shown, 8) or 1
            rows = (shown + cols - 1) // cols if shown else 0
            size = 34 if shown > 8 else 44 if shown > 3 else 70
            gap = size * 2.4
            for i in range(shown):
                r, c = divmod(i, cols)
                x = WIDTH / 2 + (c - (cols - 1) / 2) * gap
                y = HEIGHT / 2 - 40 + (r - (rows - 1) / 2) * gap
                k = 1.0
                if data.get("new") and i == shown - 1:   # the new one: pops in
                    k = min(1.0, t / 0.6) * (1 + 0.35 * math.sin(min(1.0, t / 0.6) * math.pi))
                _draw_star(scr, x, y, size * k, (255, 205, 60), (255, 240, 170))
            label = f"{data['name']}: {n}"
            img = _get_font(40).render(label, True, STAR_COL)
            scr.blit(img, img.get_rect(center=(WIDTH // 2, HEIGHT - 60)))
        elif kind == "card":
            # a quiz question or a spelled word — big, in the middle (quiz.py,
            # commands.py); "ok" glows green, "bad" warm red
            col = {"ok": (120, 230, 140), "bad": (255, 120, 100)}.get(data.get("tone"),
                                                                       STAR_COL)
            key = (data["text"], data.get("sub"), col)
            if getattr(self, "_card_cache", (None,))[0] != key:
                text = data["text"]
                size = 130
                font = _get_font(size)
                while font.size(text)[0] > WIDTH - 60 and size > 40:
                    size -= 10
                    font = _get_font(size)
                lines = [text]
                if size < 70 and " " in text:
                    # a sentence (reading practice): two lines, bigger letters
                    words = text.split()
                    cut = min(range(1, len(words)), key=lambda k: abs(
                        len(" ".join(words[:k])) - len(" ".join(words[k:]))))
                    lines = [" ".join(words[:cut]), " ".join(words[cut:])]
                    size = 110
                    font = _get_font(size)
                    while max(font.size(x)[0] for x in lines) > WIDTH - 60 and size > 40:
                        size -= 10
                        font = _get_font(size)
                imgs = [font.render(x, True, col) for x in lines]
                w = max(i.get_width() for i in imgs)
                h = sum(i.get_height() for i in imgs)
                img = pygame.Surface((w, h), pygame.SRCALPHA)
                y = 0
                for i in imgs:
                    img.blit(i, ((w - i.get_width()) // 2, y))
                    y += i.get_height()
                sub = None
                if data.get("sub"):                # the hint line fits the screen too
                    st, ss = data["sub"], 30
                    while _get_font(ss).size(st)[0] > WIDTH - 40 and ss > 22:
                        ss -= 2
                    sf = _get_font(ss)
                    parts = [st]
                    if sf.size(st)[0] > WIDTH - 40 and " · " in st:
                        cut = st.rfind(" · ", 0, len(st) // 2 + 10) or st.find(" · ")
                        parts = [st[:cut], st[cut + 3:]]
                    rendered = [sf.render(x, True, EYE_MID) for x in parts]
                    sub = pygame.Surface((max(r.get_width() for r in rendered),
                                          sum(r.get_height() for r in rendered)), pygame.SRCALPHA)
                    yy = 0
                    for r in rendered:
                        sub.blit(r, ((sub.get_width() - r.get_width()) // 2, yy))
                        yy += r.get_height()
                self._card_cache = (key, img, sub, len(lines))
            _, img, sub, nlines = self._card_cache
            scr.fill(BG)
            rect = img.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 20 - 30 * (nlines - 1)))
            if nlines == 1:                    # the glow smears a wide two-line block
                glow = img.copy()
                glow.fill((*GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
                bloom(scr, glow, rect.topleft, radius=8, passes=1, max_alpha=70, grow=0.0)
            scr.blit(img, rect)
            if sub:
                scr.blit(sub, sub.get_rect(center=(WIDTH // 2,
                                                   max(HEIGHT // 2 + 90, rect.bottom + 30))))
        elif kind == "dice":
            scr.fill(BG)
            t = time.time() - data["t0"]
            n = len(data["results"])
            rolling = t < 1.4
            for j, res in enumerate(data["results"]):
                face_n = random.randint(1, 6) if rolling else res
                size = 150
                d = pygame.Surface((size, size), pygame.SRCALPHA)
                pygame.draw.rect(d, (250, 246, 236), d.get_rect(), border_radius=26)
                pip = {1: [(2, 2)], 2: [(1, 1), (3, 3)], 3: [(1, 1), (2, 2), (3, 3)],
                       4: [(1, 1), (1, 3), (3, 1), (3, 3)],
                       5: [(1, 1), (1, 3), (2, 2), (3, 1), (3, 3)],
                       6: [(1, 1), (1, 2), (1, 3), (3, 1), (3, 2), (3, 3)]}[face_n]
                for px, py in pip:
                    pygame.draw.circle(d, (40, 30, 20), (px * size // 4, py * size // 4), 14)
                if rolling:
                    d = pygame.transform.rotate(d, (t * 720 + j * 90) % 360)
                x = WIDTH // 2 + (j - (n - 1) / 2) * 200
                y = HEIGHT // 2 - (40 * abs(math.sin(t * 9)) if rolling else 0)
                scr.blit(d, d.get_rect(center=(int(x), int(y))))
        elif kind == "coin":
            scr.fill(BG)
            t = time.time() - data["t0"]
            flipping = t < 1.5
            squash = abs(math.cos(t * 14)) if flipping else 1.0
            r = 110
            w = max(6, int(2 * r * squash))
            coin = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
            pygame.draw.circle(coin, (232, 186, 70), (r, r), r)
            pygame.draw.circle(coin, (190, 140, 40), (r, r), r, 8)
            if not flipping:
                txt = _get_font(42).render(data["side"], True, (110, 70, 10))
                coin.blit(txt, txt.get_rect(center=(r, r)))
            coin = pygame.transform.smoothscale(coin, (w, 2 * r))
            y = HEIGHT // 2 - (120 * math.sin(min(1.0, t / 1.5) * math.pi) if flipping else 0)
            scr.blit(coin, coin.get_rect(center=(WIDTH // 2, int(y))))
        elif kind == "breath":
            t0, t_in, t_hold, t_out = data
            u = (time.time() - t0) % (t_in + t_hold + t_out)
            ease = lambda x: 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))
            if time.time() < t0 or u < t_in:
                k, word = ease(u / t_in) if time.time() >= t0 else 0.0, "wdech"
            elif u < t_in + t_hold:
                k, word = 1.0, "zatrzymaj"
            else:
                k, word = 1.0 - ease((u - t_in - t_hold) / t_out), "wydech"
            scr.fill(BG)
            r = int(70 + 120 * k)
            c = (WIDTH // 2, HEIGHT // 2 - 20)
            draw_glow_circle(scr, GLOW_COL, c, r, layers=5, max_alpha=60)
            pygame.draw.circle(scr, _lerp_col(EYE_OUTER, EYE_INNER, k), c, r)
            pygame.draw.circle(scr, IRIS_SHINE, c, r, 3)
            txt = _get_font(40).render(word, True, EYE_INNER)
            scr.blit(txt, txt.get_rect(center=(WIDTH // 2, HEIGHT - 45)))
        elif kind == "story":                           # a story: picture, choices; the list
            ui_screens.draw_story(scr, data, time.time(), WIDTH, HEIGHT)
        elif kind == "schedule":                        # "plan tygodnia" (schedule.py)
            import ui_schedule
            ui_schedule.draw(scr, data, time.time(), WIDTH, HEIGHT)
        elif kind == "radio":                           # the stations to pick from
            ui_screens.draw_radio(scr, data, time.time(), WIDTH, HEIGHT)
        elif kind == "settings":                        # "pokaż ustawienia" (settings_page.py)
            ui_screens.draw_settings(scr, data, time.time(), WIDTH, HEIGHT)
        elif kind == "list":                            # lists, plan, reminders, status
            ui_screens.draw_list(scr, data[0], data[1], time.time(), WIDTH, HEIGHT,
                                 data[2] if len(data) > 2 else None)
        elif kind == "memo":
            # the memory game (memo.py): 4 × 3 cards
            scr.fill(BG)
            ncol, nrow, cw, ch, gap = data.get("layout", (4, 3, 150, 130, 14))
            left = (WIDTH - (ncol * cw + (ncol - 1) * gap)) // 2
            top = (HEIGHT - (nrow * ch + (nrow - 1) * gap)) // 2
            cols = {"circle": (255, 90, 90), "square": (90, 160, 255),
                    "triangle": (110, 220, 120), "star": (255, 215, 70),
                    "heart": (255, 120, 200), "diamond": (180, 120, 255),
                    "moon": (240, 240, 255), "cross": (255, 150, 60)}
            for i, shape in enumerate(data["cards"]):
                x = left + (i % ncol) * (cw + gap)
                y = top + (i // ncol) * (ch + gap)
                rect = pygame.Rect(x, y, cw, ch)
                if i not in data["up"]:
                    pygame.draw.rect(scr, EYE_MID, rect, border_radius=16)
                    pygame.draw.rect(scr, STAR_COL, rect.inflate(-18, -18), 3,
                                     border_radius=12)
                    continue
                pygame.draw.rect(scr, (40, 40, 52), rect, border_radius=16)
                if i in data["found"]:
                    pygame.draw.rect(scr, (120, 230, 140), rect, 4, border_radius=16)
                cx, cy, r = x + cw // 2, y + ch // 2, int(min(cw, ch) * 0.32)
                col = cols[shape]
                if shape == "circle":
                    pygame.draw.circle(scr, col, (cx, cy), r)
                elif shape == "square":
                    pygame.draw.rect(scr, col, pygame.Rect(cx - r + 6, cy - r + 6,
                                                           2 * r - 12, 2 * r - 12))
                elif shape == "triangle":
                    pygame.draw.polygon(scr, col, [(cx, cy - r), (cx - r, cy + r - 8),
                                                   (cx + r, cy + r - 8)])
                elif shape == "star":
                    _draw_star(scr, cx, cy, r + 4, col, (255, 255, 255))
                elif shape == "heart":
                    k = r / 42
                    pygame.draw.circle(scr, col, (cx - int(19 * k), cy - int(10 * k)), int(22 * k))
                    pygame.draw.circle(scr, col, (cx + int(19 * k), cy - int(10 * k)), int(22 * k))
                    pygame.draw.polygon(scr, col, [(cx - int(41 * k), cy - int(7 * k)),
                                                   (cx + int(41 * k), cy - int(7 * k)),
                                                   (cx, cy + int(40 * k))])
                elif shape == "moon":
                    pygame.draw.circle(scr, col, (cx, cy), r)
                    pygame.draw.circle(scr, (40, 40, 52), (cx + r // 2, cy - r // 4), r)
                elif shape == "cross":
                    t = max(8, r // 3)
                    pygame.draw.rect(scr, col, pygame.Rect(cx - t, cy - r, 2 * t, 2 * r))
                    pygame.draw.rect(scr, col, pygame.Rect(cx - r, cy - t, 2 * r, 2 * t))
                else:
                    pygame.draw.polygon(scr, col, [(cx, cy - r), (cx + r - 6, cy),
                                                   (cx, cy + r), (cx - r + 6, cy)])
            msg = _get_font(24).render(data.get("msg", ""), True, EYE_MID)
            scr.blit(msg, msg.get_rect(midbottom=(WIDTH // 2, HEIGHT - 2)))
        elif kind == "ttt":
            # noughts and crosses (tictac.py): a 420 px board in the middle
            scr.fill(BG)
            size = 420
            left, top = (WIDTH - size) // 2, (HEIGHT - size) // 2
            for k in (1, 2):
                pygame.draw.line(scr, EYE_MID, (left + k * 140, top + 12),
                                 (left + k * 140, top + size - 12), 5)
                pygame.draw.line(scr, EYE_MID, (left + 12, top + k * 140),
                                 (left + size - 12, top + k * 140), 5)
            for i, v in enumerate(data["b"]):
                cx = left + (i % 3) * 140 + 70
                cy = top + (i // 3) * 140 + 70
                if v == "X":
                    for d in (1, -1):
                        pygame.draw.line(scr, (110, 200, 255), (cx - 40, cy - 40 * d),
                                         (cx + 40, cy + 40 * d), 12)
                elif v == "O":
                    pygame.draw.circle(scr, EYE_INNER, (cx, cy), 44, 10)
            if data.get("line"):
                a, b = data["line"][0], data["line"][2]
                pa = (left + (a % 3) * 140 + 70, top + (a // 3) * 140 + 70)
                pb = (left + (b % 3) * 140 + 70, top + (b // 3) * 140 + 70)
                pygame.draw.line(scr, (255, 255, 255), pa, pb, 8)
            words = data.get("msg", "").split(" · ")
            for j, w in enumerate(words):
                img = _get_font(30 if j == 0 else 22).render(w, True, EYE_MID if j else STAR_COL)
                scr.blit(img, img.get_rect(midleft=(left + size + 18, HEIGHT // 2 - 20 + j * 40)))
            sides = ((("X", "gracz 1"), ("O", "gracz 2")) if data.get("duo") else
                     (("X", "ty"), ("O", "Luna")))
            for j, (mark, who) in enumerate(sides):
                img = _get_font(26).render(f"{mark} — {who}", True,
                                           (110, 200, 255) if mark == "X" else EYE_INNER)
                scr.blit(img, img.get_rect(midright=(left - 18, HEIGHT // 2 - 20 + j * 40)))
        elif kind == "clock":
            scr.fill(BG)
            big = _get_font(190).render(time.strftime("%H:%M"), True, EYE_MID)
            days = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek",
                    "sobota", "niedziela"]
            months = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
                      "lipca", "sierpnia", "września", "października", "listopada",
                      "grudnia"]
            lt = time.localtime()
            small = _get_font(42).render(
                f"{days[lt.tm_wday]}, {lt.tm_mday} {months[lt.tm_mon - 1]}", True, EYE_INNER)
            rect = big.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
            glow = big.copy()
            glow.fill((*GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
            bloom(scr, glow, rect.topleft, radius=10, passes=1, max_alpha=110, grow=0.0)
            scr.blit(big, rect)
            scr.blit(small, small.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 85)))
        # fade out in the last half second
        if left < 0.5:
            veil = pygame.Surface((WIDTH, HEIGHT))
            veil.fill(BG)
            veil.set_alpha(int(255 * (1 - left / 0.5)))
            scr.blit(veil, (0, 0))

    def _draw_mic_off(self, x):
        if getattr(self, "_micoff", None) is None:
            s = pygame.Surface((44, 46), pygame.SRCALPHA)
            col = (*STAR_COL, 230)
            pygame.draw.rect(s, col, pygame.Rect(15, 3, 14, 24), 3, border_radius=7)
            pygame.draw.arc(s, col, pygame.Rect(8, 12, 28, 24), math.pi, 2 * math.pi, 3)
            pygame.draw.line(s, col, (22, 36), (22, 43), 3)
            pygame.draw.line(s, (255, 110, 90, 240), (6, 4), (38, 42), 4)   # crossed out
            self._micoff = s
        self.screen.blit(self._micoff, (x, 12))

    def _draw_cam_off(self, x):
        if getattr(self, "_camoff", None) is None:
            s = pygame.Surface((50, 46), pygame.SRCALPHA)
            col = (*STAR_COL, 230)
            pygame.draw.rect(s, col, pygame.Rect(4, 12, 42, 28), 3, border_radius=6)   # body
            pygame.draw.rect(s, col, pygame.Rect(16, 6, 16, 8), 3, border_radius=2)    # top
            pygame.draw.circle(s, col, (25, 26), 8, 3)                                 # lens
            pygame.draw.line(s, (255, 110, 90, 240), (4, 4), (46, 44), 4)   # crossed out
            self._camoff = s
        self.screen.blit(self._camoff, (x, 12))

    def _draw_note(self, x):
        if getattr(self, "_note", None) is None:
            s = pygame.Surface((44, 44), pygame.SRCALPHA)
            col = (*STAR_COL, 230)
            pygame.draw.ellipse(s, col, pygame.Rect(4, 28, 15, 11))      # two heads
            pygame.draw.ellipse(s, col, pygame.Rect(24, 24, 15, 11))
            pygame.draw.line(s, col, (17, 33), (17, 6), 3)              # stems
            pygame.draw.line(s, col, (37, 29), (37, 3), 3)
            pygame.draw.polygon(s, col, [(17, 6), (37, 3), (37, 10), (17, 13)])   # beam
            self._note = s
        bob = 3 * math.sin(time.time() * 3.0)                           # a little sway
        self.screen.blit(self._note, (x, 12 + int(bob)))

    def _draw_envelope(self, x):
        if getattr(self, "_envelope", None) is None:
            s = pygame.Surface((56, 40), pygame.SRCALPHA)
            col = (*STAR_COL, 230)
            pygame.draw.rect(s, col, pygame.Rect(2, 4, 52, 34), 3, border_radius=5)
            pygame.draw.lines(s, col, False, [(4, 7), (28, 24), (52, 7)], 3)
            self._envelope = s
        pulse = 0.6 + 0.4 * abs(math.sin(time.time() * 2.0))
        env = self._envelope.copy()
        env.set_alpha(int(255 * pulse))
        self.screen.blit(env, (x, 12))

    def _draw_offline(self):
        if getattr(self, "_offline_icon", None) is None:
            s = pygame.Surface((64, 44), pygame.SRCALPHA)
            col = (*EYE_MID, 210)
            for cx, cy, r in ((20, 26, 11), (32, 19, 14), (45, 26, 11)):
                pygame.draw.circle(s, col, (cx, cy), r)
            pygame.draw.rect(s, col, pygame.Rect(18, 26, 30, 11))
            pygame.draw.line(s, (*ANGRY_COL, 235), (10, 40), (54, 4), 5)
            self._offline_icon = s
        self.screen.blit(self._offline_icon, (14, 10))

    def _draw_timer(self, text):
        """A little clock and the time left, top-right. Cached per text."""
        if getattr(self, "_timer_cache", (None,))[0] != text:
            font = _get_font(34)
            label = font.render(text, True, EYE_MID)
            w, h = label.get_width() + 46, max(label.get_height(), 32) + 8
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            c = (18, h // 2)
            pygame.draw.circle(surf, EYE_MID, c, 13, 3)            # clock face
            pygame.draw.line(surf, EYE_MID, c, (c[0], c[1] - 8), 3)
            pygame.draw.line(surf, EYE_MID, c, (c[0] + 6, c[1]), 3)
            surf.blit(label, (40, (h - label.get_height()) // 2))
            surf.set_alpha(200)
            self._timer_cache = (text, surf)
        surf = self._timer_cache[1]
        self.screen.blit(surf, (WIDTH - surf.get_width() - 14, 10))

    # ── small mirrored camera view, bottom-right ──────────────────────────
    _preview_surf  = None
    _preview_tick  = 0

    def _draw_camera_preview(self):
        self._preview_tick += 1
        if self._preview_tick % 2 == 0 or self._preview_surf is None:   # ~15 fps
            with state.lock:
                frame = state.frame
                fd    = state.face_detected
                fx, fy, fw = state.face_x, state.face_y, state.face_w
            if frame is not None:
                import cv2
                pw = CAMERA_PREVIEW_W
                ph = int(pw * frame.shape[0] / frame.shape[1])
                small = cv2.resize(frame, (pw, ph), interpolation=cv2.INTER_AREA)
                small = cv2.flip(small, 1)                     # mirror, like face_x
                rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                surf  = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))
                if fd:
                    # face_x is already mirrored → matches the flipped image
                    bw = int(fw * pw); bh = int(bw * 1.25)
                    cx, cy = int(fx * pw), int(fy * ph)
                    pygame.draw.rect(surf, EYE_MID,
                                     pygame.Rect(cx - bw // 2, cy - bh // 2, bw, bh), 2)
                self._preview_surf = surf
            else:
                self._preview_surf = None      # camera off: no frozen picture
        if self._preview_surf is None:
            return
        surf = self._preview_surf
        x = WIDTH - surf.get_width() - 10
        y = HEIGHT - surf.get_height() - 10
        pygame.draw.rect(self.screen, EYE_OUTER,
                         pygame.Rect(x - 2, y - 2, surf.get_width() + 4,
                                     surf.get_height() + 4), 2, border_radius=4)
        self.screen.blit(surf, (x, y))


# Registering the scene catalogue last: reply_scenes reaches back into this
# module for the drawing helpers and the live palette, so it can only be
# imported once everything above exists.
import reply_scenes  # noqa: E402
