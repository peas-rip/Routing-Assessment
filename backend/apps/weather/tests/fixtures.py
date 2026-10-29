"""Mock NWS payloads and shared builders for weather tests."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.contrib.gis.geos import LineString, Point
from django.utils import timezone

from apps.routing.models import Checkpoint
from apps.routing.tests.fixtures import make_route
from apps.weather.models import WeatherObservation

# The NWS client resolves a grid office via /points/ then fetches the hourly
# forecast from the returned forecastHourly URL; a regex matches any coords.
NWS_POINTS_URL = re.compile(r"https://api\.weather\.gov/points/.*")
NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/LOT/73,71/forecast/hourly"

BASE_TIME = datetime(2023, 12, 27, 8, 0, tzinfo=UTC)


def nws_points_payload() -> dict:
    return {"properties": {"forecastHourly": NWS_FORECAST_URL}}


def nws_forecast_payload(
    hours: int = 48,
    temp: float = 45.2,
    wind: float = 12.5,
    wind_dir: int = 230,
    pop: int = 8,
    short: str = "Light Rain",
) -> dict:
    periods = []
    for i in range(hours):
        periods.append(
            {
                "startTime": (BASE_TIME + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "temperature": temp,
                "windSpeed": {"value": wind, "unitCode": "wmoUnit:miles_per_hour"},
                "windDirection": {"value": wind_dir},
                "probabilityOfPrecipitation": {"value": pop},
                "shortForecast": short,
            }
        )
    return {"properties": {"periods": periods}}


def register_nws(
    hours: int = 48,
    temp: float = 45.2,
    wind: float = 12.5,
    wind_dir: int = 230,
    pop: int = 8,
    short: str = "Light Rain",
) -> None:
    """Register mock NWS points + hourly-forecast responses."""
    import responses

    responses.add(responses.GET, NWS_POINTS_URL, json=nws_points_payload())
    responses.add(
        responses.GET,
        NWS_FORECAST_URL,
        json=nws_forecast_payload(hours, temp, wind, wind_dir, pop, short),
    )


def register_nws_error(status: int = 500, retry_after: int | None = None) -> None:
    """Register an NWS error response on the /points/ step."""
    import responses

    headers = {"Retry-After": str(retry_after)} if retry_after else {}
    responses.add(responses.GET, NWS_POINTS_URL, json={}, status=status, headers=headers)


MOCK_NWS_RESPONSE = nws_forecast_payload()
MOCK_NWS_SNOW = nws_forecast_payload(pop=90, short="Heavy Snow")
MOCK_NWS_CLEAR = nws_forecast_payload(pop=0, short="Clear")


def future_arrival(hour: int = 8, minute: int = 25):
    """Dynamic future ETA whose UTC hour matches a fixture forecast entry."""
    arrival = timezone.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    if arrival <= timezone.now():
        arrival += timedelta(days=1)
    return arrival


def make_checkpoint(
    route=None,
    latitude: float = 39.7817,
    longitude: float = -89.6501,
    estimated_arrival=None,
    **overrides,
) -> Checkpoint:
    """Persist a checkpoint directly (bypasses route generation)."""
    if route is None:
        route = make_route()
    defaults = {
        "sequence": 0,
        "mile_marker": Decimal("0.00"),
        "latitude": latitude,
        "longitude": longitude,
        "location": Point(longitude, latitude, srid=4326),
        "estimated_arrival": estimated_arrival or future_arrival(8),
    }
    defaults.update(overrides)
    return Checkpoint.objects.create(route=route, **defaults)


def make_checkpoints() -> list[Checkpoint]:
    """Three checkpoints: two share rounded coords + hour, one differs (F04)."""
    return [
        make_checkpoint(latitude=39.7817, longitude=-89.6501, estimated_arrival=future_arrival(8)),
        make_checkpoint(
            latitude=39.7817,
            longitude=-89.6501,
            estimated_arrival=future_arrival(8),
            sequence=1,
        ),
        make_checkpoint(
            latitude=40.0000,
            longitude=-89.0000,
            estimated_arrival=future_arrival(9),
            sequence=2,
        ),
    ]


def make_observation(checkpoint: Checkpoint, fetched_at=None, **overrides) -> WeatherObservation:
    """Persist a stored observation (defaults mirror the rain fixture entry)."""
    defaults = {
        "forecast_time": checkpoint.estimated_arrival,
        "wind_speed_mph": Decimal("12.50"),
        "wind_direction_deg": 230,
        "wind_gust_mph": Decimal("18.00"),
        "precipitation_rate_in_hr": Decimal("0.080"),
        "precipitation_type": "rain",
        "snowfall_rate_in_hr": Decimal("0.000"),
        "snow_depth_in": None,
        "temperature_f": Decimal("45.20"),
        "humidity_pct": 65,
        "visibility_mi": None,
        "conditions": "Light Rain",
        "raw_response": MOCK_NWS_RESPONSE,
        "source": "nws",
    }
    defaults.update(overrides)
    observation = WeatherObservation.objects.create(checkpoint=checkpoint, **defaults)
    if fetched_at is not None:
        WeatherObservation.objects.filter(id=observation.id).update(fetched_at=fetched_at)
        observation.refresh_from_db()
    return observation


def checkpoint_ids_param(items) -> str:
    """Comma-separated ``checkpoint_ids`` query value (ids or checkpoints)."""
    return ",".join(str(getattr(item, "id", item)) for item in items)


def make_heatmap_route(**overrides):
    """Short route with a compact geometry for heatmap tests (F08)."""
    return make_route(
        distance_miles=Decimal("50.00"),
        geometry=LineString([(-89.65, 39.78), (-89.15, 40.28)], srid=4326),
        **overrides,
    )
