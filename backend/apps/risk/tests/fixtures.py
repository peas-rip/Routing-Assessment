"""Shared builders for risk tests (docs/SERVICES/risk/TESTING.md)."""

from decimal import Decimal

from apps.risk.models import RouteScore
from apps.routing.models import Route
from apps.routing.tests.fixtures import make_route
from apps.weather.models import WeatherObservation
from apps.weather.tests.fixtures import make_checkpoint, make_observation


def create_mock_weather(wind=0, rain=0, snow=0, precip_type="none") -> WeatherObservation:
    """Unsaved observation following TESTING.md's fixture convention.

    ``precipitation_rate_in_hr`` is the total (rain + snow) rate and
    ``snowfall_rate_in_hr`` its snow component. The default ``precip_type``
    of ``none`` keeps rain/snow at zero regardless of the amounts.
    """
    return WeatherObservation(
        wind_speed_mph=Decimal(str(wind)),
        wind_direction_deg=180,
        precipitation_rate_in_hr=Decimal(str(rain + snow)),
        precipitation_type=precip_type,
        snowfall_rate_in_hr=Decimal(str(snow)),
        temperature_f=Decimal("50"),
        humidity_pct=50,
        visibility_mi=Decimal("10"),
        conditions="Test",
        raw_response={},
    )


def make_scored_route(
    route_request=None,
    *,
    low=50.0,
    moderate=50.0,
    high=0.0,
    severe=0.0,
    no_travel=0.0,
    avg=1.5,
    duration=200,
    **route_overrides,
) -> Route:
    """Route with a RouteScore built from the documented composite formula."""
    route = make_route(route_request, duration_minutes=duration, **route_overrides)
    composite = (
        Decimal(str(severe + no_travel)) * Decimal("10000")
        + Decimal(str(high)) * Decimal("100")
        + Decimal(str(avg)) * Decimal("10")
        + Decimal(str(duration)) / Decimal("1000")
    ).quantize(Decimal("0.001"))
    RouteScore.objects.create(
        route=route,
        severe_miles=Decimal(str(severe + no_travel)),
        high_miles=Decimal(str(high)),
        average_risk_score=Decimal(str(avg)),
        duration_minutes=duration,
        composite_score=composite,
        risk_breakdown={
            "low": low,
            "moderate": moderate,
            "high": high,
            "severe": severe,
            "no_travel": no_travel,
        },
    )
    return route


def make_weathered_route(
    route,
    *,
    weather_specs: list[dict],
    start_marker="0.00",
    marker_step="25.00",
) -> list:
    """Persist checkpoints + observations on ``route``; returns checkpoints.

    ``weather_specs`` holds observation overrides per checkpoint (in
    sequence order); mile markers step from ``start_marker`` by
    ``marker_step``.
    """
    checkpoints = []
    marker = Decimal(start_marker)
    step = Decimal(marker_step)
    for sequence, spec in enumerate(weather_specs):
        overrides = dict(spec)
        estimated_arrival = overrides.pop("estimated_arrival", None)
        checkpoint = make_checkpoint(
            route=route,
            sequence=sequence,
            mile_marker=marker,
            estimated_arrival=estimated_arrival,
        )
        make_observation(checkpoint, **overrides)
        checkpoints.append(checkpoint)
        marker += step
    return checkpoints
