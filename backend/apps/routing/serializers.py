"""Routing serializers (docs/API_CONTRACTS.md routing section)."""

import json
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from common.validators import (
    validate_latitude,
    validate_load_weight_lbs,
    validate_longitude,
)

from .models import Route, RouteRequest
from .services import resolve_interval


class TimezoneAwareDateTimeField(serializers.DateTimeField):
    """Rejects naive datetimes instead of silently assuming the server TZ."""

    def enforce_timezone(self, value):
        if timezone.is_naive(value):
            raise serializers.ValidationError("Departure time must include a timezone offset.")
        return super().enforce_timezone(value)


class CoordinateSerializer(serializers.Serializer):
    """A geocoded location (address + coordinates) for origin/destination."""

    address = serializers.CharField(max_length=500)
    latitude = serializers.FloatField(validators=[validate_latitude])
    longitude = serializers.FloatField(validators=[validate_longitude])


class GenerateRouteRequestSerializer(serializers.Serializer):
    """Validates POST /api/v1/routes/generate/ (F01/F02 validation rules)."""

    origin = CoordinateSerializer()
    destination = CoordinateSerializer()
    departure_time = TimezoneAwareDateTimeField()
    load_weight_lbs = serializers.IntegerField(validators=[validate_load_weight_lbs])
    checkpoint_interval_miles = serializers.IntegerField(required=False)

    def validate_departure_time(self, value):
        now = timezone.now()
        if value < now:
            raise serializers.ValidationError("Departure time cannot be in the past.")
        if value > now + timedelta(hours=48):
            raise serializers.ValidationError("Departure time must be within 48 hours.")
        return value

    def validate_checkpoint_interval_miles(self, value):
        # F03: anything outside (10, 25, 50) falls back to 25 with a warning.
        return resolve_interval(value)

    def validate(self, attrs):
        origin = attrs["origin"]
        destination = attrs["destination"]
        if (
            origin["latitude"] == destination["latitude"]
            and origin["longitude"] == destination["longitude"]
        ):
            raise serializers.ValidationError("Origin and destination must be different locations.")
        return attrs


class CheckpointSerializer(serializers.Serializer):
    """Checkpoint payload for route/status responses (contract order)."""

    id = serializers.UUIDField()
    sequence = serializers.IntegerField()
    mile_marker = serializers.DecimalField(max_digits=10, decimal_places=2)
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    estimated_arrival = serializers.DateTimeField()


class RouteSerializer(serializers.Serializer):
    """One route option with checkpoints (contract fields)."""

    id = serializers.UUIDField()
    route_index = serializers.IntegerField()
    name = serializers.CharField()
    distance_miles = serializers.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = serializers.IntegerField()
    geometry = serializers.SerializerMethodField()
    summary = serializers.JSONField()
    checkpoints = CheckpointSerializer(many=True, source="checkpoints.ordered")

    def get_geometry(self, route: Route) -> dict:
        """GeoJSON LineString as rendered on the map (WGS84)."""
        return json.loads(route.geometry.json)


class RouteRequestStatusSerializer(serializers.Serializer):
    """GET /api/v1/routes/{task_id}/ while pending/processing."""

    task_id = serializers.UUIDField(source="id")
    status = serializers.CharField()
    progress = serializers.IntegerField()
    message = serializers.SerializerMethodField()

    def get_message(self, route_request: RouteRequest) -> str:
        if route_request.status == RouteRequest.Status.PENDING:
            return "Queued for route generation."
        progress = route_request.progress
        if progress <= 30:
            return "Generating route options."
        if progress <= 60:
            return "Sampling checkpoints along the routes."
        if progress <= 90:
            return "Fetching weather forecasts."
        return "Finalizing results."


class RouteRequestCompletedSerializer(serializers.Serializer):
    """GET /api/v1/routes/{task_id}/ once generation completed."""

    request_id = serializers.UUIDField(source="id")
    status = serializers.CharField()
    routes = RouteSerializer(many=True, source="routes.ordered")
    origin = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()
    departure_time = serializers.DateTimeField()
    load_weight_lbs = serializers.IntegerField()

    def _location(self, route_request: RouteRequest, prefix: str) -> dict:
        return {
            "address": getattr(route_request, f"{prefix}_address"),
            "latitude": getattr(route_request, f"{prefix}_lat"),
            "longitude": getattr(route_request, f"{prefix}_lon"),
        }

    def get_origin(self, route_request: RouteRequest) -> dict:
        return self._location(route_request, "origin")

    def get_destination(self, route_request: RouteRequest) -> dict:
        return self._location(route_request, "destination")
