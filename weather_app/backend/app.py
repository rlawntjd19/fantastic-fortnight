"""Flask backend for the 날씨알리미 (Weather Alert) PWA.

Serves the static frontend and proxies weather requests to whichever
provider is configured (AccuWeather, KMA, or the built-in mock), so the
frontend never needs to see API keys and never has to deal with CORS.

Run:
    python backend/app.py
"""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from locations import find_location, search_locations
from providers import available_providers, get_provider

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")

_CACHE_TTL_SECONDS = 5 * 60
_cache: dict = {}


def _cached_weather(provider_name: str, location: dict) -> dict:
    key = (provider_name, location["id"])
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    provider = get_provider(provider_name)
    data = provider.get_weather(location)
    _cache[key] = (now, data)
    return data


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "providers": available_providers()})


@app.get("/api/locations")
def locations():
    query = request.args.get("q", "")
    return jsonify(search_locations(query))


@app.get("/api/weather")
def weather():
    location_id = request.args.get("location_id", "seoul")
    provider_name = request.args.get("provider")

    location = find_location(location_id)
    if not location:
        return jsonify({"error": f"unknown location_id '{location_id}'"}), 404

    try:
        data = _cached_weather(provider_name, location)
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        return jsonify({"error": str(exc)}), 502

    return jsonify(data)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
