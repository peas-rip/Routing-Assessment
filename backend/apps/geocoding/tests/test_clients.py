"""Nominatim client parsing and transport errors."""


import requests
import responses
from django.test import TestCase

from apps.geocoding.clients.nominatim import GeocodingClient, parse_search_payload
from apps.geocoding.exceptions import (
    GeocodingProviderError,
    RateLimitError,
)

from .fixtures import (
    MOCK_REVERSE_RESPONSE,
    MOCK_SEARCH_RESPONSE,
    NOMINATIM_REVERSE_URL,
    NOMINATIM_SEARCH_URL,
)

SEARCH_URL = NOMINATIM_SEARCH_URL
REVERSE_URL = NOMINATIM_REVERSE_URL
EXPECTED_LABEL = MOCK_REVERSE_RESPONSE["display_name"]


class GeocodingClientTests(TestCase):
    def make_client(self, **kwargs) -> GeocodingClient:
        return GeocodingClient(**kwargs)

    @responses.activate
    def test_search_parses_results(self):
        responses.add(responses.GET, SEARCH_URL, json=MOCK_SEARCH_RESPONSE, status=200)

        response = self.make_client().search("Springfield", limit=5)

        self.assertEqual(len(response.results), 2)
        first = response.results[0]
        self.assertEqual(first["place_id"], "4726946")
        self.assertEqual(first["latitude"], 39.7817)
        self.assertEqual(first["longitude"], -89.6501)
        self.assertEqual(first["address"]["city"], "Springfield")
        self.assertEqual(first["address"]["state"], "IL")
        self.assertEqual(first["type"], "house")
        self.assertEqual(response.raw["results"], MOCK_SEARCH_RESPONSE)

    @responses.activate
    def test_search_sends_expected_params(self):
        captured = {}

        def request_callback(request):
            captured["params"] = request.params
            captured["headers"] = request.headers
            return (200, {}, "[]")

        responses.add_callback(responses.GET, SEARCH_URL, callback=request_callback)

        self.make_client().search("Springfield", limit=3, lat=39.78, lon=-89.65)

        self.assertEqual(captured["params"]["q"], "Springfield")
        self.assertEqual(captured["params"]["limit"], "3")
        self.assertEqual(captured["params"]["format"], "json")
        self.assertIn("addressdetails", captured["params"])
        # Nominatim is keyless: no Authorization header is sent.
        self.assertNotIn("Authorization", captured["headers"])
        self.assertIn("User-Agent", captured["headers"])

    @responses.activate
    def test_reverse_parses_single_result(self):
        responses.add(responses.GET, REVERSE_URL, json=MOCK_REVERSE_RESPONSE, status=200)

        response = self.make_client().reverse(39.7817, -89.6501)

        self.assertIsNotNone(response)
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0]["display_name"], EXPECTED_LABEL)

    @responses.activate
    def test_reverse_returns_none_on_404(self):
        responses.add(responses.GET, REVERSE_URL, json={"error": "no match"}, status=404)

        self.assertIsNone(self.make_client().reverse(0.0, 0.0))

    @responses.activate
    def test_reverse_returns_none_for_unparseable_payload(self):
        responses.add(responses.GET, REVERSE_URL, json={"error": "Unable to geocode"}, status=200)

        self.assertIsNone(self.make_client().reverse(39.7817, -89.6501))

    @responses.activate
    def test_rate_limit_raises_rate_limit_error(self):
        responses.add(
            responses.GET,
            SEARCH_URL,
            json={"error": "rate limited"},
            status=429,
            headers={"Retry-After": "30"},
        )

        with self.assertRaises(RateLimitError) as ctx:
            self.make_client().search("Springfield")

        self.assertEqual(ctx.exception.retry_after, 30)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        self.assertEqual(ctx.exception.status_code, 429)

    @responses.activate
    def test_server_error_raises_provider_error(self):
        responses.add(responses.GET, SEARCH_URL, json={"error": "boom"}, status=500)

        with self.assertRaises(GeocodingProviderError) as ctx:
            self.make_client().search("Springfield")

        self.assertEqual(ctx.exception.code, "GEOCODING_FAILED")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.details["status_code"], 500)

    @responses.activate
    def test_timeout_raises_provider_error(self):
        responses.add(responses.GET, SEARCH_URL, body=requests.Timeout("timed out"))

        with self.assertRaises(GeocodingProviderError):
            self.make_client().search("Springfield")

    @responses.activate
    def test_connection_error_raises_provider_error(self):
        responses.add(responses.GET, SEARCH_URL, body=requests.ConnectionError("refused"))

        with self.assertRaises(GeocodingProviderError):
            self.make_client().search("Springfield")

    @responses.activate
    def test_invalid_json_raises_provider_error(self):
        responses.add(responses.GET, SEARCH_URL, body="not json", status=200)

        with self.assertRaises(GeocodingProviderError):
            self.make_client().search("Springfield")

    @responses.activate
    def test_search_unexpected_404_raises_provider_error(self):
        responses.add(responses.GET, SEARCH_URL, json={}, status=404)

        with self.assertRaises(GeocodingProviderError):
            self.make_client().search("Springfield")

    @responses.activate
    def test_malformed_coordinates_are_skipped(self):
        payload = [{"display_name": "x", "lat": "bad", "lon": "-89.6"}]
        responses.add(responses.GET, SEARCH_URL, json=payload, status=200)

        results = self.make_client().search("Springfield").results

        self.assertEqual(results, [])

    def test_parser_handles_malformed_features(self):
        payload = [
            None,
            {"lat": "bad", "lon": "-89.6"},
            {"lat": "39.7", "lon": "-89.6", "display_name": "ok"},
        ]
        results = parse_search_payload(payload)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["latitude"], 39.7)
