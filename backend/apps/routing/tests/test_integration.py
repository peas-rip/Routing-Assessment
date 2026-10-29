"""Full flow tests: API -> Celery task -> provider -> API (TESTING.md).

These drive the service the way a client does: POST generate, poll status,
fetch results and detail. The worker step is invoked manually because tests
run without a broker (Celery is eager).
"""

from unittest.mock import patch

import responses
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.routing.exceptions import RoutingProviderError
from apps.routing.models import RouteRequest
from apps.routing.tasks import generate_routes_task

from .fixtures import (
    MOCK_ORS_RESPONSE_1_ROUTE,
    MOCK_ORS_RESPONSE_3_ROUTES,
    MOCK_ORS_RESPONSE_SHORT_ROUTE,
    OSRM_ROUTE_URL,
    valid_generate_payload,
)

GENERATE_URL = "/api/v1/routes/generate/"
TASK_DELAY = "apps.routing.tasks.generate_routes_task.delay"


class FullFlowTests(TestCase):
    """End-to-end journey: POST -> poll -> completed -> route detail."""

    def setUp(self):
        self.client = APIClient()

    def start_request(self, payload=None) -> str:
        """POST /generate/ with the worker enqueue mocked; returns task id."""
        with patch(TASK_DELAY) as delay:
            response = self.client.post(
                GENERATE_URL, payload or valid_generate_payload(), format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        task_id = response.data["data"]["task_id"]
        delay.assert_called_once_with(task_id)
        return task_id

    @responses.activate
    def test_full_flow_polls_pending_then_completed_three_routes(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        task_id = self.start_request()

        # Poll before the worker picks it up.
        pending = self.client.get(f"/api/v1/routes/{task_id}/")
        self.assertEqual(pending.status_code, status.HTTP_200_OK)
        self.assertEqual(pending.data["data"]["status"], "pending")
        self.assertEqual(pending.data["data"]["progress"], 0)

        # Worker runs the task inline (eager Celery, no broker).
        result = generate_routes_task(task_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["routes"], 3)

        # Poll after completion: 3 named routes, every one with checkpoints.
        completed = self.client.get(f"/api/v1/routes/{task_id}/")
        self.assertEqual(completed.status_code, status.HTTP_200_OK)
        data = completed.data["data"]
        self.assertEqual(data["status"], "completed")
        self.assertEqual(len(data["routes"]), 3)
        names = [route["name"] for route in data["routes"]]
        self.assertEqual(names, ["Fastest", "Shortest", "Balanced"])
        for route in data["routes"]:
            self.assertEqual(route["geometry"]["type"], "LineString")
            self.assertGreaterEqual(len(route["checkpoints"]), 2)

        # Route detail by route id returns the same first route.
        first = data["routes"][0]
        detail = self.client.get(f"/api/v1/routes/{first['id']}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        detail_data = detail.data["data"]
        self.assertEqual(detail_data["id"], first["id"])
        self.assertEqual(detail_data["name"], "Fastest")
        self.assertEqual(
            [cp["sequence"] for cp in detail_data["checkpoints"]],
            list(range(len(detail_data["checkpoints"]))),
        )

    @responses.activate
    def test_single_route_flow_completes_with_one_route(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_1_ROUTE)
        task_id = self.start_request()

        generate_routes_task(task_id)

        completed = self.client.get(f"/api/v1/routes/{task_id}/")
        data = completed.data["data"]
        self.assertEqual(data["status"], "completed")
        self.assertEqual(len(data["routes"]), 1)
        self.assertEqual(data["routes"][0]["name"], "Fastest")

    @responses.activate
    def test_short_route_flow_has_origin_and_destination_checkpoints(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_SHORT_ROUTE)
        task_id = self.start_request()

        generate_routes_task(task_id)

        completed = self.client.get(f"/api/v1/routes/{task_id}/")
        checkpoints = completed.data["data"]["routes"][0]["checkpoints"]
        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(float(checkpoints[0]["mile_marker"]), 0.0)
        self.assertGreater(float(checkpoints[-1]["mile_marker"]), 0.0)

    @responses.activate
    def test_provider_outage_ends_in_failed_envelope(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json={"error": "down"}, status=503)
        task_id = self.start_request()

        # Retries exhausted: the request is marked failed (TESTING.md policy).
        with self.assertRaises(RoutingProviderError):
            generate_routes_task.apply(args=(task_id,), retries=3)

        failed = self.client.get(f"/api/v1/routes/{task_id}/")
        self.assertEqual(failed.status_code, status.HTTP_502_BAD_GATEWAY)
        error = failed.data["error"]
        self.assertEqual(error["code"], "ROUTE_GENERATION_FAILED")
        self.assertTrue(error["message"].startswith("Failed to generate routes: "))
        self.assertEqual(error["details"]["provider"], "osrm")
        self.assertEqual(error["details"]["retry_after"], 60)

        # No partial output is left behind.
        route_request = RouteRequest.objects.get(id=task_id)
        self.assertFalse(route_request.routes.exists())

    @patch(TASK_DELAY)
    def test_validation_failure_never_creates_a_request(self, delay):
        payload = valid_generate_payload(load_weight_lbs=0)

        response = self.client.post(GENERATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        delay.assert_not_called()
        self.assertEqual(RouteRequest.objects.count(), 0)
