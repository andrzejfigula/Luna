"""
weather.py — the forecast, so "jaka będzie pogoda?" gets a real answer.

Opt-in: set LUNA_LAT and LUNA_LON in .env (decimal degrees) — or just say
"Luna, pogoda dla Krakowa" / "mieszkam w Gdańsku": the place is turned into
its nominative ("Krakowa" → "Kraków", one small model call — the geocoder
only knows nominatives), found with open-meteo's geocoder and kept in
settings ("wyłącz pogodę" forgets it). Without a place nothing is fetched
and nothing leaves the Pi. With one, open-meteo.com (free, no key) is asked
every WEATHER_REFRESH_SECS in the background, and a short summary goes into
every request: now, today, tomorrow.
"""

from datetime import datetime, timedelta
import json
import re
import os
import threading
import time
import urllib.parse
import urllib.request

from config import WEATHER_LAT, WEATHER_LON, WEATHER_REFRESH_SECS, LUNA_LOCATION

_lock = threading.Lock()
_summary = ""
_fetched = 0.0

# WMO weather codes → Polish
_WMO = {
    0: "bezchmurnie", 1: "przeważnie słonecznie", 2: "częściowe zachmurzenie",
    3: "pochmurno", 45: "mgła", 48: "szadź i mgła",
    51: "lekka mżawka", 53: "mżawka", 55: "gęsta mżawka",
    56: "marznąca mżawka", 57: "marznąca mżawka",
    61: "lekki deszcz", 63: "deszcz", 65: "ulewa",
    66: "marznący deszcz", 67: "marznący deszcz",
    71: "lekki śnieg", 73: "śnieg", 75: "intensywny śnieg", 77: "ziarnisty śnieg",
    80: "przelotne opady", 81: "przelotny deszcz", 82: "gwałtowne ulewy",
    85: "przelotny śnieg", 86: "intensywne opady śniegu",
    95: "burza", 96: "burza z gradem", 99: "silna burza z gradem",
}



def _place():
    """(lat, lon, name): .env first, else the place set by voice, else None."""
    if WEATHER_LAT is not None and WEATHER_LON is not None:
        return WEATHER_LAT, WEATHER_LON, LUNA_LOCATION
    import settings
    p = settings.get("weather_place")
    if p:
        return p["lat"], p["lon"], p["name"]
    return None


def _region():
    """", województwo dolnośląskie" for the home place (asked once, kept in
    settings) — 11 Oct sweep: "Kiedy są ferie zimowe?" → "podaj województwo",
    though she knew the town. "" when unknown."""
    import settings
    name = (_place() or (None, None, None))[2]
    if not name:
        return ""
    kept = settings.get("place_region") or {}
    if kept.get("name") != name:
        try:
            f = _geocode(name) or {}
        except Exception:
            return ""                    # offline: asked again next time
        kept = {"name": name, "region": f.get("admin1") or ""}
        settings.put("place_region", kept)
    return f", {kept['region'].lower()}" if kept.get("region") else ""


def enabled():
    return _place() is not None


def _nominative(phrase):
    """"Krakowa" / "w Zielonej Górze" → "Kraków" / "Zielona Góra"."""
    from openai import OpenAI
    from config import OPENAI_API_KEY, OPENAI_MODEL
    c = OpenAI(api_key=OPENAI_API_KEY, timeout=10, max_retries=1)
    r = c.chat.completions.create(
        model=OPENAI_MODEL, temperature=0, max_tokens=40,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content":
                   "Return JSON {\"place\": ...}: the name of the town or city in this "
                   "Polish phrase, in the nominative case, as on a map (e.g. "
                   "\"Krakowa\" -> \"Kraków\", \"w Zielonej Górze\" -> \"Zielona Góra\", "
                   "\"w Berlinie\" -> \"Berlin\"). Empty string if there is none.\n\n"
                   + phrase}])
    return json.loads(r.choices[0].message.content).get("place", "").strip()


def _geocode(name):
    """Best match for a nominative place name: Poland first, but only an
    exact name (the Polish search turns "Berlin" into "Barlinek")."""
    picks = []
    for country in ("&countryCode=PL", ""):
        url = ("https://geocoding-api.open-meteo.com/v1/search?count=3&language=pl"
               + country + "&name=" + urllib.parse.quote(name))
        with urllib.request.urlopen(url, timeout=8) as r:
            picks += (json.loads(r.read().decode("utf-8")).get("results") or [])
    exact = [f for f in picks if f["name"].lower() == name.lower()]
    return (exact or picks or [None])[0]


def forecast_for(phrase):
    """"Jaka jest pogoda w Berlinie?" — that place's forecast as a prompt
    block for this one question (the home place stays), or None."""
    name = _nominative(phrase)
    if not name:
        return None
    here = _place()
    if here and here[2].lower() == name.lower():
        return None                           # home: already in every prompt
    f = _geocode(name)
    if not f:
        return None
    d = _fetch(f["latitude"], f["longitude"])
    print(f"[weather] one-off forecast for {f['name']}", flush=True)
    return ("\n" + _describe(d, f["name"] + (f", {f['country']}" if f.get("country") else ""))
            + " The user asked about THIS place: answer from it.\n")


def set_place(phrase):
    """Find the place said and switch the weather on for it. Returns its
    name, or None when it can't be found."""
    import settings
    name = _nominative(phrase)
    if not name:
        return None
    f = _geocode(name)
    if not f:
        return None
    settings.put("weather_place", {"name": f["name"], "lat": f["latitude"],
                                   "lon": f["longitude"]})
    print(f"[weather] place set: {f['name']} ({f['latitude']:.2f}, "
          f"{f['longitude']:.2f})", flush=True)
    refresh()
    return f["name"]


def forget_place():
    import settings
    global _summary
    settings.put("weather_place", None)
    with _lock:
        _summary = ""


def refresh():
    """Fetch now (after the place changed); starts the loop if needed."""
    global _summary, _fetched
    try:
        s = _describe(_fetch())
        with _lock:
            _summary, _fetched = s, time.time()
        print(f"[weather] {s}", flush=True)
    except Exception as e:
        print(f"[weather] fetch failed ({e})", flush=True)
    start_weather()


def _fetch(lat=None, lon=None):
    if lat is None:
        lat, lon, _ = _place()
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,sunrise,sunset",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        # a week: "czy będzie padać w weekend?" was answered from today and
        # tomorrow only — the model invented Saturday and Sunday (7 Oct probe)
        "timezone": "auto", "forecast_days": 7,
    })
    with urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q,
                                timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _wind_word(kmh):
    """9 km/h is "słaby" — 8 Oct sweep: "dziś wieje umiarkowanie, około 9 km/h"."""
    return ("bezwietrznie" if kmh < 2 else "słaby wiatr" if kmh < 12 else
            "umiarkowany wiatr" if kmh < 29 else "silny wiatr" if kmh < 50 else
            "bardzo silny wiatr")


def _describe(d, where=None):
    cur, day = d["current"], d["daily"]
    now = (f"{cur['temperature_2m']:.0f}°C (feels like {cur['apparent_temperature']:.0f}°C), "
           f"{_WMO.get(cur['weather_code'], 'kod ' + str(cur['weather_code']))}, "
           f"wind {cur['wind_speed_10m']:.0f} km/h ({_wind_word(cur['wind_speed_10m'])})")

    def day_text(i):
        rain = day["precipitation_probability_max"][i]
        return (f"{_WMO.get(day['weather_code'][i], '?')}, "
                f"{day['temperature_2m_min'][i]:.0f}–{day['temperature_2m_max'][i]:.0f}°C"
                + (f", rain chance {rain}%" if rain is not None else ""))

    sun = (f"sunrise {day['sunrise'][0][-5:]}, sunset {day['sunset'][0][-5:]}")
    later = []
    for i in range(2, len(day.get("time") or [])):
        try:
            dt = datetime.strptime(day["time"][i], "%Y-%m-%d")
            later.append(f"{_WD_PL[dt.weekday()]} {dt.day}.{dt.month:02d}: {day_text(i)}")
        except (ValueError, IndexError, TypeError):
            break
    week = (" Later: " + "; ".join(later) + ". Beyond these days you don't know the "
            "weather.") if later else ""
    home = "" if where else _region()
    return (f"Weather in {where or _place()[2]}{home} (open-meteo): now {now}. Today: {day_text(0)}; "
            f"{sun}. Tomorrow: {day_text(1)}.{_hours(d)}{week}")


def _hours(d, now=None):
    """" By the hour — today 18:00 15°C (rain 60%), …; tomorrow 07:00 9°C …" —
    "co ubrać do szkoły rano?" got only the day's 7–21°C (8 Oct sweep)."""
    try:
        h = d["hourly"]
        now = now or datetime.now()
        today, tomorrow = now.date(), (now + timedelta(days=1)).date()
        bits = {today: [], tomorrow: []}
        for t, temp, rain in zip(h["time"], h["temperature_2m"], h["precipitation_probability"]):
            dt = datetime.strptime(t, "%Y-%m-%dT%H:%M")
            if dt.date() == today and dt.hour > now.hour and dt.hour in (9, 12, 15, 18, 21):
                pass
            elif dt.date() == tomorrow and dt.hour in (7, 12, 15, 18):
                pass
            else:
                continue
            bits[dt.date()].append(f"{dt:%H:%M} {temp:.0f}°C"
                                   + (f" (rain {rain}%)" if rain else ""))
        out = ([f"today {', '.join(bits[today])}"] if bits[today] else []) + \
              ([f"tomorrow {', '.join(bits[tomorrow])}"] if bits[tomorrow] else [])
        return (" By the hour — " + "; ".join(out) + ".") if out else ""
    except (KeyError, TypeError, ValueError):
        return ""


_WD_PL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def prompt_line():
    """One line for the system prompt. Without data it says so explicitly —
    otherwise the model happily invents sunshine (seen in testing)."""
    unknown = ("You have NO weather information: never describe or guess the "
               "weather; if asked, say you can't check it yet — it is switched "
               "on by saying \"Luna, pogoda dla\" and the town, e.g. \"pogoda dla "
               "Krakowa\".\n")
    if not enabled():
        return unknown
    with _lock:
        s = _summary
    if not s:
        return unknown
    return (s + " Use it when asked about the weather, or briefly when it "
            "matters (going out, a morning greeting) — don't recite it unasked. "
            "\"Co/jak się ubrać\" is a weather question: advise from THIS forecast for "
            "that time (school asked about after about 14:00 = \"jutro\" 07:00, \"dziś rano\" is gone) naming its temperature "
            "and rain — never \"jeśli będzie zimno…\". " + _school_note() + "\n")


def _school_note():
    """Whether today/tomorrow are school days, counted (9 Oct: "Jak ubrać Maję
    do szkoły?" on a Saturday got "dziś do szkoły", and after a rule about it,
    a Monday got "szkoły nie ma")."""
    from datetime import date
    from kids import school_day as school          # one rule for the routine and this
    today = date.fromtimestamp(time.time())
    t, n = school(today), school(today + timedelta(days=1))
    return (f"Today is {'a school day' if t else 'NOT a school day (no school)'}, "
            f"tomorrow is {'a school day' if n else 'NOT a school day'}.")


_started = [False]


_days = []          # [(label, text)] per day — "pokaż pogodę" (screens.py)
_screen = {}        # the same as pictures (screen_days)


def forecast_rows(d=None):
    """The days of the last forecast as rows for her screen: ("Dziś",
    "pochmurno, 7–13°C, deszcz 40%"). [] without one."""
    if d is None:
        with _lock:
            return list(_days)
    rows = []
    try:
        day = d["daily"]
        for i, t in enumerate(day["time"][:7]):
            dt = datetime.strptime(t, "%Y-%m-%d")
            label = ("Dziś" if i == 0 else "Jutro" if i == 1
                     else f"{_WD_PL[dt.weekday()]} {dt.day}.{dt.month:02d}")
            rain = day["precipitation_probability_max"][i]
            rows.append((label, f"{_WMO.get(day['weather_code'][i], '?')}, "
                                f"{day['temperature_2m_min'][i]:.0f}–"
                                f"{day['temperature_2m_max'][i]:.0f}°C"
                                + (f", deszcz {rain}%" if rain else "")))
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return rows


def kind_of(code):
    """A WMO code → clear / partly / cloud / fog / drizzle / rain / snow / storm."""
    if code is None:
        return "cloud"
    if code in _KIND:
        return _KIND[code]
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    return "drizzle" if 51 <= code <= 57 else "rain"


def screen_days(d=None):
    """"Pokaż pogodę" as pictures (ui_screens.py): {"place", "now": {temp,
    kind, day, desc, feels, wind}, "days": [{label, short, kind, desc, tmin,
    tmax, rain}]}; None without a forecast."""
    if d is None:
        with _lock:
            got = dict(_screen) if _screen else None
        if got:
            got["hours"] = hours_ahead()
        return got
    try:
        cur, day = d["current"], d["daily"]
        days = []
        for i, t in enumerate(day["time"][:7]):
            dt = datetime.strptime(t, "%Y-%m-%d")
            code = day["weather_code"][i]
            days.append({"label": "Dziś" if i == 0 else "Jutro" if i == 1
                         else _WD_PL[dt.weekday()].capitalize(),
                         "date": f"{dt.day}.{dt.month:02d}",
                         "kind": kind_of(code), "desc": _WMO.get(code, ""),
                         "tmin": round(day["temperature_2m_min"][i]),
                         "tmax": round(day["temperature_2m_max"][i]),
                         "rain": day["precipitation_probability_max"][i] or 0})
        stamp = cur.get("time") or time.strftime("%Y-%m-%dT%H:%M")
        rise, sset = day["sunrise"][0], day["sunset"][0]
        place = (_place() or (None, None, ""))[2] or ""
        return {"place": place,
                "now": {"temp": round(cur["temperature_2m"]),
                        "feels": round(cur["apparent_temperature"]),
                        "wind": round(cur["wind_speed_10m"]),
                        "kind": kind_of(cur["weather_code"]),
                        "desc": _WMO.get(cur["weather_code"], ""),
                        "day": rise <= stamp < sset},
                "days": days}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def hours_ahead(now=None, n=5, every=3):
    """The next hours for the screen: [{"h": "18", "temp", "kind", "day"}],
    every `every` hours from the next full hour."""
    t0 = (now if now is not None else time.time()) // 3600 * 3600 + 3600
    out = []
    with _lock:
        hours, light = _sky.get("hours", {}), _sky.get("light", {})
    for j in range(n):
        lt = time.localtime(t0 + j * every * 3600)
        got = hours.get(time.strftime("%Y-%m-%dT%H:00", lt))
        if not got or got[0] is None:
            continue
        sun = light.get(time.strftime("%Y-%m-%d", lt))
        stamp = time.strftime("%Y-%m-%dT%H:%M", lt)
        out.append({"h": f"{lt.tm_hour}", "temp": round(got[0]), "kind": kind_of(got[1]),
                    "day": bool(sun) and sun[0] <= stamp < sun[1]})
    return out


def _apply(d):
    """A forecast (fresh or the cached one) into the summary and today's notes."""
    global _summary, _fetched
    s = _describe(d)
    rows = forecast_rows(d)
    scr = screen_days(d)
    with _lock:
        _summary, _fetched = s, time.time()
        _days[:] = rows
        _screen.clear()
        _screen.update(scr or {})
        try:
            h, day = d["hourly"], d["daily"]
            _sky.clear()
            _sky.update(hours=dict(zip(h["time"], zip(h["temperature_2m"],
                                                      h.get("weather_code") or [None] * len(h["time"])))),
                        light={t: (r, st) for t, r, st in zip(day["time"], day["sunrise"],
                                                               day["sunset"])},
                        rain=dict(zip(h["time"], h.get("precipitation_probability")
                                      or [None] * len(h["time"]))))
        except (KeyError, TypeError):
            pass
        try:
            _today.update(rain=d["daily"]["precipitation_probability_max"][0],
                          tmax=d["daily"]["temperature_2m_max"][0],
                          date=d["daily"]["time"][0],
                          hours=[(int(t[11:13]), p) for t, p in zip(
                              d["hourly"]["time"], d["hourly"]["precipitation_probability"])
                              if t[:10] == d["daily"]["time"][0] and p is not None],
                          morning=next(((temp, p) for t, temp, p in zip(
                              d["hourly"]["time"], d["hourly"]["temperature_2m"],
                              d["hourly"]["precipitation_probability"])
                              if t[:10] == d["daily"]["time"][1] and t[11:13] == "07"),
                              None))
        except (KeyError, IndexError, TypeError):
            pass
    return s


def _cache_path():
    from config import DATA_DIR
    return os.path.join(DATA_DIR, "weather_last.json")


def _load_cache(max_age=3 * 3600):
    """The last good forecast, if it's recent — a restart while open-meteo
    answers 503 (8 Oct) shouldn't leave her without any weather for 5 min."""
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            c = json.load(f)
        if time.time() - c.get("t", 0) < max_age:
            return c["d"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def _loop():
    first = True
    fails = 0
    while True:
        if not enabled():                    # "wyłącz pogodę"
            time.sleep(60)
            continue
        try:
            d = _fetch()
            s = _apply(d)
            fails = 0
            try:
                with open(_cache_path(), "w", encoding="utf-8") as f:
                    json.dump({"t": time.time(), "d": d}, f)
            except OSError:
                pass
            print(f"[weather] {s}", flush=True)
            first = False
            time.sleep(WEATHER_REFRESH_SECS)
        except Exception as e:
            fails += 1
            if first:
                first = False
                cached = _load_cache()
                if cached:
                    try:
                        _apply(cached)
                        print("[weather] using the last forecast from disk meanwhile", flush=True)
                    except Exception:
                        pass
            wait = 30 if fails <= 2 else 300
            print(f"[weather] fetch failed ({e}) — retrying in {wait} s", flush=True)
            time.sleep(wait)


_today = {}        # today's rain chance and max temperature (the last fetch)
_sky = {}          # hour → (temperature, WMO code); day → (sunrise, sunset)

# WMO code → the status bar's little picture (statusbar.py)
_KIND = {0: "clear", 1: "clear", 2: "partly", 3: "cloud", 45: "fog", 48: "fog",
         95: "storm", 96: "storm", 99: "storm"}


def now(t=None):
    """(temperature, kind, daytime) for this hour, from the last forecast —
    "kind" one of clear / partly / cloud / fog / rain / snow / storm; None
    without a forecast (or with the weather switched off)."""
    if not enabled():
        return None
    lt = time.localtime(t if t is not None else time.time())
    hour = time.strftime("%Y-%m-%dT%H:00", lt)
    with _lock:
        got = _sky.get("hours", {}).get(hour)
        light = _sky.get("light", {}).get(hour[:10])
    if not got or got[0] is None:
        return None
    temp, code = got
    kind = kind_of(code)
    if kind == "drizzle":
        kind = "rain"                       # (the status bar has no drizzle)
    stamp = time.strftime("%Y-%m-%dT%H:%M", lt)
    day = bool(light) and light[0] <= stamp < light[1]
    return round(temp), kind, day


_SUN_Q = re.compile(r"\b(wschód|wschod|zachód|zachod)\s+słońca|\b(wschodzi|zachodzi)\s+słońce|"
                    r"\bsłońce\s+(wschodzi|zachodzi|wstaje)|\b(ściemnia|sciemnia|robi\s+się\s+ciemno|"
                    r"zrobi\s+się\s+ciemno|zapada\s+zmrok|zmrok|zmierzch)\b|"
                    r"\b(robi\s+się\s+jasno|zrobi\s+się\s+jasno|rozjaśnia|świta|swita|świt|swit)\b",
                    re.I)


def sun_answer(text, now=None):
    """"O której zachód słońca?", "kiedy się ściemnia?", "o której jutro
    wschód?" → from the forecast (14 Oct probe: to the model). None when it
    isn't that question or there is no forecast."""
    low = text.lower()
    m = _SUN_Q.search(low)
    if not m or len(low.split()) > 10 or not re.search(r"\b(?:o\s+której|o\s+ktorej|kiedy|"
                                                      r"która|jaka\s+godzin|godzin\w*)\b", low):
        return None
    said = next(g for g in m.groups() if g)
    rise = said.startswith(("wsch", "wsta", "robi się jasno", "zrobi się jasno", "rozja",
                            "świt", "swit"))
    now = now or time.time()
    lt = time.localtime(now)
    tomorrow = "jutro" in low
    day = time.strftime("%Y-%m-%d", time.localtime(now + (86400 if tomorrow else 0)))
    with _lock:
        light = _sky.get("light", {}).get(day)
    if not light:
        return None
    at = light[0 if rise else 1][-5:]
    import clock
    h, mi = int(at[:2]), int(at[3:])
    when = clock.hour_locative(h, mi)
    gone = not tomorrow and at < time.strftime("%H:%M", lt)
    what = "Wschód słońca" if rise else "Zachód słońca"
    if gone:
        verb = "wzeszło" if rise else "zaszło"
        nxt = None
        with _lock:
            nxt = _sky.get("light", {}).get(time.strftime("%Y-%m-%d", time.localtime(now + 86400)))
        tail = ""
        if nxt:
            a = nxt[0 if rise else 1][-5:]
            tail = f" Jutro o {clock.hour_locative(int(a[:2]), int(a[3:]))}."
        return f"Słońce {verb} dziś o {when}.{tail}"
    return f"{what} {'jutro' if tomorrow else 'dziś'} o {when}."


def rain_soon(t=None, hours=3, chance=60):
    """Rain likely in the next few hours (this one included) — the status bar's
    umbrella. False without a forecast or with the weather off."""
    if not enabled():
        return False
    t = t if t is not None else time.time()
    with _lock:
        rain = _sky.get("rain", {})
        probs = [rain.get(time.strftime("%Y-%m-%dT%H:00", time.localtime(t + 3600 * i)))
                 for i in range(hours)]
    return any(p is not None and p >= chance for p in probs)


def morning_note(now=None):
    """For a grown-up's good night: "Jutro rano osiem stopni i może padać." —
    tomorrow at 7 from the hourly forecast; '' when unknown or before 18:00."""
    with _lock:
        t = dict(_today)
    m = t.get("morning")
    if (not m or t.get("date") != time.strftime("%Y-%m-%d", time.localtime(now))
            or time.localtime(now).tm_hour < 18):
        return ""
    temp, rain = round(m[0]), m[1] or 0
    n = abs(temp)
    unit = ("stopień" if n == 1 else "stopnie" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)
            else "stopni")
    said = f"minus {n}" if temp < 0 else str(n)
    return (f"Jutro rano {said} {unit}" + (" i może padać — przyda się parasol." if rain >= 50
                                           else "."))


def umbrella_note(now=None):
    """What to say to someone leaving: "Weź parasol — dziś ma padać." when
    today's rain chance is high, "Ubierz się ciepło…" when it's cold; None."""
    with _lock:
        t = dict(_today)
    if not t or t.get("date") != time.strftime("%Y-%m-%d", time.localtime(now)):
        return None
    hours = t.get("hours")
    if hours:
        # the hours still ahead (8 Oct: at 14:00, rain only from 21:00 — and a
        # morning shower already over is no reason for an umbrella)
        hour = time.localtime(now).tm_hour
        wet = [h for h, p in hours if h >= hour and p >= 50]
        if wet:
            h = wet[0]
            when = ("zaraz może padać" if h <= hour + 1 else
                    "ma padać po południu" if h < 17 else "wieczorem ma padać")
            return f"Weź parasol — {when}."
    elif (t.get("rain") or 0) >= 50:
        return "Weź parasol — dziś ma padać."
    if t.get("tmax") is not None and t["tmax"] <= 3:
        return "Ubierz się ciepło, dziś zimno."
    return None


def start_weather():
    if not enabled() or _started[0]:
        return
    _started[0] = True
    threading.Thread(target=_loop, daemon=True, name="weather").start()
