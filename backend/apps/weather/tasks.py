"""Celery tasks for the weather service."""

import logging

from django.conf import settings

from apps.routing.models import Checkpoint, Route
from config.celery import app as celery_app

from .exceptions import WeatherProviderError, WeatherRateLimitError
from .services import (
    DEFAULT_HEATMAP_RESOLUTION_MILES,
    fetch_weather_batch,
    generate_heatmap,
    save_observations,
)

logger = logging.getLogger(__name__)


def _enqueue_risk_assessment(checkpoint_ids) -> None:
    """Queue F05 risk assessments; failures never fail the weather fetch."""
    if "apps.risk" not in settings.INSTALLED_APPS:
        return
    try:
        from apps.risk.tasks import calculate_risk_for_checkpoint

        for checkpoint_id in checkpoint_ids:
            calculate_risk_for_checkpoint.delay(str(checkpoint_id))
    except Exception as exc:
        # Eager runs surface calculation errors here; weather is already stored.
        logger.warning("Risk assessment enqueue failed: %s", exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def fetch_weather_for_checkpoints(self, checkpoint_ids: list[str]) -> dict:
    """Fetch and store forecasts for the given checkpoints (F04).

    Retry policy (docs/SERVICES/weather/SERVICE_SPEC.md):
    * ``WeatherProviderError`` / ``WeatherRateLimitError`` when every
      location bucket failed - retried up to ``max_retries`` with the
      60s default delay.
    * Partial failures and missing forecast hours - successful buckets are
      stored and the task completes without retrying.
    """
    checkpoints = list(Checkpoint.objects.filter(id__in=checkpoint_ids))
    if not checkpoints:
        logger.warning("No checkpoints found for weather fetch: %s", checkpoint_ids)
        return {"checkpoints": 0, "observations": 0, "saved": 0}

    try:
        results = fetch_weather_batch(checkpoints)
    except (WeatherProviderError, WeatherRateLimitError) as exc:
        if self.request.retries >= self.max_retries:
            raise
        # Stays unmarked while Celery schedules the retry.
        raise self.retry(exc=exc) from exc

    saved = save_observations(results)

    # Step 4 (F05): queue risk assessment for every checkpoint that just
    # received a stored observation.
    _enqueue_risk_assessment(list(results))

    logger.info(
        "Weather fetch for request checkpoints: %d/%d stored",
        saved,
        len(checkpoints),
    )
    return {
        "checkpoints": len(checkpoints),
        "observations": len(results),
        "saved": saved,
    }


@celery_app.task
def generate_heatmap_task(
    route_id: str, hour: int, resolution_miles: float = DEFAULT_HEATMAP_RESOLUTION_MILES
) -> dict:
    """Pre-compute and cache one heatmap grid (F08).

    Used to warm the HeatmapCache ahead of the slider; the endpoint
    generates on demand whenever the cache misses or has expired.
    """
    route = Route.objects.filter(id=route_id).first()
    if route is None:
        logger.warning("No route found for heatmap generation: %s", route_id)
        return {"route": str(route_id), "hour": hour, "generated": False}

    result = generate_heatmap(route, forecast_hour=hour, resolution_miles=resolution_miles)
    logger.info("Heatmap generated for route %s at hour %s", route_id, hour)
    return {
        "route": str(route_id),
        "hour": hour,
        "generated": True,
        "points": len(result["grid"]),
    }
