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

from datetime import datetime
import json
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
    return (f"Weather in {where or _place()[2]} (open-meteo): now {now}. Today: {day_text(0)}; "
            f"{sun}. Tomorrow: {day_text(1)}.{week}")


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
            "matters (going out, a morning greeting) — don't recite it unasked.\n")


_started = [False]


def _loop():
    global _summary, _fetched
    while True:
        if not enabled():                    # "wyłącz pogodę"
            time.sleep(60)
            continue
        try:
            d = _fetch()
            s = _describe(d)
            with _lock:
                _summary, _fetched = s, time.time()
                try:
                    _today.update(rain=d["daily"]["precipitation_probability_max"][0],
                                  tmax=d["daily"]["temperature_2m_max"][0],
                                  date=d["daily"]["time"][0])
                except (KeyError, IndexError, TypeError):
                    pass
            print(f"[weather] {s}", flush=True)
            time.sleep(WEATHER_REFRESH_SECS)
        except Exception as e:
            print(f"[weather] fetch failed ({e}) — retrying in 5 min")
            time.sleep(300)


_today = {}        # today's rain chance and max temperature (the last fetch)


def umbrella_note(now=None):
    """What to say to someone leaving: "Weź parasol — dziś ma padać." when
    today's rain chance is high, "Ubierz się ciepło…" when it's cold; None."""
    with _lock:
        t = dict(_today)
    if not t or t.get("date") != time.strftime("%Y-%m-%d", time.localtime(now)):
        return None
    if (t.get("rain") or 0) >= 50:
        return "Weź parasol — dziś ma padać."
    if t.get("tmax") is not None and t["tmax"] <= 3:
        return "Ubierz się ciepło, dziś zimno."
    return None


def start_weather():
    if not enabled() or _started[0]:
        return
    _started[0] = True
    threading.Thread(target=_loop, daemon=True, name="weather").start()
