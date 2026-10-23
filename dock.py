"""
dock.py — a row of quick icons along the bottom of her screen: shopping,
to-do, the week's plan, photos, radio, settings. A tap opens that page.

Faint (a third opaque) and in the face's own colours; drawn by robot_face
(_draw_dock) only on the bare face: no page up, not asleep, no subtitles.
Tapped in the touch thread (touch_module._publish → "dock"), so the face
doesn't react to it and she doesn't giggle. "Ukryj ikony" / "pokaż ikony"
or Ustawienia → Ekran → Ikony na dole switch it.

Pure logic here (no pygame): the unit tests read it.
"""

import time

from config import SCREEN_WIDTH, SCREEN_HEIGHT
from shared_state import state

# (key, what it opens) — left to right
ITEMS = (("shopping", "Zakupy"), ("todo", "Do zrobienia"), ("schedule", "Plan"),
         ("photos", "Zdjęcia"), ("radio", "Radio"), ("settings", "Ustawienia"))

W, H = SCREEN_WIDTH, SCREEN_HEIGHT
ICON = 40                 # an icon's box, px
STEP = 72                 # icon to icon
BAND = 64                 # the strip a tap counts in, from the bottom
CY = H - 30               # the icons' centre line
FLASH = 0.45              # a tapped icon lights up this long

_tapped = (None, 0.0)     # (key, time) — the icon just tapped


def enabled():
    import settings
    return settings.get("dock", True) is not False


def centres():
    """[(key, x)] — the icons' centres, the row centred on the screen."""
    x0 = W / 2 - STEP * (len(ITEMS) - 1) / 2
    return [(k, x0 + i * STEP) for i, (k, _) in enumerate(ITEMS)]


def visible(now=None):
    """On the bare face only."""
    if not enabled():
        return False
    now = now if now is not None else time.time()
    with state.lock:
        ov, cap, asleep = state.overlay, state.caption, state.sleep_mode
    if asleep or (ov and now < ov[1]):
        return False
    if cap and now < cap[2]:
        import settings
        if settings.get("captions", False):
            return False
    return True


def hit(nx, ny, now=None):
    """The icon under a tap (normalised coords), or None."""
    if ny * H < H - BAND or not visible(now):
        return None
    x = nx * W
    for k, cx in centres():
        if abs(x - cx) <= STEP / 2:
            return k
    return None


def lit(key, now=None):
    """0..1: how lit up the icon still is from a tap."""
    k, t = _tapped
    el = (now if now is not None else time.time()) - t
    return max(0.0, 1.0 - el / FLASH) if k == key else 0.0


def _card(text, sub=""):
    with state.lock:
        state.overlay = ("card", time.time() + 5, {"text": text, "sub": sub, "tone": None})


def open_page(key):
    """Open what the icon stands for (silently: a card if there's nothing)."""
    global _tapped
    _tapped = (key, time.time())
    print(f"[dock] {key}", flush=True)
    if key in ("shopping", "todo"):
        import lists
        import screens
        name = "zakupy" if key == "shopping" else "do zrobienia"
        if key == "todo":                   # (said offline it's "rzeczy do zrobienia")
            name = next((k for k, v in lists.get().items() if "do zrobienia" in k and v), name)
        items = lists.get(name)
        if items:
            screens._show("list", 12, (f"Lista: {name}", [("•", i) for i in items],
                                       {"list": name}))
        else:
            _card("Lista zakupów jest pusta" if key == "shopping"
                  else "Nic do zrobienia",
                  "Powiedz: „dopisz mleko”" if key == "shopping"
                  else "Powiedz: „dopisz … do listy rzeczy do zrobienia”")
    elif key == "schedule":
        import schedule
        schedule.show()
    elif key == "photos":
        import screens
        if not screens.show_all_photos():
            _card("Nie mam jeszcze zdjęć", "Powiedz: „zrób mi zdjęcie”")
    elif key == "radio":
        import radio
        radio.show_page()
    elif key == "settings":
        import settings_page
        settings_page.show(0)
