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
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from shared_state import state
from config import (
    MEMORY_ENABLED,
    MEMORY_PATH,
    MEMORY_MAX_FACTS,
    MEMORY_MAX_EPISODES,
    MEMORY_PROMPT_EPISODES,
    MEMORY_MODEL,
    MEMORY_MAX_THREADS,
    MEMORY_THREAD_ASKS,
    FORGET_PHRASES,
    OPENAI_API_KEY,
    OPENAI_TIMEOUT,
    LUNA_TIMEZONE,
)

try:
    _TZ = ZoneInfo(LUNA_TIMEZONE)
except Exception:
    _TZ = None

_lock    = threading.Lock()      # guards the file and _session
_session = []                    # [(user_text, luna_reply)] not yet consolidated
_client  = (OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT, max_retries=1)
            if (OPENAI_API_KEY and MEMORY_ENABLED) else None)

_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "luna_memory",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "facts":   {"type": "array", "items": {"type": "string"}},
                "episode": {"type": "string"},
                "threads": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "due":      {"type": "string"},
                    },
                    "required": ["question", "due"],
                    "additionalProperties": False,
                }},
            },
            "required": ["facts", "episode", "threads"],
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
                "_wiped_at": mem.get("_wiped_at", 0)}
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
            for t in mem["threads"]:
                if t.get("due", "") <= today and t.get("asked", 0) < MEMORY_THREAD_ASKS:
                    thread = t
                    break
            if thread is not None:
                thread["asked"] = thread.get("asked", 0) + 1
                _save(mem)
    facts    = mem["facts"]
    episodes = mem["episodes"][-MEMORY_PROMPT_EPISODES:]
    if not facts and not episodes and thread is None:
        return ""
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


def record(user_text, reply):
    """Called by brain after every answered utterance."""
    if not MEMORY_ENABLED:
        return
    with _lock:
        _session.append((user_text, reply))


# ── consolidation: one model call per conversation ────────────────────────────

_INSTRUCTIONS = """You maintain the long-term memory of Luna, a small desktop
robot who talks with the people in one home. You get her current memory and
the conversation that just ended. Reply with JSON:

"facts": the COMPLETE updated list of lasting facts. Keep every old fact that
is still true, merge duplicates, update facts that changed, and drop facts the
user corrected or asked Luna to forget. Add what is worth knowing next time:
names (who is who), work or school, family, pets, likes and dislikes, plans
and upcoming events, running jokes, anything the user explicitly asked Luna to
remember. Short sentences in Polish, most important first, at most {max_facts}.
Once an event's date has passed, rewrite it in the past tense or drop it.
Never store passwords, PINs, codes, card or account numbers, or addresses.
Don't store facts about Luna herself or trivia she explained.

"threads": the COMPLETE updated list of open follow-ups — things whose
outcome Luna does not know yet and a friend would ask about later: an
interview, exam, doctor's visit, trip, a worry, something they were going to
try. "question" is a short, natural Polish question Luna could ask ("Jak
poszła rozmowa o pracę w Nokii?"); "due" is the date (YYYY-MM-DD) from which
asking makes sense — the day after the event, or today if it is ongoing. Keep
the open ones from CURRENT THREADS, drop those this conversation answered or
made pointless, at most {max_threads}.

"episode": one or two Polish sentences about THIS conversation that would be
worth coming back to later — something the person is going through, planning
or looking forward to (e.g. "Andrzej ma jutro rozmowę o pracę i się
stresuje."). Use an empty string when the conversation was routine (the time,
a quick fact, small talk).

DATES: this memory is read on later days, so NEVER write relative time words
("jutro", "dzisiaj", "wczoraj", "w przyszły piątek", "za tydzień") in facts or
the episode. Work out the calendar date from today's date and write it, e.g.
"ma rozmowę o pracę 25 września 2026".

Today's date: {today} ({weekday})."""


_WEEKDAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek",
             "sobota", "niedziela"]


def _transcript(session):
    return "\n".join(f"Użytkownik: {u}\nLuna: {r}" for u, r in session)


def consolidate():
    """Fold the finished conversation into memory.json. Runs in a thread."""
    with _lock:
        session = list(_session)
        _session.clear()
    if not session or _client is None:
        return
    with _lock:
        mem = _load()
    current = "\n".join(f"- {f}" for f in mem["facts"]) or "(nothing yet)"
    threads = "\n".join(f"- {t.get('question', '')} (due {t.get('due', '')}, "
                        f"asked {t.get('asked', 0)}x)" for t in mem["threads"]) or "(none)"
    t0 = time.time()
    try:
        r = _client.chat.completions.create(
            model=MEMORY_MODEL,
            messages=[
                {"role": "system", "content": _INSTRUCTIONS.format(
                    max_facts=MEMORY_MAX_FACTS, max_threads=MEMORY_MAX_THREADS,
                    today=_today().isoformat(),
                    weekday=_WEEKDAYS[_today().weekday()])},
                {"role": "user", "content":
                    f"CURRENT FACTS:\n{current}\n\nCURRENT THREADS:\n{threads}"
                    f"\n\nCONVERSATION:\n{_transcript(session)}"},
            ],
            temperature=0.2,
            max_tokens=900,
            response_format=_SCHEMA,
        )
        data = json.loads(r.choices[0].message.content)
    except Exception as e:
        print(f"[memory] consolidation failed ({e}) — keeping it for next time")
        with _lock:
            _session[:0] = session           # retry with the next conversation
        return

    facts = [str(f).strip() for f in data.get("facts", []) if str(f).strip()]
    facts = facts[:MEMORY_MAX_FACTS]
    episode = str(data.get("episode", "")).strip()
    with _lock:
        mem = _load()                        # re-read: a wipe may have happened
        if mem.get("_wiped_at", 0) > t0:
            return
        mem["facts"] = facts
        old = {t.get("question"): t.get("asked", 0) for t in mem["threads"]}
        mem["threads"] = [
            {"question": str(t["question"]).strip(), "due": str(t["due"]).strip(),
             "asked": old.get(str(t["question"]).strip(), 0)}
            for t in data.get("threads", []) if str(t.get("question", "")).strip()
        ][:MEMORY_MAX_THREADS]
        if episode:
            mem["episodes"].append({"date": _today().isoformat(), "text": episode})
            mem["episodes"] = mem["episodes"][-MEMORY_MAX_EPISODES:]
        _save(mem)
    print(f"[memory] saved ({time.time() - t0:.1f}s): {len(facts)} facts, "
          f"{len(mem['threads'])} open threads"
          + (f", episode: {episode}" if episode else ", no episode"), flush=True)


# ── "Luna, zapomnij wszystko" ─────────────────────────────────────────────────

def check_forget(text):
    """True when the utterance asks her to wipe her memory (and it was)."""
    low = text.lower()
    if not any(p in low for p in FORGET_PHRASES):
        return False
    with _lock:
        _session.clear()
        _save(_empty(wiped_at=time.time()))
    print("[memory] wiped on request", flush=True)
    return True


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
