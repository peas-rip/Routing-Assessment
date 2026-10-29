"""OSRM (Open Source Routing Machine) directions client.

Free, keyless public demo server. Supports alternative routes for long trips
that OpenRouteService's alternative-routes algorithm caps at ~100 km.
"""

import logging
import time
from typing import NamedTuple

import requests
from django.conf import settings

from apps.routing.exceptions import NoRouteFoundError, RoutingProviderError, RoutingRateLimitError

logger = logging.getLogger(__name__)

DEFAULT_RETRY_AFTER = 60
MAX_ROUTES = 3
METERS_PER_MILE = 1609.344


class RouteData(NamedTuple):
    distance_miles: float
    duration_minutes: int
    geometry: dict | str | None
    summary: dict


def parse_route(route: dict) -> RouteData | None:
    if not isinstance(route, dict):
        return None
    distance = route.get("distance")
    duration = route.get("duration")
    if isinstance(distance, bool) or isinstance(duration, bool):
        return None
    if not isinstance(distance, int | float) or not isinstance(duration, int | float):
        return None
    if distance <= 0 or duration <= 0:
        return None
    geometry = route.get("geometry")
    summary = {"distance": distance, "duration": duration}
    return RouteData(
        distance_miles=round(distance / METERS_PER_MILE, 2),
        duration_minutes=round(duration / 60),
        geometry=geometry,
        summary=summary,
    )


def parse_routes(payload: dict) -> list[RouteData]:
    entries = (payload or {}).get("routes") or []
    return [parsed for entry in entries if (parsed := parse_route(entry))]


class RoutingClient:
    def __init__(self, timeout: float | None = None, base_url: str | None = None):
        self.timeout = (
            timeout if timeout is not None else getattr(settings, "ROUTING_TIMEOUT", 30.0)
        )
        self.base_url = (
            base_url or getattr(settings, "OSRM_BASE_URL", "https://router.project-osrm.org")
        ).rstrip("/")
        self.session = requests.Session()

    def get_routes(self, origin, destination) -> list[RouteData]:
        coords = f"{origin.x},{origin.y};{destination.x},{destination.y}"
        url = f"{self.base_url}/route/v1/driving/{coords}"
        params = {
            "alternatives": "true",
            "geometries": "geojson",
            "overview": "full",
            "steps": "true",
        }
        started = time.monotonic()
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RoutingProviderError(
                "Routing provider is unavailable.",
                details={"reason": exc.__class__.__name__, "provider": "osrm"},
            ) from exc
        finally:
            logger.debug(
                "Routing provider GET %s completed in %.3fs", url, time.monotonic() - started
            )

        if response.status_code == 429:
            raise RoutingRateLimitError(int(response.headers.get("Retry-After", 60)))
        if response.status_code >= 400:
            raise RoutingProviderError(
                "Routing provider returned an error.",
                details={"status_code": response.status_code, "provider": "osrm"},
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise RoutingProviderError("Routing provider returned an invalid response.") from exc

        routes = parse_routes(data)
        if not routes:
            raise NoRouteFoundError()
        return routes[:MAX_ROUTES]
