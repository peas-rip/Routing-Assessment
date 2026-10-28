"""Routing models (docs/DATABASE_SCHEMA.md tables 1-3).

Additive deviations from the SQL schema (documented in the field docstrings):

* ``RouteRequest.checkpoint_interval_miles`` - F03 lets users pick the
  sampling interval (10/25/50, default 25) at generation time.
* ``RouteRequest.progress`` - F02 polling contract reports progress
  (0 -> 30 routing -> 60 checkpoints -> 90 weather queue -> 100).
"""

import uuid

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.postgres.indexes import GistIndex

from common.validators import validate_load_weight_lbs

from .managers import CheckpointManager, RouteManager

DEFAULT_CHECKPOINT_INTERVAL = 25
CHECKPOINT_INTERVAL_CHOICES = [(10, "10 miles"), (25, "25 miles"), (50, "50 miles")]


class RouteRequest(models.Model):
    """Tracks one async route generation request."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    origin_address = models.TextField()
    origin_lat = models.FloatField()
    origin_lon = models.FloatField()
    destination_address = models.TextField()
    destination_lat = models.FloatField()
    destination_lon = models.FloatField()
    departure_time = models.DateTimeField()
    load_weight_lbs = models.PositiveIntegerField(validators=[validate_load_weight_lbs])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Additive columns (see module docstring).
    checkpoint_interval_miles = models.PositiveSmallIntegerField(
        choices=CHECKPOINT_INTERVAL_CHOICES,
        default=DEFAULT_CHECKPOINT_INTERVAL,
    )
    progress = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["status"], name="idx_route_requests_status"),
            models.Index(fields=["-created_at"], name="idx_route_requests_created"),
        ]

    def __str__(self):
        return f"{self.origin_address} -> {self.destination_address} [{self.status}]"

    @property
    def origin_point(self) -> Point:
        """Origin as a WGS84 GEOS point (lon, lat) for the routing client."""
        return Point(self.origin_lon, self.origin_lat, srid=4326)

    @property
    def destination_point(self) -> Point:
        """Destination as a WGS84 GEOS point (lon, lat)."""
        return Point(self.destination_lon, self.destination_lat, srid=4326)


class Route(models.Model):
    """One generated route option (geometry, distance, duration, metadata)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(RouteRequest, on_delete=models.CASCADE, related_name="routes")
    route_index = models.IntegerField(choices=[(0, 0), (1, 1), (2, 2)])
    name = models.CharField(max_length=100, blank=True)
    distance_miles = models.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = models.PositiveIntegerField()
    geometry = models.LineStringField(srid=4326)  # PostGIS
    summary = models.JSONField()
    is_recommended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RouteManager()

    class Meta:
        indexes = [
            GistIndex(fields=["geometry"], name="idx_routes_geometry"),
        ]

    def __str__(self):
        label = self.name or "Route"
        return f"{label} #{self.route_index} ({self.distance_miles} mi)"


class Checkpoint(models.Model):
    """Weather sampling point along a route (origin, interval, destination)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="checkpoints")
    sequence = models.PositiveIntegerField()
    mile_marker = models.DecimalField(max_digits=10, decimal_places=2)
    latitude = models.FloatField()
    longitude = models.FloatField()
    location = models.PointField(srid=4326, geography=True)
    estimated_arrival = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CheckpointManager()

    class Meta:
        ordering = ["sequence"]
        indexes = [
            models.Index(fields=["route", "sequence"], name="idx_checkpoints_route_seq"),
            models.Index(fields=["estimated_arrival"], name="idx_checkpoints_arrival"),
        ]

    def __str__(self):
        return f"cp seq={self.sequence} mi={self.mile_marker}"
