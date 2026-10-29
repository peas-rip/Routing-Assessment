"""Full pipeline: weather -> risk -> score -> recommendation (F05/F06)."""

from decimal import Decimal

import responses
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.risk.models import RiskAssessment, RouteScore
from apps.risk.services import rank_routes
from apps.risk.tasks import calculate_risk_for_checkpoint, score_route
from apps.routing.tests.fixtures import make_route, make_route_request
from apps.weather.models import WeatherObservation
from apps.weather.tasks import fetch_weather_for_checkpoints
from apps.weather.tests.fixtures import (
    future_arrival,
    make_checkpoint,
    make_observation,
    register_nws,
)

from .fixtures import make_scored_route

RISK_STRIPPED_APPS = [app for app in settings.INSTALLED_APPS if app != "apps.risk"]

SNOW_STORM_SPEC = {
    "wind_speed_mph": Decimal("38.00"),
    "precipitation_rate_in_hr": Decimal("1.500"),
    "precipitation_type": "snow",
    "snowfall_rate_in_hr": Decimal("1.500"),
    "conditions": "heavy snow",
}
MODERATE_WIND_SPEC = {"wind_speed_mph": Decimal("30.00")}


def build_route_with_weather(request, spec, **route_overrides):
    """Route with three checkpoints carrying the same weather spec."""
    route = make_scored_route(request, **route_overrides)
    checkpoints = [
        make_checkpoint(route=route, sequence=sequence, mile_marker=Decimal(f"{sequence * 50}.00"))
        for sequence in range(3)
    ]
    for checkpoint in checkpoints:
        make_observation(checkpoint, **dict(spec))
    return route


@override_settings(OPENWEATHERMAP_API_KEY="test-key")
class RiskPipelineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def build_three_routes(self):
        """Three routes: severe snow, moderate wind, calm rain."""
        request = make_route_request(load_weight_lbs=45000)
        routes = [
            build_route_with_weather(request, SNOW_STORM_SPEC, route_index=0, name="Severe"),
            build_route_with_weather(request, MODERATE_WIND_SPEC, route_index=1, name="Moderate"),
            build_route_with_weather(request, {}, route_index=2, name="Calm"),
        ]
        RouteScore.objects.all().delete()  # score from scratch in the test
        return routes

    def test_weather_to_risk_to_score_to_recommendation(self):
        routes = self.build_three_routes()

        for route in routes:
            for checkpoint in route.checkpoints.all():
                calculate_risk_for_checkpoint(str(checkpoint.id))
            score_route(str(route.id))

        ranked, recommended_id = rank_routes(routes[0])

        assert [route.id for route, _ in ranked] == [
            routes[2].id,  # calm: avg 1.0
            routes[1].id,  # moderate wind: avg 2.0
            routes[0].id,  # snow + load escalation: severe miles
        ]
        assert recommended_id == routes[2].id
        severe_score = dict(ranked)[routes[0]]
        assert severe_score.severe_miles == Decimal("100.00")
        assert RouteScore.objects.count() == 3

    def test_recommendation_endpoint_after_calculate(self):
        routes = self.build_three_routes()

        for route in routes:
            response = self.client.post(
                "/api/v1/risk/calculate/",
                {
                    "route_id": str(route.id),
                    "load_weight_lbs": 45000,
                    "checkpoint_interval_miles": 25,
                },
                format="json",
            )
            assert response.status_code == 200

        response = self.client.get(f"/api/v1/risk/recommendation/{routes[0].id}/")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["recommended_route_id"] == str(routes[2].id)
        assert [item["name"] for item in data["routes"]] == ["Calm", "Moderate", "Severe"]

    @responses.activate
    def test_weather_fetch_enqueues_risk_assessments(self):
        register_nws()
        request = make_route_request()
        route = make_route(request)
        checkpoint = make_checkpoint(
            route=route,
            sequence=0,
            mile_marker=Decimal("0.00"),
            estimated_arrival=future_arrival(8),
        )

        fetch_weather_for_checkpoints([str(checkpoint.id)])

        observation = WeatherObservation.objects.get(checkpoint=checkpoint)
        assessment = RiskAssessment.objects.get(checkpoint=checkpoint)
        assert assessment.load_weight_lbs == request.load_weight_lbs
        assert assessment.combined_risk == "low"
        assert assessment.weather_observation_id == observation.id
        # Scoring stays lazy: the hook only assesses, never scores.
        assert RouteScore.objects.count() == 0

    @responses.activate
    def test_refetched_weather_reassesses_risk_in_place(self):
        register_nws()
        request = make_route_request()
        route = make_route(request)
        checkpoint = make_checkpoint(
            route=route,
            sequence=0,
            mile_marker=Decimal("0.00"),
            estimated_arrival=future_arrival(8),
        )

        fetch_weather_for_checkpoints([str(checkpoint.id)])
        assert RiskAssessment.objects.get(checkpoint=checkpoint).combined_risk == "low"

        # The provider now reports 60 mph winds for every hour.
        responses.reset()
        register_nws(wind=60.0, pop=0, short="Clear")
        cache.clear()  # bypass the 15-minute forecast cache

        fetch_weather_for_checkpoints([str(checkpoint.id)])

        assessment = RiskAssessment.objects.get(checkpoint=checkpoint)
        assert RiskAssessment.objects.count() == 1
        assert assessment.combined_risk == "no_travel"
        assert assessment.load_rule_applied == "wind_ge_55_any_load"

    @override_settings(INSTALLED_APPS=RISK_STRIPPED_APPS)
    @responses.activate
    def test_risk_enqueue_is_skipped_without_the_risk_app(self):
        register_nws()
        request = make_route_request()
        route = make_route(request)
        checkpoint = make_checkpoint(
            route=route,
            sequence=0,
            mile_marker=Decimal("0.00"),
            estimated_arrival=future_arrival(8),
        )

        fetch_weather_for_checkpoints([str(checkpoint.id)])

        assert WeatherObservation.objects.count() == 1
        assert RiskAssessment.objects.count() == 0
