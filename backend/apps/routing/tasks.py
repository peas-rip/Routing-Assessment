"""Celery tasks for the routing service."""

import logging

from django.conf import settings
from django.utils import timezone

from config.celery import app as celery_app

from .exceptions import NoRouteFoundError, RoutingError, RoutingProviderError
from .models import Checkpoint, RouteRequest
from .services import generate_routes

logger = logging.getLogger(__name__)


def _mark_failed(route_request: RouteRequest, message: str) -> None:
    route_request.status = RouteRequest.Status.FAILED
    route_request.error_message = message
    route_request.save(update_fields=["status", "error_message", "updated_at"])


def _enqueue_weather_fetch(route_request: RouteRequest, checkpoint_ids: list) -> None:
    """Queue the F04 weather fetch; failures never fail route generation."""
    if "apps.weather" not in settings.INSTALLED_APPS:
        return
    # When Celery runs tasks eagerly (e.g. free-tier demos without a
    # worker), running the bulk weather fetch inline would block the
    # request for tens of seconds and overwhelm the worker. Rely on the
    # on-demand fetch in /weather/checkpoints/ and /risk/calculate/ instead.
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return
    try:
        from apps.weather.tasks import fetch_weather_for_checkpoints

        fetch_weather_for_checkpoints.delay([str(pk) for pk in checkpoint_ids])
    except Exception as exc:
        # Eager runs surface provider errors here; the route is already done.
        logger.warning("Weather fetch enqueue failed for request %s: %s", route_request.id, exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def generate_routes_task(self, request_id: str) -> dict:
    """Generate routes + checkpoints for one RouteRequest.

    Retry policy (docs/SERVICES/routing/TESTING.md):
    * ``RoutingProviderError`` - transient provider failure: retried up to
      ``max_retries``; the request stays ``processing`` until retries exhaust,
      then it is marked ``failed``.
    * ``NoRouteFoundError`` and every other error - fails immediately,
      no retry.
    """
    route_request = RouteRequest.objects.get(id=request_id)
    route_request.status = RouteRequest.Status.PROCESSING
    route_request.error_message = None
    route_request.save(update_fields=["status", "error_message", "updated_at"])

    try:
        routes = generate_routes(route_request)
    except NoRouteFoundError as exc:
        _mark_failed(route_request, str(exc))
        raise
    except RoutingProviderError as exc:
        if self.request.retries >= self.max_retries:
            _mark_failed(route_request, str(exc))
            raise
        # Stays in `processing` while Celery schedules the retry.
        raise self.retry(exc=exc) from exc
    except RoutingError as exc:
        _mark_failed(route_request, str(exc))
        raise
    except Exception as exc:
        logger.exception("Unexpected route generation failure for request %s", request_id)
        _mark_failed(route_request, str(exc))
        raise

    # Step 3: queue weather forecasts for the new checkpoints (F04) and
    # advance progress through the documented 90 milestone.
    checkpoint_ids = list(
        Checkpoint.objects.filter(route__request=route_request).values_list("id", flat=True)
    )
    if checkpoint_ids:
        route_request.progress = 90
        route_request.save(update_fields=["progress", "updated_at"])
        _enqueue_weather_fetch(route_request, checkpoint_ids)

    route_request.status = RouteRequest.Status.COMPLETED
    route_request.progress = 100
    route_request.completed_at = timezone.now()
    route_request.save(
        update_fields=["status", "progress", "completed_at", "updated_at"],
    )
    logger.info("Route generation completed for request %s (%d routes)", request_id, len(routes))
    return {"request_id": str(request_id), "status": "completed", "routes": len(routes)}
