"""
news.py — the news, from real headlines.

  "Jakie są wiadomości?" / "Co słychać na świecie?" / "Przeczytaj najnowsze
  wiadomości" / "Co nowego w Polsce?"

Without this she had no news at all — and asked for "trzy najważniejsze
wiadomości na dzisiaj" she made some up from her memory of the day. Now the
latest headlines come from public RSS feeds (RMF24, Polsat News as a
fallback), cached for NEWS_CACHE_SECS, and go to the model as context for
THIS question only (not into the chat history or her memory), with the rule
to summarise them, not to add anything.
"""

import html
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

FEEDS = [("RMF24", "https://www.rmf24.pl/feed"),
         ("Polsat News", "https://www.polsatnews.pl/rss/wszystkie.xml")]
NEWS_CACHE_SECS = 600
NEWS_COUNT = 12

_TRIGGERS = ("najnowsze wiadomości", "najważniejsze wiadomości", "przeczytaj wiadomości",
             "jakie są wiadomości", "jakie są dzisiaj wiadomości", "jakie są dziś wiadomości",
             "co w wiadomościach", "wiadomości ze świata", "wiadomości z kraju",
             "wiadomości z polski", "newsy", "co słychać na świecie", "co słychać w polsce",
             "co słychać w kraju", "co się dzieje na świecie", "co się dzieje w polsce",
             "co się dzieje w kraju", "co nowego na świecie", "co nowego w polsce",
             "co nowego w kraju", "serwis informacyjny", "przegląd wiadomości",
             "wiadomości na dzisiaj", "wiadomości na dziś", "dzisiejsze wiadomości",
             "the news", "news today", "latest news")

_lock = threading.Lock()
_cache = {"t": 0.0, "items": [], "source": ""}


# "co dzisiaj ważnego się stało na świecie?" (6 Oct: missed — the model offered
# "nagłówki z RMF24", and after "chcę" read out headlines it had made up)
_ASK_RX = re.compile(
    r"\bco\b[^.?!]{0,30}\b(?:stało|wydarzyło|dzieje|działo|słychać|nowego|ciekawego)\b"
    r"[^.?!]{0,30}\b(?:na\s+świecie|w\s+polsce|w\s+kraju|w\s+europie)\b|"
    r"\bco\b[^.?!]{0,20}\b(?:ważnego|ciekawego)\b[^.?!]{0,20}\b(?:stało|wydarzyło)\b|"
    r"\b(?:nagłówki|najnowsze\s+informacje|wiadomości\s+dnia)\b|"
    # "co dzisiaj w wiadomościach?", "nowe informacje z kraju", "co słychać w
    # świecie?" (7 Oct: these reached the model without headlines — it makes
    # news up from what it remembers of the house)
    r"\bco\b[^.?!]{0,15}\bw\s+(?:wiadomościach|dzienniku|serwisie)\b|"
    r"\binformacje\s+(?:z\s+kraju|ze\s+świata|z\s+polski)\b|"
    r"\bco\s+(?:słychać|nowego|się\s+dzieje)\s+w\s+świecie\b", re.I)
_YES = re.compile(r"^(?:no\s+)?(?:tak|chcę|chce|poproszę|poprosze|dawaj|jasne|pewnie|okej|ok|"
                  r"dobrze|czemu\s+nie|chętnie)\b", re.I)
_OFFERED = re.compile(r"nagłówk|wiadomości|newsy", re.I)


def is_yes(text):
    low = text.lower().strip(" .!?")
    return bool(_YES.match(low)) and len(low.split()) <= 4 and "nie" not in low.split()


def accepts_offer(text, last_reply):
    """"Chcę." right after she offered the news ("…mogę podać najnowsze
    nagłówki, jeśli chcesz") — the headlines must be fetched for THIS answer,
    or the model reads out ones it invents."""
    return (is_yes(text) and bool(_OFFERED.search(last_reply or ""))
            and ("?" in last_reply or "jeśli chcesz" in last_reply.lower()))


def is_request(text):
    low = text.lower()
    if re.search(r"\b(mam|moje|moich|dla mnie|głosow|nagr)", low):
        return False                      # "jakie mam wiadomości" — voice messages
    if any(t in low for t in _TRIGGERS) or _ASK_RX.search(low):
        return True
    # "co słychać w sporcie?", "wiadomości sportowe", "co nowego w polityce?"
    return bool(re.search(r"\bco (?:słychać|slychac|nowego|się dzieje|sie dzieje) w "
                          r"(?:sporcie|polityce|gospodarce|kulturze|nauce|europie|ameryce|"
                          r"ukrainie|niemczech|usa|technologii)\b|"
                          r"\bwiadomości (?:sportowe|polityczne|gospodarcze|ze sportu|z kraju)",
                          low))


def _clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return " ".join(s.split())


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Luna-robot"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=8).read())
    out = []
    for it in root.findall(".//item")[:NEWS_COUNT]:
        title = _clean(it.findtext("title"))
        desc = _clean(it.findtext("description"))[:240]
        when = (it.findtext("pubDate") or "")[:22]
        if title:
            out.append((title, desc, when))
    return out


# the general feeds hardly carry sport: "co słychać w sporcie?" found nothing
# (7 Oct probe) — a sport question reads these instead
SPORT_FEEDS = [("WP SportoweFakty", "https://sportowefakty.wp.pl/rss.xml"),
               ("Interia Sport", "https://sport.interia.pl/feed")]
_SPORT_RX = re.compile(r"\bspor[tc]\w*|\bmecz\w*|\bpiłk\w*|\bpilk\w*|\bligi?\b|\bligach\b|"
                       r"\bwynik\w*\s+(?:meczu|meczów)", re.I)
_sport_cache = {"t": 0.0, "items": [], "source": ""}


def headlines(sport=False):
    """[(title, description, date)] and the source name; [] when offline."""
    cache, feeds = (_sport_cache, SPORT_FEEDS) if sport else (_cache, FEEDS)
    with _lock:
        if time.time() - cache["t"] < NEWS_CACHE_SECS and cache["items"]:
            return cache["items"], cache["source"]
    for name, url in feeds:
        try:
            items = _fetch(url)
        except Exception as e:
            print(f"[news] {name}: {e}", flush=True)
            continue
        if items:
            with _lock:
                cache.update(t=time.time(), items=items, source=name)
            print(f"[news] {len(items)} headlines from {name}", flush=True)
            return items, name
    return [], ""


def context(text=""):
    """The headlines as a system-prompt block, or None (sport ones for a
    sport question)."""
    items, source = headlines(sport=bool(_SPORT_RX.search(text or "")))
    if not items:
        return None
    lines = "\n".join(f"- {t}" + (f" — {d}" if d else "") + (f" ({w})" if w else "")
                      for t, d, w in items)
    child = None
    try:
        import faces
        from shared_state import state
        with state.lock:
            who = state.person[0] if state.person else None
        if who and "dziecko" in faces.notes().get(who, "").lower():
            child = who
    except Exception:
        pass
    head = f"\nLATEST NEWS HEADLINES from {source} (RSS, fetched just now):\n{lines}\n"
    if child:
        # a soft extra sentence lost to "pick the 3 most important" (tested):
        # for a child the whole instruction is different
        return (head + f"You are talking to {child}, a CHILD. From these headlines "
                "tell ONLY the ones with nothing about violence, crime, vandalism, "
                "fires, accidents, war, disasters, illness or death — sport, science, "
                "animals, culture, nice events — at most 3, simply, one short sentence "
                "each, in Polish. Fewer is fine; if none fits, say kindly that today "
                "there is nothing interesting for kids in the news. Never add news "
                "that is not listed.\n")
    return (head +
            "The user asked for the news. Answer ONLY from these headlines: pick the "
            "3 most important (or what they asked about), one short sentence each, in "
            "your own words, in Polish; mention the source once (\"według " + source +
            "\"). Never add news that is not listed here. If they asked about a topic "
            "that is not here, say you don't see anything about it in the headlines.\n")
