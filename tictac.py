"""
tictac.py — noughts and crosses on her touchscreen ("zagrajmy w kółko i krzyżyk").

You are X and tap a square; Luna is O and answers after a moment's thought.
With a child she plays loosely (half her moves are a guess) so a game can be
won; with a grown-up she rarely slips. After a game a tap starts the next one,
and whoever didn't start last time starts. The board times out after
IDLE_SECS without a tap. robot_face.py draws it ("ttt" overlay) and passes
the taps here.
"""

import random
import re
import threading
import time

from shared_state import state

IDLE_SECS = 90
_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8),
          (0, 4, 8), (2, 4, 6))
_START = re.compile(r"\b(?:kółko\s+i\s+krzyżyk|kolko\s+i\s+krzyzyk|tic[\s-]?tac[\s-]?toe)\b",
                    re.I)

_lock = threading.Lock()
_g = None        # {"b": [None|"X"|"O"]*9, "turn", "end", "line", "first", "loose", "msg"}


def wants(text):
    """Asked for — not "koleżanka gra w kółko i krzyżyk na lekcjach"."""
    if not _START.search(text) or len(text.split()) > 9:
        return False
    return len(re.findall(r"\w+", text)) <= 5 or bool(re.search(
        r"\b(?:zagrajmy|zagramy|pograjmy|zagraj|gramy|chcę|chce|możemy|mozemy|"
        r"pobawmy|włącz|wlacz)\b", text, re.I))


def active():
    with state.lock:
        ov = state.overlay
    return bool(ov) and ov[0] == "ttt" and time.time() < ov[1]


def _winner(b):
    for line in _LINES:
        a, c, d = (b[i] for i in line)
        if a and a == c == d:
            return a, line
    if all(b):
        return "draw", None
    return None, None


def _minimax(b, me, turn, depth=0):
    """(score, move) for `me` with `turn` to play: a win sooner scores more
    (10 - depth), a loss later scores less badly, a draw 0."""
    w, _ = _winner(b)
    if w == me:
        return 10 - depth, None
    if w == "draw":
        return 0, None
    if w:
        return depth - 10, None
    best = None
    for i in range(9):
        if b[i]:
            continue
        b[i] = turn
        s, _ = _minimax(b, me, "O" if turn == "X" else "X", depth + 1)
        b[i] = None
        if best is None or (s > best[0] if turn == me else s < best[0]):
            best = (s, i)
    return best


def best_move(b, me="O"):
    free = [i for i in range(9) if not b[i]]
    if len(free) == 9:
        return random.choice((0, 2, 4, 6, 8))       # an opening with some variety
    return _minimax(list(b), me, me)[1]


def _publish():
    with state.lock:
        state.overlay = ("ttt", time.time() + IDLE_SECS, dict(_g))


def _child():
    try:
        import faces
        with state.lock:
            who = state.person[0] if state.person else None
        return bool(who) and "dziecko" in faces.notes().get(who, "").lower(), who
    except Exception:
        return False, None


_DUO = re.compile(r"\b(?:we\s+dwoje|we\s+dwójkę|we\s+dwojke|dla\s+dwóch|dla\s+dwojga|"
                  r"z\s+mamą|z\s+tatą|z\s+mama|z\s+tata|z\s+siostrą|z\s+bratem|"
                  r"z\s+koleżanką|z\s+kolegą|dwóch\s+graczy|2\s+graczy)\b", re.I)


def duo_wanted(text):
    """"…we dwoje", "…z mamą": two people on the board, Luna only referees."""
    return bool(_DUO.search(text))


def _new_game(first, duo=None):
    global _g
    loose, _ = _child()
    duo = _g.get("duo", False) if duo is None and _g else bool(duo)
    _g = {"b": [None] * 9, "turn": first, "end": None, "line": None, "first": first,
          "loose": 0.5 if loose else 0.1, "duo": duo,
          "msg": (f"Ruch: {'krzyżyk' if first == 'X' else 'kółko'}" if duo else
                  "Twój ruch" if first == "X" else "Myślę…")}
    _publish()
    if first == "O" and not duo:
        threading.Timer(0.9, _luna_moves).start()


def start(speak, duo=False):
    with _lock:
        _new_game("X", duo)
    speak("Gramy we dwoje! Zaczyna krzyżyk — dotykajcie pól po kolei." if duo else
          "Gramy! Ty jesteś krzyżyk — dotknij pola na ekranie.")


def again(speak):
    """"Jeszcze raz" / "rewanż": the next game, the other side starting."""
    with _lock:
        if not _g:
            return False
        first = "O" if _g["first"] == "X" else "X"
        _new_game(first)
        duo = _g["duo"]
    if duo:
        speak(f"Rewanż! Zaczyna {'kółko' if first == 'O' else 'krzyżyk'}.")
    else:
        speak("Rewanż! Zaczynam ja." if first == "O" else "Nowa gra — zaczynasz ty!")
    return True


def stop():
    global _g
    with _lock:
        _g = None
    with state.lock:
        if state.overlay and state.overlay[0] == "ttt":
            state.overlay = None


def _say(text):
    try:
        from text_to_speech import speak
        speak(text)
    except Exception as e:
        print(f"[tictac] could not speak ({e})", flush=True)


def _finish(w, line):
    _g["end"], _g["line"] = w, line
    _, who = _child()
    if _g.get("duo"):                         # she only referees
        _g["msg"] = {"X": "Wygrywa krzyżyk!", "O": "Wygrywa kółko!"}.get(w, "Remis")
        said = {"X": "Wygrywa krzyżyk! Brawo!", "O": "Wygrywa kółko! Brawo!"}.get(
            w, "Remis! Jesteście równi.")
    elif w == "X":
        try:
            import faces
            won = "wygrałaś" if who and faces._female(who) else "wygrałeś" if who else "wygrana"
        except Exception:
            won = "wygrana"
        _g["msg"] = "Brawo!"
        said = random.choice((f"Brawo, {won}!", f"No proszę, {won}! Rewanż?"))
    elif w == "O":
        _g["msg"] = "Wygrałam!"
        said = random.choice(("Tym razem ja! Jeszcze raz?", "Mam trzy w rzędzie! Rewanż?"))
    else:
        _g["msg"] = "Remis"
        said = "Remis! Dotknij ekranu, zagramy jeszcze raz."
    _g["msg"] += " · dotknij = nowa gra"
    print(f"[tictac] game over: {w}", flush=True)
    with state.lock:                         # "jeszcze raz" needs no "Luna"
        state.conversation_active = True
        state.last_activity_time = time.time() + 5
    threading.Thread(target=_say, args=(said,), daemon=True).start()


def _luna_moves():
    with _lock:
        if not _g or _g["end"] or _g["turn"] != "O":
            return
        b = _g["b"]
        free = [i for i in range(9) if not b[i]]
        i = random.choice(free) if random.random() < _g["loose"] else best_move(b)
        b[i] = "O"
        w, line = _winner(b)
        if w:
            _finish(w, line)
        else:
            _g["turn"], _g["msg"] = "X", "Twój ruch"
        _publish()


def cell_at(nx, ny, width=800, height=480):
    """The square under a tap (normalised screen coords), or None — the
    board is a 420 px square in the middle (robot_face draws the same)."""
    x, y = nx * width, ny * height
    left, top, size = (width - 420) // 2, (height - 420) // 2, 420
    if not (left <= x < left + size and top <= y < top + size):
        return None
    return int((y - top) // 140) * 3 + int((x - left) // 140)


def tap(nx, ny, width=800, height=480):
    """A tap on the board. Returns True when it was used."""
    with _lock:
        if not _g:
            return False
        if _g["end"]:
            _new_game("O" if _g["first"] == "X" else "X")      # take turns starting
            return True
        if _g["turn"] != "X" and not _g["duo"]:
            return True                                         # she is thinking
        i = cell_at(nx, ny, width, height)
        if i is None or _g["b"][i]:
            return True
        mark = _g["turn"]
        _g["b"][i] = mark
        w, line = _winner(_g["b"])
        if w:
            _finish(w, line)
        elif _g["duo"]:
            _g["turn"] = "O" if mark == "X" else "X"
            _g["msg"] = f"Ruch: {'krzyżyk' if _g['turn'] == 'X' else 'kółko'}"
        else:
            _g["turn"], _g["msg"] = "O", "Myślę…"
            threading.Timer(0.8, _luna_moves).start()
        _publish()
    return True
