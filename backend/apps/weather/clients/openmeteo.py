"""Open-Meteo Forecast client (keyless, non-commercial free tier).

Responsibilities: HTTP transport, timeouts, provider error mapping and hourly
forecast parsing (docs/SERVICES/weather/SERVICE_SPEC.md). Units are requested
as imperial (°F, mph, inches) so values are stored as returned, matching the
fields the risk engine consumes. Open-Meteo requires no API key.

Licensing: the Open-Meteo free API is intended for non-commercial use; see
docs/SERVICES/weather/SERVICE_SPEC.md.
"""

import logging
import time
from datetime import UTC, datetime
from typing import NamedTuple

import requests
from django.conf import settings

from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError

from ..utils import classify_precipitation

logger = logging.getLogger(__name__)

DEFAULT_RETRY_AFTER = 60
MAX_HOURS = 48  # enough to cover the 0-48h forecast slider

# Open-Meteo returns no visibility field, so it is always None.
HOURLY_VARIABLES = (
    "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,rain,snowfall,weather_code"
)

# WMO weather interpretation codes -> human readable condition text.
WMO_DESCRIPTIONS = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


class HourlyForecast(NamedTuple):
    """One parsed hourly forecast entry."""

    dt: datetime
    temp_f: float
    humidity: int
    wind_speed_mph: float
    wind_deg: int
    wind_gust_mph: float | None
    precipitation_rate_in_hr: float
    precipitation_type: str
    snowfall_rate_in_hr: float
    conditions: str
    visibility_mi: float | None = None


class WeatherClient:
    """Thin, testable wrapper around the Open-Meteo Forecast API."""

    def __init__(self, timeout: float | None = None, base_url: str | None = None):
        self.timeout = timeout if timeout is not None else settings.WEATHER_TIMEOUT
        self.base_url = base_url or settings.OPEN_METEO_BASE_URL
        self.session = requests.Session()

    def fetch_hourly(self, lat: float, lon: float) -> list[HourlyForecast]:
        """Fetch and parse the hourly forecast for one location."""
        return self.fetch(lat, lon)[0]

    def fetch(self, lat: float, lon: float) -> tuple[list[HourlyForecast], dict]:
        """Fetch hourly forecasts plus the raw payload (stored for debugging)."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": HOURLY_VARIABLES,
            "temperature_unit": "fahrenheit",  # °F
            "wind_speed_unit": "mph",  # mph
            "precipitation_unit": "inch",  # inches/hr
            "forecast_days": 3,  # slice to MAX_HOURS (0-48h slider)
            "timezone": "UTC",
        }
        started = time.monotonic()
        try:
            response = self.session.get(self.base_url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("Weather provider request failed: %s", exc.__class__.__name__)
            raise WeatherProviderError(
                "Weather provider is unavailable.", details={"reason": exc.__class__.__name__}
            ) from exc
        finally:
            logger.debug("Weather provider GET completed in %.3fs", time.monotonic() - started)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER))
            raise WeatherRateLimitError(retry_after)

        if response.status_code >= 400:
            raise WeatherProviderError(
                "Weather provider returned an error.",
                details={"status_code": response.status_code},
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherProviderError("Weather provider returned an invalid response.") from exc

        hourly = payload.get("hourly") if isinstance(payload, dict) else None
        if not isinstance(hourly, dict):
            raise WeatherProviderError("Weather provider returned an invalid response.")

        try:
            forecasts = self._parse_hourly(hourly)
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherProviderError("Weather provider returned an invalid response.") from exc

        if not forecasts:
            raise WeatherProviderError("Weather provider returned an invalid response.")
        return forecasts[:MAX_HOURS], payload

    @staticmethod
    def _series(hourly: dict, key: str) -> list:
        """Read one hourly series, erroring when it is missing."""
        values = hourly.get(key)
        if not isinstance(values, list):
            raise KeyError(key)
        return values

    @classmethod
    def _parse_hourly(cls, hourly: dict) -> list[HourlyForecast]:
        """Convert Open-Meteo hourly arrays into parsed forecast entries."""
        times = cls._series(hourly, "time")
        temps = cls._series(hourly, "temperature_2m")
        humidity = cls._series(hourly, "relative_humidity_2m")
        wind = cls._series(hourly, "wind_speed_10m")
        wind_dir = cls._series(hourly, "wind_direction_10m")
        gusts = cls._series(hourly, "wind_gusts_10m")
        rain = cls._series(hourly, "rain")
        snow = cls._series(hourly, "snowfall")
        codes = cls._series(hourly, "weather_code")

        forecasts: list[HourlyForecast] = []
        for i, timestamp in enumerate(times[:MAX_HOURS]):
            # Open-Meteo returns ISO-8601 local-to-timezone strings ("UTC" here).
            dt = datetime.fromisoformat(str(timestamp)).replace(tzinfo=UTC)
            gust = gusts[i] if i < len(gusts) else None
            precip_type, precip_rate, snowfall = classify_precipitation(
                rain[i] if i < len(rain) else 0,
                snow[i] if i < len(snow) else 0,
            )
            code = codes[i] if i < len(codes) else 0
            forecasts.append(
                HourlyForecast(
                    dt=dt,
                    temp_f=float(temps[i]),
                    humidity=int(humidity[i]),
                    wind_speed_mph=float(wind[i]),
                    wind_deg=int(wind_dir[i]),
                    wind_gust_mph=float(gust) if gust is not None else None,
                    precipitation_rate_in_hr=precip_rate,
                    precipitation_type=precip_type,
                    snowfall_rate_in_hr=snowfall,
                    conditions=WMO_DESCRIPTIONS.get(int(code) if code is not None else 0, "unknown"),
                    visibility_mi=None,
                )
            )
        return forecasts
