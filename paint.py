"""
paint.py — Malowanie: a sheet to paint on with a finger, and with Luna.

The page (the dock's brush icon, "otwórz malowanie", "chcę malować"): the
sheet on the left, the tools on the right — colours, brush (tap again: a
bigger one), eraser, "Pokaż" (tap or circle what Luna should change: red
marks, not paint), undo, a new sheet, open a picture (her drawings, saved
sheets, photos), save, print, "Powiedz" (she listens, like a held finger).

Voice while it is up:
  "narysuj arkusz A4 z uroczymi zwierzątkami i ubrankami do przebierania"
                                → a new picture (A4 portrait; "poziomo")
  "dodaj kotu kapelusz", "zmień tło na niebieskie", "zrób go większym",
  "tego nie chcę" (with marks)  → the picture changed; with marks only there
                                  (the rest is pasted back as it was)
  "zrób z mojego rysunku ładny obrazek" → her version of the finger drawing
  "cofnij", "nowa kartka", "zapisz", "wydrukuj (czarno-biało, dwa razy)"
  With a drawing or photo on the screen: "popraw ten rysunek: dodaj tęczę",
  "otwórz to w malowaniu".

Touch: touch_module hands every raw finger event here while the page is up
(raw), so a stroke paints instead of petting her. Drawn by
ui_screens.draw_paint from view(). The sheet lives at data/paint/current.png
(saved a moment after each change); "zapisz" keeps a copy in data/paint/saved
(never pruned). Pure logic + PIL here, no pygame: the unit tests read it.
"""

import base64
import io
import json
import math
import os
import re
import threading
import time

from config import DATA_DIR, PHOTOS_DIR, SCREEN_WIDTH, SCREEN_HEIGHT
from shared_state import state

DIR = os.path.join(DATA_DIR, "paint")
CURRENT = os.path.join(DIR, "current.png")
SAVED = os.path.join(DIR, "saved")
MODEL = "gpt-image-1-mini"
QUALITY = "medium"                 # printed on A4: "low" was blotchy at that size
PER_DAY = 40                       # pictures made or changed by the model, a day
PAGE_SECS = 1800                   # the page stays up this long untouched
UNDO = 40                          # steps back ("Cofnij"); a stroke keeps only its own patch
UNDO_PIXELS = 12_000_000           # …and all of them together at most this much (~36 MB)
SIZES = {"portrait": (1024, 1536), "landscape": (1536, 1024), "square": (1024, 1024)}

W, H = SCREEN_WIDTH, SCREEN_HEIGHT
BOX = (8, 8, W - 184, H - 16)      # where the sheet goes (x, y, w, h)
TB = W - 168                       # the toolbar's left edge
COLOURS = ((25, 25, 30), (230, 57, 70), (247, 140, 40), (250, 210, 50),
           (70, 180, 90), (60, 120, 220), (150, 90, 210), (240, 120, 170))
BRUSH = (4, 10, 22)                # px on the screen
MARK_R = 30                        # a tap with "Pokaż": a circle this big on the screen
MARK_COL = (255, 40, 60)

_lock = threading.RLock()
_s = {"img": None, "ver": 0, "view": None, "undo": [], "tool": "brush", "colour": 0,
      "size": 1, "marks": [], "stroke": None, "busy": None, "busy_t": 0.0, "hint": "",
      "picker": None, "page": 0, "title": "", "down": None, "saved_ver": -1,
      "asked_t": 0.0, "touch_t": 0.0}
TALK_SECS = 120          # a wish with no command word counts this long after a touch / her question
_s.update(paper="landscape", photo=False)   # how new sheets lie ("Obróć" changes it); a photo on it
_s.update(camera=None, flash_t=0.0)          # "Zdjęcie": the countdown on the live camera ("" before it)
COUNT_SECS = 0.9
_s.update(confirm=None, confirm_t=0.0, printing=False, printed_t=0.0, kept_ver=-1)
CONFIRM_SECS = 4.0       # "Nowa", "Drukuj", "Upiększ": a second tap this soon does it
CONFIRM = {"new": "Nowa kartka? Dotknij „Nowa” jeszcze raz",
           "print": "Wydrukować? Dotknij „Drukuj” jeszcze raz",
           "beautify": "Upiększyć? Dotknij „Upiększ” jeszcze raz"}
PRINT_COOL = 20.0        # "Drukuj" rests this long after a page went to the printer
SLOW = ("save", "print", "beautify", "photo")   # buttons that run on their own thread
_running = set()         # …whose work is still going: a tap on them again waits (lock held)
_save_timer = [None]
_save_lock = threading.Lock()   # one writer of current.png at a time


# ── layout ───────────────────────────────────────────────────────────────────

def buttons():
    """[(key, (x, y, w, h))] — the toolbar."""
    out = [("talk", (TB, 8, 76, 48)), ("close", (TB + 84, 8, 76, 48))]
    for i in range(len(COLOURS)):
        out.append((f"c{i}", (TB + (i % 4) * 41, 66 + (i // 4) * 41, 36, 36)))
    rows = (("brush", "eraser"), ("mark", "undo"), ("beautify", "rotate"), ("new", "photo"),
            ("open", "save"), ("print", None))
    for r, (a, b) in enumerate(rows):
        y = 148 + r * 46
        out.append((a, (TB, y, 76 if b else 160, 40)))
        if b:
            out.append((b, (TB + 84, y, 76, 40)))
    return out


HINT = (TB, 426, 160, H - 430)     # a line of help / what she is doing


def canvas_rect(size):
    """Where a picture of this size sits on the screen: (x, y, w, h, scale)."""
    bx, by, bw, bh = BOX
    k = min(bw / size[0], bh / size[1])
    w, h = int(size[0] * k), int(size[1] * k)
    return bx + (bw - w) // 2, by + (bh - h) // 2, w, h, k


def picker_cells():
    """The picture picker's 4 × 2 cells in the sheet's box."""
    bx, by, bw, bh = BOX
    cw, ch = (bw - 3 * 8) / 4, (bh - 8) / 2
    return [(int(bx + c * (cw + 8)), int(by + r * (ch + 8)), int(cw), int(ch))
            for r in range(2) for c in range(4)]


def _inside(p, r):
    return r[0] <= p[0] < r[0] + r[2] and r[1] <= p[1] < r[1] + r[3]


def button_at(x, y):
    return next((k for k, r in buttons() if _inside((x, y), r)), None)


# ── the page ─────────────────────────────────────────────────────────────────

def active(now=None):
    with state.lock:
        ov = state.overlay
    return bool(ov and ov[0] == "paint" and (now or time.time()) < ov[1])


def _show():
    with state.lock:
        state.overlay = ("paint", time.time() + PAGE_SECS, None)


def _keep_up():
    with state.lock:
        ov = state.overlay
        if ov and ov[0] == "paint":
            state.overlay = ("paint", time.time() + PAGE_SECS, None)


def close():
    with state.lock:
        if state.overlay and state.overlay[0] == "paint":
            state.overlay = None
    with _lock:
        _s["picker"], _s["stroke"], _s["down"] = None, None, None
    _flush()


def open_page(hint=None):
    """Open the sheet (the last one, else a clean A4)."""
    with _lock:
        broken = _s["img"] is None and _load()
        _s["picker"] = None
        _s["asked_t"] = time.time()
        _s["hint"] = hint if hint is not None else (
            "" if _s["busy"] else "Poprzedni obrazek się zepsuł — oto czysta kartka" if broken
            else "Maluj palcem albo naciśnij „Powiedz” i powiedz, co narysować")
    _show()
    print("[paint] page open", flush=True)


def _blank(kind="landscape"):
    from PIL import Image
    return Image.new("RGB", SIZES[kind], (255, 255, 255))


def _load():
    """The sheet from last time (lock held); True when it was broken (kept aside)."""
    from PIL import Image
    img, broken = None, False
    try:
        with Image.open(CURRENT) as f:
            img = f.convert("RGB")
    except FileNotFoundError:
        pass
    except Exception as e:       # (PIL calls a broken PNG a SyntaxError — 26 Oct: the page never opened)
        aside = os.path.join(DIR, time.strftime("broken-%Y%m%d-%H%M%S.png"))
        print(f"[paint] the sheet is broken ({e!r}) — kept as {aside}, a clean one", flush=True)
        broken = True
        try:
            os.replace(CURRENT, aside)
        except OSError:
            pass
    _set(img or _blank(), push=False)
    try:
        with open(CURRENT[:-4] + ".json", encoding="utf-8") as f:
            _s["title"] = json.load(f).get("title", "")
    except (OSError, ValueError):
        pass
    _s["saved_ver"] = _s["ver"]
    return broken


def _set(img, push=True, title=None):
    """A new picture on the sheet (lock held); the old one can be undone."""
    if push and _s["img"] is not None:
        _push_undo({"img": _s["img"], "title": _s["title"]})
    _s["img"] = img
    if title is not None:
        _s["title"] = title
    _s["marks"] = []
    _changed()


def _changed():
    """The picture changed (lock held): a new view, saved in a moment."""
    from PIL import Image
    _s["ver"] += 1
    x, y, w, h, _k = canvas_rect(_s["img"].size)
    _s["view"] = _s["img"].resize((w, h), Image.BILINEAR)
    if _save_timer[0] is None:
        t = threading.Timer(2.0, _flush)
        t.daemon = True
        _save_timer[0] = t
        t.start()


def _push_undo(entry):
    """(lock held) {"img", "title"} — the whole picture, or {"box", "crop", "title"} —
    only what a stroke covered. The oldest go past UNDO steps or UNDO_PIXELS."""
    u = _s["undo"]
    u.append(entry)

    def px(e):
        im = e.get("img") or e.get("crop")
        return im.width * im.height
    total = sum(px(e) for e in u)
    while len(u) > 1 and (len(u) > UNDO or total > UNDO_PIXELS):
        total -= px(u.pop(0))


def _atomic(path, write):
    """write(f) into a file beside path, then swap it in: never half a file."""
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        with open(tmp, "wb") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _flush():
    """Write the sheet to disk if it changed. One writer at a time (26 Oct: the
    timer's write and close()'s met in one .tmp — a broken current.png)."""
    with _save_lock:
        with _lock:
            _save_timer[0] = None
            if _s["img"] is None or _s["saved_ver"] == _s["ver"]:
                return
            img, title, ver = _s["img"].copy(), _s["title"], _s["ver"]
        try:
            os.makedirs(DIR, exist_ok=True)
            _atomic(CURRENT, lambda f: img.save(f, "PNG"))
            _atomic(CURRENT[:-4] + ".json",
                    lambda f: f.write(json.dumps({"title": title}, ensure_ascii=False).encode()))
            with _lock:
                _s["saved_ver"] = max(_s["saved_ver"], ver)
        except Exception as e:
            print(f"[paint] couldn't save the sheet: {e!r}", flush=True)


def view():
    """A snapshot for the drawing: everything ui_screens.draw_paint needs."""
    with _lock:
        if _s["img"] is None:
            _load()
        x, y, w, h, k = canvas_rect(_s["img"].size)
        st = _s["stroke"]
        confirm = _confirming()
        return {"ver": _s["ver"], "view": _s["view"], "rect": (x, y, w, h), "k": k,
                "tool": _s["tool"], "colour": _s["colour"], "size": _s["size"],
                "marks": [dict(m, pts=list(m["pts"])) for m in _s["marks"]],
                "stroke": dict(st, pts=list(st["pts"])) if st else None,
                "busy": _s["busy"], "busy_t": _s["busy_t"],
                "hint": CONFIRM[confirm] if confirm else _s["hint"], "confirm": confirm,
                "printing": _print_resting(), "running": sorted(_running),
                "undo_n": len(_s["undo"]),
                "picker": _picker_page() if _s["picker"] is not None else None,
                "undo": bool(_s["undo"]), "down": _s["down"],
                "wide": _s["img"].width > _s["img"].height, "voice": voice_state(),
                "camera": _s["camera"], "flash_t": _s["flash_t"]}


def _hint(text):
    with _lock:
        _s["hint"] = text


def _confirming(now=None):
    """The button waiting for its second tap, or None (lock held)."""
    c = _s["confirm"]
    return c if c and (now or time.time()) - _s["confirm_t"] < CONFIRM_SECS else None


def _print_resting(now=None):
    """Printing, or a page just went out: "Drukuj" waits (lock held). 26 Oct:
    Maja tapped it 20 times, 20 threads on one file, a Bus error."""
    return _s["printing"] or (now or time.time()) - _s["printed_t"] < PRINT_COOL


# ── the finger ───────────────────────────────────────────────────────────────

def _to_img(x, y):
    """Screen px → picture px (lock held)."""
    cx, cy, cw, ch, k = canvas_rect(_s["img"].size)
    return ((x - cx) / k, (y - cy) / k)


def raw(phase, nx, ny):
    """A finger event from touch_module while the page is up: "down", "move", "up"."""
    x, y = nx * W, ny * H
    _keep_up()
    with _lock:
        _s["touch_t"] = time.time()
        if _s["img"] is None:
            _load()
        if phase == "down":
            cx, cy, cw, ch, k = canvas_rect(_s["img"].size)
            on_sheet = _inside((x, y), (cx, cy, cw, ch))
            if on_sheet and _s["picker"] is None:
                _s["confirm"] = None                    # (painting on: not "na pewno?")
                tool = _s["tool"]
                r = (MARK_R if tool == "mark" else
                     BRUSH[_s["size"]] * (1.8 if tool == "eraser" else 1.0) / 2) / k
                _s["stroke"] = {"tool": tool, "pts": [_to_img(x, y)], "r": r,
                                "colour": (255, 255, 255) if tool == "eraser"
                                else COLOURS[_s["colour"]]}
            else:
                _s["down"] = button_at(x, y) or ("pick", x, y)
            return
        st = _s["stroke"]
        if phase == "move":
            if st:
                p = _to_img(x, y)
                q = st["pts"][-1]
                if abs(p[0] - q[0]) + abs(p[1] - q[1]) >= 2 / canvas_rect(_s["img"].size)[4]:
                    st["pts"].append(p)
            return
        # up
        _s["stroke"] = None
        down, _s["down"] = _s["down"], None
        if st:
            if st["tool"] == "mark":
                _s["marks"].append({"pts": st["pts"], "r": st["r"]})
                _s["hint"] = "Powiedz, co tu zmienić — albo „tego nie chcę”"
                _s["ver"] += 1
            else:
                _paint(st)
            return
    if down:
        key = down if isinstance(down, str) else None
        if key and button_at(x, y) == key:
            tapped(key)
        elif not key:
            _pick_at(x, y)


def tapped(key):
    """A toolbar tap: "Nowa", "Drukuj", "Upiększ" ask for a second tap first;
    the slow ones run on their own thread (she talks), one at a time each."""
    now = time.time()
    with _lock:
        armed = _confirming(now) == key
        _s["confirm"] = None
        if key in _running or (key == "print" and _print_resting(now)):
            _s["hint"] = "Już drukuję — chwileczkę" if key == "print" else "Chwileczkę…"
            print(f"[paint] button {key} — still busy, ignored", flush=True)
            return False
        blank = _s["img"] is not None and _is_blank(_s["img"])
        if key in CONFIRM and not armed and not (key == "new" and blank):
            _s["confirm"], _s["confirm_t"] = key, now
            print(f"[paint] button {key} — once more to do it", flush=True)
            return False
        slow = key in SLOW
        if slow:
            _running.add(key)
    if slow:
        threading.Thread(target=_press_bg, args=(key,), daemon=True, name="paint-btn").start()
    else:
        press(key)
    return True


def _press_bg(key):
    try:
        press(key)
    except Exception as e:
        print(f"[paint] button {key} failed: {e!r}", flush=True)
    finally:
        with _lock:
            _running.discard(key)


def _paint(st):
    """A finished stroke into the picture (lock held)."""
    from PIL import ImageDraw
    img, pts, r = _s["img"], st["pts"], st["r"]
    pad = r + 3
    box = (max(0, int(min(p[0] for p in pts) - pad)), max(0, int(min(p[1] for p in pts) - pad)),
           min(img.width, int(max(p[0] for p in pts) + pad) + 1),
           min(img.height, int(max(p[1] for p in pts) + pad) + 1))
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    _push_undo({"box": box, "crop": img.crop(box), "title": _s["title"]})
    d = ImageDraw.Draw(img)
    if len(pts) > 1:
        d.line(pts, fill=st["colour"], width=max(1, int(2 * r)), joint="curve")
    for p in (pts[0], pts[-1]) if len(pts) > 1 else pts:     # round ends; a tap: a dot
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=st["colour"])
    _changed()


def press(key):
    """A toolbar button."""
    print(f"[paint] button {key}", flush=True)
    if key == "close":
        with _lock:
            if _s["picker"] is not None:
                _s["picker"] = None
                return
        close()
    elif key == "talk":
        if voice_state() == "listening":
            stop_listening()
        else:
            listen()
    elif key == "rotate":
        rotate()
    elif key == "beautify":
        _start("beautify", "upiększ", _say)
    elif key == "photo":
        take_photo(_say)
    elif key.startswith("c") and key[1:].isdigit():
        with _lock:
            _s["colour"] = int(key[1:])
            if _s["tool"] != "brush":
                _s["tool"] = "brush"
    elif key in ("brush", "eraser"):
        with _lock:
            if _s["tool"] == key:
                _s["size"] = (_s["size"] + 1) % len(BRUSH)
            _s["tool"] = key
    elif key == "mark":
        with _lock:
            if _s["tool"] == "mark" and _s["marks"]:
                _s["marks"] = []                       # again: the marks go
                _s["hint"] = "Zaznaczenia usunięte"
            else:
                _s["tool"] = "mark"
                _s["hint"] = "Dotknij albo obrysuj to, co Luna ma zmienić"
            _s["ver"] += 1
    elif key == "undo":
        undo()
    elif key == "new":
        new_sheet()
    elif key == "open":
        with _lock:
            if _s["picker"] is None:
                _s["picker"], _s["page"] = _openable(), 0
            elif len(_s["picker"]) > 8:            # the next eight
                _s["page"] = (_s["page"] + 1) % math.ceil(len(_s["picker"]) / 8)
            else:
                _s["picker"] = None
    elif key == "save":
        save(_say)
    elif key == "print":
        print_sheet(_say)


def _say(text):
    try:
        from text_to_speech import speak
        speak(text)
    except Exception as e:
        print(f"[paint] couldn't say {text!r}: {e!r}", flush=True)


def listen():
    """"Powiedz": she listens, as for a held finger (idle_engine says "hm?";
    while she talks or thinks the touch cuts in the same way)."""
    import touch_module
    with state.lock:
        state.last_activity_time = time.time()     # (a fresh window to speak in)
    touch_module._publish("hold", 0.5, 0.5)
    _hint("Słucham — powiedz, co narysować albo zmienić")


def stop_listening():
    """"Słucham" tapped: she stops listening now ("Luna" still wakes her). 26 Oct:
    the window stayed open and the room's talk became edits — no way to stop it."""
    with state.lock:
        state.conversation_active = False
        state.convo_expired_time = time.time()
        state.convo_closed_hard = True
        state.listening = False
    try:
        from text_to_speech import play_sound_async
        play_sound_async("tick")
    except Exception as e:
        print(f"[paint] no sound: {e!r}", flush=True)
    _hint("Nie słucham. Naciśnij „Powiedz”, żeby mówić")
    print("[paint] stopped listening", flush=True)


def voice_state():
    """What the "Powiedz" button shows: "speaking" | "thinking" | "listening" | None."""
    with state.lock:
        if state.speaking:
            return "speaking"
        if state.luna_mode == "processing":
            return "thinking"
        muted = time.time() < state.mic_muted_until
        return "listening" if (state.conversation_active or state.listening) and not muted \
            else None


def take_photo(speak):
    """"Zdjęcie": the live camera on the sheet, 3-2-1, the photo onto the sheet
    (and kept with the other photos, like "zrób mi zdjęcie")."""
    with state.lock:
        frame, ok = state.frame, state.camera_ok
        off = time.time() < getattr(state, "camera_off_until", 0.0)
    if off:
        speak("Kamera jest teraz wyłączona. Powiedz: włącz kamerę.")
        return True
    if frame is None or not ok:
        speak("Ojej, nie widzę nic przez kamerę.")
        return True
    with _lock:
        if _s["busy"] or _s["camera"] is not None:
            return True
        _s["camera"], _s["picker"] = "", None
        _s["hint"] = "Uśmiech! Patrz w kamerę"
    if not active():
        open_page("Uśmiech! Patrz w kamerę")
    try:
        from text_to_speech import play_sound_async
    except Exception:
        play_sound_async = None
    try:
        speak("Uśmiech! Patrz w kamerę.")
        for n in ("3", "2", "1"):
            with _lock:
                _s["camera"] = n
            _keep_up()
            if play_sound_async:
                play_sound_async("tick")
            time.sleep(COUNT_SECS)
        with state.lock:
            frame = state.frame
        if frame is None:
            speak("Ojej, nie widzę nic przez kamerę.")
            return True
        import screens
        path, names = screens.save_frame(frame)
        with _lock:
            _s["flash_t"] = time.time()
    finally:
        with _lock:
            _s["camera"] = None
    open_picture(path, "zdjęcie")
    _hint("Maluj po zdjęciu, „Upiększ” albo powiedz, co zmienić")
    with _lock:
        _s["asked_t"] = time.time()
    speak("Mam! Możesz po nim malować albo naciśnij Powiedz i powiedz, co zmienić.")
    return True


def orientation(img):
    return "landscape" if img.width > img.height else "portrait"


def rotate():
    """The paper turned a quarter (what is on it turns with it); undo turns it back."""
    from PIL import Image
    with _lock:
        if _s["img"] is None:
            _load()
        _set(_s["img"].transpose(Image.ROTATE_90))
        _s["paper"] = orientation(_s["img"])         # new sheets lie this way from now on
        _s["hint"] = "Kartka poziomo" if _s["paper"] == "landscape" else "Kartka pionowo"
    print(f"[paint] rotated → {_s['img'].size}", flush=True)
    return True


def undo():
    with _lock:
        if _s["marks"]:
            _s["marks"] = []
            _s["ver"] += 1
            return True
        if not _s["undo"]:
            _s["hint"] = "Nie ma czego cofnąć"
            return False
        e = _s["undo"].pop()
        if "box" in e:                          # a stroke: only its patch goes back
            _s["img"].paste(e["crop"], e["box"][:2])
        else:
            _s["img"] = e["img"]
        _s["title"] = e["title"]
        _s["marks"] = []
        _changed()
        n = len(_s["undo"])
        _s["hint"] = f"Cofnięte — jeszcze {n} do cofnięcia" if n else "Cofnięte — to już wszystko"
    return True


def new_sheet(kind=None):
    """A clean sheet: landscape, unless turned with "Obróć" or told."""
    with _lock:
        _set(_blank(kind or _s["paper"]), title="")
        _s["photo"] = False
        _s["picker"] = None
        _s["asked_t"] = time.time()
        _s["hint"] = "Nowa kartka"


# ── pictures to open ─────────────────────────────────────────────────────────

def saved_works():
    try:
        return sorted((os.path.join(SAVED, f) for f in os.listdir(SAVED) if f.endswith(".png")),
                      reverse=True)
    except OSError:
        return []


def _openable():
    """Saved sheets, her drawings and the photos, newest first."""
    import drawing
    paths = saved_works() + drawing.saved()
    try:
        paths += [os.path.join(PHOTOS_DIR, f) for f in os.listdir(PHOTOS_DIR)
                  if f.endswith(".jpg")]
    except OSError:
        pass

    def when(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0
    return sorted(paths, key=when, reverse=True)[:48]


def _picker_page():
    pics = _s["picker"] or []
    return {"paths": pics[_s["page"] * 8:_s["page"] * 8 + 8], "page": _s["page"],
            "pages": max(1, math.ceil(len(pics) / 8))}


def _pick_at(x, y):
    with _lock:
        if _s["picker"] is None:
            return
        paths = _picker_page()["paths"]
    for path, cell in zip(paths, picker_cells()):
        if _inside((x, y), cell):
            open_picture(path)
            return


def open_picture(path, title=""):
    """A drawing or photo onto the sheet (no bigger than the model's sizes)."""
    from PIL import Image
    try:
        with Image.open(path) as f:
            img = f.convert("RGB")
    except Exception as e:                  # (a broken PNG is a SyntaxError)
        print(f"[paint] couldn't open {path}: {e!r}", flush=True)
        _hint("Nie udało się otworzyć obrazka")
        return False
    k = min(1.0, 1536 / max(img.size))
    if k < 1.0:
        img = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
    with _lock:
        _set(img, title=title)
        _s["photo"] = path.lower().endswith((".jpg", ".jpeg"))   # (camera shots; drawings are .png)
        _s["picker"] = None
        _s["hint"] = "Maluj albo powiedz, co zmienić"
    print(f"[paint] opened {path}", flush=True)
    return True


# ── save, print ──────────────────────────────────────────────────────────────

def save(speak):
    with _lock:
        if _s["img"] is None:
            _load()
        if _s["kept_ver"] == _s["ver"]:         # (26 Oct: two taps, two same files)
            _s["hint"] = "Już zapisane — „Otwórz” je pokaże"
            speak("Ten obrazek już jest zapisany.")
            return True
        img, title, ver = _s["img"].copy(), _s["title"], _s["ver"]
    try:
        os.makedirs(SAVED, exist_ok=True)
        stem = os.path.join(SAVED, time.strftime("%Y%m%d-%H%M%S"))
        path = next(p for p in (stem + s + ".png" for s in ("", "-2", "-3", "-4", "-5", "-6"))
                    if not os.path.exists(p))
        _atomic(path, lambda f: img.save(f, "PNG"))
        _keep_title(path, title)
    except Exception as e:
        print(f"[paint] save failed: {e!r}", flush=True)
        speak("Nie udało mi się zapisać obrazka.")
        return True
    with _lock:
        _s["kept_ver"] = ver
    print(f"[paint] saved {path}", flush=True)
    _hint("Zapisane — „Otwórz” je pokaże")
    speak("Zapisane! Znajdziesz je pod przyciskiem Otwórz.")
    return True


def _keep_title(path, title):
    tp = os.path.join(SAVED, "titles.json")
    try:
        with open(tp, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d[os.path.basename(path)] = title
    try:
        _atomic(tp, lambda f: f.write(json.dumps(d, ensure_ascii=False).encode()))
    except OSError:
        pass


def print_pages(mono=False):
    """The sheet on A4 (a wide picture turned to fill the page). In memory: 26 Oct
    every tap wrote one shared /tmp file while another read it — a broken PNG."""
    import printer
    with _lock:
        if _s["img"] is None:
            _load()
        img = _s["img"].copy()
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    return printer.image_page(img, "", mono)


def print_sheet(speak, copies=1, mono=False):
    """One print at a time: asked again meanwhile, she says she is on it."""
    import printer
    with _lock:
        busy = _s["printing"]
        _s["printing"] = True
    if busy:
        speak("Już drukuję — chwileczkę.")
        return True
    sent = False
    try:
        _hint("Drukuję…")
        pages = print_pages(mono)
        job, err = printer.submit(pages, "Malowanie", copies, mono)
        sent = bool(job)
        _hint("Wysłane do drukarki" if sent else "Nie wydrukowało się")
        speak(err or "Drukuję obrazek" + (f" {copies} razy." if copies > 1 else "."))
    except Exception as e:
        print(f"[paint] print failed: {e!r}", flush=True)
        _hint("Nie wydrukowało się")
        speak("Nie udało mi się przygotować wydruku.")
    finally:
        with _lock:
            _s["printing"] = False
            if sent:
                _s["printed_t"] = time.time()
    return True


# ── marks → the model's mask ─────────────────────────────────────────────────

def _draw_marks(d, marks, k=1.0, off=(0, 0), grow=1.0, fill=0):
    """Marks drawn into a PIL image: thick lines, dots, a filled loop."""
    for m in marks:
        pts = [(off[0] + p[0] * k, off[1] + p[1] * k) for p in m["pts"]]
        r = m["r"] * k * grow
        if len(pts) > 1:
            d.line(pts, fill=fill, width=max(1, int(2 * r)), joint="curve")
            span = max(math.dist(pts[0], p) for p in pts)
            if len(pts) >= 6 and math.dist(pts[0], pts[-1]) < max(3 * r, span / 3):
                d.polygon(pts, fill=fill)          # circled: the inside too
        for p in pts:
            d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=fill)


def model_frame(size):
    """The model's size for a picture this size, and where it sits in it
    (padded, not cropped): ((tw, th), (ox, oy, w, h))."""
    a = size[0] / size[1]
    tw, th = min(SIZES.values(), key=lambda s: abs(math.log(s[0] / s[1] / a)))
    k = min(tw / size[0], th / size[1])
    w, h = round(size[0] * k), round(size[1] * k)
    return (tw, th), ((tw - w) // 2, (th - h) // 2, w, h)


def model_inputs(img, marks):
    """(picture PNG, mask PNG or None, frame) for images.edit."""
    from PIL import Image, ImageDraw
    (tw, th), (ox, oy, w, h) = model_frame(img.size)
    pad = Image.new("RGB", (tw, th), (255, 255, 255))
    pad.paste(img.resize((w, h), Image.LANCZOS), (ox, oy))
    mask = None
    if marks:
        m = Image.new("RGBA", (tw, th), (0, 0, 0, 255))     # opaque: keep
        _draw_marks(ImageDraw.Draw(m), marks, w / img.width, (ox, oy), 1.15, (0, 0, 0, 0))
        mask = _png(m)
    return _png(pad), mask, ((tw, th), (ox, oy, w, h))


def from_model(png, frame, size):
    """The model's picture back to the sheet's size."""
    from PIL import Image
    (tw, th), (ox, oy, w, h) = frame
    out = Image.open(io.BytesIO(png)).convert("RGB")
    if out.size != (tw, th):
        out = out.resize((tw, th), Image.LANCZOS)
    return out.crop((ox, oy, ox + w, oy + h)).resize(size, Image.LANCZOS)


def keep_outside(new, old, marks, step=4):
    """Only what grew out of the marked places changes; drift elsewhere goes
    back to the old picture. (A plain feathered circle smeared the old bear
    into the new panda: the model draws the whole thing, bigger than the mark.)"""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    small = (max(1, old.width // step), max(1, old.height // step))
    diff = ImageChops.difference(new.resize(small), old.resize(small)).convert("L")
    changed = diff.point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MaxFilter(5))
    marked = Image.new("L", small, 0)
    _draw_marks(ImageDraw.Draw(marked), marks, 1 / step, (0, 0), 1.0, 255)
    cp, mp = changed.load(), marked.load()
    for yy in range(small[1]):
        for xx in range(small[0]):
            if mp[xx, yy] and cp[xx, yy] == 255:    # a change under a mark: all of it
                ImageDraw.floodfill(changed, (xx, yy), 128)
    keep = ImageChops.lighter(changed.point(lambda v: 255 if v == 128 else 0), marked)
    keep = keep.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.5))
    return Image.composite(new, old, keep.resize(old.size, Image.BILINEAR))


def _png(img):
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


# ── the model ────────────────────────────────────────────────────────────────

_STYLE = ("Pogodna, kolorowa ilustracja jak z książeczki dla dzieci, łagodne kształty, "
          "wyraźne kontury, nic strasznego, bez żadnych napisów.")
_SHEET = ("Arkusz A4 do wydrukowania i wycięcia: białe tło, każdy element osobno, z "
          "wyraźnym odstępem od innych, grube czyste kontury, nic nie przycięte brzegiem "
          "kartki, bez napisów.")
_DRESS = ("Jak papierowe laleczki do przebierania: każde zwierzątko stoi prosto, przodem, w "
          "prostym body; ubranka (czapki, sukienki, spodnie, kurtki, buty) narysowane "
          "osobno obok, w tej samej skali i tym samym kształcie co zwierzątka, każde z "
          "małymi białymi zakładkami do zagięcia.")
_SHEETY = re.compile(r"\barkusz\w*|\ba4\b|\bkart(?:k[aęiy]|ek)\b|\bdo\s+(?:wyci\w+|wydruk\w*|"
                     r"druku|naklejenia)|\bnaklej\w*|\bwycinank\w*|\bplansz\w*", re.I)
_DRESSY = re.compile(r"\bprzebier\w*|\bubran\w*|\bubrań|\bubiera\w*|\bubrać|\bubierz\w*|"
                     r"\blaleczk\w*|\bstroj\w*", re.I)
_COLORING = re.compile(r"\bkolorowank\w*|\bdo\s+pokolorowania\b", re.I)
_WIDE = re.compile(r"\bpoziom\w*|\bpanoram\w*|\bszerok\w*", re.I)
_TALL = re.compile(r"\bpion(?:ow\w*|ie)?\b", re.I)
_SQUARE = re.compile(r"\bkwadrat\w*", re.I)


def size_kind(what, current="landscape"):
    """"poziomo" / "pionowo" / "kwadrat", else the way the paper lies now."""
    return ("landscape" if _WIDE.search(what) else "portrait" if _TALL.search(what)
            else "square" if _SQUARE.search(what) else current)


def gen_prompt(what, current="landscape"):
    """(prompt, size kind) for a new picture."""
    import printer
    kind = size_kind(what, current)
    if _COLORING.search(what):
        style = printer.COLORING_STYLE
    elif _SHEETY.search(what) or _DRESSY.search(what):
        style = _SHEET + (" " + _DRESS if _DRESSY.search(what) else "") + " " + _STYLE
    else:
        style = _STYLE
    return f"Obrazek dla dziecka: {what}. {style}", kind


def edit_prompt(instr, marked):
    if marked:
        return (f"Zmień TYLKO zaznaczone miejsce obrazka: {instr}. Wszystko poza nim zostaw "
                "dokładnie takie samo. Dopasuj styl, kolory i kreskę do reszty obrazka. "
                "Bez napisów, nic strasznego.")
    return (f"Zmień ten obrazek: {instr}. Zachowaj resztę: kompozycję, postacie, kolory i "
            "styl. Bez napisów, nic strasznego.")


def beautify_prompt(photo, marked):
    """"Upiększ": the same picture, made nicely — a drawing redrawn with care,
    a photo touched up (still a photo: the same people, nothing invented)."""
    where = "TYLKO w zaznaczonym miejscu; resztę zostaw dokładnie taką samą. " if marked else ""
    if photo:
        return ("Popraw to zdjęcie " + where + "tak, żeby wyglądało ładniej: lepsze światło, "
                "żywsze naturalne kolory, ostrość, mniej szumu. To ma zostać prawdziwe zdjęcie: "
                "te same osoby z tymi samymi twarzami, ten sam pokój i te same rzeczy, nic nie "
                "dodawaj ani nie usuwaj.")
    return ("Upiększ ten obrazek " + where + "— narysuj go jeszcze raz starannie i ładnie: "
            "dokładnie to samo, co przedstawia, w tym samym układzie, tych samych miejscach i "
            "kolorach, ale z czystymi, pewnymi konturami, równo wypełnionymi kolorami, "
            "łagodnym cieniowaniem i przyjemnym tłem, jak ilustracja w dobrej książeczce dla "
            "dzieci. Jeśli to dziecięcy rysunek, zachowaj jego pomysł i urok. Niczego nowego "
            "nie dodawaj, bez napisów, nic strasznego.")


def _count(bump=False):
    path = os.path.join(DIR, "count.json")
    today = time.strftime("%Y-%m-%d")
    try:
        with open(path, encoding="utf-8") as f:
            n = json.load(f).get(today, 0)
    except (OSError, ValueError):
        n = 0
    if bump:
        try:
            os.makedirs(DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({today: n + 1}, f)
        except OSError:
            pass
    return n


def _start(kind, words, speak):
    """A new picture (kind "new") or a change ("edit") on its own thread."""
    import webphoto
    with state.lock:
        online = state.online
    if not online:
        speak("Nie mam teraz internetu, więc nie narysuję. Ale palcem możesz malować!")
        return True
    if webphoto.NOT_FOR_KIDS.search(words):
        print(f"[paint] not for a child: {words!r}", flush=True)
        speak("Tego nie narysuję — może coś wesołego?")
        return True
    with _lock:
        if _s["busy"]:
            speak("Chwileczkę, jeszcze rysuję.")
            return True
        if _count() >= PER_DAY:
            speak("Na dziś mam już dość rysowania — jutro narysuję więcej! Palcem możesz dalej.")
            return True
        if _s["img"] is None:
            _load()
        if kind == "beautify" and _is_blank(_s["img"]):
            speak("Kartka jest pusta — najpierw coś namaluj albo powiedz, co narysować.")
            return True
        _s["busy"] = {"new": "Rysuję…", "beautify": "Upiększam…"}.get(kind, "Poprawiam…")
        _s["busy_t"] = time.time()
        _s["hint"] = ""
        old, marks = _s["img"].copy(), [dict(m) for m in _s["marks"]]
        paper, photo = _s["paper"], _s["photo"]
    _count(bump=True)
    if not active():
        open_page("")
    if kind == "new":
        speak("Dobrze, już rysuję. Chwileczkę!")
    elif kind == "beautify":
        speak("Dobrze, upiększam" + (" zaznaczone miejsce." if marks else ". Chwileczkę!"))
    elif marks:
        speak("Dobrze, zmieniam zaznaczone miejsce.")
    else:
        speak("Dobrze, już poprawiam.")
    print(f"[paint] {kind}: {words!r}{f' ({len(marks)} marks)' if marks else ''}", flush=True)
    threading.Thread(target=_run, args=(kind, words, old, marks, paper, photo), daemon=True,
                     name="paint").start()
    return True


def _client():
    from openai import OpenAI
    from config import OPENAI_API_KEY
    return OpenAI(api_key=OPENAI_API_KEY, timeout=150, max_retries=1)


def _run(kind, words, old, marks, paper="landscape", photo=False):
    try:
        c = _client()
        if kind == "new":
            prompt, kind_ = gen_prompt(words, paper)
            tw, th = SIZES[kind_]
            r = c.images.generate(model=MODEL, size=f"{tw}x{th}", quality=QUALITY, n=1,
                                  prompt=prompt)
            from PIL import Image
            img = Image.open(io.BytesIO(base64.b64decode(r.data[0].b64_json))).convert("RGB")
            title = words
        else:
            pic, mask, frame = model_inputs(old, marks)
            (tw, th), _ = frame
            args = dict(model=MODEL, size=f"{tw}x{th}", quality=QUALITY, n=1,
                        image=("obrazek.png", pic, "image/png"),
                        prompt=beautify_prompt(photo, bool(marks)) if kind == "beautify"
                        else edit_prompt(words, bool(marks)))
            try:
                r = c.images.edit(mask=("maska.png", mask, "image/png"), **args) if mask \
                    else c.images.edit(**args)
            except Exception as e:
                if not (mask and "mask" in str(e).lower()):
                    raise
                print(f"[paint] the mask was refused ({e}); without it", flush=True)
                r = c.images.edit(**args)
            img = from_model(base64.b64decode(r.data[0].b64_json), frame, old.size)
            if marks:
                img = keep_outside(img, old, marks)
            title = None
        with _lock:
            _set(img, title=title)
            if kind == "new":
                _s["photo"] = False
            _s["hint"] = "Coś zmienić? Naciśnij „Powiedz” albo pokaż palcem („Pokaż”)"
            _s["asked_t"] = time.time()
        if not active():
            _show()
        print(f"[paint] done: {kind}", flush=True)
        # (not listening after it: 26 Oct the open window took "Ależ nieładna",
        # "Się" for wishes — "Powiedz" or "Luna" starts the next one)
        _say({"beautify": "Gotowe! Jeśli się nie podoba, naciśnij Cofnij."}.get(
            kind, "Gotowe! Jeśli coś zmienić, naciśnij Powiedz."))
        try:
            import brain
            brain.add_to_last_reply("(Na ekranie Malowanie: " +
                                    (f"nowy obrazek — {words}" if kind == "new"
                                     else "obrazek upiększony" if kind == "beautify"
                                     else f"obrazek zmieniony — {words}") + ".)")
        except Exception:
            pass
    except Exception as e:
        print(f"[paint] failed: {e!r}", flush=True)
        refused = "safety" in str(e).lower() or "moderation" in str(e).lower()
        _hint("Nie wyszło — spróbuj jeszcze raz")
        _say("Tego nie narysuję — może coś wesołego?" if refused
             else "Nie udało mi się narysować — spróbuj jeszcze raz.")
    finally:
        with _lock:
            _s["busy"] = None


# ── voice ────────────────────────────────────────────────────────────────────

_POLITE = r"(?:(?:a\s+|no\s+|to\s+|dobra,?\s+|okej,?\s+|teraz\s+|luna,?\s+)*" \
          r"(?:(?:czy\s+)?(?:możesz|mozesz|mogłabyś|moglabys|mogłabys)\s+)?(?:proszę\s+|prosze\s+)?)"
_OPEN = re.compile(
    r"^" + _POLITE + r"(?:(?:otwórz|otworz|włącz|wlacz|pokaż|pokaz|uruchom|otworzyć|włączyć)\s+"
    r"(?:mi\s+|nam\s+)?(?:malowanie|malowank[eęi]|paint|kartkę\s+do\s+malowania|"
    r"edytor(?:\s+(?:obrazków|obrazkow|zdjęć|zdjec|rysunków|rysunkow))?)|"
    r"(?:chcę|chce|chcemy|chciałabym|chciałbym)\s+(?:po)?malować|"
    r"pomalujmy|(?:po)?malujmy(?:\s+razem)?|malujemy(?:\s+razem)?|porysujmy(?:\s+razem)?)"
    r"\W*$", re.I)
_EDIT_SHOWN = re.compile(
    r"^" + _POLITE + r"(?:(?:otwórz|otworz|weź|wez|daj)\s+(?:to|go|je|ją|ten\s+\w+|tę\s+\w+)\s+"
    r"(?:do|w)\s+malowani\w*|(?:edytuj|popraw|przerób|przerob|pomaluj|zmień|zmien|"
    r"przemaluj)\s+(?:to(?:\s+zdjęcie|\s+zdjecie)?|ten\s+(?:rysunek|obrazek|obraz)|"
    r"tę\s+(?:fotkę|fotke)|to\s+co\s+(?:jest\s+)?na\s+ekranie))(?:\s*[:,—–-]?\s*(.*))?$", re.I)
# "Hal, włącz w edytorze moje zdjęcie", "chcę upiększyć swoje zdjęcie" (26 Oct:
# the model said "włączam", nothing opened; on a clean sheet the next "chcę je
# zobaczyć w edytorze" was drawn as a picture)
_PHOTO_WORD = r"(?:zdjęci[eua]|zdjeci[eua]|fotk[eęia]|fotografi[eęia])"
_MY = r"(?:moje|swoje|moją|moja|swoją|swoja|nasze|to|ostatnie|jakieś|jakies)"
_IN_EDITOR = (r"(?:w|do)\s+(?:edytor\w*|malowani\w*|malowank\w*)"
              r"(?:\s+(?:zdjęć|zdjec|obrazków|obrazkow|rysunków|rysunkow))?")
_PHOTO_OBJ = r"(?:(?:" + _MY + r"\s+)?" + _PHOTO_WORD + r"|je|go|ją)"
_OPEN_PHOTO = re.compile(
    r"^" + _POLITE + r"(?:(?:na\s+razie|teraz|najpierw|tylko)\s+)?"
    r"(?:(?:chcę|chce|chcemy|chciałbym|chcialbym|chciałabym|chcialabym)\s+)?"
    r"(?:(?:na\s+razie|teraz|najpierw|tylko)\s+)?(?:(?:je|go|ją)\s+)?(?:(?:włącz\w*|wlacz\w*|"
    r"otwórz|otworz\w*|pokaż|pokaz\w*|daj|wrzuć|wrzuc\w*|weź|wez|wczytaj|wczytać|zobaczyć|"
    r"zobaczyc|obejrzeć)\s+(?:mi\s+|nam\s+)?(?:" + _PHOTO_OBJ + r"\s+" + _IN_EDITOR + r"|"
    + _IN_EDITOR + r"(?:\s+" + _PHOTO_OBJ + r")?)|(?:upiększ\w*|upieksz\w*|popraw\w*|edytuj|edytować|edytowac|pomaluj|"
    r"pomalować|pomalowac|przerób|przerob\w*)\s+(?:mi\s+)?(?:" + _MY + r"\s+)?" + _PHOTO_WORD
    + r"(?:\s+" + _IN_EDITOR + r")?)\W*$", re.I)
_UNDO = re.compile(r"^" + _POLITE + r"(?:cofnij|cofnąć|cofnac|wróć|wroc|jednak\s+nie|"
                   r"przywróć|przywroc)(?:\s+(?:to|go|jak\s+było|tak\s+jak\s+było|"
                   r"poprzedni\w*|zmian\w*|ostatni\w*|wszystko|do\s+poprzedniego))*\W*$", re.I)
_SAVE = re.compile(r"^" + _POLITE + r"(?:zapisz|zachowaj|zapisać|zachować)(?:\s+(?:to|go|ją|"
                   r"je|ten\s+\w+|tę\s+\w+|obrazek|rysunek|kartkę|arkusz|na\s+później|"
                   r"w\s+galerii|do\s+galerii))*\W*$", re.I)
_BLANK = re.compile(r"^" + _POLITE + r"(?:(?:daj|weź|wez|poproszę)\s+(?:mi\s+|nam\s+)?)?"
                    r"(?:(?:nową|nowa|czystą|czysta|pustą|pusta)\s+(?:kartkę|kartke|kartka|"
                    r"stronę|strona)(?:\s+(?:na\s+)?(?:poziom\w*|pionow\w*))?|wyczyść\s+(?:wszystko|kartkę|kartke|"
                    r"obrazek)|wyczyść|wyczysc|zmaż\s+wszystko|zacznijmy\s+od\s+nowa|"
                    r"od\s+nowa)\W*$", re.I)
_SNAP = r"(?:zrób|zrob|zróbmy|zrobmy|zrobić|zrobic|cyknij|strzel)\s+(?:mi\s+|nam\s+)?" \
        r"(?:(?:nowe|jakieś|jakies)\s+)?(?:zdjęcie|zdjecie|fotkę|fotke|fotografię|fotografie)"
_PHOTO = re.compile(r"^" + _POLITE + r"(?:" + _SNAP + r"(?:\s+(?:mi|nam|mnie|nas|"
                    r"aparatem|kamerą|kamera|z\s+kamery|do\s+malowania))*|(?:weź|wez)\s+"
                    r"(?:zdjęcie|zdjecie)\s+z\s+(?:kamery|aparatu)|(?:z\s+)?aparat\w*)\W*$", re.I)
_PHOTO_TO_PAINT = re.compile(
    r"^" + _POLITE + _SNAP + r"(?:\s+(?:mi|nam|mnie|nas))*\s+(?:do\s+(?:malowania|"
    r"pomalowania|rysowania|edytora)|(?:i|żeby|zeby|by)\s+(?:je\s+|go\s+)?(?:otwórz\w*|"
    r"otworz\w*|pomaluj\w*|pomalować|pomalowac|edytuj\w*|edytować|popraw\w*)(?:\s+(?:je|go|"
    r"to))?(?:\s+w\s+malowaniu)?)\W*$", re.I)
_BEAUTIFY = re.compile(
    r"^" + _POLITE + r"(?:upiększ\w*|upieksz\w*|wypiększ\w*|"
    r"(?:zrób|zrob|zrobić|zrobic|narysuj|namaluj|popraw)\s+(?:to\s+|go\s+|ją\s+|je\s+|"
    r"ten\s+\w+\s+|tę\s+\w+\s+|mój\s+\w+\s+|moj\w*\s+\w+\s+)?(?:ładniej\w*|ladniej\w*|"
    r"piękniej\w*|pieknie\w*|ładnie|ladnie|lepiej)|(?:niech|żeby|zeby)\s+(?:to\s+)?"
    r"(?:wygląda\w*|wyglada\w*)\s+(?:ładniej|ladniej|lepiej|pięknie|piekniej))"
    r"(?:\s+(?:to|go|ją|je|ten\s+\w+|tę\s+\w+|obrazek|rysunek|zdjęcie|zdjecie|"
    r"kartkę|mój\s+\w+|moje\s+\w+|proszę|prosze))*\W*$", re.I)
_ROTATE = re.compile(
    r"^" + _POLITE + r"(?:(?:obróć|obroc|przekręć|przekrec|odwróć|odwroc|ustaw|połóż|poloz|"
    r"zrób|zrob|daj)\s+(?:mi\s+|nam\s+)?(?:kartkę|kartke|papier|stronę|strone|arkusz)"
    r"(?:\s+(?:na\s+)?(?:poziom\w*|pionow\w*|w\s+poziomie|w\s+pionie|bokiem|na\s+bok))?|"
    r"obróć|obroc|(?:kartka|kartkę|kartke)\s+(?:na\s+)?(?:poziom\w*|pionow\w*)|"
    r"(?:na\s+)?(?:poziomo|pionowo)|w\s+poziomie|w\s+pionie)\W*$", re.I)
_UNMARK = re.compile(r"^" + _POLITE + r"(?:usuń|usun|wyczyść|wyczysc|skasuj|zabierz)\s+"
                     r"(?:te\s+|to\s+)?(?:zaznaczeni\w*|kółk\w*|kolk\w*|znaczk\w*|czerwon\w*)\W*$",
                     re.I)
_NEW_VERB = r"(?:narysuj\w*|namaluj\w*|narysować|namalować|stwórz|stworz|stworzyć|stworzyc|" \
            r"wygeneruj\w*|przygotuj|przygotować|zrób|zrob|zrobić|zrobic)"
_GEN = re.compile(r"^" + _POLITE + _NEW_VERB + r"\s+(?:mi\s+|nam\s+|teraz\s+)*(.{3,}?)\W*$", re.I)
_NEW_SHEET = re.compile(r"\b(?:arkusz\w*|a4|kart(?:k[aęiy]|ek)|kolorowank\w*|plakat\w*|laurk\w*|"
                        r"plansz\w*|now[ąyaego]+|inny|inną|inne)\b", re.I)
_NEW_NOUN = re.compile(r"\b(?:obrazek|obrazka|rysunek|rysunku|obraz)\b", re.I)
_HERE = re.compile(r"\b(?:tu|tutaj|tam|obok|tego|temu|niego|niej|nim|mu|jej|im|go|ją|je|"
                   r"większ\w*|wieksz\w*|mniejsz\w*|zamiast|w\s+miejsc\w*|zaznaczon\w*|"
                   r"z\s+(?:mojego|tego|mojej|tej)\s+\w+|ładniej\w*|ladniej\w*|lepiej|"
                   r"inaczej|kolorow\w+\s+(?:to|go))\b", re.I)
_EDIT = re.compile(
    r"^" + _POLITE + r"(?:zmień|zmien|zmienić|zmienic|popraw|poprawić|dodaj|dodać|dorysuj|"
    r"domaluj|dołóż|doloz|usuń|usun|usunąć|wymaż|wymaz|zmaż|zmaz|zabierz|pokoloruj|przemaluj|"
    r"pomaluj|zamień|zamien|niech|powiększ|powieksz|zmniejsz|przesuń|przesun|odwróć|odwroc|"
    r"wstaw|włóż|wloz|ubierz|przebierz|załóż|zaloz|wyrzuć|wyrzuc|daj\s+(?:mu|jej|im|tu|tutaj)|"
    r"chcę,?\s+żeby|chce,?\s+zeby|chciałabym,?\s+żeby|zrób\s+(?:tak|żeby|zeby|go|ją|je|to|z)|"
    r"zrob\s+(?:tak|zeby|go|ja|je|to|z)|a\s+może|a\s+moze|ma\s+(?:być|byc|mieć|miec)|"
    r"więcej|wiecej|mniej|bez)\b.{0,200}$", re.I)
_NOT_PICTURE = re.compile(r"\bdo\s+(?:listy|zakupów|zakupow|planu|kalendarza|przypomnie\w*)|"
                          r"\bna\s+list\w*|\bprzypomnieni\w*|\bbudzik\w*|\bminut\w*|\bgłośn\w*|"
                          r"\bglosn\w*|\bradi\w+|\bmuzyk\w*|\bświatł\w*|\blampk\w*", re.I)
_DISLIKE = re.compile(r"\bnie\s+podoba\s+mi\s+się|\bnie\s+podoba\s+mi\s+sie|\bnie\s+chcę\s+"
                      r"(?:tego|tu|tutaj)|\bnie\s+chce\s+(?:tego|tu|tutaj)|\btego\s+nie\s+chc\w+|"
                      r"\bto\s+(?:jest\s+)?(?:brzydk\w*|złe|zle|głupie|glupie|okropne)|"
                      r"\bbez\s+tego\b|\bzabierz\s+to\b|\busuń\s+to\b|\busun\s+to\b|"
                      r"\bwyrzuć\s+to\b", re.I)
_ABOUT_PAGE = re.compile(r"\bedytor\w*|\bw\s+malowaniu\b", re.I)    # the page, not a picture
_QUESTION = re.compile(r"^(?:a\s+)?(?:co|jak|jaki\w*|jaka|jakie|kto|ile|czy|kiedy|gdzie|"
                       r"dlaczego|czemu|po\s+co|któr\w*|ktor\w*|skąd|skad)\b", re.I)
_REACTION = re.compile(r"^(?:(?:dzięki|dzieki|dziękuję|dziekuje|super|fajnie|fajne|ok|okej|"
                       r"tak|nie|dobrze|dobra|świetnie|swietnie|ładnie|ladnie|ekstra|wow|hura|"
                       r"pięknie|pieknie|cudownie|bomba|czad|extra|jest\s+super|"
                       r"bardzo|dziękujemy)\W*)+$", re.I)


def _clean(text):
    t = re.sub(r"^\s*(?:luna|hej\s+luna)\s*[,!:]?\s*", "", text.strip(), flags=re.I)
    return t.strip(" .!?")


def opener(text, speak):
    """"otwórz malowanie"; with a picture on the screen, "popraw ten rysunek: …"."""
    t = _clean(text)
    if _OPEN.match(t):
        open_page()
        speak("Dobrze! Maluj palcem albo naciśnij Powiedz i powiedz, co narysować.")
        return True
    if _PHOTO_TO_PAINT.match(t):                    # "zrób zdjęcie do malowania"
        open_page("Uśmiech! Patrz w kamerę")
        return take_photo(speak)
    m = _EDIT_SHOWN.match(t)
    if m:
        import gallery
        shown = gallery.current()
        if not (shown and shown.get("path") and os.path.exists(shown["path"])):
            return False
        open_picture(shown["path"], str(shown.get("caption") or ""))
        open_page("Maluj albo powiedz, co zmienić")
        rest = (m.group(1) or "").strip(" ,.")
        if len(rest) >= 3:
            return _start("edit", rest, speak)
        speak("Otwieram w malowaniu. Jeśli coś zmienić, naciśnij Powiedz.")
        return True
    if _OPEN_PHOTO.match(t):
        return open_photo(speak)
    return False


def open_photo(speak):
    """"Włącz moje zdjęcie w edytorze": the photo on the screen onto the sheet,
    else the page with its picker (photos and pictures, newest first)."""
    import gallery
    shown = gallery.current()
    if shown and shown.get("path") and os.path.exists(shown["path"]):
        open_picture(shown["path"], str(shown.get("caption") or ""))
        open_page("Maluj albo powiedz, co zmienić")
        speak("Otwieram w malowaniu. Jeśli coś zmienić, naciśnij Powiedz.")
        return True
    pics = _openable()
    open_page("Wybierz zdjęcie albo naciśnij „Zdjęcie”, żeby zrobić nowe")
    with _lock:
        _s["picker"], _s["page"] = (pics or None), 0
    print(f"[paint] a photo to open: the picker ({len(pics)})", flush=True)
    speak("Wybierz palcem, które otworzyć — albo naciśnij Zdjęcie." if pics else
          "Nie mam jeszcze zdjęć. Naciśnij Zdjęcie, a zrobię nowe.")
    return True


def voice(text, speak):
    """An utterance while the page is up: True when it was for the picture."""
    if not active():
        return opener(text, speak)
    t = _clean(text)
    low = t.lower()
    _keep_up()
    if _UNDO.match(t):
        speak("Cofnięte." if undo() else "Nie ma czego cofnąć.")
        return True
    if _SAVE.match(t):
        return save(speak)
    import printer
    m = printer._PRINT.match(t)
    if m:
        what = m.group(1).strip(" ,")
        copies, what = printer._copies(what)
        mono = bool(printer._MONO.search(what))
        what = printer._MONO.sub("", what).strip(" ,")
        if not what or printer._THIS.match(what) or printer._PICTURE.search(what) \
                or re.search(r"\b(?:kart\w*|arkusz\w*|malowani\w*)\b", what, re.I):
            return print_sheet(speak, copies, mono)
        return False                               # "wydrukuj listę zakupów"
    if _BLANK.match(t):
        new_sheet(size_kind(t, _s["paper"]))
        speak("Proszę, czysta kartka.")
        return True
    r = _ROTATE.match(t)
    if r:
        want = size_kind(t, "")
        with _lock:
            now = orientation(_s["img"]) if _s["img"] is not None else "portrait"
        if want == now:
            speak("Kartka już leży " + ("poziomo." if now == "landscape" else "pionowo."))
            return True
        rotate()
        speak("Obracam kartkę.")
        return True
    if _OPEN_PHOTO.match(t) and not (_BEAUTIFY.match(t) and _has_picture()):
        return open_photo(speak)                    # another photo onto the sheet
    if _BEAUTIFY.match(t):
        return _start("beautify", "upiększ", speak)
    if _PHOTO.match(t):
        return take_photo(speak)
    if _UNMARK.match(t):
        with _lock:
            _s["marks"] = []
            _s["ver"] += 1
        speak("Dobrze, bez zaznaczeń.")
        return True
    if _NOT_PICTURE.search(low):
        return False
    with _lock:
        marked = bool(_s["marks"])
        blank = _s["img"] is None or _is_blank(_s["img"])
    g = _GEN.match(t)
    if g and not _EDIT.match(t):
        what = g.group(1).strip(" ,")
        new = blank or _NEW_SHEET.search(what) or \
            (_NEW_NOUN.search(what) and not _HERE.search(what)) or \
            (not marked and not _HERE.search(what) and re.match(r"(?:narysuj|namaluj|stw|wyg)",
                                                                  low))
        return _start("new" if new else "edit", what if new else t, speak)
    if _DISLIKE.search(t) or _EDIT.match(t):
        return _edit(t, marked, blank, speak)
    return False


def fallback(text, speak):
    """The last word before the model: with the page up, a wish that no other
    command took ("kot ma być rudy") is about the picture."""
    if not active():
        return False
    t = _clean(text)
    if (len(t.split()) < 2 or _QUESTION.match(t) or text.strip().endswith("?")
            or _REACTION.match(t) or _NOT_PICTURE.search(t) or _ABOUT_PAGE.search(t)):
        return False
    with _lock:
        marked = bool(_s["marks"])
        blank = _s["img"] is None or _is_blank(_s["img"])
        recent = time.time() - max(_s["touch_t"], _s["asked_t"]) < TALK_SECS
    if not (marked or recent):
        return False                                # (talk in the room, the page long idle)
    if blank:
        return _start("new", t, speak)              # a clean sheet: "kot na rowerze"
    return _edit(t, marked, blank, speak)


def _edit(t, marked, blank, speak):
    if _DISLIKE.search(t) and not marked:
        rest = _DISLIKE.sub("", t).strip(" ,.")
        if len(rest.split()) < 2:                   # "nie podoba mi się" — but what?
            with _lock:
                _s["tool"] = "mark"
                _s["hint"] = "Dotknij tego, co ci się nie podoba"
                _s["ver"] += 1
            speak("Pokaż mi palcem, co ci się nie podoba — dotknij tego miejsca na obrazku, "
                  "a potem naciśnij Powiedz i powiedz, co zrobić.")
            return True
    if blank:
        speak("Kartka jest pusta — powiedz, co narysować, albo maluj palcem.")
        return True
    instr = t
    if marked and re.fullmatch(r"(?:" + _DISLIKE.pattern + r")\W*", t, re.I):
        instr = "usuń to, co tu jest, i uzupełnij tło tak, żeby pasowało do reszty"
    return _start("edit", instr, speak)


def _has_picture():
    with _lock:
        return _s["img"] is not None and not _is_blank(_s["img"])


def _is_blank(img):
    lo, hi = img.convert("L").getextrema()
    return lo >= 250
