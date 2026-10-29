"""OSRM client behavior: request params, parsing, provider error mapping."""

from urllib.parse import parse_qs, urlparse

import requests
import responses
from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings

from apps.routing.clients.osrm import RoutingClient, parse_routes
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
    OSRM_ROUTE_URL,
)

ORIGIN = Point(-89.65, 39.78, srid=4326)
DESTINATION = Point(-87.63, 41.88, srid=4326)


class RoutingClientTests(TestCase):
    def make_client(self, **kwargs) -> RoutingClient:
        return RoutingClient(**kwargs)

    @responses.activate
    def test_get_routes_parses_three_alternatives(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)

        routes = self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(len(routes), 3)
        first = routes[0]
        # 325,800 m -> 202.44 mi; 11,700 s -> 195 min.
        self.assertEqual(first.distance_miles, 202.44)
        self.assertEqual(first.duration_minutes, 195)
        self.assertEqual(first.geometry["type"], "LineString")
        self.assertEqual(first.geometry["coordinates"][0], [-89.65, 39.78])
        self.assertTrue(all(route.distance_miles > 0 for route in routes))

    @responses.activate
    def test_single_route_when_alternatives_unavailable(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_1_ROUTE)

        routes = self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(len(routes), 1)

    @responses.activate
    def test_request_contains_alternatives_and_geojson(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_1_ROUTE)

        self.make_client().get_routes(ORIGIN, DESTINATION)

        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        self.assertEqual(query["alternatives"], ["true"])
        self.assertEqual(query["geometries"], ["geojson"])
        self.assertEqual(query["overview"], ["full"])

    @responses.activate
    def test_no_api_key_required(self):
        """OSRM is keyless: the request succeeds without credentials."""
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_1_ROUTE)

        routes = self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertTrue(routes)
        self.assertNotIn("Authorization", responses.calls[0].request.headers)

    @responses.activate
    def test_malformed_entries_are_skipped(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_MALFORMED)

        routes = self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].duration_minutes, 210)

    @responses.activate
    def test_empty_routes_raises_no_route_found(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json=MOCK_ORS_RESPONSE_EMPTY)

        with self.assertRaises(NoRouteFoundError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.code, "ROUTE_NOT_FOUND")
        self.assertEqual(ctx.exception.status_code, 404)

    @responses.activate
    def test_rate_limit_raises_rate_limit_error(self):
        responses.add(
            responses.GET,
            OSRM_ROUTE_URL,
            json={"code": "TooBig"},
            status=429,
            headers={"Retry-After": "45"},
        )

        with self.assertRaises(RoutingRateLimitError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.retry_after, 45)
        self.assertEqual(ctx.exception.status_code, 429)

    @responses.activate
    def test_server_error_raises_provider_error(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, json={"error": "boom"}, status=500)

        with self.assertRaises(RoutingProviderError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.code, "ROUTE_GENERATION_FAILED")
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.details["status_code"], 500)

    @responses.activate
    def test_timeout_raises_provider_error(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, body=requests.Timeout("slow"))

        with self.assertRaises(RoutingProviderError) as ctx:
            self.make_client().get_routes(ORIGIN, DESTINATION)

        self.assertEqual(ctx.exception.details["reason"], "Timeout")

    @responses.activate
    def test_invalid_json_raises_provider_error(self):
        responses.add(responses.GET, OSRM_ROUTE_URL, body="not json", status=200)

        with self.assertRaises(RoutingProviderError):
            self.make_client().get_routes(ORIGIN, DESTINATION)

    @override_settings(ROUTING_TIMEOUT=12.5)
    def test_default_timeout_comes_from_settings(self):
        client = RoutingClient()

        self.assertEqual(client.timeout, 12.5)


class ParseRoutesTests(TestCase):
    def test_parse_routes_ignores_non_dict_entries(self):
        payload = {"routes": [None, "garbage", {"distance": 10}]}

        self.assertEqual(parse_routes(payload), [])

    def test_parse_routes_handles_missing_payload(self):
        self.assertEqual(parse_routes({}), [])
        self.assertEqual(parse_routes(None), [])
