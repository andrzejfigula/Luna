"""
hangman.py — "zagrajmy w wisielca": guess the word letter by letter (ideas #26).

A word from a checked list for a child, blanks on her screen, a Polish
keyboard below (32 letters) and the gallows drawn a piece per miss — 8 misses
and it's over. Letters by touch or by voice ("ka", "litera em", "a z
ogonkiem"), the whole word by voice ("to jest kot"). "Podpowiedź" says the
category, then uncovers a letter; "powtórz" says where they are; "koniec"
ends it and tells the word; "jeszcze raz" deals a new one.
robot_face.py draws it ("hang" overlay, ui_screens.draw_hangman) and passes
the taps here.
"""

import random
import re
import threading
import time

from shared_state import state

IDLE_SECS = 180
MISSES = 8
ALPHABET = "aąbcćdeęfghijklłmnńoóprsśtuwyzźż"
KEYS = (8, 4, 88, 52, 8, 238)          # cols, rows, w, h, gap, top (800 × 480)

WORDS = {
    "zwierzę": "kot pies koń krowa owca koza kura kaczka gęś mysz żaba ryba wilk lis "
               "niedźwiedź zając jeż sowa bocian wiewiórka słoń żyrafa zebra lew tygrys "
               "małpa pingwin foka delfin motyl pszczoła biedronka ślimak papuga chomik "
               "królik wąż krokodyl wielbłąd kangur",
    "owoc": "jabłko gruszka śliwka wiśnia banan ananas cytryna truskawka malina arbuz "
            "winogrono pomarańcza brzoskwinia jagoda",
    "warzywo": "marchew ogórek pomidor ziemniak cebula kapusta papryka groszek rzodkiewka "
               "dynia sałata burak",
    "coś w domu": "stół krzesło łóżko szafa lampa okno drzwi dywan poduszka kołdra lustro "
                  "zegar telewizor lodówka wanna czajnik kubek talerz widelec łyżka garnek",
    "coś ze szkoły": "zeszyt ołówek gumka linijka plecak tablica kreda książka piórnik "
                     "nożyczki klej kredka ławka dzwonek",
    "coś z przyrody": "drzewo kwiat słońce księżyc gwiazda chmura deszcz śnieg tęcza góra "
                      "rzeka jezioro morze las łąka kamień liść grzyb wiatr",
    "pojazd": "auto rower pociąg samolot statek autobus tramwaj rakieta hulajnoga łódka "
              "traktor helikopter",
    "coś do jedzenia": "chleb masło ser zupa pizza naleśnik pierogi lody ciastko czekolada "
                       "cukierek makaron jajko mleko kanapka",
}

_START = re.compile(r"\bw\s+wisielc\w*|\bwisiel(?:ec|ca|cem)\b|\bgr[ęay]\w*\s+w\s+szubienic", re.I)
_ASK = re.compile(r"\b(?:zagrajmy|zagramy|pograjmy|zagraj|gramy|chcę|chce|możemy|mozemy|"
                  r"pobawmy|włącz|wlacz)\b", re.I)
_HARD = re.compile(r"\btrudn\w*|\bdług\w*\s+słow|\bdla\s+dorosłych", re.I)
_STOP = re.compile(r"\b(?:koniec|wystarczy|kończymy|konczymy|stop|przestań|przestan|dość|dosc|"
                   r"poddaj[eę]\s+się|poddaje\s+sie|nie\s+chc[eę]\s+(?:już\s+|juz\s+)?gra[ćc]|"
                   r"nie\s+gramy)\b")
_HINT = re.compile(r"\b(?:podpowied\w*|podpowiedz|pom[óo]ż|pomocy|nie\s+wiem|wskazówk\w*|"
                   r"jaka\s+kategori\w*|co\s+to\s+(?:jest\s+)?za\s+słow\w*)\b")
_REPEAT = re.compile(r"\b(?:powtórz|powtorz|ile\s+(?:liter|szans|zostało|zostalo)|"
                     r"jakie\s+litery|co\s+już\s+mam|co\s+mam|jak\s+(?:to\s+)?wygląda)\b")
_AGAIN = re.compile(r"\b(?:jeszcze\s+raz|nowa\s+gra|nowe\s+słowo|od\s+nowa|zagrajmy\s+jeszcze|"
                    r"następne\s+słowo|kolejne\s+słowo|inne\s+słowo|rewanż)\b")
_YES = {"tak", "dobrze", "jasne", "pewnie", "chcę", "chce", "okej", "ok", "gramy"}
_NO = {"nie", "dziękuję", "dziekuje", "wystarczy"}
_NAMES = {"a": "a", "be": "b", "ce": "c", "cie": "ć", "de": "d", "e": "e", "ef": "f",
          "gie": "g", "gje": "g", "ha": "h", "i": "i", "jot": "j", "ka": "k", "el": "l",
          "eł": "ł", "em": "m", "en": "n", "eń": "ń", "o": "o", "pe": "p", "er": "r",
          "es": "s", "eś": "ś", "te": "t", "u": "u", "wu": "w", "igrek": "y", "zet": "z",
          "ziet": "ź", "żet": "ż"}
_MARK = {("a", "ogon"): "ą", ("e", "ogon"): "ę", ("c", "kres"): "ć", ("n", "kres"): "ń",
         ("o", "kres"): "ó", ("u", "zamk"): "ó", ("s", "kres"): "ś", ("z", "kres"): "ź",
         ("z", "krop"): "ż", ("l", "kres"): "ł", ("l", "prze"): "ł"}
_FILL = {"luna", "litera", "literę", "litere", "literka", "literkę", "literke", "czy", "jest",
         "może", "moze", "chyba", "wybieram", "daj", "poproszę", "poprosze", "proszę", "prosze",
         "spróbuję", "sprobuje", "próbuję", "probuje", "teraz", "no", "to", "słowo", "slowo",
         "hasło", "haslo", "ma", "tam"}

_lock = threading.Lock()
_g = None   # {"word", "cat", "hit", "miss", "end", "hints", "msg", "voice"}


def wants(text):
    if not _START.search(text) or len(text.split()) > 9:
        return False
    return len(re.findall(r"\w+", text)) <= 3 or bool(_ASK.search(text))


def hard_wanted(text):
    return bool(_HARD.search(text))


def active():
    with state.lock:
        ov = state.overlay
    return bool(ov) and ov[0] == "hang" and time.time() < ov[1]


def _shown(g):
    return " ".join(ch if ch in g["hit"] or g["end"] else "_" for ch in g["word"])


def prompt_line():
    """While the game is on: where they are — never the word itself."""
    g = _g
    if not g or not active():
        return ""
    if g["end"]:
        return f"Hangman on your screen: the game is over, the word was {g['word']}.\n"
    return (f"Hangman (wisielec) on your screen: the word has {len(g['word'])} letters, "
            f"shown so far: {_shown(g)}; missed letters: {', '.join(g['miss']) or 'none'}; "
            f"{MISSES - len(g['miss'])} chances left. Letters are guessed by touch or by "
            "voice and she checks them herself; never say or hint the word.\n")


def _publish():
    g = _g
    data = {"word": g["word"], "hit": set(g["hit"]), "miss": list(g["miss"]), "end": g["end"],
            "won": g["end"] and _won(g), "msg": g["msg"], "keys": KEYS}
    with state.lock:
        state.overlay = ("hang", time.time() + IDLE_SECS, data)


def _won(g):
    return all(ch in g["hit"] for ch in g["word"])


def _deal(hard=None):
    global _g
    hard = bool(_g and _g.get("hard")) if hard is None else hard
    last = _g["word"] if _g else None
    pool = [(w, cat) for cat, ws in WORDS.items() for w in ws.split()
            if w != last and (len(w) >= 7 if hard else len(w) <= 7)]
    word, cat = random.choice(pool)
    _g = {"word": word, "cat": cat, "hit": set(), "miss": [], "end": False, "hints": 0,
          "hard": hard, "msg": f"{len(word)} liter · zgaduj!"}
    print(f"[hangman] new word ({len(word)} letters, {cat})", flush=True)
    _publish()


def _liter(n):
    import calc
    return f"{n} {calc._plural(n, 'litera', 'litery', 'liter')}"


def _chances(n):
    import calc
    return f"{calc._plural(n, 'Została', 'Zostały', 'Zostało')} {n} " \
           f"{calc._plural(n, 'szansa', 'szanse', 'szans')}"


def start(speak, hard=False):
    with _lock:
        _deal(hard)
        n = len(_g["word"])
    speak(f"Gramy w wisielca! Moje słowo ma {_liter(n)}. Mów litery albo dotykaj ich na ekranie.")
    _keep_listening()


def again(speak):
    with _lock:
        if not _g:
            return False
        _deal()
        n = len(_g["word"])
    speak(f"Nowe słowo — {_liter(n)}. Zgaduj!")
    _keep_listening()
    return True


def stop():
    global _g
    with _lock:
        _g = None
    with state.lock:
        if state.overlay and state.overlay[0] == "hang":
            state.overlay = None


def _keep_listening():
    with state.lock:
        state.conversation_active = True
        state.last_activity_time = max(state.last_activity_time, time.time() + 20)


def _say(text):
    try:
        from text_to_speech import speak
        speak(text)
    except Exception as e:
        print(f"[hangman] could not speak ({e})", flush=True)


def _guess(ch):
    """A letter tried (under _lock). What to say, or None for a repeat."""
    g = _g
    if ch in g["hit"] or ch in g["miss"]:
        g["msg"] = f"{ch.upper()} już było"
        return f"{ch.upper()} już było."
    if ch in g["word"]:
        g["hit"].add(ch)
        n = g["word"].count(ch)
        if _won(g):
            return _finish()
        g["msg"] = f"Jest {ch.upper()}!"
        return f"Jest {ch.upper()}!" + (" Aż dwa razy." if n == 2 else
                                         f" Aż {n} razy." if n > 2 else "")
    g["miss"].append(ch)
    if len(g["miss"]) >= MISSES:
        return _finish()
    left = MISSES - len(g["miss"])
    g["msg"] = f"Nie ma {ch.upper()} · szanse: {left}"
    return f"Nie ma {ch.upper()}." + (f" {_chances(left)}." if left <= 3 else "")


def _finish():
    g = _g
    g["end"] = True
    won = _won(g)
    print(f"[hangman] {'won' if won else 'lost'}: {g['word']} ({len(g['miss'])} misses)",
          flush=True)
    g["msg"] = ("Brawo!" if won else "Tym razem nie…") + " · dotknij = nowe słowo"
    with state.lock:                          # "jeszcze raz" needs no "Luna"
        state.conversation_active = True
        state.last_activity_time = time.time() + 5
    if won:
        return (f"Brawo! To słowo to {g['word']}!" +
                (" Bez ani jednej pomyłki!" if not g["miss"] else "") + " Jeszcze raz?")
    return f"Ojej, wisielec gotowy. To było słowo: {g['word']}. Jeszcze raz?"


def key_at(nx, ny, width=800, height=480):
    """The letter under a tap (normalised coords), or None."""
    cols, rows, kw, kh, gap, top = KEYS
    x, y = nx * width, ny * height
    left = (width - (cols * kw + (cols - 1) * gap)) // 2
    col, cx = divmod(int(x - left), kw + gap)
    row, cy = divmod(int(y - top), kh + gap)
    if x < left or y < top or col >= cols or row >= rows or cx >= kw or cy >= kh:
        return None
    i = row * cols + col
    return ALPHABET[i] if i < len(ALPHABET) else None


def tap(nx, ny, width=800, height=480):
    """A tap on the board. Returns True when it was used."""
    said = None
    with _lock:
        if not _g:
            return False
        if _g["end"]:
            _deal()
            return True
        ch = key_at(nx, ny, width, height)
        if not ch:
            return True
        said = _guess(ch)
        _publish()
        end = _g["end"]
    if end:                                   # a tap is quiet; the end is said
        threading.Thread(target=_say, args=(said,), daemon=True).start()
    return True


def letter(text):
    """The one letter said ("ka", "litera em", "a z ogonkiem", "Ż."), or None."""
    words = [w for w in re.findall(r"\w+", text.lower()) if w not in _FILL]
    if len(words) >= 3 and words[1] in ("z", "ze"):
        base = _NAMES.get(words[0], words[0] if len(words[0]) == 1 else "")
        return _MARK.get((base, words[2][:4]))
    if len(words) == 2 and words[1][:4] in ("zamk", "kres", "otwa"):
        base = _NAMES.get(words[0], words[0] if len(words[0]) == 1 else "")
        return "u" if words[1].startswith("otwa") and base == "u" else _MARK.get((base, words[1][:4]))
    if len(words) == 2 and words[0] == "a":          # "a ka?" — "and k?"
        words = words[1:]
    if len(words) != 1:
        return None
    w = words[0]
    if len(w) == 1:
        return w if w in ALPHABET else None
    return _NAMES.get(w)


def _word_guess(text):
    """"to jest kot", "hasło to żaba", "kot" (as long as the word): the word, or None."""
    g = _g
    low = text.lower()
    words = [w for w in re.findall(r"\w+", low) if w not in _FILL]
    if (len(words) != 1 or len(words[0]) < 3 or words[0] in _NAMES or words[0] in _YES
            or words[0] in _NO):
        return None
    w = words[0]
    said_it = re.search(r"\b(?:to|hasło|haslo|słowo|slowo)\b", low)
    if not all(ch in ALPHABET for ch in w) or not (said_it or len(w) == len(g["word"])):
        return None
    return w


def answer(text, speak):
    """An utterance while the board is up. True when it was about the game."""
    low = text.lower().strip(" .!?")
    words = re.findall(r"\w+", low)
    with _lock:
        g = _g
        if not g:
            return False
        end = g["end"]
    if end:                                           # "Jeszcze raz?" — "tak" / "nie"
        if _AGAIN.search(low) or (words and words[0] in _YES and len(words) <= 3):
            return again(speak)
        if _STOP.search(low) or (words and words[0] in _NO and len(words) <= 3):
            stop()
            speak("Dobrze, koniec gry. Dzięki!")
            return True
        return False
    if _AGAIN.search(low) and len(words) <= 5:
        return again(speak)
    if _STOP.search(low) and len(words) <= 6:
        word = g["word"]
        stop()
        speak(f"Dobrze, kończymy. Moje słowo to było: {word}.")
        return True
    with _lock:
        if _HINT.search(low) and len(words) <= 6:
            g["hints"] += 1
            missing = [ch for ch in g["word"] if ch not in g["hit"]]
            if g["hints"] == 1 or len(set(missing)) <= 1:
                said = f"Podpowiedź: to {g['cat']}."
            else:
                ch = random.choice(missing)
                g["hit"].add(ch)
                said = f"Podpowiem literę: {ch.upper()}."
                if _won(g):
                    said = _finish()
            _publish()
        elif _REPEAT.search(low) and len(words) <= 6:
            left = MISSES - len(g["miss"])
            got = sorted(g["hit"], key=g["word"].index)
            said = (f"Słowo ma {_liter(len(g['word']))}. "
                    + (f"Odgadnięte: {', '.join(c.upper() for c in got)}. " if got else "")
                    + (f"Pudła: {', '.join(c.upper() for c in g['miss'])}. " if g["miss"] else "")
                    + f"{_chances(left)}.")
        else:
            ch = letter(text) if len(words) <= 5 else None
            w = None if ch else _word_guess(text) if len(words) <= 5 else None
            if ch:
                said = _guess(ch)
            elif w:
                if w == g["word"]:
                    g["hit"] |= set(w)
                    said = _finish()
                else:
                    g["miss"].append(w)
                    said = (_finish() if len(g["miss"]) >= MISSES else
                            f"To nie {w}. {_chances(MISSES - len(g['miss']))}.")
                    if not g["end"]:
                        g["msg"] = f"Nie {w} · szanse: {MISSES - len(g['miss'])}"
            else:
                return False
            _publish()
    speak(said)
    _keep_listening()
    return True
