"""Batch fetch, deduplication, caching and persistence (F04); heatmaps (F08)."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import responses
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError
from apps.weather.models import HeatmapCache, WeatherObservation
from apps.weather.services import (
    CACHE_TTL_SECONDS,
    MAX_HEATMAP_RESOLUTION_MILES,
    cache_key,
    capped_grid,
    corridor_grid,
    fetch_weather_batch,
    generate_heatmap,
    get_stored_observations,
    is_stale,
    save_observations,
)

from .fixtures import (
    MOCK_OWM_RESPONSE,
    OWM_ONECALL_URL,
    future_arrival,
    make_checkpoint,
    make_checkpoints,
    make_heatmap_route,
    make_observation,
    mock_onecall_response,
)


class CacheKeyTests(TestCase):
    def test_cache_key_rounds_coordinates_to_four_decimals(self):
        self.assertEqual(cache_key(39.78171, -89.65014, 8), "weather:39.7817:-89.6501:8")

    def test_cache_key_collapses_nearby_coordinates(self):
        # ~11m precision: coordinates that round alike share one bucket.
        self.assertEqual(cache_key(39.78171, -89.65014, 8), cache_key(39.78174, -89.65011, 8))


@override_settings(OPENWEATHERMAP_API_KEY="test-key")
class FetchWeatherBatchTests(TestCase):
    def setUp(self):
        # LocMem cache persists across tests: reset weather keys + throttle history.
        cache.clear()

    @responses.activate
    def test_deduplicates_by_rounded_coords_and_hour(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        checkpoints = make_checkpoints()

        results = fetch_weather_batch(checkpoints)

        self.assertEqual(len(results), 3)  # every checkpoint gets weather
        self.assertEqual(len(responses.calls), 2)  # only unique (lat, lon, hour) fetched

    @responses.activate
    def test_cache_hit_avoids_second_provider_call(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        checkpoints = make_checkpoints()
        fetch_weather_batch(checkpoints)
        self.assertEqual(len(responses.calls), 2)

        results = fetch_weather_batch(checkpoints)

        self.assertEqual(len(results), 3)
        self.assertEqual(len(responses.calls), 2)  # served from the 15-minute cache

    @responses.activate
    def test_partial_failure_continues_with_successful_buckets(self):
        def conditional(request):
            query = parse_qs(urlparse(request.url).query)
            if query["lat"][0].startswith("40."):
                return (500, {}, '{"error": "boom"}')
            return (200, {}, json.dumps(MOCK_OWM_RESPONSE))

        responses.add_callback(
            responses.GET,
            OWM_ONECALL_URL,
            callback=conditional,
            content_type="application/json",
        )
        checkpoints = make_checkpoints()  # third checkpoint lives at lat 40.0

        results = fetch_weather_batch(checkpoints)

        # The failed bucket is skipped; the shared bucket still stores.
        self.assertEqual(len(results), 2)
        self.assertNotIn(checkpoints[2].id, results)

    @responses.activate
    def test_all_buckets_failed_raises_provider_error(self):
        responses.add_callback(
            responses.GET,
            OWM_ONECALL_URL,
            callback=lambda request: (500, {}, '{"error": "boom"}'),
            content_type="application/json",
        )
        checkpoints = make_checkpoints()

        with self.assertRaises(WeatherProviderError):
            fetch_weather_batch(checkpoints)

    @responses.activate
    def test_rate_limited_batch_raises_rate_limit_error(self):
        responses.add_callback(
            responses.GET,
            OWM_ONECALL_URL,
            callback=lambda request: (429, {"Retry-After": "30"}, "{}"),
            content_type="application/json",
        )
        checkpoints = make_checkpoints()

        with self.assertRaises(WeatherRateLimitError) as ctx:
            fetch_weather_batch(checkpoints)

        self.assertEqual(ctx.exception.retry_after, 30)

    @responses.activate
    def test_missing_forecast_hour_is_skipped_without_error(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        # Fixture only has hours 8 and 9: an hour-14 arrival has no target.
        checkpoint = make_checkpoint(estimated_arrival=future_arrival(14))

        results = fetch_weather_batch([checkpoint])

        self.assertEqual(results, {})
        self.assertEqual(len(responses.calls), 1)


@override_settings(OPENWEATHERMAP_API_KEY="test-key")
class SaveObservationsTests(TestCase):
    def setUp(self):
        cache.clear()

    @responses.activate
    def test_save_uses_checkpoint_estimated_arrival_as_forecast_time(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        checkpoints = make_checkpoints()

        results = fetch_weather_batch(checkpoints)
        saved = save_observations(results)

        self.assertEqual(saved, 3)
        self.assertEqual(WeatherObservation.objects.count(), 3)
        for checkpoint in checkpoints:
            observation = WeatherObservation.objects.get(checkpoint_id=checkpoint.id)
            self.assertEqual(observation.forecast_time, checkpoint.estimated_arrival)
        # Rain bucket (hour 8) vs snow bucket (hour 9).
        self.assertEqual(
            WeatherObservation.objects.get(checkpoint=checkpoints[0]).precipitation_type, "rain"
        )
        self.assertEqual(
            WeatherObservation.objects.get(checkpoint=checkpoints[2]).precipitation_type, "snow"
        )

    @responses.activate
    def test_save_refreshes_existing_rows_instead_of_duplicating(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        checkpoints = make_checkpoints()
        results = fetch_weather_batch(checkpoints)
        save_observations(results)

        stale_since = timezone.now() - timedelta(hours=1)
        WeatherObservation.objects.filter(checkpoint=checkpoints[0]).update(
            fetched_at=stale_since, temperature_f=Decimal("1.00")
        )

        save_observations(results)

        self.assertEqual(WeatherObservation.objects.count(), 3)
        observation = WeatherObservation.objects.get(checkpoint=checkpoints[0])
        self.assertGreater(observation.fetched_at, stale_since)
        self.assertEqual(observation.temperature_f, Decimal("45.20"))

    def test_save_without_results_is_a_noop(self):
        self.assertEqual(save_observations({}), 0)
        self.assertEqual(WeatherObservation.objects.count(), 0)


class StoredObservationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_stored_lookup_matches_estimated_arrival_only(self):
        checkpoint = make_checkpoint()
        make_observation(checkpoint)
        make_observation(
            checkpoint, forecast_time=checkpoint.estimated_arrival + timedelta(hours=2)
        )

        stored = get_stored_observations([checkpoint])

        self.assertEqual(list(stored), [checkpoint.id])
        self.assertEqual(stored[checkpoint.id].forecast_time, checkpoint.estimated_arrival)

    def test_stored_lookup_with_explicit_forecast_time(self):
        checkpoint = make_checkpoint()
        other_time = checkpoint.estimated_arrival + timedelta(hours=2)
        make_observation(checkpoint)

        stored = get_stored_observations([checkpoint], forecast_time=other_time)
        self.assertEqual(stored, {})

        make_observation(checkpoint, forecast_time=other_time)
        stored = get_stored_observations([checkpoint], forecast_time=other_time)
        self.assertEqual(stored[checkpoint.id].forecast_time, other_time)

    def test_stored_lookup_for_no_checkpoints_is_empty(self):
        self.assertEqual(get_stored_observations([]), {})


class StalenessTests(TestCase):
    def test_fresh_observation_is_not_stale(self):
        checkpoint = make_checkpoint()
        observation = make_observation(checkpoint)

        self.assertFalse(is_stale(observation))

    def test_observation_older_than_ttl_is_stale(self):
        checkpoint = make_checkpoint()
        observation = make_observation(
            checkpoint, fetched_at=timezone.now() - timedelta(seconds=CACHE_TTL_SECONDS + 1)
        )

        self.assertTrue(is_stale(observation))


class CorridorGridTests(TestCase):
    def setUp(self):
        self.route = make_heatmap_route()

    def test_points_lay_inside_expanded_bounds(self):
        points, bounds = corridor_grid(self.route, 10.0)

        self.assertEqual(list(bounds), ["north", "south", "east", "west"])
        self.assertGreater(len(points), 0)
        self.assertEqual(len(points), len(set(points)))
        for latitude, longitude in points:
            self.assertGreaterEqual(latitude, bounds["south"])
            self.assertLessEqual(latitude, bounds["north"])
            self.assertGreaterEqual(longitude, bounds["west"])
            self.assertLessEqual(longitude, bounds["east"])

    def test_wider_resolution_yields_fewer_points(self):
        fine, _ = corridor_grid(self.route, 5.0)
        coarse, _ = corridor_grid(self.route, 20.0)

        self.assertGreater(len(fine), len(coarse))


class CappedGridTests(TestCase):
    def setUp(self):
        self.route = make_heatmap_route()

    def test_under_cap_returns_points_unchanged(self):
        points_in = [(1.0, 2.0), (1.1, 2.1)]

        with patch("apps.weather.services.corridor_grid", return_value=(points_in, {"north": 1})):
            points, bounds, resolution = capped_grid(self.route, 10.0)

        self.assertEqual(points, points_in)
        self.assertEqual(bounds, {"north": 1})
        self.assertEqual(resolution, 10.0)

    def test_over_cap_reduces_resolution(self):
        huge = [(0.0, index * 0.001) for index in range(20000)]
        small = [(0.0, 0.0), (0.1, 0.1)]

        with patch("apps.weather.services.corridor_grid", side_effect=[(huge, {}), (small, {})]):
            points, _, resolution = capped_grid(self.route, 10.0)

        self.assertEqual(points, small)
        self.assertEqual(resolution, 20.0)  # 10 * sqrt(20000 / 5000)

    def test_at_max_resolution_subsamples_to_cap(self):
        huge = [(0.0, index * 0.001) for index in range(6000)]

        with patch("apps.weather.services.corridor_grid", return_value=(huge, {})):
            points, _, resolution = capped_grid(self.route, MAX_HEATMAP_RESOLUTION_MILES)

        self.assertEqual(resolution, MAX_HEATMAP_RESOLUTION_MILES)
        self.assertEqual(len(points), 3000)  # step = ceil(6000 / 5000) = 2


@override_settings(OPENWEATHERMAP_API_KEY="test-key")
class GenerateHeatmapTests(TestCase):
    def setUp(self):
        cache.clear()
        self.route = make_heatmap_route()

    @responses.activate
    def test_contract_shape_and_risk_rules(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=mock_onecall_response())

        result = generate_heatmap(self.route, forecast_hour=6, resolution_miles=10.0)

        self.assertEqual(
            list(result),
            ["route_id", "forecast_hour", "bounds", "resolution_miles", "grid", "generated_at"],
        )
        self.assertEqual(result["route_id"], self.route.id)
        self.assertEqual(result["forecast_hour"], 6)
        self.assertEqual(list(result["bounds"]), ["north", "south", "east", "west"])
        self.assertEqual(result["resolution_miles"], 10.0)
        self.assertGreater(len(result["grid"]), 0)
        for point in result["grid"]:
            self.assertEqual(list(point), ["lat", "lon", "risk_level", "risk_score"])
            # Fixture weather (12.5 mph wind, 0.08 in/hr rain) is Low risk.
            self.assertEqual(point["risk_level"], "low")
            self.assertEqual(point["risk_score"], 1.0)

    @responses.activate
    def test_grid_is_cached_within_ttl(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=mock_onecall_response())
        first = generate_heatmap(self.route, forecast_hour=6, resolution_miles=10.0)
        calls_after_first = len(responses.calls)

        second = generate_heatmap(self.route, forecast_hour=6, resolution_miles=10.0)

        self.assertEqual(second["generated_at"], first["generated_at"])
        self.assertEqual(len(responses.calls), calls_after_first)
        self.assertEqual(HeatmapCache.objects.count(), 1)

    @responses.activate
    def test_expired_grid_is_regenerated_in_place(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=mock_onecall_response())
        first = generate_heatmap(self.route, forecast_hour=6, resolution_miles=10.0)
        HeatmapCache.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

        second = generate_heatmap(self.route, forecast_hour=6, resolution_miles=10.0)

        self.assertEqual(HeatmapCache.objects.count(), 1)
        self.assertGreater(second["generated_at"], first["generated_at"])

    @responses.activate
    def test_forecast_hours_are_cached_separately(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=mock_onecall_response())

        generate_heatmap(self.route, forecast_hour=6, resolution_miles=10.0)
        generate_heatmap(self.route, forecast_hour=7, resolution_miles=10.0)

        self.assertEqual(HeatmapCache.objects.count(), 2)

    @responses.activate
    def test_resolution_is_clamped_to_supported_band(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=mock_onecall_response())

        low = generate_heatmap(self.route, forecast_hour=6, resolution_miles=1.0)
        high = generate_heatmap(self.route, forecast_hour=6, resolution_miles=100.0)

        self.assertEqual(low["resolution_miles"], 5.0)
        self.assertEqual(high["resolution_miles"], 50.0)

    @responses.activate
    def test_hour_without_forecast_yields_empty_grid(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        departure = self.route.request.departure_time
        hour = next(
            candidate
            for candidate in range(49)
            if (departure + timedelta(hours=candidate)).hour not in (8, 9)
        )

        result = generate_heatmap(self.route, forecast_hour=hour, resolution_miles=50.0)

        self.assertEqual(result["grid"], [])
        stored = HeatmapCache.objects.get(route=self.route, forecast_hour=hour)
        self.assertEqual(stored.grid_data, [])

    @responses.activate
    def test_provider_failure_yields_empty_grid(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json={"error": "boom"}, status=500)

        result = generate_heatmap(self.route, forecast_hour=6, resolution_miles=50.0)

        # Failed point fetches are skipped, leaving the frontend's
        # "data unavailable" overlay to cover the corridor.
        self.assertEqual(result["grid"], [])
