"""Risk Celery tasks: assessment + scoring persistence (F05/F06)."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from apps.risk.models import RiskAssessment, RouteScore
from apps.risk.tasks import calculate_risk_for_checkpoint, score_route
from apps.weather.tests.fixtures import make_checkpoint, make_observation

from .fixtures import make_scored_route

UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


class CalculateRiskForCheckpointTests(TestCase):
    def test_unknown_checkpoint_is_skipped(self):
        result = calculate_risk_for_checkpoint(UNKNOWN_ID)

        assert result == {"checkpoint": UNKNOWN_ID, "assessed": False}

    def test_checkpoint_without_weather_is_skipped(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=Decimal("0.00"))

        result = calculate_risk_for_checkpoint(str(checkpoint.id))

        assert result["assessed"] is False
        assert RiskAssessment.objects.count() == 0

    def test_assesses_with_request_load_weight(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=Decimal("0.00"))
        observation = make_observation(checkpoint, wind_speed_mph=Decimal("40.00"))

        result = calculate_risk_for_checkpoint(str(checkpoint.id))

        assessment = RiskAssessment.objects.get(checkpoint=checkpoint)
        assert result == {
            "checkpoint": str(checkpoint.id),
            "assessed": True,
            "combined_risk": "severe",
        }
        assert assessment.load_weight_lbs == route.request.load_weight_lbs
        assert assessment.load_rule_applied == "wind_35_44_over_40k"
        # A lone checkpoint covers the whole route (remaining distance to end).
        assert assessment.segment_miles == route.distance_miles
        assert assessment.weather_observation_id == observation.id

    def test_uses_latest_stored_observation(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=Decimal("0.00"))
        make_observation(checkpoint)
        latest = make_observation(
            checkpoint,
            forecast_time=checkpoint.estimated_arrival + timedelta(hours=2),
            wind_speed_mph=Decimal("60.00"),
        )

        calculate_risk_for_checkpoint(str(checkpoint.id))

        assessment = RiskAssessment.objects.get(checkpoint=checkpoint)
        assert assessment.weather_observation_id == latest.id
        assert assessment.combined_risk == "no_travel"


class ScoreRouteTests(TestCase):
    def test_unknown_route_is_skipped(self):
        result = score_route(UNKNOWN_ID)

        assert result == {"route": UNKNOWN_ID, "scored": False}

    def test_creates_route_score(self):
        route = make_scored_route(duration=240)
        RouteScore.objects.filter(route=route).delete()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=Decimal("0.00"))
        make_observation(checkpoint, wind_speed_mph=Decimal("30.00"))
        RiskAssessment.objects.create(
            checkpoint=checkpoint,
            weather_observation=checkpoint.weather_observations.get(),
            load_weight_lbs=10000,
            wind_risk="moderate",
            rain_risk="low",
            snow_risk="low",
            combined_risk="moderate",
            segment_miles=Decimal("100.00"),
        )

        result = score_route(str(route.id))

        score = RouteScore.objects.get(route=route)
        assert result["scored"] is True
        assert result["composite_score"] == str(score.composite_score)
        assert score.duration_minutes == 240
        assert score.average_risk_score == Decimal("2.000")

    def test_rescoring_is_idempotent(self):
        route = make_scored_route()
        first_id = RouteScore.objects.get(route=route).id

        score_route(str(route.id))

        assert RouteScore.objects.count() == 1
        assert RouteScore.objects.get(route=route).id == first_id
