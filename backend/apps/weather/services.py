"""Weather fetching, caching and persistence (F04), heatmap grids (F08).

* Deduplicates provider calls by rounded (lat, lon, forecast hour) buckets.
* Caches parsed forecasts in Redis for 15 minutes before hitting the API.
* Persists one WeatherObservation per checkpoint at its forecast time.
* Generates risk heatmaps along the route corridor, cached 10 minutes.
"""

import logging
import math
import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from apps.risk.rules import RISK_SCORE_MAP
from apps.risk.services import assess_conditions

from .clients.openmeteo import HourlyForecast, WeatherClient
from .exceptions import WeatherError
from .models import HeatmapCache, WeatherObservation

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 15 * 60  # F04: 15 minutes for checkpoint weather
COORD_PRECISION = 4  # ~11m precision for cache/dedup keys (F04 edge case 7)


def cache_key(latitude: float, longitude: float, hour: int) -> str:
    """Redis key for one (lat, lon, hour) forecast bucket."""
    lat = round(latitude, COORD_PRECISION)
    lon = round(longitude, COORD_PRECISION)
    return f"weather:{lat}:{lon}:{hour}"


def group_checkpoints(checkpoints, target_times=None):
    """Group checkpoints by rounded (lat lon, forecast hour) for dedup.

    ``target_times`` optionally overrides each checkpoint's ETA (used when
    the API is queried with an explicit ``forecast_time``).
    """
    groups = defaultdict(list)
    for checkpoint in checkpoints:
        target = (target_times or {}).get(checkpoint.id) or checkpoint.estimated_arrival
        key = (
            round(checkpoint.latitude, COORD_PRECISION),
            round(checkpoint.longitude, COORD_PRECISION),
            target.hour,
        )
        groups[key].append((checkpoint, target))
    return groups


def forecast_fields(forecast: HourlyForecast, raw_response: dict) -> dict:
    """Observation field values for one parsed forecast (no per-cp fields)."""
    return {
        "wind_speed_mph": forecast.wind_speed_mph,
        "wind_direction_deg": forecast.wind_deg,
        "wind_gust_mph": forecast.wind_gust_mph,
        "precipitation_rate_in_hr": forecast.precipitation_rate_in_hr,
        "precipitation_type": forecast.precipitation_type,
        "snowfall_rate_in_hr": forecast.snowfall_rate_in_hr,
        "snow_depth_in": None,
        "temperature_f": forecast.temp_f,
        "humidity_pct": forecast.humidity,
        "visibility_mi": forecast.visibility_mi,
        "conditions": forecast.conditions,
        "raw_response": raw_response,
        "source": "open-meteo",
    }


def fetch_weather_batch(checkpoints, *, client=None, target_times=None) -> dict[uuid.UUID, dict]:
    """Fetch weather for checkpoints, deduplicated by (lat, lon, hour).

    One provider call serves every checkpoint in a bucket, with a 15-minute
    Redis cache in front. Bucket failures are logged and skipped unless
    *every* bucket failed, in which case the first provider error
    propagates so the Celery task can retry (F04 error handling).
    """
    client = client or WeatherClient()
    groups = group_checkpoints(checkpoints, target_times)
    observations: dict[uuid.UUID, dict] = {}
    errors: list[WeatherError] = []
    cache_hits = 0

    for (latitude, longitude, hour), members in groups.items():
        key = cache_key(latitude, longitude, hour)
        fields = cache.get(key)

        if fields is None:
            try:
                forecasts, payload = client.fetch(latitude, longitude)
            except WeatherError as exc:
                errors.append(exc)
                logger.warning("Weather fetch failed for %s: %s", key, exc)
                continue
            target = next((f for f in forecasts if f.dt.hour == hour), None)
            if target is None:
                logger.info("No %02d:00 forecast available for %s", hour, key)
                continue
            fields = forecast_fields(target, raw_response=payload)
            cache.set(key, fields, CACHE_TTL_SECONDS)
        else:
            cache_hits += 1

        for checkpoint, target in members:
            observations[checkpoint.id] = {**fields, "forecast_time": target}

    logger.info(
        "Weather batch: %d checkpoints, %d buckets, %d cache hits, %d stored",
        len(checkpoints),
        len(groups),
        cache_hits,
        len(observations),
    )

    if errors and len(errors) == len(groups):
        raise errors[0]
    return observations


def save_observations(results: dict[uuid.UUID, dict]) -> int:
    """Persist observations, refreshing rows that already exist (upsert).

    ``update_conflicts`` rewrites existing (checkpoint, forecast_time,
    source) rows so stale-while-revalidate refreshes actually update
    ``fetched_at`` and the weather values (F04 acceptance criterion 10).
    """
    if not results:
        return 0
    observations = [
        WeatherObservation(checkpoint_id=checkpoint_id, **fields)
        for checkpoint_id, fields in results.items()
    ]
    WeatherObservation.objects.bulk_create(
        observations,
        update_conflicts=True,
        unique_fields=["checkpoint", "forecast_time", "source"],
        update_fields=[
            "wind_speed_mph",
            "wind_direction_deg",
            "wind_gust_mph",
            "precipitation_rate_in_hr",
            "precipitation_type",
            "snowfall_rate_in_hr",
            "snow_depth_in",
            "temperature_f",
            "humidity_pct",
            "visibility_mi",
            "conditions",
            "raw_response",
            "fetched_at",
        ],
    )
    return len(observations)


def get_stored_observations(checkpoints, forecast_time=None) -> dict[uuid.UUID, WeatherObservation]:
    """Stored observations for ``checkpoints`` at the requested forecast time.

    Without an explicit ``forecast_time`` each checkpoint is matched at its
    own estimated arrival time (the only time we store observations at).
    """
    if not checkpoints:
        return {}
    if forecast_time is not None:
        rows = WeatherObservation.objects.for_checkpoints(
            [checkpoint.id for checkpoint in checkpoints]
        ).at_forecast_time(forecast_time)
    else:
        condition = Q()
        for checkpoint in checkpoints:
            condition |= Q(checkpoint_id=checkpoint.id, forecast_time=checkpoint.estimated_arrival)
        rows = WeatherObservation.objects.filter(condition)
    return {row.checkpoint_id: row for row in rows}


def is_stale(observation: WeatherObservation, now=None) -> bool:
    """True when the observation is older than the 15-minute cache TTL."""
    now = now or timezone.now()
    return observation.fetched_at < now - timedelta(seconds=CACHE_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Weather heatmap (F08)
# ---------------------------------------------------------------------------
# docs/FEATURES/FEATURE_08_WEATHER_HEATMAP.md: 10-minute grid cache, 0-48
# forecast hours, 5-50 mile resolution, max 5000 grid points.
HEATMAP_CACHE_TTL_SECONDS = 10 * 60
MAX_HEATMAP_POINTS = 5000
DEFAULT_HEATMAP_RESOLUTION_MILES = 10.0
MIN_HEATMAP_RESOLUTION_MILES = 5.0
MAX_HEATMAP_RESOLUTION_MILES = 50.0
MILES_PER_DEGREE_LATITUDE = 69.0  # ~69 miles per degree of latitude (F08)
CORRIDOR_BUFFER_MIN_MILES = 20.0


def corridor_grid(route, resolution_miles: float):
    """Grid points inside the route corridor + their geographic bounds (F08).

    The corridor is the route geometry buffered by max(20, 2 * resolution)
    miles, approximated in degrees; points are laid over the route's
    bounding box at ``resolution_miles`` spacing on both axes.
    """
    geometry = route.geometry
    min_lon, min_lat, max_lon, max_lat = geometry.extent
    buffer_miles = max(CORRIDOR_BUFFER_MIN_MILES, resolution_miles * 2)
    buffer_degrees = buffer_miles / MILES_PER_DEGREE_LATITUDE
    corridor = geometry.buffer(buffer_degrees)

    mid_latitude = (min_lat + max_lat) / 2
    lon_scale = max(math.cos(math.radians(mid_latitude)), 0.01)
    lat_step = resolution_miles / MILES_PER_DEGREE_LATITUDE
    lon_step = resolution_miles / (MILES_PER_DEGREE_LATITUDE * lon_scale)

    points = []
    latitude = min_lat
    while latitude <= max_lat:
        longitude = min_lon
        while longitude <= max_lon:
            if corridor.contains(Point(longitude, latitude, srid=4326)):
                points.append((round(latitude, 4), round(longitude, 4)))
            longitude += lon_step
        latitude += lat_step

    bounds = {
        "north": round(max_lat + buffer_degrees, 4),
        "south": round(min_lat - buffer_degrees, 4),
        "east": round(max_lon + buffer_degrees, 4),
        "west": round(min_lon - buffer_degrees, 4),
    }
    return points, bounds


def capped_grid(route, resolution_miles: float):
    """Corridor grid honoring the 5000-point cap (F08 edge case 1).

    Too many points auto-reduce the resolution by sqrt(overcount); at the
    maximum resolution the points are subsampled evenly instead.
    """
    points, bounds = corridor_grid(route, resolution_miles)
    if len(points) <= MAX_HEATMAP_POINTS:
        return points, bounds, resolution_miles

    reduced = resolution_miles * math.sqrt(len(points) / MAX_HEATMAP_POINTS)
    resolution = min(MAX_HEATMAP_RESOLUTION_MILES, max(resolution_miles, reduced))
    if resolution > resolution_miles:
        logger.warning(
            "Heatmap grid too large (%d points); reducing resolution to %.1f mi",
            len(points),
            resolution,
        )
        return capped_grid(route, resolution)

    logger.warning(
        "Heatmap grid still too large at %.1f mi; subsampling to %d points",
        resolution,
        MAX_HEATMAP_POINTS,
    )
    step = math.ceil(len(points) / MAX_HEATMAP_POINTS)
    return points[::step], bounds, resolution


def fetch_heatmap_forecasts(points, target_time) -> dict[tuple[float, float], dict]:
    """Cached forecasts for grid points at the target hour (F08).

    Reuses the 15-minute (lat, lon, hour) cache in front of the provider;
    points without a forecast for the hour (or whose fetch failed) are
    omitted so the frontend can show its "data unavailable" overlay.
    """
    client = WeatherClient()
    forecasts: dict[tuple[float, float], dict] = {}
    for latitude, longitude in points:
        key = cache_key(latitude, longitude, target_time.hour)
        fields = cache.get(key)
        if fields is None:
            try:
                hourly, payload = client.fetch(latitude, longitude)
            except WeatherError as exc:
                logger.warning("Heatmap weather fetch failed for %s: %s", key, exc)
                continue
            target = next((item for item in hourly if item.dt.hour == target_time.hour), None)
            if target is None:
                logger.info("No %02d:00 forecast available for %s", target_time.hour, key)
                continue
            fields = forecast_fields(target, raw_response=payload)
            cache.set(key, fields, CACHE_TTL_SECONDS)
        forecasts[(latitude, longitude)] = fields
    return forecasts


def _forecast_observation(fields: dict) -> WeatherObservation:
    """Unsaved observation view of cached forecast fields for the risk rules."""
    return WeatherObservation(
        wind_speed_mph=fields["wind_speed_mph"],
        precipitation_rate_in_hr=fields["precipitation_rate_in_hr"],
        precipitation_type=fields["precipitation_type"],
        snowfall_rate_in_hr=fields["snowfall_rate_in_hr"],
    )


def _heatmap_payload(record: HeatmapCache) -> dict:
    """API payload for one cached heatmap grid record."""
    return {
        "route_id": record.route_id,
        "forecast_hour": record.forecast_hour,
        "bounds": record.bounds,
        "resolution_miles": float(record.resolution_miles),
        "grid": record.grid_data,
        "generated_at": record.created_at,
    }


def generate_heatmap(route, forecast_hour: int, resolution_miles: float) -> dict:
    """Serve or generate the heatmap grid for a route + forecast hour (F08).

    Grids live in HeatmapCache for HEATMAP_CACHE_TTL_SECONDS. Every grid
    point carries the risk classification of the target hour's forecast for
    the request's load weight - the risk rules are reused from the risk
    service. Resolution is clamped to 5-50 miles.
    """
    resolution = min(
        MAX_HEATMAP_RESOLUTION_MILES,
        max(MIN_HEATMAP_RESOLUTION_MILES, float(resolution_miles)),
    )
    resolution_key = Decimal(str(resolution)).quantize(Decimal("0.01"))
    cached = HeatmapCache.objects.filter(
        route=route,
        forecast_hour=forecast_hour,
        resolution_miles=resolution_key,
        expires_at__gt=timezone.now(),
    ).first()
    if cached is not None:
        return _heatmap_payload(cached)

    points, bounds, effective_resolution = capped_grid(route, resolution)
    target_time = route.request.departure_time + timedelta(hours=forecast_hour)
    forecasts = fetch_heatmap_forecasts(points, target_time)
    load_weight_lbs = route.request.load_weight_lbs

    grid = []
    for latitude, longitude in points:
        fields = forecasts.get((latitude, longitude))
        if fields is None:
            continue
        risks = assess_conditions(_forecast_observation(fields), load_weight_lbs)
        combined = risks["combined_risk"]
        grid.append(
            {
                "lat": latitude,
                "lon": longitude,
                "risk_level": combined.value_label,
                "risk_score": float(RISK_SCORE_MAP[combined]),
            }
        )
    if not grid:
        logger.info("No heatmap weather data for route %s at hour %s", route.id, forecast_hour)

    now = timezone.now()
    record, created = HeatmapCache.objects.update_or_create(
        route=route,
        forecast_hour=forecast_hour,
        resolution_miles=Decimal(str(effective_resolution)).quantize(Decimal("0.01")),
        defaults={
            "grid_data": grid,
            "bounds": bounds,
            "expires_at": now + timedelta(seconds=HEATMAP_CACHE_TTL_SECONDS),
        },
    )
    if not created:
        # Auto-now-add only stamps inserts; keep created_at meaning
        # "when this grid was generated".
        HeatmapCache.objects.filter(id=record.id).update(created_at=now)
        record.created_at = now
    return _heatmap_payload(record)
