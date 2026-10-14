"""
gallery.py — her photos, drawings and the people she knows, one at a time.

  "pokaż zdjęcia" / "pokaż rysunki"   → a slideshow, newest first, STEP s each
                                        (the first AUTO_MAX, then it stands)
  "kogo znasz?" / "pokaż osoby"       → the people she knows (screens.py)
  "następne" / "dalej" / "kolejne"    → the next one (the slideshow stops:
  "poprzednie" / "cofnij" / "wstecz"     you are looking — it stays PAUSE s)
  "pierwsze" / "najstarsze"           → the newest / the oldest
  "usuń to" / "zapomnij tę osobę"     → into the bin: "przywróć zdjęcie /
                                        rysunek / osobę" brings it back
  "zamknij" / "wróć do buzi"          → closed (commands.close_page)
  on the screen: ‹ › at the sides (or a swipe), ✕ in the corner, the bin
  next to it (tapped twice: "Usunąć?" first); a tap in the middle: next

While it is open she keeps listening (speech_to_text: page_open), so
"dalej" and "zamknij" need no "Luna" (14 Oct: the drawings ran on for two
minutes, every tap only turned the page, and "zamknij" wanted her name).
A photo just taken or a drawing just made opens here too, standing still,
so "poprzednie" goes back to the older ones. ui_screens.py draws it; this is
the logic only (no pygame), state.overlay = ("gallery", until, data).
"""

import os
import re
import time

from shared_state import state

STEP = 6.0           # the slideshow: seconds per picture
AUTO_MAX = 10        # …for this many, then it stands on the last one
PAUSE = 30.0         # after a step by hand: on the screen this long
SLIDE = 0.35         # the slide from one picture to the next (ui_screens)
CONFIRM = 4.0        # the bin tapped again within this: deleted
TOAST = 3.0

_MONTHS = ("stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
           "sierpnia", "września", "października", "listopada", "grudnia")


def when(path, now=None):
    """"20261014-173902.jpg" → "dziś, 17:39" / "wczoraj, 9:05" / "3 października"."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})", os.path.basename(path))
    if not m:
        return ""
    y, mo, d, hh, mm = (int(x) for x in m.groups())
    return day_word(y, mo, d, now) + (f", {hh}:{mm:02d}" if (y, mo, d) in _near(now) else "")


def _near(now=None):
    lt = time.localtime(now if now is not None else time.time())
    yest = time.localtime(time.mktime(lt[:3] + (12, 0, 0, 0, 0, -1)) - 86400)[:3]
    return {tuple(lt[:3]), tuple(yest)}


def day_word(y, mo, d, now=None):
    lt = time.localtime(now if now is not None else time.time())
    if (y, mo, d) == tuple(lt[:3]):
        return "dziś"
    yest = time.localtime(time.mktime(lt[:3] + (12, 0, 0, 0, 0, -1)) - 86400)[:3]
    if (y, mo, d) == tuple(yest):
        return "wczoraj"
    return f"{d} {_MONTHS[mo - 1]}" + (f" {y}" if y != lt.tm_year else "")


def show(items, title="", start=0, auto=True, secs=None):
    """items: [{"path", "caption", "sub", "kind", …}], newest first. auto: a
    slideshow; else it stands at `start` for `secs`."""
    if not items:
        return
    now = time.time()
    start = max(0, min(start, len(items) - 1))
    auto = auto and len(items) > 1
    data = {"items": list(items), "i": start, "title": title, "auto": auto,
            "next": now + STEP, "t_nav": 0.0, "dir": 0, "from": None, "shown": 1,
            "confirm": 0.0, "toast": None}
    until = now + (min(len(items) - start, AUTO_MAX) * STEP + PAUSE if auto else (secs or PAUSE))
    with state.lock:
        state.overlay = ("gallery", until, data)
        state.conversation_active = True          # "dalej", "zamknij" without "Luna"
        state.last_activity_time = max(state.last_activity_time, now)


def page_open(now=None):
    """A page you look through (the gallery, the weather) is on the screen."""
    with state.lock:
        ov = state.overlay
    return bool(ov and ov[0] in ("gallery", "weather")
                and (now if now is not None else time.time()) < ov[1])


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
    g["i"], g["t_nav"], g["confirm"] = i, now, 0.0


def _gallery_now(now):
    """(overlay, data) of the gallery on the screen (state.lock held), or (None, None)."""
    ov = state.overlay
    if not ov or ov[0] != "gallery" or now >= ov[1]:
        return None, None
    return ov, ov[2]


def step(delta, now=None):
    """By hand: delta +1 / -1, or "first" / "last". Returns "ok", "end" (no
    more that way), or None (no gallery on the screen)."""
    now = now if now is not None else time.time()
    with state.lock:
        ov, g = _gallery_now(now)
        if not g:
            return None
        n = len(g["items"])
        i = {"first": 0, "last": n - 1}.get(delta, g["i"] + (delta if isinstance(delta, int) else 0))
        g["auto"] = False                       # you are looking: no slideshow
        state.overlay = (ov[0], now + PAUSE, g)
        state.last_activity_time = max(state.last_activity_time, now)
        if not 0 <= i < n or i == g["i"]:
            return "end"
        _go(g, i, now)
    return "ok"


def tick(g, now):
    """The slideshow, once a frame (robot_face; state.lock held). False:
    it is over, close it."""
    if g.get("auto") and now >= g["next"]:
        if g["i"] + 1 >= len(g["items"]) or g.get("shown", 1) >= AUTO_MAX:
            g["auto"] = False                   # the end of the show: it stands
            ov = state.overlay
            if ov and ov[2] is g:
                state.overlay = (ov[0], now + PAUSE, g)
            return True
        _go(g, g["i"] + 1, now)
        g["next"] = now + STEP
        g["shown"] = g.get("shown", 1) + 1
    return True


# ── deleting: into a bin, never for good ─────────────────────────────────────

def _deleter(kind):
    """kind → (delete(item) → bool, what was deleted, how to get it back)."""
    if kind == "photo":
        import screens
        return screens.bin_photo, "zdjęcie", "przywróć zdjęcie"
    if kind == "drawing":
        import drawing
        return drawing.bin_drawing, "rysunek", "przywróć rysunek"
    if kind == "person":
        import faces
        return (lambda it: faces.forget(it["name"])), "osobę", "przywróć osobę"
    return None


def deletable(item):
    return bool(item) and item.get("kind") in ("photo", "drawing", "person")


def delete_current(now=None):
    """The one on the screen into the bin. Returns what to say (or show),
    None when there is nothing to delete."""
    now = now if now is not None else time.time()
    with state.lock:
        ov, g = _gallery_now(now)
        item = g["items"][g["i"]] if g and 0 <= g["i"] < len(g["items"]) else None
    if not deletable(item):
        return None
    fn, what, back = _deleter(item["kind"])
    try:
        ok = fn(item)
    except Exception as e:
        print(f"[gallery] delete failed: {e}", flush=True)
        ok = False
    if not ok:
        return "Nie udało się usunąć."
    print(f"[gallery] deleted {item['kind']}: {item.get('name') or item.get('path')}", flush=True)
    said = (f"Zapomniałam: {item['name']}." if item["kind"] == "person"
            else f"Usunęłam {what}.") + f" Gdyby co — powiedz: {back}."
    with state.lock:
        ov, g2 = _gallery_now(now)
        if g2 is g:
            g["items"] = [x for x in g["items"] if x is not item]
            if not g["items"]:
                state.overlay = None
            else:
                g["i"] = min(g["i"], len(g["items"]) - 1)
                g["from"], g["t_nav"], g["confirm"], g["auto"] = None, now, 0.0, False
                g["toast"] = (f"Usunięto · „{back}”", now + TOAST)
                state.overlay = (ov[0], now + PAUSE, g)
    return said


# ── touch ────────────────────────────────────────────────────────────────────

def touch(kind, nx, ny, dx=0.0, item=None):
    """A touch on the gallery: "close" | "delete" | "prev" | "next" | None.
    ✕ top right closes, the bin next to it deletes; the sides (or a swipe)
    turn; the middle: next."""
    if kind == "swipe":
        return "next" if dx < 0 else "prev"
    if kind not in ("tap", "stop"):
        return None
    if ny < 0.2 and nx > 0.905:
        return "close"
    if ny < 0.2 and nx > 0.78 and deletable(item):
        return "delete"
    if nx < 0.22:
        return "prev"
    return "next"


def on_touch(kind, nx, ny, dx=0.0):
    now = time.time()
    with state.lock:
        ov, g = _gallery_now(now)
        item = g["items"][g["i"]] if g else None
    what = touch(kind, nx, ny, dx, item)
    if what:
        print(f"[gallery] touch {kind} ({nx:.2f}, {ny:.2f}) → {what}", flush=True)
    if what == "close":
        with state.lock:
            state.overlay = None
    elif what == "delete":
        with state.lock:
            first = now - g["confirm"] > CONFIRM
            if first:                            # "Usunąć?" — tap it again
                g["confirm"] = now
                state.overlay = (ov[0], now + PAUSE, g)
        if not first:
            delete_current(now)
    elif what:
        if step(1 if what == "next" else -1) == "end" and what == "next":
            with state.lock:                    # past the last one: done
                state.overlay = None
    return what


# ── by voice, while the gallery is on the screen (a bare "dalej" means nothing
# without one: commands asks here first only then) ──────────────────────────
_NEXT = re.compile(r"^(?:luna,?\s+)?(?:(?:a\s+|i\s+|to\s+|pokaż\s+|pokaz\s+)?(?:następn\w*|nastepn\w*|"
                   r"kolejn\w*|dalej|dalsz\w*|next)|jeszcze\s+jedn\w*|przewiń|przewin)"
                   r"(?:\s+(?:zdjęcie|zdjecie|rysunek|obrazek|osob\w+|proszę|prosze|poproszę|poprosze))?\W*$", re.I)
_PREV = re.compile(r"^(?:luna,?\s+)?(?:(?:a\s+|pokaż\s+|pokaz\s+)?(?:poprzedni\w*|wcześniejsz\w*|"
                   r"wczesniejsz\w*|previous)|cofnij(?:\s+się|\s+sie)?|wstecz|do\s+tyłu|do\s+tylu|"
                   r"w\s+tył|w\s+tyl|back)"
                   r"(?:\s+(?:zdjęcie|zdjecie|rysunek|obrazek|osob\w+|proszę|prosze))?\W*$", re.I)
_FIRST = re.compile(r"^(?:luna,?\s+)?(?:pokaż\s+|pokaz\s+)?(?:pierwsz\w*|od\s+początku|"
                    r"od\s+poczatku|najnowsz\w*|ostatni\w*)(?:\s+(?:zdjęcie|zdjecie|rysunek))?\W*$", re.I)
# ("ostatnie zdjęcie" is the newest one: the first here)
_LAST = re.compile(r"^(?:luna,?\s+)?(?:pokaż\s+|pokaz\s+)?(?:najstarsz\w*)"
                   r"(?:\s+(?:zdjęcie|zdjecie|rysunek))?\W*$", re.I)
_DELETE = re.compile(r"^(?:luna,?\s+)?(?:(?:usuń|usun|skasuj|wyrzuć|wyrzuc|wykasuj)(?:\s+(?:to|go|ją|ja|"
                     r"tego|tę|te|ten|tą))?(?:\s+(?:zdjęcie|zdjecie|rysunek|obrazek|osobę|osobe|"
                     r"fotkę|fotke|twarz))?|zapomnij\s+(?:o\s+)?(?:tę|te|tą|ta|tej|tego|ją|ja|jego|go)"
                     r"(?:\s+(?:osobę|osobe|osoby|twarz|człowieka|czlowieka))?)\W*$", re.I)


# "Tylko te?", "To wszystkie?", "Ile ich jest?" (14 Oct: "Tylko te?" with her
# 3 photos on → the model: "Nie, nie tylko te — mogę pokazać inne")
_HOW_MANY = re.compile(r"^(?:luna,?\s+)?(?:a\s+|i\s+)?(?:(?:tylko|to)\s+(?:te|tyle|tyle\s+ich|"
                       r"wszystk\w+|wszystko|jedno|jeden)|ile\s+(?:ich|jest|masz)(?:\s+\w+)?|"
                       r"więcej\s+nie\s+ma|wiecej\s+nie\s+ma|nie\s+masz\s+więcej|nie\s+masz\s+wiecej)"
                       r"(?:\s+(?:zdjęć|zdjec|rysunków|rysunkow|osób|osob))?\W*$", re.I)
_KIND_N = {"photo": ("zdjęcie", "zdjęcia", "zdjęć"), "drawing": ("rysunek", "rysunki", "rysunków"),
           "person": ("osobę", "osoby", "osób")}


def voice(text, speak):
    """"Następne", "poprzednie", "usuń to" with the gallery on — True if done."""
    if not page_open() or not current():
        return False
    with state.lock:
        if state.overlay[0] != "gallery":
            return False
    t = (text or "").strip()
    if _HOW_MANY.match(t):
        import calc
        with state.lock:
            g = state.overlay[2]
            n, kind = len(g["items"]), (g["items"][0].get("kind") if g["items"] else None)
        forms = _KIND_N.get(kind, ("obrazek", "obrazki", "obrazków"))
        said = f"{'znam' if kind == 'person' else 'mam'} {n} {calc._plural(n, *forms)}."
        speak(f"Tak, {said}" if re.match(r"(?:luna,?\s+)?(?:a\s+|i\s+)?(?:tylko|to)\b", t, re.I)
              else said.capitalize())
        return True
    if _DELETE.match(t):
        said = delete_current()
        speak(said or "Tego nie mogę usunąć.")
        return True
    what = (1 if _NEXT.match(t) else -1 if _PREV.match(t) else
            "first" if _FIRST.match(t) else "last" if _LAST.match(t) else None)
    if what is None:
        return False
    got = step(what)
    if got == "end":
        speak("To już ostatnie." if what in (1, "last") else "To jest pierwsze.")
    print(f"[gallery] {what}: {got}", flush=True)
    return True


# "przywróć rysunek" / "przywróć osobę" — any time (photos: screens.py)
_RESTORE = re.compile(r"^(?:luna,?\s+)?(?:przywróć|przywroc|odzyskaj|cofnij\s+usunięcie)\s+"
                      r"(?:to\s+|ten\s+|tę\s+|te\s+|ostatni\w*\s+)?"
                      r"(rysunek|obrazek|osobę|osobe|twarz)\W*$", re.I)


def restore_voice(text, speak):
    m = _RESTORE.match((text or "").strip())
    if not m:
        return False
    if m.group(1).lower() in ("rysunek", "obrazek"):
        import drawing
        got = drawing.restore_drawing()
        speak("Proszę, wrócił." if got else "Nie mam czego przywrócić.")
        if got:
            drawing.show_one(got)
    else:
        import faces
        name = faces.restore()
        speak(f"Dobrze, znowu pamiętam: {name}." if name else "Nikogo nie zapomniałam.")
    return True
