"""Geometry helpers and route naming (docs/FEATURES/FEATURE_02)."""

import ctypes

from django.contrib.gis.geos import GEOSException, LineString

from .exceptions import RoutingProviderError


def name_route(route, index: int, all_routes) -> str:
    """Label a route option: Fastest/Shortest/Balanced by index.

    Fallback (index out of 0-2): compare against the other options.
    """
    if index == 0:
        return "Fastest"
    if index == 1:
        return "Shortest"
    if index == 2:
        return "Balanced"
    fastest = min(all_routes, key=lambda item: item.duration_minutes)
    shortest = min(all_routes, key=lambda item: item.distance_miles)
    if route is fastest:
        return "Fastest"
    if route is shortest:
        return "Shortest"
    return f"Alternative {index + 1}"


def to_linestring(geometry) -> LineString:
    """Convert a GeoJSON LineString payload into a WGS84 GEOS LineString."""
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise RoutingProviderError("Routing provider returned a route without usable geometry.")
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2:
        raise RoutingProviderError("Routing provider returned a degenerate route geometry.")
    try:
        return LineString([tuple(coordinate[:2]) for coordinate in coordinates], srid=4326)
    except (TypeError, ValueError, GEOSException, ctypes.ArgumentError) as exc:
        raise RoutingProviderError("Routing provider returned an invalid route geometry.") from exc
