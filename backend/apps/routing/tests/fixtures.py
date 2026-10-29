"""Mock OpenRouteService payloads and shared builders for routing tests."""

import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.gis.geos import LineString
from django.utils import timezone

from apps.routing.models import Route, RouteRequest

# The active routing provider (OSRM) issues a GET whose path embeds the
# coordinates; a regex matches any origin/destination pair in one registration.
OSRM_ROUTE_URL = re.compile(r"https://router\.project-osrm\.org/route/v1/driving/.*")

# docs/SERVICES/routing/TESTING.md fixture: 3 alternatives (distance in
# meters, duration in seconds) with GeoJSON geometry.
MOCK_ORS_RESPONSE_3_ROUTES = {
    "routes": [
        {
            "geometry": {
                "type": "LineString",
                "coordinates": [[-89.65, 39.78], [-87.63, 41.88]],
            },
            "distance": 325800,
            "duration": 11700,
        },
        {
            "geometry": {
                "type": "LineString",
                "coordinates": [[-89.65, 39.78], [-88.00, 40.50], [-87.63, 41.88]],
            },
            "distance": 318000,
            "duration": 12600,
        },
        {
            "geometry": {
                "type": "LineString",
                "coordinates": [[-89.65, 39.78], [-88.50, 40.00], [-87.63, 41.88]],
            },
            "distance": 338000,
            "duration": 12000,
        },
    ]
}

MOCK_ORS_RESPONSE_1_ROUTE = {"routes": [MOCK_ORS_RESPONSE_3_ROUTES["routes"][0]]}
MOCK_ORS_RESPONSE_EMPTY = {"routes": []}

# Real ORS JSON puts distance/duration inside ``summary`` only.
MOCK_ORS_RESPONSE_SUMMARY_STYLE = {
    "routes": [
        {
            "geometry": {
                "type": "LineString",
                "coordinates": [[-89.65, 39.78], [-87.63, 41.88]],
            },
            "summary": {"distance": 325800, "duration": 11700, "weight": 11700},
        }
    ]
}

# One malformed entry (no distance) that must be skipped.
MOCK_ORS_RESPONSE_MALFORMED = {
    "routes": [
        {
            "geometry": {
                "type": "LineString",
                "coordinates": [[-89.65, 39.78], [-87.63, 41.88]],
            },
            "duration": 1000,
        },
        MOCK_ORS_RESPONSE_3_ROUTES["routes"][1],
    ]
}

# ~2 mile route (3218 m) for short-route checkpoint behavior.
MOCK_ORS_RESPONSE_SHORT_ROUTE = {
    "routes": [
        {
            "geometry": {
                "type": "LineString",
                "coordinates": [[-89.65, 39.78], [-89.64, 39.80]],
            },
            "distance": 3218,
            "duration": 300,
        }
    ]
}


def future_departure(hours: float = 6) -> str:
    """Dynamic future departure time (tests must not hardcode dates)."""
    return (timezone.now() + timedelta(hours=hours)).isoformat()


def valid_generate_payload(**overrides) -> dict:
    """A valid POST /api/v1/routes/generate/ body."""
    payload = {
        "origin": {"address": "Springfield, IL", "latitude": 39.7817, "longitude": -89.6501},
        "destination": {"address": "Chicago, IL", "latitude": 41.8781, "longitude": -87.6298},
        "departure_time": future_departure(),
        "load_weight_lbs": 45000,
    }
    payload.update(overrides)
    return payload


def make_route_request(**overrides) -> RouteRequest:
    """Persist a RouteRequest directly (bypasses API validation)."""
    defaults = {
        "origin_address": "Springfield, IL",
        "origin_lat": 39.7817,
        "origin_lon": -89.6501,
        "destination_address": "Chicago, IL",
        "destination_lat": 41.8781,
        "destination_lon": -87.6298,
        "departure_time": timezone.now() + timedelta(hours=6),
        "load_weight_lbs": 45000,
    }
    defaults.update(overrides)
    return RouteRequest.objects.create(**defaults)


def make_route(route_request: RouteRequest | None = None, **overrides) -> Route:
    """Persist a Route with a straight-line geometry (defaults to 100 mi)."""
    if route_request is None:
        route_request = make_route_request()
    defaults = {
        "route_index": 0,
        "name": "Fastest",
        "distance_miles": Decimal("100.00"),
        "duration_minutes": 120,
        "geometry": LineString([(-89.65, 39.78), (-87.63, 41.88)], srid=4326),
        "summary": {"distance": 160934.4, "duration": 7200},
    }
    defaults.update(overrides)
    return Route.objects.create(request=route_request, **defaults)
