"""
settings_page.py — "pokaż ustawienia": one page on her screen, four tabs.

  Ogólne  — the default language, speech speed, reply length, captions, the bar
  Ekran   — the camera preview, how smoothly the face is drawn (fps)
  Koszty  — API calls by day and their estimated cost (health.py's counts)
  Reset   — what she remembers; the factory reset: memories and the people she
            knows MOVED to data/reset-<date>/ (never deleted), then a restart

ui_screens draws it (draw_settings / settings_hit); robot_face sends taps and
swipes here. Values go to data/settings.json (settings.py) and are read live.
"""

import os
import shutil
import signal
import threading
import time

import settings
from shared_state import state
from config import (DATA_DIR, PHOTOS_DIR, OPENAI_TTS_SPEED, CAMERA_PREVIEW, DRAW_FPS,
                    API_COST_USD, USD_PLN)

PAGE_SECS = 60                # untouched this long, the page closes
CONFIRM_SECS = 20             # the reset's "Na pewno?" waits this long
TABS = ("Ogólne", "Ekran", "Koszty", "Reset")

_LANGS = (("pl", "Polski"), ("en", "English"))
_SPEEDS = (1.0, 1.1, 1.2, 1.3, 1.4)
_LENGTHS = (("short", "Krótkie"), ("normal", "Zwykłe"), ("long", "Długie"))
_FPS = (30, 45, 60)

# what the factory reset takes away (relative to DATA_DIR; photos/people.json apart)
RESET_FILES = ("memory.json", "history.json", "relations.json", "day.json", "diary.json",
               "greeted.json", "people.json", "people_forgotten.json", "seen.json", "faces")


def _plural(n, one, few, many):
    import calc
    return calc._plural(n, one, few, many)


def show(tab=0):
    with state.lock:
        state.overlay = ("settings", time.time() + PAGE_SECS, {"tab": tab})


def _next(options, cur):
    keys = [o[0] if isinstance(o, tuple) else o for o in options]
    i = keys.index(cur) if cur in keys else -1
    return keys[(i + 1) % len(keys)]


def _label(options, cur):
    return dict(options).get(cur, str(cur))


def language():
    return settings.get("language", "pl")


def draw_fps():
    v = settings.get("draw_fps", DRAW_FPS)
    return v if isinstance(v, int) and 10 <= v <= 60 else DRAW_FPS


# ── the costs ─────────────────────────────────────────────────────────────────

def cost(counts):
    """Estimated PLN for {kind: calls} (config.API_COST_USD per call)."""
    return sum(API_COST_USD.get(k, 0.0) * n for k, n in counts.items()) * USD_PLN


def _zl(v):
    return f"≈ {v:.2f} zł".replace(".", ",")


def _calls(counts):
    return " · ".join(f"{k} {v}" for k, v in sorted(counts.items()) if k != "ping") or "brak"


def cost_rows(today=None):
    import health
    from datetime import date, timedelta
    today = today or date.today()
    usage = health._read_usage()
    days = {}
    for k in range(31):
        d = (today - timedelta(days=k)).isoformat()
        days[d] = health.day_counts(d, usage)

    def total(keys):
        out = {}
        for d in keys:
            for k, v in days[d].items():
                out[k] = out.get(k, 0) + v
        return out
    t, y = today.isoformat(), (today - timedelta(days=1)).isoformat()
    week = total([(today - timedelta(days=k)).isoformat() for k in range(7)])
    month = total([d for d in days if d[:7] == t[:7]])
    rows = [{"label": "Dziś", "sub": _calls(days[t]), "value": _zl(cost(days[t]))},
            {"label": "Wczoraj", "sub": _calls(days[y]), "value": _zl(cost(days[y]))},
            {"label": "7 dni", "sub": _calls(week), "value": _zl(cost(week))},
            {"label": "Ten miesiąc", "sub": _calls(month), "value": _zl(cost(month))}]
    with state.lock:
        online = state.online
    rows.append({"label": "Konto OpenAI",
                 "sub": "szacunek; rachunek: platform.openai.com",
                 "value": "BRAK ŚRODKÓW" if health.no_credits()
                 else "połączone" if online else "brak sieci"})
    for r in rows:
        r["kind"] = "info"
    return rows


# ── the rows of each tab ──────────────────────────────────────────────────────

_cache = {}                   # tab → (when, rows): drawn every frame, read once a second


def rows(tab, now=None):
    """[{"key", "label", "sub", "value", "kind": toggle|cycle|info|danger}]"""
    now = now or time.time()
    hit = _cache.get(tab)
    if hit and now - hit[0] < 1.0:
        return hit[1]
    out = _rows(tab)
    _cache[tab] = (now, out)
    return out


def _rows(tab):
    if tab == 0:
        speed = settings.get("tts_speed", OPENAI_TTS_SPEED)
        return [
            {"key": "language", "kind": "cycle", "label": "Język",
             "sub": "w jakim języku odpowiada",
             "value": _label(_LANGS, language())},
            {"key": "tts_speed", "kind": "cycle", "label": "Tempo mowy",
             "sub": "wspólne dla całego domu",
             "value": f"{speed:.1f}×".replace(".", ",")},
            {"key": "reply_length", "kind": "cycle", "label": "Długość odpowiedzi",
             "sub": "jak długo mówi", "value": _label(_LENGTHS, settings.get("reply_length", "normal"))},
            {"key": "captions", "kind": "toggle", "label": "Napisy",
             "sub": "jej słowa na dole ekranu", "value": bool(settings.get("captions", False))},
            {"key": "status_bar", "kind": "toggle", "label": "Pasek u góry",
             "sub": "godzina, pogoda, minutniki", "value": settings.get("status_bar", True) is not False},
        ]
    if tab == 1:
        return [
            {"key": "camera_preview", "kind": "toggle", "label": "Podgląd kamery",
             "sub": "mały obraz z kamery w rogu",
             "value": bool(settings.get("camera_preview", CAMERA_PREVIEW))},
            {"key": "draw_fps", "kind": "cycle", "label": "Płynność twarzy",
             "sub": "klatki na sekundę; mniej = chłodniejszy procesor",
             "value": f"{draw_fps()} kl./s"},
        ]
    if tab == 2:
        return cost_rows()
    import memory
    import faces
    try:
        m = memory._load()
        nf, ne = len(m["facts"]), len(m["episodes"])
    except Exception:
        nf = ne = 0
    names = faces.names()
    return [
        {"kind": "info", "label": "Wspomnienia", "sub": "fakty i rozmowy, które pamięta",
         "value": f"{nf} {_plural(nf, 'fakt', 'fakty', 'faktów')} · "
                  f"{ne} {_plural(ne, 'rozmowa', 'rozmowy', 'rozmów')}"},
        {"kind": "info", "label": "Znane osoby", "sub": ", ".join(names) or "nikogo nie zna",
         "value": str(len(names))},
        {"key": "reset", "kind": "danger", "label": "Reset fabryczny",
         "sub": "zapomina wspomnienia i osoby (zostaje kopia)",
         "value": "Wyczyść"},
    ]


def change(key):
    """A tap on a row's control: the next value. Returns the toast text."""
    _cache.clear()
    if key == "language":
        new = _next(_LANGS, language())
        settings.put("language", new)
        return f"Język: {_label(_LANGS, new)}"
    if key == "tts_speed":
        cur = settings.get("tts_speed", OPENAI_TTS_SPEED)
        new = next((s for s in _SPEEDS if s > cur + 0.01), _SPEEDS[0])
        settings.put("tts_speed", new)
        return f"Tempo mowy {new:.1f}×".replace(".", ",")
    if key == "reply_length":
        new = _next(_LENGTHS, settings.get("reply_length", "normal"))
        settings.put("reply_length", new)
        return f"Odpowiedzi: {_label(_LENGTHS, new).lower()}"
    if key == "draw_fps":
        new = _next(_FPS, draw_fps())
        settings.put("draw_fps", new)
        return f"Płynność: {new} klatek na sekundę"
    defaults = {"captions": False, "status_bar": True, "camera_preview": CAMERA_PREVIEW}
    if key in defaults:
        cur = settings.get(key, defaults[key])
        new = not (cur is not False if key == "status_bar" else bool(cur))
        settings.put(key, new)
        return "Włączone" if new else "Wyłączone"
    return None


# ── the factory reset ─────────────────────────────────────────────────────────

def factory_reset(data_dir=DATA_DIR, photos_dir=PHOTOS_DIR, now=None):
    """Move her memories and the people she knows to data_dir/reset-<stamp>/.
    Nothing is deleted: copying them back (and a restart) undoes it.
    Returns the folder."""
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(now or time.time()))
    dest = os.path.join(data_dir, f"reset-{stamp}")
    os.makedirs(dest, exist_ok=True)
    moved = []
    for name in RESET_FILES:
        src = os.path.join(data_dir, name)
        if os.path.exists(src):
            shutil.move(src, os.path.join(dest, name))
            moved.append(name)
    tags = os.path.join(photos_dir, "people.json")      # who is in which photo
    if os.path.exists(tags):
        shutil.move(tags, os.path.join(dest, "photos-people.json"))
        moved.append("photos/people.json")
    print(f"[settings] FACTORY RESET — moved to {dest}: {', '.join(moved) or 'nothing'}",
          flush=True)
    return dest


def _reset_and_restart():
    with state.lock:
        state.overlay = ("card", time.time() + 10,
                         {"text": "Zaczynam od nowa…", "sub": "zaraz wracam", "tone": None})
    try:
        factory_reset()
    except OSError as e:
        print(f"[settings] factory reset failed: {e}", flush=True)
        return
    time.sleep(2.0)
    os.kill(os.getpid(), signal.SIGTERM)       # main._shutdown; lwrespawn starts her again


def _child_here():
    import screens
    return screens._child_here()


# ── touch ─────────────────────────────────────────────────────────────────────

def _page_data():
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "settings":
            return None
        state.overlay = (ov[0], time.time() + PAGE_SECS, ov[2])
        return ov[2]


def _toast(data, text):
    data["toast"] = (text, time.time() + 2.0)


def tap(x, y, W, H, now=None):
    """A tap (px) on the page: a tab, a row's control, the reset's dialog."""
    import ui_screens
    now = now or time.time()
    data = _page_data()
    if data is None:
        return False
    hit = ui_screens.settings_hit(x, y, W, H, data)
    if data.get("confirm"):
        if now - data["confirm"] > CONFIRM_SECS or hit == ("no",) or not hit:
            data["confirm"] = None
        elif hit == ("yes",):
            data["confirm"] = None
            if _child_here():
                _toast(data, "Poproś dorosłego")
            else:
                threading.Thread(target=_reset_and_restart, daemon=True,
                                 name="factory-reset").start()
        return True
    if not hit:
        return True
    if hit[0] == "tab":
        data["tab"] = hit[1]
    elif hit[0] == "row":
        r = rows(data.get("tab", 0))[hit[1]]
        if r["kind"] == "danger":
            data["confirm"] = now
        elif r.get("key"):
            said = change(r["key"])
            if said:
                _toast(data, said)
    return True


def swipe(dx):
    """A swipe: the next tab (to the left) or the one before."""
    data = _page_data()
    if data is None or data.get("confirm"):
        return False
    data["tab"] = (data.get("tab", 0) + (1 if dx < 0 else -1)) % len(TABS)
    return True
