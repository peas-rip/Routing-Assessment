from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from common.validators import (
    validate_coordinates,
    validate_latitude,
    validate_load_weight_lbs,
    validate_longitude,
)


class CoordinateValidatorTests(SimpleTestCase):
    def test_latitude_accepts_boundaries(self):
        validate_latitude(-90.0)
        validate_latitude(0.0)
        validate_latitude(90.0)

    def test_latitude_rejects_out_of_range(self):
        for value in (-90.1, 90.1, 100.0):
            with self.assertRaises(ValidationError):
                validate_latitude(value)

    def test_longitude_accepts_boundaries(self):
        validate_longitude(-180.0)
        validate_longitude(0.0)
        validate_longitude(180.0)

    def test_longitude_rejects_out_of_range(self):
        for value in (-180.1, 180.1, -200.0):
            with self.assertRaises(ValidationError):
                validate_longitude(value)

    def test_validate_coordinates_accepts_valid_pair(self):
        validate_coordinates(39.7817, -89.6501)

    def test_validate_coordinates_rejects_invalid_pair(self):
        with self.assertRaises(ValidationError):
            validate_coordinates(91.0, -89.6501)


class LoadWeightValidatorTests(SimpleTestCase):
    def test_accepts_valid_weights(self):
        validate_load_weight_lbs(1)
        validate_load_weight_lbs(45_000)
        validate_load_weight_lbs(80_000)

    def test_rejects_zero_and_negative(self):
        for value in (0, -1):
            with self.assertRaises(ValidationError):
                validate_load_weight_lbs(value)

    def test_rejects_over_legal_limit(self):
        with self.assertRaises(ValidationError):
            validate_load_weight_lbs(80_001)
