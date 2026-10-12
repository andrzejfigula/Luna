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
import threading
import time
import urllib.parse
import urllib.request

from config import DATA_DIR

DIR = os.path.join(DATA_DIR, "webphotos")
KEEP = 20
GAP = 5
_API = "https://pl.wikipedia.org/w/api.php?"
_UA = {"User-Agent": "Luna-robot/1.0 (https://github.com/andrzejfigula/Luna; home robot)"}
# a photo shown to a child: far stricter than the moderation's own "flagged"
_LIMITS = {"sexual": 0.02, "sexual_minors": 0.01, "violence": 0.35, "violence_graphic": 0.05,
           "self_harm": 0.05, "self_harm_intent": 0.05, "self_harm_instructions": 0.05,
           "harassment": 0.3, "harassment_threatening": 0.1, "hate": 0.1,
           "hate_threatening": 0.05, "illicit": 0.3, "illicit_violent": 0.1}
_last = [0.0]


def _get(params, timeout=6):
    url = _API + urllib.parse.urlencode(dict(params, format="json", formatversion="2"))
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return json.load(r)


def _title(client, what):
    """"żyrafy" → "Żyrafa" (the small model knows Polish cases and Wikipedia)."""
    from config import OPENAI_MODEL
    r = client.chat.completions.create(
        model=OPENAI_MODEL, temperature=0.0, max_tokens=20,
        messages=[{"role": "user", "content":
                   "Dziecko prosi robota: „pokaż mi zdjęcie " + what + "”. Podaj dokładny "
                   "tytuł artykułu w polskiej Wikipedii, którego główne zdjęcie najlepiej to "
                   "pokazuje (np. „żyrafy” → Żyrafa, „lwa” → Lew afrykański, „wieży Eiffla” → "
                   "Wieża Eiffla). Jeśli to nie jest rzecz, zwierzę, roślina, miejsce ani "
                   "zjawisko, które da się sfotografować, napisz: BRAK. Tylko tytuł."}])
    t = (r.choices[0].message.content or "").strip().strip("„”\"'.")
    return None if not t or t.upper() == "BRAK" or len(t) > 60 else t


def _page(title):
    """(title, thumbnail url) of that article, redirects followed; None without a photo."""
    d = _get({"action": "query", "titles": title, "redirects": "1",
              "prop": "pageimages|pageprops", "piprop": "thumbnail", "pithumbsize": "960",
              "ppprop": "disambiguation"})
    for p in d.get("query", {}).get("pages", []):
        src = (p.get("thumbnail") or {}).get("source")
        if p.get("missing") or "pageprops" in p or not src:
            continue
        if "logo" in src.lower():
            continue                                    # a logo, not a photo
        return p["title"], src
    return None


def pick(client, what):
    """(title, url) of the photo for `what`, or None."""
    title = _title(client, what)
    found = title and _page(title)
    # her word for it, not the redirect's ("Żyrafa", not "Giraffinae")
    return (title, found[1]) if found else None


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


def show(what, speak, fallback):
    """Find and show a photo of `what` in the background; `fallback()` (her
    drawing) when there is none or it isn't for a child. True (handled)."""
    if time.time() - _last[0] < GAP:
        return fallback()
    _last[0] = time.time()
    speak("Dobrze, szukam zdjęcia. Chwileczkę!")

    def run():
        from text_to_speech import speak as say
        from shared_state import state
        try:
            from openai import OpenAI
            from config import OPENAI_API_KEY
            c = OpenAI(api_key=OPENAI_API_KEY, timeout=20, max_retries=1)
            found = pick(c, what)
            if not found:
                print(f"[webphoto] no photo for {what!r}", flush=True)
                return fallback("Dobrze, zdjęcia nie znalazłam, ale narysuję. Chwileczkę!")
            title, url = found
            with urllib.request.urlopen(urllib.request.Request(url, headers=_UA),
                                        timeout=10) as r:
                img = r.read(4_000_000)
            if not safe(c, what, img):
                return fallback("Dobrze, tego zdjęcia nie pokażę, ale narysuję. Chwileczkę!")
            os.makedirs(DIR, exist_ok=True)
            ext = ".png" if img[:4] == b"\x89PNG" else ".jpg"
            out = os.path.join(DIR, time.strftime("%Y%m%d-%H%M%S") + ext)
            with open(out, "wb") as f:
                f.write(img)
            old = sorted(os.listdir(DIR))[:-KEEP]
            for name in old:
                try:
                    os.remove(os.path.join(DIR, name))
                except OSError:
                    pass
            with state.lock:
                state.overlay = ("photo", time.time() + 40, out)
            print(f"[webphoto] {what!r} → {title} ({url.split('?')[0]})", flush=True)
            say(f"Dobrze, proszę — {title}, zdjęcie z Wikipedii.")
            with state.lock:
                # "a lwa?" next needs no "Luna"
                state.conversation_active = True
                state.last_activity_time = max(state.last_activity_time, time.time())
            try:
                import brain       # the model knows what is on her screen
                brain.add_to_last_reply(f"(Na ekranie zdjęcie z Wikipedii: {title}.)")
            except Exception:
                pass
        except Exception as e:
            print(f"[webphoto] failed: {e}", flush=True)
            fallback("Dobrze, zdjęcia nie znalazłam, ale narysuję. Chwileczkę!")
    threading.Thread(target=run, daemon=True, name="webphoto").start()
    return True
