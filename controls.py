"""
controls.py — a strip of controls along the bottom of the screen for what
fills it without a page of its own: the night lamp (its picture or plain
light) and the music's effects over her face. A tap shows it; ‹ name ›
goes back and forth (pictures / effects), the dots pick a colour, ⏻ turns
it off (the lamp; the radio or sleep sound). It hides after SECS without a
touch, or at a tap above it. A swipe changes the picture / effect and shows
the strip with the new name.

The lamp's taps come from robot_face (the lamp is a page), the effects' from
touch_module (the bare face: kind "dock", so she doesn't react to them).
Logic here; draw() alone needs pygame.
"""

import time

from config import SCREEN_WIDTH, SCREEN_HEIGHT
from shared_state import state

W, H = SCREEN_WIDTH, SCREEN_HEIGHT
SECS = 6.0
FADE = 0.6
BAR_H = 84
Y0 = H - BAR_H
PREV = (0, 60)                     # x ranges, px
NEXT = (250, 310)
SW_X, SW_W = 320, 40               # the colour dots: from here, each this wide
OFF = (730, W)

_bar = {"kind": None, "until": 0.0}
# the effects' short names, for the strip
VIS_NAMES = {"wstegi": "wstęgi", "pierscienie": "pierścienie", "iskry": "iskry",
             "slupki": "słupki", "oscyloskop": "fale stereo", "nutki": "nutki",
             "losowo": "co piosenkę inny", "off": "bez efektów"}


def show(kind, now=None):
    _bar.update(kind=kind, until=(now or time.time()) + SECS)


def hide():
    _bar.update(kind=None, until=0.0)


def shown(kind, now=None):
    """0..1 how visible the strip is for this kind (fading out at the end)."""
    if _bar["kind"] != kind:
        return 0.0
    left = _bar["until"] - (now or time.time())
    return max(0.0, min(1.0, left / FADE))


def _lamp_data():
    with state.lock:
        ov = state.overlay
    if ov and ov[0] == "lamp" and time.time() < ov[1]:
        return ov[2] or {}
    return None


def vis_active():
    """The music's effects own the bare face: something plays, no page up, awake."""
    import visualizer
    with state.lock:
        ov, asleep = state.overlay, state.sleep_mode
    return not asleep and not (ov and time.time() < ov[1]) and visualizer.playing()


def content(kind):
    """(name, [(key, rgb or None: a rainbow)], the key chosen) for the strip."""
    import fun
    if kind == "lamp":
        import lamp_scenes
        data = _lamp_data() or {}
        scene = data.get("scene")
        if scene:
            dots = [("own", None)] + [(k, fun.LAMP_COLOURS[k][0]) for k in fun._TINT_ORDER]
            cur = next((k for k, _ in dots[1:] if fun.LAMP_COLOURS[k] == data.get("tint")), "own")
            return lamp_scenes.NAMES.get(scene, scene), dots, cur
        keys = ("ciepł", "biał") + fun._TINT_ORDER
        dots = [(k, fun.LAMP_COLOURS[k][0]) for k in keys]
        col = tuple(map(tuple, data.get("col") or fun.LAMP_COLOURS["ciepł"]))
        cur = next((k for k in keys if fun.LAMP_COLOURS[k] == col), None)
        return "zwykła lampka", dots, cur
    import visualizer
    dots = [("auto", None)] + [(k, tuple(int(255 * c) for c in v[0]))
                               for k, v in visualizer.COLORS.items()]
    return VIS_NAMES.get(visualizer.style(), ""), dots, visualizer.color_setting()


def hit(kind, x, y):
    """What a tap at (x, y) px is on: "prev" | "next" | "off" | ("dot", key) |
    None (on the strip, between them) | "above"."""
    if y < Y0:
        return "above"
    if PREV[0] <= x < PREV[1]:
        return "prev"
    if NEXT[0] <= x < NEXT[1]:
        return "next"
    if OFF[0] <= x <= OFF[1]:
        return "off"
    dots = content(kind)[1]
    i = int((x - SW_X) // SW_W)
    if x >= SW_X and i < len(dots):
        return ("dot", dots[i][0])
    return None


def _step(kind, step):
    if kind == "lamp":
        import fun
        fun.lamp_next(step)
    else:
        import visualizer
        visualizer.step_style(step)


def _do(kind, what):
    import fun
    if what in ("prev", "next"):
        _step(kind, -1 if what == "prev" else 1)
    elif what == "off":
        hide()
        if kind == "lamp":
            fun.lamp_off()
        else:
            import ambience
            import radio
            if radio.playing():
                radio.stop()
            elif ambience.playing():
                ambience.stop()
        return
    elif isinstance(what, tuple):
        key = what[1]
        if kind == "lamp":
            data = _lamp_data() or {}
            if data.get("scene"):
                fun.lamp_tint(None if key == "own" else fun.LAMP_COLOURS[key])
            else:
                fun.lamp_on(fun.LAMP_COLOURS[key], fun._lamp_left())
        else:
            import visualizer
            visualizer.set_colors(key)
    show(kind)


def tap(kind, x, y):
    """A tap (px) on the lamp / the effects: the strip, or what's on it."""
    if not shown(kind):
        show(kind)
        return
    what = hit(kind, x, y)
    print(f"[controls] {kind}: {what}", flush=True)
    if what == "above":
        hide()
    elif what is not None:
        _do(kind, what)
    else:
        show(kind)


def swipe(kind, dx):
    _step(kind, -1 if dx > 0 else 1)
    show(kind)


def vis_touch(kind, nx, ny, dx=0.0):
    """touch_module: a tap / swipe on the bare face while music's effects show
    → True when the strip took it."""
    if kind not in ("tap", "swipe") or not vis_active():
        return False
    if kind == "swipe":
        swipe("vis", dx)
    else:
        tap("vis", nx * W, ny * H)
    return True


# ── drawing (pygame) ─────────────────────────────────────────────────────

_INK = (205, 208, 220)
_RAINBOW = ((255, 90, 70), (255, 200, 70), (120, 255, 140), (90, 200, 255), (130, 120, 255),
            (230, 120, 255))


def draw(scr, kind, now=None):
    """The strip at the bottom of the screen layer, if it shows for this kind."""
    a = shown(kind, now)
    if a <= 0.0:
        return
    import math
    import pygame
    import ui_screens
    name, dots, cur = content(kind)
    bar = pygame.Surface((W, BAR_H), pygame.SRCALPHA)
    bar.fill((6, 6, 12, 175))
    ink = _INK + (255,)
    cy = BAR_H // 2
    for x0, x1, d in (PREV + (-1,), NEXT + (1,)):        # ‹ ›
        cx = (x0 + x1) // 2
        pts = [(cx - 7 * d, cy - 14), (cx + 7 * d, cy), (cx - 7 * d, cy + 14)]
        pygame.draw.lines(bar, ink, False, pts, 4)
    size = 26
    img = ui_screens.font(size, "SemiBold").render(name, True, _INK)
    while img.get_width() > NEXT[0] - PREV[1] - 8 and size > 14:
        size -= 2
        img = ui_screens.font(size, "SemiBold").render(name, True, _INK)
    bar.blit(img, img.get_rect(center=((PREV[1] + NEXT[0]) // 2, cy)))
    for i, (key, rgb) in enumerate(dots):
        cx = SW_X + SW_W * i + SW_W // 2
        if rgb is None:                                   # its own colours / changing ones
            for k, c in enumerate(_RAINBOW):
                a0, a1 = k * math.pi / 3, (k + 1) * math.pi / 3
                pts = [(cx, cy)] + [(cx + 14 * math.cos(a0 + (a1 - a0) * j / 4),
                                     cy + 14 * math.sin(a0 + (a1 - a0) * j / 4)) for j in range(5)]
                pygame.draw.polygon(bar, c + (255,), pts)
        else:
            pygame.draw.circle(bar, tuple(rgb) + (255,), (cx, cy), 14)
        if key == cur:
            pygame.draw.circle(bar, ink, (cx, cy), 18, 2)
    cx = (OFF[0] + OFF[1]) // 2                           # ⏻
    pygame.draw.arc(bar, ink, (cx - 13, cy - 13, 26, 26), math.radians(120), math.radians(420), 3)
    pygame.draw.line(bar, ink, (cx, cy - 17), (cx, cy - 3), 3)
    if a < 1.0:
        bar.fill((255, 255, 255, int(255 * a)), special_flags=pygame.BLEND_RGBA_MULT)
    scr.blit(bar, (0, Y0))
