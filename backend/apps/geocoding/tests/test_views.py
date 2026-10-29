"""API contract tests for the geocoding endpoints (docs/API_CONTRACTS.md)."""

import responses
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.geocoding.models import GeocodeCache, QueryType

from .fixtures import MOCK_REVERSE_RESPONSE, MOCK_SEARCH_RESPONSE

SEARCH_URL = "https://nominatim.openstreetmap.org/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"


class GeocodingApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.search_url = reverse("geocoding:search")
        self.reverse_url = reverse("geocoding:reverse")

    def tearDown(self):
        cache.clear()

    @responses.activate
    def test_search_success_contract(self):
        responses.add(responses.GET, SEARCH_URL, json=MOCK_SEARCH_RESPONSE, status=200)

        response = self.client.get(self.search_url, {"q": "Springfield", "limit": 2})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("data", body)
        self.assertIn("meta", body)
        self.assertEqual(body["meta"]["cached"], False)
        self.assertEqual(len(body["data"]), 2)

        first = body["data"][0]
        self.assertEqual(
            set(first.keys()),
            {"place_id", "display_name", "latitude", "longitude", "address", "type"},
        )
        self.assertEqual(first["place_id"], "4726946")
        self.assertEqual(first["latitude"], 39.7817)
        self.assertEqual(first["longitude"], -89.6501)
        self.assertEqual(first["address"]["city"], "Springfield")
        self.assertEqual(first["address"]["state"], "IL")
        self.assertEqual(first["address"]["postcode"], "62701")
        self.assertEqual(first["type"], "house")

    @responses.activate
    def test_search_second_request_is_cached(self):
        responses.add(responses.GET, SEARCH_URL, json=MOCK_SEARCH_RESPONSE, status=200)

        self.client.get(self.search_url, {"q": "Springfield"})
        second_response = self.client.get(self.search_url, {"q": "Springfield"})

        self.assertEqual(second_response.json()["meta"]["cached"], True)
        self.assertEqual(len(responses.calls), 1)  # Provider hit only once

    @responses.activate
    def test_search_persists_db_cache_row(self):
        responses.add(responses.GET, SEARCH_URL, json=MOCK_SEARCH_RESPONSE, status=200)

        self.client.get(self.search_url, {"q": "Springfield"})

        self.assertTrue(
            GeocodeCache.objects.filter(
                query_text="springfield", query_type=QueryType.AUTOCOMPLETE
            ).exists()
        )

    def test_search_missing_query_returns_validation_error(self):
        response = self.client.get(self.search_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error = response.json()["error"]
        self.assertEqual(error["code"], "VALIDATION_ERROR")
        self.assertIn("fields", error["details"])

    def test_search_too_short_query_returns_validation_error(self):
        response = self.client.get(self.search_url, {"q": "A"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_search_limit_out_of_bounds_returns_validation_error(self):
        for limit in ("0", "11"):
            response = self.client.get(self.search_url, {"q": "Springfield", "limit": limit})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_latitude_out_of_bounds_returns_validation_error(self):
        response = self.client.get(self.search_url, {"q": "Springfield", "lat": 91.0, "lon": -89.0})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_lat_without_lon_returns_validation_error(self):
        response = self.client.get(self.search_url, {"q": "Springfield", "lat": 39.7})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @responses.activate
    def test_reverse_success_contract(self):
        responses.add(responses.GET, REVERSE_URL, json=MOCK_REVERSE_RESPONSE, status=200)

        response = self.client.get(self.reverse_url, {"lat": 39.7817, "lon": -89.6501})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["meta"]["cached"], False)
        data = body["data"]
        self.assertEqual(
            set(data.keys()),
            {"place_id", "display_name", "latitude", "longitude", "address", "type"},
        )
        self.assertEqual(data["place_id"], "4726946")

    def test_reverse_missing_coordinates_returns_validation_error(self):
        response = self.client.get(self.reverse_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    @responses.activate
    def test_reverse_provider_no_match_returns_geocoding_failed(self):
        responses.add(responses.GET, REVERSE_URL, json={}, status=404)

        response = self.client.get(self.reverse_url, {"lat": 0.0, "lon": 0.0})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error = response.json()["error"]
        self.assertEqual(error["code"], "GEOCODING_FAILED")
        self.assertEqual(error["details"], {"latitude": 0.0, "longitude": 0.0})

    @responses.activate
    def test_provider_error_returns_502_envelope(self):
        responses.add(responses.GET, SEARCH_URL, json={"error": "boom"}, status=500)

        response = self.client.get(self.search_url, {"q": "Springfield"})

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        error = response.json()["error"]
        self.assertEqual(error["code"], "GEOCODING_FAILED")
        self.assertEqual(error["details"]["provider"], "nominatim")

    @responses.activate
    def test_provider_rate_limit_returns_429(self):
        responses.add(
            responses.GET,
            SEARCH_URL,
            json={"error": "rate limited"},
            status=429,
            headers={"Retry-After": "45"},
        )

        response = self.client.get(self.search_url, {"q": "Springfield"})

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        error = response.json()["error"]
        self.assertEqual(error["code"], "RATE_LIMITED")
        self.assertEqual(error["details"]["retry_after"], 45)
