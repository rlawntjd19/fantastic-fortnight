"""AccuWeather provider.

Uses the standard AccuWeather Locations / CurrentConditions / Forecasts /
Alerts REST APIs (dataservice.accuweather.com), requested with
language=ko-kr so text fields come back in Korean already.

Get a free-tier key at https://developer.accuweather.com (등록 후
"Add a new App" 하면 API Key 발급). The free tier is capped at 50
calls/day, so results are cached (see app.py) and each get_weather()
call only issues the handful of requests below.

As with kma.py, every step is defensive: on any request/parsing failure
the whole provider falls back to MockProvider so a flaky upstream call
never breaks the app for the user.
"""

from datetime import datetime, timedelta, timezone

import requests

from .mock import MockProvider, _grade

KST = timezone(timedelta(hours=9))

BASE = "https://dataservice.accuweather.com"
REQUEST_TIMEOUT = 6

SKY_KEYWORDS = [
    (("눈",), "snow"),
    (("뇌우", "천둥"), "showers"),
    (("소나기",), "showers"),
    (("비",), "rain"),
    (("흐림", "대체로 흐림"), "cloudy"),
    (("구름 많음", "구름많음"), "mostly_cloudy"),
    (("구름 조금", "구름조금", "부분적으로"), "partly_cloudy"),
    (("맑음",), "clear"),
]


def _sky_code_from_phrase(phrase: str) -> str:
    for keywords, code in SKY_KEYWORDS:
        if any(k in phrase for k in keywords):
            return code
    return "cloudy"


class AccuWeatherProvider:
    name = "accuweather"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._fallback = MockProvider()
        self._location_key_cache: dict = {}

    def get_weather(self, location: dict) -> dict:
        try:
            location_key = self._resolve_location_key(location)
            current = self._get_current(location_key)
            hourly = self._get_hourly(location_key)
            daily = self._get_daily(location_key)
            alerts = self._get_alerts(location_key, location)
            return {
                "provider": self.name,
                "location": {
                    "id": location["id"],
                    "name": location["name"],
                    "lat": location["lat"],
                    "lon": location["lon"],
                },
                "current": current,
                "hourly": hourly,
                "daily": daily,
                "alerts": alerts,
            }
        except Exception:
            fallback = self._fallback.get_weather(location)
            fallback["provider"] = "mock (accuweather fallback)"
            return fallback

    # -- helpers ---------------------------------------------------------

    def _resolve_location_key(self, location: dict) -> str:
        if location["id"] in self._location_key_cache:
            return self._location_key_cache[location["id"]]
        resp = requests.get(
            f"{BASE}/locations/v1/cities/geoposition/search",
            params={
                "apikey": self.api_key,
                "q": f"{location['lat']},{location['lon']}",
                "language": "ko-kr",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        key = resp.json()["Key"]
        self._location_key_cache[location["id"]] = key
        return key

    def _get_current(self, location_key: str) -> dict:
        resp = requests.get(
            f"{BASE}/currentconditions/v1/{location_key}",
            params={"apikey": self.api_key, "language": "ko-kr", "details": "true"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()[0]
        sky = data.get("WeatherText", "맑음")
        wind = data.get("Wind", {})
        pm = data.get("PrecipitationSummary", {}).get("PastHour", {}).get("Metric", {}).get("Value", 0)
        return {
            "temp": data.get("Temperature", {}).get("Metric", {}).get("Value"),
            "feels_like": data.get("RealFeelTemperature", {}).get("Metric", {}).get("Value"),
            "humidity": data.get("RelativeHumidity"),
            "wind_speed": wind.get("Speed", {}).get("Metric", {}).get("Value"),
            "wind_dir": wind.get("Direction", {}).get("Localized", "-"),
            "sky": sky,
            "sky_code": _sky_code_from_phrase(sky),
            "precip_type": "없음" if not pm else "비",
            "precip_prob": None,
            # AccuWeather's air quality endpoint requires an Enterprise plan,
            # so PM values aren't available on the free/standard tier.
            "pm10": None,
            "pm10_grade": "정보없음",
            "pm25": None,
            "pm25_grade": "정보없음",
            "updated_at": datetime.now(KST).isoformat(),
        }

    def _get_hourly(self, location_key: str) -> list:
        resp = requests.get(
            f"{BASE}/forecasts/v1/hourly/12hour/{location_key}",
            params={"apikey": self.api_key, "language": "ko-kr", "metric": "true"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        hourly = []
        for it in resp.json():
            dt = datetime.fromisoformat(it["DateTime"])
            phrase = it.get("IconPhrase", "맑음")
            hourly.append({
                "time": dt.strftime("%H:%M"),
                "date": dt.strftime("%Y-%m-%d"),
                "temp": it.get("Temperature", {}).get("Value"),
                "sky": phrase,
                "sky_code": _sky_code_from_phrase(phrase),
                "precip_prob": it.get("PrecipitationProbability", 0),
                "precip_type": it.get("PrecipitationType", "없음") or "없음",
            })
        return hourly

    def _get_daily(self, location_key: str) -> list:
        resp = requests.get(
            f"{BASE}/forecasts/v1/daily/5day/{location_key}",
            params={"apikey": self.api_key, "language": "ko-kr", "metric": "true", "details": "true"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        daily = []
        weekday_labels = ["월", "화", "수", "목", "금", "토", "일"]
        for i, it in enumerate(resp.json().get("DailyForecasts", [])):
            date = it["Date"][:10]
            dt = datetime.strptime(date, "%Y-%m-%d")
            day = it.get("Day", {})
            night = it.get("Night", {})
            daily.append({
                "date": date,
                "label": "오늘" if i == 0 else ("내일" if i == 1 else weekday_labels[dt.weekday()]),
                "temp_min": it.get("Temperature", {}).get("Minimum", {}).get("Value"),
                "temp_max": it.get("Temperature", {}).get("Maximum", {}).get("Value"),
                "sky_am": day.get("IconPhrase", "-"),
                "sky_pm": night.get("IconPhrase", "-"),
                "precip_prob_am": day.get("PrecipitationProbability", 0),
                "precip_prob_pm": night.get("PrecipitationProbability", 0),
            })
        return daily

    def _get_alerts(self, location_key: str, location: dict) -> list:
        try:
            resp = requests.get(
                f"{BASE}/alerts/v1/{location_key}",
                params={"apikey": self.api_key, "language": "ko-kr"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            items = resp.json()
        except Exception:
            return []

        alerts = []
        for it in items:
            desc = it.get("Description", {}).get("Localized", "")
            areas = it.get("Area", [])
            area_name = areas[0]["Name"] if areas else location["name"]
            alerts.append({
                "level": it.get("Priority", "특보"),
                "title": desc or it.get("Category", "기상특보"),
                "area": area_name,
                "description": desc,
                "issued_at": it.get("Source", ""),
            })
        return alerts
