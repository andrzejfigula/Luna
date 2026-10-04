"""
weather.py — the forecast, so "jaka będzie pogoda?" gets a real answer.

Opt-in: set LUNA_LAT and LUNA_LON in .env (decimal degrees). Without them
nothing is fetched and nothing leaves the Pi. With them, open-meteo.com
(free, no key) is asked every WEATHER_REFRESH_SECS in the background, and
a short summary goes into every request: now, today, tomorrow.
"""

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


def enabled():
    return WEATHER_LAT is not None and WEATHER_LON is not None


def _fetch():
    q = urllib.parse.urlencode({
        "latitude": WEATHER_LAT, "longitude": WEATHER_LON,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,sunrise,sunset",
        "timezone": "auto", "forecast_days": 2,
    })
    with urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q,
                                timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _describe(d):
    cur, day = d["current"], d["daily"]
    now = (f"{cur['temperature_2m']:.0f}°C (feels like {cur['apparent_temperature']:.0f}°C), "
           f"{_WMO.get(cur['weather_code'], 'kod ' + str(cur['weather_code']))}, "
           f"wind {cur['wind_speed_10m']:.0f} km/h")

    def day_text(i):
        rain = day["precipitation_probability_max"][i]
        return (f"{_WMO.get(day['weather_code'][i], '?')}, "
                f"{day['temperature_2m_min'][i]:.0f}–{day['temperature_2m_max'][i]:.0f}°C"
                + (f", rain chance {rain}%" if rain is not None else ""))

    sun = (f"sunrise {day['sunrise'][0][-5:]}, sunset {day['sunset'][0][-5:]}")
    return (f"Weather in {LUNA_LOCATION} (open-meteo): now {now}. Today: {day_text(0)}; "
            f"{sun}. Tomorrow: {day_text(1)}.")


def prompt_line():
    """One line for the system prompt. Without data it says so explicitly —
    otherwise the model happily invents sunshine (seen in testing)."""
    unknown = ("You have NO weather information: never describe or guess the "
               "weather; if asked, say you can't check it (it can be switched "
               "on by setting LUNA_LAT and LUNA_LON).\n")
    if not enabled():
        return unknown
    with _lock:
        s = _summary
    if not s:
        return unknown
    return (s + " Use it when asked about the weather, or briefly when it "
            "matters (going out, a morning greeting) — don't recite it unasked.\n")


def _loop():
    global _summary, _fetched
    while True:
        try:
            s = _describe(_fetch())
            with _lock:
                _summary, _fetched = s, time.time()
            print(f"[weather] {s}", flush=True)
            time.sleep(WEATHER_REFRESH_SECS)
        except Exception as e:
            print(f"[weather] fetch failed ({e}) — retrying in 5 min")
            time.sleep(300)


def start_weather():
    if not enabled():
        return
    threading.Thread(target=_loop, daemon=True, name="weather").start()
