"""Celery tasks for the risk service.

Risk is pure DB computation over stored rows, so tasks never retry: an
unexpected failure fails the task and the next call recomputes from scratch.
"""

import logging

from apps.routing.models import Checkpoint, Route
from config.celery import app as celery_app

from .services import assess_checkpoint, calculate_route_score, segment_miles_by_checkpoint

logger = logging.getLogger(__name__)


@celery_app.task
def calculate_risk_for_checkpoint(checkpoint_id: str) -> dict:
    """Assess and store risk for one checkpoint (F05).

    A checkpoint without stored weather is skipped (the weather fetch may
    still be running or may have failed); unknown ids are logged and skipped.
    """
    checkpoint = (
        Checkpoint.objects.select_related("route__request").filter(id=checkpoint_id).first()
    )
    if checkpoint is None:
        logger.warning("No checkpoint found for risk assessment: %s", checkpoint_id)
        return {"checkpoint": str(checkpoint_id), "assessed": False}

    weather = checkpoint.weather_observations.order_by("-forecast_time").first()
    if weather is None:
        logger.info("Checkpoint %s has not received weather yet; skipping", checkpoint_id)
        return {"checkpoint": str(checkpoint_id), "assessed": False}

    segments = segment_miles_by_checkpoint(checkpoint.route)
    assessment = assess_checkpoint(
        checkpoint,
        weather,
        checkpoint.route.request.load_weight_lbs,
        segments[checkpoint.id],
    )
    logger.info("Risk assessment for checkpoint %s: %s", checkpoint_id, assessment.combined_risk)
    return {
        "checkpoint": str(checkpoint_id),
        "assessed": True,
        "combined_risk": assessment.combined_risk,
    }


@celery_app.task
def score_route(route_id: str) -> dict:
    """Recompute and persist the F06 score for one route."""
    route = Route.objects.filter(id=route_id).first()
    if route is None:
        logger.warning("No route found for scoring: %s", route_id)
        return {"route": str(route_id), "scored": False}

    score = calculate_route_score(route)
    logger.info("Scored route %s: composite=%s", route_id, score.composite_score)
    return {
        "route": str(route_id),
        "scored": True,
        "composite_score": str(score.composite_score),
    }
