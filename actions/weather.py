"""JARVIS - live weather (Mark LVI has a weather_report action;
this is a fresh stdlib implementation on Open-Meteo, which needs
no API key). Geocode the city, fetch current conditions + today's
range, cache for 10 minutes."""

import json
import time
import urllib.parse
import urllib.request

_CACHE = {}
_WMO = {
    0: "saaf aasmaan", 1: "lagbhag saaf", 2: "thoda badal",
    3: "badal chhaye", 45: "dhundh", 48: "dhundh",
    51: "halki boondabandi", 53: "boondabandi", 55: "tez boondabandi",
    61: "halki baarish", 63: "baarish", 65: "tez baarish",
    71: "halki barf", 73: "barf", 75: "tez barf",
    80: "baarish ki bauchhar", 81: "bauchhar", 82: "tez bauchhar",
    95: "garaj-bijli ke saath baarish",
}


def _get(url, timeout=5.0):
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_weather(city):
    city = (city or "").strip()
    if not city:
        return {"status": "error", "message": "sheher ka naam chahiye"}
    key = city.lower()
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    try:
        geo = _get("https://geocoding-api.open-meteo.com/v1/search?"
                   + urllib.parse.urlencode(
                       {"name": city, "count": 1, "language": "en"}))
        results = geo.get("results") or []
        if not results:
            return {"status": "error",
                    "message": f"'{city}' naam ki jagah nahi mili"}
        place = results[0]
        fc = _get("https://api.open-meteo.com/v1/forecast?"
                  + urllib.parse.urlencode({
                      "latitude": place["latitude"],
                      "longitude": place["longitude"],
                      "current": "temperature_2m,relative_humidity_2m,"
                                 "apparent_temperature,weather_code,"
                                 "wind_speed_10m",
                      "daily": "temperature_2m_max,temperature_2m_min",
                      "forecast_days": 1, "timezone": "auto"}))
        cur = fc.get("current", {})
        daily = fc.get("daily", {})
        out = {
            "status": "done", "verified": True,
            "city": place.get("name", city),
            "country": place.get("country", ""),
            "temperature_c": cur.get("temperature_2m"),
            "feels_like_c": cur.get("apparent_temperature"),
            "humidity_percent": cur.get("relative_humidity_2m"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "condition": _WMO.get(cur.get("weather_code"),
                                  "mausam saaf nahi pata"),
            "today_max_c": (daily.get("temperature_2m_max") or [None])[0],
            "today_min_c": (daily.get("temperature_2m_min") or [None])[0],
        }
        _CACHE[key] = (time.time(), out)
        return out
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return {"status": "error",
                "message": f"mausam nahi mil paya ({exc.__class__.__name__})"}
