"""
autoclose.py — a page that closes by itself (a card, a translation, a list,
the clock, a photo…) shows how long it has left: a thin line along the
bottom that shrinks, like the gallery's slideshow, and ⏸ next to ✕ that
keeps it open (▶ lets it go on from where it stopped).

robot_face.py draws it (ui_screens.draw_countdown) and passes taps on the
button to toggle(). Pages with their own clock (gallery, lamp, games) and
very short or very long ones get no line.
"""

import time

from shared_state import state

KINDS = ("card", "clock", "clockface", "list", "mirror", "photo", "stars", "weather")
MIN_SECS, MAX_SECS = 3.0, 600.0
HELD = 24 * 3600.0          # paused: "until" this far off

_seen = {}                  # the page on the screen: key, t0, total
_paused = {}                # key (kind, until set, id(data)), left, total


def _key(ov):
    return (ov[0], ov[1], id(ov[2]))


def progress(ov, now=None):
    """None (no line on this page) | (part left 0..1, paused)."""
    now = time.time() if now is None else now
    if not ov or ov[0] not in KINDS:
        return None
    k = _key(ov)
    if _paused.get("key") == k:
        return (_paused["left"] / _paused["total"], True)
    if _seen.get("key") != k:               # a new page, or its time changed
        _seen.clear()
        _seen.update(key=k, t0=now, total=ov[1] - now)
    total = _seen["total"]
    if not MIN_SECS <= total <= MAX_SECS:
        return None
    return (max(0.0, min(1.0, (ov[1] - now) / total)), False)


def hit(nx, ny, W):
    """Was this tap (normalised) on ⏸ / ▶ (left of ✕, top right)?"""
    x = nx * W
    return W - 132 <= x <= W - 70 and ny < 0.2


def toggle(now=None):
    """⏸ → the page stays; ▶ → it goes on. "paused" | "resumed" | None."""
    now = time.time() if now is None else now
    with state.lock:
        ov = state.overlay
        if not ov:
            return None
        if _paused.get("key") == _key(ov):
            left, total = _paused["left"], _paused["total"]
            _paused.clear()
            state.overlay = (ov[0], now + left, ov[2])
            _seen.clear()
            _seen.update(key=_key(state.overlay), t0=now - (total - left), total=total)
            return "resumed"
        p = progress(ov, now)
        if p is None:
            return None
        held = now + HELD
        state.overlay = (ov[0], held, ov[2])
        _paused.clear()
        _paused.update(key=(ov[0], held, id(ov[2])), left=max(0.5, ov[1] - now),
                       total=_seen["total"])
        return "paused"
