from locations import LOCATIONS, find_location
from providers.mock import MockProvider


def test_mock_provider_shape():
    provider = MockProvider()
    data = provider.get_weather(find_location("seoul"))

    assert data["provider"] == "mock"
    assert data["location"]["id"] == "seoul"

    current = data["current"]
    for key in ("temp", "feels_like", "humidity", "wind_speed", "wind_dir", "sky", "pm10", "pm25"):
        assert key in current

    assert len(data["hourly"]) == 24
    for hour in data["hourly"]:
        assert set(("time", "date", "temp", "sky", "sky_code", "precip_prob", "precip_type")) <= set(hour)

    assert len(data["daily"]) == 7
    assert data["daily"][0]["label"] == "오늘"
    assert data["daily"][1]["label"] == "내일"

    assert isinstance(data["alerts"], list)


def test_mock_provider_covers_every_location():
    provider = MockProvider()
    for loc in LOCATIONS:
        data = provider.get_weather(loc)
        assert data["location"]["id"] == loc["id"]
        assert data["current"]["temp"] is not None


def test_mock_provider_is_stable_within_a_run():
    provider = MockProvider()
    loc = find_location("seoul")
    first = provider.get_weather(loc)
    second = provider.get_weather(loc)
    assert first["current"]["temp"] == second["current"]["temp"]
