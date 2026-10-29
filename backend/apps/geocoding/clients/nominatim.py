"""Nominatim (OpenStreetMap) geocoding client (keyless, free).

Responsibilities: HTTP transport, timeouts, provider error mapping and
response parsing. Business/caching logic lives in apps.geocoding.services.

Nominatim requires a descriptive User-Agent and is rate-limited to ~1 req/s
for the public instance.
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

SOURCE = "nominatim"
SEARCH_PATH = "/search"
REVERSE_PATH = "/reverse"
DEFAULT_RETRY_AFTER = 60


class GeocodeResponse(NamedTuple):
    """Parsed provider result plus the raw payload (used for DB cache replay)."""

    results: list[dict]
    raw: dict


def _clean_address(properties: dict) -> dict:
    address = properties if isinstance(properties, dict) else {}
    city = address.get("city") or address.get("town") or address.get("village") or address.get("municipality")
    mapping = {
        "house_number": address.get("house_number"),
        "road": address.get("road"),
        "city": city,
        "state": address.get("state"),
        "postcode": address.get("postcode"),
        "country": address.get("country"),
    }
    return {key: value for key, value in mapping.items() if value}


def _normalize_type(item: dict) -> str:
    return item.get("type") or item.get("class") or "address"


def parse_feature(item: dict) -> dict | None:
    """Convert one Nominatim result into the API result shape."""
    if not isinstance(item, dict):
        return None
    try:
        lat = float(item.get("lat"))
        lon = float(item.get("lon"))
    except (TypeError, ValueError):
        return None
    address = item.get("address") or {}
    display_name = item.get("display_name") or ""
    place_id = item.get("place_id")
    if place_id is None:
        place_id = item.get("osm_id") or ""
    return {
        "place_id": str(place_id),
        "display_name": display_name,
        "latitude": lat,
        "longitude": lon,
        "address": _clean_address(address),
        "type": _normalize_type(item),
    }


def parse_search_payload(payload) -> list[dict]:
    """Parse a Nominatim search payload (list) into results."""
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        entries = payload.get("results") or payload.get("features") or []
    else:
        entries = []
    return [parsed for entry in entries if (parsed := parse_feature(entry))]


def parse_reverse_payload(payload) -> dict | None:
    """Parse a Nominatim reverse payload (a single object)."""
    if isinstance(payload, dict) and "lat" in payload and "lon" in payload:
        return parse_feature(payload)
    if isinstance(payload, list) and payload:
        return parse_feature(payload[0])
    return None


class GeocodingClient:
    """Thin, testable wrapper around the Nominatim geocoding API."""

    def __init__(self, timeout: float | None = None, base_url: str | None = None):
        self.timeout = timeout if timeout is not None else settings.EXTERNAL_API_TIMEOUT
        self.base_url = (base_url or settings.NOMINATIM_BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": getattr(settings, "NOMINATIM_USER_AGENT", "Routing-Assessment/1.0")}
        )

    def search(
        self, query: str, limit: int = 5, lat: float | None = None, lon: float | None = None
    ) -> GeocodeResponse:
        params: dict = {"q": query, "format": "json", "limit": limit, "addressdetails": 1}
        payload = self._request("GET", SEARCH_PATH, params=params)
        return GeocodeResponse(results=parse_search_payload(payload), raw={"results": payload})

    def reverse(self, lat: float, lon: float) -> GeocodeResponse | None:
        params = {"format": "json", "lat": lat, "lon": lon, "addressdetails": 1}
        try:
            payload = self._request("GET", REVERSE_PATH, params=params, allow_not_found=True)
        except GeocodingNotFoundError:
            return None
        result = parse_reverse_payload(payload)
        if result is None:
            return None
        return GeocodeResponse(results=[result], raw=payload)

    def _request(self, method: str, path: str, params: dict, allow_not_found: bool = False) -> dict:
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
            logger.debug("Geocoding provider GET %s completed in %.3fs", path, time.monotonic() - started)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER))
            raise RateLimitError(retry_after)

        if response.status_code == 404 and allow_not_found:
            raise GeocodingNotFoundError(details={"path": path})

        if response.status_code >= 400:
            raise GeocodingProviderError(
                "Geocoding provider returned an error.",
                details={"status_code": response.status_code},
            )

        try:
            return response.json()
        except ValueError as exc:
            raise GeocodingProviderError("Geocoding provider returned an invalid response.") from exc
