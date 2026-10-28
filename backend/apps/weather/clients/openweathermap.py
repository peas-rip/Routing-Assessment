"""OpenWeatherMap One Call 3.0 client.

Responsibilities: HTTP transport, timeouts, provider error mapping and
hourly forecast parsing (docs/SERVICES/weather/SERVICE_SPEC.md). Units are
requested as imperial (°F, mph, inches) so values are stored as returned.
"""

import logging
import time
from datetime import UTC, datetime
from typing import NamedTuple

import requests
from django.conf import settings

from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError

from ..utils import classify_precipitation, meters_to_miles

logger = logging.getLogger(__name__)

DEFAULT_RETRY_AFTER = 60
MAX_HOURS = 48  # One Call 3.0 provides 48 hourly entries


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
    """Thin, testable wrapper around the OpenWeatherMap One Call API."""

    def __init__(
        self, api_key: str | None = None, timeout: float | None = None, base_url: str | None = None
    ):
        self.api_key = api_key if api_key is not None else settings.OPENWEATHERMAP_API_KEY
        self.timeout = timeout if timeout is not None else settings.WEATHER_TIMEOUT
        self.base_url = base_url or settings.OPENWEATHERMAP_BASE_URL
        self.session = requests.Session()

    def fetch_hourly(self, lat: float, lon: float) -> list[HourlyForecast]:
        """Fetch and parse the hourly forecast for one location."""
        return self.fetch(lat, lon)[0]

    def fetch(self, lat: float, lon: float) -> tuple[list[HourlyForecast], dict]:
        """Fetch hourly forecasts plus the raw payload (stored for debugging)."""
        if not self.api_key:
            raise WeatherProviderError("OpenWeatherMap API key is not configured.")

        params = {
            "lat": lat,
            "lon": lon,
            "exclude": "minutely,daily,alerts",
            "units": "imperial",  # mph, °F, inches
            "appid": self.api_key,
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
        if not isinstance(hourly, list):
            raise WeatherProviderError("Weather provider returned an invalid response.")

        try:
            return [self._parse_hourly_entry(entry) for entry in hourly[:MAX_HOURS]], payload
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherProviderError("Weather provider returned an invalid response.") from exc

    @staticmethod
    def _parse_hourly_entry(entry: dict) -> HourlyForecast:
        """Convert one provider hourly entry (F04 fields, imperial units)."""
        weather_entries = entry.get("weather") or []
        weather = weather_entries[0] if weather_entries else {}
        precip_type, precip_rate, snowfall = classify_precipitation(
            (entry.get("rain") or {}).get("1h"),
            (entry.get("snow") or {}).get("1h"),
        )
        return HourlyForecast(
            dt=datetime.fromtimestamp(entry["dt"], tz=UTC),
            temp_f=float(entry["temp"]),
            humidity=int(entry["humidity"]),
            wind_speed_mph=float(entry["wind_speed"]),
            wind_deg=int(entry["wind_deg"]),
            wind_gust_mph=entry.get("wind_gust"),
            precipitation_rate_in_hr=precip_rate,
            precipitation_type=precip_type,
            snowfall_rate_in_hr=snowfall,
            conditions=str(weather.get("description") or ""),
            visibility_mi=meters_to_miles(entry.get("visibility")),
        )
