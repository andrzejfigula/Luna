"""
radio.py — internet radio.

  "Włącz radio"                 → the last station (RMF FM the first time)
  "Włącz Trójkę" / "puść radio Nowy Świat" / "włącz radio 357"
  "Wyłącz radio" / "stop radio"
  "Wyłącz radio za 30 minut"    → a sleep timer ("radio na 20 minut" too)
  "Jakie to radio?"             → the station's name
  "Co teraz gra?"               → the song, from the stream's ICY title
  "Następna stacja"             → the next built-in station
  "Ciszej" / "głośniej"         → while music plays: the MUSIC, not her voice
                                  ("mów ciszej" is still about her voice)
  "Budź mnie radiem"            → wake-up alarms start the radio, fading in
                                  over a minute, instead of the chime
                                  ("budź mnie dzwonkiem" switches back)

A few Polish stations are built in; any other name is looked up in the
public radio-browser.info directory (Polish stations first) and remembered.
ffmpeg decodes the stream; Python feeds the PCM to its own pw-play stream,
so the music never mixes into her voice's stream. While she listens or
speaks the music drops to RADIO_DUCK of its volume — you can always say
"Luna" over it, and she can be heard — then comes back up.
"""

import json
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import numpy as np

import visualizer
from shared_state import state

RATE, CHANNELS = 44100, 2
CHUNK = RATE * CHANNELS * 2 // 10          # 0.1 s of s16 stereo
RADIO_GAIN = 1.0                           # "ciszej" / "głośniej" while it plays: × this
MUSIC_RMS = 1530                           # the music is levelled to this loudness (s16
                                           # RMS): ~7 dB under her voice (~3700 when she
                                           # speaks). 11 Oct: "radio is by default too
                                           # loud compared to her voice" — at the old
                                           # fixed 0.55, RMF came out at 4450, louder
                                           # than her, and Dwójka at half of that.
                                           # (1700 at first; "10% quieter", Andrzej 11 Oct)
RADIO_DUCK = 0.12                          # while she listens or speaks
RETRIES = 3

# name → (spoken name, stream). Checked from the Pi on 2026-10-04.
STATIONS = {
    "rmf fm":        ("RMF FM", "http://195.150.20.242:8000/rmf_fm"),
    "radio zet":     ("Radio ZET", "http://zet-net-01.cdn.eurozet.pl:8400/"),
    "trójka":        ("Trójka", "http://mp3.polskieradio.pl:8904/;.mp3"),
    "jedynka":       ("Jedynka", "http://mp3.polskieradio.pl:8900/;.mp3"),
    "dwójka":        ("Dwójka", "http://mp3.polskieradio.pl:8902/;.mp3"),
    "radio 357":     ("Radio 357", "https://n-11-21.dcs.redcdn.pl/sc/o2/radio357/live/radio357_pr.livx?preroll=0"),
    "nowy świat":    ("Radio Nowy Świat", "https://go-audio.toya.net.pl/63214"),
    # 8 Oct night: the online lookup for "dla dzieci" failed once → kept here
    "dla dzieci":    ("RMF Dla Dzieci", "http://195.150.20.8/BABY"),
}
# ── the catalogue (15 Oct): stations by kind ─────────────────────────────────
# Andrzej: "soft background music for work — she has one jazz station and picks
# from 4 in total; I want a better choice and a list to choose from". Each kind:
# (key, label on the page, how she names it, [(name, url, a few words)]).
# Every stream checked from the Pi on 15 Oct (radio-browser.info, ffmpeg).
CATALOG = [
    ("calm", "Do pracy", "spokojna muzyka", [
        ("SomaFM Groove Salad", "https://ice2.somafm.com/groovesalad-128-mp3", "chill, downtempo"),
        ("Radio Paradise Mellow", "https://stream.radioparadise.com/mellow-128", "łagodny miks"),
        ("SomaFM Lush", "https://ice2.somafm.com/lush-128-mp3", "miękkie wokale"),
        ("RMF Chillout", "https://rs202-krk.rmfstream.pl/rmf_chillout", "chillout"),
        ("Lofi 24/7", "http://usa9.fastcast4u.com/proxy/jamz?mp=/1", "lo-fi hip-hop"),
        ("SomaFM Fluid", "https://ice2.somafm.com/fluid-128-mp3", "instrumentalny hip-hop"),
        ("SomaFM Deep Space One", "https://ice2.somafm.com/deepspaceone-128-mp3", "kosmiczny ambient"),
        ("SomaFM Drone Zone", "https://ice2.somafm.com/dronezone-128-mp3", "ambient, bez rytmu"),
    ]),
    ("jazz", "Jazz", "jazz", [
        ("Radio Swiss Jazz", "http://stream.srg-ssr.ch/m/rsj/mp3_128", "jazz bez reklam"),
        ("FIP Jazz", "https://icecast.radiofrance.fr/fipjazz-midfi.mp3", "jazz z Paryża"),
        ("Jazz Radio", "http://jazzradio.ice.infomaniak.ch/jazzradio-high.mp3", "jazz z Lyonu"),
        ("RMF Smooth Jazz", "https://rs202-krk.rmfstream.pl/rmf_smooth_jazz", "smooth jazz"),
        ("SomaFM Sonic Universe", "https://ice2.somafm.com/sonicuniverse-128-mp3", "nowoczesny jazz"),
        ("SomaFM Secret Agent", "https://ice2.somafm.com/secretagent-128-mp3", "lounge, klimat szpiegowski"),
        ("FIP Groove", "https://icecast.radiofrance.fr/fipgroove-midfi.mp3", "soul, funk, groove"),
    ]),
    ("classic", "Klasyka", "muzyka klasyczna", [
        ("Radio Swiss Classic", "http://stream.srg-ssr.ch/m/rsc_de/mp3_128", "klasyka bez gadania"),
        ("RMF Classic", "http://rmfstream1.interia.pl:8000/rmf_classic", "klasyka i muzyka filmowa"),
        ("Radio Chopin", "http://stream3.polskieradio.pl:8910/", "Chopin i fortepian"),
        ("Dwójka", "http://mp3.polskieradio.pl:8902/;.mp3", "Polskie Radio, kultura"),
        ("Venice Classic Radio", "https://uk2.streamingpulse.com/ssl/vcr1", "barok, kameralna"),
        ("France Musique", "https://icecast.radiofrance.fr/francemusique-midfi.mp3", "klasyka z Paryża"),
        ("Classic FM", "https://media-ice.musicradio.com/ClassicFMMP3", "klasyka z Londynu"),
    ]),
    ("polish", "Polskie", "polskie radio", [
        ("RMF FM", "http://195.150.20.242:8000/rmf_fm", "przeboje i fakty"),
        ("Radio ZET", "http://zet-net-01.cdn.eurozet.pl:8400/", "przeboje i fakty"),
        ("Trójka", "http://mp3.polskieradio.pl:8904/;.mp3", "Polskie Radio"),
        ("Jedynka", "http://mp3.polskieradio.pl:8900/;.mp3", "Polskie Radio, wiadomości"),
        ("Radio 357", "https://n-11-21.dcs.redcdn.pl/sc/o2/radio357/live/radio357_pr.livx?preroll=0",
         "dawna Trójka"),
        ("Radio Nowy Świat", "https://go-audio.toya.net.pl/63214", "ambitna muzyka"),
        ("TOK FM", "https://radiostream.pl/tuba10-1.mp3", "rozmowy, wiadomości"),
        ("Meloradio", "https://ml.cdn.eurozet.pl/mel-net.mp3", "melodyjne przeboje"),
    ]),
    ("hits", "Przeboje", "przeboje", [
        ("RMF MAXXX", "http://195.150.20.242/rmf_maxxx", "najnowsze hity"),
        ("ESKA Gorąca 100", "http://ic1.smcdn.pl/6120-1.mp3", "lista przebojów"),
        ("VOX FM", "https://ic2.smcdn.pl/3990-1.mp3", "do tańca"),
        ("Złote Przeboje", "http://radiostream.pl/tuba8928-1.mp3", "stare dobre przeboje"),
        ("Radio Swiss Pop", "http://stream.srg-ssr.ch/m/rsp/mp3_128", "pop bez reklam"),
        ("Radio Paradise", "https://stream.radioparadise.com/mp3-128", "eklektyczny miks"),
    ]),
    ("rock", "Rock", "rock", [
        ("Antyradio", "https://n-4-2.dcs.redcdn.pl/sc/o2/Eurozet/live/antyradio.livx?audio=5",
         "polski rock"),
        ("RMF Classic Rock", "https://rs201-krk.rmfstream.pl/rmf_classic_rock", "klasyka rocka"),
        ("Rock Antenne", "http://mp3channels.webradio.rockantenne.de/rockantenne", "rock z Monachium"),
        ("Radio Paradise Rock", "https://stream.radioparadise.com/rock-128", "rockowy miks"),
        ("FIP Rock", "https://icecast.radiofrance.fr/fiprock-midfi.mp3", "rock z Paryża"),
        ("SomaFM Indie Pop Rocks", "https://ice2.somafm.com/indiepop-128-mp3", "indie"),
        ("ESKA Rock", "https://ic2.smcdn.pl/5380-1.mp3", "rock po polsku"),
    ]),
    ("electronic", "Elektronika", "muzyka elektroniczna", [
        ("FIP Electro", "https://icecast.radiofrance.fr/fipelectro-midfi.mp3", "elektronika z Paryża"),
        ("SomaFM Beat Blender", "https://ice2.somafm.com/beatblender-128-mp3", "deep house"),
        ("SomaFM Space Station", "https://ice2.somafm.com/spacestation-128-mp3", "kosmiczna elektronika"),
        ("SomaFM Underground 80s", "https://ice2.somafm.com/u80s-128-mp3", "syntezatory lat 80"),
    ]),
    ("kids", "Dla dzieci", "radio dla dzieci", [
        ("RMF Dla Dzieci", "http://195.150.20.8/BABY", "piosenki dla dzieci"),
        ("Polskie Radio Dzieciom", "http://stream3.polskieradio.pl:8916/", "bajki i piosenki"),
    ]),
]
_CAT = {key: (label, said, sts) for key, label, said, sts in CATALOG}
# (almost) no singing — "bez śpiewania", "instrumentalne" (15 Oct: "jazzowe, ale
# bez śpiewania" got a station of show tunes)
INSTRUMENTAL = {"SomaFM Groove Salad", "SomaFM Fluid", "Lofi 24/7", "SomaFM Deep Space One",
                "SomaFM Drone Zone", "SomaFM Sonic Universe", "SomaFM Secret Agent",
                "Radio Swiss Classic", "Venice Classic Radio", "Radio Chopin", "RMF Classic",
                "SomaFM Beat Blender", "SomaFM Space Station"}
_NO_VOICE = re.compile(r"instrumentaln|bez\s+(?:śpiew|spiew|wokal|słów|slow|tekstu|gadania|słowa)")
for _k, _l, _s, _sts in CATALOG:                  # every one by name, too ("włącz FIP Jazz")
    for _n, _u, _b in _sts:
        STATIONS.setdefault(_n.lower(), (_n, _u))


def _kind_asked(what):
    """A kind of music (CATALOG's), not a station whose name says one."""
    w = (what or "").strip(" .!?").lower()
    if not w or not any(re.search(rx, w) for rx, k in _GENRES if k.startswith("cat:")):
        return False
    if any(k in w for k in STATIONS if len(k) > 3) or w in _ALIASES:
        return False                       # "Polskie Radio Chopin"
    kinds = [rx for rx, k in _GENRES if k.startswith("cat:")]
    other = [t for t in w.split() if not any(re.search(rx, t) for rx in kinds)]
    # "swiss jazz" — part of a station's name, with a word that isn't a kind
    return not (any(w in k for k in STATIONS) and other)


def _category_of(name):
    """The kind of the station by that name, or None."""
    return next((key for key, _, _, sts in CATALOG if any(n == name for n, _, _ in sts)), None)


def _pick(cat, instrumental=False):
    """A station of that kind — not the one playing, nor the last one
    picked of that kind (she chose among the same few before); with
    instrumental, one without singing (of that kind if it has any)."""
    import random
    sts = _CAT[cat][2]
    if instrumental:
        sts = [s for s in sts if s[0] in INSTRUMENTAL] or [
            s for s in _CAT["calm"][2] if s[0] in INSTRUMENTAL]
    last = _picked.get(cat)
    now = playing()
    gone = dead()
    pool = ([s for s in sts if s[0] not in (now, last) and s[1] not in gone]
            or [s for s in sts if s[1] not in gone] or list(sts))
    name, url, _ = random.choice(pool)
    _picked[cat] = name
    return name, url


_picked = {}               # kind → the last station picked for it


# stations move and fail: what to try next when a stream won't start
# (checked 2026-10-04 evening: Trójka's MP3 stream was down, its HLS worked)
FALLBACKS = {
    "http://195.150.20.8/BABY": ["http://stream3.polskieradio.pl:8916/"],   # Polskie Radio Dzieciom
    "http://195.150.20.242:8000/rmf_fm": ["http://195.150.20.9/RMFFM48"],
    "http://zet-net-01.cdn.eurozet.pl:8400/": ["https://r.dcs.redcdn.pl/sc/o2/Eurozet/live/audio.livx?audio=5"],
    "http://mp3.polskieradio.pl:8904/;.mp3": ["https://stream13.polskieradio.pl/pr3/pr3.sdp/playlist.m3u8"],
    "http://mp3.polskieradio.pl:8900/;.mp3": ["http://stream3.polskieradio.pl:8950/;.mp3"],
    "https://n-11-21.dcs.redcdn.pl/sc/o2/radio357/live/radio357_pr.livx?preroll=0": ["https://stream.radio357.pl/"],
}
_ALIASES = {"rmf": "rmf fm", "rmfu": "rmf fm", "rmf-u": "rmf fm", "zet": "radio zet", "zed": "radio zet", "zett": "radio zet",
            "set": "radio zet", "radio zed": "radio zet", "radio set": "radio zet",
            "zetkę": "radio zet", "zetka": "radio zet", "trójkę": "trójka", "trojke": "trójka",
            "trojka": "trójka", "jedynkę": "jedynka", "jedynke": "jedynka",
            "dwójkę": "dwójka", "dwojke": "dwójka", "357": "radio 357",
            "trzysta pięćdziesiąt siedem": "radio 357", "nowy swiat": "nowy świat",
            "nowego świata": "nowy świat",
            "rmf dla dzieci": "dla dzieci", "radio dla dzieci": "dla dzieci"}

# ("daj": "Daj jakąś muzykę" got an offer, nothing played — 13 Oct sweep)
_ON = re.compile(r"^(?:luna,? |luno,? )?(?:włącz|wlacz|puść|pusc|zagraj|odpal|graj|daj)\s+"
                 r"(?:(?:mi|nam)\s+)?(?:(?:radio|radijko|radyjko|radyjka|stację|stacje)\s*(.*)|(.+))$")
# "włącz radio z jakąś spokojną muzyką" — a kind of music, not a station name
# ("cat:…" — a kind from CATALOG, a different station of it each time)
_GENRES = [
    (r"jazz|dżez|dzez|smooth", "cat:jazz"),
    (r"klasyczn|poważn|powazn|opera|operow|chopin|fortepian|pianin|symfon|barok", "cat:classic"),
    (r"instrumentaln|bez\s+(?:śpiew|spiew|wokal|słów|slow|tekstu)|spokojn|relaks|do\s+pracy|do\s+nauki|do\s+czytania|skupi|koncentr|w\s+tle|chill|"
     r"lounge|łagodn|lagodn|wycisz|lo-?fi|ambient|do\s+snu|nastrojow|cich", "cat:calm"),
    (r"rock|alternatyw|gitar", "cat:rock"),
    (r"elektron|techno|house|electro|syntez", "cat:electronic"),
    # (13 Oct sweep: "Puść coś do biegania" — an offer, nothing played)
    (r"przebo|hit|pop|disco|tanecz|wesoł|wesol|imprez|biega|bieg\b|trening|ćwicz|cwicz|"
     r"energi|sport|siłown|silown|rower", "cat:hits"),
    (r"wiadomości|wiadomosci|informac|news|publicyst", "jedynka"),
    (r"ambitn|nowoczesn|indie|ciekaw", "nowy świat"),
    # (found online by "włącz radio dla dzieci": RMF Dla Dzieci)
    (r"dla\s+dzieci|dziecięc|dzieciec|dla\s+maj|bajk", "cat:kids"),
]
# the page to pick from — by meaning, not a few fixed phrases (15 Oct: "pokaż
# jakie masz radia", "jakie masz inne stacje radiowe", "pokaż stronę ze
# stacjami radiowymi" all went to the model): a show / which / list word and a
# word for radio stations, not a play / stop / "what's playing" request
_SHOW_WORD = re.compile(r"\b(?:pokaż|pokaz|wyświetl|wyswietl|otwórz|otworz|zobacz\w*|lista|listę|liste|"
                        r"listy|spis\w*|wyb[oó]r\w*|wybra\w*|wybierz\w*|jakie|jakich|które|ktore|"
                        r"co\s+masz|co\s+mamy|dostępn\w*|dostepn\w*|stron\w*|ekran\w*)\b")
_SHOW_NOUN = re.compile(r"stacj\w*|\bradi(?:a|ów|ow|ami|ach|o|om)\b|radyj\w*|rozgłośn\w*|rozglosn\w*")
_SHOW_NOT = re.compile(r"\b(?:włącz|wlacz|puść|pusc|zagraj|odpal|graj|wyłącz|wylacz|zmień|zmien|"
                       r"przełącz|przelacz|zatrzymaj|gra|grało|leci|teraz|śpiewa|spiewa|"
                       r"budź|budz|budzik\w*|lubi\w*|ulubion\w*|polec\w*|słuchasz|sluchasz|"
                       r"najlepsz\w*|myślisz|myslisz|sądzisz|sadzisz)\b"   # (an opinion: the model)
                       r"|to\s+za|jaka\s+to|która\s+to|ktora\s+to")


_FAV_ADD = re.compile(r"\b(?:dodaj|zapisz|zapamiętaj|zapamietaj|wrzuć|wrzuc)\s+(?:mi\s+)?"
                      r"(?:tę\s+|te\s+|tą\s+|ta\s+|to\s+|tej\s+)?(?:stację\s+|stacje\s+|radio\s+)?"
                      r"(?:do\s+)?(?:moich\s+)?ulubion"
                      r"|\b(?:lubię|lubie)\s+(?:tę|te|tą|ta|to)\s+(?:stację|stacje|radio)\b")
# "Ulubione." alone, "pokaż ulubione" — the page at the favourites
_FAV_SHOW = re.compile(r"^(?:luna,?\s+)?(?:(?:pokaż|pokaz)\s+(?:mi\s+)?)?(?:moje\s+)?ulubione"
                       r"(?:\s+(?:stacje|radia))?\W*$")
_FAV_DEL = re.compile(r"\b(?:usuń|usun|wyrzuć|wyrzuc|skasuj|wykreśl|wykresl)\b.*\bz\s+ulubionych")
# (18 Oct: "Spróbuj jeszcze raz włączyć ulubionych", "Coś z ulubionych." went to
# the model, whose command was refused — three tries, no music)
_FAV_PLAY = re.compile(r"\b(?:włącz\w*|wlacz\w*|puść|pusc|puścić|puscic|zagraj|zagrać|zagrac|daj|"
                       r"odpal\w*|przełącz\w*|przelacz\w*|zmień|zmien)"
                       r"(?:\s+(?:mi|nam|na|coś|cos|jakąś|jakas|jedną|jedna|którąś|ktoras|z|"
                       r"moją|moja|moje|moich|stację|stacje|radio))*\s+ulubion\w*"
                       r"|^(?:luna,?\s+)?(?:coś|cos|jakąś|jakas|cokolwiek|którąś|ktoras|jedną|jedna)"
                       r"\s+z\s+(?:moich\s+)?ulubionych\W*$")
_COUNT = re.compile(r"\bile\s+(?:masz\s+|mamy\s+|jest\s+)?(?:stacji|radi\w*|rozgłośni)"
                    r"|\bjakie\s+(?:masz\s+|mamy\s+)?(?:rodzaje|gatunki)\s+(?:muzyki|radia|stacji)")
# "coś podobnego", "inną w tym stylu" — the next of the same kind
_SIMILAR = re.compile(r"\b(?:coś|cos)\s+(?:innego\s+)?(?:podobnego|w\s+tym\s+(?:stylu|klimacie))"
                      r"|\binn\w+\s+(?:stację\s+|stacje\s+|radio\s+)?w\s+tym\s+(?:stylu|klimacie)"
                      r"|\bwięcej\s+takiej\s+muzyki|\bwiecej\s+takiej\s+muzyki")


def _show_asked(low):
    low = re.sub(r"^(?:a\s+|no\s+|to\s+)?(?:luna,?\s+|luno,?\s+)?", "", low)
    return (len(low.split()) <= 9 and bool(_SHOW_WORD.search(low))
            and bool(_SHOW_NOUN.search(low)) and not _SHOW_NOT.search(low))
# stations known by a broadcaster's name alone ("puść BBC") — looked up online
_BROADCASTERS = re.compile(r"(?:bbc|npr|kexp|fip|cnn|classic\s+fm|jazz\s+fm|virgin\s+radio|"
                           r"radio\s+paradise)\b")
# "puść jakieś radio, obojętnie jakie" — any station is fine (9 Oct model
# suite: she asked which one)
_ANY = re.compile(r"(?:(?:jakieś|jakies|jakąś|jakas|dowolne|dowolną|dowolna|byle\s+jakie|"
                  r"jakiekolwiek|cokolwiek|coś|cos)\s*)?(?:radio|stację|stacje|muzykę|muzyke)?"
                  r"[\s,]*(?:obojętnie\s+jak\w*|obojetnie\s+jak\w*|wszystko\s+jedno|"
                  r"jakiekolwiek|cokolwiek|dowolne)?")
_ALARM_ON = ("budź mnie radiem", "budz mnie radiem", "obudź mnie radiem",
             "obudz mnie radiem", "budzik z radiem", "budzenie radiem", "budzik radiem")
_ALARM_OFF = ("budź mnie dzwonkiem", "budz mnie dzwonkiem", "budzik bez radia",
              "budzik z dzwonkiem", "budzenie dzwonkiem")
_MUSIC = {"muzykę", "muzyke", "jakąś muzykę", "jakas muzyke", "muzyczkę", "coś do słuchania"}
_OFF = ("wyłącz radio", "wylacz radio", "stop radio", "zatrzymaj radio", "wyłącz muzykę",
        "wylacz muzyke", "zatrzymaj muzykę", "koniec radia", "radio stop", "ścisz radio do zera",
        # (the sweep files: "Wyłącz to radio" went to the model)
        "wyłącz to radio", "wylacz to radio", "wyłącz tę muzykę", "wyłącz tą muzykę",
        "zatrzymaj to radio", "stop muzyka")
# "Wznów radio", "wróć do radia" — the last station again (14 Oct probe: to the model)
_RESUME = re.compile(r"^(?:luna,?\s+)?(?:wznów|wznow|wróć\s+do|wroc\s+do|puść\s+dalej|"
                     r"pusc\s+dalej|graj\s+dalej|włącz\s+z\s+powrotem|wlacz\s+z\s+powrotem|"
                     r"włącz\s+znowu|wlacz\s+znowu|włącz\s+jeszcze\s+raz)\s+"
                     r"(?:radio|radia|muzykę|muzyke|muzyki)\W*$")
_WHAT = ("jakie to radio", "jaka to stacja", "co to za radio", "co to za stacja",
         "jakie radio gra", "jakie radio leci")
_SONG = ("co teraz gra", "co to za piosenka", "co to za utwór", "co to za utwor",
         "jaka to piosenka", "jaki to utwór", "jaki to utwor", "kto to śpiewa",
         "kto to spiewa", "co leci", "co to leci", "what song is this", "what's playing")
_NEXT = ("następna stacja", "nastepna stacja", "zmień stację", "zmien stacje",
         "inna stacja", "inną stację", "inna stacje", "next station", "kolejna stacja")
# "Weź jakieś inne radio, to jest paskudne." (11 Oct: the model asked which
# station instead) — the first clause alone; a complaint may follow
_NEXT_RX = re.compile(
    r"(?:luna\s+)?(?:(?:weź|wez|daj|puść|pusc|włącz|wlacz|zmień|zmien|przełącz|przelacz)\s+)?"
    r"(?:mi\s+|nam\s+)?(?:jakieś\s+|jakies\s+|jakąś\s+|jakas\s+)?"
    r"(?:inn[aeąy]|następn[aąe]|nastepn[aae]|kolejn[aąe])\s+(?:stacj[aeę]|radio)"
    r"|(?:zmień|zmien|przełącz|przelacz)\s+(?:tę\s+|te\s+|to\s+)?(?:stację|stacje|radio)"
    r"|(?:weź|wez|daj|puść|pusc|włącz|wlacz)\s+(?:mi\s+)?coś\s+innego")


def _next_asked(low):
    """Another station, said with something after it — only while one plays."""
    first = re.split(r"[,.;!?]|\s+(?:bo|to\s+jest|ta\s+jest|ten\s+jest)\s+", low, maxsplit=1)[0]
    return bool(playing() and _NEXT_RX.fullmatch(first.strip()))


_QUIETER = ("ciszej", "ścisz", "scisz", "przycisz", "quieter")
_LOUDER = ("głośniej", "glosniej", "podgłośnij", "podglosnij", "pogłośnij", "louder")
_SLEEP = re.compile(r"(?:wyłącz|wylacz)\s+(?:radio|muzykę|muzyke)\s+za\s+(.+)$|"
                    r"radio\s+(?:na|przez)\s+(.+)$")

_SLEEP_AT = re.compile(r"(?:wyłącz|wylacz)\s+(?:radio|muzykę|muzyke)\s+o\s+(?:godzinie\s+)?"
                       r"[\w:.]+(?:\s+\w+)?$")

_lock = threading.Lock()
_player = None             # {"name", "url", "stop": Event, "thread", "until"}
_say = [None]              # speak(), for "the stream died" from the player thread


# ── which station ─────────────────────────────────────────────────────────────

_MIRRORS = ("de1", "de2", "all")


def _search(q, country):
    """One radio-browser.info search, trying the next mirror when one fails
    (fi1/at1/nl1 were down on 9 Oct); None if no mirror answered."""
    for host in _MIRRORS:
        url = (f"https://{host}.api.radio-browser.info/json/stations/search?name="
               f"{urllib.parse.quote(q)}{country}&order=votes&reverse=true&limit=5&hidebroken=true")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Luna-robot/1.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.load(r)
        except Exception as e:
            print(f"[radio] lookup on {host} failed: {e}", flush=True)
    return None


def _lookup(name):
    """radio-browser.info: the most voted working station by that name. The
    search is by substring, so "polskie radio chopin" finds nothing ("Polskie
    Radio - Chopin") — shorter forms are tried too (9 Oct sweep)."""
    words = name.split()
    tries = [name]
    short = re.sub(r"^(?:polskie\s+)?radio\s+", "", name, flags=re.I)
    if short != name and short:
        tries.append(short)
    if len(words) > 1 and words[-1] not in tries:
        tries.append(words[-1])
    for q in tries:
        for country in ("&countrycode=PL", ""):
            found = _search(q, country)
            if found is None:
                return None
            for s in found:
                if s.get("url_resolved") and s.get("codec", "").upper() in ("MP3", "AAC", "AAC+", "OGG"):
                    return _spoken(s["name"]), s["url_resolved"]
    return None


def _spoken(name):
    """"Polskie Radio - Chopin (Radio Chopin) (AAC+)" → "Polskie Radio Chopin"."""
    out = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", name)
    out = re.sub(r"\s+[-–|]\s+", " ", out).strip(" -|")
    # "Radio Paradise Main Mix 320k AAC" — she read the bitrate out
    out = re.sub(r"\s+\d{2,3}\s*k(?:bps)?\b.*$|\s+(?:AAC\+?|MP3|OGG|HQ)$", "", out, flags=re.I)
    return out or name.strip()


def _station(words):
    """(spoken name, url) for what was said after "włącz radio", or None."""
    import settings
    w = words.strip(" .!?").lower()
    w = re.sub(r"^(?:radio|stację|stacje)\s+", "", w)
    if _ANY.fullmatch(w):                   # "puść jakieś radio, obojętnie jakie"
        w = ""
    if not w:                              # "włącz radio": your last station
        mine = (settings.get("radio_last_by", {}) or {}).get(_who())
        if not mine and _child_here():
            return _pick("kids")           # a child: their radio
        last = mine or settings.get("radio_last")
        return tuple(last) if last else _pick(_default_kind())
    if w.startswith("cat:") and w.split(":")[1] in _CAT:
        return _pick(w.split(":")[1], instrumental=w.endswith(":i"))
    key = _ALIASES.get(w, w)
    if key in STATIONS:
        return STATIONS[key]
    for k, v in STATIONS.items():
        if key in k or k in key:
            return v
    saved = settings.get("radio_found", {})
    if key in saved:
        return tuple(saved[key])
    for n, u in favs() + [(s[0], s[1]) for _, _, _, sts in CATALOG for s in sts]:
        if n.lower() == key:                # a favourite / the catalog's own stream
            return n, u
    found = _lookup(w)
    if found:
        saved[key] = list(found)
        settings.put("radio_found", saved)
    return found


# ── playback ──────────────────────────────────────────────────────────────────

def _who():
    with state.lock:
        return state.person[0] if state.person else None


def _remember_station(name, url):
    """The last station, for the house and for whoever asked (by face)."""
    import settings
    settings.put("radio_last", [name, url])
    recent = [r for r in settings.get("radio_recent", []) or [] if r[0] != name]
    settings.put("radio_recent", [[name, url]] + recent[:11])
    who = _who()
    if who:
        by = settings.get("radio_last_by", {}) or {}
        by[who] = [name, url]
        settings.put("radio_last_by", by)
        cat = _category_of(name)
        if cat:                            # the page opens at your kind
            kb = settings.get("radio_kind_by", {}) or {}
            kb[who] = cat
            settings.put("radio_kind_by", kb)


def _die_with_parent():
    """Children get SIGTERM when Luna's process dies — even killed -9 or
    crashed — so the music can never keep playing without her."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except Exception:
        pass


def _acc(name):
    """"Włączam …": Trójka → Trójkę."""
    return name[:-1] + "ę" if name.endswith("ka") else name


def _sink():
    try:
        from openai_tts import tts
        return tts._sink
    except Exception:
        return None


NIGHT_FROM, NIGHT_TO = 21, 7                # the night volume is its own


def _level_key(now=None):
    """The radio keeps two volumes: the day's and the night's — "ciszej" at
    ten in the evening doesn't make the morning radio a whisper, and the
    evening one isn't blaring after a loud afternoon."""
    h = time.localtime(now if now is not None else time.time()).tm_hour
    return "radio_level_night" if h >= NIGHT_FROM or h < NIGHT_TO else "radio_level"


def _gain(now=None):
    import settings
    key = _level_key(now)
    day = settings.get("radio_level", RADIO_GAIN)
    if key == "radio_level":
        return day
    return settings.get(key, round(min(day, 0.7), 3))   # night: never louder than 70%


def _set_gain(g):
    import settings
    g = round(max(0.1, min(2.5, g)), 3)
    settings.put(_level_key(), g)
    print(f"[radio] music volume → {g:.0%} ({'night' if 'night' in _level_key() else 'day'})",
          flush=True)
    return g


_KEEP_LEVEL = re.compile(r"\b(?:zapamiętaj|zapamietaj|zostaw|zapisz)\s+(?:tę|te|taką|taka|tą|ta|tak[aą]?)?\s*"
                         r"(?:głośność|glosnosc|poziom)")


NAME_DUCK_SECS = 4.0       # "Luna" heard mid-sentence: quiet for the rest of it


def _ducked():
    # (and as soon as her name is in the words still being said — not only
    # once the sentence has ended: 17 Oct the radio, loud under "Luna, ustaw
    # ekran…", made half of it unreadable)
    with state.lock:
        return (state.speaking or state.listening or state.conversation_active
                or time.time() - state.name_heard_at < NAME_DUCK_SECS)


def _open_icy(url):
    """(response, metaint, ffmpeg format) when the server sends ICY titles;
    "dead" when the server refused (ICY/HTTP 4xx-5xx) — try another address;
    else None — then ffmpeg reads the URL itself."""
    try:
        req = urllib.request.Request(url, headers={"Icy-MetaData": "1",
                                                   "User-Agent": "Luna-robot/1.0"})
        r = urllib.request.urlopen(req, timeout=8)
        mi = int(r.headers.get("icy-metaint") or 0)
        ctype = (r.headers.get("content-type") or "").lower()
        fmt = "mp3" if "mpeg" in ctype else "aac" if "aac" in ctype else None
        if mi and fmt:
            return r, mi, fmt
        r.close()
    except Exception as e:
        msg = " ".join(str(e).split())
        if re.search(r"(ICY|HTTP Error) [45]\d\d", msg):
            print(f"[radio] {url} refused: {msg}", flush=True)
            return "dead"
        print(f"[radio] no ICY titles ({msg}) — ffmpeg reads the stream", flush=True)
    return None


def _feed(p, r, mi, dec):
    """Copy the audio into ffmpeg; every `mi` bytes comes a title block."""
    try:
        while not p["stop"].is_set():
            data = r.read(mi)
            if not data:
                break
            dec.stdin.write(data)
            n = r.read(1)
            if not n:
                break
            if n[0]:
                meta = r.read(n[0] * 16)
                m = re.search(rb"StreamTitle='(.*?)';", meta)
                title = m.group(1).decode("utf-8", "replace").strip(" -") if m else ""
                if title and title != p.get("title"):
                    p["title"] = title
                    print(f"[radio] now playing: {title}", flush=True)
                    visualizer.new_song(title)
    except Exception:
        pass
    finally:
        for close in (dec.stdin.close, r.close):
            try:
                close()
            except Exception:
                pass


def _play(p):
    """Decode → gain → pw-play, until p["stop"] is set. Reconnects a few times."""
    out_cmd = ["pw-play", "--raw", f"--rate={RATE}", "--format=s16",
               f"--channels={CHANNELS}", "--media-role=Music"]
    if _sink():
        out_cmd += ["--target", _sink()]
    out = subprocess.Popen(out_cmd + ["-"], stdin=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
    p["out"] = out
    visualizer.set_kind(_category_of(p["name"]))     # (its colours)
    gain = 0.0
    fails = 0
    urls = [p["url"]] + FALLBACKS.get(p["url"], [])
    alt = 0                                  # which of them is playing
    try:
        while not p["stop"].is_set() and fails <= RETRIES:
            p["url"] = urls[alt % len(urls)]
            icy = _open_icy(p["url"])
            if icy == "dead":
                if len(urls) > 1:
                    alt += 1
                fails += 1
                time.sleep(0.3)
                continue
            if icy:
                src = ["-f", icy[2], "-i", "pipe:0"]
            else:
                src = ["-reconnect", "1", "-reconnect_streamed", "1",
                       "-reconnect_delay_max", "5", "-i", p["url"]]
            dec = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error"] + src +
                ["-f", "s16le", "-ac", str(CHANNELS), "-ar", str(RATE), "-"],
                stdin=subprocess.PIPE if icy else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                preexec_fn=_die_with_parent)
            p["dec"] = dec
            if icy:
                threading.Thread(target=_feed, args=(p, icy[0], icy[1], dec),
                                 daemon=True, name="radio-icy").start()
            got = 0
            level = MUSIC_RMS                    # the station's loudness, measured as it plays
            while not p["stop"].is_set():
                if p.get("until") and time.time() > p["until"]:
                    print("[radio] sleep timer — off", flush=True)
                    p["stop"].set()
                    break
                data = dec.stdout.read(CHUNK)
                if not data:
                    break
                got += len(data)
                a = np.frombuffer(data, np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(a * a))) if a.size else 0.0
                if rms > 300:                        # (not a quiet moment between songs)
                    level += (rms - level) * 0.03    # ~3 s to settle on a station
                e = rms / max(level, 1.0)
                _pulse[0] += (e - _pulse[0]) * 0.6
                _pulse[1] += (e - _pulse[1]) * 0.05
                if not p.get("ok") and got > RATE * 4 * 20:
                    p["ok"] = True                   # it plays: not dead (any more)
                    if p.get("url0") in dead():
                        _mark(p["url0"], False)
                norm = min(2.5, max(0.2, MUSIC_RMS / max(level, 1.0)))
                target = _gain() * norm * (RADIO_DUCK if _ducked() else 1.0)
                if p.get("fade"):                    # an alarm: from a whisper up
                    target *= min(1.0, 0.05 + (time.time() - p["t0"]) / p["fade"])
                new = target if abs(target - gain) < 0.01 else gain + (target - gain) * 0.5
                try:                                 # the face sees it as it's heard
                    visualizer.tap(a, level, out.stdin.fileno(), CHANNELS)
                except Exception as e:
                    if not p.get("vis_err"):
                        p["vis_err"] = True
                        print(f"[vis] {e}", flush=True)
                ramp = np.linspace(gain, new, a.size // CHANNELS).repeat(CHANNELS)
                gain = new                           # ~0.3 s to duck, no clicks
                out.stdin.write((a * ramp).clip(-32768, 32767).astype(np.int16).tobytes())
            dec.kill()
            dec.wait()
            if p["stop"].is_set():
                break
            fails = 0 if got > RATE * 4 * 30 else fails + 1    # ran 30 s+ → fresh tries
            if got < RATE * 4 and len(urls) > 1:
                alt += 1                                     # didn't even start: next address
                print(f"[radio] trying {urls[alt % len(urls)]}", flush=True)
            if fails == RETRIES and not p.get("looked_up"):
                p["looked_up"] = True                        # last resort: the directory
                found = _lookup(p["name"])
                if found and found[1] not in urls:
                    urls.append(found[1])
                    alt = len(urls) - 1
                    print(f"[radio] directory says: {found[1]}", flush=True)
            print(f"[radio] stream ended — reconnecting ({fails}/{RETRIES})", flush=True)
            time.sleep(min(2 * fails, 4))
    except (BrokenPipeError, OSError) as e:
        if not p["stop"].is_set():               # a stop kills the player on purpose
            print(f"[radio] player failed: {e}", flush=True)
    finally:
        try:
            out.stdin.close()
        except OSError:
            pass
        out.terminate()
        global _player
        with _lock:
            if _player is p:
                _player = None
            idle = _player is None
        if idle:
            with state.lock:
                if not (state.radio or "").startswith("♪"):   # a sleep sound took over
                    state.radio = None
        _pulse[:] = [0.0, 0.0]
        visualizer.reset()
        if not p["stop"].is_set():
            print("[radio] gave up", flush=True)
            _mark(p.get("url0") or p["url"], True)
            # another station of the same kind, rather than silence (at most
            # three such moves in ten minutes)
            cat = _category_of(p["name"])
            _switched[:] = [t for t in _switched if time.time() - t < 600]
            alt = _pick(cat) if cat and not p.get("alarm") and len(_switched) < 3 else None
            if alt and alt[0] != p["name"]:
                _switched.append(time.time())
                if _say[0]:
                    _say[0](f"{p['name']} nie odpowiada — włączam {_acc(alt[0])}.")
                threading.Thread(target=lambda: (play(*alt), _remember_station(*alt)),
                                 daemon=True).start()
            elif _say[0]:
                _say[0]("Radio przestało grać — nie mogę się połączyć ze stacją.")


def play(name, url, until=None, fade=0, alarm=False):
    stop()
    try:
        import ambience                          # one sound at a time
        ambience.stop()
    except Exception:
        pass
    # (a second's fade in, not a blast; an alarm: its own long one)
    p = {"name": name, "url": url, "url0": url, "stop": threading.Event(), "until": until,
         "fade": fade or 1.5, "alarm": alarm, "t0": time.time()}
    p["thread"] = threading.Thread(target=_play, args=(p,), daemon=True, name="radio")
    with _lock:
        global _player
        _player = p
    with state.lock:
        state.radio = name
    p["thread"].start()
    print(f"[radio] playing {name} ({url})", flush=True)


def stop():
    global _player
    with _lock:
        p, _player = _player, None
    if p:
        p["stop"].set()
        for proc in (p.get("dec"), p.get("out")):
            if proc:
                try:
                    proc.kill()
                except OSError:
                    pass
        print(f"[radio] stopped {p['name']}", flush=True)
    with state.lock:
        if not (state.radio or "").startswith("♪"):   # sleep sounds keep their note
            state.radio = None
    return p is not None


def wake_up_radio():
    """A wake-up alarm rings: the radio instead of the chime, if asked for.
    True when the radio started."""
    import settings
    if not settings.get("alarm_radio", False) or playing():
        return False
    st = _station("")
    play(st[0], st[1], fade=60, alarm=True)
    return True


def stop_alarm():
    """"Jeszcze 5 minut" after a radio alarm: the music stops too."""
    with _lock:
        p = _player
    return stop() if p and p.get("alarm") else False


def stop_for_the_night():
    """"Dobranoc": quiet — unless a sleep timer was set on purpose."""
    with _lock:
        p = _player
    if p and not p.get("until"):
        stop()


def playing():
    with _lock:
        return _player["name"] if _player else None


# ── commands ──────────────────────────────────────────────────────────────────

def _minutes(text):
    import timers
    secs, _ = timers.parse_duration(text)
    return secs if secs and secs <= 4 * 3600 else None


def answer_question(text, speak):
    """"Jakie to radio?", "co teraz gra?" — questions, so commands.py asks
    here before its question guard. True when answered."""
    low = text.lower().strip(" .!?")
    if any(k in low for k in _WHAT) and len(low.split()) <= 6:
        now = playing()
        with _lock:
            where = _player.get("from") if _player else None
        speak((f"Gra {now}" + (f" — radio {where}." if where else ".")) if now
              else "Radio nie gra.")
        return True
    if playing() and any(k in low for k in _SONG) and len(re.findall(r"\w+", low)) <= 7:
        with _lock:
            title = _player.get("title") if _player else None
        speak(f"Teraz gra: {title.rstrip('.!?')}." if title else
              f"Gra {playing()}, ale stacja nie podaje tytułu piosenki.")
        return True
    return False


def handle(text, speak):
    """Radio commands. True when handled."""
    import settings
    _say[0] = speak
    low = text.lower().strip(" .!?")
    if _RESUME.match(low):
        text = low = "włącz radio"             # your last station (_station)
    if _COUNT.search(low):                 # "ile masz stacji?"
        n = sum(len(sts) for _, _, _, sts in CATALOG)
        names = [said for _, _, said, _ in CATALOG]
        speak(f"Mam {n} stacji: " + ", ".join(names[:-1]) + f" i {names[-1]}. "
              "Pokazuję je na ekranie.")
        show_page()
        return True
    if _FAV_SHOW.match(low):               # "Ulubione." (15 Oct: went to the model)
        if not favs():
            speak("Nie masz jeszcze ulubionych stacji — gdy gra taka, którą lubisz, "
                  "powiedz „dodaj do ulubionych”.")
        else:
            show_page("fav")
            speak("Twoje ulubione stacje.")
        return True
    if _FAV_PLAY.search(low):              # "włącz moją ulubioną stację"
        fs = favs()
        if not fs:
            speak("Nie masz jeszcze ulubionych stacji — gdy gra taka, którą lubisz, "
                  "powiedz „dodaj do ulubionych”.")
            return True
        import random
        name, url = random.choice([f for f in fs if f[0] != playing()] or fs)
        speak(f"Włączam {_acc(name)}.")
        play(name, url)
        _remember_station(name, url)
        return True
    if _FAV_DEL.search(low):
        # a favourite named ("usuń Lofi z ulubionych") — not the one playing
        named = next((n for n, _ in favs() if n.lower() in low), None)
        if named:
            fav_toggle(named, "")
            speak(f"Usunęłam {_acc(named)} z ulubionych.")
            return True
        if not playing():
            speak("Teraz nic nie gra. Powiedz, którą stację usunąć z ulubionych.")
            return True
    if _FAV_ADD.search(low) or _FAV_DEL.search(low):
        now = playing()
        if not now:
            speak("Teraz nic nie gra — włącz stację, którą lubisz, i wtedy ją dodam.")
            return True
        on = any(n == now for n, _ in favs())
        if _FAV_DEL.search(low):
            if on:
                fav_toggle(now, _current_url())
            speak(f"Usunęłam {_acc(now)} z ulubionych." if on else f"{now} nie jest w ulubionych.")
        else:
            if not on:
                fav_toggle(now, _current_url())
            speak(f"Dodałam {_acc(now)} do ulubionych.")
        return True
    if _show_asked(low):
        show_page()
        speak("Oto moje stacje.")          # ("Wybierz stację" came out "Vediš stacje")
        return True
    if any(k in low for k in _ALARM_ON + _ALARM_OFF):
        on = any(k in low for k in _ALARM_ON)
        settings.put("alarm_radio", on)
        print(f"[radio] alarm with radio: {on}", flush=True)
        if len(low.split()) > 6 or re.search(r"\bo\s+(?:\d|\w+ej\b)|\bna\s+\d|godzin|jutro|rano",
                                               low):
            return False                   # "…o siódmej" — the model sets the alarm
        speak("Dobrze, budzik obudzi cię radiem, po cichutku coraz głośniej." if on
              else "Dobrze, budzik znowu będzie dzwonił.")
        return True
    if answer_question(text, speak):
        return True
    words = re.findall(r"\w+", low)
    m = re.search(r"\b(?:zmień|zmien|przełącz|przelacz)\s+(?:stację\s+|stacje\s+|radio\s+)?na\s+(.+)$",
                  low)
    if m:
        # "zmień stację na RMF" — that station, not the next one (7 Oct probe:
        # it answered "Teraz Jedynka")
        low = f"włącz {m.group(1)}"
        words = low.split()
    elif ((any(k in low for k in _NEXT) and len(words) <= 5) or _next_asked(low)
          or (playing() and _SIMILAR.search(low))):   # "coś podobnego"
        if _world_next(speak):             # the next one of "radio z Francji"
            return True
        now = playing()
        cat = _category_of(now) if now else None
        if cat:                            # the next one of the same kind
            sts = _CAT[cat][2]
            i = next(k for k, s in enumerate(sts) if s[0] == now)
            name, url, _ = sts[(i + 1) % len(sts)]
            speak(f"Teraz {name}.")
            play(name, url)
            _remember_station(name, url)
            return True
        names = list(STATIONS.values())
        i = next((k for k, st in enumerate(names) if st[0] == now), -1)
        name, url = names[(i + 1) % len(names)]
        speak(f"Teraz {name}.")
        play(name, url)
        _remember_station(name, url)
        return True
    # "ciszej" while music plays: the music. "mów ciszej": her voice (commands.py)
    if (playing() and len(words) <= 6 and not any(w.startswith("mów") or w == "mow" for w in words)
            and any(k in low for k in _QUIETER + _LOUDER)):
        g = _gain()
        m = re.search(r"(\d{1,3})\s*(%|procent)?", low)
        if m:
            g = int(m.group(1)) / 100
        else:
            step = 1.5 if any(k in low for k in _LOUDER) else 1 / 1.5
            if "dużo" in low or "duzo" in low:
                step = step ** 2
            g *= step
        _set_gain(g)
        return True                        # the music itself is the answer
    if playing() and _KEEP_LEVEL.search(low):
        # "zapamiętaj tę głośność": it is already kept — say which one
        part = "wieczorem i w nocy" if "night" in _level_key() else "w dzień"
        speak(f"Zapamiętane: radio {part} gra na {round(_gain() * 100)} procent.")
        return True
    m = _SLEEP.search(low)
    at = _SLEEP_AT.search(low)
    if at and not m:
        # "wyłącz radio o 22" / "…o dziesiątej wieczorem" — until that time today
        # (or tonight / tomorrow early, if it has already passed)
        import errands
        hm, _ = errands._when(at.group(0))
        if hm:
            hh, mm = (int(x) for x in hm.split(":"))
            if hh < 12 and re.search(r"wieczor|w\s+nocy", low):
                hh += 12
            t = time.localtime()
            target = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hh, mm, 0, 0, 0, -1))
            if target <= time.time():
                target += 12 * 3600 if hh < 12 and target + 12 * 3600 > time.time() else 86400
            secs = int(target - time.time())
            with _lock:
                p = _player
            if p:
                p["until"] = target
            else:
                st = _station("")
                play(st[0], st[1], until=target)
            import clock
            lt = time.localtime(target)
            speak(f"Dobrze, radio wyłączy się o {clock.hour_locative(lt.tm_hour, lt.tm_min)}.")
            return True
    if m and ("radio" in low or "muzyk" in low):
        secs = _minutes(m.group(1) or m.group(2))
        if secs:
            with _lock:
                p = _player
            if p:
                p["until"] = time.time() + secs
            else:
                st = _station("")
                play(st[0], st[1], until=time.time() + secs)
            import timers
            speak(f"Dobrze, radio wyłączy się za {timers.say_duration(secs)}.")
            return True
    if any(k in low for k in _OFF) and len(low.split()) <= 6:
        if not stop():
            speak("Radio nie gra.")
        return True
    m = _ON.match(low)
    if not m:
        return False
    if _world_play(m.group(1) if m.group(1) is not None else m.group(2), speak):
        return True                        # "…z Francji", "francuski jazz", "reggae"
    if m.group(1) is None:                 # "włącz trójkę" — only a known station
        key = _ALIASES.get(m.group(2).strip(), m.group(2).strip())
        if key in _MUSIC or (key and _ANY.fullmatch(key.strip(" .!?"))):
            what = ""                      # "włącz muzykę" → the last station
        elif (re.match(r"(?:jakąś|jakas|jakieś|jakies|trochę|troche|coś|cos)\s+|muzyk|muzyczk|piosenk",
                       key) and any(re.search(rx, key) for rx, _ in _GENRES)):
            what = key                     # "puść muzykę dla dzieci" (7 Oct: went to
                                           # the model), "jakieś radio rockowe", "coś
                                           # spokojnego do pracy" (11 Oct sweep: "Nie
                                           # znalazłam stacji…", "Nie mogę…") → the genre
        elif _BROADCASTERS.match(key):
            what = key                     # "puść BBC" (11 Oct sweep: the model refused)
        elif re.search(r"\bradio\b|\bfm\b", key) and len(key.split()) <= 6:
            what = key                     # "włącz Polskie Radio Chopin", "włącz BBC Radio 1"
        elif _kind_asked(key):
            what = key                     # "włącz jazz" → a jazz station
        elif known(key):
            what = key                     # "włącz Classic Vinyl HD" — a favourite
        elif key not in STATIONS:
            return False
        else:
            what = key
    else:
        what = m.group(1)
    genre = next((key for rx, key in _GENRES if re.search(rx, what or "")), None)
    if genre and (_kind_asked(what) or not what or what.split()[0] in ("z", "ze", "jakąś", "jakas", "jakieś", "jakies",
                                                  "coś", "cos")
                  or re.search(r"muzyk|muzyczk|piosenk", what)
                  or re.fullmatch(r"\w+(?:owe|ową|owa|owego|czne|czną)", what)):   # "radio rockowe"
        what = genre                       # "…z jakąś spokojną muzyką" → Dwójka
        if genre.startswith("cat:") and _NO_VOICE.search(low):
            what += ":i"                   # "…ale bez śpiewania"
    if len(what.split()) > 4:
        return False
    st = _station(what)
    if not st:
        speak(f"Nie znalazłam stacji {what}.")
        return True
    name, url = st
    kind = what.split(":")[1] if what.startswith("cat:") else None
    said = _CAT[kind][1] if kind in _CAT else ""
    if said and what.endswith(":i"):
        said += " bez śpiewu"
    speak(f"Włączam {_acc(name)}" + (f" — {said}." if said else "."))
    play(name, url)
    _remember_station(name, url)
    return True


# ── the page: kinds on the left, their stations to tap (15 Oct) ───────────────

PAGE_SECS = 90             # the page stays this long after the last tap
_TIMER_STEPS = (15, 30, 60)                # the page's sleep-timer button, minutes


def _blurb(name):
    """A few words about a station (the catalogue's), for the page."""
    cat = _category_of(name)
    if cat:
        return next(b for n, _, b in _CAT[cat][2] if n == name)
    return "z wyszukiwania"


def page_kinds():
    """The page's kinds: your favourites and the last played first (when
    there are any), then the catalogue — [(key, label, [(name, url, blurb)])]."""
    import settings
    out = []
    fs = favs()
    if fs:
        out.append(("fav", "Ulubione", [(n, u, _blurb(n)) for n, u in fs]))
    recent = settings.get("radio_recent", []) or []
    if recent:
        out.append(("recent", "Ostatnie", [(n, u, _blurb(n)) for n, u in recent[:8]]))
    return out + [(k, label, sts) for k, label, _, sts in CATALOG]


def _child_here():
    try:
        import commands
        return commands._child_here()
    except Exception:
        return False


def _default_kind():
    """Where the page and a bare "włącz radio" (nothing remembered) start:
    the kind of the one playing, else yours (by face), else a child's, else
    the time of day — Polish radio at breakfast, calm music through the
    working day, jazz in the evening, calm again at night."""
    import settings
    cat = _category_of(playing() or "")
    if cat:
        return cat
    mine = (settings.get("radio_kind_by", {}) or {}).get(_who())
    if mine in _CAT:
        return mine
    if _child_here():
        return "kids"
    h = time.localtime().tm_hour
    return "polish" if 6 <= h < 9 else "jazz" if 17 <= h < 22 else "calm"


def show_page(cat=None):
    """The station page, at that kind (or _default_kind's)."""
    keys = [k for k, _, _ in page_kinds()]
    cat = cat if cat in keys else _default_kind()
    with state.lock:
        state.overlay = ("radio", time.time() + PAGE_SECS, {"cat": cat})


def page_list(data):
    """(kinds, index of the one shown) — the kind kept when favourites come
    and go (it is a key, not a position)."""
    kinds = page_kinds()
    keys = [k for k, _, _ in kinds]
    if data.get("cat") not in keys:
        data["cat"] = _default_kind()
    return kinds, keys.index(data["cat"])


def now_title():
    """The song playing (ICY title), or None."""
    with _lock:
        return _player.get("title") if _player else None


def until():
    """When the sleep timer stops the radio (time.time()), or None."""
    with _lock:
        return _player.get("until") if _player else None


def _toast(data, text):
    data["toast"] = (text, time.time() + 2.0)


def _page_data():
    with state.lock:
        ov = state.overlay
        if not ov or ov[0] != "radio":
            return None
        state.overlay = (ov[0], time.time() + PAGE_SECS, ov[2])
        return ov[2]


def tap(x, y, W, H):
    """A tap (px) on the station page: a kind, a station (plays it), its
    star, Stop, quieter / louder, the sleep timer."""
    import settings
    import ui_screens
    data = _page_data()
    if data is None:
        return False
    kinds, ci = page_list(data)
    hit = ui_screens.radio_hit(x, y, W, H, data)
    if not hit:
        return True                        # (a tap on the page doesn't close it)
    if hit[0] == "cat":
        data["cat"] = kinds[hit[1]][0]
    elif hit[0] == "stop":
        stop()
    elif hit[0] == "st":
        name, url, _ = kinds[ci][2][hit[1]]
        if playing() != name:
            play(name, url)
            _remember_station(name, url)
    elif hit[0] == "star":
        name, url, _ = kinds[ci][2][hit[1]]
        _toast(data, f"{name}: w ulubionych" if fav_toggle(name, url)
               else f"{name}: usunięta z ulubionych")
    elif hit[0] in ("vol-", "vol+"):
        g = _set_gain(_gain() * (1.25 if hit[0] == "vol+" else 1 / 1.25))
        _toast(data, f"Głośność {int(round(g * 100))}%")
    elif hit[0] == "timer":
        left = until()
        mins = (left - time.time()) / 60 if left else 0
        nxt = next((m for m in _TIMER_STEPS if m > mins + 1), None)
        with _lock:
            if _player:
                _player["until"] = time.time() + nxt * 60 if nxt else None
        _toast(data, f"Wyłączę za {nxt} minut" if nxt else "Gra bez wyłączania")
    return True


def swipe(dx):
    """A swipe on the page: the next kind (to the left) or the one before."""
    data = _page_data()
    if data is None:
        return False
    kinds, ci = page_list(data)
    data["cat"] = kinds[(ci + (1 if dx < 0 else -1)) % len(kinds)][0]
    return True


# ── favourites, the last played, stations that don't answer ───────────────────

def favs():
    """[(name, url)] — the house's favourite stations."""
    import settings
    return [tuple(f) for f in settings.get("radio_favs", []) or []]


def model_command(label):
    """A label from the model's command list that handle() runs: a kind of
    music, the stations page, the favourites (22 Oct: "włącz muzykę
    elektroniczną", listed in her prompt, refused three times in a row)."""
    low = (label or "").lower().strip(" .!?")
    if (_FAV_ADD.search(low) or _FAV_DEL.search(low) or _FAV_SHOW.match(low)
            or _FAV_PLAY.search(low) or _show_asked(low)):
        return True
    m = re.match(r"(?:włącz|wlacz|puść|pusc)\s+(.{2,60})$", low)
    return bool(m) and len(m.group(1).split()) <= 6 and any(
        re.search(rx, m.group(1)) for rx, _ in _GENRES)


def known(name):
    """A station she already has — the catalog, a favourite, one found before
    (no network): the model may send "włącz <it>" (18 Oct: "włącz Classic Vinyl
    HD" was refused)."""
    import settings
    w = re.sub(r"^(?:radio|stację|stacje)\s+", "", (name or "").strip(" .!?").lower())
    if not w:
        return False
    key = _ALIASES.get(w, w)
    names = ({k.lower() for k in STATIONS} | {v[0].lower() for v in STATIONS.values()}
             | {n.lower() for n, _ in favs()} | set(settings.get("radio_found", {}) or {}))
    names |= {s[0].lower() for _, _, _, sts in CATALOG for s in sts}
    return key in names


def fav_toggle(name, url):
    """Adds or removes a favourite; True when it is one now."""
    import settings
    fs = favs()
    if any(n == name for n, _ in fs):
        settings.put("radio_favs", [list(f) for f in fs if f[0] != name])
        return False
    settings.put("radio_favs", [list(f) for f in fs] + [[name, url]])
    return True


def _current_url():
    with _lock:
        return (_player.get("url0") or _player["url"]) if _player else None


_DEAD_SECS = 6 * 3600      # a station that didn't answer is skipped this long


def dead():
    """URLs of stations that didn't answer lately (skipped, greyed)."""
    import settings
    d = settings.get("radio_dead", {}) or {}
    return {u for u, t in d.items() if time.time() - t < _DEAD_SECS}


def _mark(url, is_dead):
    import settings
    d = settings.get("radio_dead", {}) or {}
    if is_dead:
        d[url] = time.time()
    elif url in d:
        d.pop(url)
    else:
        return
    settings.put("radio_dead", d)


def health_check():
    """Every catalogue stream decoded for a second (ffmpeg, no sound): the
    dead marked (skipped, greyed on the page), the live cleared."""
    bad = []
    for _, _, _, sts in CATALOG:
        for name, url, _ in sts:
            if playing() == name:
                continue
            try:
                ok = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-t", "1",
                                     "-i", url, "-f", "null", "-"], timeout=25,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL).returncode == 0
            except Exception:
                ok = False
            _mark(url, not ok)
            if not ok:
                bad.append(name)
    print(f"[radio] health check: {len(bad)} not answering {bad}", flush=True)
    return bad


def start_background():
    """The nightly health check, at 4:40 (main.py starts it)."""
    def loop():
        while True:
            t = time.localtime()
            at = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 4, 40, 0, 0, 0, -1))
            if at <= time.time():                 # tomorrow: a calendar day (DST nights)
                at = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 4, 40, 0, 0, 0, -1))
            time.sleep(max(60.0, at - time.time()))
            try:
                health_check()
            except Exception as e:
                print(f"[radio] health check failed: {e}", flush=True)
    threading.Thread(target=loop, daemon=True, name="radio-health").start()


# the music's beat, roughly: a fast and a slow loudness (robot_face sways)
_pulse = [0.0, 0.0]


def music_pulse():
    """0..1 — the music louder than lately (a beat, roughly); 0 when off."""
    if _player is None:
        return 0.0
    return max(0.0, min(1.0, (_pulse[0] - _pulse[1]) * 1.5))


_switched = []             # when the radio moved on from a dead station (a cap)


# ── the world's radio: by country, by kind of music (11 Oct) ──────────────────
# "Włącz radio z Francji", "włoskie radio", "francuski jazz", "radio reggae",
# "jakieś zagraniczne radio" — radio-browser.info's most voted working stations
# for that country / tag; "następna stacja" then goes through them.
# (Andrzej: "more radio stations including abroad, not only a few Polish ones")

# (stem, ISO code, "z Francji" — how she says where it is from)
_COUNTRIES = [
    (r"franc", "FR", "z Francji"), (r"niemc|niemi|niemie", "DE", "z Niemiec"),
    (r"włoch|włosk|wloch|wlosk", "IT", "z Włoch"), (r"hiszpa", "ES", "z Hiszpanii"),
    (r"angli|angiel|brytyj|brytani|londyn", "GB", "z Wielkiej Brytanii"),
    (r"ameryk|usa\b|stanów\s+zjednoczonych|stanow\s+zjednoczonych|nowego\s+jorku", "US",
     "z Ameryki"),
    (r"czech|czesk", "CZ", "z Czech"), (r"słowac|slowac", "SK", "ze Słowacji"),
    (r"ukrai", "UA", "z Ukrainy"), (r"grec|grek", "GR", "z Grecji"),
    (r"szwec|szwedz", "SE", "ze Szwecji"), (r"norw", "NO", "z Norwegii"),
    (r"holand|niderland", "NL", "z Holandii"), (r"japo", "JP", "z Japonii"),
    (r"brazyl", "BR", "z Brazylii"), (r"irland", "IE", "z Irlandii"),
    (r"austri", "AT", "z Austrii"), (r"szwajcar", "CH", "ze Szwajcarii"),
    (r"portugal", "PT", "z Portugalii"), (r"chorwac", "HR", "z Chorwacji"),
    (r"kanad", "CA", "z Kanady"), (r"australi", "AU", "z Australii"),
    (r"litw|litew", "LT", "z Litwy"), (r"węgi|węgr|wegi|wegr|węgier", "HU", "z Węgier"),
    (r"turc|turek|turk", "TR", "z Turcji"), (r"meksyk", "MX", "z Meksyku"),
    (r"kubań|kuban|z\s+kuby", "CU", "z Kuby"), (r"jamaj", "JM", "z Jamajki"),
    (r"duńsk|dunsk|\bdani", "DK", "z Danii"), (r"fińsk|finsk|finland", "FI", "z Finlandii"),
    (r"belgi", "BE", "z Belgii"), (r"island", "IS", "z Islandii"),
    (r"argent", "AR", "z Argentyny"), (r"indi[ia]|indyjsk", "IN", "z Indii"),
]
_ABROAD = re.compile(r"zagranic|z\s+(?:innego|jakiegoś|jakiegos|obcego)\s+kraju|z\s+(?:całego|calego)\s+"
                     r"świata|ze\s+świata|ze\s+swiata|z\s+daleka", re.I)
_ABROAD_PICK = ["FR", "IT", "ES", "GB", "US", "DE", "BR", "JP", "GR", "IE", "NL", "CU"]
# kinds of music → radio-browser tags
_TAGS = [
    (r"jazz|dżez|dzez", "jazz"), (r"blues", "blues"), (r"reggae|rege", "reggae"),
    (r"metal", "metal"), (r"country", "country"), (r"rock", "rock"),
    (r"klasyczn|poważn|powazn|opera|operow", "classical"),
    (r"elektron|techno|house", "electronic"), (r"tanecz|dance|disco", "dance"),
    (r"chill|relaks|lounge|spokojn", "chillout"), (r"ambient", "ambient"),
    (r"latyn|salsa|samba|bossa", "latin"), (r"hip\s*hop|rap\b", "hiphop"),
    (r"lat\s+(?:80|osiemdziesiąt\w*)|osiemdziesiąt\w*|80s", "80s"),
    (r"lat\s+(?:90|dziewięćdziesiąt\w*)|dziewięćdziesiąt\w*|90s", "90s"),
    (r"stare\s+przeboje|oldies|retro", "oldies"), (r"przebo|hit|pop\b", "pop"),
    (r"wiadomości|wiadomosci|news|informac", "news"), (r"dla\s+dzieci|dziecięc|dzieciec", "children"),
    (r"folk|ludow", "folk"), (r"soul|funk", "soul"),
]
_GOOD_CODECS = ("MP3", "AAC", "AAC+", "OGG")
# how she names the kind of music she found ("Włączam Classic Vinyl HD — jazz.")
_TAG_PL = {"electronic": "muzyka elektroniczna", "latin": "muzyka latynoska",
           "hiphop": "hip-hop", "80s": "przeboje lat osiemdziesiątych",
           "90s": "przeboje lat dziewięćdziesiątych", "oldies": "stare przeboje",
           "classical": "muzyka klasyczna", "chillout": "spokojna muzyka",
           "children": "radio dla dzieci", "news": "wiadomości", "folk": "muzyka folk"}
_browse = {}               # {"label", "list": [(name, url, where)], "i"} — the last world search


def _world_wanted(what):
    """(country code or None, tag or None, how she says it) when the words ask
    for a country's radio or a kind of music abroad — None when they don't
    (then the Polish stations and genres as before)."""
    w = (what or "").lower()
    cc = next(((code, where) for rx, code, where in _COUNTRIES if re.search(rx, w)), None)
    if not cc and _ABROAD.search(w):
        import random
        code = random.choice(_ABROAD_PICK)
        cc = (code, next(where for _, c, where in _COUNTRIES if c == code))
    tag = next((t for rx, t in _TAGS if re.search(rx, w)), None)
    if cc:
        return cc[0], tag, cc[1]
    # a kind of music with no Polish station for it (reggae, blues, metal…)
    # (jazz too — 11 Oct: "jakieś radio z jazzem" took three tries, then Nowy
    # Świat, which isn't a jazz station)
    # (jazz, electronic, ambient: CATALOG has them now — 15 Oct)
    if tag in ("blues", "reggae", "metal", "country", "latin",
               "hiphop", "80s", "90s", "oldies", "folk", "soul"):
        return None, tag, ""
    return None


def _world_search(code, tag):
    """The most voted working stations for a country and/or tag, [(name, url)]."""
    q = "&".join(x for x in (f"countrycode={code}" if code else "",
                            f"tag={urllib.parse.quote(tag)}" if tag else "") if x)
    for host in _MIRRORS:
        url = (f"https://{host}.api.radio-browser.info/json/stations/search?{q}"
               "&order=votes&reverse=true&limit=25&hidebroken=true")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Luna-robot/1.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                found = json.load(r)
            break
        except Exception as e:
            print(f"[radio] world lookup on {host} failed: {e}", flush=True)
    else:
        return []
    out, seen = [], set()
    for s in found:
        name = _spoken(s.get("name", ""))
        if (s.get("url_resolved") and s.get("codec", "").upper() in _GOOD_CODECS
                and name.lower() not in seen):
            seen.add(name.lower())
            out.append((_short(name), s["url_resolved"]))
    return out[:10]


def _alive(url):
    """The stream answers (Rai Radio 1, the most voted in Italy, says 403 from
    here — 11 Oct)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Luna-robot/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status < 400 and bool(r.read(2048))
    except Exception as e:
        print(f"[radio] {url} doesn't answer ({' '.join(str(e).split())[:60]})", flush=True)
        return False


def _short(name):
    """A name she can say: "SABROSITA Ciudad de México 590 AM XEPH-AM NRM…" →
    "SABROSITA Ciudad de México"."""
    if len(name) <= 30:
        return name
    cut = re.split(r"\s+[-–|,:]\s+|,\s*", name)[0]
    words = cut.split()
    return " ".join(words[:4]) if len(cut) > 30 else cut


def _world_play(what, speak):
    """"Włącz radio z Francji" → True when it was such a request (handled)."""
    asked = _world_wanted(what)
    if not asked:
        return False
    code, tag, where = asked
    speak(f"Szukam radia {where}…" if where else "Szukam takiej stacji…")
    found = _world_search(code, tag)
    first = next((i for i, (_, u) in enumerate(found[:5]) if _alive(u)), None)
    if first is None:
        speak("Nie udało mi się znaleźć działającej stacji — spróbuj inaczej.")
        return True
    _browse.clear()
    _browse.update(label=where, list=found, i=first)
    name, url = found[first]
    kind = _TAG_PL.get(tag, tag) if tag and not where else ""
    speak(f"Włączam {name}" + (f" — radio {where}." if where else f" — {kind}." if kind
                               else "."))
    play(name, url)
    _remember_station(name, url)
    with _lock:
        if _player:
            _player["from"] = where
    return True


def _world_next(speak):
    """"Następna stacja" while a world search's station plays → its next one."""
    if not _browse or playing() not in [n for n, _ in _browse["list"]]:
        return False
    n = len(_browse["list"])
    for step in range(1, min(n, 5) + 1):          # (a station abroad may refuse us)
        i = (_browse["i"] + step) % n
        if _alive(_browse["list"][i][1]):
            break
    _browse["i"] = i
    name, url = _browse["list"][i]
    speak(f"Teraz {name}.")
    play(name, url)
    _remember_station(name, url)
    with _lock:
        if _player:
            _player["from"] = _browse["label"]
    return True
