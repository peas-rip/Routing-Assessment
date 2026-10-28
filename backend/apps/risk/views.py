"""Risk API views (docs/API_CONTRACTS.md risk section)."""

import logging

from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.routing.models import Route

from .exceptions import (
    InsufficientRiskDataError,
    RiskCalculationError,
    RiskError,
    RouteNotFoundError,
)
from .models import RiskAssessment
from .serializers import (
    CheckpointRiskSerializer,
    RecommendedRouteSerializer,
    RiskCalculateSerializer,
)
from .services import assess_checkpoint, rank_routes, segment_miles_by_checkpoint
from .tasks import score_route

logger = logging.getLogger(__name__)


def _enqueue_route_scoring(route_ids) -> None:
    """Queue F06 scoring; enqueue failures never fail the request."""
    for route_id in route_ids:
        try:
            score_route.delay(str(route_id))
        except Exception as exc:
            logger.warning("Route scoring enqueue failed for %s: %s", route_id, exc)


class CalculateView(APIView):
    """POST /api/v1/risk/calculate/ - assess one route's checkpoints (F05)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "risk"

    def post(self, request):
        payload = RiskCalculateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        route = Route.objects.select_related("request").filter(id=data["route_id"]).first()
        if route is None:
            raise RouteNotFoundError()

        checkpoints = list(route.checkpoints.all())
        if not checkpoints:
            raise InsufficientRiskDataError("Route has no checkpoints to assess.")

        try:
            assessed = self._assess(route, checkpoints, data["load_weight_lbs"])
        except RiskError:
            raise
        except Exception as exc:
            logger.exception("Risk calculation failed for route %s", route.id)
            raise RiskCalculationError() from exc

        if not assessed:
            raise InsufficientRiskDataError(
                "No weather data is available for this route's checkpoints yet."
            )

        self._enqueue_scoring(route)
        return Response(
            {
                "data": {
                    "route_id": str(route.id),
                    "checkpoints": CheckpointRiskSerializer(assessed, many=True).data,
                }
            }
        )

    @staticmethod
    def _assess(route, checkpoints, load_weight_lbs) -> list[dict]:
        """Assess stored weather per checkpoint; returns serializable payloads."""
        segments = segment_miles_by_checkpoint(route, checkpoints)
        payloads = []
        for checkpoint in checkpoints:
            weather = checkpoint.weather_observations.order_by("-forecast_time").first()
            if weather is None:
                continue
            assessment = assess_checkpoint(
                checkpoint, weather, load_weight_lbs, segments[checkpoint.id]
            )
            payloads.append(
                {
                    "checkpoint_id": checkpoint.id,
                    "mile_marker": checkpoint.mile_marker,
                    "latitude": checkpoint.latitude,
                    "longitude": checkpoint.longitude,
                    "estimated_arrival": checkpoint.estimated_arrival,
                    "weather": weather,
                    "risk": assessment,
                }
            )
        return payloads

    @staticmethod
    def _enqueue_scoring(route) -> None:
        """Score every route of the request that has risk assessments (F06)."""
        assessed_route_ids = set(
            RiskAssessment.objects.filter(checkpoint__route__request=route.request).values_list(
                "checkpoint__route_id", flat=True
            )
        )
        _enqueue_route_scoring(assessed_route_ids)


class RecommendationView(APIView):
    """GET /api/v1/risk/recommendation/{route_id}/ - best route per F06."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "risk"

    def get(self, request, route_id):
        route = Route.objects.select_related("request").filter(id=route_id).first()
        if route is None:
            raise RouteNotFoundError("Route not found for recommendation.")

        try:
            ranked, recommended_id = rank_routes(route)
        except RiskError:
            raise
        except Exception as exc:
            logger.exception("Recommendation failed for route %s", route_id)
            raise RiskCalculationError() from exc

        routes = [
            {
                "route_id": candidate.id,
                "name": candidate.name,
                "distance_miles": candidate.distance_miles,
                "duration_minutes": candidate.duration_minutes,
                "score": score,
                "is_recommended": candidate.id == recommended_id,
            }
            for candidate, score in ranked
        ]
        return Response(
            {
                "data": {
                    "request_id": str(route.request_id),
                    "recommended_route_id": str(recommended_id),
                    "routes": RecommendedRouteSerializer(routes, many=True).data,
                }
            }
        )
