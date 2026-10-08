"""
memory.py — what Luna remembers between conversations.

The chat history (brain._history) is a short rolling window: after a few
exchanges, or a restart, yesterday is gone. This module keeps two things in
data/memory.json:

  facts     lasting things about the people she talks to — names, work,
            family, likes, plans with their dates, inside jokes, anything
            they asked her to remember
  episodes  one or two sentences per conversation worth following up on
            ("has a job interview tomorrow and is nervous"), with the date
  threads   open questions to come back to, each from a date on ("Jak poszła
            rozmowa o pracę?" from the day after the interview)

After a conversation ends (the conversation window times out), ONE cheap
model call reads what was said and returns the updated fact list and the
episode. Every request then carries a short memory block in the system
prompt, with episode dates turned into "wczoraj" / "3 dni temu". At the start
of a new conversation a thread that is due is handed to her as something to
ask now — "you may follow up" alone was too weak, the model never did. Each
thread is offered at most MEMORY_THREAD_ASKS times; the next consolidation
closes it once it has been talked about.

Everything stays in a plain JSON file on the Pi. "Luna, zapomnij wszystko"
wipes it (FORGET_PHRASES); LUNA_MEMORY=0 in .env switches memory off.
"""

import json
import re
import os
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from openai import OpenAI
except ImportError:          # tests on a PC without the SDK
    OpenAI = None

from shared_state import state
from config import (
    MEMORY_ENABLED,
    MEMORY_PATH,
    MEMORY_MAX_FACTS,
    MEMORY_MAX_EPISODES,
    MEMORY_PROMPT_EPISODES,
    MEMORY_MODEL,
    MEMORY_TIDY_MODEL,
    MEMORY_MAX_THREADS,
    MEMORY_THREAD_ASKS,
    FORGET_PHRASES,
    FORGET_REPLY,
    OPENAI_API_KEY,
    OPENAI_TIMEOUT,
    LUNA_TIMEZONE,
)

try:
    _TZ = ZoneInfo(LUNA_TIMEZONE)
except Exception:
    _TZ = None

_lock    = threading.Lock()      # guards the file and _session
_session = []                    # [(user_text, luna_reply, local)] not yet consolidated
_SESSION_MAX = 30                # turns kept for a retry after a failed consolidation
_added   = []                    # [(time, fact)] from "zapamiętaj, że…" — kept
                                 # even if a consolidation running meanwhile
                                 # rewrites the facts without them
_client  = (OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT, max_retries=1)
            if (OpenAI and OPENAI_API_KEY and MEMORY_ENABLED) else None)

_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "luna_memory",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                # written first, so the old facts are judged before the list is
                "dropped": {"type": "array", "items": {"type": "string"}},
                "facts":   {"type": "array", "items": {"type": "string"}},
                "episode": {"type": "string"},
                "routine_episodes": {"type": "array", "items": {"type": "string"}},
                "threads": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "due":      {"type": "string"},
                        "who":      {"type": "string"},
                    },
                    "required": ["question", "due", "who"],
                    "additionalProperties": False,
                }},
            },
            "required": ["dropped", "facts", "episode", "routine_episodes", "threads"],
            "additionalProperties": False,
        },
    },
}


def _today():
    return (datetime.now(_TZ) if _TZ else datetime.now()).date()


# ── the file ──────────────────────────────────────────────────────────────────

def _load():
    try:
        with open(MEMORY_PATH, encoding="utf-8") as f:
            mem = json.load(f)
        return {"facts": list(mem.get("facts", [])),
                "episodes": list(mem.get("episodes", [])),
                "threads": list(mem.get("threads", [])),
                "_wiped_at": mem.get("_wiped_at", 0),
                "_tidied": mem.get("_tidied", "")}
    except FileNotFoundError:
        return _empty()
    except (OSError, ValueError) as e:
        print(f"[memory] could not read {MEMORY_PATH} ({e}) — starting empty")
        return _empty()


def _empty(wiped_at=0):
    return {"facts": [], "episodes": [], "threads": [], "_wiped_at": wiped_at}


def _save(mem):
    # write-then-rename: a power cut mid-write must not eat the whole memory
    tmp = MEMORY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MEMORY_PATH)


# ── what the brain sees ───────────────────────────────────────────────────────

def _when(iso):
    try:
        days = (_today() - datetime.strptime(iso, "%Y-%m-%d").date()).days
    except ValueError:
        return iso
    if days <= 0:
        return "dzisiaj"
    if days == 1:
        return "wczoraj"
    if days < 7:
        return f"{days} dni temu"
    return iso


_DAY_Q = re.compile(r"\b(przedwczoraj|wczoraj|dzisiaj|dziś|dzis)\b", re.I)
_RECALL_Q = re.compile(r"\b(?:rozmawia\w*|robi\w*|mówi\w*|mowi\w*|gada\w*|grali\w*|"
                       r"bawi\w*|działo|dzialo|było|bylo|pamiętasz|pamietasz)\b", re.I)


def day_line(text):
    """"O czym rozmawialiśmy wczoraj?" → exactly that day's conversations from
    memory, worked out here (7 Oct: the model gave today's topics as
    yesterday's, twice, with the dates in front of it). '' otherwise."""
    m = _DAY_Q.search(text or "")
    if not m or not _RECALL_Q.search(text):
        return ""
    word = m.group(1).lower()
    back = {"przedwczoraj": 2, "wczoraj": 1}.get(word, 0)
    day = (_today() - timedelta(days=back)).isoformat()
    with _lock:
        eps = [e.get("text", "") for e in _load()["episodes"] if e.get("date") == day]
    if not eps:
        return (f"Asked about {word} ({day}): your memory has NO conversations from that "
                "day — say you don't remember it; don't use other days' lines.\n")
    return (f"Asked about {word} ({day}): your memory has from that day only: "
            + " ".join(eps) + " — answer from these, nothing from other days.\n")


def prompt_block():
    """Text for the system prompt, rebuilt on every request (so a fresh
    consolidation applies immediately). Empty when there is nothing yet."""
    if not MEMORY_ENABLED:
        return ""
    with _lock:
        mem = _load()
        # a new conversation = nothing said yet since the last consolidation
        thread = None
        if not _session:
            today = _today().isoformat()
            with state.lock:
                here = state.person[0] if state.person else None
            for t in mem["threads"]:
                # only to the person it is about: Andrzej's interview isn't a
                # question for Maja, and asking her would use up its turn (8 Oct)
                if t.get("who") and t["who"] != here:
                    continue
                if t.get("due", "") <= today and t.get("asked", 0) < MEMORY_THREAD_ASKS:
                    thread = t
                    break
            if thread is not None:
                thread["asked"] = thread.get("asked", 0) + 1
                _save(mem)
    facts    = mem["facts"]
    episodes = mem["episodes"][-MEMORY_PROMPT_EPISODES:]
    if not facts and not episodes and thread is None:
        # a brand-new Luna: get to know the person (their name only if her
        # camera doesn't know it — "Miło mi, Maju — a ty jak masz na imię?")
        with state.lock:
            known = bool(state.person)
        return ("\n--- YOUR MEMORY ---\nYou don't know anything about the person "
                "you talk to yet." + ("" if known else
                " At a natural moment (not in the middle of answering something "
                "else) ask their name, once.") + "\n--- END MEMORY ---")
    out = ["", "--- YOUR MEMORY (from earlier conversations) ---"]
    if facts:
        out.append("What you know about the people you talk to:")
        out += [f"- {f}" for f in facts]
    if episodes:
        out.append("Recent conversations (oldest first):")
        out += [f"- {_when(e.get('date', ''))} ({e.get('date', '')}): {e.get('text', '')}"
                for e in episodes]
    out += [
        "Use this memory the way a friend would: naturally, without reciting",
        "it or listing what you know. Compare dates with today: an event that",
        "was upcoming may have happened by now. If a recent conversation left",
        "something open (an event that has since happened, a worry, a plan),",
        "ask about it ONCE in your first or second reply of a new",
        "conversation — e.g. \"Jak poszła wczoraj rozmowa o pracę?\" — and",
        "don't ask about the same thing again after that. Never claim to",
        "remember anything that is not written here or in this conversation.",
        "The day of each conversation is written before it (dzisiaj / wczoraj /",
        "N dni temu): asked about a day, use only that day's lines — with none",
        "for that day, say you don't remember that day (7 Oct: \"o czym",
        "rozmawialiśmy wczoraj?\" got today's topics).",
        "--- END MEMORY ---",
    ]
    if thread is not None:
        out += [
            "THIS IS THE START OF A NEW CONVERSATION. Something is still open",
            f"from before — ask about it in THIS reply: \"{thread['question']}\"",
            "Answer what they said first if it needs an answer, then ask it in",
            "your own words, warmly and briefly.",
        ]
    return "\n".join(out)


def record(user_text, reply, local=False):
    """Called by brain after every answered utterance. local: a command
    handled without the model (radio, lamp, dice…) — kept as context, but a
    conversation of only those has nothing to remember."""
    if not MEMORY_ENABLED:
        return
    with _lock:
        _session.append((user_text, reply, local))


# ── consolidation: one model call per conversation ────────────────────────────

_INSTRUCTIONS = """You maintain the long-term memory of Luna, a small desktop
robot who talks with the people in one home. You get her current memory and
the conversation that just ended. Reply with JSON:

A FACT is something lasting about the people of this home that a friend
would still want to know in a month: names (who is who), work or school,
family, pets, health, likes and dislikes, plans and upcoming events with their
date, running jokes, anything someone explicitly asked Luna to remember.
NOT a fact:
- what Luna did when asked (radio, lamp, timers, the time, a photo, dice),
  and list contents — the lists are kept elsewhere
- what can be seen in the room or on the camera
- trivia or advice Luna explained (how to water a cactus), facts about Luna
- words that sound like a radio, TV or someone else's phone call in the
  background rather than said to Luna (an advert, a news item, a stranger)
- passing states ("is tired", "went shopping") unless they matter later
- details of a discussion: at most TWO facts per topic — ten facts about
  one work project become one ("Andrzej pracuje nad systemem do certyfikatów
  i transakcji")

"dropped": FIRST go through CURRENT FACTS one by one and list here every one
that is NOT a fact by the rules above, was corrected, was asked to be
forgotten, or is merged into another — each with a 2-4 word reason
("trivia", "room view", "merged", "radio"). Be strict: an old fact that
breaks the rules must go even though it is already stored.

"facts": the COMPLETE updated list: the old facts that were not dropped
(merged and updated where the conversation changed them), plus what this
conversation adds. Short sentences in Polish, most important first, at most
{max_facts}. Once an event's date has passed, rewrite it in the past tense or
drop it. Never store passwords, PINs, codes, card or account numbers, or
addresses. Only facts about the PEOPLE and the HOME — never general knowledge,
dates of public events or what Luna answered (8 Oct: her own wrong answer
"zmiana czasu z 25 na 26 października" was kept as a fact and repeated).
Read carefully who is who: "Maja w sobotę ma urodziny koleżanki"
means a friend's birthday party Maja goes to, not Maja's birthday.
A line starting "[Kasia]" was said by Kasia (Luna knows her face): write
facts about that person with their name ("Kasia lubi koty"). "[Kasia, with Ola]"
means Ola was in front of Luna too and may have said it: a game or activity
then belongs to both ("Kasia i Ola rozwiązały zagadki"), and a personal fact
only to whoever it clearly is about. An untagged line
is from someone Luna didn't recognise: write "ktoś w domu", never
"użytkownik". Old facts saying "Użytkownik" may be rewritten with the right
name only when the facts make it certain who it was.

"threads": the COMPLETE updated list of open follow-ups — things whose
outcome Luna does not know yet and a friend would ask about later: an
interview, exam, doctor's visit, trip, a worry, something they were going to
try. "question" is a short, natural Polish question Luna could ask ("Jak
poszła rozmowa o pracę w Nokii?"); "due" is the date (YYYY-MM-DD) from which
asking makes sense — the day after the event, or today if it is ongoing;
"who" is the name of the person to ask (from the "[Name]" tags), or "" when it
is unknown. Keep
the open ones from CURRENT THREADS, drop those this conversation answered or
made pointless, at most {max_threads}.

"episode": one or two Polish sentences about THIS conversation that would be
worth coming back to later — something the person is going through, planning
or looking forward to (e.g. "Andrzej ma jutro rozmowę o pracę i się
stresuje."). Use an empty string when the conversation was routine: commands
(radio, lamp, timers, lists, the time, dice, status), a quick fact, small
talk, a greeting and goodbye.

DATES: this memory is read on later days, so NEVER write relative time words
("jutro", "dzisiaj", "wczoraj", "w przyszły piątek", "za tydzień") in facts or
the episode. Work out the calendar date from today's date and write it, e.g.
"ma rozmowę o pracę 25 września 2026".

Today's date: {today} ({weekday}). The next days: {week} — use these for
"w piątek", "jutro", "w sobotę" (a weekday is the next one of these)."""


_TIDY = """

TODAY'S TIDY-UP (once a day): besides this conversation, rewrite CURRENT FACTS
into a short, clean list. Every group of facts on one topic becomes one or two
facts — list each merged one in "dropped" with the reason "merged". Write
"użytkownik" as the person's name only where the facts make it certain.
Also copy into "routine_episodes", word for word, every one of the RECENT
EPISODES below that was routine (a command, the time, the radio, a lamp, a
quick fact, a greeting) — they will be removed. On other days that list is
empty."""


_WEEKDAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek",
             "sobota", "niedziela"]


def _transcript(session):
    out = []
    for u, r, local in session:
        m = re.match(r"\[([^\]]+)\]\s*(.*)", u, re.S)
        who, u = (m.group(1), m.group(2)) if m else ("Ktoś", u)
        out.append(f"[{who}] {u}\nLuna{' (command)' if local else ''}: {r}")
    return "\n".join(out)


def consolidate():
    """Fold the finished conversation into memory.json. Runs in a thread."""
    with _lock:
        session = list(_session)
        _session.clear()
    if not session or _client is None:
        return
    if all(local for _, _, local in session):
        print(f"[memory] {len(session)} command(s) only — nothing to remember", flush=True)
        return
    with _lock:
        mem = _load()
    current = "\n".join(f"- {f}" for f in mem["facts"]) or "(nothing yet)"
    threads = "\n".join(f"- {t.get('question', '')} (due {t.get('due', '')}, "
                        f"asked {t.get('asked', 0)}x)" for t in mem["threads"]) or "(none)"
    t0 = time.time()
    tidy = mem.get("_tidied") != _today().isoformat()     # once a day, the better model
    try:
        r = _client.chat.completions.create(
            model=MEMORY_TIDY_MODEL if tidy else MEMORY_MODEL,
            messages=[
                {"role": "system", "content": _INSTRUCTIONS.format(
                    max_facts=MEMORY_MAX_FACTS, max_threads=MEMORY_MAX_THREADS,
                    today=_today().isoformat(),
                    weekday=_WEEKDAYS[_today().weekday()],
                    # (8 Oct: "w piątek sprawdzian" said on a Thursday got the
                    # follow-up on Sunday — weekday sums are not the model's)
                    week=", ".join(f"{_WEEKDAYS[d.weekday()]} {d.isoformat()}" for d in
                                   (_today() + timedelta(days=i) for i in range(1, 8))))},
                {"role": "user", "content":
                    f"CURRENT FACTS:\n{current}\n\nCURRENT THREADS:\n{threads}"
                    f"\n\nCONVERSATION:\n{_transcript(session)}"
                    + (_TIDY + "\n\nRECENT EPISODES:\n" + "\n".join(
                        f"- {e.get('text', '')}" for e in mem["episodes"])
                       if tidy else "")},
            ],
            temperature=0.2,
            max_tokens=3000,                 # the COMPLETE fact list comes back
            response_format=_SCHEMA,
        )
        if r.choices[0].finish_reason == "length":
            raise ValueError("reply cut off at max_tokens")
        data = json.loads(r.choices[0].message.content)
    except Exception as e:
        print(f"[memory] consolidation failed ({e}) — keeping it for next time")
        with _lock:
            _session[:0] = session           # retry with the next conversation
            del _session[:-_SESSION_MAX]     # …but never a growing pile
        return
    if not facts_ok(data.get("facts"), mem["facts"], data.get("dropped")):
        print("[memory] the new fact list lost most old facts — not saved", flush=True)
        return

    facts = [str(f).strip() for f in data.get("facts", []) if str(f).strip()]
    facts = keep_old_facts(facts, mem["facts"], tidy)
    for d in (data.get("dropped", []) if tidy else [])[:20]:
        print(f"[memory] dropped: {d}", flush=True)
    facts = facts[:MEMORY_MAX_FACTS]
    if tidy and len(facts) > MERGE_ABOVE:
        facts = merge_topics(facts)
    with _lock:
        facts += [f for t, f in _added if t >= t0 and f not in facts]
    episode = str(data.get("episode", "")).strip()
    with _lock:
        mem = _load()                        # re-read: a wipe may have happened
        if mem.get("_wiped_at", 0) > t0:
            return
        mem["facts"] = facts
        if tidy:
            mem["_tidied"] = _today().isoformat()
        old = {t.get("question"): t.get("asked", 0) for t in mem["threads"]}
        mem["threads"] = [
            {"question": str(t["question"]).strip(), "due": str(t["due"]).strip(),
             "who": str(t.get("who", "")).strip(),
             "asked": old.get(str(t["question"]).strip(), 0)}
            for t in data.get("threads", []) if str(t.get("question", "")).strip()
            # asked as often as it may be: done with, not carried on forever
            and old.get(str(t["question"]).strip(), 0) < MEMORY_THREAD_ASKS
        ][:MEMORY_MAX_THREADS]
        routine = {str(e).strip(" -") for e in data.get("routine_episodes", [])} if tidy else set()
        if routine:
            before = len(mem["episodes"])
            mem["episodes"] = [e for e in mem["episodes"] if e.get("text") not in routine]
            print(f"[memory] {before - len(mem['episodes'])} routine episode(s) let go",
                  flush=True)
        if episode:
            mem["episodes"].append({"date": _today().isoformat(), "text": episode})
            mem["episodes"] = mem["episodes"][-MEMORY_MAX_EPISODES:]
        _save(mem)
    print(f"[memory] saved ({time.time() - t0:.1f}s{', tidied' if tidy else ''}): "
          f"{len(facts)} facts, "
          f"{len(mem['threads'])} open threads"
          + (f", episode: {episode}" if episode else ", no episode"), flush=True)


MERGE_ABOVE = 10
_MERGE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {"name": "merged", "strict": True, "schema": {
        "type": "object",
        "properties": {"facts": {"type": "array", "items": {"type": "string"}}},
        "required": ["facts"], "additionalProperties": False}},
}


def merge_topics(facts):
    """The daily tidy's second step, one job only: facts on the same topic
    (ten details of one work project) become one or two. The list as it was
    if anything looks wrong."""
    if _client is None:
        return facts
    try:
        r = _client.chat.completions.create(
            model=MEMORY_TIDY_MODEL, temperature=0.1, max_tokens=1500,
            response_format=_MERGE_SCHEMA,
            messages=[{"role": "user", "content":
                       "These are the lasting facts a home robot remembers about a "
                       "family. Group them by topic and rewrite each group as ONE short "
                       "Polish sentence (two only if the topic really needs it): keep "
                       "names, dates and anything specific that matters; drop chatty "
                       "details. Facts that stand alone stay as they are. Return JSON "
                       "{\"facts\": [...]}, most important first.\n\n"
                       + "\n".join(f"- {f}" for f in facts)}])
        new = [str(f).strip() for f in json.loads(r.choices[0].message.content)["facts"]
               if str(f).strip()]
    except Exception as e:
        print(f"[memory] merging failed ({e}) — kept as is", flush=True)
        return facts
    if not new or len(new) < max(3, len(facts) // 5) or len(new) > len(facts):
        print(f"[memory] merge gave {len(new)} of {len(facts)} — kept as is", flush=True)
        return facts
    print(f"[memory] merged by topic: {len(facts)} → {len(new)} facts", flush=True)
    return new


TIDY_MAX_DROP = 0.4        # the daily tidy may let go of at most 40 % of the facts


def keep_old_facts(new, old, tidy):
    """Only the daily tidy may make the memory smaller. An ordinary
    consolidation (the cheaper model) kept "weeding" a few facts each time and
    on 5 Oct wore 17 facts down to 1 ("lubi żarty", "mówi po hiszpańsku"…):
    now every old fact it left out is put back (a changed one stays changed
    only if the new list still mentions its subject). The tidy keeps at least
    60 % (merged facts count by their words)."""
    if not tidy:
        newstems = [_stems(f) for f in new]
        back = [f for f in old if f not in new and not any(
            len(_stems(f) & s) >= max(2, len(_stems(f)) // 2) for s in newstems)]
        if back:
            print(f"[memory] kept {len(back)} old fact(s) the update left out", flush=True)
        return back + new
    covered = sum(1 for f in old if f in new or any(
        len(_stems(f) & _stems(n)) >= 2 for n in new))
    if old and covered < (1 - TIDY_MAX_DROP) * len(old):
        print(f"[memory] the tidy would keep {covered} of {len(old)} — too few, kept as it was",
              flush=True)
        return list(old)
    return new


def facts_ok(new, old, dropped=()):
    """A sanity check on the model's COMPLETE list: it may drop junk and merge,
    but only when it says so — a reply that silently lost most of the memory
    is a mistake, not a cleanup."""
    if not isinstance(new, list):
        return False
    if len(old) < 6 or len(new) >= len(old) // 3:
        return True
    return len(new) + len(dropped or ()) >= 0.8 * len(old)   # every loss accounted for


# ── "Luna, zapomnij wszystko" ─────────────────────────────────────────────────

_FIRST_PERSON = {"jestem", "mam", "mój", "moja", "moje", "mojego", "mojej", "moich",
                 "mnie", "mi", "lubię", "lubie", "mieszkam", "pracuję", "pracuje",
                 "muszę", "musze", "chcę", "chce", "będę", "bede", "my", "nasz",
                 "nasza", "nasze", "naszego", "naszej", "mamy", "jesteśmy"}
_RELATIVE = {"jutro", "pojutrze", "dziś", "dzisiaj", "wczoraj", "przedwczoraj",
             "przyszły", "przyszłym", "przyszłą", "przyszłej", "tydzień", "tygodniu",
             "weekend", "weekendzie", "miesiąc", "miesiącu", "wieczorem", "rano"}


_STOP = {"jest", "mają", "mamy", "masz", "który", "która", "które", "bardzo", "tego",
         "takie", "także", "oraz", "bardziej", "mnie", "moja", "moje", "mój", "mojego"}


def _stems(text):
    return {w[:5] for w in re.findall(r"\w+", text.lower()) if len(w) >= 4 and w not in _STOP}


def facts_about(name):
    """The facts that mention this person in any case form ("Mai", "Maję")."""
    import faces
    forms = faces.forms(name)
    with _lock:
        facts = _load()["facts"]
    return [f for f in facts if forms & set(re.findall(r"\w+", f.lower()))]


_WHERE_THING = re.compile(
    r"\bgdzie\s+(?:jest|są|sa|leży|lezy|leżą|leza|położył\w*|polozyl\w*|zostawił\w*|"
    r"zostawil\w*|schował\w*|schowal\w*|odłożył\w*|odlozyl\w*|mam|mamy)\s+"
    r"(?:mój|moj|moja|moje|moi|nasz\w*|te|ten|ta)?\s*(.+?)[?.!]*$", re.I)
_PLACE = re.compile(r"\b(?:w|we|na|pod|przy|obok|za|u|nad|między)\s+\w+", re.I)


def where_is_thing(text):
    """"Gdzie są klucze?" → "Zapisałam: Klucze są w szufladzie." from what she
    was told to remember; None when no remembered fact says where it is."""
    m = _WHERE_THING.search(text)
    if not m:
        return None
    want = _stems(m.group(1))
    if not want or len(m.group(1).split()) > 4:
        return None
    with _lock:
        facts = _load()["facts"]
    for f in reversed(facts):                     # the newest note wins
        body = re.sub(r"^(?:\w+ mówi: |Powiedziano mi: )?[„\"]?", "", f)
        head = _stems(" ".join(body.split()[:3]))
        if want & head and _PLACE.search(body):
            return f"Zapisałam: {body.strip('„”\" .')}."
    return None


def forget_fact(what, among=None):
    """"zapomnij, że mam chomika" → the fact removed (best word match), or None.
    among: only these facts may go (a child: the ones about herself)."""
    want = _stems(what)
    if not want:
        return None
    with _lock:
        mem = _load()
        best, score = None, 0.0
        for f in mem["facts"]:
            if among is not None and f not in among:
                continue
            s = len(want & _stems(f)) / len(want)
            if s > score:
                best, score = f, s
        if best is None or score < 0.5:
            return None
        mem["facts"].remove(best)
        _save(mem)
    print(f"[memory] forgot on request: {best}", flush=True)
    return best


def add_fact(fact):
    """"Zapamiętaj, że klucze są w szufladzie" — written at once, not at the
    end of the conversation, and never judged as trivia."""
    fact = fact.strip().rstrip(".")
    words = set(re.findall(r"\w+", fact.lower()))
    if words & _FIRST_PERSON or any(w.endswith(("łem", "łam")) for w in words):
        with state.lock:                           # "jestem uczulony…" — not Luna
            who = state.person[0] if state.person else None
        fact = f"{who} mówi: „{fact}”" if who else f"Powiedziano mi: „{fact}”"
    else:
        fact = fact[0].upper() + fact[1:]
    if words & _RELATIVE:                          # "jutro" must keep its day
        fact += f" (zanotowane {_today().strftime('%d.%m.%Y')})"
    fact += "."
    with _lock:
        mem = _load()
        if fact.lower() in (f.lower() for f in mem["facts"]):
            return fact
        mem["facts"].append(fact)
        if len(mem["facts"]) > MEMORY_MAX_FACTS:
            mem["facts"] = mem["facts"][-MEMORY_MAX_FACTS:]
        _save(mem)
        _added.append((time.time(), fact))
        del _added[:-20]
    print(f"[memory] noted: {fact}", flush=True)
    return fact


_confirm_until = 0.0              # "na pewno?" asked — the answer is awaited till then
_CONFIRM_SECS  = 25


def _child_in_view():
    try:
        import faces
        from shared_state import state
        with state.lock:
            who = state.person[0] if state.person else None
        return bool(who) and "dziecko" in faces.notes().get(who, "").lower()
    except Exception:
        return False


def check_forget(text, now=None):
    """The reply when the utterance is about wiping her memory, else None.

    Wiping is asked back first ("Na pewno…?"), and only a "tak" within
    _CONFIRM_SECS does it: "nie zapomnij o mnie" or a sentence from the radio
    must never erase the family's memories. A child can't wipe it."""
    global _confirm_until
    now = time.time() if now is None else now
    low = re.sub(r"[^\w\s]", " ", text.lower())
    words = low.split()
    if _confirm_until and now < _confirm_until:
        _confirm_until = 0.0
        if re.search(r"\b(tak|zapomnij|potwierdzam|na pewno|yes)\b", low) and \
                not re.search(r"\b(nie|jednak|stop)\b", low):
            with _lock:
                _session.clear()
                _save(_empty(wiped_at=now))
            try:                               # the recent conversation goes too
                import sys
                os.remove(os.path.join(os.path.dirname(MEMORY_PATH), "history.json"))
                if "brain" in sys.modules:
                    sys.modules["brain"]._history.clear()
            except (OSError, AttributeError):
                pass
            print("[memory] wiped on request (confirmed)", flush=True)
            return FORGET_REPLY
        if len(words) <= 4 and re.search(r"\b(nie|jednak|anuluj|stop)\b", low):
            return "Dobrze, niczego nie zapominam."
        # anything else: the question lapses and the sentence goes on as usual
    _confirm_until = 0.0
    if not any(p in low for p in FORGET_PHRASES):
        return None
    if re.search(r"\bnie\s+(zapomnij|zapominaj|wymaż|wymaz|czyść|czysc)", low) or \
            len(words) > 8 or "?" in text:
        return None                    # "nie zapomnij o mnie", a story, a question
    if _child_in_view():
        return "Tego może mnie poprosić tylko dorosły."
    _confirm_until = now + _CONFIRM_SECS
    return ("Na pewno mam zapomnieć wszystko, co o was wiem? "
            "Powiedz: tak, zapomnij — albo nie.")


# ── watcher: consolidate when a conversation window closes ────────────────────

def _watch():
    was_active = False
    while True:
        try:
            with state.lock:
                active = state.conversation_active
            with _lock:
                pending = len(_session)
            # the conversation window closed, or one very long conversation
            if (was_active and not active and pending) or pending >= 40:
                threading.Thread(target=consolidate, daemon=True,
                                 name="memory-save").start()
            was_active = active
        except Exception as e:
            print(f"[memory] watcher error (recovering): {e}")
        time.sleep(1.0)


def start_memory():
    if not MEMORY_ENABLED:
        print("[memory] off (LUNA_MEMORY=0)")
        return
    mem = _load()
    print(f"[memory] {len(mem['facts'])} facts, {len(mem['episodes'])} episodes "
          f"in {MEMORY_PATH}")
    threading.Thread(target=_watch, daemon=True, name="memory").start()
