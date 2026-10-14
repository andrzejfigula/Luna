"""
fun.py — small on-request games and gadgets (all local, no model call).

  "włącz lampkę"           → night light: a warm glow over the whole screen
                             until "wyłącz lampkę" or a tap
  "lampka na niebiesko"    → in a colour (czerwony, zielony, niebieski, fioletowy,
                             różowy, żółty, pomarańczowy, biały, ciepły)
  "lampka na 20 minut"     → goes out by itself
  "przybij piątkę"         → her hand comes up; tap the screen within 4 s
  "rzuć kostką"            → a die rolls on her screen ("dwiema kostkami": two)
  "rzuć monetą" / "orzeł czy reszka" → a coin flips
  "pokaż mi kotka" / "zamień się w pieska" / "bądź zajączkiem" → cat / dog /
                             bunny ears (and whiskers) on her face for 25 s
  "pomachaj", "kiwnij głową", "pokręć głową", "pokaż kciuk", "pokaż serce"
                           → the gesture at once (robot_face's hands and head)

robot_face.py draws the overlays ("lamp", "dice", "coin"); see screens.py for
the overlay mechanism. None of these run on their own.
"""

import random
import re
import time

from shared_state import state

LAMP_ON  = ("włącz lampkę", "zapal lampkę", "włącz lampkę nocną", "tryb lampki",
            "wlacz lampke", "night light", "turn on the lamp")
LAMP_OFF = ("wyłącz lampkę", "zgaś lampkę", "wylacz lampke", "zgas lampke",
            "turn off the lamp")
HIGH_FIVE = ("przybij piątkę", "daj piątkę", "przybijemy piątkę", "przybij piatke",
             "high five")
DICE = ("rzuć kostką", "rzuć kością", "rzuc kostka", "rzuć kostkami", "roll a die",
        "roll the dice", "roll a dice")
COIN = ("rzuć monetą", "rzuc moneta", "orzeł czy reszka", "orzel czy reszka",
        "flip a coin", "rzuć monetę")

LAMP_HOURS = 10

# stem → (centre colour, edge colour) of the glow
LAMP_COLOURS = {
    "ciepł": ((255, 214, 150), (120, 50, 8)),    "ciepl": ((255, 214, 150), (120, 50, 8)),
    "czerwon": ((255, 90, 70), (110, 10, 5)),    "zielon": ((120, 255, 140), (10, 90, 25)),
    "niebiesk": ((110, 170, 255), (10, 30, 110)), "fiolet": ((200, 130, 255), (60, 15, 110)),
    "różow": ((255, 150, 210), (110, 25, 70)),   "rozow": ((255, 150, 210), (110, 25, 70)),
    "żółt": ((255, 240, 120), (120, 90, 5)),     "zolt": ((255, 240, 120), (120, 90, 5)),
    "pomarańcz": ((255, 170, 70), (120, 45, 5)), "pomarancz": ((255, 170, 70), (120, 45, 5)),
    "biał": ((255, 255, 250), (110, 110, 105)),  "bial": ((255, 255, 250), (110, 110, 105)),
    "red": ((255, 90, 70), (110, 10, 5)), "green": ((120, 255, 140), (10, 90, 25)),
    "blue": ((110, 170, 255), (10, 30, 110)),
}


def _overlay(kind, secs, data=None):
    with state.lock:
        state.overlay = (kind, time.time() + secs, data)


# "Pomachaj mi", "kiwnij głową"… — the gestures robot_face animates (14 Oct
# probe: all went to the model; "pokaż kciuk" even looked for a photo)
_GESTURES = [
    ("wave", re.compile(r"^(?:pomachaj|pomachasz|machnij|pomachaj\s+ręką|pomachaj\s+rączką)"
                        r"(?:\s+(?:mi|nam|ręką|rączką|do\s+\w+|na\s+do\s+widzenia|proszę))*$"),
     ("Hej, hej!", "Pa, pa!", "Cześć!")),
    ("nod", re.compile(r"^(?:kiwnij|pokiwaj|skiń|przytaknij)(?:\s+(?:mi|głową|glowa|głowa|"
                       r"proszę))*$"), ("Mhm, tak!", "Tak, tak!")),
    ("shake", re.compile(r"^(?:pokręć|pokrec|pokiwaj\s+przecząco|zaprzecz)(?:\s+(?:mi|głową|"
                         r"glowa|głowa|proszę))*$"), ("Nie, nie!", "O nie!")),
    ("thumbs_up", re.compile(r"^(?:pokaż|pokaz|daj)\s+(?:mi\s+)?(?:kciuka?|kciuk\s+w\s+górę)"
                             r"(?:\s+w\s+górę)?(?:\s+proszę)?$|^kciuk\s+w\s+górę$"),
     ("Super!", "Ekstra!")),
    ("heart", re.compile(r"^(?:pokaż|pokaz|zrób|zrob)\s+(?:mi\s+|nam\s+)?(?:serce|serduszko|"
                         r"serduszko\s+rękami|serce\s+rękami)(?:\s+proszę)?$"),
     ("Dla ciebie!", "Kocham was!")),
]


# "Jak robi krowa?", "zamiaucz", "ryknij jak lew" — said at once (14 Oct probe:
# all to the model). stem → (the sound, the costume she puts on with it)
_ANIMAL_SOUNDS = [
    (r"kot|kotek|kotka|kici", "Miau, miau!", "cat"),
    (r"pies|piesek|psa|pieska|szczeni", "Hau, hau!", "dog"),
    (r"zając|zajac|zajączek|zajaczek|królik|krolik", "Kic, kic!", "bunny"),
    (r"krow", "Muuu!", None), (r"koń|kon\b|konik|konia|konika", "Iiihaha!", None),
    (r"kur[ay]?\b|kurk|kurczak|kurczaczek", "Ko, ko, ko!", None),
    (r"kogut", "Kukuryku!", None), (r"kacz", "Kwa, kwa!", None),
    (r"owc|owieczk|baran", "Beee!", None), (r"koz", "Meee!", None),
    (r"świn|swin|prosiak|prosiaczek", "Chrum, chrum!", None),
    (r"lew|lwa|lwem|lwica|tygrys", "Wrrraaau!", None), (r"żab|zab", "Kum, kum!", None),
    (r"sow|puszczyk", "Hu, hu!", None), (r"wilk|wilka", "Auuuuu!", None),
    (r"mysz|myszk", "Pi, pi, pi!", None), (r"osioł|osiol|osła|osla", "I-o, i-o!", None),
    (r"indyk", "Gul, gul, gul!", None), (r"gęś|ges\b|gęsi|gesi", "Gę, gę, gę!", None),
    (r"pszcz|trzmiel|mucha|much", "Bzzzzz!", None), (r"wąż|waz\b|węż|wez", "Ssssss!", None),
    (r"słoń|slon|słonia|slonia", "Tuuuuu!", None), (r"kukułk|kukulk", "Ku-ku, ku-ku!", None),
    (r"ptak|ptaszek|ptaszk|wróbel|wrobel", "Ćwir, ćwir!", None),
]
_SOUND_Q = re.compile(r"^jak\s+(?:robi|mówi|mowi)\s+(\w+(?:\s+\w+)?)$|"
                      r"^jaki\s+(?:dźwięk|dzwiek|odgłos|odglos)\s+(?:wydaje|robi)\s+(\w+(?:\s+\w+)?)$|"
                      r"^(?:zrób|zrob|udawaj|naśladuj|nasladuj)\s+(?:mi\s+)?(?:jak|dźwięk|dzwiek|"
                      r"odgłos|odglos)\s+(\w+(?:\s+\w+)?)$|"
                      r"^(?:ryknij|zaryknij|zarycz)(?:\s+jak)?\s*(\w+)?$")
_SOUND_VERBS = {"zamiaucz": "kot", "miaucz": "kot", "zaszczekaj": "pies", "szczekaj": "pies",
                "zamucz": "krowa", "zabecz": "owca", "zakwacz": "kaczka", "zapiej": "kogut",
                "zachrumkaj": "świnia", "zawyj": "wilk", "zarżyj": "koń", "zarzyj": "koń"}


def animal_sound(text, speak):
    """The animal's sound at once (and the cat's or dog's ears with it)."""
    low = re.sub(r"^(?:luna|luno)\W+", "", text.lower().strip(" .!?"))
    low = re.sub(r"\s+(?:proszę|prosze)$", "", low)
    animal = _SOUND_VERBS.get(low.split(" ")[0]) if len(low.split()) <= 3 else None
    if animal is None:
        m = _SOUND_Q.match(low)
        if not m:
            return False
        animal = next((g for g in m.groups() if g), None) or "lew"   # "ryknij!" alone
        if re.search(r"\bpo\b", animal):
            return False                       # "jak mówi kot po angielsku?" — the model
    for stem, sound, costume in _ANIMAL_SOUNDS:
        if re.match(r"(?:" + stem + ")", animal):
            if costume:
                with state.lock:
                    state.costume = (costume, time.time() + COSTUME_SECS)
            _mood("happy")
            print(f"[fun] animal sound: {animal}", flush=True)
            speak(sound)
            return True
    return False


# "Mrugnij", "Zrób zeza", "Zatańcz", "Zrób smutną minę" — her face at once
# (14 Oct probe: all to the model, ~3 s for a wink). → (scene, emotion, lines)
_MIN = r"(?:\s+(?:mi|nam|proszę|prosze|do\s+mnie|jeszcze\s+raz))*$"
_FACES = [
    (re.compile(r"^(?:mrugnij|mrugaj|puść\s+(?:mi\s+)?oczko|pusc\s+(?:mi\s+)?oczko|"
                r"zrób\s+oczko|oczko)" + _MIN), "wink", "happy", ("Hihi!", "Oczko!")),
    (re.compile(r"^(?:zrób|zrob)\s+(?:mi\s+)?(?:zeza|zeza\s+oczami)" + _MIN + r"|^zezuj" + _MIN),
     "cross_eyes", "happy", ("Ale mam zeza!", "Zez!")),
    (re.compile(r"^(?:zatańcz|zatancz|zatańczysz|tańcz|tancz|potańcz|potancz)"
                r"(?:\s+(?:mi|nam|ze\s+mną|dla\s+mnie|coś|cos|proszę))*$"),
     "dance", "happy", ("Tańczę!", "Patrz, jak tańczę!")),
    (re.compile(r"^(?:zaśmiej|zasmiej|pośmiej|posmiej)\s+się" + _MIN), "laugh", "happy",
     ("Ha, ha, ha!", "Hihihi!")),
    (re.compile(r"^(?:zasalutuj|salutuj)" + _MIN), "salute", "happy", ("Melduję się!",)),
    (re.compile(r"^(?:klaśnij|klasnij|klaszcz|pokaż\s+jak\s+klaszczesz|zaklaszcz)"
                r"(?:\s+w\s+(?:dłonie|rączki|ręce))?" + _MIN), "clap", "happy", ("Brawo!",)),
    (re.compile(r"^(?:przewróć|przewroc)\s+oczami" + _MIN), "eye_roll", "neutral", ("No weź…",)),
    (re.compile(r"^(?:uśmiechnij|usmiechnij)\s+się" + _MIN + r"|^(?:zrób|zrob)\s+(?:mi\s+)?"
                r"(?:wesołą|wesola|uśmiechniętą|usmiechnieta|szczęśliwą|szczesliwa)\s+minę$"),
     "slow_blink", "happy", ("Proszę bardzo!", "Uśmiecham się!")),
    (re.compile(r"^(?:zrób|zrob)\s+(?:mi\s+)?(?:smutną|smutna)\s+(?:minę|mine|minkę|minke)$"
                r"|^(?:posmutniej|bądź\s+smutna)$"), "sigh", "sad", ("Oj…", "Smutno mi…")),
    (re.compile(r"^(?:zrób|zrob)\s+(?:mi\s+)?(?:złą|zla|groźną|grozna|gniewną)\s+(?:minę|mine|minkę)$"
                r"|^(?:zezłość|zezlosc)\s+się$"), None, "angry", ("Grrr!",)),
    (re.compile(r"^(?:zrób|zrob)\s+(?:mi\s+)?(?:zdziwioną|zdziwiona|zaskoczoną|zaskoczona)\s+"
                r"(?:minę|mine|minkę)$|^(?:zdziw|zdziwić)\s+się$"), "big_pupils", "surprised",
     ("Oooo!", "Coo?!")),
    (re.compile(r"^(?:zrób|zrob)\s+(?:mi\s+)?(?:przestraszoną|przestraszona|wystraszoną)\s+"
                r"(?:minę|mine|minkę)$|^(?:przestrasz|wystrasz)\s+się$"), "scared", "surprised",
     ("Aaa! Boję się!",)),
    (re.compile(r"^(?:zrób|zrob)\s+(?:mi\s+)?(?:śmieszną|smieszna|głupią|glupia|zabawną|zabawna)\s+"
                r"(?:minę|mine|minkę|minke)$|^(?:pokaż|pokaz)\s+(?:mi\s+)?(?:swój\s+)?język$"
                r"|^(?:wystaw|pokaż)\s+język$"), "cross_eyes", "happy", ("Bleee!",)),
    (re.compile(r"^(?:zrób|zrob)\s+(?:mi\s+)?(?:zakochaną|zakochana)\s+(?:minę|mine|minkę)$"
                r"|^(?:zrób|zrob)\s+(?:serduszka|serca)\s+(?:w\s+)?oczach$"), "heart_eyes", "love",
     ("Ojej!",)),
    (re.compile(r"^(?:zawstydź|zawstydz|zarumień|zarumien)\s+się$"), "shy", "love",
     ("Oj, przestań…",)),
    (re.compile(r"^(?:zakręć|zakrec)\s+się$|^(?:zrób|zrob)\s+(?:mi\s+)?(?:zawroty|zakręconą)\s+"
                r"(?:głowy|minę)$"), "dizzy", "surprised", ("Wszystko się kręci!",)),
]


def face_play(text, speak):
    """A face asked for — wink, cross-eyes, a dance, a sad face — at once.
    True when it was one."""
    low = re.sub(r"^(?:luna|luno)\W+", "", text.lower().strip(" .!?"))
    for rx, scene, emotion, lines in _FACES:
        if rx.match(low):
            now = time.time()
            with state.lock:
                if scene:
                    state.reply_scene = scene
                    state.reply_scene_start = now
                state.emotion = emotion.capitalize()
                state.face_override = emotion if emotion != "neutral" else None
                state.face_override_until = now + 6.0
            print(f"[fun] face: {scene or emotion}", flush=True)
            speak(random.choice(lines))
            return True
    return False


def gesture(text, speak):
    """The gesture asked for, at once. True when it was one."""
    low = re.sub(r"^(?:luna|luno)\W+", "", text.lower().strip(" .!?"))
    for name, rx, lines in _GESTURES:
        if rx.match(low):
            with state.lock:
                state.gesture_anim = name
                state.gesture_anim_start = time.time()
            print(f"[fun] gesture: {name}", flush=True)
            speak(random.choice(lines))
            return True
    return False


def _mood(emotion):
    with state.lock:
        state.emotion = emotion


def _colour(low):
    return next((c for stem, c in LAMP_COLOURS.items() if stem in low), None)


def lamp_on(colour=None, secs=None):
    _overlay("lamp", secs or LAMP_HOURS * 3600,
             {"col": colour or LAMP_COLOURS["ciepł"]})


def lamp_lit():
    with state.lock:
        ov = state.overlay
    return bool(ov and ov[0] == "lamp" and time.time() < ov[1])


def lamp_off():
    with state.lock:
        if state.overlay and state.overlay[0] == "lamp":
            state.overlay = None


def high_five(speak, play_sound):
    t0 = time.time()                 # any touch from the moment the hand is up
    with state.lock:                 # counts — even one that cuts "Przybij!"
        state.game_hand = ("paper", t0 + 7.0)
    _mood("Happy")
    speak("Przybij!")
    t_end = time.time() + 4.0
    touched = False
    while time.time() < t_end:
        with state.lock:
            touched = state.touch_time > t0
        if touched:
            break
        time.sleep(0.03)
    with state.lock:
        state.game_hand = None
    if touched:
        play_sound("giggle", can_drop=False)
        _mood("Excited")
        speak(random.choice(["Piątka!", "Jest piątka!", "Ale mocna!"]))
    else:
        _mood("Sad")
        speak("Hej, nie zostawiaj mnie z ręką w powietrzu!")
    _mood("Neutral")


_PL_DICE = {1: "jeden", 2: "dwa", 3: "trzy", 4: "cztery", 5: "pięć", 6: "sześć"}
_PIPS = {1: "jedynka", 2: "dwójka", 3: "trójka", 4: "czwórka", 5: "piątka", 6: "szóstka"}


def roll(speak, play_sound_async, low):
    two = bool(re.search(r"\b(dwiema|dwoma|dwie|2)\b", low)) or "kostkami" in low
    results = [random.randint(1, 6) for _ in range(2 if two else 1)]
    _overlay("dice", 3.6, {"results": results, "t0": time.time()})
    for _ in range(4):
        play_sound_async("tick")
        time.sleep(0.28)
    time.sleep(0.2)
    if re.search(r"\b(?:roll|dice|die)\b", low):          # "Roll a die" — in English
        speak(" and ".join(str(r) for r in results) + (f" — {sum(results)} together!"
                                                        if two else "!"))
        return
    if two:
        speak(f"{_PIPS[results[0]].capitalize()} i {_PIPS[results[1]]} — "
              f"razem {sum(results)}!")
    else:
        speak(f"Wypadła {_PIPS[results[0]]}!")          # what the die shows


def flip(speak, play_sound_async, english=False):
    side = random.choice(["orzeł", "reszka"])
    _overlay("coin", 3.4, {"side": side, "t0": time.time()})
    play_sound_async("tick")
    time.sleep(1.5)
    speak({"orzeł": "Heads!", "reszka": "Tails!"}[side] if english else side.capitalize() + "!")


_NUMBER = re.compile(r"\b(?:wylosuj|losuj|wybierz|podaj|daj)\s+(?:mi\s+)?(?:jakąś\s+|losową\s+)?"
                     r"liczbę\s+od\s+(.+?)\s+do\s+(.+?)[.!?]*$", re.I)
_PICK = re.compile(r"\b(?:wylosuj|losuj|wybierz|zdecyduj)\b(?:\s+(?:za\s+mnie|losowo|mi|"
                   r"coś))*\s*[:,]?\s*(.+?)[.!?]*$", re.I)
_WHO_DOES = re.compile(r"^(?:luna,?\s+)?kto\s+(?:dziś\s+|dzisiaj\s+)?(?:ma\s+)?(\w+(?:\s+\w+)?)"
                       r"\s*[:,]\s*(.+?)[?.!]*$", re.I)


def _number(word_or_digits):
    import calc
    s = word_or_digits.strip(" ,.")
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    words = s.lower().split()
    if words and all(w in calc._ONES for w in words):
        return calc._words_number(words)
    return None


def _options(s):
    parts = [p.strip(" ,.?!") for p in re.split(r",|\s+(?:czy|albo|lub)\s+", s) if p.strip(" ,.?!")]
    return parts if 2 <= len(parts) <= 8 and all(len(p.split()) <= 4 for p in parts) else None


def random_answer(text, rng=random):
    """"Wylosuj liczbę od 1 do 100", "wybierz: pizza czy makaron", "kto zmywa:
    Maja, tata czy mama?" → her pick, really at random (a model isn't)."""
    m = _NUMBER.search(text)
    if m:
        lo, hi = _number(m.group(1)), _number(m.group(2))
        if lo is not None and hi is not None and lo < hi <= 1_000_000:
            return f"Losuję… {rng.randint(lo, hi)}!"
        return None
    m = _WHO_DOES.match(text.strip())
    if m and (re.search(r"\b(?:losuj|wylosuj|losowo)\b", text, re.I) or re.search(
            r"(?:zmyw|sprząt|sprzat|wynos|zaczyn|pierwsz|wybier|idzie|myje|odkurz|karmi|"
            r"gotuj|wyprowadz|podlew|nakryw|rozpak)", m.group(1).lower())):
        # chores and turns only — "kto jest lepszy, Messi czy Ronaldo?" is no draw
        opts = _options(m.group(2))
        if opts:
            return f"Losuję… {rng.choice(opts)}!"
        return None
    m = _PICK.search(text)
    if m and re.search(r"\b(czy|albo|lub)\b|,", m.group(1)):
        opts = _options(m.group(1))
        if opts:
            return f"Wybieram: {rng.choice(opts)}!"
    return None


def handle(text, speak, play_sound, play_sound_async):
    said = random_answer(text)
    if said:
        speak(said)
        return True
    if gesture(text, speak) or face_play(text, speak) or animal_sound(text, speak):
        return True
    low = text.lower()
    words = re.findall(r"\w+", low)
    polite = re.search(r"\b(?:możesz|mozesz|mogłabyś|moglabys|mogłabys|can\s+you|could\s+you)\b",
                       low)
    if len(words) > 8 or (low.strip().endswith("?") and not polite
                          and not any(k in low for k in COIN)):
        return False                       # "czy możesz rzucić kostką?" is a request
    if any(k in low for k in LAMP_OFF):
        import timers
        secs, _ = timers.parse_duration(low) if re.search(r"\bza\b", low) else (None, None)
        when = None
        if not secs and re.search(r"\bo\s+(?:godzinie\s+)?[\w:.]+", low):
            import errands                    # "zgaś lampkę o 21" — at that time
            hm, _ = errands._clock(low)
            if hm:
                hh, mm = (int(x) for x in hm.split(":"))
                t = time.localtime()
                target = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hh, mm, 0, 0, 0, -1))
                if target <= time.time():
                    target += 86400
                secs = target - time.time() + 0.5
                import clock
                when = f"o {clock.hour_locative(hh, mm)}"
        if secs and lamp_lit():               # "wyłącz lampkę za kwadrans" — later
            with state.lock:
                col = (state.overlay[2] or {}).get("col")
            lamp_on(col, secs)
            speak(f"Lampka zgaśnie {when or 'za ' + timers.say_duration(secs)}.")
            return True
        if secs and not lamp_lit():           # "zgaś lampkę za godzinę" — it isn't on
            speak("Lampka teraz nie świeci.")   # (10 Oct: nothing was said at all)
            return True
        lamp_off()
        return True
    colour = _colour(low)
    lampish = any(k in low for k in LAMP_ON) or re.search(r"\blamp", low)
    # "lampka na niebiesko", "zmień kolor lampki na zielony", "lampka na 20 minut"
    if lampish and (any(k in low for k in LAMP_ON) or colour
                    or re.search(r"\b(?:włącz|wlacz|zapal|zmień|zmien|ustaw|zrób|zrob|daj)\b", low)
                    or re.search(r"\bna\s+\S+\s+(?:minut|godzin|sekund)", low)
                    or "kwadrans" in low or "pół godziny" in low):
        import timers
        secs, _ = timers.parse_duration(low)
        if colour is None and lamp_lit():           # "lampka na 20 minut" while on:
            with state.lock:                        # keep its colour
                colour = (state.overlay[2] or {}).get("col")
        lamp_on(colour, secs)
        if secs:
            speak(f"Lampka zgaśnie za {timers.say_duration(secs)}.")
        print(f"[fun] lamp {colour or 'warm'}" + (f" for {secs}s" if secs else ""), flush=True)
        return True
    if any(k in low for k in HIGH_FIVE):
        high_five(speak, play_sound)
        return True
    if any(k in low for k in DICE) or re.search(r"\brzu[cć]\w*\b.*\bko(st|ś)", low):
        roll(speak, play_sound_async, low)
        return True
    if any(k in low for k in COIN):
        flip(speak, play_sound_async, english="flip" in low or "coin" in low)
        return True
    if _PANSTWA.search(low):
        panstwa(speak)
        return True
    with state.lock:                          # a round on: "koniec" / "stop" ends it
        ov = state.overlay
    if (ov and ov[0] == "card" and "państwa-miasta" in str((ov[2] or {}).get("sub", ""))
            and re.fullmatch(r"(?:koniec|stop|starczy|wystarczy|kończymy)(?:\s+\w+){0,2}",
                             low.strip(" .!?"))):
        with state.lock:
            state.overlay = None
        speak("Dobrze, koniec rundy.")
        return True
    return costume(low, speak)


# "Zagrajmy w państwa-miasta" — a letter big on her screen, a minute, "Stop!"
# (a family evening game; she only keeps the time — they write on paper)
_PANSTWA = re.compile(r"państwa[\s-]*miasta|panstwa[\s-]*miasta|"
                      r"(?:wylosuj|losuj|nowa|następna|nastepna|kolejna)\s+liter[ęae]", re.I)
_LETTERS = "ABCDEFGHIJKLMNOPRSTUWZ"           # no Q, V, X, Y — nothing starts with them
PANSTWA_SECS = 60
_LETTER_SAID = {"A": ("a", "arbuz"), "B": ("be", "balon"), "C": ("ce", "cebula"),
                "D": ("de", "dom"), "E": ("e", "ekran"), "F": ("ef", "foka"),
                "G": ("gie", "góra"), "H": ("ha", "herbata"), "I": ("i", "igła"),
                "J": ("jot", "jabłko"), "K": ("ka", "kot"), "L": ("el", "las"),
                "M": ("em", "mama"), "N": ("en", "nos"), "O": ("o", "okno"),
                "P": ("pe", "pies"), "R": ("er", "rower"), "S": ("es", "słońce"),
                "T": ("te", "tata"), "U": ("u", "ucho"), "W": ("wu", "woda"),
                "Z": ("zet", "zebra")}


def panstwa(speak):
    letter = random.choice(_LETTERS)
    t0 = time.time()
    _overlay("card", PANSTWA_SECS + 5, {"text": letter, "sub": "państwa-miasta · minuta",
                                        "tone": None})
    _mood("Excited")
    print(f"[fun] państwa-miasta: {letter}", flush=True)
    # a lone "W" was read "double-u", "K" heard as "T" (TTS round trip, 8 Oct):
    # the Polish letter name and a word for it
    name, word = _LETTER_SAID[letter]
    speak(f"Litera {name} — jak {word}! Macie minutę — start!")

    def clock():
        from text_to_speech import speak as say
        for at, line in ((PANSTWA_SECS - 10, "Zostało dziesięć sekund!"),
                         (PANSTWA_SECS, "Stop! Koniec czasu — odkładamy długopisy.")):
            time.sleep(max(0.0, t0 + at - time.time()))
            with state.lock:          # another letter or game since: this round is over
                ov = state.overlay
            if not (ov and ov[0] == "card" and (ov[2] or {}).get("text") == letter):
                return
            say(line)
        _overlay("card", 8, {"text": letter, "sub": "koniec czasu", "tone": "bad"})
    import threading
    threading.Thread(target=clock, daemon=True, name="panstwa").start()


# "Pokaż mi kotka" — she has no pictures, so she becomes one: ears, a nose and
# whiskers on her own face for a while (8 Oct sweep: the model offered a kitten
# "na ekranie" she can't show)
_COSTUME = re.compile(r"\b(?:pokaż|pokaz|pokazać|pokazac|zamień\s+się\s+w|zamien\s+sie\s+w|"
                      r"zamienić\s+się\s+w|zamienic\s+sie\s+w|bądź|badz|być|byc|"
                      r"zrób\s+się\s+na|zrob\s+sie\s+na|udawaj|udawać|udawac|"
                      # "Zrób kotka" (13 Oct 22:19: the model, then the costume)
                      r"zrób\s+z\s+siebie|zrob\s+z\s+siebie|zrób|zrob|"
                      r"przebierz\s+się\s+za|przebierz\s+sie\s+za|przebrać\s+się\s+za|"
                      r"przebrac\s+sie\s+za|zrób\s+minę|zrob\s+mine|zrobić\s+minę|zrobic\s+mine|"
                      r"narysuj|narysować|narysowac)"
                      r"\s+(?:mi\s+)?(?:jak\s+)?(?:(?:jakiegoś|jakiegos|małego|malego|małym|malym|"
                      r"słodkiego|slodkiego)\s+){0,2}(\w+)((?:\W+\w+){0,3})")
_COSTUME_KIND = (("cat", r"kot|kici|kotk"), ("dog", r"pies|psa|psem|piesk|szczeni"),
                 ("bunny", r"zając|zajac|zajączk|zajaczk|królik|krolik|króliczk|kroliczk"))
_COSTUME_SAY = {"cat": "Miau! Zobacz — jestem kotkiem!",
                "dog": "Hau, hau! Teraz jestem pieskiem!",
                "bunny": "Kic, kic! Zobacz, jaki ze mnie zajączek!"}
_COSTUME_OFF = re.compile(r"\b(?:zdejmij\s+uszy|koniec\s+przebrania|bądź\s+sobą|badz\s+soba)\b")
COSTUME_SECS = 25
_COSTUME_EN = re.compile(r"^(?:luna,?\s+)?(?:show\s+me\s+a|be\s+a|turn\s+into\s+a|"
                         r"can\s+you\s+be\s+a)\s+(cat|kitty|kitten|dog|puppy|bunny|rabbit)\W*$")


def costume(low, speak):
    if _COSTUME_OFF.search(low):
        with state.lock:
            was, state.costume = state.costume, None
        if was:
            speak("Już jestem sobą!")
        return bool(was)
    e = _COSTUME_EN.search(low)              # "Show me a cat" (8 Oct sweep: "Here's a cat: kot.")
    if e:
        kind = {"cat": "cat", "kitty": "cat", "kitten": "cat", "dog": "dog", "puppy": "dog",
                "bunny": "bunny", "rabbit": "bunny"}[e.group(1)]
        with state.lock:
            state.costume = (kind, time.time() + COSTUME_SECS)
        _mood("happy")
        print(f"[fun] costume: {kind}", flush=True)
        speak({"cat": "Meow! Look — I'm a kitty!", "dog": "Woof, woof! Now I'm a puppy!",
               "bunny": "Hop, hop! Look, I'm a bunny!"}[kind])
        return True
    m = _COSTUME.search(low)
    if not m or len(re.findall(r"\w+", m.group(2))) > 1 and not re.search(
            r"^\W*(?:proszę|prosze|luna|luno)\b", m.group(2)):
        return False                       # "pokaż kota w butach" is something else
    kind = next((k for k, rx in _COSTUME_KIND if re.match(rx, m.group(1))), None)
    if not kind:
        return False
    with state.lock:
        state.costume = (kind, time.time() + COSTUME_SECS)
    _mood("happy")
    print(f"[fun] costume: {kind}", flush=True)
    # "Narysuj mi kotka" got ASCII art read aloud (8 Oct sweep)
    speak(("Rysować nie umiem, ale popatrz! " if m.group(0).startswith("narys") else "")
          + _COSTUME_SAY[kind])
    return True
