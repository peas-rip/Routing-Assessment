"""Weather model constraints and behavior (docs/DATABASE_SCHEMA.md tables 4, 8)."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.routing.tests.fixtures import make_route
from apps.weather.models import HeatmapCache, PrecipType, WeatherObservation

from .fixtures import make_checkpoint, make_observation


class WeatherObservationModelTests(TestCase):
    def test_str_and_reverse_relation(self):
        checkpoint = make_checkpoint()
        observation = make_observation(checkpoint)

        self.assertIn("weather cp=", str(observation))
        self.assertIn("rain", str(observation))
        self.assertEqual(list(checkpoint.weather_observations.all()), [observation])

    def test_unique_per_checkpoint_forecast_time_and_source(self):
        checkpoint = make_checkpoint()
        make_observation(checkpoint)

        with self.assertRaises(IntegrityError), transaction.atomic():
            make_observation(checkpoint)

    def test_precipitation_type_choices_enforced(self):
        checkpoint = make_checkpoint()
        observation = WeatherObservation(
            checkpoint=checkpoint,
            forecast_time=checkpoint.estimated_arrival,
            precipitation_type="sleet",
            raw_response={},
        )

        with self.assertRaises(ValidationError):
            observation.full_clean()

    def test_valid_precipitation_types_pass_full_clean(self):
        checkpoint = make_checkpoint()
        for precip_type in PrecipType:
            observation = WeatherObservation(
                checkpoint=checkpoint,
                forecast_time=checkpoint.estimated_arrival,
                precipitation_type=precip_type.value,
                raw_response={"hourly": []},  # JSONField rejects {} as blank
            )
            observation.full_clean()  # no exception


class HeatmapCacheModelTests(TestCase):
    def make_heatmap(self, route, forecast_hour: int = 6) -> HeatmapCache:
        return HeatmapCache(
            route=route,
            forecast_hour=forecast_hour,
            grid_data=[{"lat": 39.78, "lon": -89.65, "risk_level": "low", "risk_score": 1.0}],
            bounds={"north": 42.0, "south": 39.5, "east": -87.0, "west": -90.0},
            resolution_miles=Decimal("10.00"),
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    def test_heatmap_cache_str_and_reverse_relation(self):
        route = make_route()
        heatmap = self.make_heatmap(route)
        heatmap.save()

        self.assertIn("hour=6", str(heatmap))
        self.assertEqual(list(route.heatmaps.all()), [heatmap])

    def test_forecast_hour_accepts_slider_range(self):
        route = make_route()
        for hour in (0, 6, 48):
            self.make_heatmap(route, forecast_hour=hour).full_clean()

    def test_forecast_hour_rejects_out_of_range_values(self):
        route = make_route()
        for hour in (-1, 49):
            with self.assertRaises(ValidationError):
                self.make_heatmap(route, forecast_hour=hour).full_clean()
