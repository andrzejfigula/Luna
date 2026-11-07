"""
phone.py — a phone paired over Bluetooth: its SMS read, shown and sent from here.

  "sparuj telefon", "odłącz telefon", "czy telefon jest połączony?"
  "pokaż SMS-y", "przeczytaj SMS-y", "przeczytaj SMS od Kasi", "ile mam SMS-ów?",
  "co napisała Kasia?"
  "wyślij SMS do Kasi, że będę o piątej", "napisz SMS", then "odpisz, że dobrze"

Sent only after she reads it back and hears "tak" (or ✕ / Anuluj): one SMS costs
money and can't be taken back. phone_link.py talks to BlueZ; ui_phone.py draws.

Private: an SMS is never logged, written to disk or given to the model (a stranger
writes it: it must not become her instructions). A guest, a stranger or a child
gets neither the list nor the sending, unless the phone is theirs; a new SMS shows
only "Nowy SMS" then. Numbers and address book stay in memory; data/phone.json has
only which phone it is and whose.

The list is polled (the listing doesn't mark anything read); a message's whole text
is downloaded only when someone asks for it, because that counts as reading it.
Nothing runs until a phone is paired.
"""

import json
import os
import queue
import re
import threading
import time

import contacts
import phone_link
import settings
from config import DATA_DIR
from shared_state import keep_private, state

FILE = os.path.join(DATA_DIR, "phone.json")
PAGE_SECS = 60                # untouched this long, a page closes
EDIT_SECS = 180               # …longer while typing
PAIR_SECS = 180               # visible to phones this long
BANNER_SECS = 10
POLL_SECS = 30
RETRY_SECS, RETRY_MAX = 60, 300       # paging an absent phone can stutter her speaker: not often
DRAFT_SECS = 90
REPLY_SECS = 600              # "odpisz" means the last one read, this long after
READ_MAX = 3                  # read out at one go
SAY_MAX = 400                 # a longer one: the rest on the screen
BODY_MAX = 480
PAGE_ROWS = 5

_ADULTS = "Telefon jest prywatny. Poproś dorosłego z rodziny."
_NONE = "Nie mam sparowanego telefonu. Powiedz: sparuj telefon."
_NO_OBEX = ("Do SMS-ów brakuje mi pakietu bluez-obexd. Trzeba go zainstalować na Raspberry Pi.")
_NO_OBEX_PAIR = "Zanim sparuję telefon, trzeba zainstalować na Raspberry Pi pakiet bluez-obexd."
_NO_DBUS = "Do telefonu brakuje mi obsługi Bluetooth. Trzeba doinstalować python3-dbus."
_AWAY = "Telefon jest poza zasięgiem albo nie zezwolił na dostęp do wiadomości."
_HINT_BODY = "Powiedz po prostu, co mam napisać, albo: anuluj."
_HINT_WHO = "Powiedz imię z telefonu albo numer, cyfra po cyfrze. Albo: anuluj."

_link = phone_link            # (tests swap it)
_lock = threading.RLock()
_cfg = False                  # False: not read yet
_status = "off"               # off, connecting, on, no_obex, no_dbus
_inbox = []                   # newest first: {"id", "path", "who", "number", "text", "whole", "when", "read"}
_book = {}                    # name → number (from the phone; not kept on disk)
_session = None
_next_poll = 0.0
_fails = 0
_first_poll = True
_want_book = False
_jobs = queue.Queue()
_thread = None
_pair = None                  # {"until", "known", "addr", "name", "code", "answer", "speak"}
_draft = None                 # {"step": who/body/confirm/typing, "to", "number", "text", "until", "tries"}
_last_read = None             # (message id, when)
_say_fn = None                # (tests)


def _say(text):
    fn = _say_fn
    if fn is None:
        from text_to_speech import speak as fn
    fn(text)


# ── which phone ───────────────────────────────────────────────────────

def config():
    """{"addr", "name", "owner"} of the paired phone, or None."""
    global _cfg
    with _lock:
        if _cfg is False:
            try:
                with open(FILE, encoding="utf-8") as f:
                    _cfg = json.load(f)
            except (OSError, ValueError):
                _cfg = None
        return _cfg


def _save_config(cfg):
    global _cfg
    with _lock:
        _cfg = cfg
        if cfg is None:
            try:
                os.remove(FILE)
            except OSError:
                pass
            return
        os.makedirs(os.path.dirname(FILE), exist_ok=True)
        tmp = FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        os.replace(tmp, FILE)


def _denied():
    """None if whoever is here may see the messages and send, else what to say."""
    cfg = config()
    return _ADULTS if contacts.may_edit((cfg or {}).get("owner") or "") else None


def status():
    with _lock:
        return _status


def _unavailable():
    """Why nothing can be read or sent right now (what to say), or None."""
    global _next_poll
    if not config():
        return _NONE
    said = {"no_obex": _NO_OBEX, "no_dbus": _NO_DBUS, "off": _AWAY}.get(status())
    if said == _AWAY:       # someone's asking (perhaps they've just tapped Allow): try now
        _next_poll = 0.0
    return said


# ── the worker: everything that touches Bluetooth ─────────────────────

def _ensure_thread():
    global _thread
    with _lock:
        if _thread is None:
            _thread = threading.Thread(target=_worker, daemon=True, name="phone")
            _thread.start()


def start():
    """At start: nothing unless a phone is paired."""
    if config():
        _jobs.put(_register)
        _ensure_thread()


def _worker():
    while True:
        try:
            job = _jobs.get(timeout=1.0)
        except queue.Empty:
            job = None
        try:
            if job:
                job()
            _step(time.time())
        except Exception as e:
            print(f"[phone] {type(e).__name__}: {e}", flush=True)


def _step(now):
    _tick_pair(now)
    if config() and now >= _next_poll:
        _poll(now)


def _register():
    global _status
    try:
        _link.register_agent(_on_confirm, _on_cancel, _is_phone)
    except phone_link.NoDbus:
        _status = "no_dbus"
    except phone_link.LinkError as e:
        print(f"[phone] the agent: {e}", flush=True)


def _drop_session():
    global _session
    _link.close(_session)
    _session = None


def _lost(now):
    global _status, _next_poll, _fails
    _drop_session()
    _fails += 1
    _status = "off"
    _next_poll = now + min(RETRY_SECS * _fails, RETRY_MAX)


def _poll(now):
    global _status, _session, _next_poll, _fails, _first_poll, _want_book, _book_fails, _book_next
    cfg = config()
    _next_poll = now + POLL_SECS        # (whatever happens below, never a tight loop)
    try:
        if not _session:
            if _status != "on":
                _status = "connecting"
            _session = _link.open_map(cfg["addr"])
            _want_book, _book_fails, _book_next = True, 0, 0.0
            print("[phone] connected", flush=True)
        rows = _link.list_messages(_session)
        if _status != "on":
            print(f"[phone] {len(rows)} messages on the list", flush=True)
        _status, _fails = "on", 0
        _merge(rows, now)
        if _want_book and now >= _book_next:
            _want_book = False
            if _load_book(cfg["addr"], now):
                _merge(rows, now)       # (names from the book)
    except phone_link.NoObex:      # (no Bluetooth involved, so soon: he may have just installed it)
        _status, _next_poll = "no_obex", now + POLL_SECS
    except phone_link.NoDbus:
        _status, _next_poll = "no_dbus", now + RETRY_MAX
    except phone_link.LinkError as e:
        print(f"[phone] no link: {e}", flush=True)     # (error names only, no message text)
        _lost(now)
    except Exception as e:              # a bug: the name and line, a message's text may be in `e`
        line = e.__traceback__.tb_next.tb_lineno if e.__traceback__.tb_next else 0
        print(f"[phone] poll failed: {type(e).__name__} (line {line})", flush=True)
        _lost(now)


_book_fails, _book_next = 0, 0.0
BOOK_TRIES, BOOK_RETRY_SECS = 3, 600     # (the phone may be waiting for an Allow: not every poll)


def _load_book(addr, now=None):
    """True once the book is in; if not, it's tried again a few times, far apart."""
    global _book, _book_fails, _book_next, _want_book
    try:
        people = _link.pull_book(addr)
    except (phone_link.LinkError, phone_link.NoObex) as e:
        print(f"[phone] no address book: {e}", flush=True)
        _book_fails += 1
        if _book_fails < BOOK_TRIES:
            _want_book, _book_next = True, (now or time.time()) + BOOK_RETRY_SECS
        return False
    with _lock:
        _book = dict(people)
    print(f"[phone] address book: {len(people)} entries", flush=True)
    return True


def _key(number):
    """A number to compare by: its last nine digits."""
    return re.sub(r"\D", "", number or "")[-9:]


def _name_of(number, given):
    """Who it's from: the address book first, then what the phone said, else the number."""
    key = _key(number)
    if key:
        with _lock:
            hit = next((n for n, num in _book.items() if _key(num) == key), None)
        if hit:
            return hit
        hit = next((n for n, num in _card_numbers().items() if _key(num) == key), None)
        if hit:
            return hit
    return (given or "").strip() or number or "nieznany numer"


def _card_numbers():
    """{name: number} from the contact cards (contacts.py)."""
    import faces
    out = {}
    for name in faces.family() + faces.guests():
        num = (contacts.card(name) or {}).get("phone")
        if num:
            out[name] = num
    return out


def _tidy(s):
    """What the font and her voice can do: no emoji, no control characters."""
    return "".join(c for c in (s or "") if ord(c) < 0x10000 and (c.isprintable() or c == "\n")).strip()


def _when(stamp, now):
    try:
        return time.mktime(time.strptime(stamp[:15], "%Y%m%dT%H%M%S"))
    except (TypeError, ValueError):
        return now


def _merge(rows, now):
    """The phone's list into ours; a new unread one is announced on the screen."""
    global _inbox, _first_poll
    new, seen = [], []
    with _lock:
        known = {m["id"]: m for m in _inbox}
        fresh = []
        for r in rows:
            if not str(r.get("Type", "sms")).lower().startswith(("sms", "mms")):
                continue
            mid = r["path"].rsplit("message", 1)[-1]
            old = known.get(mid)
            subject = _tidy(r.get("Subject"))
            if old:
                old.update(path=r["path"], read=old["read"] or bool(r.get("Read")),
                           who=_tidy(_name_of(old["number"], r.get("Sender"))))
                fresh.append(old)
                continue
            number = str(r.get("SenderAddress") or "")
            m = {"id": mid, "path": r["path"], "number": number,
                 "who": _tidy(_name_of(number, r.get("Sender"))), "text": subject,
                 "whole": False,        # (the list has only its start, on some phones a short one)
                 "when": _when(r.get("Timestamp"), now), "read": bool(r.get("Read"))}
            fresh.append(m)
            if not _first_poll:
                (new if not m["read"] else seen).append(m)
        fresh.sort(key=lambda m: -m["when"])
        _inbox = fresh
        _first_poll = False
    _publish()
    for m in new:
        print("[phone] a new SMS", flush=True)
    for m in seen:               # (no icon for these: the phone says it's been read)
        print("[phone] a new SMS, already read on the phone", flush=True)
    if new:
        _banner(new[0], now)


def _publish():
    with _lock:
        n = sum(1 for m in _inbox if not m["read"])
    with state.lock:
        state.phone_unread = n


def _banner(msg, now):
    """A new SMS, for a moment, unless she's busy (then the status bar has it)."""
    import screens
    with state.lock:
        busy = (state.overlay or state.sleep_mode or state.speaking or state.conversation_active
                or now < state.focus_until or now < state.proactive_muted_until)
    if busy:
        return
    # (only to someone she knows may see it: nobody seen isn't enough, the room may fill)
    private = (contacts.viewer() is None or _denied() is not None
               or settings.get("phone_preview", True) is False)
    screens._show("phone", BANNER_SECS, {"view": "new", "id": msg["id"], "private": private})


def _run(fn, timeout=30.0):
    """A job on the worker, waited for (a voice sentence that needs the phone).
    (result, True), or (None, False) if it failed or took too long."""
    done, out = threading.Event(), {}

    def job():
        try:
            out["r"] = fn()
        except (phone_link.LinkError, phone_link.NoObex, phone_link.NoDbus) as e:
            print(f"[phone] {type(e).__name__}", flush=True)
        finally:
            done.set()
    if threading.current_thread() is _thread:
        job()
        return out.get("r"), "r" in out
    _jobs.put(job)
    _ensure_thread()
    done.wait(timeout)
    return out.get("r"), "r" in out


def _whole_text(m):
    """The whole of a message, downloaded if the list had only its start."""
    if m["whole"]:
        return m["text"]
    body, ok = _run(lambda: _link.get_body(m["path"]))
    if ok and body:
        m["text"], m["whole"] = _tidy(body), True
    return m["text"]


def _seen(m):
    """Someone has read it here: it's read on the phone too."""
    global _last_read
    _last_read = (m["id"], time.time())
    if not m["read"]:
        m["read"] = True
        _publish()
        path = m["path"]

        def job():
            try:
                _link.mark_read(path)
            except phone_link.LinkError:
                pass
        _jobs.put(job)
        _ensure_thread()


_marking = False


def _mark_all(done):
    """Every unread SMS read, on the phone too; done(how many, all of them?) from the
    worker. False if that's already under way."""
    global _marking
    with _lock:
        if _marking:
            return False
        _marking = True

    def job():
        global _session, _marking, _next_poll
        n, ok = 0, False
        try:
            if not _session:
                _session = _link.open_map(config()["addr"])
            for path in _link.unread_paths(_session):
                _link.mark_read(path)
                n += 1
            ok = True
        except (phone_link.LinkError, phone_link.NoObex, phone_link.NoDbus) as e:
            print(f"[phone] marking failed: {e}", flush=True)
            _drop_session()
        finally:
            _marking = False
        if ok:
            with _lock:
                for m in _inbox:
                    m["read"] = True
            _publish()
        _next_poll = 0.0                  # (stopped halfway: the list says which)
        print(f"[phone] marked {n} as read", flush=True)
        done(n, ok)
    _jobs.put(job)
    _ensure_thread()
    return True


def _marked_said(n, ok):
    if ok:
        return f"Oznaczone jako przeczytane: {n} {_sms_word(n)}." if n else "Nie ma nieprzeczytanych SMS-ów."
    return f"Oznaczone tylko: {n}. Telefon przestał odpowiadać." if n else "Nie udało się. Telefon nie odpowiada."


def mark_all_read(speak):
    """„Oznacz wszystkie SMS-y jako przeczytane”."""
    said = _denied() or _unavailable()
    if said:
        speak(said)
    elif not _mark_all(lambda n, ok: _say(_marked_said(n, ok))):
        speak("Już to robię.")


def inbox():
    with _lock:
        return list(_inbox)


def _message(mid):
    return next((m for m in inbox() if m["id"] == mid), None)


# ── pairing ───────────────────────────────────────────────────────────

def _is_phone(addr):
    cfg = config()
    pair = _pair
    return bool((cfg and cfg["addr"] == addr) or (pair and pair.get("addr") == addr))


def _on_confirm(addr, name, code, answer):
    """A device asks to pair (the D-Bus thread): only in the window, and someone taps."""
    if not _pair or (code is None):
        answer(False)
        return
    with _lock:
        _pair.update(addr=addr, name=name, code=code, answer=answer)
    with state.lock:
        ov = state.overlay
    import screens
    if not ov or ov[0] != "phone" or ov[2].get("view") != "pair":
        screens._show("phone", PAGE_SECS, {"view": "pair"})
    speak = _pair.get("speak") or _say
    threading.Thread(target=speak, daemon=True, name="phone-code",
                     args=("Czy na telefonie widzisz ten sam kod? Dotknij: zgadza się, albo powiedz: tak.",)).start()


def _on_cancel():
    with _lock:
        if _pair:
            _pair.update(code=None, answer=None)


def pair_answer(yes):
    """The code on both screens: someone says if it matches."""
    with _lock:
        if not _pair or not _pair.get("answer"):
            return False
        answer = _pair["answer"]
        _pair.update(answer=None, code=None if not yes else _pair.get("code"), accepted=yes)
    answer(yes)
    return True


def pair_info():
    with _lock:
        return dict(_pair) if _pair else None


def _obex_missing():
    try:
        return not _link.has_obex()
    except (phone_link.LinkError, phone_link.NoDbus, phone_link.NoObex):
        return False                # (can't tell: the window's own errors will say)


def start_pairing(speak):
    """"sparuj telefon": visible to phones for three minutes."""
    global _pair
    said = _denied()
    if said:
        speak(said)
        return
    cfg = config()
    if cfg:
        speak(f"Mam już sparowany telefon: {cfg['name']}. Żeby sparować inny, powiedz: odłącz telefon.")
        return
    if _obex_missing():
        speak(_NO_OBEX_PAIR)
        return
    import screens
    with _lock:
        _pair = {"until": time.time() + PAIR_SECS, "known": None, "speak": speak}
    screens._show("phone", PAIR_SECS, {"view": "pair"})
    _jobs.put(_open_window)
    _ensure_thread()
    speak("Dobrze. Na telefonie wejdź w Bluetooth i wybierz Lunę.")


def _open_window():
    global _pair
    try:
        _register()
        if _status == "no_dbus":
            raise phone_link.NoDbus("")
        known = {a for a, d in _link.devices().items() if d["paired"]}
        _link.open_window(PAIR_SECS)
        with _lock:
            if _pair:
                _pair["known"] = known
        print("[phone] waiting for a phone to pair", flush=True)
    except (phone_link.NoDbus, phone_link.LinkError) as e:
        print(f"[phone] pairing: {type(e).__name__} {e}", flush=True)
        speak = (_pair or {}).get("speak") or _say
        _end_pairing()
        speak(_NO_DBUS if isinstance(e, phone_link.NoDbus) else "Nie udało mi się włączyć Bluetootha.")


def _end_pairing():
    """The window is over. Her page goes with it."""
    global _pair
    with _lock:
        was, _pair = _pair, None
    if was is None:
        return
    try:
        _link.close_window()
    except (phone_link.LinkError, phone_link.NoDbus):
        pass
    with state.lock:
        ov = state.overlay
        if ov and ov[0] == "phone" and ov[2].get("view") == "pair":
            state.overlay = None
    if not config():
        _link.unregister_agent()          # (no phone: the desktop's agent again)


def cancel_pairing():
    pair_answer(False)
    _jobs.put(_end_pairing)
    _ensure_thread()


def _tick_pair(now):
    global _next_poll, _first_poll
    pair = pair_info()
    if not pair:
        return
    if now > pair["until"]:
        _end_pairing()
        return
    if pair.get("known") is None:
        return
    new = [(a, d) for a, d in _link.devices().items() if d["paired"] and a not in pair["known"]]
    if not new:
        return
    addr, dev = new[0]
    owner = contacts.viewer()
    _save_config({"addr": addr, "name": dev["name"] or pair.get("name") or "telefon", "owner": owner})
    print("[phone] paired", flush=True)
    _end_pairing()
    _first_poll, _next_poll = True, now + 3
    speak = pair.get("speak") or _say
    speak("Telefon sparowany. Na telefonie zezwól mi na dostęp do wiadomości i kontaktów.")


def forget(speak):
    """"odłącz telefon": the pairing and all we hold about it are gone."""
    said = _denied()
    if said:
        speak(said)
        return
    cfg = config()
    if not cfg:
        speak("Nie mam sparowanego telefonu.")
        return

    def job():
        global _inbox, _book, _status, _draft, _last_read, _first_poll, _next_poll
        _drop_session()
        addr = cfg["addr"]
        _save_config(None)
        with _lock:
            _inbox, _book, _draft, _last_read = [], {}, None, None
        _status, _first_poll, _next_poll = "off", True, 0.0
        _publish()
        try:
            _link.forget(addr)
        except phone_link.LinkError as e:
            print(f"[phone] forgetting: {e}", flush=True)
        _link.unregister_agent()
    _run(job, timeout=10.0)
    speak("Odłączyłam telefon. Możesz go też usunąć z listy Bluetooth w telefonie.")


# ── drafts: who, what, "wysłać?" ──────────────────────────────────────

def can_reply(m):
    """A sender with a number (not "InPost" or the like)."""
    return bool(re.fullmatch(r"\+?\d{3,15}", re.sub(r"[\s\-]", "", m["number"] or "")))


def _spoken_number(s):
    """A number said or typed in digits ("600 100 200"), or None."""
    if re.search(r"[a-ząćęłńóśźż]", s.lower()):
        try:
            s = contacts._spoken_digits(s)
        except Exception:
            return None
    plain = re.sub(r"[\s\-()]", "", s or "")
    return plain if re.fullmatch(r"\+?\d{9,15}", plain) else None


def _prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _word_score(said, word):
    """How well a declined word fits a name's ("Kasi" – "Kasia"); 0: not at all."""
    if said == word:
        return 100
    n = _prefix(said, word)
    return n if n >= 2 and n >= min(len(said), len(word)) - 2 else 0


def find_people(spoken):
    """The best fits among those she has numbers for: [(name, number)]."""
    words = re.findall(r"\w+", spoken.lower())
    if not words:
        return []
    with _lock:
        people = dict(_book)
        for m in _inbox:
            if m["number"] and m["who"] != m["number"]:
                people.setdefault(m["who"], m["number"])
    people.update(_card_numbers())
    for w in words:                                # "do mamy": faces knows who that is
        name = contacts._person(w)
        if name and name in people:
            return [(name, people[name])]
    scored = []
    for name, number in people.items():
        parts = re.findall(r"\w+", name.lower())
        total = 0
        for w in words:
            best = max((_word_score(w, p) for p in parts), default=0)
            if not best:
                total = 0
                break
            total += best
        if total:
            scored.append((total, name, number))
    if not scored:
        return []
    top = max(s[0] for s in scored)
    return [(n, num) for s, n, num in scored if s == top]


def draft():
    global _draft
    with _lock:
        if _draft and time.time() > _draft["until"]:
            _draft = None
        return _draft


def active():
    """She's waiting for a word about a draft or a pairing code."""
    d = draft()
    with _lock:
        code = bool(_pair and _pair.get("answer"))
    return code or bool(d and d["step"] != "typing")


def dictating():
    """The next sentence is the text of an SMS: taken as it is, no filters."""
    d = draft()
    return bool(d and d["step"] == "body")


def _touch(d):
    d["until"] = time.time() + DRAFT_SECS


def _drop_draft():
    global _draft
    with _lock:
        _draft = None


def closed_by_voice(data):
    """"Zamknij wiadomości": a draft or a pairing on the page ends with it."""
    view = (data or {}).get("view")
    if view == "confirm" or (data or {}).get("edit"):
        _drop_draft()
    elif view == "pair":
        cancel_pairing()


def _show_confirm():
    import screens
    screens._show("phone", PAGE_SECS, {"view": "confirm", "edit": None, "toast": None})


def _ask_next(speak):
    """Whatever the draft still needs, asked."""
    d = draft()
    if not d:
        return
    _touch(d)
    if d["to"] is None:
        d["step"] = "who"
        speak("Do kogo?")
    elif not d["text"]:
        d["step"] = "body"
        speak(f"Co mam napisać? Do: {d['to']}.")
    else:
        d["step"] = "confirm"
        keep_private(d["text"])
        _show_confirm()
        speak(f"SMS do: {d['to']}. Wysłać?" if d.pop("told", False) else _read_back(d))


def _set_who(d, spoken, speak):
    """Who it's for, from what was said. True if settled (or asked again)."""
    number = _spoken_number(spoken)
    if number:
        d["to"], d["number"] = _name_of(number, None), number
        return True
    hits = find_people(spoken)
    if len(hits) == 1:
        d["to"], d["number"] = hits[0]
        return True
    d["tries"] = d.get("tries", 0) + 1
    d["step"] = "who"
    _touch(d)
    if len(hits) > 1:
        speak("Do kogo: " + " czy ".join(n for n, _ in hits[:3]) + "?")
    else:
        speak(f"Nie mam numeru: {spoken}. Podaj inne imię albo numer.")
    return False


def _read_back(d):
    text = d["text"].rstrip(" .")
    return f"SMS do: {d['to']}. {text}{'' if text[-1:] in ('!', '?', '…') else '.'} Wysłać?"


def _begin(who, text, speak, reply_to=None, told=False):
    """A new SMS, with whatever of it has been said so far."""
    global _draft
    said = _denied() or _unavailable()
    if said:
        speak(said)
        return True
    with _lock:
        _draft = {"step": "who", "to": reply_to and reply_to["who"], "number": reply_to and reply_to["number"],
                  "text": _tidy(text)[:BODY_MAX], "until": time.time() + DRAFT_SECS, "tries": 0, "told": told}
    if who and not _set_who(_draft, who, speak):
        return True
    _ask_next(speak)
    return True


def _send(d, done):
    """The draft goes to the phone; done(ok) from the worker."""
    number, body = d["number"], d["text"]
    _drop_draft()

    def job():
        global _session
        ok = False
        try:
            if not _session:
                _session = _link.open_map(config()["addr"])
            _link.push_message(_session, phone_link.bmessage(number, body))
            ok = True
            print(f"[phone] an SMS sent ({len(body)} characters)", flush=True)
        except (phone_link.LinkError, phone_link.NoObex, phone_link.NoDbus) as e:
            print(f"[phone] sending failed: {type(e).__name__}", flush=True)
            _drop_session()
        done(ok)
    _jobs.put(job)
    _ensure_thread()


_CANCEL = re.compile(r"^(?:anuluj|stop|nieważne|rezygnuję|zostaw|nic|daj spokój|nie wysyłaj|"
                     r"nie trzeba|nie chcę)(?: to| tego)?$", re.I)
_YES = re.compile(r"^(?:(?:no|no to|to|więc|weź) )?(?:tak|tak tak|wyślij|wysyłaj|ok|okej|dobrze|dobra|zgadza się|"
                  r"potwierdzam|jasne|pewnie|dawaj|śmiało|poproszę)(?: (?:wyślij|wysyłaj|proszę|tak|to|go|ją|już|śmiało))*$", re.I)
_NO = re.compile(r"^nie(?: nie| wysyłaj| trzeba| chcę)*$", re.I)
_REPEAT = re.compile(r"^(?:powtórz|jeszcze raz|co\??$|słucham|nie słyszałem|nie słyszałam|przeczytaj)", re.I)
_CHANGE = re.compile(r"^(?:popraw|zmień|napisz inaczej|inaczej|poprawka)", re.I)
_HINT = re.compile(r"^(?:nie wiem|pomóż|pomocy|co mam powiedzieć|jak to)", re.I)
_NAME = re.compile(r"^luna[,\s]+", re.I)      # (a "hej" in an SMS stays)


_ASKS = re.compile(r"^(?:pokaż|wyświetl|otwórz|przeczytaj|odczytaj|czytaj|wyślij|napisz|odpisz|włącz|wyłącz|"
                   r"puść|zamknij|ile|czy|co|jak|jaka|jaki|jakie|kiedy|gdzie|która|który|dlaczego|"
                   r"sparuj|odłącz|oznacz|zaznacz)\b", re.I)


def _not_a_name(t):
    """At "Do kogo?": a sentence that's plainly something else, and nobody she knows."""
    spoken = re.sub(r"^do\s+", "", t, flags=re.I)
    if _spoken_number(t) or find_people(spoken):
        return False
    return len(spoken.split()) > 4 or bool(_ASKS.match(t)) or bool(_SMS_IN.search(t))


def answer(text, speak):
    """A sentence while she waits. True if it was for her; False: it goes on, and an
    unsent draft is dropped (a later "tak" must not send it)."""
    t = _clean(text)
    with _lock:
        code = bool(_pair and _pair.get("answer"))
    if code:
        if _YES.match(t) or t.startswith("zgadza"):
            pair_answer(True)
            speak("Dobrze. Potwierdź jeszcze na telefonie.")
            return True
        if _NO.match(t) or _CANCEL.match(t):
            pair_answer(False)
            speak("Dobrze, nie paruję.")
            return True
    d = draft()
    if not d or d["step"] == "typing":
        return False
    step = d["step"]
    if step in ("who", "body") and _CANCEL.match(t):
        _drop_draft()
        _close_page()
        speak("Dobrze, nie wysyłam.")
        return True
    if step == "who":
        if _REPEAT.match(t):
            _touch(d)
            speak("Do kogo?")
            return True
        if _HINT.match(t):
            _touch(d)
            speak(_HINT_WHO)
            return True
        if _not_a_name(t):
            _drop_draft()
            if not _SMS_IN.search(t):                          # (about SMS: its answer says enough)
                speak("Nie wysyłam tego SMS-a.")
            return False
        if _set_who(d, re.sub(r"^do\s+", "", t, flags=re.I), speak):
            _ask_next(speak)
        elif d["tries"] >= 3:
            _drop_draft()
            speak("Nie znalazłam tego numeru, więc nie wysyłam.")
        return True
    if step == "body":
        if _REPEAT.match(t) and len(t.split()) <= 3:
            _touch(d)
            speak(f"Co mam napisać? Do: {d['to']}.")
            return True
        if _HINT.match(t) and len(t.split()) <= 4:
            _touch(d)
            speak(_HINT_BODY)
            return True
        if _WRITE_IT.match(t):
            speak("Już piszę.")
            d["text"] = _composed(t, d["to"])
            _ask_next(speak)
            return True
        d["text"] = _tidy(_NAME.sub("", text.strip()))[:BODY_MAX]
        _ask_next(speak)
        return True
    # confirm ("Dobra, wyślij"; "What? Nie.": the noise before a short no)
    plain = " ".join(t.replace(",", " ").split())
    if _NO.match(plain) or _CANCEL.match(plain) or (len(plain.split()) <= 3 and re.search(r"(?:^|[\s?!.])nie$", plain, re.I)):
        _drop_draft()
        _close_page()
        speak("Dobrze, nie wysyłam.")
        return True
    if _YES.match(plain):
        if _denied():
            _drop_draft()
            _close_page()
            speak(_ADULTS)
            return True
        _close_page()
        _send(d, lambda ok: speak("Wysłane." if ok else "Nie udało się wysłać. Telefon nie odpowiada."))
        return True
    if _CHANGE.match(t):
        d["text"] = ""
        _ask_next(speak)
        return True
    if _REPEAT.match(t):
        _touch(d)
        speak(_read_back(d))
        return True
    if _HINT.match(t):
        _touch(d)
        speak("Powiedz: tak, żeby wysłać, popraw, żeby zmienić treść, albo: anuluj.")
        return True
    if len(plain.split()) <= 2 and not d.get("asked_again"):       # a misheard word, not a new request
        d["asked_again"] = True
        _touch(d)
        speak("Nie dosłyszałam. Wysłać? Powiedz: tak albo nie.")
        return True
    _drop_draft()
    _close_page()
    speak("Nie wysyłam tego SMS-a.")
    return False


# ── reading ───────────────────────────────────────────────────────────

def _say_one(m, speak):
    body = _whole_text(m)
    cut = len(body) > SAY_MAX
    if cut:
        body = body[:SAY_MAX].rsplit(" ", 1)[0]
    keep_private(body)
    if cut:
        body += ". Reszta jest na ekranie"
    speak(f"{m['who']} pisze: {body or 'pusta wiadomość, może zdjęcie'}.")
    _seen(m)


def _show_message(m):
    import screens
    screens._show("phone", PAGE_SECS, {"view": "read", "id": m["id"], "edit": None, "toast": None})


def show_inbox(page=0, only=None):
    """The list; `only`: the names whose messages it shows."""
    import screens
    screens._show("phone", PAGE_SECS, {"view": "inbox", "page": page, "only": only, "edit": None, "toast": None})


def _show_list(sender, speak):
    """"pokaż SMS-y [od Kasi]": the page, and in a few words what's on it."""
    msgs = inbox()
    said = _denied() or (None if msgs else _unavailable())
    if said:
        speak(said)
        return
    only = None
    if sender:
        only = sorted({n for n, _ in _who_wrote(sender)})
        if not only:
            speak(f"Nie mam SMS-a od: {sender}.")
            return
    show_inbox(only=only)
    n = sum(1 for m in msgs if not m["read"])
    if not msgs:
        speak("Jeszcze łączę się z telefonem." if status() == "connecting" else "Nie ma żadnych SMS-ów.")
    elif only:
        speak(f"SMS-y od: {only[0]}.")
    else:
        speak(f"Nowe: {n}." if n else "Nie ma nowych SMS-ów. Oto ostatnie.")


def _sms_word(n):
    if n == 1:
        return "SMS"
    return "SMS-y" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "SMS-ów"


def _read_out(sender, last, speak):
    """"przeczytaj SMS-y": the unread ones; "od Kasi": hers; "ostatni": the newest."""
    said = _denied() or _unavailable()
    if said and not (inbox() and not _denied()):
        speak(said)
        return True
    msgs = inbox()
    if sender:
        fits = {n for n, _ in _who_wrote(sender)}
        picked = [m for m in msgs if m["who"] in fits][:1]
        if not picked:
            speak(f"Nie mam SMS-a od: {sender}.")
            return True
    elif last:
        picked = msgs[:1]
    else:
        picked = [m for m in msgs if not m["read"]][:READ_MAX]
        if not picked and msgs:
            speak("Nie ma nowych SMS-ów. Ostatni:")
            picked = msgs[:1]
    if not picked:
        speak("Nie ma żadnych SMS-ów.")
        return True
    _show_message(picked[0])
    for m in picked:
        _say_one(m, speak)
    return True


def _who_wrote(spoken):
    """Senders that fit what was said: [(name, score)], the best ones."""
    words = re.findall(r"\w+", spoken.lower())
    scored = []
    for name in {m["who"] for m in inbox()}:
        parts = re.findall(r"\w+", name.lower())
        scores = [max((_word_score(w, p) for p in parts), default=0) for w in words]
        if scores and all(scores):
            scored.append((name, sum(scores)))
    top = max((s for _, s in scored), default=0)
    return [(n, s) for n, s in scored if s == top]


# ── sentences ─────────────────────────────────────────────────────────

_SMS = r"(?:sms(?:-?[a-ząćęłńóśźż]+)?|esemes\w*|es\s?em\s?es\w*)"
_LEAD = re.compile(r"^(?:luna|hej|proszę|mogłabyś)[,\s]+", re.I)
_ANY = re.compile(_SMS + r"|telefon|komórk|smartfon|odpisz|odpowiedz|napisał|pisze|jako przeczytane|wiadomo[sś]", re.I)
_MY = r"(?:\s+(?:mój|moim|mojego|moja|moją|ten|tym|tego|nowy|nowym|sparowany))?"
_THE_PHONE = r"\s+(?:telefon|telefonu|telefonem|komórk[aąęi]|smartfon\w*)"
_PAIR = re.compile(rf"^(?:sparuj|połącz|podłącz|dodaj)(?:\s+się)?(?:\s+z)?{_MY}{_THE_PHONE}"
                   r"(?:\s+(?:przez|po)\s+bluetooth\w*)?$", re.I)
_FORGET = re.compile(rf"^(?:odłącz|rozłącz|odparuj|rozparuj|zapomnij)(?:\s+się)?(?:\s+(?:od|z))?{_MY}{_THE_PHONE}$", re.I)
_STATE = re.compile(r"^(?:czy\s+)?(?:(?:masz|mamy)\s+)?(?:(?:jest\s+)?telefon\s+(?:jest\s+)?"
                    r"(?:połączony|sparowany|podłączony)|połączenie\s+z\s+telefonem|"
                    r"jaki\s+telefon\s+(?:jest\s+|masz\s+)?(?:połączony|sparowany|podłączony)|"
                    r"masz\s+połączenie\s+z\s+telefonem|stan\s+telefonu)$", re.I)
_MANY = r"(?:\s+(?:moje|moją|mojego|nowe|nową|nowego|nowy|nowych|ostatnie|ostatnią|ostatni|ostatniego|wszystkie|jakieś|jakiś|jakiegoś|nieprzeczytane|nieprzeczytanych))*"
_FROM_PHONE = rf"wiadomo(?:ści|ść)\s+(?:{_SMS}|z\s+(?:telefonu|komórki))"
_LIST_WORD = rf"(?:{_SMS}|{_FROM_PHONE})"
_HOW_MANY = r"(?:\s+(?:\d+|dwa|dwie|trzy|cztery|pięć|sześć|siedem|osiem|dziewięć|dziesięć|kilka|parę|ostatnich|wszystkich))*"
_SHOW = re.compile(rf"^(?:pokaż|wyświetl|otwórz)(?:\s+mi)?{_HOW_MANY}{_MANY}{_HOW_MANY}\s+{_LIST_WORD}"
                   r"(?:\s+(?:z\s+telefonu|z\s+komórki|na\s+ekranie))*(?:\s+od\s+(?P<who>.+))?$", re.I)
_SHOW_BARE = re.compile(rf"^(?:pokaż|wyświetl|otwórz)(?:\s+mi)?{_MANY}\s+wiadomo(?:ści|ść)(?:\s+od\s+(?P<who>.+))?$", re.I)
_READ = re.compile(rf"^(?:przeczytaj|odczytaj|czytaj)(?:\s+mi)?(?P<many>{_MANY})\s+{_LIST_WORD}"
                   r"(?:\s+od\s+(?P<who>.+))?$", re.I)
_MARK_ALL = re.compile(rf"^(?:oznacz|zaznacz|ustaw)(?:\s+mi)?(?:\s+(?:wszystkie|wszystko|moje|te|nowe))*"
                       rf"(?:\s+{_LIST_WORD}|\s+wiadomości)?(?:\s+z\s+telefonu)?\s+jako\s+przeczytane$", re.I)
_COUNT = re.compile(rf"^(?:czy\s+)?(?:(?:(?:jakie\s+)?mam|są|jest|przyszedł|przyszły|przyszło|dostałem|dostałam)"
                    rf"{_MANY}\s+{_LIST_WORD}|ile\s+(?:mam|jest){_MANY}\s+{_LIST_WORD}|ile{_MANY}\s+{_LIST_WORD})$", re.I)
_WROTE = re.compile(r"^co\s+(?:mi\s+|do\s+mnie\s+)?(?:napisał[ao]?|pisze)\s+(?P<who>\w+(?:\s+\w+)?)$", re.I)
_SEND = re.compile(r"^(?:wyślij|napisz|prześlij|nadaj)\b(?P<rest>.*)$", re.I | re.S)
_SMS_IN = re.compile(rf"\b{_SMS}\b", re.I)
_FILL = re.compile(r"^(?:mi|nowy|nowego|nową|krótki|krótkiego|krótką|jeszcze|takiego|wiadomość|wiadomości)\b\s*", re.I)
_MARK = re.compile(r"\s*[,:]?\s*\b(?:że|o treści|z treścią|treść)\b\s*[,:]?\s*|\s*[,:]\s*", re.I)
_TO_THEM = rf"\s+(?:jej|mu|do niej|do niego|na to|na niego|na\s+tego\s+{_SMS}|na\s+{_SMS})"
_REPLY = re.compile(rf"^(?:odpisz(?:{_TO_THEM})?|odpowiedz{_TO_THEM}|odpowiedz(?=\s*[,:]|\s+że\b))"
                    r"(?:\s*[,:]\s*(?:że\s+)?|\s+że\s+|\s+|$)(?P<body>.*)$", re.I | re.S)


def _clean(text):
    return " ".join(_LEAD.sub("", text.strip()).strip(" .!?…").split())


def _split_who(left):
    """"Kasi będę później" (no comma heard): (who, what's left)."""
    words = left.split()
    if _spoken_number(left):
        return left, ""
    for n in range(min(3, len(words)), 0, -1):
        if find_people(" ".join(words[:n])):
            return " ".join(words[:n]), " ".join(words[n:])
    return left, ""


_NICE = r"(?:fajn|mił[aeyą]|ładn|zabawn|śmieszn|ciekaw|kreatywn|sympatyczn|wesoł)\w*"
_DESCRIBED = re.compile(rf"\b(?:jakie\w+|jakiś|jakąś|coś|{_NICE})\b", re.I)
_WRITE_IT = re.compile(rf"^(?:(?:ty|sama)\s+)?(?:napisz|wymyśl|ułóż)(?:\s+sama)?"
                       rf"(?:\s+coś(?:\s+{_NICE}|\s+od\s+siebie)?)?(?:\s+sama)?$|^coś\s+(?:{_NICE}|od\s+siebie)$", re.I)
_FROM_MODEL = re.compile(r"^wyślij\s+sms(?:\s+do\s+(?P<who>[^:]+?))?\s*(?::\s*(?P<body>.*))?$", re.I | re.S)


def model_line():
    """For her prompt: with a phone here she can send, and the model writes the text."""
    try:
        if not config() or _denied():
            return ""
    except Exception as e:
        print(f"[phone] no line for the model: {e!r}", flush=True)
        return ""
    return ("A phone is connected, so you CAN send SMS; never say you can't. When they ask you to "
            "write or send one (\"napisz coś miłego do Mai\" means an SMS too) and you know who to: write the text yourself unless they dictated it, "
            "and add an action of type \"command\" with the label \"wyślij SMS do <imię>: <treść>\". "
            "Then \"reply\" is only a few words such as \"Już piszę.\": not the text, and no question "
            "whether to send, because the app reads it out and asks, and nothing goes without their yes. "
            "\"Wyślij\" or \"napisz to w SMS-ie\" about what you have just said is the same action with that text, "
            "to the person you were talking about. Sign it only "
            "if they ask. Who to not known: ask in \"reply\", no action.\n")


def _words(s):
    return " ".join(re.findall(r"\w+", s.lower()))


def from_model(label, reply=""):
    """The model's "wyślij SMS do Maja: treść": a draft, read out; sent only after a yes."""
    m = _FROM_MODEL.match(label.strip())
    who, body = (m["who"], m["body"] or "") if m else (None, "")
    print(f"[phone] the model wrote an SMS ({len(body)} characters)", flush=True)
    _begin(who, body, _say, told=bool(body) and _words(body)[:40] in _words(reply))
    return True


def claims_first(text):
    """"wiadomości SMS": before news and voice messages, which go by "wiadomości" alone."""
    return bool(re.search(rf"\b{_FROM_PHONE}\b", text, re.I))


_POINTING = frozenset("""to w we na jako przez z ze tym tą tę te ta ten tego tej tamto tamtym jej mu jemu im je ją
                        niej niego nich nim tekst tekstem treść treścią wiadomość wiadomością""".split())


_COMPOSE = re.compile(r"^(?:napisz|ułóż|wymyśl|przygotuj|wyślij)\s+(?:mi\s+)?(?P<rest>.+)$", re.I | re.S)
_ABOUT_SMS = re.compile(rf"{_SMS}|wiadomo\w+|treś\w+|tekst\w*|krótk\w+|i|wyślij|wysyłaj|pokaż|od|siebie|"
                        rf"{_NICE}|jakie\w+|jakiś|jakąś|jakaś|coś", re.I)
_NO_NAME = _POINTING | {"o", "dla", "po", "za", "pod", "nad", "przy"}


def _composed(request, to):
    """The SMS the model writes for this request. "" if it can't."""
    try:
        from openai import OpenAI
        from config import CRAFT_MODEL, OPENAI_API_KEY
        msg = (f"You write one SMS in Polish to {to}. It goes from the phone of {state.person or 'its owner'}, "
               f"written as them, in the first person. Someone told Luna, a small home robot: \"{request}\". "
               "Follow that. One or two warm, natural sentences, at most 160 characters, no emoji, no quotes around it. "
               "No signature unless they ask; \"podpisz się\" said to Luna means sign it as Luna. "
               "Answer with the text of the SMS only.")
        r = OpenAI(api_key=OPENAI_API_KEY, timeout=10, max_retries=1).chat.completions.create(
            model=CRAFT_MODEL, temperature=0.9, max_tokens=120, messages=[{"role": "user", "content": msg}])
        body = _tidy(r.choices[0].message.content or "").strip("\"„”“' ")[:BODY_MAX]
        print(f"[phone] she wrote an SMS ({len(body)} characters)", flush=True)
        return body
    except Exception as e:
        print(f"[phone] couldn't write an SMS: {e!r}", flush=True)
        return ""


def _write_to_someone(t, speak):
    """No word "SMS", but "napisz coś miłego do Mai" and "napisz do Mai, że wracam" can only mean one. True if handled."""
    m = _COMPOSE.match(t)
    if not m or not config() or _denied():
        return False
    head, *rest = re.split(r"\s*[,:]\s*", m["rest"], maxsplit=1)
    tail = rest[0] if rest else ""
    words = head.split()
    others = [w for w in words if w.lower() != "do" and not _ABOUT_SMS.fullmatch(w)]
    if not 1 <= len(others) <= 2 or _NO_NAME.intersection(w.lower() for w in others):
        return False
    who = " ".join(others)
    hits = find_people(who)
    if not hits:
        return False
    if _DESCRIBED.search(head) or re.search(r"\btreś", head, re.I) or _WRITE_IT.match(tail):
        said = _unavailable()
        if said:
            speak(said)
            return True
        speak("Już piszę.")
        return _begin(who, _composed(t, hits[0][0] if len(hits) == 1 else who), speak)
    if t.lower().startswith("napisz") and words[0].lower() == "do" and len(words) == len(others) + 1:
        return _begin(who, re.sub(r"^że\s+", "", tail, flags=re.I), speak)
    return False


def _parse_send(t):
    """(who, body) of "wyślij SMS do Kasi, że…", or None if it isn't about an SMS."""
    m = _SEND.match(t)
    hit = m and _SMS_IN.search(m["rest"])
    if not hit:
        return None
    before = m["rest"][:hit.start()].strip()
    after = m["rest"][hit.end():].strip()
    while _FILL.match(before):
        before = _FILL.sub("", before)
    if _DESCRIBED.search(before):                 # "napisz do Mai jakiegoś fajnego SMS-a": the model writes it
        return None
    body = ""
    mark = _MARK.search(after)
    if mark:
        after, body = after[:mark.start()].strip(), after[mark.end():].strip()
        if _WRITE_IT.match(body):
            return None
    if before and after:                          # "napisz Kasi SMS będę później"
        body, after = (after + " " + body).strip() if body else after, ""
    who = re.sub(r"^(?:do|na\s+numer|na)\s+", "", before or after, flags=re.I).strip()
    if who and not mark and not before:
        who, body = _split_who(who)
    elif before:
        who = re.sub(r"^do\s+", "", before, flags=re.I)
    if who and set(who.lower().replace(",", " ").split()) <= _POINTING:   # "napisz to w SMS-ie": the model knows what, and who
        return None
    return who or None, body


def command(text, speak):
    """A sentence about the phone. True if it was handled."""
    if len(text.split()) > 60:
        return False
    t = _clean(text)
    if _write_to_someone(t, speak):
        return True
    if not _ANY.search(text):
        return False
    if _PAIR.match(t):
        start_pairing(speak)
        return True
    if _FORGET.match(t):
        forget(speak)
        return True
    if _STATE.match(t):
        cfg = config()
        if not cfg:
            speak(_NONE)
        else:
            speak({"on": f"Tak, jestem połączona z telefonem: {cfg['name']}.",
                   "connecting": "Właśnie łączę się z telefonem."}.get(status())
                  or _unavailable() or _AWAY)
        return True
    sent = _parse_send(t)
    if sent:
        return _begin(sent[0], sent[1], speak)
    m = _SHOW.match(t)
    if m:
        _show_list(m["who"], speak)
        return True
    m = _SHOW_BARE.match(t)
    if m and config():                  # (no phone: it isn't about SMS)
        _show_list(m["who"], speak)
        return True
    if _MARK_ALL.match(t):
        mark_all_read(speak)
        return True
    m = _READ.match(t)
    if m:
        return _read_out(m["who"], "ostatni" in (m["many"] or "").lower(), speak)
    if _COUNT.match(t):
        said = _denied() or (None if inbox() else _unavailable())
        if said:
            speak(said)
        else:
            n = sum(1 for x in inbox() if not x["read"])
            speak(f"Masz {n} {'nowy' if n == 1 else 'nowe' if _sms_word(n) == 'SMS-y' else 'nowych'} {_sms_word(n)}."
                  if n else "Nie ma nowych SMS-ów.")
        return True
    m = _WROTE.match(t)
    if m and config() and _who_wrote(m["who"]):    # (else a question for the model)
        return _read_out(m["who"], False, speak)
    m = _REPLY.match(t)
    if m and _last_read and time.time() - _last_read[1] < REPLY_SECS:
        last = _message(_last_read[0])
        if last and can_reply(last):
            return _begin(None, m["body"], speak, reply_to=last)
        if last:
            speak("Na tę wiadomość nie da się odpisać.")
            return True
    return False


# ── the page ──────────────────────────────────────────────────────────

def _close_page():
    with state.lock:
        ov = state.overlay
        if ov and ov[0] == "phone":
            state.overlay = None


def _page_data(now=None):
    now = now or time.time()
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "phone":
            return None
        secs = EDIT_SECS if ov[2].get("edit") else PAGE_SECS
        if ov[2].get("view") not in ("pair", "new"):
            state.overlay = (ov[0], now + secs, ov[2])
        return ov[2]


def _toast(data, text, now=None):
    data["toast"] = (text, (now or time.time()) + 2.5)


def _within(rect, x, y):
    return rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]


def row_rects(W, H):
    """The list's rows."""
    return [(24, 88 + i * 66, W - 48, 60) for i in range(PAGE_ROWS)]


def buttons(view, W, H, data=None):
    """[(key, label, rect, gold?)] on this view; the logic owns them, so taps and
    tests need no pygame."""
    y, h, gap = H - 78, 62, 14
    keys = []
    if view == "pair":
        if (pair_info() or {}).get("answer"):
            keys = [("pair_yes", "Zgadza się", True), ("pair_no", "Nie", False)]
    elif view == "inbox":
        keys = [("prev", "‹", False), ("write", "Nowy SMS", True), ("next", "›", False)]
        y, h = H - 58, 48
        if data and not data.get("only") and any(not m["read"] for m in inbox()):
            keys.insert(2, ("mark_all", "Wszystkie przeczytane", False))
            widths = (80, 200, W - 48 - 3 * gap - 360, 80)
            xs = [24 + sum(widths[:i]) + i * gap for i in range(4)]
            return [(k, lab, (x, y, w, h), gold) for (k, lab, gold), x, w in zip(keys, xs, widths)]
    elif view == "read":
        keys = [("reply", "Odpisz", True), ("say", "Przeczytaj", False), ("list", "Lista", False)]
    elif view == "confirm":
        keys = [("send", "Wyślij", True), ("retype", "Popraw", False), ("cancel", "Anuluj", False)]
    elif view == "new":
        keys = [("open", "Otwórz", True)]
    if not keys:
        return []
    w = (W - 48 - gap * (len(keys) - 1)) // len(keys)
    return [(k, lab, (24 + i * (w + gap), y, w, h), gold) for i, (k, lab, gold) in enumerate(keys)]


def page_of(data):
    """(this page's messages, page number, how many pages)."""
    msgs = inbox()
    if data.get("only"):
        msgs = [m for m in msgs if m["who"] in data["only"]]
    pages = max(1, -(-len(msgs) // PAGE_ROWS))
    page = min(data.get("page", 0), pages - 1)
    return msgs[page * PAGE_ROWS:(page + 1) * PAGE_ROWS], page, pages


def _start_typing(data, m, now=None):
    """"Odpisz" on the screen: the keyboard, then "Wysłać?" as for her voice."""
    global _draft
    if _denied():
        _toast(data, "Poproś dorosłego", now)
        return
    if _unavailable():
        _toast(data, "Telefon nie odpowiada", now)
        return
    if not can_reply(m):
        _toast(data, "Na tę wiadomość nie da się odpisać", now)
        return
    with _lock:
        _draft = {"step": "typing", "to": m["who"], "number": m["number"], "text": "",
                  "until": time.time() + EDIT_SECS, "tries": 0}
    data["edit"] = {"text": "", "layer": "abc", "shift": True}


def _key_press(data, key, now=None):
    e = data["edit"]
    if key == "save":
        d = draft()
        text = e["text"].strip()
        if not d or not text:
            _toast(data, "Napisz coś najpierw" if d else "Za długo to trwało", now)
            return
        d["text"], d["step"] = _tidy(text)[:BODY_MAX], "confirm"
        _touch(d)
        data["edit"] = None
        data["view"] = "confirm"
    else:
        contacts.type_key(e, key, BODY_MAX)


def tap(x, y, W, H, now=None):
    """A tap (px): a row, a button, a key."""
    data = _page_data(now)
    if data is None:
        return False
    e = data.get("edit")
    if e:
        key = contacts.key_at("text", e["layer"], x, y, W, H)
        if key:
            _key_press(data, key, now)
        return True
    view = data.get("view")
    hit = next((b[0] for b in buttons(view, W, H, data) if _within(b[2], x, y)), None)
    if view == "inbox" and not hit:
        msgs = page_of(data)[0]
        for m, rect in zip(msgs, row_rects(W, H)):
            if _within(rect, x, y):
                data.update(view="read", id=m["id"])
                threading.Thread(target=_open_message, args=(m,), daemon=True, name="phone-read").start()
                return True
    if not hit:
        return True
    _button(data, hit, now, W, H)
    return True


def _open_message(m):
    _whole_text(m)
    _seen(m)


def _button(data, hit, now, W, H):
    if hit == "pair_yes":
        pair_answer(True)
        _toast(data, "Potwierdź jeszcze na telefonie", now)
    elif hit == "pair_no":
        cancel_pairing()
    elif hit in ("prev", "next"):
        pages = page_of(data)[2]
        data["page"] = (page_of(data)[1] + (1 if hit == "next" else -1)) % pages
    elif hit == "mark_all":
        if _denied():
            _toast(data, "Poproś dorosłego", now)
        elif _mark_all(lambda n, ok: _toast(data, _marked_said(n, ok))):
            _toast(data, "Oznaczam…", now)
    elif hit == "write":
        threading.Thread(target=_begin, args=(None, "", _say), daemon=True, name="phone-write").start()
    elif hit == "list":
        data.update(view="inbox", page=0)
    elif hit == "open":
        said = _denied()
        if said:
            _toast(data, "Poproś dorosłego", now)
            return
        m = _message(data.get("id"))
        if m:
            _show_message(m)                       # (a page's time, not the banner's)
            threading.Thread(target=_open_message, args=(m,), daemon=True, name="phone-read").start()
    elif hit in ("reply", "say"):
        m = _message(data.get("id"))
        if not m:
            data.update(view="inbox", page=0)
        elif hit == "reply":
            _start_typing(data, m, now)
        else:
            threading.Thread(target=_say_one, args=(m, _say), daemon=True, name="phone-say").start()
    elif hit == "send":
        d = draft()
        if not d or d["step"] != "confirm":
            _toast(data, "Za długo to trwało", now)
            return
        if _denied():
            _toast(data, "Poproś dorosłego", now)
            return
        _close_page()
        _send(d, lambda ok: _say("Wysłane." if ok else "Nie udało się wysłać. Telefon nie odpowiada."))
    elif hit == "retype":
        d = draft()
        if d:
            d["step"], d["until"] = "typing", time.time() + EDIT_SECS
            data["edit"] = {"text": d["text"], "layer": "abc", "shift": False}
    elif hit == "cancel":
        _drop_draft()
        _close_page()


def swipe(dx):
    """On the list: the next page."""
    data = _page_data()
    if data and data.get("view") == "inbox" and not data.get("edit"):
        _, page, pages = page_of(data)
        data["page"] = (page + (1 if dx < 0 else -1)) % pages


def on_close():
    """✕ on this page. True if something of it is still on the screen: the keyboard
    goes first, a message goes back to the list. A draft or a pairing ends with it."""
    with state.lock:
        ov = state.overlay
        data = ov[2] if ov and ov[0] == "phone" else None
    if data is None:
        return False
    if data.get("edit"):
        data["edit"] = None
        d = draft()
        if d and d["step"] == "typing":
            if d.get("text"):
                d["step"] = "confirm"
            else:
                _drop_draft()
        return True
    view = data.get("view")
    if view == "read":
        data.update(view="inbox", page=0)
        return True
    if view == "confirm":
        _drop_draft()
    elif view == "pair":
        cancel_pairing()
    return False


# ── the settings page ─────────────────────────────────────────────────

def _state_word():
    return {"on": "połączony", "connecting": "łączy się…", "no_obex": "brakuje pakietu bluez-obexd",
            "no_dbus": "brakuje python3-dbus"}.get(status(), "poza zasięgiem")


def settings_row():
    """Her row on Ustawienia → Urządzenia: pairing, or her group."""
    cfg = config()
    if not cfg:
        return {"key": "phone", "kind": "cycle", "label": "Telefon",
                "sub": "SMS-y z telefonu przez Bluetooth", "value": "Sparuj"}
    return {"key": "group:phone", "kind": "group", "label": "Telefon",
            "sub": f"{cfg['name']} — {_state_word()}", "value": ""}


def settings_group():
    """The group's rows, once a phone is paired."""
    return [{"key": "phone", "kind": "cycle", "label": "SMS-y", "sub": f"{config()['name']} — {_state_word()}",
             "value": "Otwórz"},
            {"key": "phone_preview", "kind": "toggle", "label": "Podgląd SMS-ów",
             "sub": "nowy SMS: od kogo i początek treści",
             "value": settings.get("phone_preview", True) is not False}]


def settings_tap():
    """The row tapped: pairing, or the messages. Returns the toast."""
    said = _denied()
    if said:
        return "Poproś dorosłego"
    if config():
        show_inbox()
    else:
        threading.Thread(target=start_pairing, args=(_say,), daemon=True, name="phone-pair").start()
    return None
