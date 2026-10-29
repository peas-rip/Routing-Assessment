from unittest.mock import patch

import responses
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.geocoding.exceptions import GeocodingProviderError, RateLimitError
from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError


class HealthCheckTests(APITestCase):
    def setUp(self):
        self.url = reverse("health")

    def test_healthy_response_contract(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["checks"]["database"], "ok")
        self.assertEqual(body["checks"]["redis"], "ok")
        self.assertEqual(body["checks"]["nominatim"], "not_configured")
        self.assertIn("version", body)
        self.assertIn("timestamp", body)

    def test_nominatim_not_configured_when_probe_disabled(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["nominatim"], "not_configured")

    @override_settings(NOMINATIM_HEALTHCHECK_ENABLED=True)
    @responses.activate
    def test_nominatim_ok_when_enabled(self):
        responses.add(
            responses.GET,
            "https://nominatim.openstreetmap.org/search",
            json=[{"place_id": 1, "display_name": "x", "lat": "39.78", "lon": "-89.65"}],
            status=200,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["nominatim"], "ok")

    @override_settings(NOMINATIM_HEALTHCHECK_ENABLED=True)
    def test_nominatim_error_marks_degraded(self):
        with patch(
            "apps.geocoding.clients.nominatim.GeocodingClient.search",
            side_effect=GeocodingProviderError(),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["checks"]["nominatim"], "error")

    @override_settings(NOMINATIM_HEALTHCHECK_ENABLED=True)
    def test_nominatim_rate_limit_is_non_fatal(self):
        with patch(
            "apps.geocoding.clients.nominatim.GeocodingClient.search",
            side_effect=RateLimitError(60),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["nominatim"], "rate_limited")

    def test_openmeteo_not_configured_when_probe_disabled(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["openmeteo"], "not_configured")

    @override_settings(OPEN_METEO_HEALTHCHECK_ENABLED=True)
    @responses.activate
    def test_openmeteo_ok_when_enabled(self):
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json={
                "hourly": {
                    "time": ["2023-12-27T08:00"],
                    "temperature_2m": [45.0],
                    "relative_humidity_2m": [65],
                    "wind_speed_10m": [10.0],
                    "wind_direction_10m": [200],
                    "wind_gusts_10m": [None],
                    "rain": [0],
                    "snowfall": [0],
                    "weather_code": [0],
                }
            },
            status=200,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["openmeteo"], "ok")

    @override_settings(OPEN_METEO_HEALTHCHECK_ENABLED=True)
    def test_openmeteo_error_marks_degraded(self):
        with patch(
            "apps.weather.clients.openmeteo.WeatherClient.fetch_hourly",
            side_effect=WeatherProviderError(),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["checks"]["openmeteo"], "error")

    @override_settings(OPEN_METEO_HEALTHCHECK_ENABLED=True)
    def test_openmeteo_rate_limit_is_non_fatal(self):
        with patch(
            "apps.weather.clients.openmeteo.WeatherClient.fetch_hourly",
            side_effect=WeatherRateLimitError(60),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["openmeteo"], "rate_limited")

    def test_database_failure_marks_degraded(self):
        with patch("common.health.connection.ensure_connection", side_effect=Exception("down")):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["checks"]["database"], "error")

    def test_redis_failure_marks_degraded(self):
        with patch("django.core.cache.cache.set", side_effect=Exception("down")):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["checks"]["redis"], "error")
