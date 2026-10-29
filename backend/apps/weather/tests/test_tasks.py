"""fetch_weather_for_checkpoints task: persistence and retry policy (F04).

Also covers generate_heatmap_task (F08).
"""

import json
import uuid
from unittest.mock import patch

import responses
from celery.exceptions import Retry
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError
from apps.weather.models import HeatmapCache, WeatherObservation
from apps.weather.tasks import fetch_weather_for_checkpoints, generate_heatmap_task

from .fixtures import (
    MOCK_NWS_RESPONSE,
    NWS_FORECAST_URL,
    NWS_POINTS_URL,
    make_checkpoint,
    make_checkpoints,
    make_heatmap_route,
    nws_points_payload,
    register_nws,
)


@override_settings(OPENWEATHERMAP_API_KEY="test-key")
class FetchWeatherForCheckpointsTests(TestCase):
    def setUp(self):
        cache.clear()

    @responses.activate
    def test_creates_observations_for_all_checkpoints(self):
        register_nws()
        checkpoints = make_checkpoints()
        checkpoint_ids = [str(cp.id) for cp in checkpoints]

        result = fetch_weather_for_checkpoints(checkpoint_ids)

        self.assertEqual(result["saved"], 3)
        self.assertEqual(WeatherObservation.objects.count(), 3)
        for checkpoint in checkpoints:
            observation = WeatherObservation.objects.get(checkpoint_id=checkpoint.id)
            self.assertEqual(observation.forecast_time, checkpoint.estimated_arrival)
        self.assertEqual(
            WeatherObservation.objects.get(checkpoint=checkpoints[0]).precipitation_type,
            "rain",
        )
        self.assertEqual(
            WeatherObservation.objects.get(checkpoint=checkpoints[2]).precipitation_type,
            "rain",
        )

    @responses.activate
    def test_unknown_checkpoint_ids_are_a_noop(self):
        checkpoint_ids = ["00000000-0000-0000-0000-000000000000"]

        result = fetch_weather_for_checkpoints(checkpoint_ids)

        self.assertEqual(result, {"checkpoints": 0, "observations": 0, "saved": 0})
        self.assertEqual(WeatherObservation.objects.count(), 0)
        self.assertEqual(len(responses.calls), 0)

    @responses.activate
    def test_provider_error_propagates_when_called_directly(self):
        responses.add(responses.GET, NWS_POINTS_URL, json={}, status=500)
        checkpoint = make_checkpoint()
        checkpoint_ids = [str(checkpoint.id)]

        # Called directly (not through a worker): Celery re-raises the
        # original error instead of scheduling a retry.
        with self.assertRaises(WeatherProviderError) as ctx:
            fetch_weather_for_checkpoints(checkpoint_ids)

        self.assertEqual(ctx.exception.details["status_code"], 500)
        self.assertEqual(WeatherObservation.objects.count(), 0)

    @responses.activate
    def test_provider_error_retries_until_exhausted(self):
        responses.add(responses.GET, NWS_POINTS_URL, json={}, status=500)
        checkpoint = make_checkpoint()
        checkpoint_ids = [str(checkpoint.id)]

        # retries == max_retries: the task raises the original error instead
        # of scheduling yet another attempt (eager runs never loop/sleep).
        with self.assertRaises(WeatherProviderError):
            fetch_weather_for_checkpoints.apply(args=(checkpoint_ids,), retries=3)

        self.assertEqual(len(responses.calls), 1)
        self.assertEqual(WeatherObservation.objects.count(), 0)

    @responses.activate
    def test_rate_limit_retries_until_exhausted(self):
        responses.add(responses.GET, NWS_POINTS_URL, json={}, status=429)
        checkpoint = make_checkpoint()
        checkpoint_ids = [str(checkpoint.id)]

        with self.assertRaises(WeatherRateLimitError):
            fetch_weather_for_checkpoints.apply(args=(checkpoint_ids,), retries=3)

        self.assertEqual(len(responses.calls), 1)

    @responses.activate
    def test_provider_error_schedules_retry_when_attempts_remain(self):
        responses.add(responses.GET, NWS_POINTS_URL, json={}, status=500)
        checkpoint = make_checkpoint()
        checkpoint_ids = [str(checkpoint.id)]

        # First attempt (retries=0 < max_retries): Celery raises Retry so the
        # worker schedules another run rather than failing the task.
        with self.assertRaises(Retry):
            fetch_weather_for_checkpoints.apply(args=(checkpoint_ids,))

        self.assertEqual(len(responses.calls), 1)
        self.assertEqual(WeatherObservation.objects.count(), 0)

    @responses.activate
    def test_partial_failure_completes_with_successful_buckets(self):
        def conditional(request):
            # NWS resolves a grid via /points/{lat},{lon}; fail coords near 40.
            if "/40." in request.url:
                return (500, {}, '{"error": "boom"}')
            return (200, {}, json.dumps(nws_points_payload()))

        responses.add_callback(
            responses.GET,
            NWS_POINTS_URL,
            callback=conditional,
            content_type="application/json",
        )
        responses.add(responses.GET, NWS_FORECAST_URL, json=MOCK_NWS_RESPONSE)
        checkpoints = make_checkpoints()  # third checkpoint lives at lat 40.0
        checkpoint_ids = [str(cp.id) for cp in checkpoints]

        result = fetch_weather_for_checkpoints(checkpoint_ids)

        self.assertEqual(result["checkpoints"], 3)
        self.assertEqual(result["saved"], 2)
        self.assertEqual(WeatherObservation.objects.count(), 2)
        self.assertFalse(
            WeatherObservation.objects.filter(checkpoint_id=checkpoints[2].id).exists()
        )

    @responses.activate
    def test_risk_enqueue_failure_does_not_fail_weather_fetch(self):
        register_nws()
        checkpoint = make_checkpoint()

        with patch(
            "apps.risk.tasks.calculate_risk_for_checkpoint.delay",
            side_effect=RuntimeError("broker down"),
        ):
            result = fetch_weather_for_checkpoints([str(checkpoint.id)])

        self.assertEqual(result["saved"], 1)
        self.assertEqual(WeatherObservation.objects.count(), 1)


@override_settings(OPENWEATHERMAP_API_KEY="test-key")
class GenerateHeatmapTaskTests(TestCase):
    def setUp(self):
        cache.clear()

    @responses.activate
    def test_generates_and_caches_grid(self):
        register_nws()
        route = make_heatmap_route()

        result = generate_heatmap_task(str(route.id), 6)

        self.assertTrue(result["generated"])
        self.assertEqual(result["route"], str(route.id))
        self.assertEqual(result["hour"], 6)
        self.assertGreater(result["points"], 0)
        self.assertEqual(HeatmapCache.objects.count(), 1)

    def test_unknown_route_is_skipped(self):
        result = generate_heatmap_task(str(uuid.uuid4()), 6)

        self.assertFalse(result["generated"])
        self.assertEqual(result["hour"], 6)
