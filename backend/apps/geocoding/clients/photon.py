"""Photon (Komoot OSM) geocoding client (keyless, free).

Alternative geocoder selected by settings.GEOCODING_PROVIDER. Mirrors the
GeocodingClient interface (search/reverse + GeocodeResponse) so the service
can swap providers without changes.
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

SOURCE = "photon"
SEARCH_PATH = "/api/"
REVERSE_PATH = "/reverse"
DEFAULT_RETRY_AFTER = 60


class GeocodeResponse(NamedTuple):
    results: list[dict]
    raw: dict


def _clean_address(properties: dict) -> dict:
    mapping = {
        "house_number": properties.get("housenumber"),
        "road": properties.get("street"),
        "city": properties.get("city") or properties.get("district"),
        "state": properties.get("state"),
        "postcode": properties.get("postcode"),
        "country": properties.get("country"),
    }
    return {key: value for key, value in mapping.items() if value}


def _normalize_type(properties: dict) -> str:
    return properties.get("osm_value") or properties.get("type") or "address"


def parse_feature(feature: dict) -> dict | None:
    if not isinstance(feature, dict):
        return None
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    properties = feature.get("properties") or {}
    if len(coordinates) < 2:
        return None
    try:
        lat = float(coordinates[1])
        lon = float(coordinates[0])
    except (TypeError, ValueError):
        return None
    place_id = properties.get("osm_id") or properties.get("id") or ""
    display_name = properties.get("name") or ""
    if properties.get("street"):
        display_name = f"{properties.get('street')} {display_name}".strip()
    return {
        "place_id": str(place_id),
        "display_name": display_name,
        "latitude": lat,
        "longitude": lon,
        "address": _clean_address(properties),
        "type": _normalize_type(properties),
    }


def parse_search_payload(payload) -> list[dict]:
    features = (payload or {}).get("features") or []
    return [parsed for feature in features if (parsed := parse_feature(feature))]


def parse_reverse_payload(payload) -> dict | None:
    if isinstance(payload, dict) and payload.get("features"):
        return parse_feature(payload["features"][0])
    return None


class GeocodingClient:
    """Thin, testable wrapper around the Photon geocoding API."""

    def __init__(self, timeout: float | None = None, base_url: str | None = None):
        self.timeout = timeout if timeout is not None else settings.EXTERNAL_API_TIMEOUT
        self.base_url = (base_url or settings.PHOTON_BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": getattr(settings, "NOMINATIM_USER_AGENT", "Routing-Assessment/1.0")}
        )

    def search(
        self, query: str, limit: int = 5, lat: float | None = None, lon: float | None = None
    ) -> GeocodeResponse:
        params: dict = {"q": query, "limit": limit}
        if lat is not None and lon is not None:
            params["lat"] = lat
            params["lon"] = lon
        payload = self._request("GET", SEARCH_PATH, params=params)
        return GeocodeResponse(results=parse_search_payload(payload), raw=payload)

    def reverse(self, lat: float, lon: float) -> GeocodeResponse | None:
        params = {"lat": lat, "lon": lon}
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
