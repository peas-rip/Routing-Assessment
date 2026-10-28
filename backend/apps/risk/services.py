"""Risk calculation, route scoring and recommendation (F05/F06).

Pure computation over stored Routing + Weather rows - the risk service never
calls external APIs (docs/SERVICES/risk/SERVICE_SPEC.md).
"""

import logging
import uuid
from decimal import Decimal

from django.utils import timezone

from apps.routing.models import Route
from apps.weather.models import PrecipType, WeatherObservation

from .exceptions import InsufficientRiskDataError
from .models import RiskAssessment, RouteScore
from .rules import (
    RISK_SCORE_MAP,
    RiskLevel,
    apply_load_rules,
    classify_rain,
    classify_snow,
    classify_wind,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
ONE = Decimal("1")
AVERAGE_RISK_QUANTUM = Decimal("0.001")
COMPOSITE_QUANTUM = Decimal("0.001")
RISK_BREAKDOWN_ORDER = ("low", "moderate", "high", "severe", "no_travel")

# Composite score weights: each term is bounded so it cannot overflow into
# the next priority (docs/SERVICES/risk/TESTING.md property tests).
SEVERE_MILES_WEIGHT = Decimal("10000")
HIGH_MILES_WEIGHT = Decimal("100")
AVERAGE_RISK_WEIGHT = Decimal("10")
DURATION_WEIGHT = Decimal("1000")


def _decimal(value) -> Decimal:
    """Coerce a model/float value to Decimal (None counts as zero)."""
    return Decimal(str(value)) if value is not None else ZERO


def extract_precip_rates(weather: WeatherObservation) -> tuple[Decimal, Decimal]:
    """Split a stored observation into (rain_rate, snow_rate) in/hr.

    ``precipitation_rate_in_hr`` is the total rate and
    ``snowfall_rate_in_hr`` is its snow component: pure rain counts fully as
    rain, pure snow as snow, mixed splits ``total - snow`` off as rain, and
    ``none``/missing values count as zero.
    """
    total = _decimal(weather.precipitation_rate_in_hr)
    snow = _decimal(weather.snowfall_rate_in_hr)
    precip_type = weather.precipitation_type
    if precip_type == PrecipType.RAIN:
        return total, ZERO
    if precip_type == PrecipType.SNOW:
        return ZERO, snow if snow > ZERO else total
    if precip_type == PrecipType.MIXED:
        rain = total - snow
        return (rain if rain > ZERO else ZERO), snow
    return ZERO, ZERO


def assess_conditions(weather: WeatherObservation, load_lbs: int) -> dict[RiskLevel, ...]:
    """Individual + combined risk for one weather snapshot (F05).

    Combined risk starts as the highest of the three condition risks. Load
    rules apply only when the wind risk is High or worse and can only
    escalate - never lower - the combined level; rain/snow risk is never
    affected by the load.
    """
    rain_rate, snow_rate = extract_precip_rates(weather)
    wind_speed = _decimal(weather.wind_speed_mph)
    wind_risk = classify_wind(wind_speed)
    rain_risk = classify_rain(rain_rate)
    snow_risk = classify_snow(snow_rate)

    combined = max(wind_risk, rain_risk, snow_risk)
    load_rule = ""
    if wind_risk >= RiskLevel.HIGH:
        escalated, load_rule = apply_load_rules(wind_risk, wind_speed, load_lbs)
        combined = max(combined, escalated)

    return {
        "wind_risk": wind_risk,
        "rain_risk": rain_risk,
        "snow_risk": snow_risk,
        "combined_risk": combined,
        "load_rule_applied": load_rule or None,
    }


def calculate_checkpoint_risk(
    weather: WeatherObservation, load_lbs: int, segment_miles: Decimal
) -> RiskAssessment:
    """Build an (unsaved) RiskAssessment for one checkpoint (F05)."""
    risks = assess_conditions(weather, load_lbs)
    return RiskAssessment(
        weather_observation=weather,
        load_weight_lbs=load_lbs,
        wind_risk=risks["wind_risk"].value_label,
        rain_risk=risks["rain_risk"].value_label,
        snow_risk=risks["snow_risk"].value_label,
        combined_risk=risks["combined_risk"].value_label,
        load_rule_applied=risks["load_rule_applied"],
        segment_miles=segment_miles,
    )


def segment_miles_by_checkpoint(route: Route, checkpoints=None) -> dict[uuid.UUID, Decimal]:
    """Miles each checkpoint of ``route`` represents (F06 weighting).

    Segments run forward from each checkpoint (docs/API_CONTRACTS.md and
    FEATURE_05 edge case 8): a checkpoint covers the distance to the next
    one, and the destination checkpoint covers the remaining distance to
    the route's end - so from a mile-0 origin the segments always sum to
    ``route.distance_miles``. Regressing markers clamp at zero.
    """
    ordered = sorted(
        checkpoints if checkpoints is not None else route.checkpoints.all(),
        key=lambda checkpoint: checkpoint.sequence,
    )
    segments: dict[uuid.UUID, Decimal] = {}
    for index, checkpoint in enumerate(ordered):
        if index < len(ordered) - 1:
            segment = ordered[index + 1].mile_marker - checkpoint.mile_marker
        else:
            segment = route.distance_miles - checkpoint.mile_marker
        segments[checkpoint.id] = segment if segment > ZERO else ZERO
    return segments


def assess_checkpoint(
    checkpoint, weather: WeatherObservation, load_lbs: int, segment_miles: Decimal
) -> RiskAssessment:
    """Persist (upsert) the risk assessment for one checkpoint."""
    assessment = calculate_checkpoint_risk(weather, load_lbs, segment_miles)
    persisted, _created = RiskAssessment.objects.update_or_create(
        checkpoint=checkpoint,
        defaults={
            "weather_observation": assessment.weather_observation,
            "load_weight_lbs": assessment.load_weight_lbs,
            "wind_risk": assessment.wind_risk,
            "rain_risk": assessment.rain_risk,
            "snow_risk": assessment.snow_risk,
            "combined_risk": assessment.combined_risk,
            "load_rule_applied": assessment.load_rule_applied,
            "segment_miles": assessment.segment_miles,
            "calculated_at": timezone.now(),
        },
    )
    return persisted


def assess_route(route: Route, load_weight_lbs: int) -> list[RiskAssessment]:
    """Assess every checkpoint of a route that has stored weather (F05)."""
    checkpoints = list(route.checkpoints.all())
    segments = segment_miles_by_checkpoint(route, checkpoints)
    assessments = []
    for checkpoint in checkpoints:
        weather = checkpoint.weather_observations.order_by("-forecast_time").first()
        if weather is None:
            logger.info("Checkpoint %s has no weather yet; skipping risk", checkpoint.id)
            continue
        assessments.append(
            assess_checkpoint(checkpoint, weather, load_weight_lbs, segments[checkpoint.id])
        )
    return assessments


def calculate_route_score(route: Route) -> RouteScore:
    """Score a route with the F06 4-priority algorithm (upsert)."""
    breakdown: dict[str, Decimal] = {level: ZERO for level in RISK_BREAKDOWN_ORDER}
    assessments = RiskAssessment.objects.filter(checkpoint__route=route).values_list(
        "combined_risk", "segment_miles"
    )
    for combined_risk, segment_miles in assessments:
        breakdown[combined_risk] = breakdown.get(combined_risk, ZERO) + segment_miles

    # Priority 1: Severe + No Travel miles. Priority 2: High miles.
    severe_miles = breakdown["severe"] + breakdown["no_travel"]
    high_miles = breakdown["high"]

    # Priority 3: risk-score weighted average miles.
    total_miles = sum(breakdown.values(), ZERO)
    if total_miles == ZERO:
        average_risk = ONE
    else:
        weighted = sum(
            (
                RISK_SCORE_MAP[RiskLevel.from_value(level)] * miles
                for level, miles in breakdown.items()
            ),
            ZERO,
        )
        average_risk = weighted / total_miles
    average_risk = average_risk.quantize(AVERAGE_RISK_QUANTUM)

    # Priority 4: duration, encoded so no term overflows into the next.
    composite = (
        severe_miles * SEVERE_MILES_WEIGHT
        + high_miles * HIGH_MILES_WEIGHT
        + average_risk * AVERAGE_RISK_WEIGHT
        + _decimal(route.duration_minutes) / DURATION_WEIGHT
    ).quantize(COMPOSITE_QUANTUM)

    score, _ = RouteScore.objects.update_or_create(
        route=route,
        defaults={
            "severe_miles": severe_miles,
            "high_miles": high_miles,
            "average_risk_score": average_risk,
            "duration_minutes": route.duration_minutes,
            "composite_score": composite,
            "risk_breakdown": {level: float(miles) for level, miles in breakdown.items()},
        },
    )
    return score


def rank_routes(route: Route) -> tuple[list[tuple[Route, RouteScore]], uuid.UUID]:
    """Rank the request's assessed routes for recommendation (F06).

    Routes with persisted risk assessments but no score yet are scored
    lazily; a recommendation needs at least two of them, otherwise there is
    nothing to compare (docs/SERVICES/risk/SERVICE_SPEC.md).
    """
    routes = list(Route.objects.filter(request=route.request).order_by("route_index"))
    assessed_ids = set(
        RiskAssessment.objects.filter(checkpoint__route__in=routes).values_list(
            "checkpoint__route_id", flat=True
        )
    )
    eligible = [candidate for candidate in routes if candidate.id in assessed_ids]
    if len(eligible) < 2:
        raise InsufficientRiskDataError(
            "Insufficient route data: risk assessments are required for at least "
            "two routes before a recommendation can be made."
        )

    eligible_ids = [candidate.id for candidate in eligible]
    scored_ids = set(
        RouteScore.objects.filter(route_id__in=eligible_ids).values_list("route_id", flat=True)
    )
    for candidate in eligible:
        if candidate.id not in scored_ids:
            calculate_route_score(candidate)
    scores = {
        score.route_id: score for score in RouteScore.objects.filter(route_id__in=eligible_ids)
    }

    ranked = sorted(
        ((candidate, scores[candidate.id]) for candidate in eligible),
        key=lambda pair: pair[1].composite_score,
    )
    return ranked, ranked[0][0].id
