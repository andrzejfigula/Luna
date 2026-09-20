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

import pygame
import math
import random
import time
import numpy as np
from shared_state import state
from config import (RENDER_FPS, FACE_STYLE, SCREEN_WIDTH, SCREEN_HEIGHT,
                    FULLSCREEN, HIDE_CURSOR, GESTURE_DURATION)

# The face geometry below is in absolute pixels and was drawn for a 1400x800
# window; it fits the 800x480 DSI panel as-is (~560x400 used), just larger
# relative to the screen — which suits a desktop-robot face.
WIDTH  = SCREEN_WIDTH
HEIGHT = SCREEN_HEIGHT

BG        = (0, 0, 0)
PUPIL_COL = (0, 0, 0)

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
        EYE_MODE="block", EYE_SCALE=1.18, EYE_SPREAD=150,
        EYE_GRAD_TOP=(255, 232, 140), EYE_GRAD_BOTTOM=(232, 96, 12),
        BLOCK_PUPIL=True, PUPIL_DARK=(28, 12, 2),
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
    global BLOCK_PUPIL, PUPIL_DARK, BROW_GRAD_TOP, BROW_GRAD_BOTTOM
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

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


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


def bloom(surf, layer, pos, radius=10, passes=2, max_alpha=110):
    """Soft glow that follows an arbitrary SRCALPHA shape. Cheap blur:
    pad, shrink, enlarge (smoothscale both ways) — then blit behind."""
    lw, lh = layer.get_size()
    pad = radius * 3
    big = pygame.Surface((lw + pad * 2, lh + pad * 2), pygame.SRCALPHA)
    big.blit(layer, (pad, pad))
    bw, bh = big.get_size()
    small = pygame.transform.smoothscale(big, (max(2, bw // radius), max(2, bh // radius)))
    for i in range(passes, 0, -1):
        k = 1.0 + 0.10 * i
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


def _get_font(size):
    f = _FONT_CACHE.get(size)
    if f is None:
        f = pygame.font.SysFont("monospace", size, bold=True)
        _FONT_CACHE[size] = f
    return f


# ── Particles ─────────────────────────────────────────────────────────────────

class ZzzParticle:
    def __init__(self, x, y):
        self.x     = x
        self.y     = y
        self.alpha = 255
        self.size  = random.randint(18, 36)
        self.vx    = random.uniform(-0.4, 0.4)
        self.vy    = random.uniform(-1.2, -0.6)

    def update(self):
        self.x    += self.vx
        self.y    += self.vy
        self.alpha = max(0, self.alpha - 3)

    def alive(self): return self.alpha > 0

    def draw(self, surf):
        try:
            txt = _get_font(self.size).render("z", True, ZZZ_COL)
            txt.set_alpha(self.alpha)
            surf.blit(txt, (int(self.x), int(self.y)))
        except Exception:
            pass


class TearParticle:
    def __init__(self, x, y):
        self.x     = float(x)
        self.y     = float(y)
        self.alpha = 200
        self.r     = random.randint(6, 10)
        self.vy    = random.uniform(1.0, 2.0)
        self.vx    = random.uniform(-0.2, 0.2)

    def update(self):
        self.x    += self.vx
        self.y    += self.vy
        self.vy   += 0.1   # gravity
        self.alpha = max(0, self.alpha - 2)

    def alive(self): return self.alpha > 0

    def draw(self, surf):
        s = pygame.Surface((self.r * 2 + 4, self.r * 3 + 4), pygame.SRCALPHA)
        # teardrop shape — circle + small triangle above
        pygame.draw.circle(s, (*TEAR_COL, self.alpha),
                           (self.r + 2, self.r * 2 + 2), self.r)
        pts = [(self.r + 2, 2),
               (self.r - 4, self.r * 2 - 4),
               (self.r + 8, self.r * 2 - 4)]
        pygame.draw.polygon(s, (*TEAR_COL, self.alpha), pts)
        surf.blit(s, (int(self.x) - self.r - 2, int(self.y) - self.r - 2))


class SteamParticle:
    def __init__(self, x, y):
        self.x     = float(x)
        self.y     = float(y)
        self.alpha = 180
        self.r     = random.randint(5, 12)
        self.vx    = random.uniform(-0.5, 0.5)
        self.vy    = random.uniform(-1.5, -0.8)

    def update(self):
        self.x    += self.vx
        self.y    += self.vy
        self.alpha = max(0, self.alpha - 4)
        self.r     = max(1, self.r - 0.1)

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
        self.x    += self.vx
        self.y    += self.vy
        self.vx   *= 0.92
        self.vy   *= 0.92
        self.alpha = max(0, self.alpha - 6)

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
        self.sway += 0.1
        self.x    += self.vx + math.sin(self.sway) * 0.6
        self.y    += self.vy
        self.alpha = max(0, self.alpha - 3)

    def alive(self): return self.alpha > 0

    def draw(self, surf):
        r = self.size
        s = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
        col = (*HEART_COL, int(self.alpha))
        # two circles + triangle = heart
        cr = max(2, r // 2)
        pygame.draw.circle(s, col, (2 + cr, 2 + cr), cr)
        pygame.draw.circle(s, col, (2 + r + cr - 1, 2 + cr), cr)
        pts = [(2, 2 + cr), (2 + r * 2, 2 + cr), (2 + r, 2 + r * 2)]
        pygame.draw.polygon(s, col, pts)
        surf.blit(s, (int(self.x) - r, int(self.y) - r))


class SoundWave:
    def __init__(self, x, y):
        self.x     = x
        self.y     = y
        self.r     = 20.0
        self.alpha = 180
        self.max_r = random.randint(80, 140)

    def update(self):
        self.r    += 3.5
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
        self.alpha = lerp(self.alpha, target_alpha, 0.04)

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
        self.w           = lerp(self.w,           target_w,    0.10)
        self.h           = lerp(self.h,           target_h,    0.10)
        self.blink_t     = lerp(self.blink_t,     blink_t,     0.30)
        self.pupil_ox    = lerp(self.pupil_ox,    pupil_ox,    0.18)
        self.pupil_oy    = lerp(self.pupil_oy,    pupil_oy,    0.18)
        self.pupil_scale = lerp(self.pupil_scale, pupil_scale, 0.10)
        self.squint      = lerp(self.squint,      squint,      0.08)
        self.widen       = lerp(self.widen,       widen,       0.08)
        self.droop       = lerp(self.droop,       droop,       0.06)

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


# ── Hands (style extra) ───────────────────────────────────────────────────────
# Rounded "mitten" hands drawn as gradient blocks. Poses:
#   open      — palm + 4 fingers + thumb (waving, heart)
#   thumb     — fist with the thumb up
def hand_surface(pose, side):
    """Cached hand image for a pose; side 'L'/'R' mirrors it."""
    key = (pose, side)
    s = _HAND_CACHE.get(key)
    if s is not None:
        return s
    S = 1.6                                   # hand scale
    W_, H_ = int(120 * S), int(150 * S)
    s = pygame.Surface((W_, H_), pygame.SRCALPHA)
    top, bot = HAND_GRAD_TOP, HAND_GRAD_BOTTOM

    def block(w, h, r, cx, cy, angle=0):
        b = gradient_block(int(w * S), int(h * S), int(r * S), top, bot)
        if angle:
            b = pygame.transform.rotate(b, angle)
        s.blit(b, b.get_rect(center=(int(cx * S), int(cy * S))))

    if pose == "thumb":
        block(24, 60, 12, 32, 66, 6)               # thumb up (base under the fist)
        block(70, 66, 26, 60, 104)                 # fist
        for i in range(4):                         # curled finger ridges
            block(14, 22, 6, 44 + i * 13, 82)
    else:                                          # open palm
        # thumb first so its base sits UNDER the palm (attached, not floating)
        block(20, 50, 9, 22, 86, -34)
        block(66, 70, 26, 60, 108)                 # palm
        for i, (dx, fh) in enumerate(((-24, 44), (-8, 52), (8, 50), (24, 42))):
            block(16, fh, 7, 60 + dx, 78 - (fh - 40) // 2)
    if side == "L":
        s = pygame.transform.flip(s, True, False)
    _HAND_CACHE[key] = s
    return s


def draw_heart(surf, cx, cy, size, alpha=255):
    r = size // 2
    hs = pygame.Surface((size * 2 + 8, size * 2 + 8), pygame.SRCALPHA)
    ox, oy = size + 4, size // 2 + 4
    col = (*HEART_COL, alpha)
    pygame.draw.circle(hs, col, (ox - r // 1, oy), r)
    pygame.draw.circle(hs, col, (ox + r // 1, oy), r)
    pygame.draw.polygon(hs, col, [(ox - size + 1, oy + r // 3),
                                  (ox + size - 1, oy + r // 3),
                                  (ox, oy + size + r // 2)])
    surf.blit(hs, (cx - ox, cy - oy))


# ── Mouth ─────────────────────────────────────────────────────────────────────
class Mouth:
    def __init__(self, rel_x, rel_y):
        self.rel_x        = rel_x
        self.rel_y        = rel_y
        self.talk_open    = 0.0
        self.mouth_w      = 140.0
        self.visible      = 0.0
        self.corner_lift  = 0.0   # smile corners
        self.jaw_bounce   = 0.0   # extra bounce on high energy
        self.prev_energy  = 0.0

    def update(self, energy, emotion, speaking):
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

        self.visible      = lerp(self.visible, target_visible, 0.20)  # faster open
        self.corner_lift  = lerp(self.corner_lift,
                                    0.8 if emotion in ("happy", "excited", "love")
                                    else 0.0, 0.08)

        if speaking:
            # use energy directly but floor at 0.15 so mouth is never fully closed
            # while speaking — prevents dead mouth between words
            effective_energy = max(0.04, energy)   # real lip sync: pauses close the mouth
            target_open      = effective_energy
            self.talk_open   = lerp(self.talk_open, target_open, 0.30)
            self.mouth_w     = lerp(self.mouth_w,
                                    190.0 if energy > 0.5 else 150.0, 0.12)
            delta = energy - self.prev_energy
            if delta > 0.15:
                self.jaw_bounce = min(1.0, self.jaw_bounce + delta * 2)
            self.jaw_bounce = lerp(self.jaw_bounce, 0.0, 0.20)
        else:
            self.talk_open  = lerp(self.talk_open, 0.0, 0.15)
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

        # ── SPEAKING — robotic bars or 4-shape jaw ────────────────────────
        if speaking and MOUTH_STYLE == "bars":
            self._draw_bars(surf, cx, cy, alpha)
            return

        if speaking:
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
                # CLOSED — thin line with slight curve
                cl = int(self.corner_lift * 8)
                pts = [
                    (cx - 70, cy + cl),
                    (cx - 20, cy - cl // 2),
                    (cx,      cy - cl),
                    (cx + 20, cy - cl // 2),
                    (cx + 70, cy + cl),
                ]
                if len(pts) >= 2:
                    pygame.draw.lines(surf, MOUTH_COL, False, pts, 10)
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

        #elif emotion == "surprised":
            # O shape
          #  r = 52
          #  os_ = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
          #  draw_glow_circle(os_, GLOW_COL, (r + 2, r + 2), r)
          #  pygame.draw.circle(os_, (*MOUTH_COL, alpha), (r + 2, r + 2), r)
          #  pygame.draw.circle(os_, (*PUPIL_COL, alpha), (r + 2, r + 2),
          #                     int(r * 0.55))
          #  surf.blit(os_, (cx - r - 2, cy - r - 2))

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

    def update(self, emotion, listening, speaking):
        now = time.time()

        if speaking:
            self.squint_target = 0.0
            self.widen_target  = 0.0
            self.droop_target  = 0.0
            self.pupil_scale   = 1.0
            return

        if listening:
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
        if emotion in ("happy", "love"):
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
class RobotFace:

    _WAKE_NONE   = 0
    _WAKE_ACTIVE = 1

    def __init__(self):
        pygame.init()
        flags = pygame.FULLSCREEN if FULLSCREEN else 0
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), flags)
        pygame.display.set_caption("Luna")
        if HIDE_CURSOR:
            pygame.mouse.set_visible(False)
        self.clock  = pygame.time.Clock()

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
        self.base = pygame.Surface((WIDTH, HEIGHT))

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
            self.prev_state = self.state
            self.state      = new_state

    def _spawn_stars(self, fcx, fcy):
        for _ in range(12):
            ox = random.randint(-200, 200)
            oy = random.randint(-150, 150)
            self.star_particles.append(StarParticle(fcx + ox, fcy + oy))

    def update(self):
        self.breath_phase += 0.045
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
            look_dir       = state.look_dir
            frozen_emotion = state.frozen_emotion
            g_anim         = state.gesture_anim
            g_start        = state.gesture_anim_start
            convo_active   = state.conversation_active
            convo_expired  = state.convo_expired_time

        # ── conversation window indicator ─────────────────────────────────
        # soft glow while awake; when the window times out play a subtle
        # "rest" cue — one slow dim blink and the glow fades out
        self.awake_glow = lerp(self.awake_glow, 1.0 if convo_active else 0.0,
                               0.06)
        if convo_expired > self._last_expire:
            self._last_expire = convo_expired
            self.rest_pulse   = 1.0
            self._blink_dir   = -1        # start a blink…
            self.blink_counter = 0
        self.rest_pulse *= 0.965          # ~1.5 s decay at 60 fps

        # emotion — frozen while speaking
        if speaking and frozen_emotion:
            emotion = frozen_emotion.lower() if frozen_emotion != "Neutral" else "neutral"
        else:
            emotion = self.visual_state

        # ── sleep / wake ──────────────────────────────────────────────────
        if not face_detected and not speaking:
            self.idle_frames += 1
        else:
            if self.idle_frames > 0 and emotion == "sleeping":
                self.set_state("neutral")
            self.idle_frames = 0

        # ── eye size targets ──────────────────────────────────────────────
        if speaking:
            tw, th = 185, 118
        elif emotion == "happy":
            tw, th = 205, 150
        elif emotion == "surprised":
            tw, th = 240, 190
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

        # ── blink — two-phase animated blink (smooth close AND open) ─────
        # blink_open: 1 = fully open. Phase "closing" eases shut fast,
        # phase "opening" eases back with a soft cubic — much cuter than
        # the old instant snap-shut.
        if emotion != "sleeping":
            self.blink_counter += 1
            trigger = self.blink_timer if not speaking else 180

            if self.blink_open >= 1.0 and self.blink_counter > trigger:
                self.blink_counter = 0
                self._blink_dir    = -1          # start closing

            d = getattr(self, "_blink_dir", 0)
            if d == -1:
                self.blink_open -= 0.34          # fast close (~3 frames)
                if self.blink_open <= 0.0:
                    self.blink_open = 0.0
                    self._blink_dir = 1
            elif d == 1:
                # reopen slower right after a conversation timeout — reads
                # as a sleepy "back to rest" blink
                self.blink_open += 0.16 * (0.45 if self.rest_pulse > 0.35
                                           else 1.0)
                if self.blink_open >= 1.0:
                    self.blink_open  = 1.0
                    self._blink_dir  = 0
                    self.blink_timer = random.randint(100, 220)
                    # occasionally double-blink — very lifelike
                    if random.random() < 0.18 and not speaking:
                        self.blink_counter = self.blink_timer - 8

            # ease the reopen with a smoothstep curve
            t = clamp(self.blink_open, 0.0, 1.0)
            blink_t = t * t * (3 - 2 * t)
        else:
            blink_t = 0.0

        # ── listening pulse ───────────────────────────────────────────────
        self.listen_phase += 0.08
        if listening:
            self.listen_pulse = lerp(self.listen_pulse,
                                     0.5 + 0.5 * math.sin(self.listen_phase),
                                     0.15)
        else:
            self.listen_pulse = lerp(self.listen_pulse, 0.0, 0.1)

        # ── angry red pulse ───────────────────────────────────────────────
        self.angry_pulse_phase += 0.06
        if emotion == "angry":
            self.angry_pulse = lerp(self.angry_pulse,
                                    0.3 + 0.3 * math.sin(
                                        self.angry_pulse_phase), 0.10)
        else:
            self.angry_pulse = lerp(self.angry_pulse, 0.0, 0.08)

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
        self.micro.update(emotion, listening, speaking)

        # ── face offset / tracking ────────────────────────────────────────
        breath_y = math.sin(self.breath_phase) * 5

        if emotion == "sleeping":
            self.target_ox = 0.0
            self.target_oy = 0.0
            self.pupil_ox  = lerp(self.pupil_ox, 0.0, 0.05)
            self.pupil_oy  = lerp(self.pupil_oy, 0.0, 0.05)
            self.target_tilt = 0.0

        elif emotion == "thinking":
            # pondering: pupils glance up and slowly wander side to side,
            # head tips a touch — the classic "hmm" look
            self.think_phase = getattr(self, "think_phase", 0.0) + 0.035
            tx = 26 * math.sin(self.think_phase)
            self.target_ox   = tx * 0.6
            self.target_oy   = -12.0
            self.pupil_ox    = lerp(self.pupil_ox, tx, 0.08)
            self.pupil_oy    = lerp(self.pupil_oy, -22.0, 0.08)
            self.target_tilt = -4.0

        elif look_dir is not None:
            FACE_SHIFT  = 60
            PUPIL_SHIFT = 28
            if look_dir == "left":
                self.target_ox = -FACE_SHIFT
                self.pupil_ox  = lerp(self.pupil_ox, -PUPIL_SHIFT, 0.15)
            elif look_dir == "right":
                self.target_ox =  FACE_SHIFT
                self.pupil_ox  = lerp(self.pupil_ox,  PUPIL_SHIFT, 0.15)
            elif look_dir == "up":
                self.target_oy = -FACE_SHIFT
                self.pupil_oy  = lerp(self.pupil_oy, -PUPIL_SHIFT, 0.15)
            elif look_dir == "down":
                self.target_oy =  FACE_SHIFT
                self.pupil_oy  = lerp(self.pupil_oy,  PUPIL_SHIFT, 0.15)
            self.target_tilt = 0.0

        elif face_detected:
            target_ox = (fx - 0.5) * 120
            target_oy = (fy - 0.5) *  60
            self.target_ox = target_ox
            self.target_oy = target_oy
            self.pupil_ox  = lerp(self.pupil_ox, target_ox * 0.25, 0.15)
            self.pupil_oy  = lerp(self.pupil_oy, target_oy * 0.25, 0.15)
            self.target_tilt = (8.0 if fx < 0.38
                                else (-8.0 if fx > 0.62 else 0.0))
        else:
            self.curiosity_timer += 1
            if self.curiosity_timer > 140:
                self.curiosity_timer    = 0
                self.curiosity_target_x = random.uniform(-70, 70)
                self.curiosity_target_y = random.uniform(-35, 35)
            self.target_ox = self.curiosity_target_x
            self.target_oy = self.curiosity_target_y
            self.pupil_ox  = lerp(self.pupil_ox,
                                  self.curiosity_target_x * 0.20, 0.02)
            self.pupil_oy  = lerp(self.pupil_oy,
                                  self.curiosity_target_y * 0.20, 0.02)
            self.target_tilt = 0.0

        # cute decaying bounce on positive state changes
        bounce_y = 0.0
        if self.bounce_amp > 0.5:
            self.bounce_phase += 0.28
            bounce_y = -abs(math.sin(self.bounce_phase)) * self.bounce_amp
            self.bounce_amp *= 0.94   # decay

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
            tgt_L = (-96.0, 178.0,  30.0)
            tgt_R = ( 96.0, 178.0, -30.0)
            self._heart_pulse = 0.5 + 0.5 * math.sin(g_el * 2 * math.pi * 1.6)

        self._hand_target = {"L": tgt_L, "R": tgt_R}
        for side in ("L", "R"):
            cur, tgt = self.hand[side], self._hand_target[side]
            k = 0.22
            cur[0] = lerp(cur[0], tgt[0], k)
            cur[1] = lerp(cur[1], tgt[1], k)
            cur[2] = lerp(cur[2], tgt[2], 0.35)

        self.face_ox = lerp(self.face_ox, self.target_ox, 0.30 if head_fast else 0.12)
        self.face_oy = lerp(self.face_oy,
                            self.target_oy + breath_y + bounce_y,
                            0.30 if head_fast else 0.16)
        self.head_angle = lerp(self.head_angle, self.target_tilt,
                               0.35 if head_fast or self._gesture == "wave" else 0.07)

        # ── update eye/mouth ──────────────────────────────────────────────
        angry     = emotion == "angry"
        happy     = emotion in ("happy", "excited", "love")
        sad       = emotion == "sad"
        is_listen = listening and not speaking

        # per-style geometry (so 1/2/3 can be switched live)
        self.left_eye.rel_x  = -EYE_SPREAD
        self.right_eye.rel_x =  EYE_SPREAD
        tw, th = tw * EYE_SCALE, th * EYE_SCALE

        for eye in (self.left_eye, self.right_eye):
            eye.update(
                tw, th, blink_t,
                self.pupil_ox, self.pupil_oy,
                pupil_scale = self.micro.pupil_scale,
                squint      = self.micro.squint_target,
                widen       = self.micro.widen_target,
                droop       = self.micro.droop_target,
            )

        self.mouth.update(audio_energy, emotion, speaking)

        # ── particle spawning ─────────────────────────────────────────────
        fcx = int(self.face_cx + self.face_ox)
        fcy = int(self.face_cy + self.face_oy)

        # zzz
        if emotion == "sleeping":
            self.zzz_spawn_t += 1
            if self.zzz_spawn_t > 40:
                self.zzz_spawn_t = 0
                self.zzz_particles.append(
                    ZzzParticle(fcx + random.randint(-80, 80), fcy - 120))
        else:
            self.zzz_particles.clear()

        # tears
        if emotion == "sad":
            self.tear_spawn_t += 1
            if self.tear_spawn_t > 90:
                self.tear_spawn_t = 0
                # drip from left eye
                lx = fcx + self.left_eye.rel_x
                ly = fcy + self.left_eye.rel_y + 60
                self.tear_particles.append(TearParticle(lx, ly))
        else:
            self.tear_particles.clear()

        # steam (angry)
        if emotion == "angry":
            self.steam_spawn_t += 1
            if self.steam_spawn_t > 12:
                self.steam_spawn_t = 0
                for eye_x in [fcx - 190, fcx + 190]:
                    self.steam_particles.append(
                        SteamParticle(eye_x + random.randint(-20, 20),
                                      fcy - 80))
        else:
            self.steam_particles.clear()

        # starburst (surprised / excited — spawn once on transition)
        if emotion in ("surprised", "excited") and not self.star_spawned:
            self._spawn_stars(fcx, fcy)
            self.star_spawned = True
        elif emotion not in ("surprised", "excited"):
            self.star_spawned = False
            self.star_particles.clear()

        # excited keeps sprinkling a few extra stars while it lasts
        if emotion == "excited":
            self.excite_spawn_t += 1
            if self.excite_spawn_t > 25:
                self.excite_spawn_t = 0
                self.star_particles.append(
                    StarParticle(fcx + random.randint(-260, 260),
                                 fcy + random.randint(-180, 120)))

        # floating hearts (love)
        if emotion == "love":
            self.heart_spawn_t += 1
            if self.heart_spawn_t > 18:
                self.heart_spawn_t = 0
                self.heart_particles.append(
                    HeartParticle(fcx + random.randint(-240, 240),
                                  fcy + random.randint(-60, 100)))
        else:
            self.heart_particles.clear()

        # sound waves ripple from the mouth while speaking — nice talking effect
        if speaking and audio_energy > 0.45:
            self.wave_spawn_t += 1
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
            self.wake_ripple += 0.04
            if self.wake_ripple >= 1.0:
                self.wake_anim   = self._WAKE_NONE
                self.wake_ripple = 0.0

        # stash for draw
        self._angry       = angry
        self._happy       = happy
        self._sad         = sad
        self._listen      = is_listen
        self._speaking    = audio_playing   # mouth animates only with real sound
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

    def draw(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                # main.py's finally block handles the full clean shutdown
                raise SystemExit
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    raise SystemExit
                if event.key in (pygame.K_1, pygame.K_KP1):
                    apply_style(1)
                elif event.key in (pygame.K_2, pygame.K_KP2):
                    apply_style(2)
                elif event.key in (pygame.K_3, pygame.K_KP3):
                    apply_style(3)

        self.clock.tick(RENDER_FPS)
        self.update()

        base = self.base   # reused surface — no per-frame allocation
        base.fill(BG)

        fcx = int(self.face_cx + self.face_ox)
        fcy = int(self.face_cy + self.face_oy)

        # ── hair (behind everything) ──────────────────────────────────────
        if HAIR:
            draw_hair(base, fcx, fcy, self.head_angle)

        # ── blush (behind eyes) ───────────────────────────────────────────
        self.left_blush.draw(base, fcx, fcy)
        self.right_blush.draw(base, fcx, fcy)

        # ── sound waves (behind mouth) ────────────────────────────────────
        for w in self.sound_waves:
            w.draw(base)

        # ── steam (behind eyes) ───────────────────────────────────────────
        for p in self.steam_particles:
            p.draw(base)

        # ── eyes ──────────────────────────────────────────────────────────
        lx = fcx + self.left_eye.rel_x
        ly = fcy + self.left_eye.rel_y
        rx = fcx + self.right_eye.rel_x
        ry = fcy + self.right_eye.rel_y

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

        # ── mouth ─────────────────────────────────────────────────────────
        mx = fcx + self.mouth.rel_x
        my = fcy + self.mouth.rel_y
        self.mouth.draw(base, mx, my, self._emotion,
                        self._speaking, self._audio_energy)

        # ── hands (in front of the face) ──────────────────────────────────
        if HANDS:
            for side in ("L", "R"):
                hx, hy, ha = self.hand[side]
                if fcy + hy > HEIGHT + 60:      # fully tucked away
                    continue
                img = hand_surface(self.hand_pose[side], side)
                if abs(ha) > 0.5:
                    img = pygame.transform.rotate(img, ha)
                rect = img.get_rect(center=(fcx + int(hx), fcy + int(hy)))
                glow = img.copy()
                glow.fill((*GLOW_COL, 0), special_flags=pygame.BLEND_RGBA_MAX)
                bloom(base, glow, rect.topleft, radius=12, passes=1, max_alpha=70)
                base.blit(img, rect)
            if self._gesture == "heart":
                sz = int(50 + 12 * self._heart_pulse)
                draw_heart(base, fcx, fcy + 112, sz)

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
        if self.awake_glow > 0.04:
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

        # ── head tilt ─────────────────────────────────────────────────────
        if abs(self.head_angle) > 0.1:
            rotated = pygame.transform.rotate(base, self.head_angle)
            rect    = rotated.get_rect(center=(WIDTH // 2, HEIGHT // 2))
            self.screen.fill(BG)
            self.screen.blit(rotated, rect)
        else:
            self.screen.blit(base, (0, 0))
        
        pygame.display.flip()