"""Reusable input validators for shared primitives (coordinates, weights)."""

from django.core.exceptions import ValidationError


def validate_latitude(value):
    if not -90.0 <= value <= 90.0:
        raise ValidationError("Latitude must be between -90 and 90.")


def validate_longitude(value):
    if not -180.0 <= value <= 180.0:
        raise ValidationError("Longitude must be between -180 and 180.")


def validate_coordinates(latitude, longitude):
    """Validate a (latitude, longitude) pair. Raises django ValidationError."""
    validate_latitude(latitude)
    validate_longitude(longitude)


def validate_load_weight_lbs(value):
    if value <= 0:
        raise ValidationError("Load weight must be greater than zero.")
    if value > 80_000:
        raise ValidationError("Load weight exceeds the legal limit of 80,000 lbs.")
