"""
faces.py — who is in front of her.

Two small neural networks from the OpenCV Zoo, run by OpenCV itself:
  YuNet  (232 KB)  finds faces — faster and far steadier than the old Haar
                   cascade, and it gives five landmarks per face (eyes, nose,
                   mouth corners) that the recogniser needs
  SFace  (38.7 MB) turns a face into 128 numbers; two photos of the same
                   person give similar numbers (cosine similarity)
Both live in data/models/ (see SETUP.md); without them vision falls back to
Haar and nobody is recognised.

Getting to know someone ("Luna, to jest Kasia", "jestem Andrzej", "zapamiętaj
moją twarz, mam na imię Ola"): for a few seconds every frame with exactly one
face adds a sample; the samples (numbers only, never the picture) go to
data/people.json. From then on the face is recognised (state.person) and
the model is told who it is talking to. "Zapomnij moją twarz" / "zapomnij
twarz Kasi" removes them.

Nothing leaves the Pi: detection, recognition and the samples are local.
"""

import json
import os
import threading
import time

import numpy as np

from config import DATA_DIR
from shared_state import state

MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "models")
YUNET = os.path.join(MODELS, "face_detection_yunet_2023mar.onnx")
SFACE = os.path.join(MODELS, "face_recognition_sface_2021dec.onnx")
PEOPLE_PATH = os.path.join(DATA_DIR, "people.json")

DETECT_SCORE = 0.75        # YuNet confidence for a face
MATCH_COSINE = 0.40        # SFace: same person above this (paper: 0.363; a bit
                           # stricter — a wrong name is worse than none)
SAMPLES_MAX = 30           # kept per person (photos + a few seconds of webcam)
ENROLL_SECS = 4.0
AUTO_MIN = 0.50            # self-learning: only from a sure recognition…
AUTO_MARGIN = 0.25         # …well ahead of the second-best person…
AUTO_EVERY = 60            # …at most one sample a minute per person…
AUTO_MAX = 15              # …and at most this many (the oldest go first)…
AUTO_NEW = 0.92            # …and only one that adds something: a near-copy of a
                           # kept sample (same chair, same lamp) is skipped, so
                           # the 15 cover different light and angles
RECOGNISE_EVERY = 2.5      # seconds between recognitions of a face in view

_lock = threading.Lock()
_net_lock = threading.Lock()   # one user of the networks at a time: vision and a
                               # photo being tagged would resize the same detector
_det = None
_rec = None
_people = None             # {name: {"samples": [[128 floats]], "added": t}}
_enroll = None             # {"name", "until", "samples": [], "done": Event, "many": int}


def available():
    return os.path.exists(YUNET)


def can_recognise():
    return os.path.exists(SFACE)


def _detector(w, h):
    global _det
    if _det is None:
        import cv2
        _det = cv2.FaceDetectorYN.create(YUNET, "", (w, h), DETECT_SCORE, 0.3, 20)
        print("[faces] YuNet face detector ready", flush=True)
    _det.setInputSize((w, h))
    return _det


def _recogniser():
    global _rec
    if _rec is None:
        import cv2
        _rec = cv2.FaceRecognizerSF.create(SFACE, "")
        print("[faces] SFace recogniser ready", flush=True)
    return _rec


def detect(bgr):
    """YuNet rows (x, y, w, h, 10 landmark coords, score) for a BGR frame."""
    h, w = bgr.shape[:2]
    with _net_lock:
        _, faces = _detector(w, h).detect(bgr)
    return faces if faces is not None else np.zeros((0, 15), np.float32)


def embed(bgr_full, row_small, scale):
    """128 numbers for the face `row_small` (found on a frame `scale` times
    smaller than bgr_full) — aligned on the full-size frame, which has the
    detail recognition needs."""
    row = row_small.copy()
    row[:14] *= scale
    with _net_lock:
        rec = _recogniser()
        crop = rec.alignCrop(bgr_full, row)
        return rec.feature(crop).flatten()


# ── who is who ────────────────────────────────────────────────────────────────

_mtime = [None]            # people.json as last read or written by THIS process


def _file_mtime():
    try:
        return os.stat(PEOPLE_PATH).st_mtime_ns
    except OSError:
        return None


def _load():
    """The people, re-read when the file was changed by someone else (a
    script, a hand edit): this cached copy used to be written back over it —
    the vocatives set on 4 Oct were lost at the next self-learned sample."""
    global _people
    m = _file_mtime()
    if _people is None or m != _mtime[0]:
        try:
            with open(PEOPLE_PATH, encoding="utf-8") as f:
                _people = json.load(f)
        except (OSError, ValueError):
            if _people is None:
                _people = {}
        _mtime[0] = m
    return _people


def _save():
    tmp = PEOPLE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_people, f, ensure_ascii=False)
    os.replace(tmp, PEOPLE_PATH)
    _mtime[0] = _file_mtime()


# ── when was someone last here ("gdzie jest Maja?") ───────────────────────────

SEEN_PATH = os.path.join(DATA_DIR, "seen.json")
_seen = None                 # {name: unix time}
_seen_saved = 0.0


def saw(names_now, now=None):
    """The camera recognised these people just now. Written to disk at most
    once a minute — a restart must not forget that Maja was here."""
    global _seen, _seen_saved
    now = time.time() if now is None else now
    with _lock:
        if _seen is None:
            _seen = _read_seen()
        for n in names_now:
            if n and n != "?":
                _seen[n] = now
        if now - _seen_saved < 60:
            return
        _seen_saved = now
        data = dict(_seen)
    try:
        tmp = SEEN_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, SEEN_PATH)
    except OSError:
        pass


def _read_seen():
    try:
        with open(SEEN_PATH, encoding="utf-8") as f:
            return {k: float(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def last_seen(name):
    global _seen
    with _lock:
        if _seen is None:
            _seen = _read_seen()
        return _seen.get(name)


def _female(name):
    return name.lower().endswith("a") and name.lower() not in ("kuba", "barnaba", "kosma")


def where_is(name, now=None):
    """"Maja jest tutaj!" / "Maja była tu 12 minut temu." / "…wczoraj o 20:15"."""
    from datetime import datetime
    now = time.time() if now is None else now
    t = last_seen(name)
    was = "była" if _female(name) else "był"
    if t is None:
        return f"{name} jeszcze nie {was} przy mnie, odkąd pamiętam."
    ago = now - t
    if ago < 15:
        return f"{name} jest tutaj, przy mnie!"
    if ago < 60 * 60:
        m = max(1, int(ago // 60))
        unit = ("minutę" if m == 1 else
                "minuty" if m % 10 in (2, 3, 4) and m % 100 not in (12, 13, 14) else "minut")
        return f"{name} {was} tu {m} {unit} temu."
    d, today = datetime.fromtimestamp(t), datetime.fromtimestamp(now).date()
    hm = d.strftime("%H:%M")
    if d.date() == today:
        return f"{name} {was} tu dziś o {hm}."
    if (today - d.date()).days == 1:
        return f"Dziś jeszcze nie widziałam. {name} {was} tu wczoraj o {hm}."
    return f"{name} {was} tu ostatnio {d.strftime('%d.%m')} o {hm}."


def names():
    with _lock:
        return sorted(_load())


def vocatives():
    """{name: vocative} — "Maju", not "Majo" (the model got it wrong). Kept as
    "voc" in data/people.json; set by hand, or by the model when someone is
    introduced (_learn_face)."""
    with _lock:
        return {n: p.get("voc", "") for n, p in _load().items()}


def set_vocative(name, voc):
    with _lock:
        p = _load().get(name)
        if p is not None and voc:
            p["voc"] = voc
            _save()


def notes():
    """{name: note} — who someone is ("córka, 8 lat — dziecko"), set by hand
    in data/people.json; goes into the prompt with the name."""
    with _lock:
        return {n: p.get("note", "") for n, p in _load().items()}


def _scores(feature):
    """{name: best cosine similarity over their samples (photos, enrolment
    and self-learned)}."""
    with _lock:
        people = {n: p["samples"] + p.get("auto", []) for n, p in _load().items()}
    f = feature / (np.linalg.norm(feature) + 1e-9)
    out = {}
    for name, samples in people.items():
        if not samples:
            continue
        s = np.asarray(samples, np.float32)
        s = s / (np.linalg.norm(s, axis=1, keepdims=True) + 1e-9)
        out[name] = float(np.max(s @ f))
    return out


def who_in(bgr):
    """Names of the known people in a picture (a photo she took), left to
    right; [] without the models."""
    if not (available() and can_recognise()):
        return []
    import cv2
    h, w = bgr.shape[:2]
    k = min(1.0, 640 / max(h, w))
    small = cv2.resize(bgr, (int(w * k), int(h * k))) if k < 1 else bgr
    found = []
    for r in sorted(detect(small), key=lambda r: r[0]):
        name, _ = identify(embed(bgr, r, 1 / k), learn_ok=False)
        if name and name not in found:
            found.append(name)
    return found


def identify(feature, learn_ok=True):
    """(name, similarity) of the best match above MATCH_COSINE, else (None, best).
    A sure match also teaches her a little (see learn)."""
    scores = _scores(feature)
    if not scores:
        return None, 0.0
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    who, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    if best < MATCH_COSINE:
        global _last_miss
        _near[:] = [who, best, time.time()]
        if best >= 0.25 and time.time() - _last_miss > 60:   # who is it nearly?
            _last_miss = time.time()
            print(f"[faces] not sure who this is — closest {who} {best:.2f}"
                  f" (needs {MATCH_COSINE:.2f})", flush=True)
        return None, best
    if learn_ok and best >= AUTO_MIN and best - second >= AUTO_MARGIN:
        learn(who, feature)
    return who, best


_last_auto = {}
_last_miss = 0.0
_near = [None, 0.0, 0.0]          # the last unsure match: closest name, score, when


def probably_family(now=None, near_secs=8, seen_secs=180):
    """An unrecognised face that is most likely one of the family: a near miss
    just now (0.28+, e.g. Andrzej at 0.36 turned aside), or someone known was
    here a moment ago. Then no "nie znam cię, jak masz na imię?"."""
    now = now or time.time()
    if _near[0] and now - _near[2] < near_secs and _near[1] >= 0.28:
        return True
    global _seen
    with _lock:
        if _seen is None:
            _seen = _read_seen()
        return any(now - t < seen_secs for t in _seen.values())


def learn(name, feature):
    """Self-learning: keep a few webcam samples of a surely recognised face —
    the photos were taken by a phone in other light; this is how she sees
    them every day. Separate from the photos/enrolment, capped, oldest out."""
    now = time.time()
    if now - _last_auto.get(name, 0) < AUTO_EVERY:
        return
    _last_auto[name] = now
    with _lock:
        p = _load().get(name)
        if p is None:
            return
        kept = p.get("auto", [])
        if kept:
            k = np.asarray(kept, np.float32)
            k = k / (np.linalg.norm(k, axis=1, keepdims=True) + 1e-9)
            f = feature / (np.linalg.norm(feature) + 1e-9)
            if float(np.max(k @ f)) >= AUTO_NEW:
                return                         # nothing new about this face
        p["auto"] = (kept + [[round(float(v), 5) for v in feature]])[-AUTO_MAX:]
        _save()
    print(f"[faces] learned a little more of {name} ({len(p['auto'])} webcam samples)",
          flush=True)


def start_enrolment(name):
    """Begin collecting samples of the face in view; returns an Event that is
    set when done (see enrolment_result)."""
    global _enroll
    with _lock:
        _enroll = {"name": name, "until": time.time() + ENROLL_SECS, "samples": [],
                   "done": threading.Event(), "many": 0}
        return _enroll["done"]


def enrolling():
    with _lock:
        return _enroll is not None and not _enroll["done"].is_set()


def offer(feature, n_faces):
    """Vision calls this with every frame's feature while enrolling."""
    global _enroll
    with _lock:
        e = _enroll
        if e is None or e["done"].is_set():
            return
        if n_faces > 1:
            e["many"] += 1
        elif feature is not None:
            e["samples"].append([round(float(v), 5) for v in feature])
        if time.time() >= e["until"]:
            if e["samples"]:
                people = _load()
                p = people.setdefault(e["name"], {"samples": [], "added": time.time()})
                p["samples"] = (p["samples"] + e["samples"])[-SAMPLES_MAX:]
                _save()
                print(f"[faces] learned {e['name']}: {len(e['samples'])} samples", flush=True)
            e["done"].set()


def enrolment_result():
    """("ok", name) / ("nobody", name) / ("many", name) once enrolment ended."""
    with _lock:
        e = _enroll
    if e is None:
        return ("nobody", "")
    if e["samples"]:
        return ("ok", e["name"])
    return ("many" if e["many"] else "nobody", e["name"])


def nominative(name):
    """"Kasię" / "Kasi" → "Kasia" (one small model call; the name as said
    when it fails)."""
    try:
        from openai import OpenAI
        from config import OPENAI_API_KEY, OPENAI_MODEL
        c = OpenAI(api_key=OPENAI_API_KEY, timeout=8, max_retries=1)
        r = c.chat.completions.create(
            model=OPENAI_MODEL, temperature=0, max_tokens=20,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content":
                       "Return JSON {\"name\": ...}: this Polish first name in the "
                       "nominative case, capitalised (\"Kasię\" -> \"Kasia\", "
                       "\"Andrzeja\" -> \"Andrzej\", \"Oli\" -> \"Ola\"):\n" + name}])
        out = json.loads(r.choices[0].message.content).get("name", "").strip()
        return out or name
    except Exception as e:
        print(f"[faces] nominative failed ({e}) — using {name!r}", flush=True)
        return name


def vocative_of(name):
    """"Maja" -> "Maju" (one small model call); "" when it fails."""
    try:
        from openai import OpenAI
        from config import OPENAI_API_KEY, OPENAI_MODEL
        c = OpenAI(api_key=OPENAI_API_KEY, timeout=8, max_retries=1)
        r = c.chat.completions.create(
            model=OPENAI_MODEL, temperature=0, max_tokens=20,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content":
                       "Return JSON {\"vocative\": ...}: the Polish vocative (wołacz) "
                       "of this first name, the form used to call someone "
                       "(\"Maja\" -> \"Maju\", \"Kasia\" -> \"Kasiu\", "
                       "\"Andrzej\" -> \"Andrzeju\", \"Ola\" -> \"Olu\"): " + name}])
        return json.loads(r.choices[0].message.content).get("vocative", "").strip()
    except Exception as e:
        print(f"[faces] vocative failed ({e})", flush=True)
        return ""


def forms(name):
    """The case forms of a Polish first name: Maja → Mai, Maję, Mają, Maju…;
    Emilka → Emilki, Emilce, Emilkę…; Andrzej → Andrzeja, Andrzejowi…"""
    n = name.lower()
    out = {n}
    if n.endswith("a"):
        stem = n[:-1]
        out |= {stem + e for e in ("y", "i", "ę", "ą", "o", "u", "e")}
        if stem.endswith("j"):                  # Maja → Mai
            out.add(stem[:-1] + "i")
        if stem.endswith("k"):                  # Emilka → Emilce
            out.add(stem[:-1] + "ce")
    else:
        out |= {n + e for e in ("a", "owi", "em", "u", "e", "ie")}
    return out


def match_name(word, known=None):
    """A known person's name for any case form of it ("Mai" → "Maja"), or None."""
    w = word.lower()
    for n in (known if known is not None else names()):
        if w in forms(n):
            return n
    return None


def forget(name):
    """Remove someone. True if they were known."""
    with _lock:
        people = _load()
        key = next((n for n in people if n.lower() == name.lower()), None)
        if key is None:
            return False
        del people[key]
        _save()
    with state.lock:
        if state.person and state.person[0] == key:
            state.person = None
    print(f"[faces] forgot {key}", flush=True)
    return True


def picture_note():
    """Who is where in the camera picture, for a question about what she sees:
    "Na zdjęciu, od lewej: Maja, Andrzej." — the model can't recognise faces
    itself (5 Oct: Andrzej and Maja in view, "Kto to jest?" → "Nie wiem, kto
    to jest na tym zdjęciu"). Empty when nobody was recognised just now."""
    with state.lock:
        layout, at = state.layout
    if not layout or time.time() - at > 3 * RECOGNISE_EVERY:
        return ""
    if all(n == "?" for n, _ in layout):
        return ""
    names = [n if n != "?" else "ktoś, kogo nie znasz" for n, _ in sorted(layout, key=lambda p: p[1])]
    if len(names) == 1:
        return f" Osoba na zdjęciu to {names[0]} (rozpoznana po twarzy)."
    return (f" Twarze na zdjęciu, od lewej: {', '.join(names)} (rozpoznane po twarzy; "
            "inne postacie, np. w telewizorze albo na obrazku, nie są z tej listy).")


def prompt_line():
    """Who she knows and who is in front of her, for the system prompt."""
    known = names()
    about = notes()
    with state.lock:
        person = state.person
        seen = state.face_detected
    if not known:
        return ("Nobody's face is known yet — if someone tells you their name, "
                "they can say \"Luna, zapamiętaj moją twarz, jestem …\".\n")
    voc = vocatives()

    with _lock:
        born = {n: (p.get("birthday"), p.get("born")) for n, p in _load().items()}

    def age(n):
        """"birthday 12.05, 8 years old" from what birthdays.py stored."""
        md, year = born.get(n, (None, None))
        if not md:
            return None
        m, d = (int(x) for x in md.split("-"))
        out = f"birthday {d}.{m}"
        if year:
            t = time.localtime()
            years = t.tm_year - year - ((t.tm_mon, t.tm_mday) < (m, d))
            out += f", {years} years old"
        return out

    def one(n):
        bits = ([f"vocative \"{voc[n]}\" only when calling them directly, other "
                 "cases as Polish grammar needs"] if voc.get(n) else []) + \
               ([about[n]] if about.get(n) else []) + \
               ([age(n)] if age(n) else [])
        return f"{n} ({'; '.join(bits)})" if bits else n
    who = ", ".join(one(n) for n in known)
    now = (f"In front of you now: {person[0]} (recognised by face)."
           if person else
           "In front of you now: a face you don't recognise." if seen else
           "Nobody is in front of the camera now.")
    if not person:              # "Chciałabyś…?" guesses who it is — "Chcesz…?" doesn't
        now += (" You don't know who is speaking: address them without gendered "
                "forms (\"Chcesz…?\", \"Możesz…\", not \"Chciałabyś/Chciałbyś\", "
                "\"zrobiłaś/zrobiłeś\").")
    with state.lock:
        others, seen_at = state.others
    if seen and others and time.time() - seen_at < 3 * RECOGNISE_EVERY:
        known_others = [o for o in others if o != "?"]
        strangers = len(others) - len(known_others)
        also = known_others + ([f"{strangers} unknown"] if strangers else [])
        now += (f" Also in view: {', '.join(also)}. With more than one person there you "
                "can't tell who is speaking — don't address anyone by name in this "
                "answer (on 5 Oct Emilka asked for the radio and heard "
                "\"Miłego słuchania, Andrzeju!\").")
    if person and "dziecko" in about.get(person[0], "").lower():
        # the persona's general "with a child" rules lost to a plain question
        # (tested: 56 : 7 was answered "8" straight away) — said here, now
        now += (f" {person[0]} IS A CHILD, so right now: simple words; for any school "
                "task or sum NEVER say the result — ask what they think, give one "
                "hint, and only confirm or gently correct THEIR answer.")
    return (f"People you know by face: {who}. {now} Talk to the "
            "recognised person by name now and then (in the right Polish case), "
            "not in every sentence.\n")
