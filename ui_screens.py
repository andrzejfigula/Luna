"""
ui_screens.py — the pages that want to look nice: the gallery (gallery.py),
a single photo, and the weather ("pokaż pogodę").

Everything round is drawn 3× bigger and scaled down (smoothscale), which
gives soft, antialiased edges that pygame.draw alone doesn't; the text is
Nunito Sans (assets/fonts). Whatever can be is made once and cached — the
Pi draws a still page at 8 fps (face_renderer), a moving one at full speed.
"""

import math
import os
import time

import pygame

import gallery

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
_fonts = {}
_texts = {}
_cache = {}

WHITE = (255, 255, 255)
SOFT = (226, 230, 242)
DIM = (178, 186, 206)
SUN = (255, 196, 64)
SUN_EDGE = (255, 150, 40)
DROP = (96, 170, 255)
SS = 3                       # supersampling for the round things


# ── text ─────────────────────────────────────────────────────────────────────

def font(size, weight="Bold"):
    """Nunito Sans: Regular / SemiBold / Bold / ExtraBold (DejaVu if missing)."""
    f = _fonts.get((size, weight))
    if f is None:
        try:
            f = pygame.font.Font(os.path.join(_FONT_DIR, f"NunitoSans-{weight}.ttf"), size)
        except (OSError, FileNotFoundError, pygame.error):
            path = pygame.font.match_font("dejavusans", bold=weight != "Regular")
            f = pygame.font.Font(path, size) if path else pygame.font.SysFont(None, size + 6)
        _fonts[(size, weight)] = f
    return f


def text(s, size, col=WHITE, weight="Bold"):
    key = (s, size, col, weight)
    img = _texts.get(key)
    if img is None:
        if len(_texts) > 400:
            _texts.clear()
        img = _texts[key] = font(size, weight).render(s, True, col)
    return img


def shadowed(s, size, col=WHITE, weight="Bold", alpha=150):
    """Text with a soft dark shadow — readable over a photo or a bright sky."""
    key = ("sh", s, size, col, weight, alpha)
    img = _texts.get(key)
    if img is None:
        fg = text(s, size, col, weight)
        sh = font(size, weight).render(s, True, (0, 0, 0))
        w, h = fg.get_size()
        img = pygame.Surface((w + 8, h + 8), pygame.SRCALPHA)
        blur = pygame.transform.smoothscale(sh, (max(1, w // 3), max(1, h // 3)))
        blur = pygame.transform.smoothscale(blur, (w, h))
        blur.set_alpha(alpha)
        img.blit(blur, (4, 6))
        img.blit(fg, (4, 3))
        _texts[key] = img
    return img


def fit(s, size, width, weight="Bold"):
    """The text cut with "…" to `width` pixels."""
    f = font(size, weight)
    if f.size(s)[0] <= width:
        return s
    while s and f.size(s + "…")[0] > width:
        s = s[:-1]
    return s.rstrip() + "…"


def shrink(s, size, width, weight="Bold", least=18):
    """The largest size up to `size` at which the text fits `width`."""
    while size > least and font(size, weight).size(s)[0] > width:
        size -= 2
    return size


# ── shapes (supersampled) ────────────────────────────────────────────────────

def _down(big, w, h):
    return pygame.transform.smoothscale(big, (w, h))


def rrect(w, h, r, col):
    """A rounded rectangle, antialiased; col may have alpha."""
    key = ("rr", w, h, r, col)
    s = _cache.get(key)
    if s is None:
        big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        pygame.draw.rect(big, col, big.get_rect(), border_radius=r * SS)
        s = _cache[key] = _down(big, w, h)
    return s


def circle_button(kind, r=26, alpha=110):
    """A dark round button with a white ✕, ‹ or ›."""
    key = ("btn", kind, r, alpha)
    s = _cache.get(key)
    if s is None:
        d = 2 * r * SS
        big = pygame.Surface((d, d), pygame.SRCALPHA)
        c = d // 2
        pygame.draw.circle(big, (12, 14, 24, alpha), (c, c), c)
        pygame.draw.circle(big, (255, 255, 255, 60), (c, c), c, SS * 2)
        lw, k = int(SS * r * 0.13), r * SS * 0.32
        if kind == "close":
            for a, b in (((-k, -k), (k, k)), ((-k, k), (k, -k))):
                _line(big, WHITE, (c + a[0], c + a[1]), (c + b[0], c + b[1]), lw)
        else:
            sx = 1 if kind == "next" else -1
            tip = (c + sx * k * 0.75, c)
            _line(big, WHITE, (c - sx * k * 0.45, c - k * 1.1), tip, lw)
            _line(big, WHITE, (c - sx * k * 0.45, c + k * 1.1), tip, lw)
        s = _cache[key] = _down(big, 2 * r, 2 * r)
    return s


def _line(surf, col, a, b, w):
    """A thick line with round ends."""
    pygame.draw.line(surf, col, a, b, int(w))
    for p in (a, b):
        pygame.draw.circle(surf, col, (int(p[0]), int(p[1])), int(w) // 2)


def vgrad(w, h, top, bottom):
    """A vertical gradient; top / bottom may be RGBA."""
    key = ("vg", w, h, top, bottom)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((1, h), pygame.SRCALPHA)
        for y in range(h):
            k = y / max(1, h - 1)
            s.set_at((0, y), tuple(int(a + (b - a) * k) for a, b in
                                   zip(top + (255,) * (4 - len(top)),
                                       bottom + (255,) * (4 - len(bottom)))))
        s = _cache[key] = pygame.transform.scale(s, (w, h))
    return s


def shadow(w, h, r, spread=16, alpha=150):
    """A soft shadow under a w × h card."""
    key = ("sh", w, h, r, spread, alpha)
    s = _cache.get(key)
    if s is None:
        W, H = w + 2 * spread, h + 2 * spread
        small = pygame.Surface((max(2, W // 8), max(2, H // 8)), pygame.SRCALPHA)
        pygame.draw.rect(small, (0, 0, 0, alpha),
                         pygame.Rect(spread // 8, spread // 8, w // 8, h // 8),
                         border_radius=max(1, r // 8))
        s = _cache[key] = pygame.transform.smoothscale(small, (W, H))
    return s


# ── pictures: the card and the blurred backdrop ─────────────────────────────

_pics = {}                   # path → (backdrop, card) for the last few


def _picture(path, W, H, maxw, maxh):
    key = (path, W, H, maxw, maxh)
    got = _pics.get(key)
    if got is not None:
        return got
    try:
        pic = pygame.image.load(path)
        # (a palette PNG — Wikipedia's flags — can't be smoothscaled)
        pic = pic.convert_alpha() if pic.get_alpha() else pic.convert()
    except Exception:
        return None
    pw, ph = pic.get_size()
    k = min(maxw / pw, maxh / ph)
    cw, chh = max(1, int(pw * k)), max(1, int(ph * k))
    img = pygame.transform.smoothscale(pic, (cw, chh)).convert_alpha()
    mask = rrect(cw, chh, 18, (255, 255, 255, 255))
    card = pygame.Surface((cw, chh), pygame.SRCALPHA)
    card.fill((240, 240, 240, 255))           # (a transparent flag on light grey)
    card.blit(img, (0, 0))
    card.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    edge = pygame.Surface((cw * SS, chh * SS), pygame.SRCALPHA)
    pygame.draw.rect(edge, (255, 255, 255, 70), edge.get_rect(), SS * 2, border_radius=18 * SS)
    card.blit(_down(edge, cw, chh), (0, 0))
    # the backdrop: the same picture, covering the screen, blurred and dimmed
    kc = max(W / pw, H / ph)
    cover = pygame.transform.smoothscale(pic.convert(), (int(pw * kc) + 1, int(ph * kc) + 1))
    cover = cover.subsurface(pygame.Rect((cover.get_width() - W) // 2,
                                         (cover.get_height() - H) // 2, W, H)).copy()
    tiny = pygame.transform.smoothscale(cover, (max(1, W // 28), max(1, H // 28)))
    back = pygame.transform.smoothscale(tiny, (W, H))
    dark = pygame.Surface((W, H))
    dark.set_alpha(120)
    back.blit(dark, (0, 0))
    if len(_pics) >= 6:
        _pics.pop(next(iter(_pics)))
    _pics[key] = (back, card)
    return _pics[key]


def _ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _chrome(scr, W, H):
    """Darker at the top and the bottom, for the buttons and the caption."""
    scr.blit(vgrad(W, 90, (0, 0, 0, 120), (0, 0, 0, 0)), (0, 0))
    scr.blit(vgrad(W, 120, (0, 0, 0, 0), (0, 0, 0, 170)), (0, H - 120))


def _caption(scr, W, H, caption, sub):
    y = H - 48
    if caption:
        img = shadowed(fit(caption, 30, W - 160), 30, WHITE, "ExtraBold")
        scr.blit(img, img.get_rect(center=(W // 2, y - (14 if sub else 0))))
    if sub:
        img = shadowed(fit(sub, 21, W - 160), 21, SOFT, "SemiBold", alpha=120)
        scr.blit(img, img.get_rect(center=(W // 2, y + (18 if caption else 0))))


def draw_photo(scr, path, sub, W, H):
    """One picture (a Wikipedia photo, a flag in the quiz): no arrows."""
    got = _picture(path, W, H, W - 120, H - 110)
    if got is None:
        return
    back, card = got
    scr.blit(back, (0, 0))
    _chrome(scr, W, H)
    r = card.get_rect(center=(W // 2, (H - 70) // 2 + 14))
    scr.blit(shadow(*r.size, 18), (r.x - 16, r.y - 10))
    scr.blit(card, r)
    _caption(scr, W, H, sub or "", "")


def draw_gallery(scr, g, now, W, H):
    """The gallery page: backdrop, the picture (sliding when turned), ‹ › ✕,
    the caption, dots, and the slideshow's progress."""
    items, i = g["items"], g["i"]
    maxw, maxh = W - 190, H - 116
    got = _picture(items[i]["path"], W, H, maxw, maxh)
    if got is None:
        scr.fill((0, 0, 0))
        return
    back, card = got
    cy = (H - 70) // 2 + 12
    t = (now - g.get("t_nav", 0.0)) / gallery.SLIDE
    old = g.get("from")
    prev = (_picture(items[old]["path"], W, H, maxw, maxh)
            if 0 <= t < 1 and old is not None and 0 <= old < len(items) and old != i else None)
    if prev:
        e, d = _ease(t), g.get("dir", 1) or 1
        scr.blit(prev[0], (0, 0))
        back.set_alpha(int(255 * e))
        scr.blit(back, (0, 0))
        back.set_alpha(None)
        _chrome(scr, W, H)
        shift = int(W * 0.75)
        for (bk, cd), x in ((prev, W // 2 - int(d * shift * e)),
                            ((back, card), W // 2 + int(d * shift * (1 - e)))):
            r = cd.get_rect(center=(x, cy))
            scr.blit(shadow(*r.size, 18), (r.x - 16, r.y - 10))
            scr.blit(cd, r)
    else:
        scr.blit(back, (0, 0))
        _chrome(scr, W, H)
        r = card.get_rect(center=(W // 2, cy))
        scr.blit(shadow(*r.size, 18), (r.x - 16, r.y - 10))
        scr.blit(card, r)
    n = len(items)
    # the title and how many, top left; ✕ top right
    if g.get("title"):
        label = shadowed(f"{g['title']}", 24, WHITE, "ExtraBold")
        scr.blit(label, (18, 10))
        cnt = shadowed(f"{i + 1} z {n}", 19, DIM, "SemiBold", alpha=110)
        scr.blit(cnt, (18 + label.get_width() + 4, 15))
    btn = circle_button("close", 24)
    scr.blit(btn, btn.get_rect(center=(W - 38, 38)))
    if n > 1:
        for kind, x, on in (("prev", 46, i > 0), ("next", W - 46, i < n - 1)):
            b = circle_button(kind, 28, 110 if on else 40)
            if not on:
                b = b.copy()
                b.set_alpha(90)
            scr.blit(b, b.get_rect(center=(x, cy)))
    it = items[i]
    _caption(scr, W, H, it.get("caption") or "", it.get("sub") or "")
    # dots (or nothing: past 15 the count says it)
    if 1 < n <= 15:
        gap, y = 16, H - 12
        x0 = W // 2 - (n - 1) * gap // 2
        for k in range(n):
            if k == i:
                scr.blit(rrect(18, 8, 4, (255, 255, 255, 235)), (x0 + k * gap - 9, y - 4))
            else:
                scr.blit(rrect(7, 7, 3, (255, 255, 255, 90)), (x0 + k * gap - 3, y - 3))
    if g.get("auto"):                          # the slideshow runs: a thin line
        k = 1 - max(0.0, min(1.0, (g["next"] - now) / gallery.STEP))
        pygame.draw.rect(scr, (255, 255, 255), pygame.Rect(0, H - 3, int(W * k), 3))


def moving(kind, data, now):
    """Does this page move right now (full fps), or may it be drawn slowly?"""
    if kind == "gallery":
        return now - data.get("t_nav", 0.0) < gallery.SLIDE + 0.1
    if kind == "weather":
        return now - data.get("t0", 0.0) < 1.2
    return False


# ── the weather ──────────────────────────────────────────────────────────────

_SKY = {      # (top, bottom) of the backdrop for the weather now
    ("clear", True): ((34, 104, 196), (104, 172, 232)),
    ("partly", True): ((46, 98, 170), (118, 160, 206)),
    ("cloud", True): ((62, 76, 102), (120, 134, 160)),
    ("fog", True): ((92, 100, 116), (150, 156, 168)),
    ("drizzle", True): ((48, 64, 94), (98, 118, 150)),
    ("rain", True): ((36, 50, 80), (82, 100, 136)),
    ("snow", True): ((86, 108, 148), (168, 186, 216)),
    ("storm", True): ((28, 26, 52), (72, 66, 106)),
}


def _sky(kind, day):
    if not day:
        return ((10, 14, 38), (38, 40, 86)) if kind in ("clear", "partly") else ((16, 20, 36), (48, 54, 80))
    return _SKY.get((kind, True), _SKY[("cloud", True)])


def _cloud(big, S, ox, oy, k, col, under=None):
    """A puffy cloud: circles on a flat bottom (in a S×S supersampled box)."""
    parts = ((0.30, 0.62, 0.17), (0.48, 0.50, 0.23), (0.68, 0.60, 0.17))
    if under:                                         # a darker edge below
        for cx, cy, r in parts:
            pygame.draw.circle(big, under, (int(ox + cx * S * k), int(oy + (cy + 0.03) * S * k)),
                               int(r * S * k))
        pygame.draw.rect(big, under, pygame.Rect(int(ox + 0.30 * S * k), int(oy + 0.55 * S * k),
                                                 int(0.38 * S * k), int(0.25 * S * k)),
                         border_radius=int(0.12 * S * k))
    for cx, cy, r in parts:
        pygame.draw.circle(big, col, (int(ox + cx * S * k), int(oy + cy * S * k)), int(r * S * k))
    pygame.draw.rect(big, col, pygame.Rect(int(ox + 0.30 * S * k), int(oy + 0.52 * S * k),
                                           int(0.38 * S * k), int(0.27 * S * k)),
                     border_radius=int(0.12 * S * k))


def _sun(big, S, cx, cy, r):
    for i in range(8):                                 # rays
        a = math.radians(i * 45 + 22.5)
        _line(big, SUN, (cx + r * 1.35 * math.cos(a), cy + r * 1.35 * math.sin(a)),
              (cx + r * 1.75 * math.cos(a), cy + r * 1.75 * math.sin(a)), r * 0.22)
    pygame.draw.circle(big, SUN_EDGE, (int(cx), int(cy)), int(r))
    pygame.draw.circle(big, SUN, (int(cx - r * 0.06), int(cy - r * 0.06)), int(r * 0.9))
    pygame.draw.circle(big, (255, 226, 130), (int(cx - r * 0.3), int(cy - r * 0.3)), int(r * 0.35))


def _moon(big, S, cx, cy, r):
    pygame.draw.circle(big, (250, 236, 180), (int(cx), int(cy)), int(r))
    pygame.draw.circle(big, (0, 0, 0, 0), (int(cx + r * 0.5), int(cy - r * 0.35)), int(r * 0.85))
    for sx, sy, sr in ((0.78, 0.18, 0.035), (0.88, 0.42, 0.025)):
        pygame.draw.circle(big, (255, 250, 220), (int(sx * S), int(sy * S)), int(sr * S))


def weather_icon(kind, size, day=True):
    """The weather as a picture, size × size, soft-edged."""
    key = ("wx", kind, size, day)
    s = _cache.get(key)
    if s is not None:
        return s
    S = size * SS
    big = pygame.Surface((S, S), pygame.SRCALPHA)
    light, grey, dark = (250, 252, 255), (206, 214, 228), (118, 126, 148)
    if kind in ("clear", "partly"):
        if day:
            if kind == "clear":
                _sun(big, S, S * 0.5, S * 0.5, S * 0.24)
            else:
                _sun(big, S, S * 0.38, S * 0.36, S * 0.19)
        else:
            if kind == "clear":
                _moon(big, S, S * 0.48, S * 0.5, S * 0.3)
            else:
                _moon(big, S, S * 0.4, S * 0.36, S * 0.22)
        if kind == "partly":
            _cloud(big, S, S * 0.12, S * 0.18, 0.88, light, under=grey)
    else:
        top = (78, 82, 106) if kind == "storm" else light
        _cloud(big, S, S * 0.0, -S * 0.08, 1.0, top,
               under=(54, 56, 76) if kind == "storm" else grey)
        if kind in ("rain", "drizzle", "storm"):
            n = 3 if kind != "drizzle" else 4
            for j in range(n):
                x = S * (0.32 + j * (0.36 / (n - 1)))
                y = S * (0.80 if j % 2 == 0 else 0.86)
                r = S * (0.045 if kind != "drizzle" else 0.03)
                pygame.draw.circle(big, DROP, (int(x), int(y)), int(r))
                pygame.draw.polygon(big, DROP, ((x - r * 0.95, y - r * 0.3), (x + r * 0.95, y - r * 0.3),
                                                (x + r * 0.35, y - r * 2.6)))
        if kind == "storm":
            bolt = [(0.52, 0.56), (0.40, 0.78), (0.50, 0.78), (0.44, 0.96), (0.64, 0.70),
                    (0.54, 0.70), (0.60, 0.56)]
            pygame.draw.polygon(big, SUN, [(x * S, y * S) for x, y in bolt])
        elif kind == "snow":
            for j, (x, y) in enumerate(((0.32, 0.84), (0.5, 0.9), (0.68, 0.84))):
                cx, cy, r = x * S, y * S, S * 0.055
                for a in range(3):
                    aa = math.radians(a * 60)
                    _line(big, WHITE, (cx - r * math.cos(aa), cy - r * math.sin(aa)),
                          (cx + r * math.cos(aa), cy + r * math.sin(aa)), S * 0.018)
        elif kind == "fog":
            for j, y in enumerate((0.80, 0.90)):
                _line(big, (220, 226, 236), (S * (0.2 + 0.06 * j), S * y),
                      (S * (0.8 - 0.06 * j), S * y), S * 0.045)
    s = _cache[key] = _down(big, size, size)
    return s


def _temp_col(t):
    """Cold blue → teal → yellow → orange."""
    stops = ((-10, (120, 150, 255)), (0, (96, 190, 255)), (10, (90, 220, 190)),
             (20, (255, 210, 90)), (30, (255, 132, 60)))
    if t <= stops[0][0]:
        return stops[0][1]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if t <= b:
            k = (t - a) / (b - a)
            return tuple(int(x + (y - x) * k) for x, y in zip(ca, cb))
    return stops[-1][1]


def _range_bar(w, h, lo, hi, tmin, tmax):
    """The week's temperatures as a track; this day's lo–hi filled, coloured."""
    key = ("bar", w, h, lo, hi, tmin, tmax)
    s = _cache.get(key)
    if s is None:
        S = SS
        big = pygame.Surface((w * S, h * S), pygame.SRCALPHA)
        pygame.draw.rect(big, (255, 255, 255, 50), big.get_rect(), border_radius=h * S // 2)
        span = max(1, tmax - tmin)
        x0 = int((lo - tmin) / span * (w - h) * S)
        x1 = int((hi - tmin) / span * (w - h) * S) + h * S
        grad = pygame.Surface((max(1, x1 - x0), h * S), pygame.SRCALPHA)
        for x in range(grad.get_width()):
            t = lo + (hi - lo) * x / max(1, grad.get_width() - 1)
            pygame.draw.line(grad, _temp_col(t), (x, 0), (x, h * S))
        m = pygame.Surface(grad.get_size(), pygame.SRCALPHA)
        pygame.draw.rect(m, (255, 255, 255, 255), m.get_rect(), border_radius=h * S // 2)
        grad.blit(m, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        big.blit(grad, (x0, 0))
        s = _cache[key] = _down(big, w, h)
    return s


def draw_weather(scr, data, now, W, H):
    """Now, big on the left; the week on the right, a row a day."""
    cur, days = data["now"], data["days"]
    top, bottom = _sky(cur["kind"], cur["day"])
    scr.blit(vgrad(W, H, top, bottom), (0, 0))
    intro = _ease((now - data.get("t0", now)) / 0.8)
    # ── left: now ──
    lx = 30
    place = data.get("place") or "Teraz"
    scr.blit(shadowed(fit(place, 24, 270), 24, SOFT, "Bold", 90), (lx - 4, 18))
    icon = weather_icon(cur["kind"], 150, cur["day"])
    scr.blit(icon, (lx - 6, 52 + int(18 * (1 - intro))))
    temp = shadowed(f"{cur['temp']}°", 104, WHITE, "ExtraBold", 110)
    scr.blit(temp, (lx + 140, 52))
    desc = (cur.get("desc") or "").capitalize()
    ds = shrink(desc, 28, 290, "ExtraBold", 20)
    scr.blit(shadowed(fit(desc, ds, 290, "ExtraBold"), ds, WHITE, "ExtraBold", 110), (lx - 4, 212))
    if days:                                  # today: ▲ the highest, ▼ the lowest
        x = lx
        for up, t in ((True, days[0]["tmax"]), (False, days[0]["tmin"])):
            scr.blit(_tri(up), (x, 266))
            img = shadowed(f"{t}°", 26, SOFT, "Bold", 90)
            scr.blit(img, (x + 14, 252))
            x += 14 + img.get_width() + 14
    line = f"Odczuwalna {cur['feels']}°  ·  wiatr {cur['wind']} km/h"
    ls = shrink(line, 20, 290, "SemiBold", 15)
    scr.blit(shadowed(line, ls, SOFT, "SemiBold", 80), (lx - 4, 296))
    # the next hours, every three
    hours = data.get("hours") or []
    if hours:
        scr.blit(rrect(296, 120, 18, (255, 255, 255, 30)), (lx - 12, H - 138))
        cw = 296 // len(hours)
        for j, h in enumerate(hours):
            cx = lx - 12 + cw * j + cw // 2
            t = text(f"{h['h']}:00", 16, DIM, "Bold")
            scr.blit(t, t.get_rect(midtop=(cx, H - 128)))
            ic = weather_icon(h["kind"], 40, h["day"])
            scr.blit(ic, ic.get_rect(center=(cx, H - 80)))
            t = text(f"{h['temp']}°", 21, WHITE, "ExtraBold")
            scr.blit(t, t.get_rect(midtop=(cx, H - 54)))
    # ── right: the days ──
    rows = days[1:7] if len(days) > 1 else days
    px, pw = 330, W - 330 - 18
    ph = H - 36
    panel = rrect(pw, ph, 22, (255, 255, 255, 34))
    scr.blit(panel, (px, 18))
    if not rows:
        return
    lo = min(d["tmin"] for d in rows)
    hi = max(d["tmax"] for d in rows)
    rh = ph // len(rows)
    bw = pw - 276 - 66                       # the bar between the two temperatures
    sep = rrect(pw - 32, 1, 0, (255, 255, 255, 46))
    for j, d in enumerate(rows):
        k = _ease((now - data.get("t0", now) - 0.06 * j) / 0.6)
        y = 18 + j * rh + int(24 * (1 - k))
        if j:
            scr.blit(sep, (px + 16, 18 + j * rh))
        mid = y + rh // 2
        ns = shrink(d["label"], 23, 142, "ExtraBold", 18)
        name = text(d["label"], ns, WHITE, "ExtraBold")
        scr.blit(name, (px + 18, mid - name.get_height() // 2 - 9))
        date = text(d["date"], 17, DIM, "SemiBold")
        scr.blit(date, (px + 18, mid + 7))
        rainy = d["rain"] >= 20
        ic = weather_icon(d["kind"], 48, True)
        scr.blit(ic, (px + 166, mid - (34 if rainy else 24)))
        if rainy:
            r = text(f"{d['rain']}%", 16, (160, 210, 255), "Bold")
            scr.blit(r, r.get_rect(midtop=(px + 190, mid + 12)))
        tl = text(f"{d['tmin']}°", 24, DIM, "Bold")
        scr.blit(tl, tl.get_rect(midright=(px + 266, mid)))
        bar = _range_bar(bw, 10, d["tmin"], d["tmax"], lo, hi)
        scr.blit(bar, (px + 276, mid - 5))
        th = text(f"{d['tmax']}°", 24, WHITE, "ExtraBold")
        scr.blit(th, th.get_rect(midleft=(px + 276 + bw + 10, mid)))


def _tri(up, size=14):
    key = ("tri", up, size)
    s = _cache.get(key)
    if s is None:
        S = size * SS
        big = pygame.Surface((S, S), pygame.SRCALPHA)
        pts = ((S * 0.5, S * 0.1), (S * 0.95, S * 0.85), (S * 0.05, S * 0.85))
        if not up:
            pts = tuple((x, S - y) for x, y in pts)
        pygame.draw.polygon(big, (255, 190, 120) if up else (140, 200, 255), pts)
        s = _cache[key] = _down(big, size, size)
    return s


def _mix(a, b, k):
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))
