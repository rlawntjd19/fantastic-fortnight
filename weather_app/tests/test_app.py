import os

import pytest

os.environ.pop("ACCUWEATHER_API_KEY", None)
os.environ.pop("KMA_SERVICE_KEY", None)

import app as app_module  # noqa: E402


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert "mock" in body["providers"]


def test_locations_search(client):
    resp = client.get("/api/locations?q=부산")
    assert resp.status_code == 200
    body = resp.get_json()
    assert any(loc["id"] == "busan" for loc in body)


def test_locations_empty_query_returns_all(client):
    resp = client.get("/api/locations")
    assert resp.status_code == 200
    assert len(resp.get_json()) > 10


def test_weather_known_location(client):
    resp = client.get("/api/weather?location_id=seoul")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["location"]["id"] == "seoul"
    assert "current" in body and "hourly" in body and "daily" in body


def test_weather_unknown_location(client):
    resp = client.get("/api/weather?location_id=atlantis")
    assert resp.status_code == 404


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<!doctype html>" in resp.data.lower()
