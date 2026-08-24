from unittest.mock import patch

from locations import find_location
from providers.kma import KmaProvider


def _vilage_fcst_item(fcst_date, fcst_time, category, value):
    return {
        "baseDate": fcst_date,
        "baseTime": "0500",
        "category": category,
        "fcstDate": fcst_date,
        "fcstTime": fcst_time,
        "fcstValue": value,
        "nx": 60,
        "ny": 127,
    }


def _make_vilage_fcst_items():
    items = []
    date = "20990101"
    for hour, temp, sky, pty, pop in [
        ("0900", "24", "1", "0", "10"),
        ("1500", "27", "3", "0", "20"),
        ("1800", "22", "4", "1", "60"),
    ]:
        items.append(_vilage_fcst_item(date, hour, "TMP", temp))
        items.append(_vilage_fcst_item(date, hour, "SKY", sky))
        items.append(_vilage_fcst_item(date, hour, "PTY", pty))
        items.append(_vilage_fcst_item(date, hour, "POP", pop))
    items.append(_vilage_fcst_item(date, "0900", "TMN", "18"))
    items.append(_vilage_fcst_item(date, "1500", "TMX", "28"))
    return items


def _ultra_ncst_items():
    return [
        {"category": "T1H", "obsrValue": "23.4"},
        {"category": "REH", "obsrValue": "55"},
        {"category": "WSD", "obsrValue": "2.1"},
        {"category": "VEC", "obsrValue": "180"},
        {"category": "PTY", "obsrValue": "0"},
    ]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def fake_get(url, params=None, timeout=None):
    if "getVilageFcst" in url:
        return FakeResponse({"response": {"body": {"items": {"item": _make_vilage_fcst_items()}}}})
    if "getUltraSrtNcst" in url:
        return FakeResponse({"response": {"body": {"items": {"item": _ultra_ncst_items()}}}})
    if "getWthrWrnList" in url:
        return FakeResponse({
            "response": {
                "body": {
                    "items": {
                        "item": [
                            {"t1": "호우경보", "t2": "경보", "t4": "많은 비가 예상됩니다.", "t6": "서울", "tmFc": "202601010500"},
                            {"t1": "한파주의보", "t2": "주의보", "t4": "기온이 낮습니다.", "t6": "제주", "tmFc": "202601010500"},
                        ]
                    }
                }
            }
        })
    if "getNearbyMsrstnList" in url:
        return FakeResponse({"response": {"body": {"items": [{"stationName": "중구"}]}}})
    if "getMsrstnAcctoRltmMesureDnsty" in url:
        return FakeResponse({"response": {"body": {"items": [{"pm10Value": "45", "pm25Value": "22"}]}}})
    raise AssertionError(f"unexpected url: {url}")


@patch("providers.kma.requests.get", side_effect=fake_get)
def test_kma_provider_parses_forecast_and_current(mock_get):
    provider = KmaProvider(service_key="test-key")
    loc = find_location("seoul")
    data = provider.get_weather(loc)

    assert data["provider"] == "kma"
    assert len(data["hourly"]) >= 1
    assert data["daily"][0]["temp_min"] == 18.0
    assert data["daily"][0]["temp_max"] == 28.0

    current = data["current"]
    assert current["temp"] == 23.4
    assert current["humidity"] == 55
    assert current["pm10"] == 45
    assert current["pm25"] == 22

    # Only the 서울 alert should match the 서울 location.
    assert len(data["alerts"]) == 1
    assert data["alerts"][0]["title"] == "호우경보"


@patch("providers.kma.requests.get", side_effect=RuntimeError("network down"))
def test_kma_provider_falls_back_to_mock_on_error(mock_get):
    provider = KmaProvider(service_key="test-key")
    loc = find_location("busan")
    data = provider.get_weather(loc)

    assert data["provider"] == "mock (kma fallback)"
    assert data["location"]["id"] == "busan"
