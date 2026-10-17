"""
weekly.py — her week in numbers, for the grown-ups.

  "Luna, podsumowanie tygodnia" / "raport tygodniowy" / "statystyki z tygodnia"

What she struggled to hear (noise taken for words, the cloud hearing nothing,
names she wasn't sure of, false wakes), what went wrong (the model failing,
"nie zrozumiałam", a crash in the voice loop), who talked with her most and
what the children asked about. Said in a few sentences, shown on her screen,
and written out in full to data/weekly.txt — so a problem shows up without
anyone reading luna.log (proposal 10, 17 Oct).

Counted from her own log lines as they are printed: a tee on stdout, so no
module needs to call in. Kept per day in data/weekly.json, two weeks back.
"""

import json
import os
import re
import sys
import threading
import time
from collections import Counter
from datetime import date, timedelta

from config import DATA_DIR
from shared_state import state

PATH = os.path.join(DATA_DIR, "weekly.json")
TEXT_PATH = os.path.join(DATA_DIR, "weekly.txt")
KEEP_DAYS = 14
KIDS_KEEP = 60                    # the children's sentences kept a day
SAVE_EVERY = 600

_PATTERNS = [
    ("noise", re.compile(r"^\[STT\] Dropped \(noise\)")),
    ("empty", re.compile(r"^\[STT\] cloud heard no speech")),
    ("false_wake", re.compile(r"^\[STT\] false wake")),
    ("unsure_name", re.compile(r"^\[STT\] (?:Wake ignored \(conf|unsure of the name)")),
    ("not_facing", re.compile(r"^\[STT\] (?:Wake ignored|Ignored) \(nobody facing me\)")),
    ("oops", re.compile(r"voice loop error")),
    ("model_fail", re.compile(r"^\[brain\].*(?:failed|error|timed out|timeout)", re.I)),
    ("not_understood", re.compile(r"^\[Luna\] .*(?:nie zrozumiałam|nie dosłyszałam|nie usłyszałam|"
                                  r"możesz powtórzyć|nie wiem, o co)", re.I)),
    ("radio_closed", re.compile(r"^\[Luna\] radio on — window closed")),
]
LABELS = {"heard": "zdania do mnie", "noise": "szum wzięty za słowa",
          "empty": "chmura nic nie usłyszała", "false_wake": "fałszywe wybudzenia",
          "unsure_name": "niepewne „Luna”", "not_facing": "mówione nie do mnie",
          "oops": "błędy w rozmowie", "model_fail": "błędy modelu",
          "not_understood": "„nie zrozumiałam”", "radio_closed": "radio zamknęło rozmowę"}

_lock = threading.Lock()
_days = None
_dirty = [False]
_STOP = set("""a i w z o na do że ze to co jak czy nie tak się sie mi ci mnie ja ty jest są
był była było luna luno no ale bo by już juz jeszcze tylko też tez jaki jaka jakie
który która które ten ta te tego tej tym moja mój moje twój twoja masz mam ma mamy
możesz mozesz powiedz proszę prosze opowiedz pokaż pokaz chcę chce dlaczego czemu
ile gdzie kiedy kto po od dla przez za pod nad dzisiaj dziś teraz""".split())


def _load():
    global _days
    if _days is not None:
        return
    try:
        with open(PATH, encoding="utf-8") as f:
            _days = json.load(f)
    except (OSError, ValueError):
        _days = {}


def _today():
    return date.today().isoformat()


def _child(who):
    try:
        import brain
        return brain._is_child(who)
    except Exception:
        return False


def heard(text):
    """A sentence that reached her (main.py) — not the radio's scraps."""
    _count("heard", text)


def note(line):
    """One printed line → the day's counts."""
    kind = next((k for k, rx in _PATTERNS if rx.search(line)), None)
    if kind is not None:
        _count(kind, line)


def _count(kind, text):
    with state.lock:
        who = state.person[0] if state.person else None
    child = kind == "heard" and who and _child(who)        # (outside our lock)
    with _lock:
        _load()
        day = _days.setdefault(_today(), {"counts": {}, "people": {}, "kids": []})
        day["counts"][kind] = day["counts"].get(kind, 0) + 1
        if kind == "heard":
            if who:
                day["people"][who] = day["people"].get(who, 0) + 1
            if child and len(day["kids"]) < KIDS_KEEP:
                text = text.strip()
                if len(text.split()) >= 3:
                    day["kids"].append(f"{who}: {text}")
        _dirty[0] = True


def save():
    with _lock:
        if not _dirty[0] or _days is None:
            return
        keep = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        for k in [k for k in _days if k < keep]:
            del _days[k]
        try:
            tmp = PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_days, f, ensure_ascii=False, indent=1)
            os.replace(tmp, PATH)
            _dirty[0] = False
        except OSError:
            pass


class _Tee:
    """sys.stdout that also hands each finished line to note()."""

    def __init__(self, out):
        self._out = out
        self._buf = ""

    def write(self, s):
        n = self._out.write(s)
        try:
            self._buf += s
            if "\n" in self._buf:
                *lines, self._buf = self._buf.split("\n")
                for line in lines:
                    note(line)
            if len(self._buf) > 4000:
                self._buf = ""
        except Exception:
            self._buf = ""
        return n

    def flush(self):
        self._out.flush()

    def __getattr__(self, name):
        return getattr(self._out, name)


def start_weekly():
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout)

    def loop():
        while True:
            time.sleep(SAVE_EVERY)
            save()
    threading.Thread(target=loop, daemon=True, name="weekly").start()


# ── the report ────────────────────────────────────────────────────────────────
_ASK = re.compile(r"\b(?:podsumowanie|podsumuj|raport|statystyk\w*)\s+(?:z\s+|mi\s+)?"
                  r"(?:tego\s+|ostatniego\s+|całego\s+|calego\s+)?(?:tygodni\w*|tydzień|tydzien)|"
                  r"\b(?:raport|podsumowanie)\s+tygodniow\w*", re.I)
# ("jak ci minął tydzień?" stays small talk, for the model)


def wanted(text):
    return bool(_ASK.search(text or "")) and len((text or "").split()) <= 9


def _week(now=None):
    today = date.fromtimestamp(now if now is not None else time.time())
    with _lock:
        _load()
        days = {k: v for k, v in _days.items()
                if k > (today - timedelta(days=7)).isoformat()}
    counts, people, kids = Counter(), Counter(), []
    for k in sorted(days):
        counts.update(days[k].get("counts", {}))
        people.update(days[k].get("people", {}))
        kids += [f"{k[5:]} {s}" for s in days[k].get("kids", [])]
    return len(days), counts, people, kids


def _topics(kids, n=5):
    words = Counter()
    for s in kids:
        text = s.split(": ", 1)[-1].lower()
        for w in set(re.findall(r"[^\W\d_]{4,}", text)):
            if w not in _STOP:
                words[w] += 1
    return [w for w, c in words.most_common(n) if c >= 2]


def _times(n):
    return "raz" if n == 1 else "razy"


def report(now=None):
    """(spoken, rows for the screen); also writes data/weekly.txt."""
    n_days, c, people, kids = _week(now)
    if not n_days or not c.get("heard"):
        return "Nie mam jeszcze nic z tego tygodnia do podsumowania.", []
    h = c["heard"]
    form = ("zdanie" if h == 1 else "zdania" if 2 <= h % 10 <= 4 and not 12 <= h % 100 <= 14
            else "zdań")
    said = [f"Przez {'ostatni dzień' if n_days == 1 else f'ostatnie {n_days} dni'} "
            f"usłyszałam {h} {form}."]
    trouble = c["noise"] + c["empty"]
    hard = []
    if trouble:
        hard.append(f"{trouble} {_times(trouble)} wzięłam szum albo radio za słowa")
    if c["unsure_name"]:
        hard.append(f"{c['unsure_name']} {_times(c['unsure_name'])} nie byłam pewna, "
                    f"czy ktoś mnie woła")
    if c["false_wake"]:
        hard.append(f"{c['false_wake']} {_times(c['false_wake'])} obudziłam się niepotrzebnie")
    if hard:
        said.append("Trudności: " + ", ".join(hard) + ".")
    errors = c["oops"] + c["model_fail"]
    if errors:
        said.append(f"Błędów po mojej stronie: {errors}.")
    else:
        said.append("Żadnych błędów po mojej stronie.")
    if people:
        top = ", ".join(f"{p} ({k})" for p, k in people.most_common(3))
        said.append(f"Najwięcej rozmów: {top}.")
    topics = _topics(kids)
    if topics:
        said.append("Dzieci pytały najczęściej o: " + ", ".join(topics) + ".")
    rows = [(str(c[k]), LABELS[k]) for k in LABELS if c.get(k)]
    rows += [(str(k), p) for p, k in people.most_common(4)]
    try:
        with open(TEXT_PATH, "w", encoding="utf-8") as f:
            f.write(f"Podsumowanie tygodnia — {time.strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(" ".join(said) + "\n\n")
            for k in LABELS:
                f.write(f"{c.get(k, 0):6d}  {LABELS[k]}\n")
            f.write("\nRozmowy:\n" + "".join(f"{k:6d}  {p}\n" for p, k in people.most_common()))
            if kids:
                f.write("\nCo mówiły dzieci:\n" + "".join(f"  {s}\n" for s in kids))
    except OSError:
        pass
    return " ".join(said), rows[:14]
