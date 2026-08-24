"""Common interface every weather data provider implements.

All providers return the same shaped dict so the frontend can render
current conditions, hourly/daily forecasts, alerts and air quality the
same way regardless of whether the data came from AccuWeather, KMA
(Korea Meteorological Administration), or the built-in mock provider.
"""

from abc import ABC, abstractmethod


class WeatherProvider(ABC):
    name = "base"

    @abstractmethod
    def get_weather(self, location: dict) -> dict:
        """Return the full weather bundle for a location dict from locations.py.

        Shape:
        {
          "provider": str,
          "location": {"id", "name", "lat", "lon"},
          "current": {
             "temp", "feels_like", "humidity", "wind_speed", "wind_dir",
             "sky", "sky_code", "precip_type", "precip_prob",
             "pm10", "pm10_grade", "pm25", "pm25_grade", "updated_at"
          },
          "hourly": [
             {"time", "temp", "sky", "sky_code", "precip_prob", "precip_type"}, ...
          ],
          "daily": [
             {"date", "label", "temp_min", "temp_max",
              "sky_am", "sky_pm", "precip_prob_am", "precip_prob_pm"}, ...
          ],
          "alerts": [
             {"level", "title", "area", "description", "issued_at"}, ...
          ],
        }
        """
        raise NotImplementedError
