"""Async task flow: status transitions, retry policy, failure handling."""

from unittest.mock import patch

import responses
from django.conf import settings
from django.test import TestCase, override_settings

from apps.routing.exceptions import (
    NoRouteFoundError,
    RoutingProviderError,
    RoutingRateLimitError,
)
from apps.routing.models import Checkpoint, RouteRequest
from apps.routing.tasks import generate_routes_task

from .fixtures import (
    MOCK_ORS_RESPONSE_3_ROUTES,
    MOCK_ORS_RESPONSE_EMPTY,
    OSRM_ROUTE_URL,
    make_route_request,
)


@override_settings(OPENROUTESERVICE_API_KEY="test-key")
class GenerateRoutesTaskTests(TestCase):
    @responses.activate
    def test_success_completes_request(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()

        result = generate_routes_task(str(route_request.id))

        route_request.refresh_from_db()
        self.assertEqual(route_request.status, RouteRequest.Status.COMPLETED)
        self.assertEqual(route_request.progress, 100)
        self.assertIsNotNone(route_request.completed_at)
        self.assertIsNone(route_request.error_message)
        self.assertEqual(route_request.routes.count(), 3)
        self.assertTrue(all(route.checkpoints.exists() for route in route_request.routes.all()))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["routes"], 3)

    @responses.activate
    def test_provider_error_retries_and_keeps_processing(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json={"error": "down"}, status=500)
        route_request = make_route_request()

        with self.assertRaises(RoutingProviderError):
            generate_routes_task(str(route_request.id))

        route_request.refresh_from_db()
        # Still eligible for retry: not marked failed.
        self.assertIn(
            route_request.status,
            [RouteRequest.Status.PENDING, RouteRequest.Status.PROCESSING],
        )
        self.assertIsNone(route_request.error_message)

    @responses.activate
    def test_provider_error_marks_failed_when_retries_exhausted(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json={"error": "down"}, status=500)
        route_request = make_route_request()

        with self.assertRaises(RoutingProviderError):
            generate_routes_task.apply(args=(str(route_request.id),), retries=3)

        route_request.refresh_from_db()
        self.assertEqual(route_request.status, RouteRequest.Status.FAILED)
        self.assertIn("error", route_request.error_message)

    @responses.activate
    def test_no_route_found_fails_immediately_without_retry(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_EMPTY)
        route_request = make_route_request()

        with self.assertRaises(NoRouteFoundError):
            generate_routes_task(str(route_request.id))

        route_request.refresh_from_db()
        self.assertEqual(route_request.status, RouteRequest.Status.FAILED)
        self.assertIn("No drivable route", route_request.error_message)

    @responses.activate
    def test_rate_limit_fails_without_retry(self):
        responses.add(
            responses.GET,
            OSRM_ROUTE_URL,
            json={"error": "rate limited"},
            status=429,
            headers={"Retry-After": "60"},
        )
        route_request = make_route_request()

        with self.assertRaises(RoutingRateLimitError):
            generate_routes_task(str(route_request.id))

        route_request.refresh_from_db()
        self.assertEqual(route_request.status, RouteRequest.Status.FAILED)
        self.assertIn("rate limit", route_request.error_message)

    @responses.activate
    def test_unexpected_error_marks_failed_and_propagates(self):
        route_request = make_route_request()

        with patch("apps.routing.tasks.generate_routes", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                generate_routes_task(str(route_request.id))

        route_request.refresh_from_db()
        self.assertEqual(route_request.status, RouteRequest.Status.FAILED)
        self.assertEqual(route_request.error_message, "boom")

    @responses.activate
    def test_rerun_does_not_duplicate_routes_or_checkpoints(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()

        generate_routes_task(str(route_request.id))
        first_checkpoint_count = Checkpoint.objects.filter(route__request=route_request).count()

        generate_routes_task(str(route_request.id))

        route_request.refresh_from_db()
        self.assertEqual(route_request.routes.count(), 3)
        self.assertEqual(
            Checkpoint.objects.filter(route__request=route_request).count(),
            first_checkpoint_count,
        )

    @responses.activate
    def test_missing_request_id_propagates(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        missing_id = "00000000-0000-0000-0000-000000000000"

        with self.assertRaises(RouteRequest.DoesNotExist):
            generate_routes_task(missing_id)

    @responses.activate
    def test_weather_fetch_enqueued_with_all_checkpoints(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()

        with patch("apps.weather.tasks.fetch_weather_for_checkpoints.delay") as weather_delay:
            generate_routes_task(str(route_request.id))

        route_request.refresh_from_db()
        self.assertEqual(route_request.status, RouteRequest.Status.COMPLETED)
        weather_delay.assert_called_once()
        enqueued = weather_delay.call_args[0][0]
        expected = {
            str(pk)
            for pk in Checkpoint.objects.filter(route__request=route_request).values_list(
                "id", flat=True
            )
        }
        self.assertEqual(set(enqueued), expected)
        self.assertEqual(len(enqueued), len(expected))

    @responses.activate
    def test_weather_enqueue_failure_does_not_fail_route_generation(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()

        with patch(
            "apps.weather.tasks.fetch_weather_for_checkpoints.delay",
            side_effect=RuntimeError("broker down"),
        ):
            result = generate_routes_task(str(route_request.id))

        self.assertEqual(result["status"], "completed")
        route_request.refresh_from_db()
        self.assertEqual(route_request.status, RouteRequest.Status.COMPLETED)
        self.assertEqual(route_request.progress, 100)

    @responses.activate
    def test_weather_enqueue_skipped_when_app_disabled(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()
        without_weather = [app for app in settings.INSTALLED_APPS if app != "apps.weather"]

        with override_settings(INSTALLED_APPS=without_weather):
            with patch("apps.weather.tasks.fetch_weather_for_checkpoints.delay") as weather_delay:
                result = generate_routes_task(str(route_request.id))

        weather_delay.assert_not_called()
        self.assertEqual(result["status"], "completed")
