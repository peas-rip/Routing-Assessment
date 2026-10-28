"""Weather serializers (docs/API_CONTRACTS.md weather section)."""

from uuid import UUID

from rest_framework import serializers


class CheckpointWeatherQuerySerializer(serializers.Serializer):
    """Validates GET /api/v1/weather/checkpoints/ query parameters."""

    checkpoint_ids = serializers.CharField()
    forecast_time = serializers.DateTimeField(required=False)

    def validate_checkpoint_ids(self, value):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            raise serializers.ValidationError("At least one checkpoint id is required.")
        seen: set[UUID] = set()
        checkpoint_ids: list[UUID] = []
        for part in parts:
            try:
                checkpoint_id = UUID(part)
            except ValueError as exc:
                raise serializers.ValidationError(f"Invalid checkpoint id: {part}.") from exc
            if checkpoint_id not in seen:
                seen.add(checkpoint_id)
                checkpoint_ids.append(checkpoint_id)
        return checkpoint_ids


class WeatherSerializer(serializers.Serializer):
    """Checkpoint weather payload (docs/API_CONTRACTS.md weather section)."""

    checkpoint_id = serializers.UUIDField()
    forecast_time = serializers.DateTimeField()
    temperature_f = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    conditions = serializers.CharField()
    wind_speed_mph = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    wind_direction_deg = serializers.IntegerField(allow_null=True)
    precipitation_rate_in_hr = serializers.DecimalField(
        max_digits=5, decimal_places=3, allow_null=True
    )
    precipitation_type = serializers.CharField()
    snowfall_rate_in_hr = serializers.DecimalField(max_digits=5, decimal_places=3, allow_null=True)
    humidity_pct = serializers.IntegerField(allow_null=True)
    visibility_mi = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)


class HeatmapQuerySerializer(serializers.Serializer):
    """Validates GET /api/v1/weather/heatmap/ query parameters (F08)."""

    route_id = serializers.UUIDField()
    hour = serializers.IntegerField(min_value=0, max_value=48)
    resolution_miles = serializers.FloatField(required=False, min_value=5.0, max_value=50.0)


class HeatmapPointSerializer(serializers.Serializer):
    """One heatmap grid point (docs/API_CONTRACTS.md weather section)."""

    lat = serializers.FloatField()
    lon = serializers.FloatField()
    risk_level = serializers.ChoiceField(choices=["low", "moderate", "high", "severe", "no_travel"])
    risk_score = serializers.FloatField()


class HeatmapBoundsSerializer(serializers.Serializer):
    """Geographic extent of the heatmap grid."""

    north = serializers.FloatField()
    south = serializers.FloatField()
    east = serializers.FloatField()
    west = serializers.FloatField()


class HeatmapSerializer(serializers.Serializer):
    """Heatmap payload (docs/API_CONTRACTS.md weather section)."""

    route_id = serializers.UUIDField()
    forecast_hour = serializers.IntegerField()
    bounds = HeatmapBoundsSerializer()
    resolution_miles = serializers.FloatField()
    grid = HeatmapPointSerializer(many=True)
    generated_at = serializers.DateTimeField()
