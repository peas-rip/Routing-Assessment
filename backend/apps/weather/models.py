"""Weather models (docs/DATABASE_SCHEMA.md tables 4 and 8).

Additive detail vs the SQL schema (documented in the field docstrings):
none. ``HeatmapCache`` ships in Step 3 as schema only; grid generation and
``GET /weather/heatmap/`` arrive with the risk rules in Step 4
(docs/IMPLEMENTATION_ORDER.md).
"""

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .managers import WeatherObservationManager


class PrecipType(models.TextChoices):
    """Precipitation classification stored per observation (F04)."""

    RAIN = "rain", "Rain"
    SNOW = "snow", "Snow"
    NONE = "none", "None"
    MIXED = "mixed", "Mixed"


class WeatherObservation(models.Model):
    """Weather for one checkpoint at its forecast (arrival) time."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checkpoint = models.ForeignKey(
        "routing.Checkpoint",
        on_delete=models.CASCADE,
        related_name="weather_observations",
    )
    forecast_time = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)

    # Wind
    wind_speed_mph = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    wind_direction_deg = models.IntegerField(null=True, blank=True)
    wind_gust_mph = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Precipitation
    precipitation_rate_in_hr = models.DecimalField(
        max_digits=5, decimal_places=3, null=True, blank=True
    )
    precipitation_type = models.CharField(max_length=20, choices=PrecipType.choices)
    snowfall_rate_in_hr = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    snow_depth_in = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # General
    temperature_f = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    humidity_pct = models.IntegerField(null=True, blank=True)
    visibility_mi = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    conditions = models.CharField(max_length=100, blank=True)

    raw_response = models.JSONField()
    source = models.CharField(max_length=50, default="openweathermap")

    objects = WeatherObservationManager()

    class Meta:
        indexes = [
            models.Index(
                fields=["checkpoint", "forecast_time"], name="idx_weather_checkpoint_time"
            ),
            models.Index(fields=["fetched_at"], name="idx_weather_fetched_at"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["checkpoint", "forecast_time", "source"],
                name="unique_weather_obs",
            ),
        ]

    def __str__(self):
        return (
            f"weather cp={self.checkpoint_id} at {self.forecast_time:%Y-%m-%d %H:%M} "
            f"({self.precipitation_type})"
        )


class HeatmapCache(models.Model):
    """Pre-computed weather heatmap grid for a route + forecast hour (F08).

    Written by the Step 4 heatmap generator; the 0-48 range is enforced by
    validators here and by the CHECK constraint in docs/DATABASE_SCHEMA.md.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.ForeignKey(
        "routing.Route",
        on_delete=models.CASCADE,
        related_name="heatmaps",
    )
    forecast_hour = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(48)])
    # [{"lat": ..., "lon": ..., "risk_level": ..., "risk_score": ...}]
    grid_data = models.JSONField()
    # {"north": ..., "south": ..., "east": ..., "west": ...}
    bounds = models.JSONField()
    resolution_miles = models.DecimalField(max_digits=5, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["route", "forecast_hour"], name="idx_heatmap_route_hour"),
            models.Index(fields=["expires_at"], name="idx_heatmap_expires"),
        ]

    def __str__(self):
        return f"heatmap route={self.route_id} hour={self.forecast_hour}"
