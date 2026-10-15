"""story.py — interactive stories: Luna tells, the child chooses what happens next.

  "opowiedz bajkę, w której ja wybieram" / "interaktywna bajka o smoku" /
  "zagrajmy w bajkę" / "wymyślmy razem bajkę"
        → no topic: "O czym ma być bajka?" (three ideas on the screen to tap)
        → the story, in PARTS parts; each one told, with its own picture, then
          two choices — said, and on the screen as big buttons ("pierwsze",
          "do jaskini", or a tap)
        → the ending; the story is saved (its pictures and the choices made)
  "pokaż moje bajki" / "nasze bajki"  → the saved ones as cards; a tap tells it
                                        again, with its pictures
  "opowiedz jeszcze raz bajkę o smoku" / "ostatnią bajkę" → the same, by voice
  "koniec" / "stop" / "zamknij" / ✕   → stops at any point, back to her face
  "usuń bajkę o smoku"               → gone from the list

The pictures: one style per story, picked to fit its kind (a few random
candidates, so no two stories look alike) and kept for all of its parts; the
first picture is the reference for the others (images.edit), so the
characters look the same all the way through. (15 Oct, Andrzej: "drawings
consistent with the story's genre and across the story, unique per story".)

The text comes from CRAFT_MODEL (her Polish for stories, poems); a part is
told while its picture is drawn, so the drawing costs no waiting. An
unfinished story isn't kept.
"""

import base64
import json
import os
import random
import re
import shutil
import threading
import time

from config import DATA_DIR, CRAFT_MODEL
from shared_state import state

DIR = os.path.join(DATA_DIR, "stories")
PARTS = 5                   # the start, three more with choices, the ending
KEEP = 60                   # stories kept (the oldest go)
IMAGES_PER_DAY = 40         # a cap on the pictures (about a cent each)
IMAGE_MODEL = "gpt-image-1-mini"
PAGE = 6                    # stories on a page of the list
SHOW_SECS = 600             # the story's page stays while the story goes on
END_PAUSE = 12              # "Koniec" stays on the screen this long

# illustration styles to choose from — a few at random for each story, the
# model takes the one that suits it (so two dragon stories still differ)
_STYLES = [
    "soft watercolour with gentle washes and visible paper texture",
    "colourful cut-paper collage with layered shapes",
    "warm gouache painting like a classic 1960s picture book",
    "coloured pencil drawing with soft hatching",
    "smooth friendly 3D animation look, rounded shapes, soft light",
    "bold flat vector shapes with a limited bright palette",
    "chalk pastel on toned paper, dreamy and soft",
    "ink line drawing with bright watercolour fills",
    "cosy felt and fabric look, like a handmade toy diorama",
    "pixel-free storybook oil painting with rich warm colours",
    "linocut print look with two or three bold colours",
    "crayon drawing as if made by a talented child",
    "glowing night palette with soft neon accents",
    "nordic folk art style with simple patterns",
]
# ideas on the screen when no topic was given
_TOPICS = ["o smoku", "o kosmosie", "o leśnych zwierzętach", "o syrence", "o robocie",
           "o dinozaurze", "o czarodziejce", "o piratach", "o kotku detektywie",
           "o jednorożcu", "o podróży balonem", "o zaczarowanym ogrodzie"]

_START = re.compile(
    r"\b(?:interaktywn\w+\s+(?:bajk\w*|histori\w*|opowieś\w*)"
    r"|(?:bajk\w*|histori\w*|opowieś\w*)\s*,?\s+(?:w\s+której|w\s+ktorej|gdzie)\s+(?:ja\s+|my\s+)?"
    r"(?:wybieram|wybieramy|decyduj\w*|wybior\w*|zdecyduj\w*)"
    r"|(?:bajk\w*|histori\w*)\s+z\s+wybor\w*"
    r"|zagrajmy\s+w\s+bajk\w*|wymyśl(?:my|cie)?\s+(?:razem\s+)?bajk\w*"
    r"|ja\s+(?:wybieram|zdecyduję|zdecyduje),?\s+co\s+(?:się\s+)?(?:stanie|będzie|bedzie))", re.I)
_LIST = re.compile(r"\b(?:(?:pokaż|pokaz|otwórz|otworz)\s+(?:mi\s+|nam\s+)?(?:moje\s+|nasze\s+|"
                   r"wszystkie\s+|zapisane\s+)?bajki|lista\s+bajek|(?:moje|nasze)\s+bajki"
                   r"|jakie\s+(?:mamy|masz)\s+(?:zapisane\s+)?bajki)\b", re.I)
_REPLAY = re.compile(r"\b(?:opowiedz|przeczytaj|puść|pusc|włącz|wlacz)\s+(?:mi\s+|nam\s+)?"
                     r"(?:(?:jeszcze\s+raz|znowu|ponownie)\s+)?(?:tę\s+|te\s+|naszą\s+|nasza\s+|"
                     r"ostatnią\s+|ostatnia\s+)?bajkę(?:\s+(?:jeszcze\s+raz|znowu|ponownie))?"
                     r"(?:\s+o\s+(.{2,40}?))?\W*$", re.I)
_DELETE = re.compile(r"\b(?:usuń|usun|skasuj|wyrzuć|wyrzuc)\s+(?:tę\s+|te\s+|ostatnią\s+|ostatnia\s+)?"
                     r"bajkę(?:\s+o\s+(.{2,40}?))?\W*$", re.I)
_STOP = re.compile(r"^(?:luna,?\s+)?(?:koniec|stop|stój|zakończ\w*|zakoncz\w*|wystarczy|przestań|"
                   r"przestan|nie\s+chcę\s+już|nie\s+chce\s+juz|wróć\s+do\s+buzi|wroc\s+do\s+buzi|"
                   r"zamknij\w*|zatrzymaj\w*|dość|dosc)(?:\s+(?:bajkę|bajke|bajki|już|juz|to))?\W*$",
                   re.I)
# "pierwsze", "to drugie", "numer dwa"
_ORDINALS = [r"\b(?:pierwsz\w*|jeden|jedynk\w*|1)\b", r"\b(?:drug\w*|dwa|dwójk\w*|dwojk\w*|2)\b"]
_FILLERS = ["Ciekawe, co się teraz stanie…", "O, dobry wybór! Posłuchaj…",
            "Hmm, zobaczmy, co było dalej…", "Świetnie! Słuchaj uważnie…"]

_lock = threading.Lock()
_s = None                   # the story being told (or replayed), a dict


# ── what was said ─────────────────────────────────────────────────────────────

def wanted(text):
    return bool(_START.search(text or ""))


def _topic_of(text):
    """"…bajkę o smoku" → "o smoku" (or "" — no topic said)."""
    m = re.search(r"\b(o\s+[^,.!?]{2,50}|z\s+(?:smokiem|robotem|kotem|psem)[^,.!?]{0,30})[.!?]*$",
                  text or "", re.I)
    if not m:
        return ""
    t = m.group(1).strip()
    if re.match(r"o\s+(?:tym|to|czym|co)\b", t, re.I):
        return ""
    return t


def active():
    with _lock:
        return _s is not None


def _child():
    """The child's name, when the one in front of her is a child."""
    try:
        import commands
        if commands._child_here():
            with state.lock:
                return state.person[0] if state.person else None
    except Exception:
        pass
    return None


# ── the screen ────────────────────────────────────────────────────────────────

def _show(**data):
    """The story page (ui_screens.draw_story), refreshed with these fields."""
    with state.lock:
        ov = state.overlay
        cur = ov[2] if ov and ov[0] == "story" else {}
        cur = dict(cur)
        cur.update(data)
        state.overlay = ("story", time.time() + SHOW_SECS, cur)


def _page_gone():
    with state.lock:
        ov = state.overlay
    return not ov or ov[0] != "story"


def _listen_longer(secs=20):
    """The answer needs no "Luna" (and a bit more time to think)."""
    with state.lock:
        state.conversation_active = True
        state.last_activity_time = max(state.last_activity_time, time.time() + secs)


def _cancelled(s):
    return s["cancel"].is_set() or _page_gone()


# ── the model ─────────────────────────────────────────────────────────────────

_PART = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "text": {"type": "string"},
        "choices": {"type": "array", "items": {"type": "string"}},
        "scene": {"type": "string"},
    },
    "required": ["text", "choices", "scene"],
}
_PLAN = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "genre": {"type": "string"},
        "art_style": {"type": "string"},
        "characters": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "look": {"type": "string"}},
            "required": ["name", "look"]}},
        "setting": {"type": "string"},
        "part": _PART,
    },
    "required": ["title", "genre", "art_style", "characters", "setting", "part"],
}

_RULES = (
    "Jesteś Luną, ciepłym domowym robotem, i opowiadasz INTERAKTYWNĄ bajkę dla dziecka "
    "(ok. 5–8 lat), po polsku. Bajka ma {n} części. Każda część: 3–5 krótkich zdań, prosty "
    "język, żywo i zabawnie, ciepło; nic strasznego, żadnej przemocy, nikt nie ginie. "
    "Na końcu każdej części oprócz ostatniej dziecko wybiera, co dalej: podaj DOKŁADNIE dwa "
    "wybory (\"choices\"), każdy 2–6 słów, zaczynający się od czasownika, wyraźnie różne "
    "(np. \"wejść do jaskini\", \"popłynąć łódką\"). Nie zadawaj pytania o wybór w tekście — "
    "zadam je sama. Ostatnia część kończy bajkę dobrze i ma pustą listę wyborów. "
    "Wybór dziecka naprawdę zmienia, co się dzieje. \"scene\": ZAWSZE PO ANGIELSKU, do 45 słów, "
    "co widać na obrazku tej części (kto, co robi, gdzie) — bez tekstu na obrazku.")


def _client():
    from openai import OpenAI
    from config import OPENAI_API_KEY
    return OpenAI(api_key=OPENAI_API_KEY, timeout=40, max_retries=1)


def _llm(messages, schema, name):
    """One JSON answer from the model (strict schema)."""
    r = _client().chat.completions.create(
        model=CRAFT_MODEL, messages=messages, temperature=0.9,
        response_format={"type": "json_schema",
                         "json_schema": {"name": name, "strict": True, "schema": schema}})
    return json.loads(r.choices[0].message.content)


def _plan(topic, child):
    styles = random.sample(_STYLES, 4)
    who = f"Dziecko ma na imię {child}. " if child else ""
    msg = (_RULES.format(n=PARTS) + " " + who +
           f"Temat: {topic or 'wymyśl sam coś wesołego'}. Najpierw zaplanuj bajkę: "
           "\"title\" (krótki tytuł po polsku), \"genre\" (rodzaj, po polsku, np. baśń, "
           "przygoda w kosmosie), \"art_style\" (po angielsku: JEDEN styl ilustracji, który "
           "najlepiej pasuje do tej bajki, wybierz z: " + "; ".join(styles) +
           " — i dopisz paletę barw pasującą do jej nastroju), \"characters\" (2–3 postacie: "
           "imię i \"look\" po angielsku — bardzo konkretny, stały wygląd: gatunek, kolory, "
           "ubranie, jedna charakterystyczna rzecz), \"setting\" (po angielsku, gdzie to się "
           "dzieje, jednym zdaniem). Potem \"part\": część 1.")
    return _llm([{"role": "user", "content": msg}], _PLAN, "story_plan")


def _next_part(s, n):
    """Part n (1-based) after the choices so far."""
    told = "\n".join(
        f"Część {i + 1}: {p['text']}" + (f"\nDziecko wybrało: {p['chosen']}." if p.get("chosen")
                                          else "")
        for i, p in enumerate(s["parts"]))
    last = n == PARTS
    msg = (_RULES.format(n=PARTS) + f"\nTytuł: {s['title']}. Postacie: "
           + "; ".join(f"{c['name']}" for c in s["characters"]) + ".\n" + told +
           f"\nTeraz część {n}" + (" — OSTATNIA: zakończ bajkę, pusta lista wyborów." if last
                                   else ", z dwoma wyborami na końcu."))
    p = _llm([{"role": "user", "content": msg}], _PART, "story_part")
    if last:
        p["choices"] = []
    return p


# ── the pictures ──────────────────────────────────────────────────────────────

def _image_prompt(s, scene, ref):
    chars = "; ".join(f"{c['name']}: {c['look']}" for c in s["characters"])
    head = ("Use the reference picture ONLY for the art style and for how the characters look "
            "— keep them exactly the same; draw a NEW scene with a different composition and "
            "viewpoint than the reference (closer or wider, another angle). " if ref else "")
    return (head + f"Children's book illustration. Art style: {s['art_style']}. "
            f"Characters (always exactly this look): {chars}. Setting: {s['setting']}. "
            f"Scene: {scene}. Friendly, gentle, cheerful, nothing scary. No text, no letters.")


def _budget_ok():
    import settings
    day = time.strftime("%Y-%m-%d")
    c = settings.get("story_images", {}) or {}
    n = c.get(day, 0)
    if n >= IMAGES_PER_DAY:
        return False
    settings.put("story_images", {day: n + 1})
    return True


def _image(s, scene, out):
    """Draws a part's picture into `out` (PNG); True when it worked."""
    if not _budget_ok():
        print("[story] no more pictures today", flush=True)
        return False
    c = _client()
    ref = s.get("ref")
    prompt = _image_prompt(s, scene, ref)
    try:
        if ref and os.path.exists(ref):
            with open(ref, "rb") as f:
                r = c.images.edit(model=IMAGE_MODEL, size="1024x1024", quality="low", n=1,
                                  image=("ref.png", f.read(), "image/png"), prompt=prompt)
        else:
            r = c.images.generate(model=IMAGE_MODEL, size="1024x1024", quality="low", n=1,
                                  prompt=prompt)
    except Exception as e:
        if not ref:
            raise
        print(f"[story] edit failed ({e}) — a fresh picture", flush=True)
        r = c.images.generate(model=IMAGE_MODEL, size="1024x1024", quality="low", n=1,
                              prompt=_image_prompt(s, scene, None))
    with open(out, "wb") as f:
        f.write(base64.b64decode(r.data[0].b64_json))
    return True


def _draw_async(s, n, scene):
    """The picture for part n, in the background; shown when it's ready."""
    out = os.path.join(s["dir"], f"p{n}.png")

    def run():
        try:
            if _image(s, scene, out):
                s["parts"][n - 1]["image"] = os.path.basename(out)
                if n == 1:
                    s["ref"] = out
                if not _cancelled(s) and s.get("shown", 0) <= n:
                    _show(image=out)
                print(f"[story] picture {n} ready", flush=True)
        except Exception as e:
            print(f"[story] picture {n} failed: {e}", flush=True)
    t = threading.Thread(target=run, daemon=True, name="story-draw")
    t.start()
    return t


# ── telling ───────────────────────────────────────────────────────────────────

def _say(text):
    from text_to_speech import speak
    speak(text)


def start(text, speak):
    """"Opowiedz bajkę, w której wybieram (o …)" — True (handled)."""
    global _s
    with state.lock:
        online = state.online
    if not online:
        speak("Nie mam teraz internetu, więc nie wymyślę bajki. Spróbujmy później!")
        return True
    stop(quiet=True)
    topic = _topic_of(text)
    s = {"cancel": threading.Event(), "parts": [], "phase": "topic", "kind": "tell",
         "child": _child(), "topic": topic}
    with _lock:
        _s = s
    if not topic:
        ideas = random.sample(_TOPICS, 3)
        s["ideas"] = ideas
        _show(mode="topic", ideas=ideas, title="Bajka", image=None)
        speak("Dobrze! O czym ma być bajka? Na przykład " + ", ".join(ideas[:2])
              + f" albo {ideas[2]}.")
        _listen_longer()
        return True
    _begin(s, topic, speak)
    return True


def _begin(s, topic, speak):
    import webphoto
    if webphoto.NOT_FOR_KIDS.search(topic):
        speak("O tym nie opowiem — wymyślmy coś weselszego!")
        _listen_longer()
        return
    s["topic"], s["phase"] = topic, "making"
    _show(mode="make", title="Bajka", status="Wymyślam bajkę…", image=None)
    speak("Dobrze, wymyślam bajkę " + topic + ". Chwileczkę!")
    threading.Thread(target=_run_first, args=(s,), daemon=True, name="story").start()


def _run_first(s):
    try:
        plan = _plan(s["topic"], s["child"])
    except Exception as e:
        print(f"[story] plan failed: {e}", flush=True)
        _fail(s)
        return
    if _cancelled(s):
        return
    s.update(title=plan["title"].strip(), genre=plan["genre"], art_style=plan["art_style"],
             characters=plan["characters"][:3], setting=plan["setting"],
             id=time.strftime("%Y%m%d-%H%M%S"))
    s["dir"] = os.path.join(DIR, s["id"])
    os.makedirs(s["dir"], exist_ok=True)
    print(f"[story] \"{s['title']}\" ({s['genre']}; {s['art_style'][:60]})", flush=True)
    _tell(s, 1, plan["part"])


def _tell(s, n, part):
    """Part n: its picture starts, the part is told, then the choices (or the end)."""
    choices = [c.strip(" .!?") for c in part.get("choices", [])][:2]
    s["parts"].append({"text": part["text"].strip(), "choices": choices, "chosen": None,
                       "image": None})
    drawing = _draw_async(s, n, part["scene"])
    s["phase"], s["shown"] = "telling", n
    _show(mode="tell", title=s["title"], part=n, of=PARTS, status=None, choices=[])
    if n == 1:
        _say(f"{s['title']}.")
    if _cancelled(s):
        return
    _say(part["text"].strip())
    if _cancelled(s):
        return
    if len(choices) == 2 and n < PARTS:
        drawing.join(timeout=20)                  # (the picture up before she asks)
        if _cancelled(s):
            return
        s["phase"] = "choosing"
        _show(mode="choose", choices=choices)
        _say(f"Co dalej? {choices[0][0].upper() + choices[0][1:]} — czy {choices[1]}?")
        _listen_longer()
        return
    drawing.join(timeout=30)
    if _cancelled(s):
        return
    _finish(s)


def _finish(s):
    """The end: saved, kept on the screen a moment, then back to her face."""
    global _s
    s["phase"] = "end"
    _save(s)
    _show(mode="end", status="Koniec")
    _say("Koniec! Zapisałam tę bajkę — powiedz „pokaż moje bajki”, a opowiem ją jeszcze raz.")
    with _lock:
        if _s is s:
            _s = None
    time.sleep(END_PAUSE)
    if not _page_gone() and not active():
        with state.lock:
            state.overlay = None


def _fail(s):
    global _s
    with _lock:
        if _s is s:
            _s = None
    _drop(s)
    with state.lock:
        if state.overlay and state.overlay[0] == "story":
            state.overlay = None
    _say("Coś mi się poplątało i nie wymyśliłam bajki — spróbujmy jeszcze raz.")


def choose(i):
    """The child's choice i (0 / 1) — the next part, in the background."""
    with _lock:
        s = _s
    if not s or s.get("phase") != "choosing" or s.get("kind") != "tell":
        return False
    part = s["parts"][-1]
    part["chosen"] = part["choices"][i]
    s["phase"] = "making"
    n = len(s["parts"]) + 1
    _show(mode="make", status="Co będzie dalej…", choices=[], chosen=i)
    print(f"[story] chose: {part['chosen']}", flush=True)

    def run():
        got = {}

        def think():
            try:
                got["part"] = _next_part(s, n)
            except Exception as e:
                got["err"] = e
        t = threading.Thread(target=think, daemon=True)
        t.start()
        _say(random.choice(_FILLERS))
        t.join(timeout=45)
        if _cancelled(s):
            return
        if "part" not in got:
            print(f"[story] part {n} failed: {got.get('err')}", flush=True)
            _fail(s)
            return
        _tell(s, n, got["part"])
    threading.Thread(target=run, daemon=True, name="story").start()
    return True


def _match(text, choices):
    """Which choice the words name: "pierwsze", "do jaskini" — or None."""
    low = text.lower()
    for i, rx in enumerate(_ORDINALS):
        if re.search(rx, low):
            return i

    def stems(t):
        return {w[:5] for w in re.findall(r"\w+", t.lower()) if len(w) >= 4}
    said = stems(low)
    scores = [len(said & stems(c)) for c in choices]
    if max(scores, default=0) > 0 and scores.count(max(scores)) == 1:
        return scores.index(max(scores))
    return None


def answer(text, speak):
    """An utterance while a story is on. True when it belonged to it."""
    with _lock:
        s = _s
    if not s:
        return False
    low = (text or "").lower().strip()
    if _STOP.match(low):
        stop()
        speak("Dobrze, kończymy bajkę.")
        return True
    if s["kind"] == "replay":
        return False
    if s["phase"] == "topic":
        topic = re.sub(r"^(?:luna,?\s+)?(?:niech\s+będzie\s+|niech\s+bedzie\s+|może\s+|moze\s+|"
                       r"chcę\s+|chce\s+|bajka\s+|bajkę\s+)?", "", low).strip(" .!?")
        if len(topic) < 2:
            return True
        if not topic.startswith(("o ", "z ")):
            topic = "o " + topic
        _begin(s, topic, speak)
        return True
    if s["phase"] == "choosing":
        i = _match(text, s["parts"][-1]["choices"])
        if i is None:
            c = s["parts"][-1]["choices"]
            speak(f"Wybierz: {c[0]} — czy {c[1]}? Możesz też dotknąć obrazka.")
            _listen_longer()
            return True
        choose(i)
        return True
    return False


def tap(x, y, W, H):
    """A tap on the story page (px): an idea, a choice, a story on the list."""
    import ui_screens
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "story":
            return False
        data = ov[2]
    hit = ui_screens.story_hit(x, y, W, H, data)
    if not hit:
        return True
    with _lock:
        s = _s
    if hit[0] == "idea" and s and s.get("phase") == "topic":
        from text_to_speech import speak
        threading.Thread(target=_begin, args=(s, data["ideas"][hit[1]], speak),
                         daemon=True).start()
    elif hit[0] == "choice":
        choose(hit[1])
    elif hit[0] == "card":
        page = data.get("page", 0)
        items = saved()
        k = page * PAGE + hit[1]
        if k < len(items):
            replay(items[k]["id"])
    elif hit[0] == "page":
        pages = max(1, -(-len(saved()) // PAGE))
        _show(page=(data.get("page", 0) + hit[1]) % pages)
    return True


def swipe(dx):
    """The list of stories: the next page (to the left) or the one before."""
    with state.lock:
        ov = state.overlay
        data = ov[2] if ov and ov[0] == "story" else None
    if not data or data.get("mode") != "list":
        return False
    pages = max(1, -(-len(saved()) // PAGE))
    _show(page=(data.get("page", 0) + (1 if dx < 0 else -1)) % pages)
    return True


def stop(quiet=False):
    """Ends the story (or its replay) now; back to her face."""
    global _s
    with _lock:
        s, _s = _s, None
    if not s:
        return False
    s["cancel"].set()
    if s["kind"] == "tell" and s.get("phase") != "end":
        _drop(s)                                  # (only finished stories are kept)
    with state.lock:
        if state.overlay and state.overlay[0] == "story":
            state.overlay = None
    if not quiet:
        try:
            import text_to_speech
            text_to_speech.stop_speaking("story")
        except Exception:
            pass
    print("[story] stopped", flush=True)
    return True


# ── the library ───────────────────────────────────────────────────────────────

def _save(s):
    out = {k: s.get(k) for k in ("id", "title", "genre", "art_style", "characters", "setting",
                                 "topic", "child")}
    out["created"] = time.time()
    out["parts"] = s["parts"]
    path = os.path.join(s["dir"], "story.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)
    for old in saved()[KEEP:]:
        shutil.rmtree(os.path.join(DIR, old["id"]), ignore_errors=True)
    print(f"[story] saved: {s['title']} ({s['id']})", flush=True)


def _drop(s):
    if s.get("dir") and os.path.isdir(s["dir"]):
        shutil.rmtree(s["dir"], ignore_errors=True)


def saved():
    """The finished stories, newest first: [{"id", "title", "parts", …}]."""
    out = []
    try:
        names = sorted(os.listdir(DIR), reverse=True)
    except OSError:
        return out
    for name in names:
        try:
            with open(os.path.join(DIR, name, "story.json"), encoding="utf-8") as f:
                st = json.load(f)
            st["id"] = name
            out.append(st)
        except (OSError, ValueError):
            continue
    return out


def image_path(story_id, image):
    return os.path.join(DIR, story_id, image) if image else None


def show_list(speak):
    items = saved()
    if not items:
        speak("Nie mamy jeszcze zapisanych bajek — powiedz „opowiedz bajkę, w której wybieram”!")
        return True
    stop(quiet=True)
    with state.lock:
        state.overlay = ("story", time.time() + 120, {"mode": "list", "page": 0})
    speak("Oto nasze bajki. Dotknij jednej, a opowiem ją jeszcze raz.")
    return True


def _find(words):
    """The story whose title or topic has these words; the newest without words."""
    items = saved()
    if not items:
        return None
    if not words:
        return items[0]
    stems = {w[:5] for w in re.findall(r"\w+", words.lower()) if len(w) >= 3}
    best = max(items, key=lambda st: len(stems & {
        w[:5] for w in re.findall(r"\w+", (st.get("title", "") + " " + (st.get("topic") or ""))
                                  .lower()) if len(w) >= 3}))
    hits = stems & {w[:5] for w in re.findall(r"\w+", (best.get("title", "") + " " +
                                                       (best.get("topic") or "")).lower())}
    return best if hits else None


def replay(story_id):
    """A saved story told again, with its pictures and the choices made."""
    global _s
    st = next((x for x in saved() if x["id"] == story_id), None)
    if not st:
        return False
    stop(quiet=True)
    s = {"cancel": threading.Event(), "kind": "replay", "phase": "replay", "id": story_id}
    with _lock:
        _s = s

    def run():
        global _s
        parts = st["parts"]
        first = image_path(story_id, parts[0].get("image")) if parts else None
        _show(mode="replay", title=st["title"], part=1, of=len(parts), image=first,
              choices=[], status=None)
        _say(f"{st['title']}.")
        for n, p in enumerate(parts, 1):
            if _cancelled(s):
                return
            img = image_path(story_id, p.get("image"))
            _show(part=n, image=img if img and os.path.exists(img) else None)
            _say(p["text"])
            if _cancelled(s):
                return
            if p.get("chosen"):
                _show(status=f"Wybór: {p['chosen']}")
                _say(f"Wybraliśmy: {p['chosen']}.")
                _show(status=None)
        if _cancelled(s):
            return
        _show(mode="end", status="Koniec")
        _say("Koniec!")
        with _lock:
            if _s is s:
                _s = None
        time.sleep(END_PAUSE * 0.7)
        if not _page_gone() and not active():
            with state.lock:
                state.overlay = None
    threading.Thread(target=run, daemon=True, name="story-replay").start()
    return True


def delete(words, speak):
    st = _find(words)
    if not st:
        speak("Nie znalazłam takiej bajki.")
        return True
    shutil.rmtree(os.path.join(DIR, st["id"]), ignore_errors=True)
    speak(f"Usunęłam bajkę „{st['title']}”.")
    return True


def handle(text, speak):
    """Starts, lists, replays, deletes. True when handled."""
    low = (text or "").lower().strip()
    if wanted(low):
        return start(text, speak)
    if _LIST.search(low):
        return show_list(speak)
    m = _DELETE.search(low)
    if m:
        return delete(m.group(1) or "", speak)
    m = _REPLAY.search(low)
    # (only with words that mean "again": a plain "opowiedz bajkę o smoku" is
    # her ordinary story, made up by the model)
    if m and saved() and re.search(r"jeszcze\s+raz|znowu|ponownie|ostatni|nasz|zapisan", low):
        st = _find(m.group(1) or "")
        if not st:
            speak("Nie znalazłam takiej bajki — powiedz „pokaż moje bajki”.")
            return True
        speak("Dobrze, posłuchaj.")
        replay(st["id"])
        return True
    return False
