"""
memo.py — the memory game on her touchscreen ("zagrajmy w memory", "w pary").

Twelve cards face down, six pairs of coloured shapes. Tap a card to turn it,
tap a second one: a pair stays up, two different ones turn back after a
moment. When all pairs are found she says how many moves it took, and
remembers each player's best (by face) — "Nowy rekord!". A tap after the end
deals again; "koniec" ends it; the board closes after IDLE_SECS without a tap.
robot_face.py draws it ("memo" overlay) and passes the taps here.
"""

import random
import re
import threading
import time

from shared_state import state

IDLE_SECS = 120
COLS, ROWS = 4, 3
CARD_W, CARD_H, GAP = 150, 130, 14
SHAPES = ("circle", "square", "triangle", "star", "heart", "diamond", "moon", "cross")
LAYOUTS = {12: (4, 3, 150, 130, 14), 16: (4, 4, 150, 104, 10)}   # cols, rows, w, h, gap
_HARD = re.compile(r"\b(?:trudn\w*|duż\w*|duz\w*|16|szesnaście|dla\s+dorosłych|większ\w*)\b",
                   re.I)
_START = re.compile(r"\b(?:memory|memo|pary|parki|w\s+pamięć|gr[ęa]\s+pamięciow\w*)\b", re.I)
_ASK = re.compile(r"\b(?:zagrajmy|zagramy|pograjmy|zagraj|gramy|chcę|chce|możemy|mozemy|"
                  r"pobawmy|włącz|wlacz)\b", re.I)

_lock = threading.Lock()
_g = None          # {"cards": [shape]*12, "up": set, "found": set, "moves", "end", "msg", "who"}


def wants(text):
    if not _START.search(text) or len(text.split()) > 9:
        return False
    return len(re.findall(r"\w+", text)) <= 3 or bool(_ASK.search(text))


def active():
    with state.lock:
        ov = state.overlay
    return bool(ov) and ov[0] == "memo" and time.time() < ov[1]


def _publish():
    data = {"cards": list(_g["cards"]), "up": set(_g["up"]) | set(_g["found"]),
            "found": set(_g["found"]), "msg": _g["msg"],
            "layout": LAYOUTS[len(_g["cards"])]}
    with state.lock:
        state.overlay = ("memo", time.time() + IDLE_SECS, data)


def _deal(hard=None):
    global _g
    with state.lock:
        who = state.person[0] if state.person else None
    hard = bool(_g and _g.get("n") == 16) if hard is None else hard
    n = 16 if hard else 12
    cards = list(SHAPES[:n // 2]) * 2
    random.shuffle(cards)
    _g = {"cards": cards, "up": [], "found": set(), "moves": 0, "end": False, "n": n,
          "msg": "Znajdź pary!", "who": who, "busy": False}
    _publish()


def start(speak, hard=False):
    with _lock:
        _deal(hard)
    speak("Trudne memory — szesnaście kart! Dotknij dwóch, szukamy par." if hard else
          "Gramy w memory! Dotknij dwóch kart — szukamy par.")


def hard_wanted(text):
    return bool(_HARD.search(text))


def stop():
    global _g
    with _lock:
        _g = None
    with state.lock:
        if state.overlay and state.overlay[0] == "memo":
            state.overlay = None


def _say(text):
    try:
        from text_to_speech import speak
        speak(text)
    except Exception as e:
        print(f"[memo] could not speak ({e})", flush=True)


def card_at(nx, ny, width=800, height=480, n=12):
    """The card under a tap (normalised coords), or None."""
    cols, rows, cw, ch, gap = LAYOUTS[n]
    x, y = nx * width, ny * height
    left = (width - (cols * cw + (cols - 1) * gap)) // 2
    top = (height - (rows * ch + (rows - 1) * gap)) // 2
    col, cx = divmod(int(x - left), cw + gap)
    row, cy = divmod(int(y - top), ch + gap)
    if x < left or y < top or col >= cols or row >= rows or cx >= cw or cy >= ch:
        return None
    return row * cols + col


def _finish():
    import settings
    g = _g
    g["end"] = True
    moves, who = g["moves"], g["who"]
    best = settings.get("memo_best", {}) or {}
    key = f"{who or '?'}:{len(g['cards'])}"          # 12 and 16 cards apart
    record = key in best and moves < best[key]
    if key not in best or moves < best[key]:
        best[key] = moves
        settings.put("memo_best", best)
    said = f"Brawo! Wszystkie pary w {moves} ruchach."
    if record:
        said += " Nowy rekord!"
    elif key in best and best[key] < moves:
        said += f" Twój rekord to {best[key]}."
    g["msg"] = f"{moves} ruchów · dotknij = nowa gra"
    print(f"[memo] done in {moves} moves ({key})", flush=True)
    threading.Thread(target=_say, args=(said,), daemon=True).start()
    with state.lock:                          # "jeszcze raz" needs no "Luna"
        state.conversation_active = True
        state.last_activity_time = time.time() + 5


def _turn_back(pair):
    time.sleep(1.0)
    with _lock:
        if _g and _g["up"] == pair:
            _g["up"] = []
            _g["busy"] = False
            _publish()


def tap(nx, ny, width=800, height=480):
    """A tap on the board. Returns True when it was used."""
    with _lock:
        if not _g:
            return False
        if _g["end"]:
            _deal()
            return True
        if _g["busy"]:
            return True                         # two cards are showing — wait
        i = card_at(nx, ny, width, height, len(_g["cards"]))
        if i is None or i in _g["found"] or i in _g["up"]:
            return True
        _g["up"].append(i)
        if len(_g["up"]) == 2:
            _g["moves"] += 1
            a, b = _g["up"]
            if _g["cards"][a] == _g["cards"][b]:
                _g["found"] |= {a, b}
                _g["up"] = []
                if len(_g["found"]) == len(_g["cards"]):
                    _finish()
                else:
                    _g["msg"] = "Para!"
            else:
                _g["busy"] = True
                _g["msg"] = "Nie pasują…"
                threading.Thread(target=_turn_back, args=(list(_g["up"]),),
                                 daemon=True).start()
        else:
            _g["msg"] = f"Ruchy: {_g['moves']}"
        _publish()
    return True


def again(speak):
    with _lock:
        if not _g:
            return False
        _deal()
    speak("Tasuję! Nowa gra.")
    return True
