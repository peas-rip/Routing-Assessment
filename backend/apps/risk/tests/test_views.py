"""Risk API contracts (docs/API_CONTRACTS.md risk section)."""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.risk.exceptions import RiskCalculationError
from apps.risk.models import RiskAssessment, RouteScore
from apps.routing.tests.fixtures import make_route, make_route_request
from apps.weather.tests.fixtures import make_checkpoint, make_observation

from .fixtures import make_scored_route
from .test_services import scored_and_assessed

CALCULATE_URL = "/api/v1/risk/calculate/"

# Exact field order of the documented payloads.
CHECKPOINT_FIELDS = [
    "checkpoint_id",
    "mile_marker",
    "latitude",
    "longitude",
    "estimated_arrival",
    "weather",
    "risk",
]
WEATHER_BLOCK_FIELDS = [
    "temperature_f",
    "conditions",
    "wind_speed_mph",
    "wind_direction_deg",
    "precipitation_rate_in_hr",
    "precipitation_type",
]
RISK_BLOCK_FIELDS = [
    "wind_risk",
    "rain_risk",
    "snow_risk",
    "combined_risk",
    "load_rule_applied",
    "segment_miles",
]
RECOMMENDATION_FIELDS = ["request_id", "recommended_route_id", "routes"]
RECOMMENDATION_ROUTE_FIELDS = [
    "route_id",
    "name",
    "distance_miles",
    "duration_minutes",
    "score",
    "is_recommended",
]
SCORE_BLOCK_FIELDS = [
    "severe_miles",
    "high_miles",
    "average_risk_score",
    "duration_minutes",
    "composite_score",
    "risk_breakdown",
]


def valid_payload(route, **overrides):
    payload = {
        "route_id": str(route.id),
        "load_weight_lbs": 45000,
        "checkpoint_interval_miles": 25,
    }
    payload.update(overrides)
    return payload


def weathered_route(observation_overrides=None, **route_overrides):
    """Route with one checkpoint + stored observation."""
    route = make_scored_route(**route_overrides)
    checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=Decimal("0.00"))
    observation = make_observation(checkpoint, **(observation_overrides or {}))
    return route, checkpoint, observation


class CalculateViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_contract_shape_and_values(self):
        route, checkpoint, _ = weathered_route({"wind_speed_mph": Decimal("12.50")})

        response = self.client.post(CALCULATE_URL, valid_payload(route), format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual(list(data), ["route_id", "checkpoints"])
        self.assertEqual(data["route_id"], str(route.id))

        first = data["checkpoints"][0]
        self.assertEqual(list(first), CHECKPOINT_FIELDS)
        self.assertEqual(first["checkpoint_id"], str(checkpoint.id))
        self.assertEqual(first["mile_marker"], 0.0)
        self.assertEqual(first["latitude"], checkpoint.latitude)
        self.assertEqual(first["longitude"], checkpoint.longitude)
        self.assertEqual(list(first["weather"]), WEATHER_BLOCK_FIELDS)
        self.assertEqual(first["weather"]["wind_speed_mph"], 12.5)
        self.assertEqual(first["weather"]["precipitation_type"], "rain")
        self.assertEqual(list(first["risk"]), RISK_BLOCK_FIELDS)
        self.assertEqual(first["risk"]["combined_risk"], "low")
        self.assertIsNone(first["risk"]["load_rule_applied"])
        # The only checkpoint covers the route's remaining distance to end.
        self.assertEqual(first["risk"]["segment_miles"], float(route.distance_miles))

    def test_load_escalation_applies_through_api(self):
        route, _, _ = weathered_route({"wind_speed_mph": Decimal("40.00")})

        response = self.client.post(CALCULATE_URL, valid_payload(route), format="json")

        risk = response.json()["data"]["checkpoints"][0]["risk"]
        self.assertEqual(risk["wind_risk"], "high")
        self.assertEqual(risk["combined_risk"], "severe")
        self.assertEqual(risk["load_rule_applied"], "wind_35_44_over_40k")

    def test_checkpoints_are_ordered_with_segment_miles(self):
        route = make_scored_route(distance_miles=Decimal("75.00"))
        markers = [Decimal("0.00"), Decimal("25.00"), Decimal("50.00")]
        for sequence, marker in enumerate(markers):
            checkpoint = make_checkpoint(route=route, sequence=sequence, mile_marker=marker)
            make_observation(checkpoint)

        response = self.client.post(CALCULATE_URL, valid_payload(route), format="json")

        checkpoints = response.json()["data"]["checkpoints"]
        self.assertEqual([item["mile_marker"] for item in checkpoints], [0.0, 25.0, 50.0])
        # Forward segments: to the next checkpoint, last one to the route end
        # (75 - 50 = 25).
        self.assertEqual(
            [item["risk"]["segment_miles"] for item in checkpoints], [25.0, 25.0, 25.0]
        )

    def test_unknown_route_returns_404(self):
        payload = {
            "route_id": str(uuid.uuid4()),
            "load_weight_lbs": 45000,
            "checkpoint_interval_miles": 25,
        }

        response = self.client.post(CALCULATE_URL, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        error = response.json()["error"]
        self.assertEqual(list(error), ["code", "message", "details"])
        self.assertEqual(error["code"], "ROUTE_NOT_FOUND")

    def test_missing_fields_return_400(self):
        response = self.client.post(CALCULATE_URL, {"route_id": str(uuid.uuid4())}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error = response.json()["error"]
        self.assertEqual(error["code"], "VALIDATION_ERROR")
        self.assertIn("load_weight_lbs", error["details"]["fields"])
        self.assertIn("checkpoint_interval_miles", error["details"]["fields"])

    def test_invalid_interval_returns_400(self):
        route, _, _ = weathered_route()

        response = self.client.post(
            CALCULATE_URL, valid_payload(route, checkpoint_interval_miles=15), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_load_weight_boundaries(self):
        route, _, _ = weathered_route()

        for invalid in (9999, 80001):
            response = self.client.post(
                CALCULATE_URL, valid_payload(route, load_weight_lbs=invalid), format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            CALCULATE_URL, valid_payload(route, load_weight_lbs=10000), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_route_without_checkpoints_returns_400(self):
        route = make_scored_route()

        response = self.client.post(CALCULATE_URL, valid_payload(route), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("checkpoints", response.json()["error"]["message"])

    def test_route_without_weather_returns_400(self):
        route = make_scored_route()
        make_checkpoint(route=route, sequence=0, mile_marker=Decimal("0.00"))

        response = self.client.post(CALCULATE_URL, valid_payload(route), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("weather", response.json()["error"]["message"])

    def test_calculation_failure_returns_500(self):
        route, _, _ = weathered_route()

        with patch("apps.risk.views.assess_checkpoint", side_effect=RuntimeError("boom")):
            response = self.client.post(CALCULATE_URL, valid_payload(route), format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json()["error"]["code"], "RISK_CALCULATION_FAILED")

    def test_risk_error_from_assessment_propagates_unchanged(self):
        route, _, _ = weathered_route()

        with patch("apps.risk.views.assess_checkpoint", side_effect=RiskCalculationError()):
            response = self.client.post(CALCULATE_URL, valid_payload(route), format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json()["error"]["code"], "RISK_CALCULATION_FAILED")

    def test_scoring_enqueue_failure_does_not_fail_request(self):
        route, _, _ = weathered_route()

        with patch("apps.risk.views.score_route.delay", side_effect=RuntimeError("broker")):
            response = self.client.post(CALCULATE_URL, valid_payload(route), format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_scores_assessed_request_routes_after_calculation(self):
        request = make_route_request()
        assessed = make_route(request, route_index=0)
        checkpoint = make_checkpoint(route=assessed, sequence=0, mile_marker=Decimal("0.00"))
        make_observation(checkpoint)
        sibling = make_route(request, route_index=1)  # no assessments anywhere

        self.client.post(CALCULATE_URL, valid_payload(assessed), format="json")

        self.assertTrue(RouteScore.objects.filter(route=assessed).exists())
        self.assertFalse(RouteScore.objects.filter(route=sibling).exists())

    def test_recalculation_updates_existing_rows(self):
        route, checkpoint, _ = weathered_route()

        self.client.post(CALCULATE_URL, valid_payload(route, load_weight_lbs=10000), format="json")
        self.client.post(CALCULATE_URL, valid_payload(route, load_weight_lbs=45000), format="json")

        assessment = RiskAssessment.objects.get(checkpoint=checkpoint)
        self.assertEqual(RiskAssessment.objects.count(), 1)
        self.assertEqual(assessment.load_weight_lbs, 45000)


class RecommendationViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def url_for(self, route) -> str:
        return f"/api/v1/risk/recommendation/{route.id}/"

    def test_contract_shape_and_ordering(self):
        request = make_route_request()
        worst = scored_and_assessed(request, severe=10, duration=100, route_index=0)
        best = scored_and_assessed(request, duration=210, route_index=1)

        response = self.client.get(self.url_for(worst))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual(list(data), RECOMMENDATION_FIELDS)
        self.assertEqual(data["request_id"], str(request.id))
        self.assertEqual(data["recommended_route_id"], str(best.id))

        routes = data["routes"]
        self.assertEqual([item["route_id"] for item in routes], [str(best.id), str(worst.id)])
        first = routes[0]
        self.assertEqual(list(first), RECOMMENDATION_ROUTE_FIELDS)
        self.assertEqual(list(first["score"]), SCORE_BLOCK_FIELDS)
        self.assertEqual(first["is_recommended"], True)
        self.assertEqual(routes[1]["is_recommended"], False)
        self.assertEqual(
            list(first["score"]["risk_breakdown"]),
            ["low", "moderate", "high", "severe", "no_travel"],
        )

    def test_lazy_scoring_of_assessed_routes(self):
        request = make_route_request()
        first = scored_and_assessed(request, route_index=0)
        second = scored_and_assessed(request, avg=2.0, route_index=1)
        RouteScore.objects.all().delete()

        response = self.client.get(self.url_for(second))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(RouteScore.objects.count(), 2)
        self.assertEqual(response.json()["data"]["recommended_route_id"], str(first.id))

    def test_fewer_than_two_assessed_routes_returns_400(self):
        request = make_route_request()
        route = scored_and_assessed(request)

        response = self.client.get(self.url_for(route))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_unknown_route_returns_404(self):
        response = self.client.get(f"/api/v1/risk/recommendation/{uuid.uuid4()}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["error"]["code"], "ROUTE_NOT_FOUND")

    def test_ranking_failure_returns_500(self):
        request = make_route_request()
        route = scored_and_assessed(request)
        scored_and_assessed(request, route_index=1)

        with patch("apps.risk.views.rank_routes", side_effect=RuntimeError("boom")):
            response = self.client.get(self.url_for(route))

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json()["error"]["code"], "RISK_CALCULATION_FAILED")

    def test_insufficient_data_error_propagates_as_400(self):
        request = make_route_request()
        scored_and_assessed(request, route_index=0)
        unscored_without_assessment = make_route(request, route_index=1)

        response = self.client.get(self.url_for(unscored_without_assessment))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
