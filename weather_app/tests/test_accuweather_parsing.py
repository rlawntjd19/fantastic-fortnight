from unittest.mock import patch

from locations import find_location
from providers.accuweather import AccuWeatherProvider


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def fake_get(url, params=None, timeout=None):
    if "geoposition/search" in url:
        return FakeResponse({"Key": "226081"})
    if "currentconditions" in url:
        return FakeResponse([
            {
                "WeatherText": "맑음",
                "Temperature": {"Metric": {"Value": 26.5}},
                "RealFeelTemperature": {"Metric": {"Value": 27.8}},
                "RelativeHumidity": 48,
                "Wind": {"Speed": {"Metric": {"Value": 3.2}}, "Direction": {"Localized": "남서"}},
                "PrecipitationSummary": {"PastHour": {"Metric": {"Value": 0}}},
            }
        ])
    if "forecasts/v1/hourly" in url:
        return FakeResponse([
            {"DateTime": "2099-01-01T13:00:00+09:00", "Temperature": {"Value": 25.0},
             "IconPhrase": "구름 조금", "PrecipitationProbability": 10, "PrecipitationType": None},
            {"DateTime": "2099-01-01T14:00:00+09:00", "Temperature": {"Value": 26.0},
             "IconPhrase": "비", "PrecipitationProbability": 70, "PrecipitationType": "Rain"},
        ])
    if "forecasts/v1/daily" in url:
        return FakeResponse({
            "DailyForecasts": [
                {
                    "Date": "2099-01-01T07:00:00+09:00",
                    "Temperature": {"Minimum": {"Value": 18.0}, "Maximum": {"Value": 28.0}},
                    "Day": {"IconPhrase": "맑음", "PrecipitationProbability": 5},
                    "Night": {"IconPhrase": "구름많음", "PrecipitationProbability": 20},
                }
            ]
        })
    if "alerts/v1" in url:
        return FakeResponse([
            {
                "Priority": "경보",
                "Category": "Heat",
                "Description": {"Localized": "폭염 경보가 발효 중입니다."},
                "Area": [{"Name": "서울"}],
                "Source": "KMA",
            }
        ])
    raise AssertionError(f"unexpected url: {url}")


@patch("providers.accuweather.requests.get", side_effect=fake_get)
def test_accuweather_provider_parses_all_sections(mock_get):
    provider = AccuWeatherProvider(api_key="test-key")
    loc = find_location("seoul")
    data = provider.get_weather(loc)

    assert data["provider"] == "accuweather"
    assert data["current"]["temp"] == 26.5
    assert data["current"]["sky_code"] == "clear"

    assert len(data["hourly"]) == 2
    assert data["hourly"][1]["sky_code"] == "rain"

    assert data["daily"][0]["temp_min"] == 18.0
    assert data["daily"][0]["temp_max"] == 28.0

    assert len(data["alerts"]) == 1
    assert data["alerts"][0]["area"] == "서울"


@patch("providers.accuweather.requests.get", side_effect=RuntimeError("network down"))
def test_accuweather_provider_falls_back_to_mock_on_error(mock_get):
    provider = AccuWeatherProvider(api_key="test-key")
    loc = find_location("jeju")
    data = provider.get_weather(loc)

    assert data["provider"] == "mock (accuweather fallback)"
    assert data["location"]["id"] == "jeju"
