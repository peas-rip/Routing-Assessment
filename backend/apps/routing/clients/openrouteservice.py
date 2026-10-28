"""OpenRouteService directions client (POST /v2/directions/driving-hgv).

Responsibilities: HTTP transport, timeouts, provider error mapping and
response parsing. Business/persistence logic lives in apps.routing.services.

Per docs/API_CONTRACTS.md the stored ``summary`` keeps the raw provider
payload (distance in meters, duration in seconds) while ``distance_miles`` /
``duration_minutes`` are derived for the API response (docs/FEATURES/
FEATURE_02: distance in miles with 2 decimals, duration in minutes).
"""

import logging
import time
from typing import NamedTuple

import requests
from django.conf import settings

from apps.routing.exceptions import (
    NoRouteFoundError,
    RoutingProviderError,
    RoutingRateLimitError,
)

logger = logging.getLogger(__name__)

DIRECTIONS_PATH = "/v2/directions/driving-hgv"
PROFILE = "driving-hgv"
DEFAULT_RETRY_AFTER = 60
METERS_PER_MILE = 1609.344
MAX_ROUTES = 3


class RouteData(NamedTuple):
    """One parsed route option from the provider."""

    distance_miles: float
    duration_minutes: int
    geometry: dict | str | None
    summary: dict


def _positive_number(route: dict, key: str) -> float | None:
    """Read ``key`` from the route body, falling back to its ``summary``."""
    value = route.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        summary = route.get("summary")
        value = summary.get(key) if isinstance(summary, dict) else None
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def parse_route(route: dict) -> RouteData | None:
    """Convert one provider route entry, or ``None`` when it is unusable."""
    if not isinstance(route, dict):
        return None
    distance = _positive_number(route, "distance")
    duration = _positive_number(route, "duration")
    if distance is None or duration is None:
        return None
    summary = route.get("summary")
    if not isinstance(summary, dict):
        summary = {"distance": distance, "duration": duration}
    return RouteData(
        distance_miles=round(distance / METERS_PER_MILE, 2),
        duration_minutes=round(duration / 60),
        geometry=route.get("geometry"),
        summary=summary,
    )


def parse_routes(payload: dict) -> list[RouteData]:
    """Parse a directions payload, skipping malformed route entries."""
    entries = (payload or {}).get("routes") or []
    return [parsed for entry in entries if (parsed := parse_route(entry))]


class RoutingClient:
    """Thin, testable wrapper around the OpenRouteService directions API."""

    def __init__(
        self, api_key: str | None = None, timeout: float | None = None, base_url: str | None = None
    ):
        self.api_key = api_key if api_key is not None else settings.OPENROUTESERVICE_API_KEY
        self.timeout = timeout if timeout is not None else settings.ROUTING_TIMEOUT
        self.base_url = (base_url or settings.OPENROUTESERVICE_BASE_URL).rstrip("/")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": self.api_key})

    def get_routes(self, origin, destination) -> list[RouteData]:
        """Get up to 3 alternative HGV routes between two GEOS points."""
        payload = {
            "coordinates": [[origin.x, origin.y], [destination.x, destination.y]],
            "profile": PROFILE,
            "alternative_routes": {
                "target_count": MAX_ROUTES,
                "share_factor": 0.6,
                "weight_factor": 1.5,
            },
            "instructions": True,
            "geometry": True,
            "geometry_format": "geojson",
            "units": "mi",
        }
        data = self._request(payload)
        routes = parse_routes(data)
        if not routes:
            raise NoRouteFoundError()
        return routes

    def _request(self, payload: dict) -> dict:
        if not self.api_key:
            raise RoutingProviderError("OpenRouteService API key is not configured.")

        url = f"{self.base_url}{DIRECTIONS_PATH}"
        started = time.monotonic()
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("Routing provider request failed: %s", exc.__class__.__name__)
            raise RoutingProviderError(
                "Routing provider is unavailable.", details={"reason": exc.__class__.__name__}
            ) from exc
        finally:
            logger.debug(
                "Routing provider POST %s completed in %.3fs",
                DIRECTIONS_PATH,
                time.monotonic() - started,
            )

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER))
            raise RoutingRateLimitError(retry_after)

        if response.status_code >= 400:
            raise RoutingProviderError(
                "Routing provider returned an error.",
                details={"status_code": response.status_code},
            )

        try:
            return response.json()
        except ValueError as exc:
            raise RoutingProviderError("Routing provider returned an invalid response.") from exc
