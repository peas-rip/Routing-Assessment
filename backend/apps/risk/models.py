"""Risk models (docs/DATABASE_SCHEMA.md tables 5-6).

Additive detail vs the SQL schema (documented in the field docstrings):
``RouteScore.route`` is a OneToOneField so the DDL's
``CREATE UNIQUE INDEX idx_route_scores_route`` is realised by Django's
unique constraint (and gives the documented ``route.score`` accessor).
``RiskAssessment`` keeps plain FKs; its documented 1:1 relationship with
``Checkpoint`` is enforced application-side via ``update_or_create`` (the
DDL has no UNIQUE constraint on ``checkpoint_id``).
"""

import uuid

from django.db import models


class RiskAssessment(models.Model):
    """Per-checkpoint weather risk breakdown (F05). One row per checkpoint."""

    RISK_LEVEL_CHOICES = [
        ("low", "Low"),
        ("moderate", "Moderate"),
        ("high", "High"),
        ("severe", "Severe"),
        ("no_travel", "No Travel"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checkpoint = models.ForeignKey(
        "routing.Checkpoint",
        on_delete=models.CASCADE,
        related_name="risk_assessments",
    )
    weather_observation = models.ForeignKey(
        "weather.WeatherObservation",
        on_delete=models.CASCADE,
        related_name="risk_assessments",
    )
    load_weight_lbs = models.PositiveIntegerField()

    # Individual condition risks.
    wind_risk = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES)
    rain_risk = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES)
    snow_risk = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES)
    # Combined risk (highest of the three, with load escalation).
    combined_risk = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES)
    # Load rule flag, e.g. 'wind_45_54_over_30k' (null when no rule fired).
    load_rule_applied = models.CharField(max_length=50, null=True, blank=True)
    # Miles this checkpoint represents (weighting for route scoring).
    segment_miles = models.DecimalField(max_digits=10, decimal_places=2)
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["checkpoint"], name="idx_risk_checkpoint"),
            models.Index(fields=["combined_risk"], name="idx_risk_combined"),
        ]

    def __str__(self):
        return f"risk checkpoint={self.checkpoint_id} [{self.combined_risk}]"


class RouteScore(models.Model):
    """Aggregated route score for recommendation (F06). One row per route."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.OneToOneField(
        "routing.Route",
        on_delete=models.CASCADE,
        related_name="score",
    )
    # Priority 1: fewest Severe + No Travel miles.
    severe_miles = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Priority 2: fewest High miles.
    high_miles = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Priority 3: lowest average risk (weighted, low=1.0 .. no_travel=5.0).
    average_risk_score = models.DecimalField(max_digits=5, decimal_places=3)
    # Priority 4: shortest travel time.
    duration_minutes = models.PositiveIntegerField()
    # Lexicographic encoding of the four priorities (lower is better).
    composite_score = models.DecimalField(max_digits=10, decimal_places=3)
    # {"low": mi, "moderate": mi, "high": mi, "severe": mi, "no_travel": mi}.
    risk_breakdown = models.JSONField()
    calculated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"score route={self.route_id} composite={self.composite_score}"
