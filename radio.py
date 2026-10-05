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

from shared_state import state

RATE, CHANNELS = 44100, 2
CHUNK = RATE * CHANNELS * 2 // 10          # 0.1 s of s16 stereo
RADIO_GAIN = 0.55                          # music under her voice's level (default;
                                           # "ciszej" while it plays changes it)
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
}
# stations move and fail: what to try next when a stream won't start
# (checked 2026-10-04 evening: Trójka's MP3 stream was down, its HLS worked)
FALLBACKS = {
    "http://195.150.20.242:8000/rmf_fm": ["http://195.150.20.9/RMFFM48"],
    "http://zet-net-01.cdn.eurozet.pl:8400/": ["https://r.dcs.redcdn.pl/sc/o2/Eurozet/live/audio.livx?audio=5"],
    "http://mp3.polskieradio.pl:8904/;.mp3": ["https://stream13.polskieradio.pl/pr3/pr3.sdp/playlist.m3u8"],
    "http://mp3.polskieradio.pl:8900/;.mp3": ["http://stream3.polskieradio.pl:8950/;.mp3"],
    "https://n-11-21.dcs.redcdn.pl/sc/o2/radio357/live/radio357_pr.livx?preroll=0": ["https://stream.radio357.pl/"],
}
_ALIASES = {"rmf": "rmf fm", "rmfu": "rmf fm", "rmf-u": "rmf fm", "zet": "radio zet",
            "zetkę": "radio zet", "zetka": "radio zet", "trójkę": "trójka", "trojke": "trójka",
            "trojka": "trójka", "jedynkę": "jedynka", "jedynke": "jedynka",
            "dwójkę": "dwójka", "dwojke": "dwójka", "357": "radio 357",
            "trzysta pięćdziesiąt siedem": "radio 357", "nowy swiat": "nowy świat",
            "nowego świata": "nowy świat"}

_ON = re.compile(r"^(?:luna,? |luno,? )?(?:włącz|wlacz|puść|pusc|zagraj|odpal|graj)\s+"
                 r"(?:(?:mi|nam)\s+)?(?:(?:radio|stację|stacje)\s*(.*)|(.+))$")
_ALARM_ON = ("budź mnie radiem", "budz mnie radiem", "obudź mnie radiem",
             "obudz mnie radiem", "budzik z radiem", "budzenie radiem", "budzik radiem")
_ALARM_OFF = ("budź mnie dzwonkiem", "budz mnie dzwonkiem", "budzik bez radia",
              "budzik z dzwonkiem", "budzenie dzwonkiem")
_MUSIC = {"muzykę", "muzyke", "jakąś muzykę", "jakas muzyke", "muzyczkę", "coś do słuchania"}
_OFF = ("wyłącz radio", "wylacz radio", "stop radio", "zatrzymaj radio", "wyłącz muzykę",
        "wylacz muzyke", "zatrzymaj muzykę", "koniec radia", "radio stop", "ścisz radio do zera")
_WHAT = ("jakie to radio", "jaka to stacja", "co to za radio", "co to za stacja",
         "jakie radio gra", "jakie radio leci")
_SONG = ("co teraz gra", "co to za piosenka", "co to za utwór", "co to za utwor",
         "jaka to piosenka", "jaki to utwór", "jaki to utwor", "kto to śpiewa",
         "kto to spiewa", "co leci", "co to leci", "what song is this", "what's playing")
_NEXT = ("następna stacja", "nastepna stacja", "zmień stację", "zmien stacje",
         "inna stacja", "inną stację", "inna stacje", "next station", "kolejna stacja")
_QUIETER = ("ciszej", "ścisz", "scisz", "przycisz", "quieter")
_LOUDER = ("głośniej", "glosniej", "podgłośnij", "podglosnij", "pogłośnij", "louder")
_SLEEP = re.compile(r"(?:wyłącz|wylacz)\s+(?:radio|muzykę|muzyke)\s+za\s+(.+)$|"
                    r"radio\s+(?:na|przez)\s+(.+)$")

_lock = threading.Lock()
_player = None             # {"name", "url", "stop": Event, "thread", "until"}
_say = [None]              # speak(), for "the stream died" from the player thread


# ── which station ─────────────────────────────────────────────────────────────

def _lookup(name):
    """radio-browser.info: the most voted working station by that name."""
    q = urllib.parse.quote(name)
    for country in ("&countrycode=PL", ""):
        url = (f"https://de1.api.radio-browser.info/json/stations/search?name={q}"
               f"{country}&order=votes&reverse=true&limit=5&hidebroken=true")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Luna-robot/1.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                found = json.load(r)
        except Exception as e:
            print(f"[radio] lookup failed: {e}", flush=True)
            return None
        for s in found:
            if s.get("url_resolved") and s.get("codec", "").upper() in ("MP3", "AAC", "AAC+", "OGG"):
                return s["name"].strip(), s["url_resolved"]
    return None


def _station(words):
    """(spoken name, url) for what was said after "włącz radio", or None."""
    import settings
    w = words.strip(" .!?").lower()
    w = re.sub(r"^(?:radio|stację|stacje)\s+", "", w)
    if not w:                              # "włącz radio": your last station
        mine = (settings.get("radio_last_by", {}) or {}).get(_who())
        last = mine or settings.get("radio_last")
        return tuple(last) if last else STATIONS["rmf fm"]
    key = _ALIASES.get(w, w)
    if key in STATIONS:
        return STATIONS[key]
    for k, v in STATIONS.items():
        if key in k or k in key:
            return v
    saved = settings.get("radio_found", {})
    if key in saved:
        return tuple(saved[key])
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
    who = _who()
    if who:
        by = settings.get("radio_last_by", {}) or {}
        by[who] = [name, url]
        settings.put("radio_last_by", by)


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


def _gain():
    import settings
    return settings.get("radio_gain", RADIO_GAIN)


def _ducked():
    with state.lock:
        return state.speaking or state.listening or state.conversation_active


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
                target = _gain() * (RADIO_DUCK if _ducked() else 1.0)
                if p.get("fade"):                    # an alarm: from a whisper up
                    target *= min(1.0, 0.05 + (time.time() - p["t0"]) / p["fade"])
                new = target if abs(target - gain) < 0.01 else gain + (target - gain) * 0.5
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
                state.radio = None
        if not p["stop"].is_set():
            print("[radio] gave up", flush=True)
            if _say[0]:
                _say[0]("Radio przestało grać — nie mogę się połączyć ze stacją.")


def play(name, url, until=None, fade=0, alarm=False):
    stop()
    try:
        import ambience                          # one sound at a time
        ambience.stop()
    except Exception:
        pass
    p = {"name": name, "url": url, "stop": threading.Event(), "until": until,
         "fade": fade, "alarm": alarm, "t0": time.time()}
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
        speak(f"Gra {now}." if now else "Radio nie gra.")
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
    if any(k in low for k in _NEXT) and len(words) <= 5:
        names = list(STATIONS.values())
        now = playing()
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
        g = round(max(0.05, min(1.0, g)), 3)
        settings.put("radio_gain", g)
        print(f"[radio] music volume → {g:.0%}", flush=True)
        return True                        # the music itself is the answer
    m = _SLEEP.search(low)
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
    if m.group(1) is None:                 # "włącz trójkę" — only a known station
        key = _ALIASES.get(m.group(2).strip(), m.group(2).strip())
        if key in _MUSIC:
            what = ""                      # "włącz muzykę" → the last station
        elif key not in STATIONS:
            return False
        else:
            what = key
    else:
        what = m.group(1)
    if len(what.split()) > 4:
        return False
    st = _station(what)
    if not st:
        speak(f"Nie znalazłam stacji {what}.")
        return True
    name, url = st
    speak(f"Włączam {_acc(name)}.")
    play(name, url)
    _remember_station(name, url)
    return True
