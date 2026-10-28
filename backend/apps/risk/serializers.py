"""Risk serializers (docs/API_CONTRACTS.md risk section)."""

from rest_framework import serializers

from .services import RISK_BREAKDOWN_ORDER

# POST /risk/calculate/ input rules (docs/API_CONTRACTS.md risk section):
# load within the legal 10,000-80,000 lbs band and one of the three
# supported checkpoint sampling intervals. The interval documents how the
# route's checkpoints were sampled; risk segments come from the stored
# checkpoints themselves.
LOAD_WEIGHT_MIN_LBS = 10_000
LOAD_WEIGHT_MAX_LBS = 80_000
CHECKPOINT_INTERVAL_CHOICES = [10, 25, 50]


class RiskCalculateSerializer(serializers.Serializer):
    """Validates POST /api/v1/risk/calculate/ (F05)."""

    route_id = serializers.UUIDField()
    load_weight_lbs = serializers.IntegerField(
        min_value=LOAD_WEIGHT_MIN_LBS, max_value=LOAD_WEIGHT_MAX_LBS
    )
    checkpoint_interval_miles = serializers.ChoiceField(choices=CHECKPOINT_INTERVAL_CHOICES)


class CheckpointWeatherBriefSerializer(serializers.Serializer):
    """Weather block embedded in the calculate response (contract order)."""

    temperature_f = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    conditions = serializers.CharField()
    wind_speed_mph = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    wind_direction_deg = serializers.IntegerField(allow_null=True)
    precipitation_rate_in_hr = serializers.DecimalField(
        max_digits=5, decimal_places=3, allow_null=True
    )
    precipitation_type = serializers.CharField()


class CheckpointRiskFieldsSerializer(serializers.Serializer):
    """Risk breakdown block (contract field order)."""

    wind_risk = serializers.CharField()
    rain_risk = serializers.CharField()
    snow_risk = serializers.CharField()
    combined_risk = serializers.CharField()
    load_rule_applied = serializers.CharField(allow_null=True)
    segment_miles = serializers.DecimalField(max_digits=10, decimal_places=2)


class CheckpointRiskSerializer(serializers.Serializer):
    """Per-checkpoint payload of the calculate response (contract order).

    ``weather`` reads from the stored WeatherObservation and ``risk`` from
    the persisted RiskAssessment.
    """

    checkpoint_id = serializers.UUIDField()
    mile_marker = serializers.DecimalField(max_digits=10, decimal_places=2)
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    estimated_arrival = serializers.DateTimeField()
    weather = CheckpointWeatherBriefSerializer()
    risk = CheckpointRiskFieldsSerializer()


class RouteScoreSerializer(serializers.Serializer):
    """Persisted route score block (contract field order)."""

    severe_miles = serializers.DecimalField(max_digits=10, decimal_places=2)
    high_miles = serializers.DecimalField(max_digits=10, decimal_places=2)
    average_risk_score = serializers.DecimalField(max_digits=5, decimal_places=3)
    duration_minutes = serializers.IntegerField()
    composite_score = serializers.DecimalField(max_digits=10, decimal_places=3)
    risk_breakdown = serializers.DictField(child=serializers.FloatField())

    def to_representation(self, instance):
        """Emit risk_breakdown in the documented key order.

        PostgreSQL's jsonb does not preserve insertion order, so the stored
        mapping must be re-sorted to match the contract example.
        """
        ret = super().to_representation(instance)
        breakdown = ret.get("risk_breakdown") or {}
        ordered = {level: breakdown[level] for level in RISK_BREAKDOWN_ORDER if level in breakdown}
        ordered.update({key: value for key, value in breakdown.items() if key not in ordered})
        ret["risk_breakdown"] = ordered
        return ret


class RecommendedRouteSerializer(serializers.Serializer):
    """One scored route inside the recommendation response (contract order)."""

    route_id = serializers.UUIDField()
    name = serializers.CharField()
    distance_miles = serializers.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = serializers.IntegerField()
    score = RouteScoreSerializer()
    is_recommended = serializers.BooleanField()
