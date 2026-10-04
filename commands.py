"""
commands.py — things Luna does herself, without asking the model.

  volume   "głośniej", "ciszej", "głośność na 40", "louder" …
  speed    "mów wolniej", "szybciej", "mów normalnie" (kept in settings.json)
  sleep    "dobranoc" / "idę spać": she says good night, the screen dims, her
           eyes close and she stays quiet (no greetings, no touch talk)
           until morning — or until you speak to her
  game     "zagrajmy w kamień, papier, nożyce" (games.py)
  screens  "zrób mi zdjęcie", "pokaż lustro", "pokaż zegar" (screens.py)
  breathe  "ćwiczenie oddechowe" — a guided breathing circle (breathing.py)
  repeat   "powtórz", "co powiedziałaś?" — the last answer again, instantly
  restart  "zrestartuj się" — exits; the autostart watchdog restarts her
  fun      "włącz lampkę", "przybij piątkę", "rzuć kostką", "rzuć monetą"
           (fun.py)
  focus    "tryb skupienia" (optionally "na 50 minut"): no small talk,
           a countdown, then "czas na przerwę" and a break timer;
           "koniec skupienia" ends it
  goodbye  "pa", "do zobaczenia", "dzięki, to wszystko": a wave, and the
           conversation window closes at once
  wake     anything you say to her while she sleeps wakes her up (so
           "dzień dobry, Luna" does); in the morning (PROACTIVE_QUIET_TO) she
           wakes on her own, silently

They are instant and offline. Matching is deliberately strict — short
utterances only — so a normal sentence that happens to contain "ciszej" still
goes to the model.
"""

import json
import random
import re
import subprocess
import threading
import time

from shared_state import state
import settings
from config import (SPEED_STEP, SPEED_MIN, SPEED_MAX, OPENAI_TTS_SPEED,
                    VOLUME_STEP, VOLUME_MIN, VOLUME_MAX,
                    GOODNIGHT_REPLIES, GOODBYE_REPLIES, PROACTIVE_QUIET_TO,
                    FOCUS_MINUTES, BREAK_MINUTES, SNOOZE_MINUTES,
                    AUDIO_OUTPUT_DEVICE)

_LOUDER  = ("głośniej", "glosniej", "louder", "volume up")
_QUIETER = ("ciszej", "quieter", "volume down")
_VOLUME  = ("głośność", "glosnosc", "volume")
_SLOWER  = ("wolniej", "slower")
_FASTER  = ("szybciej", "faster")
_NORMAL_SPEED = ("normalnym tempie", "normalne tempo", "normalnie mów", "mów normalnie")
# goodbyes: the whole utterance must be one of these (after dropping "Luna")
# — "na razie nie" or "pa, a jeszcze jedno…" are not goodbyes
_BYE = {("pa",), ("pa", "pa"), ("papa",), ("do", "widzenia"), ("do", "zobaczenia"),
        ("na", "razie"), ("bye",), ("bye", "bye"), ("see", "you"), ("cześć", "pa"),
        ("to", "wszystko"), ("dzięki", "to", "wszystko"), ("dziękuję", "to", "wszystko"),
        ("dobra", "to", "wszystko"), ("trzymaj", "się")}
_FOCUS     = ("tryb skupienia", "pomodoro", "pomóż mi się skupić", "chcę się skupić",
              "chce sie skupic", "focus mode", "pomoz mi sie skupic")
_FOCUS_END = ("koniec skupienia", "przerwij skupienie", "wyłącz tryb skupienia",
              "wyłącz pomodoro", "stop pomodoro", "koniec pomodoro")
# A question ABOUT something is never a command for it: "ile trwa pomodoro?",
# "co jest mocniejsze, papier czy kamień?", "co to jest lustro?".
_QUESTION  = {"co", "czym", "jak", "jaki", "jaka", "jakie", "dlaczego", "czemu",
              "kiedy", "kto", "ile", "gdzie", "który", "która", "które", "czy",
              "what", "how", "why", "when", "who", "where", "which", "is", "are", "do"}
# …except a polite request: "czy możesz pokazać zegar?"
_POLITE    = {"możesz", "mozesz", "mogłabyś", "moglabys", "można", "mozna", "can", "could"}
_REPEAT  = ("co powiedziałaś", "co powiedzialas", "co mówiłaś", "co mowilas",
            "możesz powtórzyć", "mozesz powtorzyc", "nie dosłyszałem", "nie dosłyszałam",
            "say that again", "can you repeat")
_NIGHT   = ("dobranoc", "idę spać", "ide spac", "idę już spać", "idę już spać",
            "good night", "goodnight")
# "dobranoc" must be the whole point of the utterance — "powiedz dobranoc mojej
# córce" or "co było na dobranockę?" are not her bedtime
_NIGHT_OK = {"dobranoc", "luna", "luno", "idę", "ide", "spać", "spac", "już", "juz",
             "to", "ja", "no", "dobra", "dzięki", "dziękuję", "kochana", "pa", "papa",
             "i", "good", "night", "goodnight", "słodkich", "snów", "kolorowych"}


_LANGS = {"angiel": ("English", "angielski"), "niemiec": ("German", "niemiecki"),
          "hiszpa": ("Spanish", "hiszpański"), "francu": ("French", "francuski"),
          "włos": ("Italian", "włoski"), "wlos": ("Italian", "włoski"),
          "ukrai": ("Ukrainian", "ukraiński"), "rosyj": ("Russian", "rosyjski"),
          "czes": ("Czech", "czeski"), "portugal": ("Portuguese", "portugalski"),
          "japo": ("Japanese", "japoński"), "chiń": ("Chinese", "chiński"),
          "english": ("English", "angielski"), "german": ("German", "niemiecki"),
          "spanish": ("Spanish", "hiszpański"), "french": ("French", "francuski")}
_SNOOZE = ("drzemka", "drzemkę", "jeszcze chwilę", "jeszcze chwile", "jeszcze 5",
           "jeszcze pięć", "jeszcze 10", "jeszcze dziesięć", "jeszcze minut",
           "snooze")
_EXTEND = ("dodaj", "przedłuż", "przedluz", "add")
_RESTART = ("zrestartuj się", "zrestartuj sie", "uruchom się ponownie",
            "uruchom sie ponownie", "restart yourself")
_TRANSLATE_START = ("tłumacz na", "tlumacz na", "tłumaczyć na", "tlumaczyc na", "tryb tłumacza", "bądź tłumaczem",
                    "przetłumacz wszystko na", "tłumacz z polskiego na", "translate to",
                    "be my interpreter", "tłumacz mnie na", "tłumacz to co mówię na")
_TRANSLATE_END = ("koniec tłumaczenia", "przestań tłumaczyć", "wyłącz tłumacza",
                  "stop translating", "koniec tlumaczenia")


def _translator_language(low):
    """(English name, Polish name) when the utterance starts translator mode."""
    if not any(k in low for k in _TRANSLATE_START) or len(_words(low)) > 9:
        return None
    for stem, lang in _LANGS.items():
        if re.search(r"\b" + stem, low):
            return lang
    return ("English", "angielski") if "tryb tłumacza" in low or "tłumaczem" in low else None


def _words(text):
    return re.findall(r"\w+", text.lower())


def _short(text, n):
    return len(_words(text)) <= n


# Words a bare command may consist of. "Dlaczego w nocy jest ciszej?" is a
# question, not a command — every word has to come from this set.
_FILLER = {"luna", "luno", "mów", "mow", "mówić", "mowic", "trochę", "troche",
           "troszkę", "troszke", "nieco", "dużo", "duzo", "bardziej", "jeszcze",
           "proszę", "prosze", "możesz", "mozesz", "czy", "a", "i", "zrób",
           "zrob", "bądź", "badz", "please", "a", "bit", "little", "much",
           "speak", "talk", "more", "be", "can", "you", "volume", "turn", "it"}


def is_question(text):
    """A question about something (not a request to do it)."""
    words = [w for w in _words(text) if w not in ("luna", "luno", "hej", "a")]
    if not words:
        return False
    if words[0] in _QUESTION:
        return not (len(words) > 1 and words[1] in _POLITE)
    return False


def _bare(text, keywords):
    """True when the utterance is nothing but a command: one of `keywords`
    plus filler words."""
    words = _words(text)
    keys = {w for k in keywords for w in k.split()}
    return (any(w in keys for w in words)
            and all(w in keys or w in _FILLER for w in words))


# ── volume ────────────────────────────────────────────────────────────────────

def _sink_id():
    """wpctl wants a node id; resolve the sink Luna speaks through."""
    try:
        from openai_tts import tts
        name = tts._sink
    except Exception:
        name = None
    if name:
        try:
            dump = json.loads(subprocess.run(["pw-dump"], capture_output=True,
                                             text=True, timeout=5).stdout)
            for o in dump:
                if o.get("info", {}).get("props", {}).get("node.name") == name:
                    return str(o["id"])
        except Exception:
            pass
    return "@DEFAULT_AUDIO_SINK@"


_vol_cache = [None, 0.0]


def cached_volume():
    """Volume for the prompt: wpctl at most every 30 s (it's not free)."""
    if time.time() - _vol_cache[1] > 30:
        _vol_cache[:] = [get_volume(), time.time()]
    return _vol_cache[0]


def get_volume():
    try:
        out = subprocess.run(["wpctl", "get-volume", _sink_id()], capture_output=True,
                             text=True, timeout=5).stdout
        return float(re.search(r"([\d.]+)", out).group(1))
    except Exception:
        return None


def set_volume(v):
    v = max(VOLUME_MIN, min(VOLUME_MAX, v))
    subprocess.run(["wpctl", "set-volume", _sink_id(), f"{v:.2f}"], timeout=5)
    _vol_cache[:] = [v, time.time()]
    return v


def _volume_command(text):
    """New volume (0..1) for a volume command, or None if it isn't one."""
    low = text.lower()
    if not _short(text, 7):
        return None
    m = re.search(r"(\d{1,3})\s*(%|procent)?", low)
    if m and any(k in low for k in _VOLUME):
        return int(m.group(1)) / 100.0
    if _bare(text, _LOUDER + _QUIETER):
        cur = get_volume()
        if cur is None:
            return None
        step = VOLUME_STEP if any(k in low for k in _LOUDER) else -VOLUME_STEP
        if "dużo" in low or "duzo" in low or "much" in low:
            step *= 2
        return cur + step
    return None


# ── sleep ─────────────────────────────────────────────────────────────────────

def sleeping():
    with state.lock:
        return state.sleep_mode


def go_to_sleep():
    with state.lock:
        state.sleep_mode = True
        state.conversation_active = False
    print("[cmd] good night — sleeping until morning", flush=True)


def wake_up(why):
    with state.lock:
        if not state.sleep_mode:
            return False
        state.sleep_mode = False
    print(f"[cmd] awake ({why})", flush=True)
    return True


def _morning_watch():
    """She wakes on her own when the quiet hours end."""
    while True:
        try:
            if sleeping() and time.localtime().tm_hour == PROACTIVE_QUIET_TO:
                wake_up("morning")
        except Exception as e:
            print(f"[cmd] morning watch error: {e}")
        time.sleep(30)


# ── entry point from the voice loop ───────────────────────────────────────────

def _sound_async(name):
    from text_to_speech import play_sound_async     # only when actually used
    play_sound_async(name)


def handle(text, speak, play_sound):
    """Handle a local command. Returns True when the utterance was one (and
    must not go to the model)."""
    low = text.lower()
    question = is_question(text)

    # good night — said to her while awake
    if (any(k in low for k in _NIGHT) and not question
            and all(w in _NIGHT_OK for w in _words(text))):
        speak(random.choice(GOODNIGHT_REPLIES))
        go_to_sleep()
        return True

    # anything else said to her wakes her up, then is handled as usual
    wake_up("spoken to")

    # goodbye — wave, and stop listening right away (otherwise the window
    # stays open and she may answer the next thing said in the room)
    if tuple(w for w in _words(text) if w not in ("luna", "luno")) in _BYE:
        with state.lock:
            state.gesture_anim = "wave"
            state.gesture_anim_start = time.time()
            state.emotion = "Happy"
        speak(random.choice(GOODBYE_REPLIES))
        with state.lock:
            state.emotion = "Neutral"
            state.conversation_active = False
            state.convo_expired_time = time.time()
            state.listening = False
        print("[cmd] goodbye — conversation closed", flush=True)
        return True

    # "powtórz" / "co powiedziałaś?" — a question that IS a request: her last
    # answer again, from its audio (no new request)
    if (_bare(text, ("powtórz", "powtorz", "repeat")) or
            (any(k in low for k in _REPEAT) and _short(text, 6))):
        from text_to_speech import replay_last
        if not replay_last():
            speak("Jeszcze nic nie mówiłam.")
        return True

    # everything below acts on a request — never on a question about it
    if question:
        return False

    # "zrestartuj się" — exit; the autostart watchdog (lwrespawn) starts
    # her again a second later. Handy after editing .env.
    if any(k in low for k in _RESTART):
        speak("Dobrze, restartuję się. Zaraz wracam!")
        print("[cmd] restart requested by voice", flush=True)
        import os
        import signal
        os.kill(os.getpid(), signal.SIGTERM)    # main._shutdown does the rest
        return True

    # translator mode — "tłumacz na angielski" … "koniec tłumaczenia"
    lang = _translator_language(low)
    if lang:
        import brain
        brain.set_translator(lang[0])
        speak(f"Dobrze, tłumaczę na {lang[1]}. Powiedz „koniec tłumaczenia”, żeby skończyć.")
        return True
    if any(k in low for k in _TRANSLATE_END):
        import brain
        if brain.translator():
            brain.set_translator(None)
            speak("Koniec tłumaczenia.")
            return True

    # "jeszcze 5 minut" / "drzemka" right after an alarm or timer rang
    if any(k in low for k in _SNOOZE) and _short(text, 7):
        import timers
        secs, _ = timers.parse_duration(low)
        secs = secs or SNOOZE_MINUTES * 60
        if timers.snooze(secs):
            speak(f"Dobrze, jeszcze {timers.say_duration(secs)}.")
            return True

    # "dodaj 5 minut do minutnika" / "przedłuż minutnik o minutę"
    if any(k in low for k in _EXTEND) and ("minutnik" in low or "timer" in low
                                          or "przedłuż o" in low):
        import timers
        secs, _ = timers.parse_duration(low)
        if secs and timers.extend(secs):
            speak(f"Dodałam {timers.say_duration(secs)}.")
            return True

    # "minutnik na 10 minut" — instant, and works without the cloud
    import timers
    secs = timers.local_timer(text)
    if secs:
        timers.apply([{"type": "timer", "seconds": secs, "at": "", "label": "",
                       "repeat": "none", "list": ""}])
        speak(f"Jasne, minutnik na {timers.say_duration(secs)}.")
        return True

    # focus mode (pomodoro)
    if any(k in low for k in _FOCUS_END):
        import timers
        timers.remove({"skupienie", "przerwa"})
        with state.lock:
            state.focus_until = 0.0
        speak("Dobrze, koniec skupienia.")
        return True
    if any(k in low for k in _FOCUS) and _short(text, 9):
        import timers
        m = re.search(r"(\d{1,3})\s*(min|minut)", low)
        mins = int(m.group(1)) if m else FOCUS_MINUTES
        mins = max(5, min(120, mins))
        timers.remove({"skupienie", "przerwa"})
        timers.add(mins * 60, "skupienie",
                   say="Koniec skupienia! Czas na przerwę — wstań, rozprostuj się, napij się wody.",
                   then=(BREAK_MINUTES * 60, "przerwa",
                         "Koniec przerwy. Wracamy do pracy?"))
        with state.lock:
            state.focus_until = time.time() + mins * 60
            state.conversation_active = False
        print(f"[cmd] focus mode: {mins} min", flush=True)
        speak(f"Dobrze, {mins} minut skupienia. Będę cicho — powodzenia!")
        return True

    import breathing                               # guided breathing
    if breathing.is_trigger(low):
        breathing.run(speak, play_sound)
        return True

    import fun                                     # lamp, high five, dice, coin
    if fun.handle(text, speak, play_sound, _sound_async):
        return True

    import screens                                 # mirror, photo, clock
    if screens.handle(text, speak, _sound_async):
        return True

    import games                                   # rock, paper, scissors
    if games.is_trigger(text) or games.is_rematch(text):
        games.play_match(speak, _sound_async)
        return True

    if _bare(text, _SLOWER + _FASTER) or any(k in low for k in _NORMAL_SPEED):
        cur = settings.get("tts_speed", OPENAI_TTS_SPEED)
        if any(k in low for k in _NORMAL_SPEED):
            new = OPENAI_TTS_SPEED
        else:
            step = SPEED_STEP if any(k in low for k in _FASTER) else -SPEED_STEP
            new = round(max(SPEED_MIN, min(SPEED_MAX, cur + step)), 2)
        settings.put("tts_speed", new)
        print(f"[cmd] speech speed {cur} → {new}", flush=True)
        if new == cur:
            speak("Szybciej już nie umiem." if new >= SPEED_MAX else
                  "Wolniej już nie umiem." if new <= SPEED_MIN else "Mówię normalnie.")
        else:
            speak("Dobrze, tak mówię teraz. Może być?")
        return True

    vol = _volume_command(text)
    if vol is not None:
        v = set_volume(vol)
        print(f"[cmd] volume → {v:.0%}", flush=True)
        if not play_sound("mhm", can_drop=False):   # heard at the new level
            speak(f"Głośność {round(v * 100)} procent.")
        return True

    return False


def start_commands():
    threading.Thread(target=_morning_watch, daemon=True, name="commands").start()
