"""API contract tests for generate/status/detail endpoints."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import responses
from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.routing.models import RouteRequest
from apps.routing.tasks import generate_routes_task
from apps.routing.views import GenerateView, RouteDetailView

from .fixtures import (
    MOCK_ORS_RESPONSE_3_ROUTES,
    OSRM_ROUTE_URL,
    make_route_request,
    valid_generate_payload,
)

GENERATE_URL = "/api/v1/routes/generate/"

TASK_DELAY = "apps.routing.tasks.generate_routes_task.delay"


class GenerateViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch(TASK_DELAY)
    def test_generate_returns_accepted_contract(self, delay):
        response = self.client.post(GENERATE_URL, valid_generate_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.data["data"]
        self.assertEqual(set(data), {"task_id", "status", "poll_url", "estimated_wait_seconds"})
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["poll_url"], f"/api/v1/routes/{data['task_id']}/")
        self.assertEqual(data["estimated_wait_seconds"], 10)
        delay.assert_called_once_with(data["task_id"])

        route_request = RouteRequest.objects.get(id=data["task_id"])
        self.assertEqual(route_request.status, RouteRequest.Status.PENDING)
        self.assertEqual(route_request.checkpoint_interval_miles, 25)
        self.assertEqual(route_request.load_weight_lbs, 45000)
        self.assertEqual(route_request.origin_lat, 39.7817)
        self.assertEqual(route_request.destination_lon, -87.6298)

    @patch(TASK_DELAY)
    def test_generate_persists_requested_interval(self, delay):
        payload = valid_generate_payload(checkpoint_interval_miles=50)

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        route_request = RouteRequest.objects.get(id=response.data["data"]["task_id"])
        self.assertEqual(route_request.checkpoint_interval_miles, 50)

    @patch(TASK_DELAY)
    def test_generate_invalid_interval_falls_back_to_25_with_warning(self, delay):
        payload = valid_generate_payload(checkpoint_interval_miles=15)

        with self.assertLogs("apps.routing.services", level="WARNING"):
            response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        route_request = RouteRequest.objects.get(id=response.data["data"]["task_id"])
        self.assertEqual(route_request.checkpoint_interval_miles, 25)

    def test_generate_rejects_naive_departure_time(self):
        payload = valid_generate_payload(departure_time="2030-01-01T08:00:00")

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

    def test_generate_rejects_past_departure_time(self):
        payload = valid_generate_payload(
            departure_time=(timezone.now() - timedelta(hours=2)).isoformat()
        )

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

    def test_generate_rejects_departure_beyond_48_hours(self):
        payload = valid_generate_payload(
            departure_time=(timezone.now() + timedelta(hours=72)).isoformat()
        )

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

    def test_generate_rejects_out_of_range_weight(self):
        for weight in (0, 90_001):
            with self.subTest(weight=weight):
                payload = valid_generate_payload(load_weight_lbs=weight)
                response = self.client.post(GENERATE_URL, payload, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

    def test_generate_rejects_missing_origin(self):
        payload = valid_generate_payload()
        payload.pop("origin")

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

    def test_generate_rejects_identical_origin_and_destination(self):
        payload = valid_generate_payload()
        payload["destination"] = dict(payload["origin"])

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

    def test_generate_rejects_invalid_coordinates(self):
        payload = valid_generate_payload()
        payload["origin"]["latitude"] = 120.0

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")

    def test_throttle_scope_matches_rate_limit_table(self):
        self.assertEqual(GenerateView.throttle_scope, "route-generate")
        self.assertEqual(RouteDetailView.throttle_scope, "route-status")


class RouteStatusViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_pending_status_contract(self):
        route_request = make_route_request()

        response = self.client.get(f"/api/v1/routes/{route_request.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(str(data["task_id"]), str(route_request.id))
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["progress"], 0)
        self.assertEqual(data["message"], "Queued for route generation.")

    def test_processing_status_reports_progress_and_message(self):
        route_request = make_route_request(status="processing", progress=60)

        response = self.client.get(f"/api/v1/routes/{route_request.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["progress"], 60)
        self.assertEqual(data["message"], "Sampling checkpoints along the routes.")

    def test_processing_status_messages_cover_every_milestone(self):
        expected = [
            (30, "Generating route options."),
            (60, "Sampling checkpoints along the routes."),
            (90, "Fetching weather forecasts."),
            (95, "Finalizing results."),
        ]
        for progress, message in expected:
            with self.subTest(progress=progress):
                route_request = make_route_request(status="processing", progress=progress)
                response = self.client.get(f"/api/v1/routes/{route_request.id}/")
                self.assertEqual(response.data["data"]["message"], message)

    @responses.activate
    @responses.activate
    def test_completed_status_contract(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()
        generate_routes_task(str(route_request.id))

        response = self.client.get(f"/api/v1/routes/{route_request.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(str(data["request_id"]), str(route_request.id))
        self.assertEqual(data["status"], "completed")
        self.assertEqual(len(data["routes"]), 3)
        self.assertEqual(
            data["origin"],
            {"address": "Springfield, IL", "latitude": 39.7817, "longitude": -89.6501},
        )
        self.assertEqual(
            data["destination"],
            {"address": "Chicago, IL", "latitude": 41.8781, "longitude": -87.6298},
        )
        self.assertEqual(data["load_weight_lbs"], 45000)
        self.assertIsInstance(datetime.fromisoformat(str(data["departure_time"])), datetime)

        first = data["routes"][0]
        required = {
            "id",
            "route_index",
            "name",
            "distance_miles",
            "duration_minutes",
            "geometry",
            "summary",
            "checkpoints",
        }
        self.assertTrue(required.issubset(first))
        self.assertEqual(first["name"], "Fastest")
        self.assertEqual(float(first["distance_miles"]), 202.44)
        self.assertEqual(first["duration_minutes"], 195)
        self.assertEqual(first["geometry"]["type"], "LineString")
        self.assertEqual(first["summary"]["distance"], 325800)

        checkpoints = first["checkpoints"]
        self.assertGreaterEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[0]["sequence"], 0)
        self.assertEqual(float(checkpoints[0]["mile_marker"]), 0.0)
        for field in ("id", "latitude", "longitude", "estimated_arrival"):
            self.assertIn(field, checkpoints[0])

    def test_failed_status_returns_error_envelope(self):
        route_request = make_route_request(
            status="failed",
            error_message="Routing provider returned an error.",
        )

        response = self.client.get(f"/api/v1/routes/{route_request.id}/")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        error = response.data["error"]
        self.assertEqual(error["code"], "ROUTE_GENERATION_FAILED")
        self.assertTrue(error["message"].startswith("Failed to generate routes: "))
        self.assertIn("Routing provider", error["message"])
        self.assertEqual(error["details"]["provider"], "osrm")
        self.assertEqual(error["details"]["retry_after"], 60)

    @responses.activate
    @responses.activate
    def test_route_detail_contract(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()
        generate_routes_task(str(route_request.id))
        route = route_request.routes.first()

        response = self.client.get(f"/api/v1/routes/{route.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["id"], str(route.id))
        self.assertEqual(data["route_index"], 0)
        self.assertEqual(data["geometry"]["type"], "LineString")
        self.assertGreaterEqual(len(data["checkpoints"]), 2)

    def test_unknown_id_returns_route_not_found(self):
        missing_id = "00000000-0000-0000-0000-000000000000"

        response = self.client.get(f"/api/v1/routes/{missing_id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "ROUTE_NOT_FOUND")

    def test_non_uuid_id_returns_404(self):
        response = self.client.get("/api/v1/routes/not-a-uuid/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class GenerateViewPayloadHandlingTests(TestCase):
    """Validated payload flattening into RouteRequest columns."""

    def setUp(self):
        self.client = APIClient()

    @patch(TASK_DELAY)
    def test_stores_departure_with_utc_normalization(self, delay):
        departure = (timezone.now() + timedelta(hours=6)).astimezone(
            timezone.get_current_timezone()
        )
        payload = valid_generate_payload(departure_time=departure.isoformat())

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        route_request = RouteRequest.objects.get(id=response.data["data"]["task_id"])
        self.assertEqual(route_request.departure_time, departure)
        self.assertTrue(timezone.is_aware(route_request.departure_time))

    @responses.activate
    def test_decimal_fields_are_json_numbers_in_completed_response(self):
        """Contract renders distance/mile markers as JSON numbers, not strings."""
        self.assertFalse(settings.REST_FRAMEWORK["COERCE_DECIMAL_TO_STRING"])

        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()
        generate_routes_task(str(route_request.id))

        response = self.client.get(f"/api/v1/routes/{route_request.id}/")

        body = json.loads(response.content)
        first_route = body["data"]["routes"][0]
        self.assertIsInstance(first_route["distance_miles"], float)
        self.assertIsInstance(first_route["checkpoints"][1]["mile_marker"], float)
