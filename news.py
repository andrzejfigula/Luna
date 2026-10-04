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


def is_request(text):
    low = text.lower()
    if re.search(r"\b(mam|moje|moich|dla mnie|głosow|nagr)", low):
        return False                      # "jakie mam wiadomości" — voice messages
    if any(t in low for t in _TRIGGERS):
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


def headlines():
    """[(title, description, date)] and the source name; [] when offline."""
    with _lock:
        if time.time() - _cache["t"] < NEWS_CACHE_SECS and _cache["items"]:
            return _cache["items"], _cache["source"]
    for name, url in FEEDS:
        try:
            items = _fetch(url)
        except Exception as e:
            print(f"[news] {name}: {e}", flush=True)
            continue
        if items:
            with _lock:
                _cache.update(t=time.time(), items=items, source=name)
            print(f"[news] {len(items)} headlines from {name}", flush=True)
            return items, name
    return [], ""


def context():
    """The headlines as a system-prompt block, or None."""
    items, source = headlines()
    if not items:
        return None
    lines = "\n".join(f"- {t}" + (f" — {d}" if d else "") + (f" ({w})" if w else "")
                      for t, d, w in items)
    return (f"\nLATEST NEWS HEADLINES from {source} (RSS, fetched just now):\n{lines}\n"
            "The user asked for the news. Answer ONLY from these headlines: pick the "
            "3 most important (or what they asked about), one short sentence each, in "
            "your own words, in Polish; mention the source once (\"według " + source +
            "\"). Never add news that is not listed here. If they asked about a topic "
            "that is not here, say you don't see anything about it in the headlines.\n")
