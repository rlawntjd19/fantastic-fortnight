import os

from .accuweather import AccuWeatherProvider
from .kma import KmaProvider
from .mock import MockProvider

_instances: dict = {}


def get_provider(name: str = None):
    """Return a provider instance by name, defaulting to whichever real
    provider has an API key configured, falling back to mock."""
    name = name or _default_provider_name()
    if name in _instances:
        return _instances[name]

    if name == "accuweather":
        key = os.environ.get("ACCUWEATHER_API_KEY", "")
        provider = AccuWeatherProvider(key) if key else MockProvider()
    elif name == "kma":
        key = os.environ.get("KMA_SERVICE_KEY", "")
        provider = KmaProvider(key) if key else MockProvider()
    else:
        provider = MockProvider()

    _instances[name] = provider
    return provider


def _default_provider_name() -> str:
    preferred = os.environ.get("DEFAULT_WEATHER_PROVIDER", "").strip().lower()
    if preferred in ("accuweather", "kma") and os.environ.get(
        "ACCUWEATHER_API_KEY" if preferred == "accuweather" else "KMA_SERVICE_KEY"
    ):
        return preferred
    if os.environ.get("ACCUWEATHER_API_KEY"):
        return "accuweather"
    if os.environ.get("KMA_SERVICE_KEY"):
        return "kma"
    return "mock"


def available_providers() -> list:
    providers = ["mock"]
    if os.environ.get("KMA_SERVICE_KEY"):
        providers.append("kma")
    if os.environ.get("ACCUWEATHER_API_KEY"):
        providers.append("accuweather")
    return providers
