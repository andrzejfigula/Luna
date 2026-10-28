"""
settings_page.py — "pokaż ustawienia": one page on her screen, four tabs.

  Ogólne  — the default language, speech speed, reply length, captions, the bar
  Ekran   — her theme (themes.py), the camera preview, how smoothly the face is drawn
  Ikony   — the quick icons along the bottom (dock.py): on/off, a tile to tick for each
  Urządzenia — the speaker, microphone and camera she uses (devices.py)
  Koszty  — API calls by day and their estimated cost (health.py's counts)
  Osoby   — who she knows: family or guest (a guest gets no plan and hears
            nothing of the house), the bin tapped twice; not for a guest/stranger
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

import characters
import devices
import settings
import themes
from shared_state import state
from config import (DATA_DIR, PHOTOS_DIR, OPENAI_TTS_SPEED, CAMERA_PREVIEW, DRAW_FPS,
                    API_COST_USD, USD_PLN)

PAGE_SECS = 60                # untouched this long, the page closes
CONFIRM_SECS = 20             # the reset's "Na pewno?" waits this long
TABS = ("Ogólne", "Asystent", "Ekran", "Ikony", "Urządzenia", "Koszty", "Osoby", "Reset")
PEOPLE_PER_PAGE = 4
BIN_SECS = 4.0                # the bin tapped again within this: forgotten

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
    _people_page[0] = 0
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


# ── the devices ───────────────────────────────────────────────────────────────

_DEVICES = (("speaker", "Głośnik"), ("mic", "Mikrofon"), ("camera", "Kamera"))


_VOLUMES = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
_BRIGHT = (100, 80, 60, 40)


def device_rows():
    rows = []
    for key, label in _DEVICES:
        pick = settings.get(key)
        value = dict(devices.options(key)).get(pick or "", devices.AUTO)
        rows.append({"key": key, "kind": "cycle", "label": label,
                     "sub": f"teraz: {devices.now_label(key)}", "value": value})
    import commands
    vol = commands.get_volume()
    rows.append({"key": "volume", "kind": "cycle", "label": "Głośność",
                 "sub": "zapamiętana — wraca po odłączeniu głośnika",
                 "value": f"{round(vol * 100)} %" if vol is not None else "?"})
    rows.append({"key": "night_quiet", "kind": "toggle", "label": "Ciszej w nocy",
                 "sub": "od 22 do 8 mówi o połowę ciszej",
                 "value": settings.get("night_quiet", True) is not False})
    return rows


def _say_speaker():
    """The speaker was tapped (someone's there): a word from the new one."""
    from text_to_speech import speak
    time.sleep(1.0)                        # (openai_tts moves to it first)
    speak("Teraz mówię przez ten głośnik.")


def dock_rows():
    """Ikony: the row on/off, then a tile for every icon there can be."""
    import dock
    shown = dock.chosen()
    return [{"key": "dock", "kind": "toggle", "label": "Ikony na dole",
             "sub": "dotknij kafelka, żeby go dodać albo schować",
             "value": dock.enabled()}] + [
        {"key": "dock:" + k, "kind": "tile", "label": label, "icon": k, "value": k in shown}
        for k, label in dock.ITEMS]


# ── the rows of each tab ──────────────────────────────────────────────────────

_cache = {}                   # tab → (when, rows): drawn every frame, read once a second


def rows(tab, now=None):
    """[{"key", "label", "sub", "value", "kind": toggle|cycle|info|danger|tile|person}]"""
    now = now or time.time()
    hit = _cache.get(tab)
    if hit and now - hit[0] < 1.0:
        return hit[1]
    out = _rows(tab)
    _cache[tab] = (now, out)
    return out


def _rows(tab):
    if tab == 0:
        return [
            {"key": "language", "kind": "cycle", "label": "Język",
             "sub": "w jakim języku odpowiada",
             "value": _label(_LANGS, language())},
            {"key": "reply_length", "kind": "cycle", "label": "Długość odpowiedzi",
             "sub": "jak długo mówi", "value": _label(_LENGTHS, settings.get("reply_length", "normal"))},
            {"key": "captions", "kind": "toggle", "label": "Napisy",
             "sub": "jej słowa na dole ekranu", "value": bool(settings.get("captions", False))},
            {"key": "status_bar", "kind": "toggle", "label": "Pasek u góry",
             "sub": "godzina, pogoda, minutniki", "value": settings.get("status_bar", True) is not False},
        ]
    name = TABS[tab]
    if name == "Asystent":                # who she is: the theme, its character's own rows
        th = themes.get()
        who, speed = _speed_of()
        return [{"key": "theme", "kind": "cycle", "label": "Motyw",
                 "sub": th["sub"], "value": th["label"]},
                {"key": "tts_speed", "kind": "cycle", "label": "Tempo mowy",
                 "sub": f"dla: {who} (własne)" if who else "wspólne dla całego domu",
                 "value": f"{speed:.1f}×".replace(".", ",")}] + char_rows(th)
    if name == "Ekran":
        return [
            {"key": "brightness", "kind": "cycle", "label": "Jasność",
             "sub": "zmienia od razu; w nocy i po ciemku przygasa sama",
             "value": f"{display_base()} %"},
            {"key": "camera_preview", "kind": "toggle", "label": "Podgląd kamery",
             "sub": "mały obraz z kamery w rogu",
             "value": bool(settings.get("camera_preview", CAMERA_PREVIEW))},
            {"key": "draw_fps", "kind": "cycle", "label": "Płynność twarzy",
             "sub": "klatki na sekundę; mniej = chłodniejszy procesor",
             "value": f"{draw_fps()} kl./s"},
        ]
    if name == "Ikony":
        return dock_rows()
    if name == "Urządzenia":
        return device_rows()
    if name == "Koszty":
        return cost_rows()
    if name == "Osoby":
        return people_rows()
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


_people_page = [0]
_bin_armed = [None, 0.0]       # (name, when) — the bin tapped once


def _ago(t, now=None):
    """"widziałam dziś" / "wczoraj" / "5 dni temu"."""
    import datetime
    if not t:
        return "dawno nie widziałam"
    days = (datetime.date.fromtimestamp(now or time.time())
            - datetime.date.fromtimestamp(t)).days
    return ("widziałam dziś" if days <= 0 else "widziałam wczoraj" if days == 1 else
            f"widziałam {days} dni temu")


def people_rows(now=None):
    """One row per person (family first, then guests seen last first), a
    page switch when there are many, and how to add someone."""
    import faces
    fam = faces.family()
    rest = sorted(faces.guests(), key=lambda n: -(faces.last_seen(n) or 0))
    everyone = fam + rest
    pages = max(1, -(-len(everyone) // PEOPLE_PER_PAGE))
    page = _people_page[0] % pages
    out = []
    for n in everyone[page * PEOPLE_PER_PAGE:(page + 1) * PEOPLE_PER_PAGE]:
        f = n in fam
        out.append({"key": "person:" + n, "kind": "person", "label": n,
                    "sub": ("rodzina" if f else "gość") + " · " + _ago(faces.last_seen(n), now),
                    "value": "Rodzina" if f else "Gość",
                    "armed": _bin_armed[0] == n and time.time() - _bin_armed[1] < BIN_SECS})
    if pages > 1:
        out.append({"key": "people_page", "kind": "cycle", "label": "Więcej osób",
                    "sub": f"{len(everyone)} osób", "value": f"{page + 1} z {pages}"})
    out.append({"kind": "info", "label": "Nowa osoba",
                "sub": "powie mi „jestem Kasia” — będzie gościem",
                "value": ""})
    return out


def _outsider_here():
    """A guest or a stranger in front of her: the family decides who is who."""
    import faces
    with state.lock:
        unknown = state.person is None and state.face_detected
    return faces.guest_here() or bool(unknown and faces.names()
                                      and not faces.probably_family())


def person_change(key, binned=False, now=None, sure=True):
    """The family/guest switch or the bin on a person's row. Returns the toast,
    or "ask" when taking someone out of the family and not `sure` yet."""
    import faces
    _cache.clear()
    if key == "people_page":
        _people_page[0] += 1
        return None
    name = key.split(":", 1)[1]
    if _outsider_here():
        return "Poproś kogoś z rodziny"
    now = now or time.time()
    if binned:
        if _bin_armed[0] == name and now - _bin_armed[1] < BIN_SECS:
            _bin_armed[:] = [None, 0.0]
            faces.forget(name)
            return f"Zapomniałam: {name} (przywróć osobę — wróci)"
        _bin_armed[:] = [name, now]
        return f"Dotknij kosza jeszcze raz, by zapomnieć: {name}"
    on = not faces.is_family(name)
    if not on and faces.family() == [name]:
        return "Ktoś musi zostać w rodzinie"
    if not on and not sure:
        return "ask"
    faces.set_family(name, on)
    return f"{name}: z rodziny" if on else f"{name}: gość"


def _speed_of():
    """(who, speed): the speed she speaks at for the person in front of her —
    theirs if they set one by voice (settings "tts_speed_by"), else the
    house's (who None). 22 Oct: the page changed the house's while
    Andrzej's own 1.0 won — "the setting does nothing"."""
    with state.lock:
        who = state.person[0] if state.person else None
    by = settings.get("tts_speed_by", {}) or {}
    if who and by.get(who):
        return who, by[who]
    return None, settings.get("tts_speed", OPENAI_TTS_SPEED)


def _acc_label(names):
    return ", ".join(characters.ACC_LABELS.get(n, n) for n in names) or "bez dodatków"


def char_rows(th):
    """A drawn character's own rows (characters.py): its accessories, RETRO's
    case, how lively its effects are."""
    kind = characters.kind_of(th)
    if not kind:
        return []
    rows = [{"key": "char_acc", "kind": "cycle", "label": "Dodatki",
             "sub": "co nosi " + th["label"], "value": _acc_label(characters.accessories(kind))}]
    if kind == "retro":
        rows.append({"key": "retro_mode", "kind": "toggle", "label": "Obudowa konsoli",
                     "sub": "cała konsola albo sam ekran z twarzą",
                     "value": characters.retro_console()})
    rows.append({"key": "char_fx", "kind": "cycle", "label": "Efekty postaci",
                 "sub": "ruch, poświata i drobinki; mniej = lżej dla procesora",
                 "value": _label([(k, l) for k, l, _ in characters.FX_LEVELS],
                                 settings.get("char_fx", "full"))})
    return rows


def change(key):
    """A tap on a row's control: the next value. Returns the toast text."""
    _cache.clear()
    if key == "language":
        new = _next(_LANGS, language())
        settings.put("language", new)
        return f"Język: {_label(_LANGS, new)}"
    if key == "tts_speed":
        who, cur = _speed_of()
        new = next((s for s in _SPEEDS if s > cur + 0.01), _SPEEDS[0])
        if who:                              # their own speed ("mów wolniej") wins: change it
            by = dict(settings.get("tts_speed_by", {}) or {})
            by[who] = new
            settings.put("tts_speed_by", by)
        else:
            settings.put("tts_speed", new)
        return f"Tempo mowy {new:.1f}×".replace(".", ",") + (f" ({who})" if who else "")
    if key == "reply_length":
        new = _next(_LENGTHS, settings.get("reply_length", "normal"))
        settings.put("reply_length", new)
        return f"Odpowiedzi: {_label(_LENGTHS, new).lower()}"
    if key == "theme":
        keys = list(themes.THEMES)
        new = keys[(keys.index(themes.current()) + 1) % len(keys)]
        themes.set_theme(new)
        threading.Thread(target=_introduce, args=(new,), daemon=True, name="theme").start()
        return f"Motyw: {themes.THEMES[new]['label']}"
    if key == "volume":
        import commands
        cur = commands.get_volume() or 0.0
        new = next((v for v in _VOLUMES if v > cur + 0.01), _VOLUMES[0])
        v = commands.set_volume(new)
        threading.Thread(target=_say_volume, daemon=True, name="volume").start()
        return f"Głośność {round(v * 100)} %"
    if key == "night_quiet":
        new = settings.get("night_quiet", True) is False
        settings.put("night_quiet", new)
        return "Ciszej w nocy: tak" if new else "W nocy tak samo głośno"
    if key == "brightness":
        cur = display_base()
        new = next((b for b in _BRIGHT if b < cur), _BRIGHT[0])
        settings.put("brightness", new)
        import display
        display.set_user_override(new)   # seen now, at night too (22 Oct: "not working" —
        return f"Jasność {new} %"        # the night cap held it at 12 %)
    if key == "char_acc":
        kind = characters.kind_of(themes.get())
        if not kind:
            return None
        choices = characters.acc_choices(kind)
        cur = characters.accessories(kind)
        i = next((j for j, c in enumerate(choices) if set(c) == set(cur)), -1)
        new = choices[(i + 1) % len(choices)]
        characters.set_accessories(kind, new)
        return f"Dodatki: {_acc_label(new)}"
    if key == "retro_mode":
        new = "face" if characters.retro_console() else "console"
        settings.put("retro_mode", new)
        characters._scache.clear()
        return "Cała konsola" if new == "console" else "Sam ekran"
    if key == "char_fx":
        levels = [(k, l) for k, l, _ in characters.FX_LEVELS]
        new = _next(levels, settings.get("char_fx", "full"))
        settings.put("char_fx", new)
        characters._scache.clear()
        return f"Efekty: {_label(levels, new)}"
    if key in dict(_DEVICES):
        label = devices.pick_next(key)
        if key == "speaker":
            threading.Thread(target=_say_speaker, daemon=True, name="speaker-hello").start()
        return f"{dict(_DEVICES)[key]}: {label}"
    if key.startswith("dock:"):
        import dock
        k = key[5:]
        on = k not in dock.chosen()
        dock.choose(k, on)
        label = dict(dock.ITEMS)[k]
        if on and not dock.enabled():          # (the row was off: a tile ticked wants it)
            settings.put("dock", True)
        return f"{label}: na dole" if on else f"{label}: schowane"
    if key == "draw_fps":
        new = _next(_FPS, draw_fps())
        settings.put("draw_fps", new)
        return f"Płynność: {new} klatek na sekundę"
    defaults = {"captions": False, "status_bar": True, "dock": True,
                "camera_preview": CAMERA_PREVIEW}
    if key in defaults:
        cur = settings.get(key, defaults[key])
        new = not (cur is not False if key in ("status_bar", "dock") else bool(cur))
        settings.put(key, new)
        return "Włączone" if new else "Wyłączone"
    return None


def display_base():
    import display
    return display.base_percent()


def _say_volume():
    """The new volume, heard (the tap was someone in front of her)."""
    from text_to_speech import play_sound_async
    time.sleep(0.2)
    play_sound_async("mhm")


def _introduce(key):
    """A new theme says hello in its own voice (it was tapped: someone's there)."""
    from text_to_speech import speak
    time.sleep(0.3)
    if themes.current() == key:            # (not tapped on past it already)
        speak(themes.THEMES[key]["hello"])


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
        who = data.pop("confirm_who", None)
        if now - data["confirm"] > CONFIRM_SECS or hit == ("no",) or not hit:
            data["confirm"] = None
        elif hit == ("yes",) and who:
            data["confirm"] = None
            _toast(data, person_change("person:" + who, now=now))
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
    elif hit[0] == "bin":
        r = rows(data.get("tab", 0))[hit[1]]
        _toast(data, person_change(r["key"], binned=True, now=now))
    elif hit[0] == "row":
        r = rows(data.get("tab", 0))[hit[1]]
        if r.get("key", "").startswith("person:") or r.get("key") == "people_page":
            said = person_change(r["key"], now=now, sure=False)
            if said == "ask":                   # out of the family: "Na pewno?" first
                data["confirm"], data["confirm_who"] = now, r["key"].split(":", 1)[1]
            elif said:
                _toast(data, said)
        elif r["kind"] == "danger":
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
