"""Local extras for the bulletin: Munich weather + markets brief.
Both keyless HTTP (Open-Meteo, Yahoo Finance) — same category as the RSS fetch."""
from __future__ import annotations

import httpx

from .config import (MARKET_SYMBOLS, WEATHER_CITY, WEATHER_LAT, WEATHER_LON)
from .models import MarketQuote, Weather

_UA = {"User-Agent": "Mozilla/5.0 (podcast-automation)"}

# WMO weather codes -> plain English
_WMO = {
    0: "clear skies", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 95: "thunderstorms",
    96: "thunderstorms with hail", 99: "severe thunderstorms",
}


def fetch_weather() -> Weather | None:
    try:
        j = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": WEATHER_LAT, "longitude": WEATHER_LON,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "timezone": "Europe/Berlin", "forecast_days": 1,
            }, headers=_UA, timeout=15,
        ).json()
        cur, day = j["current"], j["daily"]
        return Weather(
            city=WEATHER_CITY,
            now_c=round(cur["temperature_2m"], 1),
            high_c=round(day["temperature_2m_max"][0], 1),
            low_c=round(day["temperature_2m_min"][0], 1),
            conditions=_WMO.get(day["weather_code"][0], "mixed conditions"),
            wind_kmh=round(cur["wind_speed_10m"], 1),
        )
    except Exception as exc:
        print(f"  ! weather unavailable: {exc}")
        return None


def fetch_markets() -> list[MarketQuote]:
    quotes: list[MarketQuote] = []
    for label, sym in MARKET_SYMBOLS:
        try:
            j = httpx.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                headers=_UA, timeout=15,
            ).json()
            m = j["chart"]["result"][0]["meta"]
            px = m["regularMarketPrice"]
            prev = m.get("previousClose") or m.get("chartPreviousClose")
            quotes.append(MarketQuote(
                label=label, price=round(px, 2),
                change_pct=round((px - prev) / prev * 100, 2) if prev else 0.0,
            ))
        except Exception as exc:
            print(f"  ! market {sym} unavailable: {exc}")
    return quotes


if __name__ == "__main__":
    print(fetch_weather())
    for q in fetch_markets():
        print(q)
