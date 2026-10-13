"""
webphoto.py — "Luna, pokaż mi zdjęcie żyrafy": a real photo, from Wikipedia.

  "pokaż mi zdjęcie żyrafy / wieży Eiffla / Marsa"
        → "Dobrze, szukam zdjęcia. Chwileczkę!", then the article's main photo,
          big, for 40 s: "Dobrze, proszę — Żyrafa, zdjęcie z Wikipedii."

The words ("żyrafy", genitive) become an article title with the small model
("Żyrafa") — Wikipedia's own search took "lwa" for "Mostwa" and "żyrafy" for
the giraffe family with an okapi in the picture. The photo is the article's
lead image, and before it is shown both the request and the photo go through
OpenAI's moderation (free), with thresholds far below its own: Maja asks for
these. Anything unsure, missing or failed → she draws it instead, as before.
(9 Oct 09:37: "pokaż mi zdjęcie żyrafy" — "Zdjęć nie mam, ale narysuję".)
"""

import base64
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from config import DATA_DIR

DIR = os.path.join(DATA_DIR, "webphotos")
KEEP = 20
_busy = threading.Lock()   # one search at a time (a request and the model's
                           # command for it came together — 12 Oct)
_API = "https://pl.wikipedia.org/w/api.php?"
_EN = "https://en.wikipedia.org/w/api.php?"
_UA = {"User-Agent": "Luna-robot/1.0 (https://github.com/andrzejfigula/Luna; home robot)"}
# a photo shown to a child: far stricter than the moderation's own "flagged"
_LIMITS = {"sexual": 0.02, "sexual_minors": 0.01, "violence": 0.35, "violence_graphic": 0.05,
           "self_harm": 0.05, "self_harm_intent": 0.05, "self_harm_instructions": 0.05,
           "harassment": 0.3, "harassment_threatening": 0.1, "hate": 0.1,
           "hate_threatening": 0.05, "illicit": 0.3, "illicit_violent": 0.1}


# topics whose photo isn't for a child, whatever the moderation says of the
# picture (13 Oct check: a pistol, "Wojna", an atomic bomb, a cigarette, beer and
# Hitler all passed it — the photos weren't graphic, the subjects are the point)
NOT_FOR_KIDS = re.compile(
    r"pistolet|karabin|strzelb|rewolwer|\bbroń|\bbron\b|amunic|granat|\bbomb|atomow|"
    r"nuklearn|\bwojn|wojenn|\bwar\b|weapon|\bguns?\b|rifle|\bbomb|terror|zamach|"
    r"papieros|cygar|tytoń|tyton|\bfajk|e-papieros|cigar|tobacco|\bsmoking\b|"
    r"\bpiw(?:o|a|em|ie|ko)\b|wódk|wodk|\bwin[oa]\b|alkohol|whisk|\bbeer|\bwine\b|vodka|"
    r"alcohol|"
    r"narkot|marihuan|kokain|heroin|drug|cannabis|"
    r"hitler|nazis|nazi\b|swastyk|stalin|ss-man|holokaust|holocaust|"
    r"zabój|zaboj|morder|zabójstw|zwłok|zwlok|\btrup|samobój|samoboj|suicid|"
    r"\bseks|\bsex|erotyk|porno|\bnag[aiy]\b|\bnagie|nagość|nagosc|\bnude", re.I)


def _get(params, timeout=6, api=_API):
    url = api + urllib.parse.urlencode(dict(params, format="json", formatversion="2"))
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return json.load(r)


def _title(client, what):
    """"żyrafy" → ("Żyrafa", "Giraffe"): the article in the Polish and the
    English Wikipedia (the small model knows Polish cases and Wikipedia)."""
    from config import OPENAI_MODEL
    r = client.chat.completions.create(
        model=OPENAI_MODEL, temperature=0.0, max_tokens=40,
        messages=[{"role": "user", "content":
                   "Dziecko prosi robota: „pokaż mi zdjęcie " + what + "”. Podaj dokładne "
                   "tytuły artykułu o tym (nie strony ujednoznaczniającej) w polskiej i w "
                   "angielskiej Wikipedii, którego główne zdjęcie najlepiej to pokazuje, w "
                   "jednej linii: polski | angielski (np. „żyrafy” → Żyrafa | Giraffe, „lwa” → "
                   "Lew afrykański | Lion, „T-rexa” → Tyranozaur | Tyrannosaurus). Jeśli to nie "
                   "jest rzecz, zwierzę, roślina, miejsce ani zjawisko, które da się "
                   "sfotografować, napisz: BRAK. Tylko ta linia."}])
    line = (r.choices[0].message.content or "").strip()
    if not line or line.upper().startswith("BRAK"):
        return None
    parts = [t.strip().strip("„”\"'.") for t in line.split("|")]
    pl = parts[0] if parts and 0 < len(parts[0]) <= 60 else None
    en = parts[1] if len(parts) > 1 and 0 < len(parts[1]) <= 60 else None
    return (pl, en) if pl or en else None


def spoken(title):
    """"Saturn (planeta)" → "Saturn" — the bracket is Wikipedia's, not hers."""
    return re.sub(r"\s*\([^)]*\)", "", title or "").strip() or title


def _page(title, api=_API):
    """(title, thumbnail url) of that article, redirects followed; None without a photo."""
    d = _get({"action": "query", "titles": title, "redirects": "1",
              "prop": "pageimages|pageprops", "piprop": "thumbnail", "pithumbsize": "960",
              "ppprop": "disambiguation"}, api=api)
    for p in d.get("query", {}).get("pages", []):
        src = (p.get("thumbnail") or {}).get("source")
        if p.get("missing") or "pageprops" in p or not src:
            continue
        if "logo" in src.lower():
            continue                                    # a logo, not a photo
        return p["title"], src
    return None


def _stems(text):
    import unicodedata
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c)).replace("ł", "l")
    return {w[:4] for w in re.findall(r"[a-z]+", t) if len(w) >= 3}


def _search(words, api=_API):
    """Wikipedia's own search, but only an article sharing a word with what
    was asked ("lwa" alone found "Mostwa")."""
    d = _get({"action": "query", "generator": "search", "gsrsearch": words, "gsrlimit": "5",
              "prop": "pageimages|pageprops", "piprop": "thumbnail", "pithumbsize": "960",
              "ppprop": "disambiguation"}, api=api)
    want = _stems(words)
    for p in sorted(d.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99)):
        src = (p.get("thumbnail") or {}).get("source")
        if src and "pageprops" not in p and "logo" not in src.lower() \
                and _stems(p.get("title")) & want:
            return p["title"], src
    return None


def pick(client, what):
    """(her name for it, photo url, api, article) for `what`, or None. The
    Polish article first, then the English one (richer in photos — 13 Oct:
    pająk, wiewiórka, lama, T-rex, rakieta had no photo on the Polish one),
    then a Polish search."""
    titles = _title(client, what)
    if not titles:
        return None
    pl, en = titles
    if NOT_FOR_KIDS.search(" ".join(x for x in (what, pl, en) if x)):
        print(f"[webphoto] not for a child: {what!r} ({pl} / {en})", flush=True)
        return "not for kids"
    tries = ([(_API, pl, _page)] if pl else []) + ([(_EN, en, _page)] if en else []) \
        + ([(_API, pl, _search)] if pl else [])
    for api, title, how in tries:
        found = how(title, api)
        if found:
            # her word for it, not the redirect's ("Żyrafa", not "Giraffinae")
            return pl or found[0], found[1], api, found[0]
    return None


def safe(client, what, img):
    """The request and the photo, both well under the child limits."""
    r = client.moderations.create(model="omni-moderation-latest", input=[
        {"type": "text", "text": f"zdjęcie {what}"},
        {"type": "image_url",
         "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}}])
    res = r.results[0]
    if res.flagged:
        return False
    scores = res.category_scores.model_dump()
    bad = {k: v for k, v in scores.items() if v and v > _LIMITS.get(k, 0.5)}
    if bad:
        print(f"[webphoto] not shown: {bad}", flush=True)
    return not bad


def _client():
    from openai import OpenAI
    from config import OPENAI_API_KEY
    return OpenAI(api_key=OPENAI_API_KEY, timeout=20, max_retries=1)


def _download(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=10) as r:
        return r.read(4_000_000)


def _key(url):
    """The file behind a thumbnail URL — the lead photo and the article's list
    give it from different hosts and sizes."""
    m = re.search(r"/commons/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/?]+)", url or "")
    return m.group(1) if m else (url or "").split("?")[0]


def _present(img, title, url, line):
    """Save, show for 40 s, say `line`; the model hears what is on the screen."""
    from text_to_speech import speak as say
    from shared_state import state
    os.makedirs(DIR, exist_ok=True)
    ext = ".png" if img[:4] == b"\x89PNG" else ".jpg"
    out = os.path.join(DIR, time.strftime("%Y%m%d-%H%M%S") + ext)
    with open(out, "wb") as f:
        f.write(img)
    for name in sorted(os.listdir(DIR))[:-KEEP]:
        try:
            os.remove(os.path.join(DIR, name))
        except OSError:
            pass
    with state.lock:
        # its name under it — Maja reads it ("Żyrafa · Wikipedia")
        state.overlay = ("photo", time.time() + 40,
                         {"path": out, "sub": f"{spoken(title)} · Wikipedia"})
    print(f"[webphoto] {title} ({url.split('?')[0]})", flush=True)
    _shown.update(at=time.time(), path=out)
    _shown.setdefault("used", set()).add(_key(url))
    say(line)
    with state.lock:
        # "a lwa?", "pokaż inne" next need no "Luna"
        state.conversation_active = True
        state.last_activity_time = max(state.last_activity_time, time.time())
    try:
        import brain       # the model knows what is on her screen
        brain.add_to_last_reply(f"(Na ekranie zdjęcie z Wikipedii: {title}.)")
    except Exception:
        pass


def show(what, speak, fallback):
    """Find and show a photo of `what` in the background; `fallback()` (her
    drawing) when there is none or it isn't for a child. True (handled)."""
    from shared_state import state
    with state.lock:
        online = state.online
    if not online:
        # (the drawing needs the internet too — two failures in a row otherwise)
        speak("Nie mam teraz internetu, więc nie pokażę zdjęcia. Spróbujmy później!")
        return True
    if not _busy.acquire(blocking=False):
        # still finding the last one (13 Oct sweep: a second request within 5 s
        # was drawn instead)
        if threading.current_thread().name != "command":
            speak("Chwileczkę, jeszcze szukam.")
        return True
    if threading.current_thread().name != "command":
        # (from the model's answer her "Pokażę ci słonia" was just said)
        speak("Dobrze, szukam zdjęcia. Chwileczkę!")

    def run():
        try:
            _find()
        finally:
            _busy.release()

    def _find():
        try:
            c = _client()
            found = pick(c, what) if not NOT_FOR_KIDS.search(what) else "not for kids"
            if found == "not for kids":
                # (no drawing of it either — a cheerful pistol is no better)
                from text_to_speech import speak as say
                say("Tego zdjęcia nie pokażę — to nie jest dla dzieci. Może pokażę ci coś innego?")
                return
            if not found:
                print(f"[webphoto] no photo for {what!r}", flush=True)
                return fallback("Dobrze, zdjęcia nie znalazłam, ale narysuję. Chwileczkę!")
            title, url, api, article = found
            img = _download(url)
            if not safe(c, what, img):
                return fallback("Dobrze, tego zdjęcia nie pokażę, ale narysuję. Chwileczkę!")
            _shown.clear()
            _shown.update(what=what, title=title, api=api, article=article)
            _present(img, title, url, f"Dobrze, proszę — {spoken(title)}, zdjęcie z Wikipedii.")
        except Exception as e:
            print(f"[webphoto] failed: {e}", flush=True)
            fallback("Dobrze, zdjęcia nie znalazłam, ale narysuję. Chwileczkę!")
    threading.Thread(target=run, daemon=True, name="webphoto").start()
    return True


# ── "pokaż inne zdjęcie": the next photo from the same article (13 Oct) ───────

_shown = {}            # the last photo: what, title, at, used (urls already shown)
MORE_SECS = 300        # "inne zdjęcie" this long after a photo
BARE_MORE_SECS = 120   # a bare "jeszcze jedno" only right after
_MORE = re.compile(r"^(?:luna,?\s+)?(?:a\s+|i\s+|no\s+to\s+)?(?:(?:pokaż|pokaz)\s+(?:mi\s+|nam\s+)?)?"
                   r"(?:(?:jakieś\s+|jakies\s+)?inne|jeszcze\s+jedno|następne|nastepne|kolejne|"
                   r"drugie|więcej|wiecej)(?:\s+zdjęci[ea]|\s+zdjęć|\s+zdjec)?[.!?]*$", re.I)
# not a photo of the thing: maps, charts, coats of arms, logos
_NOT_A_PHOTO = re.compile(r"map|diagram|schemat|logo|flag|herb|wykres|chart|interior|range|"
                          r"zasięg|zasieg|distribution|locator|icon|ikona|signature|podpis", re.I)


_AGAIN = re.compile(r"^(?:luna,?\s+)?(?:a\s+)?(?:(?:pokaż|pokaz)\s+(?:mi\s+|nam\s+)?"
                    r"(?:to|je|ją|ja|go|tę\s+\w+|to\s+zdjęcie|zdjęcie)?\s*)?"
                    r"(?:jeszcze\s+raz|znowu|ponownie)(?:\s+(?:to\s+)?zdjęcie)?[.!?]*$", re.I)
AGAIN_SECS = 600


def again_wanted(text, now=None):
    """"Pokaż to jeszcze raz" just after a photo of hers (it's gone from the
    screen after 40 s): the same picture, from disk."""
    now = now if now is not None else time.time()
    # a bare "jeszcze raz" only right after (a game's "Zagramy jeszcze raz?" comes later)
    secs = AGAIN_SECS if re.search(r"pokaż|pokaz|zdję|zdje", text or "", re.I) else 90
    return bool(_AGAIN.match((text or "").strip()) and _shown.get("path")
                and os.path.exists(_shown["path"]) and now - _shown.get("at", 0) < secs)


def show_again(speak):
    from shared_state import state
    with state.lock:
        state.overlay = ("photo", time.time() + 40,
                         {"path": _shown["path"],
                          "sub": f"{spoken(_shown.get('title', ''))} · Wikipedia"})
    speak(f"Proszę — {spoken(_shown.get('title', ''))}." if _shown.get("title") else "Proszę.")
    return True


def more_wanted(text, now=None):
    """"Pokaż inne zdjęcie" / "jeszcze jedno" just after a photo of hers."""
    now = now if now is not None else time.time()
    m = _MORE.match((text or "").strip())
    if not m or not _shown.get("title"):
        return False
    photo_said = re.search(r"zdj|pokaż|pokaz", m.group(0), re.I)
    return now - _shown.get("at", 0) < (MORE_SECS if photo_said else BARE_MORE_SECS)


def _photos(title, api=_API):
    """The article's other photos: [url], biggest first; maps and logos left out."""
    d = _get({"action": "query", "titles": title, "redirects": "1", "generator": "images",
              "gimlimit": "40", "prop": "imageinfo", "iiprop": "url|size|mime",
              "iiurlwidth": "960"}, timeout=8, api=api)
    out = []
    for p in d.get("query", {}).get("pages", []):
        ii = (p.get("imageinfo") or [{}])[0]
        if (ii.get("mime") == "image/jpeg" and ii.get("width", 0) >= 500
                and ii.get("height", 0) >= 300 and not _NOT_A_PHOTO.search(p.get("title", ""))):
            out.append((ii["width"] * ii["height"], ii.get("thumburl") or ii.get("url")))
    return [u for _, u in sorted(out, reverse=True) if u]


def more(speak):
    """The next photo of the same thing. True (handled)."""
    if not _busy.acquire(blocking=False):
        if threading.current_thread().name != "command":
            speak("Chwileczkę, jeszcze szukam.")
        return True
    title, what = _shown["title"], _shown.get("what", "")
    if threading.current_thread().name != "command":
        speak("Dobrze, szukam innego. Chwileczkę!")

    def run():
        try:
            _next()
        finally:
            _busy.release()

    def _next():
        from text_to_speech import speak as say
        try:
            c = _client()
            used = _shown.setdefault("used", set())
            for url in _photos(_shown.get("article") or title, _shown.get("api") or _API):
                if _key(url) in used:
                    continue
                used.add(_key(url))
                img = _download(url)
                if not safe(c, what or title, img):
                    continue
                return _present(img, title, url, f"Dobrze, proszę — jeszcze jedno: {spoken(title)}.")
            say("Więcej zdjęć tego nie mam — to były wszystkie z Wikipedii.")
        except Exception as e:
            print(f"[webphoto] more failed: {e}", flush=True)
            say("Nie udało mi się znaleźć innego zdjęcia.")
    threading.Thread(target=run, daemon=True, name="webphoto").start()
    return True
