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
  bedtime  "bajka na dobranoc": a calm story, then she falls asleep
  messages "nagraj wiadomość" / "odtwórz wiadomość" / "usuń wiadomości"
  calc     "ile to jest 17 razy 23?", "ile dni do Wigilii?" (calc.py)
  length   "mów krócej" / "odpowiadaj dłużej" / "normalne odpowiedzi"
  news     "jakie są wiadomości?" — headlines from RSS, summarised (news.py)
  quiz     "przepytaj mnie z tabliczki mnożenia" (quiz.py)
  remember "zapamiętaj, że klucze są w szufladzie" (memory.add_fact)
  faces    "to jest Kasia", "jestem Andrzej", "zapomnij moją twarz" (faces.py)
  errands  "przekaż Mai, żeby posprzątała pokój" — said when she sees Maja
  spell    "jak się pisze żółw?" — on the screen and letter by letter
  count    "policz do dwudziestu", "odliczaj od dziesięciu", "włącz stoper" (counting.py)
  kids     "myjemy zęby" (2-minute coach), "zacznij poranek" (a list step by step)
  radio    "włącz radio", "włącz Trójkę", "wyłącz radio za 30 minut" (radio.py)
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
import os
import random
import re

import intent
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
# how much she says: "mów krócej" / "odpowiadaj dłużej" / "normalne odpowiedzi"
_SHORTER = ("mów krócej", "mow krocej", "odpowiadaj krócej", "odpowiadaj krocej",
            "krótsze odpowiedzi", "krotsze odpowiedzi", "krócej proszę", "za długo mówisz",
            "mówisz za długo", "gadasz za dużo", "mniej gadaj", "shorter answers")
_LONGER = ("mów dłużej", "mow dluzej", "odpowiadaj dłużej", "odpowiadaj dluzej",
           "dłuższe odpowiedzi", "dluzsze odpowiedzi", "odpowiadaj szerzej",
           "mów więcej szczegółów", "longer answers")
_NORMAL_LENGTH = ("normalne odpowiedzi", "normalna długość", "odpowiadaj normalnie",
                  "zwykłe odpowiedzi")
_NORMAL_SPEED = ("normalnym tempie", "normalne tempo", "normalnie mów", "mów normalnie")
# goodbyes: the whole utterance must be one of these (after dropping "Luna")
# — "na razie nie" or "pa, a jeszcze jedno…" are not goodbyes
_BYE = {("pa",), ("pa", "pa"), ("papa",), ("do", "widzenia"), ("do", "zobaczenia"),
        ("na", "razie"), ("bye",), ("bye", "bye"), ("see", "you"), ("cześć", "pa"),
        ("to", "wszystko"), ("dzięki", "to", "wszystko"), ("dziękuję", "to", "wszystko"),
        ("dobra", "to", "wszystko"), ("trzymaj", "się"), ("na", "razie", "wszystko"),
        ("to", "na", "razie", "wszystko"), ("to", "na", "razie"), ("to", "by", "było", "na", "tyle"),
        ("to", "by", "było", "wszystko"), ("na", "tyle"), ("koniec", "rozmowy"),
        ("do", "usłyszenia"), ("do", "później"), ("na", "razie", "dzięki")}
# what may come before a goodbye: "super, to na razie wszystko", "dobra, pa"
_BYE_LEAD = {"super", "dobra", "dobrze", "ok", "okej", "okay", "dzięki", "dziękuję",
             "dzieki", "dziekuje", "no", "świetnie", "fajnie", "a", "to", "spoko", "wielkie",
             "bardzo", "ekstra", "dobre"}
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
            "idziemy spać", "idziemy spac", "pora spać", "pora spac", "czas spać",
            "czas spac", "lecę spać", "lece spac", "kładę się spać", "kładziemy się spać",
            "good night", "goodnight")
# "dobranoc" must be the whole point of the utterance — "powiedz dobranoc mojej
# córce" or "co było na dobranockę?" are not her bedtime
_NIGHT_OK = {"dobranoc", "luna", "luno", "idę", "ide", "spać", "spac", "już", "juz",
             "to", "ja", "no", "dobra", "dzięki", "dziękuję", "kochana", "pa", "papa",
             "i", "good", "night", "goodnight", "słodkich", "snów", "kolorowych",
             "idziemy", "pora", "czas", "lecę", "lece", "teraz", "my", "tutaj", "tu",
             "chyba", "więc", "wiec", "kładę", "kładziemy", "się", "na", "mnie", "nas",
             "super", "dobrze", "okej", "ok", "a"}


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
_CAPTIONS_ON  = ("włącz napisy", "wlacz napisy", "pokazuj napisy", "captions on")
_CAPTIONS_OFF = ("wyłącz napisy", "wylacz napisy", "bez napisów", "captions off")
_MSG_RECORD = ("nagraj wiadomość", "nagraj wiadomosc", "zostaw wiadomość",
               "nagraj notatkę", "nagraj mi wiadomość", "chcę zostawić wiadomość",
               "record a message")
_MSG_PLAY   = ("odtwórz wiadomość", "odtwórz wiadomości", "odtworz wiadomosc",
               "jakie mam wiadomości", "mam jakieś wiadomości", "puść wiadomość",
               "posłuchaj wiadomości", "play the message", "any messages")
_MSG_DELETE = ("usuń wiadomości", "usuń wiadomość", "skasuj wiadomości", "usun wiadomosci",
               "usuń wszystkie wiadomości", "skasuj wszystkie wiadomości",
               "usun wszystkie wiadomosci")
# "pogoda dla Krakowa", "ustaw pogodę na Gdańsk", "mieszkam w Zakopanem"
# ("pogoda w Berlinie?" is a question, not where you live — it goes to the model)
_WEATHER_SET = re.compile(r"^(?:luna,? |luno,? )?(?:(?:włącz|wlacz|ustaw|sprawdzaj) )"
                          r"(?:pogod[aęy]|prognoz[aęy])(?: pogody)? (?:dla|w|na) \w|"
                          r"^(?:luna,? |luno,? )?(?:pogod[aęy]|prognoz[aęy]) dla \w|"
                          r"^(?:luna,? |luno,? )?(?:mieszkam|mieszkamy) (?:w|we|na) \w")
_WEATHER_ELSEWHERE = re.compile(r"\b(?:pogod\w*|prognoz\w*|temperatur\w*|ciepło|zimno|"
                                r"pada|deszcz\w*|śnieg\w*)\b.*\b(?:w|we|na)\s+[A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż]{3,}",
                                re.I)
_WEATHER_OFF = ("wyłącz pogodę", "wylacz pogode", "nie sprawdzaj pogody")
_MIC_OFF = ("nie słuchaj", "nie sluchaj", "przestań słuchać", "przestan sluchac",
            "wyłącz mikrofon", "wylacz mikrofon", "nie podsłuchuj", "nie podsluchuj",
            "wycisz mikrofon", "stop listening")
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


_REMEMBER = re.compile(r"^(?:luna,? |luno,? |hej,? )?(?:proszę,? )?(?:zapamiętaj|zapamietaj|"
                       r"zanotuj|zapisz|pamiętaj|pamietaj|remember)(?: sobie)?(?: proszę)?"
                       r",? (?:że|ze|to,? że|to ze|that) (.+)$", re.I)


# getting to know a face: "to jest Kasia", "poznaj Olę", "jestem Andrzej",
# "mam na imię Ola", "zapamiętaj moją twarz, jestem Kasia". The name must be
# capitalised as the cloud writes names — "to jest problem" is no one.
_NAME = r"([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]{1,15})"
# (?i:…): the lead words in any case ("Jestem", "Poznaj"), the name capitalised
_INTRO = [re.compile(r"^(?i:(?:a\s+)?(?:to jest|to|poznaj|przedstawiam ci|oto))\s+"
                     + _NAME + r"[.!]?$"),
          re.compile(r"^(?i:(?:a\s+)?(?:ja\s+)?(?:jestem|mam na imię|mam na imie|nazywam się))\s+"
                     + _NAME + r"(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ]\w+)?[.!]?$"),
          re.compile(r"(?:zapamiętaj|zapamietaj|naucz się|poznaj)\s+(?:moją\s+|moja\s+)?twarz\w*"
                     r"[,.]?\s+(?:jestem|mam na imię|nazywam się|to)\s+" + _NAME, re.I)]
_FACE_BARE = ("zapamiętaj moją twarz", "zapamietaj moja twarz", "naucz się mojej twarzy",
              "zapamiętaj mnie", "zapamiętaj jak wyglądam")
_FACE_FORGET = re.compile(r"zapomnij\s+(?:moją\s+twarz|mnie|twarz\s+(\w+))", re.I)
_NOT_NAMES = {"Luna", "Luno", "Polak", "Polką", "Tak", "Nie", "Ok", "Okej", "Dobrze", "Super",
              "Gotowy", "Gotowa", "Głodny", "Zmęczony", "Zmęczona", "Tutaj", "Tu", "Ja",
              # one-word replies that are not names (after "jak masz na imię?")
              "Cześć", "Hej", "Hejka", "Siema", "Witaj", "Halo", "Dzięki", "Dziękuję",
              "Ciszej", "Głośniej", "Stop", "Nic", "Co", "Pa", "Dobranoc", "Później",
              "Spadaj", "Słucham", "Jasne", "Proszę", "Przepraszam", "Nikt", "Zgadnij"}


def _intro_name(text):
    """The name in an introduction, as said ("Kasię"), or None."""
    t = re.sub(r"^(?:luna|luno|hej)[,!]?\s+", "", text.strip(), flags=re.I).strip()
    for rx in _INTRO:
        m = rx.search(t)
        if m and m.group(1) not in _NOT_NAMES:
            return m.group(1)
    return None


def _learn_face(name_as_said, text, speak):
    """Collect the face in view for a few seconds and remember it."""
    import faces
    if not faces.can_recognise():
        speak("Nie mam jeszcze modelu do rozpoznawania twarzy.")
        return True
    name = faces.nominative(name_as_said)
    done = faces.start_enrolment(name)
    speak("Dobrze, popatrz na mnie przez chwilę.")
    done.wait(faces.ENROLL_SECS + 4)
    status, name = faces.enrolment_result()
    if status == "many":
        speak("Widzę kilka osób naraz. Niech przede mną zostanie tylko jedna i powtórz.")
        return True
    if status != "ok":
        speak("Nie widzę dobrze twarzy. Stań przodem do mnie, blisko, i powtórz.")
        return True
    with state.lock:
        state.person = (name, 1.0, time.time())
    if not faces.vocatives().get(name):          # "Ola" -> "Olu", for greetings
        faces.set_vocative(name, faces.vocative_of(name))
    import brain
    brain.process(text, context=(f"\nYou have just learned to recognise {name}'s face "
                                 f"(they introduced themselves or were introduced). Greet "
                                 f"{name} warmly by name — the Polish vocative — in one or "
                                 "two sentences; say you will recognise them from now on.\n"))
    return "recorded"


_name_wanted = [0.0]        # until when a bare name ("Ola.") answers "jak masz na imię?"


_place_wanted = [0.0]          # she asked "w jakim mieście mieszkamy?" until then
_WEATHER_ASK = re.compile(r"\b(?:pogod\w*|temperatur\w*|ile\s+stopni|czy\s+(?:będzie\s+)?pada|"
                          r"jak\s+jest\s+na\s+(?:dworze|zewnątrz|polu)|parasol)\b", re.I)


def weather_setup(text, speak):
    """No weather place yet: a weather question gets "w jakim mieście
    mieszkamy?", and the answer ("w Krakowie", "Kraków") switches it on — no
    phrase to learn (5 Oct: "Ale dziś zimno" → "nie mogę sprawdzić")."""
    import weather
    low = text.lower().strip(" .!?")
    if time.time() < _place_wanted[0]:
        _place_wanted[0] = 0.0
        place = re.sub(r"^(?:luna,?\s+)?(?:mieszkamy\s+|mieszkam\s+|jesteśmy\s+)?(?:w|we|na)?\s*",
                       "", low)
        # only an answer that looks like a place — "zrób mi zdjęcie" was taken
        # for a town; a place that isn't found lets the sentence go on as usual
        if place and len(place.split()) <= 3 and not re.search(
                r"\b(?:zrób|zrob|włącz|wlacz|wyłącz|pokaż|pokaz|nie|nastaw|ile|co|jak)\b", place):
            name = weather.set_place(f"pogoda dla {place}")
            if name:
                speak(f"Dzięki! Od teraz znam pogodę dla: {name}.")
                return True
    if (weather.enabled() or not _WEATHER_ASK.search(low) or len(low.split()) > 9
            or _WEATHER_SET.search(low)):
        return False                       # "pogoda dla Krakowa" sets it directly
    if re.search(r"\b(?:w|we|na)\s+[A-ZĄĆĘŁŃÓŚŹŻ]", text):
        return False                       # "pogoda w Berlinie": that one place (model)
    _place_wanted[0] = time.time() + 25
    with state.lock:                       # the answer needs no "Luna"
        state.conversation_active = True
        state.last_activity_time = time.time() + 8
    speak("Nie wiem jeszcze, gdzie mieszkamy. W jakim mieście? Powiedz tylko nazwę.")
    return True


def expect_name(secs=20):
    _name_wanted[0] = time.time() + secs


def _bare_name(text):
    """"Ola." / "Ola!" / "Luna, Ola" right after she asked — the name, else None."""
    if time.time() > _name_wanted[0]:
        return None
    t = re.sub(r"^(?:luna|luno)[,!]?\s+", "", text.strip(), flags=re.I).strip(" .!")
    if re.fullmatch(_NAME, t) and t not in _NOT_NAMES:
        _name_wanted[0] = 0.0
        return t
    return None


def _goodnight():
    """"Dobranoc, Maju! Kolorowych snów." — by name when she knows the face."""
    with state.lock:
        who = state.person[0] if state.person else None
    if not who:
        return random.choice(GOODNIGHT_REPLIES)
    import faces
    voc = faces.vocatives().get(who) or who
    return random.choice((f"Dobranoc, {voc}! Kolorowych snów.",
                          f"Dobranoc, {voc}. Śpij dobrze!",
                          f"Słodkich snów, {voc}! Do jutra."))


_ALARM = re.compile(r"\b(?:obudź|obudz|zbudź|zbudz|budź|budz|budzik|budzenie)\b(?:\s+\w+){0,3}?"
                    r"\s+(?:o|na)\s+(.+?)[.!?]*$", re.I)


def local_alarm(text):
    """("HH:MM", repeat) for "obudź mnie o 6:30", "budzik na wpół do ósmej w dni
    robocze" — set here, so an alarm works without the internet. None else."""
    import clockgame
    low = text.lower()
    m = _ALARM.search(low)
    if not m or is_question(text) or "za " in f" {low} ":   # "za 20 minut": a timer
        return None
    when = m.group(1)
    when = re.sub(r"\b(codziennie|w dni robocze|w tygodniu|od poniedziałku do piątku|"
                  r"w weekendy?|w soboty i niedziele|jutro|rano|proszę|prosze)\b", " ", when)
    if len(when.split()) > 4:
        return None
    t = clockgame.parse(when)
    if t is None:
        return None
    h, mi = t
    repeat = ("daily" if "codziennie" in low else
              "weekdays" if re.search(r"dni robocze|w tygodniu|od poniedziałku", low) else
              "weekends" if re.search(r"weekend|soboty i niedziele", low) else "none")
    return f"{h:02d}:{mi:02d}", repeat


_WHERE = re.compile(r"\b(?:gdzie\s+(?:jest|się\s+podziała?|podziała?\s+się)\s+|"
                    r"(?:kiedy\s+)?(?:ostatnio\s+)?widziała[sś]\s+(?:dziś\s+|dzisiaj\s+|"
                    r"ostatnio\s+)?|czy\s+(?:był[aoy]?|przyszedł|przyszła)\s+(?:już\s+)?)"
                    r"(\w+)", re.I)
_ABOUT = re.compile(r"\bco\s+(?:(?:wiesz|pamiętasz|pamietasz)\s+o\s+(\w+)|"
                    r"o\s+(\w+)\s+(?:wiesz|pamiętasz|pamietasz))\b", re.I)
_FORGET_THAT = re.compile(r"\bzapomnij,?\s+(?:o\s+tym,?\s+)?(?:że|ze)\s+(.+)", re.I)


def _memory_talk(text):
    """What she remembers about someone, or one fact forgotten — the reply,
    or None when the words aren't about her memory."""
    import faces
    import memory
    low = text.lower()
    with state.lock:
        me = state.person[0] if state.person else None
    m = _FORGET_THAT.search(text)
    if m and not re.search(r"\bnie\s+zapomnij", low) and _short(text, 14):
        among = memory.facts_about(me) if me and _child_here() else None   # a child: hers only
        gone = memory.forget_fact(m.group(1), among)
        return (f"Dobrze, zapomniałam: {gone.rstrip('.')}." if gone else
                "Nie mam tego zapisanego.")
    m = _ABOUT.search(text)
    if not m or not _short(text, 8):
        return None
    word = (m.group(1) or m.group(2)).lower()
    if word in ("mnie", "nas"):
        who = me
        if not who:
            return "Nie poznaję cię teraz — stań przed kamerą albo powiedz: jestem…"
    else:
        who = faces.match_name(word)
        if not who:
            return None                    # "co wiesz o dinozaurach?" — the model
        if _child_here() and who != me:
            return "O innych opowiem dorosłym. Mogę ci powiedzieć, co wiem o tobie!"
    facts = memory.facts_about(who)
    if not facts:
        return ("Jeszcze niczego o tobie nie zapisałam." if who == me else
                f"Nie mam nic zapisanego o: {who}.")
    head = "O tobie pamiętam" if who == me else f"O: {who} pamiętam"
    said = f"{head}: " + " ".join(f.rstrip(".") + "." for f in facts[:5])
    if len(facts) > 5:
        said += f" I jeszcze {len(facts) - 5} innych rzeczy."
    return said + " Jeśli coś się nie zgadza, powiedz: zapomnij, że…"


_CONTINUE = re.compile(r"\b(?:dalszy\s+ciąg|dalszy\s+ciag|ciąg\s+dalszy|ciag\s+dalszy|"
                       r"co\s+było\s+dalej|co\s+bylo\s+dalej|opowiedz\s+dalej|"
                       r"kontynuuj|następną\s+część|nastepna\s+czesc|następna\s+część)\b", re.I)


def _story_path():
    from config import DATA_DIR
    return os.path.join(DATA_DIR, "story.json")


def last_story(max_days=14):
    """The last bedtime story told (text), if not older than max_days."""
    import json
    try:
        with open(_story_path(), encoding="utf-8") as f:
            s = json.load(f)
        if time.time() - s.get("t", 0) > max_days * 86400:
            return None
        return s.get("text") or None
    except (OSError, ValueError):
        return None


def _save_story(text):
    import json
    try:
        tmp = _story_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"t": time.time(), "text": text}, f, ensure_ascii=False)
        os.replace(tmp, _story_path())
    except OSError as e:
        print(f"[cmd] story not saved ({e})", flush=True)


def _tell_story(prompt, bedtime):
    """A story through the model; it is kept, so "dalszy ciąg" can follow."""
    import brain
    if bedtime:
        with state.lock:
            state.voice_mood = "sleepy"          # a lullaby voice, not a cheerful one
    try:
        brain.process(prompt)
        hist = getattr(brain, "_history", None) or []
        last = hist[-1] if hist else {}
        if last.get("role") == "assistant" and len(last.get("content", "")) > 120:
            _save_story(last["content"])
    finally:
        if bedtime:
            with state.lock:
                state.voice_mood = None
    if bedtime:
        go_to_sleep()


def _child_here():
    """Is the recognised person marked as a child (faces.py notes)?"""
    try:
        import faces
        with state.lock:
            who = state.person[0] if state.person else None
        return bool(who) and "dziecko" in faces.notes().get(who, "").lower()
    except Exception:
        return False


def _remember(text):
    """"Zapamiętaj, że klucze są w szufladzie" → "klucze są w szufladzie"."""
    m = _REMEMBER.match(text.strip())
    if not m:
        return None
    fact = m.group(1).strip(" .!")
    return fact if len(_words(fact)) >= 2 else None


_SPELL = re.compile(r"(?:jak (?:się |sie )?(?:pisze|piszę|napisać|napisac|literuje)|"
                    r"przeliteruj|literuj|spell)(?: (?:się|sie))?(?: słowo| wyraz| word)?"
                    r"[ ,:]+[„\"']?([\w\- ]+?)[”\"']?[?.!]*$", re.I)
_LETTERS = {"a": "a", "ą": "a z ogonkiem", "b": "be", "c": "ce", "ć": "ce z kreską",
            "d": "de", "e": "e", "ę": "e z ogonkiem", "f": "ef", "g": "gie", "h": "ha",
            "i": "i", "j": "jot", "k": "ka", "l": "el", "ł": "eł", "m": "em", "n": "en",
            "ń": "en z kreską", "o": "o", "ó": "o z kreską", "p": "pe", "q": "ku",
            "r": "er", "s": "es", "ś": "es z kreską", "t": "te", "u": "u otwarte",
            "v": "fau", "w": "wu", "x": "iks", "y": "igrek", "z": "zet",
            "ź": "zet z kreską", "ż": "zet z kropką"}


def _spell_word(text):
    """"Jak się pisze żółw?" → "żółw" (one to three words), else None."""
    m = _SPELL.search(text.strip())
    if not m:
        return None
    word = m.group(1).strip(" -")
    if (not word or len(_words(word)) > 3 or any(c.isdigit() for c in word)
            or re.search(r"\bpo \w+sku\b|\bin \w+", word.lower())):   # translation
        return None
    return word


def _spell(word, speak):
    """The word big on her screen, then letter by letter."""
    with state.lock:
        state.overlay = ("card", time.time() + 15, {"text": word, "sub": "", "tone": None})
    letters = [c for c in word.lower() if c.isalpha()]
    names = ", ".join(_LETTERS.get(c, c) for c in letters)
    tricky = [t for t in ("ó", "rz", "ż", "ch", "h", "u") if t in word.lower()]
    tip = ""
    if "ó" in tricky:
        tip = " Uwaga, przez o z kreską!"
    elif "rz" in tricky:
        tip = " Uwaga: rz, czyli er i zet."
    elif "ż" in tricky:
        tip = " Uwaga, przez zet z kropką!"
    elif "ch" in tricky:
        tip = " Uwaga: ch, czyli ce i ha."
    print(f"[cmd] spell: {word}", flush=True)
    speak(f"{word}: {names}.{tip}")


def _is_goodbye(text):
    """The whole utterance is a goodbye, perhaps after "super," / "dobra,"."""
    words = [w for w in _words(text) if w not in ("luna", "luno")]
    while words and tuple(words) not in _BYE and words[0] in _BYE_LEAD:
        words = words[1:]
    return tuple(words) in _BYE


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


# "Czy możesz włączyć lampkę?" is a request: as "włącz lampkę" it reaches the
# command it means (the model can't switch her lamp on — it would only say so)
_IMPERATIVE = {
    "włączyć": "włącz", "wlaczyc": "włącz", "wyłączyć": "wyłącz", "wylaczyc": "wyłącz",
    "nastawić": "nastaw", "ustawić": "ustaw", "przypomnieć": "przypomnij",
    "obudzić": "obudź", "zrobić": "zrób", "pokazać": "pokaż", "wylosować": "wylosuj",
    "policzyć": "policz", "przywrócić": "przywróć", "zagrać": "zagraj", "puścić": "puść",
    "zgasić": "zgaś", "rzucić": "rzuć", "opowiedzieć": "opowiedz", "przeczytać": "przeczytaj",
    "powtórzyć": "powtórz", "wybrać": "wybierz", "zapamiętać": "zapamiętaj",
    "zapomnieć": "zapomnij", "dodać": "dodaj", "dopisać": "dopisz", "skreślić": "skreśl",
    "usunąć": "usuń", "nagrać": "nagraj", "odtworzyć": "odtwórz", "zatrzymać": "zatrzymaj",
    "mówić": "mów", "zmienić": "zmień", "przełączyć": "przełącz", "ściszyć": "ścisz",
    "przestać": "przestań", "przepytać": "przepytaj", "zadać": "zadaj", "odliczyć": "odliczaj",
    "uruchomić": "uruchom", "zmniejszyć": "zmniejsz", "zwiększyć": "zwiększ",
}
_POLITE_ASK = re.compile(r"^(?:luna,?\s+|hej,?\s+)*(?:czy\s+)?(?:możesz|mozesz|mogłabyś|"
                         r"moglabys|mogłabys)\s+(?:proszę\s+|prosze\s+)?((?:mi\s+|nam\s+)?)"
                         r"(\w+)(.*?)[?.!]*$", re.I)


# "Włączysz lampkę?", "nastawisz minutnik na 5 minut?" — a request too
_FUTURE = {"włączysz": "włącz", "wyłączysz": "wyłącz", "nastawisz": "nastaw",
           "ustawisz": "ustaw", "przypomnisz": "przypomnij", "obudzisz": "obudź",
           "zrobisz": "zrób", "pokażesz": "pokaż", "zagrasz": "zagraj", "puścisz": "puść",
           "policzysz": "policz", "wylosujesz": "wylosuj", "opowiesz": "opowiedz",
           "przeczytasz": "przeczytaj", "zgasisz": "zgaś", "rzucisz": "rzuć",
           "powtórzysz": "powtórz", "dopiszesz": "dopisz", "zapamiętasz": "zapamiętaj",
           "przywrócisz": "przywróć", "nagrasz": "nagraj", "odtworzysz": "odtwórz",
           "zatrzymasz": "zatrzymaj", "zmienisz": "zmień", "ściszysz": "ścisz",
           "przepytasz": "przepytaj", "zadasz": "zadaj"}
_FUTURE_ASK = re.compile(r"^(?:luna,?\s+|hej,?\s+)*(?:a\s+)?(\w+)(.*?)[?.!]*$", re.I)


_FILLER_LEAD = re.compile(r"^(?:(?:luna|luno|hej|ej|no|to|a|teraz|dobra|dobrze|okej|ok|"
                          r"słuchaj|sluchaj|proszę|prosze|dzięki|dzieki|więc|wiec)\b[\s,]*)+",
                          re.I)
_COMMAND_VERBS = set(_IMPERATIVE.values()) | {
    "zagrajmy", "pobawmy", "zróbmy", "zrobmy", "przepytaj", "nastaw", "wlacz", "wylacz",
    "minutnik", "budzik", "stoper", "ciszej", "głośniej", "glosniej", "pokaz"}


def polite_to_command(text):
    """"Czy możesz włączyć lampkę?" / "włączysz lampkę?" → "włącz lampkę";
    None when it isn't a polite request with a verb we know."""
    m = _POLITE_ASK.match(text.strip())
    if not m:
        f = _FUTURE_ASK.match(text.strip())
        verb = _FUTURE.get(f.group(1).lower()) if f else None
        if verb:
            return f"{verb} {f.group(2).strip()}".strip()
        # "no to nastaw minutnik…", "Luna, a teraz włącz radio": the filler goes,
        # but only before a command verb ("to jest Kasia" stays as it is)
        rest = _FILLER_LEAD.sub("", text.strip())
        first = rest.split()[0].lower().strip(",.") if rest.split() else ""
        if rest != text.strip() and first in _COMMAND_VERBS:
            return rest
        return None
    verb = _IMPERATIVE.get(m.group(2).lower())
    if not verb:
        return None
    return f"{verb} {m.group(1)}{m.group(3).strip()}".strip()


_COMPLAINTS = [
    (r"\b(?:za\s+wolno|zbyt\s+wolno)\b", "mów szybciej"),
    (r"\b(?:za\s+szybko|zbyt\s+szybko)\b", "mów wolniej"),
    (r"\b(?:za\s+cicho|zbyt\s+cicho|nie\s+słychać\s+cię|nie\s+slychac\s+cie|słabo\s+cię\s+słychać|"
     r"nic\s+nie\s+słyszę|nic\s+nie\s+slysze)\b", "głośniej"),
    (r"\b(?:za\s+głośno|za\s+glosno|zbyt\s+głośno)\b", "ciszej"),
]


def _complaint_as_command(low):
    """"Za wolno mówisz", "nie słychać cię" — a complaint that asks for
    something; the model only answered "mogę mówić szybciej" and changed
    nothing. The command it means, or None."""
    n = len(re.findall(r"\w+", low))
    if n > 6 or re.search(r"\b(radio|muzyk|telewiz|tv)\w*", low):
        return None
    if n > 3 and not re.search(r"\b(mówisz|mowisz|gadasz|cię|cie|ciebie|twój\s+głos|twoj\s+glos)\b",
                               low):
        return None                        # "minutnik dzwoni za głośno" is not about her
    return next((cmd for rx, cmd in _COMPLAINTS if re.search(rx, low)), None)


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
    import radio
    radio.stop_for_the_night()
    with state.lock:
        state.sleep_mode = True
        state.conversation_active = False
        state.convo_closed_hard = True
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


def handle(text, speak, play_sound, _polite=True):
    """Handle a local command. Returns True when the utterance was one (and
    must not go to the model)."""
    if _polite:
        cmd = polite_to_command(text)
        if cmd:
            handled = handle(cmd, speak, play_sound, _polite=False)
            if handled:
                print(f"[cmd] polite request → \"{cmd}\"", flush=True)
                return handled
    low = text.lower()
    said_as = _complaint_as_command(low)           # "za wolno mówisz" → "szybciej"
    if said_as and _polite:
        return handle(said_as, speak, play_sound, _polite=False)
    question = is_question(text)

    # good night — said to her while awake
    if (any(k in low for k in _NIGHT) and not question
            and all(w in _NIGHT_OK for w in _words(text))):
        import timers
        note = timers.goodnight_note()
        speak(_goodnight() + (" " + note if note else ""))
        go_to_sleep()
        return True

    # anything else said to her wakes her up, then is handled as usual
    wake_up("spoken to")

    # "Luna, nie słuchaj" — privacy: the microphone is off (a finger held on
    # the screen turns it back on; she can't hear "słuchaj" any more)
    if any(k in low for k in _MIC_OFF) and _short(text, 8) and not question:
        import timers
        secs, _ = timers.parse_duration(low)
        secs = secs or 3600
        speak(f"Dobrze, nie słucham przez {timers.say_duration(secs)}. Żeby mnie "
              "obudzić, przytrzymaj palec na ekranie.")
        with state.lock:
            state.mic_muted_until = time.time() + secs
            state.conversation_active = False
        print(f"[cmd] microphone off for {secs} s", flush=True)
        return True

    # a maths quiz is on: this utterance is probably the answer
    import quiz
    if quiz.active() and quiz.answer(text, speak, _sound_async):
        return True
    import kids                                    # a routine step: "gotowe"
    if kids.routine_active() and kids.routine_answer(text, speak, _sound_async):
        return True
    import cooking                                 # a recipe step: "dalej"
    if cooking.active() and cooking.answer(text, speak):
        return True
    import twenty                                  # "czy ma futro?"
    if twenty.active() and twenty.answer(text, speak):
        return True

    # goodbye — wave, and stop listening right away (otherwise the window
    # stays open and she may answer the next thing said in the room)
    if _is_goodbye(text):
        with state.lock:
            state.gesture_anim = "wave"
            state.gesture_anim_start = time.time()
            state.emotion = "Happy"
        speak(random.choice(GOODBYE_REPLIES))
        with state.lock:
            state.emotion = "Neutral"
            state.conversation_active = False
            state.convo_expired_time = time.time()
            state.convo_closed_hard = True
            state.listening = False
        print("[cmd] goodbye — conversation closed", flush=True)
        return True

    # "powtórz" / "co powiedziałaś?" — a question that IS a request: her last
    # answer again, from its audio (no new request)
    hit = next((k for k in _REPEAT if k in low), None)
    after = re.findall(r"\w+", low.split(hit, 1)[1]) if hit else []
    if (_bare(text, ("powtórz", "powtorz", "repeat")) or
            (hit and _short(text, 6)
             and all(w in ("teraz", "przed", "chwilą", "chwila", "właśnie", "wlasnie", "luna")
                     for w in after))):            # not "co mówiłaś o planetach"
        from text_to_speech import replay_last
        if not replay_last():
            speak("Jeszcze nic nie mówiłam.")
        return True

    # voice messages — "nagraj wiadomość", "odtwórz wiadomość", "usuń wiadomości"
    import messages
    if any(k in low for k in _MSG_RECORD) and _short(text, 8):
        to = None
        m = re.search(r"\bdla\s+(\w+)", text)
        if m:                                       # "…dla Emilki" → Emilka
            import faces
            to = faces.match_name(m.group(1))       # "dla Mai" → Maja, locally
            if not to:                              # someone she doesn't know
                to = faces.nominative(m.group(1))
        messages.arm(to)
        with state.lock:
            state.conversation_active = True
            state.last_activity_time = time.time()
        speak("Dobrze, nagrywam. Mów teraz.")
        return True
    if any(k in low for k in _MSG_PLAY) and _short(text, 8):
        from text_to_speech import play_clip
        if not messages.play(speak, play_clip):
            speak("Nie ma żadnych wiadomości.")
        return True
    if any(k in low for k in _MSG_DELETE) and _short(text, 6):
        # a child deletes only what was heard: unheard ones may be for her parents
        gone, kept = messages.delete(everything="wszystk" in low and not _child_here())
        said = "Usunęłam wiadomości." if gone else "Nie ma odsłuchanych wiadomości."
        if kept:                                    # left for someone, not heard yet
            to = sorted({m["to"] for m in kept if m.get("to")})
            whom = f" dla: {', '.join(to)}" if to else ""
            said += (f" Nieodsłuchane{whom} zostawiłam — żeby je usunąć, "
                     "powiedz: usuń wszystkie wiadomości.")
        speak(said)
        return True

    # "która godzina?" / "jaki dziś dzień?" — answered at once, locally
    import clock
    said = clock.answer(text)
    if said:
        speak(said)
        return True

    # "jak się pisze żółw?" — a question, but one she answers on the screen
    word = _spell_word(text)
    if word:
        _spell(word, speak)
        return True

    if weather_setup(text, speak):                 # first weather question: where?
        return True

    # "pogoda dla Krakowa" / "mieszkam w Gdańsku" — switch the forecast on
    if _WEATHER_SET.search(low) and _short(text, 8):
        import weather
        try:
            name = weather.set_place(text)
        except Exception as e:
            print(f"[cmd] weather place failed: {e}", flush=True)
            name = None
        speak(f"Dobrze, sprawdzam pogodę dla miejscowości {name}." if name
              else "Nie znalazłam tej miejscowości. Powiedz na przykład: pogoda dla Krakowa.")
        return True
    if any(k in low for k in _WEATHER_OFF) and _short(text, 5):
        import weather
        weather.forget_place()
        speak("Dobrze, nie sprawdzam już pogody.")
        return True

    # "jaka jest pogoda w Berlinie?" — that place's forecast, for this question
    if _WEATHER_ELSEWHERE.search(low) and _short(text, 10):
        import weather
        try:
            ctx = weather.forecast_for(text)
        except Exception as e:
            print(f"[cmd] one-off forecast failed: {e}", flush=True)
            ctx = None
        if ctx:
            import brain
            brain.process(text, context=ctx)
            return "recorded"

    # "jakie są wiadomości?" — real headlines (RSS) for the model to summarise;
    # without them she used to make news up
    import news
    if news.is_request(text):
        import brain
        ctx = news.context()
        if ctx is None:
            speak("Nie mogę teraz pobrać wiadomości — nie mam połączenia z internetem.")
        else:
            brain.process(text, context=ctx)
        return "recorded"

    # birthdays: "Maja ma urodziny 12 maja" / "ile dni do urodzin Mai?"
    import birthdays
    said = (birthdays.days_answer(text) or birthdays.nameday_answer(text)
            or birthdays.age_answer(text) or birthdays.days_alive(text))
    if said:
        speak(said)
        return True
    got = birthdays.set_nameday_from(text)          # "Maja ma imieniny 3 maja"
    if got:
        m, d = (int(x) for x in got[1].split("-"))
        import calc
        speak(f"Zapamiętałam: {got[0]} ma imieniny {d} {calc._MONTHS_GEN[m - 1]}.")
        return True
    got = birthdays.set_from(text)
    if got:
        name, md, year = got
        m, d = (int(x) for x in md.split("-"))
        import calc
        speak(f"Zapamiętałam: {name}, {d} {calc._MONTHS_GEN[m - 1]}"
              + (f" {year}" if year else "") + ".")
        return True

    # "jaki jest plan na dziś?" — a question, answered on the screen
    import screens
    if screens.wants_today(text):
        screens.show_today(speak)
        return True

    # "ile to jest 17 razy 23?" / "ile dni do Wigilii?" — counted locally
    import calc
    said = calc.answer(text)
    if said and calc.arithmetic(text) and _child_here():
        said = None        # homework: for a child the model hints instead of answering
    if said:
        print(f"[cmd] calc: {said}", flush=True)
        speak(said)
        return True

    # questions she answers herself, exactly (they must come before the guard)
    import timers
    said = timers.left_answer(text)                # "ile zostało na minutniku?"
    if not said:
        m = _WHERE.search(text)                    # "gdzie jest Maja?"
        if m and _short(text, 8):
            import faces
            who = faces.match_name(m.group(1))
            said = faces.where_is(who) if who else None
    if not said:
        said = _memory_talk(text)                  # "co o mnie wiesz?", "zapomnij, że…"
    if not said:
        import memory
        said = memory.where_is_thing(text)         # "gdzie są klucze?" — as noted
    if not said:
        import lists
        said = lists.read_answer(text)             # "co mam na liście zakupów?"
    if not said:
        import fun
        said = fun.random_answer(text)             # "kto zmywa: Maja czy tata?"
    if said:
        speak(said)
        return True
    if re.search(r"\b(?:moje|moich|ile mam)\s+gwiazd|\bpokaż\s+gwiazdki\b", low) \
            and _short(text, 6):
        import quiz
        quiz.show_stars(speak)                     # "pokaż moje gwiazdki", "ile mam…?"
        return True
    import radio
    if radio.answer_question(text, speak):         # "jakie to radio?", "co teraz gra?"
        return True
    import counting
    if counting.ask_stopwatch(text, speak):        # "ile na stoperze?"
        return True

    # everything below acts on a request — never on a question about it
    if question:
        return False

    with state.lock:
        online = state.online
    if not online:                                 # the model can't do it now:
        import lists                               # "dopisz mleko do listy" here
        said = lists.local_add(text)
        if said:
            speak(said)
            return True

    # "zrestartuj się" — exit; the autostart watchdog (lwrespawn) starts
    # her again a second later. Handy after editing .env.
    if any(k in low for k in _RESTART):
        speak("Dobrze, restartuję się. Zaraz wracam!")
        print("[cmd] restart requested by voice", flush=True)
        import os
        import signal
        os.kill(os.getpid(), signal.SIGTERM)    # main._shutdown does the rest
        return True

    # subtitles — "włącz napisy" / "wyłącz napisy"
    if _bare(text, _CAPTIONS_ON + _CAPTIONS_OFF):
        on = any(k in low for k in ("włącz", "wlacz", "pokazuj", "on"))
        settings.put("captions", on)
        speak("Dobrze, włączam napisy." if on else "Dobrze, wyłączam napisy.")
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

    # "opowiedz dalszy ciąg bajki" — last night's story goes on
    if _CONTINUE.search(low) and any(k in low for k in ("bajk", "historyjk", "opowieś",
                                                         "opowies")) and _short(text, 10):
        story = last_story()
        if not story:
            speak("Nie pamiętam żadnej bajki do kontynuowania. Mogę opowiedzieć nową!")
            return True
        bedtime = "dobranoc" in low or time.localtime().tm_hour >= 19
        _tell_story("Opowiedz dalszy ciąg tej bajki — te same postacie, co dalej się "
                    f"wydarzyło (około 8 zdań). Poprzednia część: «{story[:1200]}»"
                    + (" Spokojnie i sennie, zakończ życzeniem dobrej nocy." if bedtime else ""),
                    bedtime)
        return "recorded"

    # "bajka na dobranoc" — a calm story, then she falls asleep herself
    if (("dobranoc" in low or "do snu" in low or "na sen" in low)
            and any(k in low for k in ("bajk", "historyjk", "opowieść", "opowiesc"))
            and _short(text, 10) and intent.asked(low, 4)):
        _tell_story("Opowiedz mi spokojną, krótką bajkę na dobranoc — około 8 "
                    "zdań, łagodnie i sennie — i zakończ życzeniem dobrej nocy.", True)
        return "recorded"            # process() already put it in the history

    # "jeszcze 5 minut" / "drzemka" right after an alarm or timer rang
    if any(k in low for k in _SNOOZE) and _short(text, 7):
        import timers
        secs, _ = timers.parse_duration(low)
        secs = secs or SNOOZE_MINUTES * 60
        if timers.snooze(secs):
            import radio
            radio.stop_alarm()                     # the radio alarm goes quiet too
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
    labelled = timers.local_labelled_timer(text)  # "…na 10 minut na makaron"
    if labelled:
        secs, label = labelled
        timers.apply([{"type": "timer", "seconds": secs, "at": "", "label": label,
                       "repeat": "none", "list": ""}])
        speak(f"Jasne, {timers.say_duration(secs)} — {label}.")
        return True
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
    if any(k in low for k in _FOCUS) and _short(text, 9) and intent.asked(low, 4):
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
        import calc
        speak(f"Dobrze, {mins} {calc._plural(mins, 'minuta', 'minuty', 'minut')} skupienia. "
              "Będę cicho — powodzenia!")
        return True

    import breathing                               # guided breathing
    if breathing.is_trigger(low) and intent.asked(low, 3):
        breathing.run(speak, play_sound)
        return True

    import counting                                # "policz do 20", stopwatch
    if counting.handle(text, speak, play_sound):
        return True

    if kids.handle(text, speak, _sound_async):     # tooth brushing, routines
        return True

    if twenty.wants(text):                         # "zgadnij, o czym myślę"
        twenty.start(speak)
        return True

    dish = cooking.wants(text)                     # "gotujemy naleśniki"
    if dish:
        cooking.start(dish, speak)
        return True

    import ambience                                # "włącz szum deszczu"
    if ambience.handle(text, speak):
        return True

    import lists                                   # "przywróć listę" — undo
    said = lists.restore(text)
    if said:
        speak(said)
        return True

    import radio                                   # "włącz radio", "wyłącz Trójkę"
    if radio.handle(text, speak):
        return True

    import timers
    rem = timers.local_reminder(text)              # "przypomnij mi za 20 minut o praniu"
    if rem:
        timers.apply([rem[0]])
        speak(rem[1])
        return True

    alarm = local_alarm(text)                      # "obudź mnie o 6:30" — even offline
    if alarm:
        import clock
        import timers
        hm, repeat = alarm
        timers.apply([{"type": "alarm", "seconds": 0, "at": hm, "label": "",
                       "repeat": repeat, "list": ""}])
        h, m = (int(x) for x in hm.split(":"))
        when = {"daily": " codziennie", "weekdays": " w dni robocze",
                "weekends": " w weekendy"}.get(repeat, "")
        speak(f"Dobrze, budzik{when} na {clock.hour_accusative(h, m)}.")
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

    import voicefx                                 # "zmień mój głos"
    effect = voicefx.wants(text)
    if effect:
        voicefx.arm(effect)
        with state.lock:                           # the next sentence needs no "Luna"
            state.conversation_active = True
            state.last_activity_time = time.time() + 5
        speak("Powiedz coś — a ja zmienię twój głos!" if effect == "?" else
              f"Powiedz coś — zrobię z tego głos: {effect}!" if effect != "od tyłu" else
              "Powiedz coś — puszczę to od tyłu!")
        return True

    import memo                                    # "zagrajmy w memory"
    if memo.wants(text):
        memo.start(speak, hard=memo.hard_wanted(text))
        return True
    if memo.active() and _short(text, 5) and re.search(
            r"\b(jeszcze raz|nowa gra|od nowa|potasuj|zagrajmy jeszcze)\b", low):
        memo.again(speak)
        return True
    if memo.active() and _short(text, 4) and re.search(
            r"\b(koniec|wystarczy|kończymy|konczymy|stop)\b", low):
        memo.stop()
        speak("Dobrze, koniec gry.")
        return True

    import tictac                                  # "zagrajmy w kółko i krzyżyk"
    if tictac.wants(text):
        tictac.start(speak, duo=tictac.duo_wanted(text))
        return True
    if tictac.active() and _short(text, 5) and re.search(
            r"\b(jeszcze raz|rewanż|rewanz|nowa gra|od nowa|zagrajmy jeszcze)\b", low):
        tictac.again(speak)
        return True
    if tictac.active() and _short(text, 4) and re.search(
            r"\b(koniec|wystarczy|kończymy|konczymy|stop)\b", low):
        tictac.stop()
        speak("Dobrze, koniec gry. Dzięki za partyjkę!")
        return True

    if quiz.dictation_words(text, speak):           # "słowa do dyktanda: …"
        return True
    kind = quiz.trigger(text)                      # "przepytaj mnie z tabliczki"
    if kind:
        quiz.start(kind, text, speak, _sound_async)
        return True

    # faces: "to jest Kasia" / "jestem Andrzej" / "zapomnij moją twarz"
    m = _FACE_FORGET.search(text)
    if m and _short(text, 6):
        import faces
        if m.group(1):
            who = faces.match_name(m.group(1)) or faces.nominative(m.group(1))
        else:
            with state.lock:
                who = state.person[0] if state.person else None
        if who and faces.forget(who):
            speak(f"Dobrze, zapomniałam twarz: {who}.")
        else:
            speak("Nie znam tej twarzy.")
        return True
    name = _intro_name(text) or _bare_name(text)
    if name:
        return _learn_face(name, text, speak)
    if any(k in low for k in _FACE_BARE) and _short(text, 6):
        with state.lock:
            known = state.person[0] if state.person else None
        speak(f"Przecież cię znam — to ty, {known}!" if known else
              "Powiedz: zapamiętaj moją twarz, jestem… i swoje imię.")
        return True

    import errands                                 # "przekaż Mai, żeby…"
    gone = errands.cancel(text)
    if gone:
        who, n = gone
        speak(f"Dobrze, usunęłam przypomnienia dla: {who}." if n else
              f"Nie mam nic do przekazania dla: {who}.")
        return True
    got = errands.take(text)
    if got:
        to, _ = got
        at, daily = errands._when(text)
        if at and daily:
            speak(f"Dobrze. Codziennie po {at} powiem to, kiedy {to} się pojawi.")
        elif at:
            speak(f"Dobrze. Po {at} powiem to, kiedy {to} się pojawi.")
        else:
            speak(random.choice((f"Dobrze, przekażę, kiedy {to} się pojawi.",
                                 f"Jasne. Powiem, jak tylko zobaczę: {to}.")))
        return True

    note = _remember(text)                         # "zapamiętaj, że …"
    if note:
        import memory
        memory.add_fact(note)
        with state.lock:
            state.reply_scene = "remember"
            state.reply_scene_start = time.time()
        speak(random.choice(("Zapamiętane.", "Dobrze, zapamiętam.", "Zapisane w pamięci.")))
        return True

    if _bare(text, _SLOWER + _FASTER) or any(k in low for k in _NORMAL_SPEED):
        with state.lock:                       # per person, like the reply length
            who = state.person[0] if state.person else None
        by = settings.get("tts_speed_by", {}) or {}
        cur = by.get(who) or settings.get("tts_speed", OPENAI_TTS_SPEED)
        if any(k in low for k in _NORMAL_SPEED):
            new = OPENAI_TTS_SPEED
        else:
            step = SPEED_STEP if any(k in low for k in _FASTER) else -SPEED_STEP
            new = round(max(SPEED_MIN, min(SPEED_MAX, cur + step)), 2)
        if who:
            if new == OPENAI_TTS_SPEED:
                by.pop(who, None)
            else:
                by[who] = new
            settings.put("tts_speed_by", by)
        else:
            settings.put("tts_speed", new)
        print(f"[cmd] speech speed{' for ' + who if who else ''} {cur} → {new}", flush=True)
        if new == cur:
            speak("Szybciej już nie umiem." if new >= SPEED_MAX else
                  "Wolniej już nie umiem." if new <= SPEED_MIN else "Mówię normalnie.")
        else:
            speak("Dobrze, tak mówię teraz. Może być?")
        return True

    if _short(text, 7):
        length = ("short" if any(k in low for k in _SHORTER) else
                  "long" if any(k in low for k in _LONGER) else
                  "normal" if any(k in low for k in _NORMAL_LENGTH) else None)
        if length:
            with state.lock:
                who = state.person[0] if state.person else None
            if who:                                # each person their own
                by = settings.get("reply_length_by", {}) or {}
                by[who] = length
                settings.put("reply_length_by", by)
            else:
                settings.put("reply_length", length)
            print(f"[cmd] reply length → {length}" + (f" for {who}" if who else ""),
                  flush=True)
            speak({"short": "Dobrze, będę mówić krócej.",
                   "long": "Dobrze, będę odpowiadać dłużej.",
                   "normal": "Dobrze, wracam do zwykłych odpowiedzi."}[length])
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
