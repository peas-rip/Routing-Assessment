"""ORS client behavior: payload shape, parsing, provider error mapping."""

import json

import requests
import responses
from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings

from apps.routing.clients.openrouteservice import RoutingClient, parse_routes
from apps.routing.exceptions import (
    NoRouteFoundError,
    RoutingProviderError,
    RoutingRateLimitError,
)

from .fixtures import (
    MOCK_ORS_RESPONSE_1_ROUTE,
    MOCK_ORS_RESPONSE_3_ROUTES,
    MOCK_ORS_RESPONSE_EMPTY,
    MOCK_ORS_RESPONSE_MALFORMED,
    MOCK_ORS_RESPONSE_SUMMARY_STYLE,
    ORS_DIRECTIONS_URL,
)

ORIGIN = Point(-89.65, 39.78, srid=4326)
DESTINATION = Point(-87.63, 41.88, srid=4326)


@override_settings(OPENROUTESERVICE_API_KEY="test-key")
class RoutingClientTests(TestCase):
    def make_client(self, **kwargs) -> RoutingClient:
        kwargs.setdefault("api_key", "test-key")
        return RoutingClient(**kwargs)

    @responses.activate
    def test_get_routes_parses_three_alternatives(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)

        routes = self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(len(routes), 3)
        first = routes[0]
        # 325,800 m -> 202.44 mi; 11,700 s -> 195 min.
        self.assertEqual(first.distance_miles, 202.44)
        self.assertEqual(first.duration_minutes, 195)
        self.assertEqual(first.geometry["type"], "LineString")
        self.assertEqual(first.geometry["coordinates"][0], [-89.65, 39.78])
        self.assertTrue(all(route.distance_miles > 0 for route in routes))
        self.assertTrue(all(route.duration_minutes > 0 for route in routes))

    @responses.activate
    def test_payload_contains_hgv_alternative_options(self):
        captured = {}

        def request_callback(request):
            captured["body"] = json.loads(request.body)
            captured["headers"] = request.headers
            return (200, {}, json.dumps(MOCK_ORS_RESPONSE_1_ROUTE))

        responses.add_callback(responses.POST, ORS_DIRECTIONS_URL, callback=request_callback)

        self.make_client().get_routes(ORIGIN, DESTINATION)

        body = captured["body"]
        self.assertEqual(body["coordinates"], [[-89.65, 39.78], [-87.63, 41.88]])
        self.assertEqual(body["profile"], "driving-hgv")
        self.assertEqual(
            body["alternative_routes"],
            {"target_count": 3, "share_factor": 0.6, "weight_factor": 1.5},
        )
        self.assertTrue(body["geometry"])
        # Distance is requested in meters (default) so the parser's
        # meters-per-mile conversion is correct.
        self.assertNotIn("units", body)
        self.assertEqual(captured["headers"]["Authorization"], "test-key")

    @responses.activate
    def test_parses_summary_style_payload(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_SUMMARY_STYLE)

        routes = self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].distance_miles, 202.44)
        self.assertEqual(routes[0].duration_minutes, 195)
        self.assertEqual(routes[0].summary["weight"], 11700)

    @responses.activate
    def test_falls_back_to_top_level_distance_and_duration(self):
        payload = {
            "routes": [
                {"geometry": "encoded_polyline", "distance": 100000, "duration": 3600},
            ]
        }
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=payload)

        routes = self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].distance_miles, 62.14)
        self.assertEqual(routes[0].duration_minutes, 60)
        self.assertEqual(routes[0].geometry, "encoded_polyline")

    @responses.activate
    def test_malformed_entries_are_skipped(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_MALFORMED)

        routes = self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].duration_minutes, 210)

    @responses.activate
    def test_empty_routes_raises_no_route_found(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_EMPTY)

        with self.assertRaises(NoRouteFoundError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.code, "ROUTE_NOT_FOUND")
        self.assertEqual(ctx.exception.status_code, 404)

    @responses.activate
    def test_rate_limit_raises_rate_limit_error(self):
        responses.add(
            responses.POST,
            ORS_DIRECTIONS_URL,
            json={"error": "rate limited"},
            status=429,
            headers={"Retry-After": "45"},
        )

        with self.assertRaises(RoutingRateLimitError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.retry_after, 45)
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        self.assertEqual(ctx.exception.status_code, 429)

    @responses.activate
    def test_server_error_raises_provider_error(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json={"error": "boom"}, status=500)

        with self.assertRaises(RoutingProviderError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.code, "ROUTE_GENERATION_FAILED")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.details["status_code"], 500)
        self.assertEqual(ctx.exception.details["provider"], "openrouteservice")

    @responses.activate
    def test_timeout_raises_provider_error(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, body=requests.Timeout("slow"))

        with self.assertRaises(RoutingProviderError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.details["reason"], "Timeout")

    @responses.activate
    def test_connection_error_raises_provider_error(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, body=requests.ConnectionError("down"))

        with self.assertRaises(RoutingProviderError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.details["reason"], "ConnectionError")

    @responses.activate
    def test_invalid_json_raises_provider_error(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, body="not json", status=200)

        with self.assertRaises(RoutingProviderError):
            self.make_client().get_routes(ORIGIN, DESTINATION)

    @override_settings(OPENROUTESERVICE_API_KEY="")
    def test_missing_api_key_raises_provider_error_without_http(self):
        client = RoutingClient(api_key="")

        with self.assertRaises(RoutingProviderError) as ctx:
            client.get_routes(ORIGIN, DESTINATION)

        self.assertIn("API key", str(ctx.exception.detail))

    @override_settings(ROUTING_TIMEOUT=12.5)
    def test_default_timeout_comes_from_settings(self):
        client = RoutingClient(api_key="test-key")

        self.assertEqual(client.timeout, 12.5)


class ParseRoutesTests(TestCase):
    def test_parse_routes_ignores_non_dict_entries(self):
        payload = {"routes": [None, "garbage", {"distance": 10}]}

        self.assertEqual(parse_routes(payload), [])

    def test_parse_routes_handles_missing_payload(self):
        self.assertEqual(parse_routes({}), [])
        self.assertEqual(parse_routes(None), [])
