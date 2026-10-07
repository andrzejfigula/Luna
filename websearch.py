"""
websearch.py — she can look things up on the internet.

  "Poszukaj w internecie, jaki zasięg ma Rode NT-USB" / "sprawdź w internecie
  godziny otwarcia Biedronki" — and the model's own command "wyszukaj w
  internecie: …" when a question needs facts it doesn't have (specs, prices,
  opening hours, results, details of an event).

The search is OpenAI's web_search tool (Responses API, 3–7 s), asked for a
short factual answer in Polish; what it finds goes back to the model as
context for THIS answer, which she then says. Links and markdown are dropped
— she speaks. (6 Oct: Andrzej, choosing a microphone with her: "Opowiedz
Claude'owi, żeby dał ci opcję wyszukiwania w internecie".)
"""

import re
import threading

from config import OPENAI_API_KEY, SEARCH_MODEL, SEARCH_TIMEOUT

_START = re.compile(
    r"^(?:luna,?\s+)?(?:poszukaj|wyszukaj|sprawdź|sprawdz|znajdź|znajdz|zobacz)\s+"
    r"(?:mi\s+)?(?:w\s+internecie|w\s+sieci|w\s+google|w\s+necie|online)[:,]?\s*(.{3,200}?)[.?!]?$",
    re.I)
_client = None


def _cli():
    global _client
    if _client is None and OPENAI_API_KEY:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY, timeout=SEARCH_TIMEOUT, max_retries=0)
    return _client


def request(text):
    """The query in "poszukaj w internecie …", or None."""
    m = _START.match((text or "").strip())
    return m.group(1).strip(" ,") if m else None


def clean(text):
    """Speakable: no markdown, no links, no URLs."""
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text or "")    # [text](url) → text
    t = re.sub(r"\(\s*\)|https?://\S+", "", t)
    t = re.sub(r"\s*\(\s*[\w.-]+\.(?:pl|com|org|net|eu|io|de|info|gov)\b[^)]*\)", "", t)  # (site.pl)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    t = re.sub(r"[*_`]+", "", t)
    return " ".join(t.split())[:800]


def _location():
    try:
        import settings
        place = (settings.get("weather_place") or {}).get("name")
    except Exception:
        place = None
    loc = {"type": "approximate", "country": "PL"}
    if place:
        loc["city"] = place
    return loc


def search(query):
    """A short factual answer from the web, or None (no key, no network, nothing)."""
    c = _cli()
    if c is None:
        return None
    try:
        r = c.responses.create(
            model=SEARCH_MODEL,
            tools=[{"type": "web_search", "search_context_size": "low",
                    "user_location": _location()}],
            instructions=("Odpowiadaj po polsku, krótko (2–4 zdania), same konkretne fakty "
                          "z wyszukiwania, bez linków i bez markdownu. Jeśli nic pewnego "
                          "nie ma, napisz to wprost."),
            input=query,
            **({"reasoning": {"effort": "none"}} if SEARCH_MODEL.startswith("gpt-5") else {}))
        found = clean(r.output_text)
        print(f"[search] {query!r} → {found[:120]!r}", flush=True)
        return found or None
    except Exception as e:
        print(f"[search] failed ({e})", flush=True)
        return None


def context(query, found):
    return ("\nWEB SEARCH just now, for «" + query + "»: " + found + "\nAnswer their "
            "question from this in 1–3 spoken sentences — no links, no markdown; numbers "
            "rounded the way people say them (4,37 zł, not 4,3719); name the "
            "source only if asked. If it doesn't answer the question, say what you found "
            "and that you're not sure.\n")


def start(query, speak, announce=True):
    """Look it up in the background; the answer is spoken when it comes."""
    if announce:
        speak("Sprawdzam w internecie…")

    def run():
        found = search(query)
        import brain
        if found:
            brain.process(f"(Wynik wyszukiwania: {query})", context=context(query, found))
        else:
            from text_to_speech import speak as say
            say("Nie udało mi się nic znaleźć w internecie.")
    threading.Thread(target=run, daemon=True, name="websearch").start()
    return True
