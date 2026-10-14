"""
gallery.py — her photos and drawings on the screen, one at a time.

  "pokaż zdjęcia" / "pokaż rysunki"   → a slideshow, newest first, STEP s each
  "następne" / "dalej" / "kolejne"    → the next one (the slideshow stops:
  "poprzednie" / "cofnij" / "wstecz"     you are looking — it stays PAUSE s)
  "pierwsze" / "najstarsze"           → the newest / the oldest
  "zamknij" / "wróć do buzi"          → closed (commands.close_page)
  on the screen: ‹ › buttons at the sides (or a swipe), ✕ in the corner;
  a tap in the middle shows the next one

A photo just taken or a drawing just made opens here too, standing still, so
"poprzednie" goes back to the older ones. ui_screens.py draws it; this module
is the logic only (no pygame), state.overlay = ("gallery", until, data).
"""

import os
import re
import time

from shared_state import state

STEP = 6.0           # the slideshow: seconds per picture
PAUSE = 30.0         # after a step by hand: on the screen this long
SLIDE = 0.35         # the slide from one picture to the next (ui_screens)

_MONTHS = ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
           "sierpnia", "września", "października", "listopada", "grudnia")


def when(path, now=None):
    """"20261014-173902.jpg" → "dziś, 17:39" / "wczoraj, 9:05" / "3 października"."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})", os.path.basename(path))
    if not m:
        return ""
    y, mo, d, hh, mm = (int(x) for x in m.groups())
    lt = time.localtime(now if now is not None else time.time())
    today = (lt.tm_year, lt.tm_mon, lt.tm_mday)
    yest = time.localtime(time.mktime(lt[:3] + (12, 0, 0, 0, 0, -1)) - 86400)[:3]
    if (y, mo, d) == today:
        return f"dziś, {hh}:{mm:02d}"
    if (y, mo, d) == tuple(yest):
        return f"wczoraj, {hh}:{mm:02d}"
    return f"{d} {_MONTHS[mo - 1]}" + (f" {y}" if y != lt.tm_year else "")


def show(items, title="", start=0, auto=True, secs=None):
    """items: [{"path", "caption", "sub"}], newest first. auto: a slideshow
    that closes after the last one; else it stands at `start` for `secs`."""
    if not items:
        return
    now = time.time()
    start = max(0, min(start, len(items) - 1))
    data = {"items": list(items), "i": start, "title": title, "auto": auto,
            "next": now + STEP, "t_nav": 0.0, "dir": 0, "from": None}
    until = now + ((len(items) - start) * STEP + 1 if auto else (secs or PAUSE))
    with state.lock:
        state.overlay = ("gallery", until, data)


def current():
    """The picture on the screen now ({"path", …}), from a gallery or a single
    photo; None without one."""
    with state.lock:
        ov = state.overlay
    if not ov or time.time() >= ov[1]:
        return None
    if ov[0] == "gallery":
        g = ov[2]
        return g["items"][g["i"]] if 0 <= g["i"] < len(g["items"]) else None
    if ov[0] == "photo":
        d = ov[2]
        return {"path": d} if isinstance(d, str) else d if isinstance(d, dict) else None
    return None


def _go(g, i, now):
    """To picture i (state.lock held)."""
    g["from"], g["dir"] = g["i"], (1 if i > g["i"] else -1)
    g["i"], g["t_nav"] = i, now


def step(delta, now=None):
    """By hand: delta +1 / -1, or "first" / "last". Returns "ok", "end" (no
    more that way), or None (no gallery on the screen)."""
    now = now if now is not None else time.time()
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "gallery" or now >= ov[1]:
            return None
        g = ov[2]
        n = len(g["items"])
        i = {"first": 0, "last": n - 1}.get(delta, g["i"] + (delta if isinstance(delta, int) else 0))
        g["auto"] = False                       # you are looking: no slideshow
        state.overlay = (ov[0], now + PAUSE, g)
        if not 0 <= i < n or i == g["i"]:
            return "end"
        _go(g, i, now)
    return "ok"


def tick(g, now):
    """The slideshow, once a frame (robot_face; state.lock held). False:
    it is over, close it."""
    if g.get("auto") and now >= g["next"]:
        if g["i"] + 1 >= len(g["items"]):
            return False
        _go(g, g["i"] + 1, now)
        g["next"] = now + STEP
    return True


def touch(kind, nx, ny, dx=0.0):
    """A touch on the gallery: "close" | "prev" | "next" | None (left alone).
    The ✕ top right closes; the sides (or a swipe) turn; the middle: next."""
    if kind == "swipe":
        return "next" if dx < 0 else "prev"
    if kind not in ("tap", "stop"):
        return None
    if nx > 0.86 and ny < 0.2:
        return "close"
    if nx < 0.22:
        return "prev"
    return "next"


def on_touch(kind, nx, ny, dx=0.0):
    what = touch(kind, nx, ny, dx)
    if what == "close":
        with state.lock:
            state.overlay = None
    elif what:
        if step(1 if what == "next" else -1) == "end" and what == "next":
            with state.lock:                    # past the last one: done
                state.overlay = None
    return what


# by voice, while the gallery is on the screen (a bare "dalej" means nothing
# without one: commands asks here first only then)
_NEXT = re.compile(r"^(?:luna,?\s+)?(?:(?:a\s+|i\s+|to\s+|pokaż\s+|pokaz\s+)?(?:następn\w*|nastepn\w*|"
                   r"kolejn\w*|dalej|dalsz\w*|next)|jeszcze\s+jedn\w*|przewiń|przewin)"
                   r"(?:\s+(?:zdjęcie|zdjecie|rysunek|obrazek|proszę|prosze|poproszę|poprosze))?\W*$", re.I)
_PREV = re.compile(r"^(?:luna,?\s+)?(?:(?:a\s+|pokaż\s+|pokaz\s+)?(?:poprzedni\w*|wcześniejsz\w*|"
                   r"wczesniejsz\w*|previous)|cofnij(?:\s+się|\s+sie)?|wstecz|do\s+tyłu|do\s+tylu|"
                   r"w\s+tył|w\s+tyl|back)"
                   r"(?:\s+(?:zdjęcie|zdjecie|rysunek|obrazek|proszę|prosze))?\W*$", re.I)
_FIRST = re.compile(r"^(?:luna,?\s+)?(?:pokaż\s+|pokaz\s+)?(?:pierwsz\w*|od\s+początku|"
                    r"od\s+poczatku|najnowsz\w*|ostatni\w*)(?:\s+(?:zdjęcie|zdjecie|rysunek))?\W*$", re.I)
# ("ostatnie zdjęcie" is the newest one: the first here)
_LAST = re.compile(r"^(?:luna,?\s+)?(?:pokaż\s+|pokaz\s+)?(?:najstarsz\w*)"
                   r"(?:\s+(?:zdjęcie|zdjecie|rysunek))?\W*$", re.I)


def voice(text, speak):
    """"Następne", "poprzednie", "pierwsze" with the gallery on — True if done."""
    with state.lock:
        ov = state.overlay
    if not ov or ov[0] != "gallery" or time.time() >= ov[1]:
        return False
    t = (text or "").strip()
    what = (1 if _NEXT.match(t) else -1 if _PREV.match(t) else
            "first" if _FIRST.match(t) else "last" if _LAST.match(t) else None)
    if what is None:
        return False
    got = step(what)
    if got == "end":
        speak("To już ostatnie." if what in (1, "last") else "To jest pierwsze.")
    print(f"[gallery] {what}: {got}", flush=True)
    return True
