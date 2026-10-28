"""Weather API views (docs/API_CONTRACTS.md weather section)."""

import logging

from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.routing.models import Checkpoint, Route

from .exceptions import HeatmapRouteNotFoundError, WeatherError, WeatherNotFoundError
from .serializers import (
    CheckpointWeatherQuerySerializer,
    HeatmapQuerySerializer,
    HeatmapSerializer,
    WeatherSerializer,
)
from .services import (
    DEFAULT_HEATMAP_RESOLUTION_MILES,
    fetch_weather_batch,
    generate_heatmap,
    get_stored_observations,
    is_stale,
    save_observations,
)
from .tasks import fetch_weather_for_checkpoints

logger = logging.getLogger(__name__)


class CheckpointWeatherView(APIView):
    """GET /api/v1/weather/checkpoints/ - stored weather, fetched on demand."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "weather"

    def get(self, request):
        query = CheckpointWeatherQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        checkpoint_ids = query.validated_data["checkpoint_ids"]
        forecast_time = query.validated_data.get("forecast_time")

        checkpoints = list(Checkpoint.objects.filter(id__in=checkpoint_ids))
        observations = get_stored_observations(checkpoints, forecast_time)

        missing = [cp for cp in checkpoints if cp.id not in observations]
        if missing:
            self._fetch_missing(missing, forecast_time, observations)

        if not observations:
            raise WeatherNotFoundError()

        self._refresh_stale(observations.values())

        ordered = [observations[cp_id] for cp_id in checkpoint_ids if cp_id in observations]
        return Response({"data": WeatherSerializer(ordered, many=True).data})

    @staticmethod
    def _fetch_missing(missing, forecast_time, observations) -> None:
        """Fetch forecasts for checkpoints without a stored observation.

        Provider failures surface as 502/429 only when there is nothing
        cached to serve; otherwise the stored subset is returned.
        """
        target_times = (
            {checkpoint.id: forecast_time for checkpoint in missing}
            if forecast_time is not None
            else None
        )
        try:
            results = fetch_weather_batch(missing, target_times=target_times)
            save_observations(results)
        except WeatherError:
            if not observations:
                raise
            logger.warning("On-demand weather fetch failed; serving stored observations")
        observations.update(get_stored_observations(missing, forecast_time))

    @staticmethod
    def _refresh_stale(observations) -> None:
        """Stale-while-revalidate: serve now, refresh in the background (F04)."""
        stale_ids = [str(obs.checkpoint_id) for obs in observations if is_stale(obs)]
        if not stale_ids:
            return
        try:
            fetch_weather_for_checkpoints.delay(stale_ids)
        except Exception as exc:
            logger.warning("Stale weather refresh could not be enqueued: %s", exc)


class HeatmapView(APIView):
    """GET /api/v1/weather/heatmap/ - risk grid along the corridor (F08)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "heatmap"

    def get(self, request):
        query = HeatmapQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data

        route = Route.objects.filter(id=data["route_id"]).first()
        if route is None:
            raise HeatmapRouteNotFoundError()

        result = generate_heatmap(
            route,
            forecast_hour=data["hour"],
            resolution_miles=data.get("resolution_miles", DEFAULT_HEATMAP_RESOLUTION_MILES),
        )
        return Response({"data": HeatmapSerializer(result).data})
