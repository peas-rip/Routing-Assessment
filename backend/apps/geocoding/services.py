"""Geocoding business logic: two-tier cache (Redis hot cache + DB cache)
in front of the OpenRouteService provider.

Cache tiers:
- Redis: parsed results, 1 hour TTL (sub-ms reads).
- PostgreSQL (GeocodeCache): full provider payload, 30 day TTL (durability).

A Redis outage degrades to the DB tier; a DB write failure never fails the
request because the provider result is already in hand.
"""

import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone

from .exceptions import GeocodingNotFoundError
from .models import GeocodeCache, QueryType

logger = logging.getLogger(__name__)

SOURCE = getattr(settings, "GEOCODING_PROVIDER", "openrouteservice")
REDIS_TTL_SECONDS = 3600
DB_TTL_DAYS = 30
SEARCH_CACHE_PREFIX = "geocode:search"
REVERSE_CACHE_PREFIX = "geocode:reverse"


def normalize_query(query: str) -> str:
    """Normalize a query for cache reuse (case, whitespace)."""
    return " ".join(query.split()).lower()


def _format_coord(value: float | None) -> str:
    return f"{value:.5f}" if value is not None else ""


def _search_cache_key(
    normalized_query: str, limit: int, lat: float | None, lon: float | None
) -> str:
    return f"{SEARCH_CACHE_PREFIX}:{normalized_query}:{limit}:{_format_coord(lat)}:{_format_coord(lon)}"


def _reverse_cache_key(lat: float, lon: float) -> str:
    return f"{REVERSE_CACHE_PREFIX}:{_format_coord(lat)}:{_format_coord(lon)}"


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        logger.warning("Redis cache read failed for key %s", key, exc_info=True)
        return None


def _cache_set(key: str, value) -> None:
    try:
        cache.set(key, value, REDIS_TTL_SECONDS)
    except Exception:
        logger.warning("Redis cache write failed for key %s", key, exc_info=True)


def _store_db_cache(
    *,
    query_text: str,
    query_type: str,
    raw: dict,
    latitude: float | None,
    longitude: float | None,
    display_name: str,
    address_components: dict,
) -> None:
    try:
        GeocodeCache.objects.update_or_create(
            query_text=query_text,
            query_type=query_type,
            defaults={
                "latitude": latitude,
                "longitude": longitude,
                "display_name": display_name,
                "address_components": address_components,
                "raw_response": raw,
                "source": SOURCE,
                "expires_at": timezone.now() + timedelta(days=DB_TTL_DAYS),
            },
        )
    except DatabaseError:
        # Caching is best-effort: the caller already has fresh results.
        logger.warning("Geocode DB cache write failed", exc_info=True)


def _get_client():
    """Return the configured geocoding provider client."""
    if settings.GEOCODING_PROVIDER == "photon":
        from .clients.photon import GeocodingClient

        return GeocodingClient()
    from .clients.openrouteservice import GeocodingClient

    return GeocodingClient()


def _parse_search(raw):
    if settings.GEOCODING_PROVIDER == "photon":
        from .clients.photon import parse_search_payload

        return parse_search_payload(raw)
    from .clients.openrouteservice import parse_search_payload

    return parse_search_payload(raw)


def _parse_reverse(raw):
    if settings.GEOCODING_PROVIDER == "photon":
        from .clients.photon import parse_reverse_payload

        return parse_reverse_payload(raw)
    from .clients.openrouteservice import parse_reverse_payload

    return parse_reverse_payload(raw)


def search(
    query: str, limit: int = 5, lat: float | None = None, lon: float | None = None
) -> tuple[list[dict], bool]:
    """Return ``(results, was_cached)`` for an address search."""
    normalized = normalize_query(query)
    cache_key = _search_cache_key(normalized, limit, lat, lon)

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True

    db_cached = (
        GeocodeCache.objects.valid()
        .filter(query_text=normalized, query_type=QueryType.AUTOCOMPLETE)
        .first()
    )
    if db_cached:
        results = _parse_search(db_cached.raw_response)
        if len(results) >= limit:
            results = results[:limit]
            _cache_set(cache_key, results)
            return results, True

    started = time.monotonic()
    response = _get_client().search(query, limit=limit, lat=lat, lon=lon)
    latency_ms = (time.monotonic() - started) * 1000

    results = response.results[:limit]
    _cache_set(cache_key, results)

    primary = results[0] if results else {}
    _store_db_cache(
        query_text=normalized,
        query_type=QueryType.AUTOCOMPLETE,
        raw=response.raw,
        latitude=primary.get("latitude"),
        longitude=primary.get("longitude"),
        display_name=primary.get("display_name", ""),
        address_components=primary.get("address", {}),
    )

    logger.info(
        "geocode.search",
        extra={
            "query_length": len(normalized),
            "result_count": len(results),
            "latency_ms": round(latency_ms, 1),
            "cached": False,
        },
    )
    return results, False


def reverse(lat: float, lon: float) -> tuple[dict, bool]:
    """Return ``(result, was_cached)`` for reverse geocoding.

    Raises GeocodingNotFoundError when the provider has no result.
    """
    query_text = f"{_format_coord(lat)},{_format_coord(lon)}"
    cache_key = _reverse_cache_key(lat, lon)

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached, True

    db_cached = (
        GeocodeCache.objects.valid()
        .filter(query_text=query_text, query_type=QueryType.REVERSE)
        .first()
    )
    if db_cached:
        result = _parse_reverse(db_cached.raw_response)
        if result:
            _cache_set(cache_key, result)
            return result, True

    response = _get_client().reverse(lat, lon)
    if response is None or not response.results:
        raise GeocodingNotFoundError(details={"latitude": lat, "longitude": lon})

    result = response.results[0]
    _cache_set(cache_key, result)
    _store_db_cache(
        query_text=query_text,
        query_type=QueryType.REVERSE,
        raw=response.raw,
        latitude=result.get("latitude"),
        longitude=result.get("longitude"),
        display_name=result.get("display_name", ""),
        address_components=result.get("address", {}),
    )
    return result, False
