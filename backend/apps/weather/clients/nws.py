"""National Weather Service (NWS / NOAA) forecast client (keyless, US-only).

Responsibilities: HTTP transport, timeouts, provider error mapping and
hourly forecast parsing. NWS is completely free (no API key, no credit card)
and covers the United States only.

NWS uses a two-step API: ``/points/{lat},{lon}`` resolves a grid office, then
the ``forecastHourly`` URL returns hourly periods. The client hides both steps
behind the same ``fetch``/``fetch_hourly`` interface the other providers use.

Performance: the /points response (office + grid + forecast URL) is cached
in-process for 1 hour so repeat fetches for the same location skip a round
trip. Forecast responses are cached by the service layer (Redis, 15 min).
"""

import logging
import time
from datetime import UTC, datetime
from typing import NamedTuple

import requests
from django.conf import settings

from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError

logger = logging.getLogger(__name__)

DEFAULT_RETRY_AFTER = 60
MAX_HOURS = 48
POINTS_PATH = "https://api.weather.gov/points/{lat},{lon}"
USER_AGENT_HEADER = "User-Agent"

# In-process cache for /points responses (office + forecast URL). NWS /points
# is stable per location, so a 1-hour TTL avoids a round trip on every fetch.
_POINTS_CACHE: dict[tuple[float, float], tuple[dict, float]] = {}
_POINTS_TTL_SECONDS = 3600


def _round_coord(value: float) -> float:
    return round(value, 4)


def _cached_points(lat: float, lon: float) -> dict | None:
    key = (_round_coord(lat), _round_coord(lon))
    entry = _POINTS_CACHE.get(key)
    if entry is None:
        return None
    payload, expires_at = entry
    if time.monotonic() > expires_at:
        del _POINTS_CACHE[key]
        return None
    return payload


def _store_points(lat: float, lon: float, payload: dict) -> None:
    key = (_round_coord(lat), _round_coord(lon))
    _POINTS_CACHE[key] = (payload, time.monotonic() + _POINTS_TTL_SECONDS)


def clear_points_cache() -> None:
    """Clear the in-process /points cache (used by tests)."""
    _POINTS_CACHE.clear()


def _conditions_from_text(short_forecast: str) -> str:
    return short_forecast or ""


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
    """Thin, testable wrapper around the NWS forecast API."""

    def __init__(self, timeout: float | None = None, base_url: str | None = None):
        self.timeout = timeout if timeout is not None else settings.WEATHER_TIMEOUT
        self.base_url = base_url or settings.NWS_BASE_URL
        self.session = requests.Session()
        self.session.headers.update(
            {
                USER_AGENT_HEADER: getattr(settings, "NWS_USER_AGENT", "Routing-Assessment/1.0"),
                "Accept": "application/geo+json",
            }
        )

    def fetch_hourly(self, lat: float, lon: float) -> list[HourlyForecast]:
        return self.fetch(lat, lon)[0]

    def fetch(self, lat: float, lon: float) -> tuple[list[HourlyForecast], dict]:
        points = _cached_points(lat, lon)
        if points is None:
            points = self._get_json(POINTS_PATH.format(lat=lat, lon=lon))
            _store_points(lat, lon, points)
        properties = (points or {}).get("properties") or {}
        forecast_url = properties.get("forecastHourly")
        if not forecast_url:
            raise WeatherProviderError("Weather provider returned an invalid response.")

        forecast = self._get_json(forecast_url)
        periods = ((forecast or {}).get("properties") or {}).get("periods")
        if not isinstance(periods, list):
            raise WeatherProviderError("Weather provider returned an invalid response.")

        try:
            forecasts = [self._parse_period(p) for p in periods[:MAX_HOURS]]
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherProviderError("Weather provider returned an invalid response.") from exc
        if not forecasts:
            raise WeatherProviderError("Weather provider returned an invalid response.")
        return forecasts, forecast

    def _parse_period(self, period: dict) -> HourlyForecast:
        start = period.get("startTime")
        dt = datetime.fromisoformat(start).astimezone(UTC) if start else datetime.now(tz=UTC)
        temp = period.get("temperature") or 0
        wind_speed = period.get("windSpeed") or {}
        if isinstance(wind_speed, dict):
            speed_val = wind_speed.get("value") or 0
        else:
            try:
                speed_val = float(str(wind_speed).split()[0])
            except (ValueError, IndexError):
                speed_val = 0
        wind_dir = period.get("windDirection") or {}
        wind_deg = int(wind_dir.get("value") or 0) if isinstance(wind_dir, dict) else 0
        pop = period.get("probabilityOfPrecipitation") or {}
        pop_pct = int(pop.get("value") or 0) if isinstance(pop, dict) else 0
        short = period.get("shortForecast") or ""
        text = short.lower()
        if "snow" in text:
            precip_type = "snow"
        elif "rain" in text or "shower" in text or "drizzle" in text:
            precip_type = "rain"
        else:
            precip_type = "none"
        rate = round(pop_pct / 100.0, 2)
        snowfall = rate if precip_type == "snow" else 0.0
        return HourlyForecast(
            dt=dt,
            temp_f=float(temp),
            humidity=0,
            wind_speed_mph=float(speed_val),
            wind_deg=wind_deg,
            wind_gust_mph=None,
            precipitation_rate_in_hr=rate,
            precipitation_type=precip_type,
            snowfall_rate_in_hr=snowfall,
            conditions=_conditions_from_text(short),
            visibility_mi=None,
        )

    def _get_json(self, url: str) -> dict:
        started = time.monotonic()
        try:
            response = self.session.get(url, timeout=self.timeout)
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
            return response.json()
        except ValueError as exc:
            raise WeatherProviderError("Weather provider returned an invalid response.") from exc
