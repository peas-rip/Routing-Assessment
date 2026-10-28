"""OpenRouteService geocoding client (Pelias-based /geocode endpoints).

Responsibilities: HTTP transport, timeouts, provider error mapping and
response parsing. Business/caching logic lives in apps.geocoding.services.
"""

import logging
import time
from typing import NamedTuple

import requests
from django.conf import settings

from apps.geocoding.exceptions import (
    GeocodingNotFoundError,
    GeocodingProviderError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

SOURCE = "openrouteservice"
SEARCH_PATH = "/geocode/search"
REVERSE_PATH = "/geocode/reverse"
DEFAULT_RETRY_AFTER = 60


class GeocodeResponse(NamedTuple):
    """Parsed provider result plus the raw payload (used for DB cache replay)."""

    results: list[dict]
    raw: dict


def _clean_address(properties: dict) -> dict:
    mapping = {
        "house_number": properties.get("housenumber"),
        "road": properties.get("street"),
        "city": properties.get("locality") or properties.get("borough"),
        "state": properties.get("region_a") or properties.get("region"),
        "postcode": properties.get("postalcode"),
        "country": properties.get("country"),
    }
    return {key: value for key, value in mapping.items() if value}


def parse_feature(feature: dict) -> dict | None:
    """Convert one Pelias GeoJSON feature into the API result shape."""
    if not feature or not feature.get("geometry"):
        return None
    properties = feature.get("properties") or {}
    coordinates = feature["geometry"].get("coordinates") or []
    if len(coordinates) < 2:
        return None

    place_id = (
        f"{properties.get('source', SOURCE)}_{properties.get('source_id')}"
        if properties.get("source_id")
        else properties.get("gid") or properties.get("id") or ""
    )
    display_name = properties.get("label") or properties.get("name") or ""

    return {
        "place_id": str(place_id),
        "display_name": display_name,
        "latitude": coordinates[1],
        "longitude": coordinates[0],
        "address": _clean_address(properties),
        "type": properties.get("layer", "address"),
    }


def parse_search_payload(payload: dict) -> list[dict]:
    """Parse a /geocode/search payload into a list of results."""
    features = (payload or {}).get("features") or []
    return [parsed for feature in features if (parsed := parse_feature(feature))]


def parse_reverse_payload(payload: dict) -> dict | None:
    """Parse a /geocode/reverse payload (a single GeoJSON feature)."""
    return parse_feature(payload or {})


class GeocodingClient:
    """Thin, testable wrapper around the OpenRouteService geocoding API."""

    def __init__(
        self, api_key: str | None = None, timeout: float | None = None, base_url: str | None = None
    ):
        self.api_key = api_key if api_key is not None else settings.OPENROUTESERVICE_API_KEY
        self.timeout = timeout if timeout is not None else settings.EXTERNAL_API_TIMEOUT
        self.base_url = (base_url or settings.OPENROUTESERVICE_BASE_URL).rstrip("/")
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": self.api_key})

    def search(
        self, query: str, limit: int = 5, lat: float | None = None, lon: float | None = None
    ) -> GeocodeResponse:
        params: dict = {"text": query, "size": limit}
        if lat is not None and lon is not None:
            params["focus.point.lat"] = lat
            params["focus.point.lon"] = lon
        payload = self._request("GET", SEARCH_PATH, params=params)
        return GeocodeResponse(results=parse_search_payload(payload), raw=payload)

    def reverse(self, lat: float, lon: float) -> GeocodeResponse | None:
        params = {"point.lat": lat, "point.lon": lon}
        try:
            payload = self._request("GET", REVERSE_PATH, params=params, allow_not_found=True)
        except GeocodingNotFoundError:
            return None
        result = parse_reverse_payload(payload)
        if result is None:
            return None
        return GeocodeResponse(results=[result], raw=payload)

    def _request(self, method: str, path: str, params: dict, allow_not_found: bool = False) -> dict:
        if not self.api_key:
            raise GeocodingProviderError("OpenRouteService API key is not configured.")

        url = f"{self.base_url}{path}"
        started = time.monotonic()
        try:
            response = self.session.request(method, url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("Geocoding provider request failed: %s", exc.__class__.__name__)
            raise GeocodingProviderError(
                "Geocoding provider is unavailable.", details={"reason": exc.__class__.__name__}
            ) from exc
        finally:
            logger.debug(
                "Geocoding provider %s %s completed in %.3fs",
                method,
                path,
                time.monotonic() - started,
            )

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER))
            raise RateLimitError(retry_after)

        if response.status_code == 404:
            if allow_not_found:
                raise GeocodingNotFoundError()
            raise GeocodingProviderError(
                "Geocoding provider returned an unexpected 404.",
                details={"status_code": 404},
            )

        if response.status_code >= 400:
            raise GeocodingProviderError(
                "Geocoding provider returned an error.",
                details={"status_code": response.status_code},
            )

        try:
            return response.json()
        except ValueError as exc:
            raise GeocodingProviderError(
                "Geocoding provider returned an invalid response."
            ) from exc
