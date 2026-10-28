from unittest.mock import patch

import responses
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.geocoding.exceptions import GeocodingProviderError, RateLimitError
from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError

OWM_ONECALL_URL = "https://api.openweathermap.org/data/3.0/onecall"


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
        self.assertEqual(body["checks"]["openrouteservice"], "not_configured")
        self.assertIn("version", body)
        self.assertIn("timestamp", body)

    @override_settings(OPENROUTESERVICE_API_KEY="test-key")
    @responses.activate
    def test_openrouteservice_ok_when_configured(self):
        responses.add(
            responses.GET,
            "https://api.openrouteservice.org/geocode/search",
            json={"features": []},
            status=200,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["openrouteservice"], "ok")

    @override_settings(OPENROUTESERVICE_API_KEY="test-key")
    def test_openrouteservice_error_marks_degraded(self):
        with patch(
            "apps.geocoding.clients.openrouteservice.GeocodingClient.search",
            side_effect=GeocodingProviderError(),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["checks"]["openrouteservice"], "error")

    @override_settings(OPENROUTESERVICE_API_KEY="test-key")
    def test_openrouteservice_rate_limit_is_non_fatal(self):
        with patch(
            "apps.geocoding.clients.openrouteservice.GeocodingClient.search",
            side_effect=RateLimitError(60),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["openrouteservice"], "rate_limited")

    def test_openweathermap_not_configured_without_key(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["openweathermap"], "not_configured")

    @override_settings(OPENWEATHERMAP_API_KEY="test-key")
    @responses.activate
    def test_openweathermap_ok_when_configured(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json={"hourly": []}, status=200)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["openweathermap"], "ok")

    @override_settings(OPENWEATHERMAP_API_KEY="test-key")
    def test_openweathermap_error_marks_degraded(self):
        with patch(
            "apps.weather.clients.openweathermap.WeatherClient.fetch_hourly",
            side_effect=WeatherProviderError(),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["checks"]["openweathermap"], "error")

    @override_settings(OPENWEATHERMAP_API_KEY="test-key")
    def test_openweathermap_rate_limit_is_non_fatal(self):
        with patch(
            "apps.weather.clients.openweathermap.WeatherClient.fetch_hourly",
            side_effect=WeatherRateLimitError(60),
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["checks"]["openweathermap"], "rate_limited")

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
