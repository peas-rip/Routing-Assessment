"""Mock OpenWeatherMap payloads and shared builders for weather tests."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.gis.geos import LineString, Point
from django.utils import timezone

from apps.routing.models import Checkpoint
from apps.routing.tests.fixtures import make_route
from apps.weather.models import WeatherObservation

OWM_ONECALL_URL = "https://api.openweathermap.org/data/3.0/onecall"

# docs/SERVICES/weather/TESTING.md fixture: hour-8 rain entry + hour-9 snow
# entry (dt values are fixed UTC timestamps; tests match on hour-of-day only).
MOCK_OWM_RESPONSE = {
    "lat": 39.78,
    "lon": -89.65,
    "timezone": "America/Chicago",
    "hourly": [
        {
            "dt": 1703664000,
            "temp": 45.2,
            "humidity": 65,
            "wind_speed": 12.5,
            "wind_deg": 230,
            "wind_gust": 18.0,
            "weather": [{"id": 500, "main": "Rain", "description": "light rain"}],
            "pop": 0.3,
            "rain": {"1h": 0.08},
        },
        {
            "dt": 1703667600,
            "temp": 32.1,
            "humidity": 85,
            "wind_speed": 38.0,
            "wind_deg": 310,
            "wind_gust": 45.0,
            "weather": [{"id": 600, "main": "Snow", "description": "heavy snow"}],
            "pop": 0.9,
            "snow": {"1h": 1.5},
        },
    ],
}

MOCK_OWM_MIXED = {
    "hourly": [
        {
            "dt": 1703664000,
            "temp": 34.0,
            "humidity": 80,
            "wind_speed": 10.0,
            "wind_deg": 180,
            "weather": [{"main": "Rain"}],
            "rain": {"1h": 0.2},
            "snow": {"1h": 0.5},
        }
    ]
}

MOCK_OWM_CLEAR = {
    "hourly": [
        {
            "dt": 1703664000,
            "temp": 70,
            "humidity": 40,
            "wind_speed": 5,
            "wind_deg": 90,
            "weather": [{"main": "Clear"}],
        }
    ]
}


def mock_onecall_response(hours: int = 48) -> dict:
    """OWM payload covering every hour-of-day (dynamic: no hardcoded dates)."""
    base_hour = int(timezone.now().timestamp()) // 3600 * 3600
    hourly = [
        {
            "dt": base_hour + offset * 3600,
            "temp": 45.2,
            "humidity": 65,
            "wind_speed": 12.5,
            "wind_deg": 230,
            "wind_gust": 18.0,
            "weather": [{"id": 500, "main": "Rain", "description": "light rain"}],
            "pop": 0.3,
            "rain": {"1h": 0.08},
        }
        for offset in range(hours)
    ]
    return {"lat": 39.78, "lon": -89.65, "timezone": "UTC", "hourly": hourly}


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
        ),  # duplicate (lat, lon, hour) bucket
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
        "conditions": "light rain",
        "raw_response": MOCK_OWM_RESPONSE,
        "source": "openweathermap",
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
