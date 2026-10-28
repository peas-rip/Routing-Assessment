from rest_framework import serializers


class SearchQuerySerializer(serializers.Serializer):
    """Validates GET /geocoding/search/ query parameters."""

    q = serializers.CharField(min_length=2, max_length=200)
    limit = serializers.IntegerField(default=5, min_value=1, max_value=10, required=False)
    lat = serializers.FloatField(min_value=-90.0, max_value=90.0, required=False, allow_null=True)
    lon = serializers.FloatField(min_value=-180.0, max_value=180.0, required=False, allow_null=True)

    def validate(self, attrs):
        lat = attrs.get("lat")
        lon = attrs.get("lon")
        if (lat is None) != (lon is None):
            raise serializers.ValidationError("lat and lon must be provided together.")
        return attrs


class ReverseQuerySerializer(serializers.Serializer):
    """Validates GET /geocoding/reverse/ query parameters."""

    lat = serializers.FloatField(min_value=-90.0, max_value=90.0)
    lon = serializers.FloatField(min_value=-180.0, max_value=180.0)


class AddressSerializer(serializers.Serializer):
    house_number = serializers.CharField(required=False, allow_null=True)
    road = serializers.CharField(required=False, allow_null=True)
    city = serializers.CharField(required=False, allow_null=True)
    state = serializers.CharField(required=False, allow_null=True)
    postcode = serializers.CharField(required=False, allow_null=True)
    country = serializers.CharField(required=False, allow_null=True)


class GeocodeResultSerializer(serializers.Serializer):
    """Response shape for a single geocoding result (docs/API_CONTRACTS.md)."""

    place_id = serializers.CharField()
    display_name = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    address = AddressSerializer()
    type = serializers.CharField()
