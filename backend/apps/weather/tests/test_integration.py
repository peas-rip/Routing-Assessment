"""Full flow tests: route generation -> weather enqueue -> observations -> API.

Mirrors docs/SERVICES/weather/TESTING.md: the routing task enqueues the
weather fetch (F04), Celery is eager in tests so forecasts are stored inline,
then the checkpoint weather endpoint serves them.
"""

import responses
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.routing.models import Checkpoint, RouteRequest
from apps.routing.tasks import generate_routes_task
from apps.routing.tests.fixtures import (
    MOCK_ORS_RESPONSE_3_ROUTES,
    ORS_DIRECTIONS_URL,
    make_route_request,
)
from apps.weather.models import WeatherObservation

from .fixtures import OWM_ONECALL_URL, checkpoint_ids_param, mock_onecall_response

GENERATE_URL = "/api/v1/routes/generate/"
WEATHER_URL = "/api/v1/weather/checkpoints/"


# responses.activate must wrap the test methods, not the class: decorating a
# class replaces it with a plain function and pytest would never collect it.
@override_settings(
    OPENROUTESERVICE_API_KEY="test-key",  # route generation runs inline (eager)
    OPENWEATHERMAP_API_KEY="test-key",
)
class WeatherFullFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    @responses.activate
    def test_route_generation_stores_weather_and_serves_it(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        responses.add(responses.GET, OWM_ONECALL_URL, json=mock_onecall_response())
        route_request = make_route_request()

        result = generate_routes_task(str(route_request.id))

        self.assertEqual(result["status"], "completed")
        route_request.refresh_from_db()
        self.assertEqual(route_request.progress, 100)

        checkpoint_ids = list(
            Checkpoint.objects.filter(route__request=route_request).values_list("id", flat=True)
        )
        self.assertTrue(checkpoint_ids)
        self.assertEqual(
            WeatherObservation.objects.filter(checkpoint_id__in=checkpoint_ids).count(),
            len(checkpoint_ids),
        )

        response = self.client.get(
            WEATHER_URL, {"checkpoint_ids": checkpoint_ids_param(checkpoint_ids)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual(len(data), len(checkpoint_ids))
        expected_ids = {str(pk) for pk in checkpoint_ids}
        for item in data:
            self.assertIn(item["checkpoint_id"], expected_ids)
            self.assertEqual(item["precipitation_type"], "rain")
            self.assertEqual(item["temperature_f"], 45.2)

    @responses.activate
    def test_route_completes_but_weather_endpoint_fails_when_provider_down(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        responses.add(responses.GET, OWM_ONECALL_URL, json={"error": "down"}, status=500)
        route_request = make_route_request()

        result = generate_routes_task(str(route_request.id))

        # Weather provider outage never fails route generation (F04).
        self.assertEqual(result["status"], "completed")
        self.assertEqual(WeatherObservation.objects.count(), 0)

        checkpoint_ids = list(
            Checkpoint.objects.filter(route__request=route_request).values_list("id", flat=True)
        )
        response = self.client.get(
            WEATHER_URL, {"checkpoint_ids": checkpoint_ids_param(checkpoint_ids)}
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        error = response.json()["error"]
        self.assertEqual(error["code"], "WEATHER_API_ERROR")
        self.assertEqual(error["details"]["provider"], "openweathermap")

        route_request.refresh_from_db()
        self.assertEqual(route_request.status, RouteRequest.Status.COMPLETED)
