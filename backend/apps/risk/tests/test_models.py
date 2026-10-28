"""Model string representations (apps/risk/models.py)."""

from decimal import Decimal

from django.test import TestCase

from apps.risk.models import RiskAssessment
from apps.weather.tests.fixtures import make_checkpoint, make_observation

from .fixtures import make_scored_route


class ModelStringTests(TestCase):
    def test_risk_assessment_str(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=Decimal("0.00"))
        observation = make_observation(checkpoint)
        assessment = RiskAssessment.objects.create(
            checkpoint=checkpoint,
            weather_observation=observation,
            load_weight_lbs=45000,
            wind_risk="low",
            rain_risk="low",
            snow_risk="low",
            combined_risk="high",
            segment_miles=Decimal("25.00"),
        )

        self.assertEqual(str(assessment), f"risk checkpoint={checkpoint.id} [high]")

    def test_route_score_str(self):
        route = make_scored_route()

        score = route.score

        self.assertEqual(str(score), f"score route={route.id} composite={score.composite_score}")
