"""Routing business logic: generation, checkpoint sampling, ETA math.

Implements F02 (route generation) and F03 (checkpoint sampling):

* Sample checkpoints at 10/25/50 mile intervals; origin (mile 0) is always
  sequence 0 and the destination (final mile) is always the last checkpoint.
* ETA = departure_time + (mile_marker / total_miles) * route duration.
* Intervals outside (10, 25, 50) fall back to 25 miles with a warning (F03).
"""

import logging
import time
from datetime import timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point

from .clients.openrouteservice import MAX_ROUTES, RoutingClient
from .models import (
    DEFAULT_CHECKPOINT_INTERVAL,
    Checkpoint,
    Route,
    RouteRequest,
)
from .utils import name_route, to_linestring

logger = logging.getLogger(__name__)

ALLOWED_INTERVALS = (10, 25, 50)
MIN_CHECKPOINTS_PER_ROUTE = 2


def resolve_interval(value) -> int:
    """Normalize a requested checkpoint interval (F03 fallback + warning)."""
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = None
    if interval not in ALLOWED_INTERVALS:
        logger.warning(
            "Unsupported checkpoint interval %r; defaulting to %d miles.",
            value,
            DEFAULT_CHECKPOINT_INTERVAL,
        )
        return DEFAULT_CHECKPOINT_INTERVAL
    return interval


def calculate_eta(departure, mile_marker, total_miles: float, duration_minutes: int):
    """Departure plus the travel time proportion for ``mile_marker``."""
    if total_miles <= 0:
        return departure
    fraction = float(mile_marker) / total_miles
    fraction = min(max(fraction, 0.0), 1.0)
    return departure + timedelta(minutes=fraction * duration_minutes)


def create_checkpoints(route: Route, interval_miles, departure) -> list[Checkpoint]:
    """Sample ``route``'s geometry at ``interval_miles`` (F03).

    Always includes the origin (sequence 0, mile 0) and the destination
    (last sequence, mile == route distance); short routes only get those two.
    """
    line = route.geometry
    total_miles = float(route.distance_miles)
    interval = resolve_interval(interval_miles)

    start = line.coords[0]
    end = line.coords[-1]
    checkpoints = [
        Checkpoint(
            route=route,
            sequence=0,
            mile_marker=Decimal("0.00"),
            latitude=start[1],
            longitude=start[0],
            location=Point(start[0], start[1], srid=4326),
            estimated_arrival=calculate_eta(departure, 0, total_miles, route.duration_minutes),
        )
    ]

    sequence = 1
    miles = float(interval)
    while miles < total_miles:
        point = line.interpolate_normalized(miles / total_miles)
        checkpoints.append(
            Checkpoint(
                route=route,
                sequence=sequence,
                mile_marker=Decimal(str(round(miles, 2))),
                latitude=point.y,
                longitude=point.x,
                location=Point(point.x, point.y, srid=4326),
                estimated_arrival=calculate_eta(
                    departure, miles, total_miles, route.duration_minutes
                ),
            )
        )
        sequence += 1
        miles += interval

    destination_marker = Decimal(str(round(total_miles, 2)))
    # Append the destination unless an interval point landed exactly on it.
    if (
        len(checkpoints) < MIN_CHECKPOINTS_PER_ROUTE
        or checkpoints[-1].mile_marker != destination_marker
    ):
        checkpoints.append(
            Checkpoint(
                route=route,
                sequence=sequence,
                mile_marker=destination_marker,
                latitude=end[1],
                longitude=end[0],
                location=Point(end[0], end[1], srid=4326),
                estimated_arrival=calculate_eta(
                    departure, total_miles, total_miles, route.duration_minutes
                ),
            )
        )

    return Checkpoint.objects.bulk_create(checkpoints)


def generate_routes(route_request: RouteRequest) -> list[Route]:
    """Fetch route alternatives and persist routes + checkpoints (F02).

    Also advances ``route_request.progress`` through the documented
    milestones (30 after routing, 60 after checkpoints). Safe to re-run:
    output from a previous attempt is replaced first.
    """
    started = time.monotonic()
    client = RoutingClient()
    routes_data = client.get_routes(route_request.origin_point, route_request.destination_point)

    # Idempotent under task retries: replace any partial output from before.
    route_request.routes.all().delete()

    routes = []
    for index, data in enumerate(routes_data[:MAX_ROUTES]):
        route = Route.objects.create(
            request=route_request,
            route_index=index,
            name=name_route(data, index, routes_data),
            distance_miles=Decimal(str(data.distance_miles)),
            duration_minutes=data.duration_minutes,
            geometry=to_linestring(data.geometry),
            summary=data.summary,
        )
        routes.append(route)

    route_request.progress = 30
    route_request.save(update_fields=["progress", "updated_at"])

    checkpoint_count = 0
    for route in routes:
        created = create_checkpoints(
            route,
            interval_miles=route_request.checkpoint_interval_miles,
            departure=route_request.departure_time,
        )
        checkpoint_count += len(created)

    route_request.progress = 60
    route_request.save(update_fields=["progress", "updated_at"])

    logger.info(
        "Route generation for request %s: %d routes, %d checkpoints in %.2fs",
        route_request.id,
        len(routes),
        checkpoint_count,
        time.monotonic() - started,
    )
    return routes
