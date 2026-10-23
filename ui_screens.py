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


def draw_close(scr, W):
    """The ✕ in the top right corner of every page (robot_face)."""
    btn = circle_button("close", 24)
    scr.blit(btn, btn.get_rect(center=(W - 38, 38)))


def close_hit(nx, ny):
    """Was this tap (normalised) on the ✕?"""
    return nx > 0.905 and ny < 0.2


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

_pics = {}                   # (path, size…) → (backdrop, card) for the last few
_AVATAR = ((92, 120, 220), (226, 98, 140), (64, 170, 140), (230, 150, 50), (150, 100, 210),
           (60, 150, 200))


def _src(it):
    """(path, round, name) of a gallery item or a plain path."""
    if isinstance(it, dict):
        return it.get("path"), bool(it.get("round")), it.get("caption") or ""
    return it, False, ""


def _load(path):
    try:
        pic = pygame.image.load(path)
        # (a palette PNG — Wikipedia's flags — can't be smoothscaled)
        return pic.convert_alpha() if pic.get_alpha() else pic.convert()
    except Exception:
        return None


def _backdrop(pic, W, H):
    """The picture covering the screen, blurred and dimmed."""
    pw, ph = pic.get_size()
    kc = max(W / pw, H / ph)
    cover = pygame.transform.smoothscale(pic.convert(), (int(pw * kc) + 1, int(ph * kc) + 1))
    cover = cover.subsurface(pygame.Rect((cover.get_width() - W) // 2,
                                         (cover.get_height() - H) // 2, W, H)).copy()
    tiny = pygame.transform.smoothscale(cover, (max(1, W // 28), max(1, H // 28)))
    back = pygame.transform.smoothscale(tiny, (W, H))
    dark = pygame.Surface((W, H))
    dark.set_alpha(120)
    back.blit(dark, (0, 0))
    return back


def _avatar_col(name):
    return _AVATAR[sum(map(ord, name)) % len(_AVATAR)]


def _round_card(pic, name, D):
    """A person: their face in a circle with a light ring; without a picture,
    a coloured circle with the first letter."""
    S = D * SS
    card = pygame.Surface((D, D), pygame.SRCALPHA)
    if pic is not None:
        pw, ph = pic.get_size()
        side = min(pw, ph)
        sq = pic.subsurface(pygame.Rect((pw - side) // 2, max(0, (ph - side) // 3), side, side))
        card.blit(pygame.transform.smoothscale(sq.convert(), (D, D)), (0, 0))
    else:
        col = _avatar_col(name)
        card.blit(vgrad(D, D, _mix(col, WHITE, 0.25), _mix(col, (0, 0, 0), 0.25)), (0, 0))
        letter = text((name[:1] or "?").upper(), int(D * 0.5), WHITE, "ExtraBold")
        card.blit(letter, letter.get_rect(center=(D // 2, D // 2 + D // 40)))
    mask = pygame.Surface((S, S), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (S // 2, S // 2), S // 2)
    card.blit(_down(mask, D, D), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    ring = pygame.Surface((S, S), pygame.SRCALPHA)
    pygame.draw.circle(ring, (255, 255, 255, 210), (S // 2, S // 2), S // 2, 5 * SS)
    card.blit(_down(ring, D, D), (0, 0))
    return card


def _edge(w, h):
    key = ("edge", w, h)
    s = _cache.get(key)
    if s is None:
        big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        pygame.draw.rect(big, (255, 255, 255, 70), big.get_rect(), SS * 2, border_radius=18 * SS)
        s = _cache[key] = _down(big, w, h)
    return s


def _picture(it, W, H, maxw, maxh, load=True):
    """(backdrop, card) for a gallery item (or a plain path); None when it
    can't be read — or isn't made yet and load is False."""
    path, rnd, name = _src(it)
    key = (path, rnd, name if rnd else "", W, H, maxw, maxh)
    got = _pics.get(key)
    if got is not None or not load:
        return got
    pic = _load(path) if path else None
    if rnd:
        card = _round_card(pic, name, min(maxw, maxh, 290))
        if pic is not None:
            back = _backdrop(pic, W, H)
        else:
            col = _avatar_col(name)
            back = vgrad(W, H, _mix(col, (0, 0, 0), 0.55), _mix(col, (0, 0, 0), 0.8)).copy()
    else:
        if pic is None:
            return None
        pw, ph = pic.get_size()
        k = min(maxw / pw, maxh / ph)
        cw, chh = max(1, int(pw * k)), max(1, int(ph * k))
        img = pygame.transform.smoothscale(pic, (cw, chh)).convert_alpha()
        card = pygame.Surface((cw, chh), pygame.SRCALPHA)
        card.fill((240, 240, 240, 255))           # (a transparent flag on light grey)
        card.blit(img, (0, 0))
        card.blit(rrect(cw, chh, 18, (255, 255, 255, 255)), (0, 0),
                  special_flags=pygame.BLEND_RGBA_MULT)
        card.blit(_edge(cw, chh), (0, 0))
        back = _backdrop(pic, W, H)
    if len(_pics) >= 8:
        _pics.pop(next(iter(_pics)))
    _pics[key] = (back, card)
    return _pics[key]


def bin_button(r=24):
    """A dark round button with a white bin."""
    key = ("bin", r)
    s = _cache.get(key)
    if s is None:
        d = 2 * r * SS
        big = pygame.Surface((d, d), pygame.SRCALPHA)
        c = d // 2
        pygame.draw.circle(big, (12, 14, 24, 110), (c, c), c)
        pygame.draw.circle(big, (255, 255, 255, 60), (c, c), c, SS * 2)
        u = r * SS / 24
        lw = int(2.6 * u)
        _line(big, WHITE, (c - 9 * u, c - 7 * u), (c + 9 * u, c - 7 * u), lw)      # the lid
        _line(big, WHITE, (c - 3 * u, c - 10 * u), (c + 3 * u, c - 10 * u), lw)    # its handle
        body = [(c - 7 * u, c - 4 * u), (c + 7 * u, c - 4 * u), (c + 5.5 * u, c + 10 * u),
                (c - 5.5 * u, c + 10 * u)]
        pygame.draw.polygon(big, WHITE, body, lw)
        for x in (-2.5, 2.5):
            _line(big, WHITE, (c + x * u, c - 1 * u), (c + x * u, c + 7 * u), int(2 * u))
        s = _cache[key] = _down(big, 2 * r, 2 * r)
    return s


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
    if not items:
        scr.fill((0, 0, 0))
        return
    i = max(0, min(i, len(items) - 1))
    rnd = _src(items[i])[1]
    maxw, maxh = W - 190, H - 116
    got = _picture(items[i], W, H, maxw, maxh)
    cy = (H - 70) // 2 + 12
    t = (now - g.get("t_nav", 0.0)) / gallery.SLIDE
    old = g.get("from")
    prev = (_picture(items[old], W, H, maxw, maxh)
            if got and 0 <= t < 1 and old is not None and 0 <= old < len(items) and old != i
            else None)
    if got is None:                    # gone from the disk: say so, keep the buttons
        scr.fill((14, 16, 26))
        msg = text("Nie mogę otworzyć tego obrazka", 26, DIM, "Bold")
        scr.blit(msg, msg.get_rect(center=(W // 2, cy)))
    elif prev:
        back, card = got
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
            if not rnd:
                scr.blit(shadow(*r.size, 18), (r.x - 16, r.y - 10))
            scr.blit(cd, r)
    else:
        back, card = got
        scr.blit(back, (0, 0))
        _chrome(scr, W, H)
        r = card.get_rect(center=(W // 2, cy))
        if not rnd:                    # (a round portrait has its ring instead)
            scr.blit(shadow(*r.size, 18), (r.x - 16, r.y - 10))
        scr.blit(card, r)
    n = len(items)
    it = items[i]
    # the title and how many, top left; ✕ and the bin top right
    if g.get("title"):
        label = shadowed(f"{g['title']}", 24, WHITE, "ExtraBold")
        scr.blit(label, (18, 10))
        cnt = shadowed(f"{i + 1} z {n}", 19, DIM, "SemiBold", alpha=110)
        scr.blit(cnt, (18 + label.get_width() + 4, 15))
    btn = circle_button("close", 24)
    scr.blit(btn, btn.get_rect(center=(W - 38, 38)))
    if gallery.deletable(it):
        if now - g.get("confirm", 0.0) < gallery.CONFIRM:     # tapped once: sure?
            pill = rrect(108, 44, 22, (214, 52, 52, 235))
            pr = pill.get_rect(center=(W - 120, 38))
            scr.blit(pill, pr)
            q = text("Usunąć?", 21, WHITE, "ExtraBold")
            scr.blit(q, q.get_rect(center=pr.center))
        else:
            b = bin_button(24)
            scr.blit(b, b.get_rect(center=(W - 100, 38)))
    if n > 1:
        for kind, x, on in (("prev", 46, i > 0), ("next", W - 46, i < n - 1)):
            b = circle_button(kind, 28, 110 if on else 40)
            if not on:
                b = b.copy()
                b.set_alpha(90)
            scr.blit(b, b.get_rect(center=(x, cy)))
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
    toast = g.get("toast")
    if toast and now < toast[1]:                # "Usunięto · „przywróć zdjęcie”"
        img = text(toast[0], 20, WHITE, "Bold")
        pill = rrect(img.get_width() + 36, 40, 20, (20, 22, 34, 220))
        pr = pill.get_rect(center=(W // 2, H - 130))
        scr.blit(pill, pr)
        scr.blit(img, img.get_rect(center=pr.center))
    # the neighbours made ahead, one a frame, while nothing moves: turning
    # then never waits for a 1 MB drawing to load (~150 ms on the Pi)
    if not 0 <= t < 1.5:
        for j in (i + 1, i - 1):
            if 0 <= j < n and _picture(items[j], W, H, maxw, maxh, load=False) is None:
                _picture(items[j], W, H, maxw, maxh)
                break


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
    t = f"{cur['temp']}°"                     # "-12°" must stop short of the days' panel
    ts = shrink(t, 104, 330 - 14 - (lx + 140), "ExtraBold", 56)
    scr.blit(shadowed(t, ts, WHITE, "ExtraBold", 110), (lx + 140, 52 + (104 - ts) // 2))
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
    ptop = 72                                 # (under the ✕ of every page)
    ph = H - ptop - 14
    panel = rrect(pw, ph, 22, (255, 255, 255, 34))
    scr.blit(panel, (px, ptop))
    if not rows:
        return
    lo = min(d["tmin"] for d in rows)
    hi = max(d["tmax"] for d in rows)
    rh = ph // len(rows)
    bw = pw - 276 - 66                       # the bar between the two temperatures
    sep = rrect(pw - 32, 1, 0, (255, 255, 255, 46))
    for j, d in enumerate(rows):
        k = _ease((now - data.get("t0", now) - 0.06 * j) / 0.6)
        y = ptop + j * rh + int(24 * (1 - k))
        if j:
            scr.blit(sep, (px + 16, ptop + j * rh))
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


# ── a list: the shopping list, "plan na dziś", reminders, status ────────────

LIST_PAGE = 7                # rows on a page; more: a page every LIST_TURN s
LIST_TURN = 6.0
_LABEL = (255, 206, 120)


def _list_icon(heading, size=34):
    """A little picture for the heading: a cart, a calendar, a bell, a chip."""
    low = heading.lower()
    kind = ("cart" if "zakup" in low else "plan" if "plan" in low else
            "bell" if "przypom" in low or "minut" in low or "budzik" in low else
            "chip" if "status" in low else "list")
    key = ("licon", kind, size)
    s = _cache.get(key)
    if s is not None:
        return s
    S = size * SS
    big = pygame.Surface((S, S), pygame.SRCALPHA)
    u, w = S / 34, int(S / 34 * 3)
    if kind == "cart":
        pts = [(3 * u, 6 * u), (8 * u, 6 * u), (12 * u, 22 * u), (27 * u, 22 * u), (30 * u, 11 * u),
               (10 * u, 11 * u)]
        pygame.draw.lines(big, _LABEL, False, pts, w)
        for x in (14, 25):
            pygame.draw.circle(big, _LABEL, (int(x * u), int(28 * u)), int(2.8 * u))
    elif kind == "plan":
        pygame.draw.rect(big, _LABEL, pygame.Rect(4 * u, 7 * u, 26 * u, 24 * u), w,
                         border_radius=int(4 * u))
        pygame.draw.rect(big, _LABEL, pygame.Rect(4 * u, 7 * u, 26 * u, 7 * u),
                         border_top_left_radius=int(4 * u), border_top_right_radius=int(4 * u))
        for x in (11, 23):
            _line(big, _LABEL, (x * u, 3 * u), (x * u, 9 * u), w)
        for x, y in ((11, 20), (17, 20), (23, 20), (11, 26), (17, 26)):
            pygame.draw.circle(big, _LABEL, (int(x * u), int(y * u)), int(1.8 * u))
    elif kind == "bell":
        pygame.draw.ellipse(big, _LABEL, pygame.Rect(8 * u, 5 * u, 18 * u, 22 * u))
        pygame.draw.rect(big, _LABEL, pygame.Rect(5 * u, 21 * u, 24 * u, 5 * u),
                         border_radius=int(2 * u))
        pygame.draw.circle(big, _LABEL, (int(17 * u), int(29 * u)), int(3 * u))
    elif kind == "chip":
        pygame.draw.rect(big, _LABEL, pygame.Rect(8 * u, 8 * u, 18 * u, 18 * u), w,
                         border_radius=int(3 * u))
        for k in (12, 17, 22):
            for a, b in (((k, 3), (k, 8)), ((k, 26), (k, 31)), ((3, k), (8, k)), ((26, k), (31, k))):
                _line(big, _LABEL, (a[0] * u, a[1] * u), (b[0] * u, b[1] * u), int(2 * u))
    else:
        for y in (9, 17, 25):
            pygame.draw.circle(big, _LABEL, (int(6 * u), int(y * u)), int(2.5 * u))
            _line(big, _LABEL, (12 * u, y * u), (30 * u, y * u), w)
    s = _cache[key] = _down(big, size, size)
    return s


_LIST_TOP, _LIST_ROW, _LIST_X = 74, 52, 18


def list_page(rows, now):
    pages = max(1, -(-len(rows) // LIST_PAGE))
    return int(now // LIST_TURN) % pages


def list_row_at(nx, ny, rows, page, W=800, H=480):
    """The row (its index in rows) under a tap, or None — draw_list's layout."""
    x, y = nx * W, ny * H
    k = int((y - _LIST_TOP - 8) // _LIST_ROW)
    if not (_LIST_X <= x <= W - _LIST_X) or y < _LIST_TOP + 8 or k < 0:
        return None
    i = page * LIST_PAGE + k
    if k >= LIST_PAGE or i >= len(rows):
        return None
    return i


# ── the radio's page (radio.show_page): kinds on the left, stations to tap ───

def _radio_layout(W, H, n_st, playing, n_kinds):
    """The page's rects: {"stop", "timer", "plus", "minus" (None when nothing
    plays), "kinds": [...], "sts": [...], "stars": [...]}."""
    top = 78
    rh = min(49, (H - top - 8) // max(1, n_kinds))
    kinds = [pygame.Rect(16, top + k * rh, 168, rh - 5) for k in range(n_kinds)]
    x0, gap = 198, 12
    cw = (W - x0 - 16 - gap) // 2
    rows = max(4, -(-n_st // 2))
    ch = (H - top - 14 - (rows - 1) * 10) // rows
    sts = [pygame.Rect(x0 + (k % 2) * (cw + gap), top + (k // 2) * (ch + 10), cw, ch)
           for k in range(n_st)]
    stars = [pygame.Rect(r.right - 42, r.y + 6, 36, 36) for r in sts]
    out = {"kinds": kinds, "sts": sts, "stars": stars,
           "stop": None, "timer": None, "plus": None, "minus": None}
    if playing:
        out["stop"] = pygame.Rect(W - 210, 18, 112, 42)
        out["timer"] = pygame.Rect(out["stop"].x - 54, 19, 42, 40)
        out["plus"] = pygame.Rect(out["timer"].x - 50, 19, 42, 40)
        out["minus"] = pygame.Rect(out["plus"].x - 48, 19, 42, 40)
    return out


def radio_hit(x, y, W, H, data):
    """("cat", i) | ("st", i) | ("star", i) | ("stop",) | ("vol-",) |
    ("vol+",) | ("timer",) | None for a tap at (x, y) px."""
    import radio
    kinds, ci = radio.page_list(data)
    L = _radio_layout(W, H, len(kinds[ci][2]), radio.playing(), len(kinds))
    for key, hit in (("stop", "stop"), ("minus", "vol-"), ("plus", "vol+"), ("timer", "timer")):
        if L[key] and L[key].inflate(6, 6).collidepoint(x, y):
            return (hit,)
    for k, r in enumerate(L["kinds"]):
        if r.collidepoint(x, y):
            return ("cat", k)
    for k, r in enumerate(L["stars"]):
        if r.inflate(8, 8).collidepoint(x, y):
            return ("star", k)
    for k, r in enumerate(L["sts"]):
        if r.collidepoint(x, y):
            return ("st", k)
    return None


def _star(surf, cx, cy, r, col, filled):
    pts = []
    for j in range(10):
        a = -math.pi / 2 + j * math.pi / 5
        rr = r if j % 2 == 0 else r * 0.45
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    if filled:
        pygame.draw.polygon(surf, col, pts)
    pygame.draw.aalines(surf, col, True, pts)
    if not filled:
        pygame.draw.lines(surf, col, True, pts, 2)


def draw_radio(scr, data, now, W, H):
    """Radio: what plays (and the song), quieter / louder, the sleep timer,
    Stop; the kinds (favourites and the last played first); their stations
    — the one playing lit, with bars moving; a star for a favourite; the
    ones that didn't answer lately greyed."""
    import radio
    scr.blit(vgrad(W, H, (18, 20, 38), (40, 32, 66)), (0, 0))
    gold = (255, 205, 120)
    title = text("Radio", 32, WHITE, "ExtraBold")
    scr.blit(title, (24, 38 - title.get_height() // 2))
    kinds, ci = radio.page_list(data)
    on = radio.playing()
    sts_now = kinds[ci][2]
    L = _radio_layout(W, H, len(sts_now), on, len(kinds))
    if on:
        song = radio.now_title()
        line = on + (f" · {song}" if song else "")
        room = L["minus"].x - 150 - 12
        img = text(fit(line, 19, room, "SemiBold"), 19, gold, "SemiBold")
        scr.blit(img, (150, 38 - img.get_height() // 2))
        stop = L["stop"]
        scr.blit(rrect(stop.w, stop.h, 21, (214, 52, 52, 230)), stop)
        scr.blit(rrect(14, 14, 3, (255, 255, 255, 255)), (stop.x + 20, stop.centery - 7))
        lab = text("Stop", 21, WHITE, "ExtraBold")
        scr.blit(lab, (stop.x + 44, stop.centery - lab.get_height() // 2))
        for key, sign in (("minus", "−"), ("plus", "+")):
            r = L[key]
            scr.blit(rrect(r.w, r.h, 20, (255, 255, 255, 34)), r)
            g = text(sign, 28, WHITE, "ExtraBold")
            scr.blit(g, g.get_rect(center=(r.centerx, r.centery - 1)))
        r = L["timer"]                                # the sleep timer: a clock, or minutes left
        left = radio.until()
        scr.blit(rrect(r.w, r.h, 20, (255, 205, 120, 90) if left else (255, 255, 255, 34)), r)
        if left:
            m = text(str(max(1, int(round((left - time.time()) / 60)))), 18, WHITE, "ExtraBold")
            scr.blit(m, m.get_rect(center=r.center))
        else:
            c = r.center
            pygame.draw.circle(scr, WHITE, c, 11, 2)
            pygame.draw.line(scr, WHITE, c, (c[0], c[1] - 7), 2)
            pygame.draw.line(scr, WHITE, c, (c[0] + 5, c[1]), 2)
    fs = 21 if len(kinds) <= 8 else 19
    for k, (r, (key, label, _)) in enumerate(zip(L["kinds"], kinds)):
        sel = k == ci
        scr.blit(rrect(r.w, r.h, 14, (255, 205, 120, 70) if sel else (255, 255, 255, 16)), r)
        lab = text(label, fs, WHITE if sel else (225, 225, 240), "ExtraBold" if sel else "Bold")
        scr.blit(lab, (r.x + 16, r.centery - lab.get_height() // 2))
        if on and any(n == on for n, _, _ in kinds[k][2]) and key not in ("recent",):
            scr.blit(rrect(8, 8, 4, gold + (255,)), (r.right - 22, r.centery - 4))
    favs = {n for n, _ in radio.favs()}
    gone = radio.dead()
    for k, (r, star, (name, url, blurb)) in enumerate(zip(L["sts"], L["stars"], sts_now)):
        lit = name == on
        dim = url in gone and not lit
        scr.blit(rrect(r.w, r.h, 16, (255, 196, 110, 75) if lit else (255, 255, 255, 22)), r)
        room = r.w - (100 if lit else 60)
        ns = shrink(name, 22, room, "ExtraBold", 17)       # (long names: smaller first)
        nm = text(fit(name, ns, room, "ExtraBold"), ns, (150, 150, 165) if dim else WHITE,
                  "ExtraBold")
        bl = text(fit("nie odpowiada" if dim else blurb, 17, room, "SemiBold"), 17,
                  (150, 150, 165) if dim else (200, 200, 220), "SemiBold")
        y = r.centery - (nm.get_height() + bl.get_height()) // 2
        scr.blit(nm, (r.x + 16, y))
        scr.blit(bl, (r.x + 16, y + nm.get_height()))
        _star(scr, star.centerx, star.centery, 11, gold if name in favs else (150, 150, 175),
              name in favs)
        if lit:                                       # bars moving: it's playing
            for j in range(3):
                hgt = 8 + 14 * abs(math.sin(now * (5.0 + 1.7 * j) + j))
                bar = rrect(6, int(hgt), 3, gold + (255,))
                scr.blit(bar, (r.right - 84 + j * 10, r.centery + 11 - int(hgt)))
    toast = data.get("toast")
    if toast and time.time() < toast[1]:             # "Głośność 80%", "w ulubionych"
        img = text(toast[0], 20, WHITE, "Bold")
        pill = rrect(img.get_width() + 36, 40, 20, (20, 22, 34, 235))
        pr = pill.get_rect(center=(W // 2 + 90, H - 34))
        scr.blit(pill, pr)
        scr.blit(img, img.get_rect(center=pr.center))


# ── the story page (story.py): the picture, the title, the choices; the list ──

_STORY_IMG = {}            # (path, size) → a rounded, scaled picture


def _story_img(path, size):
    """A story's picture, scaled to size × size with rounded corners (cached)."""
    key = (path, size)
    img = _STORY_IMG.get(key)
    if img is None:
        if len(_STORY_IMG) > 40:
            _STORY_IMG.clear()
        try:
            raw = pygame.image.load(path)
        except (pygame.error, FileNotFoundError, OSError):
            return None
        img = pygame.transform.smoothscale(raw, (size, size))
        mask = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=22)
        out = pygame.Surface((size, size), pygame.SRCALPHA)
        out.blit(img, (0, 0))
        out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        img = _STORY_IMG[key] = out
    return img


def _wrap(s, size, width, weight="Bold", lines=2):
    """Words in up to `lines` lines that fit `width` (the last one cut with …)."""
    f = font(size, weight)
    out, cur = [], ""
    for w in s.split():
        t = (cur + " " + w).strip()
        if f.size(t)[0] <= width:
            cur = t
        else:
            if cur:
                out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = fit(out[-1] + "…", size, width, weight)
    return out


def _story_layout(W, H, data):
    """The page's tap targets: {"ideas": [...], "choices": [...], "cards": [...],
    "prev", "next"}."""
    mode = data.get("mode")
    out = {"ideas": [], "choices": [], "cards": [], "prev": None, "next": None}
    if mode == "topic":
        out["ideas"] = [pygame.Rect(W // 2 - 230, 170 + k * 84, 460, 70)
                        for k in range(len(data.get("ideas") or []))]
    elif mode == "choose":
        x0 = 24 + 432 + 24
        out["choices"] = [pygame.Rect(x0, 196 + k * 124, W - x0 - 24, 108)
                          for k in range(len(data.get("choices") or []))]
    elif mode == "list":
        cw, ch = (W - 48 - 2 * 16) // 3, 178
        out["cards"] = [pygame.Rect(24 + (k % 3) * (cw + 16), 78 + (k // 3) * (ch + 14), cw, ch)
                        for k in range(6)]
        out["prev"] = pygame.Rect(24, H - 50, 64, 40)
        out["next"] = pygame.Rect(W - 88, H - 50, 64, 40)
    return out


def story_hit(x, y, W, H, data):
    """("idea", i) | ("choice", i) | ("card", i) | ("page", ±1) | None."""
    import story
    L = _story_layout(W, H, data)
    for kind in ("ideas", "choices", "cards"):
        for k, r in enumerate(L[kind]):
            if r.collidepoint(x, y):
                return (kind[:-1] if kind != "ideas" else "idea", k)
    if data.get("mode") == "list" and len(story.saved()) > story.PAGE:
        if L["prev"].inflate(16, 16).collidepoint(x, y):
            return ("page", -1)
        if L["next"].inflate(16, 16).collidepoint(x, y):
            return ("page", 1)
    return None


def _dots_wait(now):
    return "." * (1 + int(now * 2.5) % 3)


def draw_story(scr, data, now, W, H):
    """A story: on the left its picture (drawing… until it's ready), on the
    right the title, the parts so far, and the two choices as big buttons —
    or the ideas for a topic, or the list of saved stories."""
    import story
    scr.blit(vgrad(W, H, (22, 18, 44), (52, 34, 78)), (0, 0))
    gold, soft = (255, 205, 120), (205, 200, 230)
    mode = data.get("mode")
    L = _story_layout(W, H, data)
    if mode == "topic":
        t = text("Bajka", 40, WHITE, "ExtraBold")
        scr.blit(t, t.get_rect(center=(W // 2, 70)))
        q = text("O czym ma być? Powiedz albo dotknij.", 22, soft, "SemiBold")
        scr.blit(q, q.get_rect(center=(W // 2, 122)))
        for r, idea in zip(L["ideas"], data.get("ideas") or []):
            scr.blit(rrect(r.w, r.h, 22, (255, 205, 120, 70)), r)
            lab = text(idea[0].upper() + idea[1:], 26, WHITE, "ExtraBold")
            scr.blit(lab, lab.get_rect(center=r.center))
        return
    if mode == "list":
        t = text("Nasze bajki", 32, WHITE, "ExtraBold")
        scr.blit(t, (24, 38 - t.get_height() // 2))
        items = story.saved()
        pages = max(1, -(-len(items) // story.PAGE))
        page = min(data.get("page", 0), pages - 1)
        shown = items[page * story.PAGE:(page + 1) * story.PAGE]
        for r, st in zip(L["cards"], shown):
            scr.blit(rrect(r.w, r.h, 18, (255, 255, 255, 26)), r)
            first = story.image_path(st["id"], (st.get("parts") or [{}])[0].get("image"))
            th = _story_img(first, 104) if first and os.path.exists(first) else None
            if th:
                scr.blit(th, (r.x + 10, r.y + 10))
            else:
                scr.blit(rrect(104, 104, 22, (255, 255, 255, 30)), (r.x + 10, r.y + 10))
            tx = r.x + 124
            for k, line in enumerate(_wrap(st.get("title", ""), 19, r.right - tx - 10,
                                           "ExtraBold", lines=3)):
                img = text(line, 19, WHITE, "ExtraBold")
                scr.blit(img, (tx, r.y + 12 + k * 24))
            when = time.localtime(st.get("created", 0))
            sub = f"{when.tm_mday}.{when.tm_mon:02d}" + (f" · {st['child']}" if st.get("child")
                                                         else "")
            img = text(sub, 16, soft, "SemiBold")
            scr.blit(img, (r.x + 12, r.bottom - 52))
            n = len(st.get("parts") or [])
            img = text(f"{n} części", 16, soft, "SemiBold")
            scr.blit(img, (r.x + 12, r.bottom - 30))
        if pages > 1:
            for key, sign in (("prev", "‹"), ("next", "›")):
                r = L[key]
                scr.blit(rrect(r.w, r.h, 20, (255, 255, 255, 34)), r)
                g = text(sign, 30, WHITE, "ExtraBold")
                scr.blit(g, g.get_rect(center=(r.centerx, r.centery - 2)))
            gap, y = 18, H - 30
            x0 = W // 2 - (pages - 1) * gap // 2
            for k in range(pages):
                on = k == page
                d = rrect(20 if on else 8, 8, 4, (255, 255, 255, 235 if on else 90))
                scr.blit(d, d.get_rect(center=(x0 + k * gap, y)))
        return
    # the story itself: the picture…
    size = 432
    path = data.get("image")
    img = _story_img(path, size) if path and os.path.exists(path) else None
    if img:
        scr.blit(img, (24, 24))
    else:
        scr.blit(rrect(size, size, 22, (255, 255, 255, 22)), (24, 24))
        lab = text("Rysuję" + _dots_wait(now), 26, soft, "Bold")
        scr.blit(lab, lab.get_rect(center=(24 + size // 2, 24 + size // 2)))
    # …the title and the parts…
    x0 = 24 + size + 24
    room = W - x0 - 24
    y = 30
    for line in _wrap(data.get("title") or "Bajka", 26, room - 50, "ExtraBold", lines=3):
        t = text(line, 26, WHITE, "ExtraBold")
        scr.blit(t, (x0, y))
        y += 32
    of, part = data.get("of") or 0, data.get("part") or 0
    for k in range(of):
        on = k < part
        d = rrect(22 if k == part - 1 else 10, 10, 5, gold + (255,) if on else (255, 255, 255, 70))
        scr.blit(d, (x0 + k * 30, y + 10))
    y += 40
    if mode == "choose":
        q = text("Co dalej?", 24, gold, "ExtraBold")
        scr.blit(q, (x0, y + 6))
        for k, (r, c) in enumerate(zip(L["choices"], data.get("choices") or [])):
            scr.blit(rrect(r.w, r.h, 22, ((255, 205, 120, 80) if k == 0 else (130, 180, 255, 80))),
                     r)
            badge = rrect(40, 40, 20, (255, 255, 255, 220))
            scr.blit(badge, (r.x + 14, r.centery - 20))
            num = text(str(k + 1), 22, (40, 30, 60), "ExtraBold")
            scr.blit(num, num.get_rect(center=(r.x + 34, r.centery)))
            lines = _wrap(c[0].upper() + c[1:], 22, r.w - 84, "ExtraBold", lines=2)
            ty = r.centery - len(lines) * 14
            for line in lines:
                t = text(line, 22, WHITE, "ExtraBold")
                scr.blit(t, (r.x + 68, ty))
                ty += 28
    else:
        status = data.get("status")
        if mode == "make":
            status = (status or "Wymyślam") .rstrip(".…") + _dots_wait(now)
        elif mode == "tell":
            status = "Opowiadam…"
        elif mode == "replay" and not status:
            status = "Opowiadam jeszcze raz…"
        if mode == "end":
            t = text("Koniec", 40, gold, "ExtraBold")
            scr.blit(t, (x0, y + 10))
            s2 = text("Zapisana w „Naszych bajkach”" if not data.get("of") or
                      data.get("part") == data.get("of") else "", 18, soft, "SemiBold")
            scr.blit(s2, (x0, y + 66))
        elif status:
            for line in _wrap(status, 22, room, "Bold", lines=3):
                t = text(line, 22, soft, "Bold")
                scr.blit(t, (x0, y))
                y += 30
            if mode in ("tell", "replay"):                # a little voice, moving
                for j in range(5):
                    hgt = 6 + 18 * abs(math.sin(now * (4.0 + j * 0.9) + j))
                    scr.blit(rrect(8, int(hgt), 4, gold + (255,)),
                             (x0 + j * 14, y + 34 - int(hgt)))


def draw_list(scr, heading, rows, now, W, H, meta=None):
    """The title with its picture, then the rows on a soft panel — a label
    (a time, "lista", "•") and its value; more than LIST_PAGE: pages. meta
    (a list of hers): the page held while tapped, "Usunąć?" on a tapped row."""
    meta = meta or {}
    scr.blit(vgrad(W, H, (20, 22, 40), (44, 36, 74)), (0, 0))
    scr.blit(_list_icon(heading), (24, 21))
    ts = shrink(heading, 32, W - 160, "ExtraBold", 22)
    title = text(fit(heading, ts, W - 160, "ExtraBold"), ts, WHITE, "ExtraBold")
    scr.blit(title, (68, 38 - title.get_height() // 2))
    pages = max(1, -(-len(rows) // LIST_PAGE))
    page = meta.get("page")
    page = list_page(rows, now) if page is None else min(page, pages - 1)
    shown = rows[page * LIST_PAGE:page * LIST_PAGE + LIST_PAGE]
    top, px, pw = _LIST_TOP, _LIST_X, W - 2 * _LIST_X
    rh = _LIST_ROW
    conf = meta.get("confirm")
    asked = conf[0] if conf and now - conf[1] < 4.0 else None
    ph = max(rh, len(shown) * rh) + 16
    scr.blit(rrect(pw, ph, 20, (255, 255, 255, 22)), (px, top))
    bullets = all(w == "•" for w, _ in rows)
    # the values start after the longest label; a smaller size when they wouldn't fit
    for fs in (28, 25, 22):
        f = font(fs, "Bold")
        label_w = 0 if bullets else max((f.size(w)[0] for w, _ in rows if w != "•"), default=0)
        value_x = px + (64 if bullets else min(26 + label_w + 26, W // 2))
        if all(font(fs, "SemiBold").size(v)[0] <= px + pw - 24 - value_x for _, v in rows):
            break
    sep = rrect(pw - 40, 1, 0, (255, 255, 255, 30))
    for k, (label, value) in enumerate(shown):
        y = top + 8 + k * rh
        mid = y + rh // 2
        if k:
            scr.blit(sep, (px + 20, y))
        if asked == page * LIST_PAGE + k:            # tapped once: sure?
            scr.blit(rrect(pw - 16, rh - 6, 14, (214, 52, 52, 150)), (px + 8, y + 3))
            q = text("Usunąć?", 20, WHITE, "ExtraBold")
            pill = rrect(q.get_width() + 28, 34, 17, (214, 52, 52, 255))
            pr = pill.get_rect(midright=(px + pw - 16, mid))
            scr.blit(pill, pr)
            scr.blit(q, q.get_rect(center=pr.center))
        if label == "•":
            scr.blit(rrect(12, 12, 6, _LABEL + (255,)), (px + 30, mid - 6))
        else:
            lab = text(label, fs, _LABEL, "Bold")
            scr.blit(lab, (px + 26, mid - lab.get_height() // 2))
        val = text(fit(value, fs, px + pw - 24 - value_x, "SemiBold"), fs, WHITE, "SemiBold")
        scr.blit(val, (value_x, mid - val.get_height() // 2))
    toast = meta.get("toast")
    if toast and now < toast[1]:                   # "Skreślone: mleko · „przywróć listę”"
        img = text(toast[0], 20, WHITE, "Bold")
        pill = rrect(img.get_width() + 36, 40, 20, (20, 22, 34, 230))
        pr = pill.get_rect(center=(W // 2, H - 40))
        scr.blit(pill, pr)
        scr.blit(img, img.get_rect(center=pr.center))
    if pages > 1:                                  # dots for the pages
        gap, y = 18, H - 16
        x0 = W // 2 - (pages - 1) * gap // 2
        for k in range(pages):
            on = k == page
            d = rrect(20 if on else 8, 8, 4, (255, 255, 255, 235 if on else 90))
            scr.blit(d, d.get_rect(center=(x0 + k * gap, y)))


# ── the settings page (settings_page.py): tabs on the left, rows to tap ──────

def _settings_layout(W, H, n_rows):
    """{"tabs": [...], "rows": [...], "ctrls": [...], "dialog", "yes", "no"}."""
    import settings_page
    top = 78
    tabs = [pygame.Rect(16, top + k * 58, 168, 50) for k in range(len(settings_page.TABS))]
    x0 = 198
    rh = min(72, (H - top - 10) // max(1, n_rows))
    rws = [pygame.Rect(x0, top + k * rh, W - x0 - 16, rh - 8) for k in range(n_rows)]
    ctrls = [pygame.Rect(r.right - 160, r.centery - 21, 148, 42) for r in rws]
    dlg = pygame.Rect(W // 2 - 270, H // 2 - 125, 540, 250)
    no = pygame.Rect(dlg.x + 30, dlg.bottom - 78, 225, 54)
    yes = pygame.Rect(dlg.right - 255, dlg.bottom - 78, 225, 54)
    return {"tabs": tabs, "rows": rws, "ctrls": ctrls, "dialog": dlg, "yes": yes, "no": no}


def settings_hit(x, y, W, H, data):
    """("tab", i) | ("row", i) | ("yes",) | ("no",) | None for a tap at (x, y) px."""
    import settings_page
    L = _settings_layout(W, H, len(settings_page.rows(data.get("tab", 0))))
    if data.get("confirm"):
        for key in ("yes", "no"):
            if L[key].inflate(10, 10).collidepoint(x, y):
                return (key,)
        return None
    for k, r in enumerate(L["tabs"]):
        if r.collidepoint(x, y):
            return ("tab", k)
    for k, r in enumerate(L["rows"]):
        if r.collidepoint(x, y):
            return ("row", k)
    return None


def draw_settings(scr, data, now, W, H):
    """Ustawienia: the tabs; each row a label, a line under it and its control
    (a switch, a value to tap through, a number); the reset asks first."""
    import settings_page
    scr.blit(vgrad(W, H, (18, 20, 38), (40, 32, 66)), (0, 0))
    gold, soft = (255, 205, 120), (200, 200, 220)
    title = text("Ustawienia", 32, WHITE, "ExtraBold")
    scr.blit(title, (24, 38 - title.get_height() // 2))
    tab = data.get("tab", 0)
    rows = settings_page.rows(tab, now)
    L = _settings_layout(W, H, len(rows))
    for k, (r, name) in enumerate(zip(L["tabs"], settings_page.TABS)):
        sel = k == tab
        scr.blit(rrect(r.w, r.h, 14, (255, 205, 120, 70) if sel else (255, 255, 255, 16)), r)
        lab = text(name, 21, WHITE if sel else (225, 225, 240), "ExtraBold" if sel else "Bold")
        scr.blit(lab, (r.x + 16, r.centery - lab.get_height() // 2))
    for r, c, row in zip(L["rows"], L["ctrls"], rows):
        scr.blit(rrect(r.w, r.h, 16, (255, 255, 255, 22)), r)
        kind, val = row["kind"], row["value"]
        room = (c.x if kind != "info" else r.right - 250) - r.x - 28
        nm = text(fit(row["label"], 22, room, "ExtraBold"), 22, WHITE, "ExtraBold")
        sub = text(fit(row["sub"], 16, room, "SemiBold"), 16, soft, "SemiBold")
        y = r.centery - (nm.get_height() + sub.get_height()) // 2
        scr.blit(nm, (r.x + 16, y))
        scr.blit(sub, (r.x + 16, y + nm.get_height()))
        if kind == "toggle":                          # a switch: gold and right when on
            sw = pygame.Rect(c.right - 74, c.centery - 17, 66, 34)
            scr.blit(rrect(sw.w, sw.h, 17, (255, 196, 110, 230) if val else (255, 255, 255, 50)), sw)
            knob = rrect(26, 26, 13, (255, 255, 255, 255))
            scr.blit(knob, (sw.right - 30 if val else sw.x + 4, sw.y + 4))
            lab = text("Wł." if val else "Wył.", 17, WHITE if val else soft, "Bold")
            scr.blit(lab, (sw.x - lab.get_width() - 10, c.centery - lab.get_height() // 2))
        elif kind in ("cycle", "danger"):             # a value to tap through / the reset
            col = (214, 52, 52, 230) if kind == "danger" else (255, 255, 255, 34)
            scr.blit(rrect(c.w, c.h, 21, col), c)
            v = text(fit(str(val), 19, c.w - 40, "ExtraBold"), 19, WHITE, "ExtraBold")
            scr.blit(v, v.get_rect(center=(c.centerx - (8 if kind == "cycle" else 0), c.centery)))
            if kind == "cycle":
                ch = text("›", 24, gold, "ExtraBold")
                scr.blit(ch, ch.get_rect(center=(c.right - 18, c.centery - 2)))
        else:                                         # a number, a cost
            v = text(fit(str(val), 21, 230, "ExtraBold"), 21, gold, "ExtraBold")
            scr.blit(v, (r.right - 16 - v.get_width(), r.centery - v.get_height() // 2))
    if data.get("confirm") and now - data["confirm"] < settings_page.CONFIRM_SECS:
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 150))
        scr.blit(shade, (0, 0))
        d = L["dialog"]
        scr.blit(rrect(d.w, d.h, 22, (34, 30, 54, 250)), d)
        q = text("Reset fabryczny?", 28, WHITE, "ExtraBold")
        scr.blit(q, q.get_rect(center=(d.centerx, d.y + 42)))
        for j, ln in enumerate(("Luna zapomni wszystkie wspomnienia", "i wszystkie znane osoby.")):
            t = text(ln, 19, soft, "SemiBold")
            scr.blit(t, t.get_rect(center=(d.centerx, d.y + 86 + j * 26)))
        for key, lab, col in (("no", "Anuluj", (255, 255, 255, 40)),
                              ("yes", "Tak, wyczyść", (214, 52, 52, 240))):
            b = L[key]
            scr.blit(rrect(b.w, b.h, 24, col), b)
            t = text(lab, 21, WHITE, "ExtraBold")
            scr.blit(t, t.get_rect(center=b.center))
    toast = data.get("toast")
    if toast and now < toast[1]:                      # "Język: English", "Włączone"
        img = text(toast[0], 20, WHITE, "Bold")
        pill = rrect(img.get_width() + 36, 40, 20, (20, 22, 34, 235))
        pr = pill.get_rect(center=(W // 2 + 90, H - 30))
        scr.blit(pill, pr)
        scr.blit(img, img.get_rect(center=pr.center))


# ── the dock: quick icons along the bottom (dock.py) ─────────────────────────

# icons on a 24-unit grid: ("l", points, closed) | ("c", centre, r) | ("r", x, y, w, h)
_GEAR = [("c", (12, 12), 3.2), ("c", (12, 12), 7.0)] + [
    ("l", [(12 + 7.0 * math.cos(a), 12 + 7.0 * math.sin(a)),
           (12 + 10.0 * math.cos(a), 12 + 10.0 * math.sin(a))], False)
    for a in (i * math.pi / 4 for i in range(8))]


def _arc(c, r, a0, a1, n=10):
    """Points along a circle from angle a0 to a1 (degrees, y down)."""
    return [(c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


# a sun peeking over a cloud: the cloud's outline, then the sun's visible arc and rays
_WEATHER_ICON = [
    ("l", _arc((18, 16.5), 3.5, 90, -95) + _arc((13.5, 13.5), 4.8, -15, -180)
     + _arc((7.5, 16.8), 3.2, -110, 90) + [(18, 20)], False),
    ("l", _arc((8, 8), 3.2, 95, 350, 12), False)] + [
    ("l", [(8 + 5.0 * math.cos(math.radians(a)), 8 + 5.0 * math.sin(math.radians(a))),
           (8 + 7.0 * math.cos(math.radians(a)), 8 + 7.0 * math.sin(math.radians(a)))], False)
    for a in (135, 180, 225, 270, 315)]
DOCK_ICONS = {
    "shopping": [("l", [(2, 4), (5, 4), (7.5, 15), (18, 15), (20.5, 7), (6, 7)], False),
                 ("c", (9, 19.5), 1.6), ("c", (17, 19.5), 1.6)],
    "todo": [("r", 3, 3.5, 6, 6), ("l", [(4.5, 6.5), (6, 8), (10, 2.5)], False),
             ("l", [(12.5, 6.5), (21, 6.5)], False),
             ("r", 3, 14.5, 6, 6), ("l", [(12.5, 17.5), (21, 17.5)], False)],
    "schedule": [("r", 3, 5, 18, 16), ("l", [(3, 10), (21, 10)], False),
                 ("l", [(8, 3), (8, 7)], False), ("l", [(16, 3), (16, 7)], False),
                 ("c", (8, 14.5), 0.9), ("c", (12, 14.5), 0.9), ("c", (16, 14.5), 0.9),
                 ("c", (8, 18), 0.9), ("c", (12, 18), 0.9)],
    "weather": _WEATHER_ICON,
    "photos": [("r", 2.5, 5, 19, 15), ("l", [(4, 18), (9.5, 11.5), (13.5, 15.5), (16, 13), (20, 18)], False),
               ("c", (16.5, 9.5), 1.7)],
    "radio": [("r", 3, 9, 18, 12), ("l", [(7, 9), (17, 3)], False), ("c", (9, 15), 3.0),
              ("l", [(15, 13), (18.5, 13)], False), ("l", [(15, 17), (18.5, 17)], False)],
    "settings": _GEAR,
}

# per character: stroke width (grid units), glow, pixel cell (px), cell gap, scanlines
_DOCK_STYLE = {
    None:    {"w": 1.9, "glow": 0.0, "cell": 0, "gap": 0, "scan": False},
    "retro": {"w": 1.4, "glow": 0.0, "cell": 2, "gap": 0, "scan": False},
    "pixel": {"w": 2.0, "glow": 0.5, "cell": 3, "gap": 1, "scan": False},
    "nex":   {"w": 1.6, "glow": 0.9, "cell": 0, "gap": 0, "scan": False},
    "mochi": {"w": 2.4, "glow": 0.0, "cell": 0, "gap": 0, "scan": False},
    "pip":   {"w": 1.7, "glow": 0.8, "cell": 0, "gap": 0, "scan": True},
    "echo":  {"w": 1.3, "glow": 0.7, "cell": 0, "gap": 0, "scan": False},
}


def _prims(surf, prims, k, ox, oy, col, w, aa=True):
    """Draw an icon's grid shapes, k pixels a unit, from (ox, oy)."""
    P = lambda p: (ox + p[0] * k, oy + p[1] * k)
    lw = max(1, int(round(w)))
    for p in prims:
        if p[0] == "l":
            pts = [P(q) for q in p[1]]
            if p[2]:
                pts.append(pts[0])
            for a, b in zip(pts, pts[1:]):
                if aa and lw > 1:
                    _line(surf, col, a, b, lw)
                else:
                    pygame.draw.line(surf, col, a, b, lw)
        elif p[0] == "c":
            c, r = P(p[1]), p[2] * k
            if r <= w * 0.8:                       # a dot
                pygame.draw.circle(surf, col, (int(c[0]), int(c[1])), max(1, int(r + w / 2)))
            else:
                pygame.draw.circle(surf, col, (int(c[0]), int(c[1])), int(r + w / 2), lw)
        else:
            x, y = P((p[1], p[2]))
            pygame.draw.rect(surf, col, pygame.Rect(int(x), int(y), int(p[3] * k), int(p[4] * k)),
                             lw, border_radius=int(2 * k) if aa else 0)


def dock_icon(key, kind, col, size=40):
    """One icon in this character's style: lines, pixels or neon (cached)."""
    ck = ("dock", key, kind, col, size)
    s = _cache.get(ck)
    if s is not None:
        return s
    st = _DOCK_STYLE.get(kind, _DOCK_STYLE[None])
    m = 8                                          # room for the glow
    out = pygame.Surface((size + 2 * m, size + 2 * m), pygame.SRCALPHA)
    big = pygame.Surface((size * SS, size * SS), pygame.SRCALPHA)
    k = size * SS / 24.0
    _prims(big, DOCK_ICONS[key], k * 0.92, size * SS * 0.04, size * SS * 0.04,
           col, st["w"] * k * 0.92)
    ico = _down(big, size, size)
    if st["cell"]:                                 # the soft icon snapped to a grid: pixels
        cell, gap = st["cell"], st["gap"]
        n = size // cell
        low = pygame.transform.smoothscale(ico, (n, n))
        ico = pygame.Surface((size, size), pygame.SRCALPHA)
        for y in range(n):
            for x in range(n):
                if low.get_at((x, y))[3] > 105:
                    ico.fill(col, (x * cell, y * cell, cell - gap, cell - gap))
    if st["glow"]:                                 # a soft halo of its own light
        pad = pygame.Surface((size + 2 * m, size + 2 * m), pygame.SRCALPHA)
        pad.blit(ico, (m, m))
        g = pad
        for f in (2, 4):                           # two passes: round, not boxy
            g = pygame.transform.smoothscale(g, (pad.get_width() // f, pad.get_height() // f))
            g = pygame.transform.smoothscale(g, pad.get_size())
        g.set_alpha(int(255 * st["glow"]))
        out.blit(g, (0, 0))
    out.blit(ico, (m, m))
    if st["scan"]:                                 # a CRT's lines
        for y in range(0, out.get_height(), 3):
            out.fill((255, 255, 255, 120), (0, y, out.get_width(), 1),
                     special_flags=pygame.BLEND_RGBA_MULT)
    _cache[ck] = out
    return out


def draw_dock(scr, kind, cols, now=None):
    """The row of quick icons, faint, in the face's colours (dock.py)."""
    import dock
    now = now if now is not None else time.time()
    col = tuple(int(c) for c in cols[0][:3])
    tint = tuple(int(c) for c in cols[1][:3])
    n = len(dock.ITEMS)
    bw, bh = dock.STEP * n - 12, 52
    pill = rrect(bw, bh, bh // 2, (tint[0] // 8, tint[1] // 8, tint[2] // 8, 70))
    scr.blit(pill, pill.get_rect(center=(dock.W // 2, dock.CY)))
    for key, cx in dock.centres():
        ico = dock_icon(key, kind, col, dock.ICON)
        ico.set_alpha(int(95 + 150 * dock.lit(key, now)))
        scr.blit(ico, ico.get_rect(center=(int(cx), dock.CY)))
