"""Routing API views (docs/API_CONTRACTS.md routing section)."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .exceptions import NoRouteFoundError, RoutingProviderError
from .models import Route, RouteRequest
from .serializers import (
    GenerateRouteRequestSerializer,
    RouteRequestCompletedSerializer,
    RouteRequestStatusSerializer,
    RouteSerializer,
)
from .tasks import generate_routes_task

GENERATED_WAIT_SECONDS = 10
FAILURE_FALLBACK = "External routing service unavailable"


class GenerateView(APIView):
    """POST /api/v1/routes/generate/ - start async route generation (202)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "route-generate"

    def post(self, request):
        payload = GenerateRouteRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        data = payload.validated_data
        origin = data.pop("origin")
        destination = data.pop("destination")
        route_request = RouteRequest.objects.create(
            origin_address=origin["address"],
            origin_lat=origin["latitude"],
            origin_lon=origin["longitude"],
            destination_address=destination["address"],
            destination_lat=destination["latitude"],
            destination_lon=destination["longitude"],
            **data,
        )
        generate_routes_task.delay(str(route_request.id))

        return Response(
            {
                "data": {
                    "task_id": str(route_request.id),
                    "status": "processing",
                    "poll_url": f"/api/v1/routes/{route_request.id}/",
                    "estimated_wait_seconds": GENERATED_WAIT_SECONDS,
                }
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RouteDetailView(APIView):
    """GET /api/v1/routes/{id}/ - task status, results, or a single route.

    The id disambiguates automatically: a RouteRequest id returns generation
    status/results, a Route id returns that route with its checkpoints.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "route-status"

    def get(self, request, route_id):
        route_request = RouteRequest.objects.filter(id=route_id).first()
        if route_request is not None:
            return Response({"data": self._request_payload(route_request)})

        route = Route.objects.filter(id=route_id).first()
        if route is None:
            raise NoRouteFoundError("Route not found.")
        return Response({"data": RouteSerializer(route).data})

    def _request_payload(self, route_request: RouteRequest) -> dict:
        if route_request.status == RouteRequest.Status.FAILED:
            raise RoutingProviderError(
                message=(
                    "Failed to generate routes: "
                    f"{route_request.error_message or FAILURE_FALLBACK}"
                ),
                details={"retry_after": 60},
            )
        if route_request.status in (
            RouteRequest.Status.PENDING,
            RouteRequest.Status.PROCESSING,
        ):
            return RouteRequestStatusSerializer(route_request).data
        return RouteRequestCompletedSerializer(route_request).data
