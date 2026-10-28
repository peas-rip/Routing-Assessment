from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .serializers import (
    GeocodeResultSerializer,
    ReverseQuerySerializer,
    SearchQuerySerializer,
)


class SearchView(APIView):
    """GET /api/v1/geocoding/search/ - address autocomplete."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "geocoding"

    def get(self, request):
        query = SearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        results, was_cached = services.search(
            query=query.validated_data["q"],
            limit=query.validated_data["limit"],
            lat=query.validated_data.get("lat"),
            lon=query.validated_data.get("lon"),
        )
        payload = GeocodeResultSerializer(results, many=True).data
        return Response({"data": payload, "meta": {"cached": was_cached}})


class ReverseView(APIView):
    """GET /api/v1/geocoding/reverse/ - reverse geocoding."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "geocoding"

    def get(self, request):
        query = ReverseQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        result, was_cached = services.reverse(
            lat=query.validated_data["lat"],
            lon=query.validated_data["lon"],
        )
        payload = GeocodeResultSerializer(result).data
        return Response({"data": payload, "meta": {"cached": was_cached}})
