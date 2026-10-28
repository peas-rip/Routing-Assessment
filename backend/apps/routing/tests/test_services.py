"""Checkpoint sampling math, ETA calculation, generation pipeline."""

from datetime import datetime, timedelta
from decimal import Decimal

import responses
from django.contrib.gis.geos import LineString
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.routing.clients.openrouteservice import RouteData
from apps.routing.exceptions import NoRouteFoundError, RoutingProviderError
from apps.routing.models import Checkpoint
from apps.routing.services import (
    calculate_eta,
    create_checkpoints,
    generate_routes,
    resolve_interval,
)
from apps.routing.utils import name_route, to_linestring

from .fixtures import (
    MOCK_ORS_RESPONSE_1_ROUTE,
    MOCK_ORS_RESPONSE_3_ROUTES,
    MOCK_ORS_RESPONSE_EMPTY,
    ORS_DIRECTIONS_URL,
    make_route,
    make_route_request,
)


class CheckpointSamplingTests(TestCase):
    """F03: origin always 0, interval points, destination always last."""

    def setUp(self):
        self.departure = timezone.make_aware(datetime(2026, 10, 27, 8, 0, 0))
        self.route = make_route(distance_miles="100.00", duration_minutes=120)

    def test_origin_checkpoint_is_always_first(self):
        checkpoints = create_checkpoints(self.route, 25, self.departure)

        origin = checkpoints[0]
        self.assertEqual(origin.sequence, 0)
        self.assertEqual(origin.mile_marker, Decimal("0.00"))
        self.assertEqual(origin.latitude, 39.78)
        self.assertEqual(origin.longitude, -89.65)
        self.assertEqual(origin.estimated_arrival, self.departure)
        self.assertEqual(origin.location.x, -89.65)
        self.assertEqual(origin.location.y, 39.78)
        self.assertEqual(origin.location.srid, 4326)

    def test_destination_checkpoint_is_always_last(self):
        checkpoints = create_checkpoints(self.route, 25, self.departure)

        destination = checkpoints[-1]
        self.assertEqual(destination.mile_marker, Decimal("100.00"))
        self.assertEqual(destination.latitude, 41.88)
        self.assertEqual(destination.longitude, -87.63)
        self.assertEqual(destination.estimated_arrival, self.departure + timedelta(minutes=120))

    def test_25_mile_intervals(self):
        checkpoints = create_checkpoints(self.route, 25, self.departure)

        markers = [checkpoint.mile_marker for checkpoint in checkpoints]
        self.assertEqual(len(checkpoints), 5)
        self.assertEqual(markers, [0, 25, 50, 75, 100])

    def test_10_mile_intervals(self):
        checkpoints = create_checkpoints(self.route, 10, self.departure)

        self.assertEqual(len(checkpoints), 11)  # 0, 10, 20, ..., 100

    def test_50_mile_intervals(self):
        checkpoints = create_checkpoints(self.route, 50, self.departure)

        self.assertEqual(len(checkpoints), 3)  # 0, 50, 100

    def test_short_route_only_origin_and_destination(self):
        route = make_route(distance_miles="2.00", duration_minutes=5)

        checkpoints = create_checkpoints(route, 25, self.departure)

        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[0].mile_marker, Decimal("0.00"))
        self.assertEqual(checkpoints[1].mile_marker, Decimal("2.00"))

    def test_interval_landing_on_destination_is_not_duplicated(self):
        checkpoints = create_checkpoints(self.route, 50, self.departure)

        markers = [checkpoint.mile_marker for checkpoint in checkpoints]
        self.assertEqual(markers, [0, 50, 100])
        self.assertEqual([checkpoint.sequence for checkpoint in checkpoints], [0, 1, 2])

    def test_eta_is_proportional_to_departure_and_duration(self):
        checkpoints = create_checkpoints(self.route, 25, self.departure)

        at_25 = checkpoints[1]
        at_75 = checkpoints[3]
        self.assertEqual(at_25.estimated_arrival, self.departure + timedelta(minutes=30))
        self.assertEqual(at_75.estimated_arrival, self.departure + timedelta(minutes=90))

    def test_intermediate_points_follow_geometry(self):
        checkpoints = create_checkpoints(self.route, 25, self.departure)

        for checkpoint in checkpoints:
            self.assertTrue(-90 < checkpoint.longitude < -87)
            self.assertTrue(39 < checkpoint.latitude < 42)
            self.assertEqual(checkpoint.location.srid, 4326)

    def test_sequences_are_contiguous(self):
        checkpoints = create_checkpoints(self.route, 25, self.departure)

        self.assertEqual([checkpoint.sequence for checkpoint in checkpoints], list(range(5)))

    def test_checkpoints_are_persisted(self):
        create_checkpoints(self.route, 25, self.departure)

        self.assertEqual(Checkpoint.objects.filter(route=self.route).count(), 5)

    def test_unsupported_interval_falls_back_to_25_with_warning(self):
        with self.assertLogs("apps.routing.services", level="WARNING") as logs:
            checkpoints = create_checkpoints(self.route, 15, self.departure)

        self.assertEqual(len(checkpoints), 5)  # sampled as 25 miles
        self.assertTrue(any("15" in message for message in logs.output))


class CalculateEtaTests(SimpleTestCase):
    def setUp(self):
        self.departure = timezone.make_aware(datetime(2026, 10, 27, 8, 0, 0))

    def test_half_route_takes_half_the_duration(self):
        eta = calculate_eta(self.departure, 50, 100, 120)
        self.assertEqual(eta, self.departure + timedelta(minutes=60))

    def test_zero_total_returns_departure(self):
        self.assertEqual(calculate_eta(self.departure, 0, 0, 120), self.departure)

    def test_mile_beyond_route_is_clamped_to_destination(self):
        eta = calculate_eta(self.departure, 150, 100, 120)
        self.assertEqual(eta, self.departure + timedelta(minutes=120))


class ResolveIntervalTests(SimpleTestCase):
    def test_allowed_intervals_pass_through(self):
        for interval in (10, 25, 50):
            self.assertEqual(resolve_interval(interval), interval)

    def test_unsupported_intervals_default_to_25(self):
        for interval in (15, 0, 100, "abc", None):
            with self.subTest(interval=interval):
                with self.assertLogs("apps.routing.services", level="WARNING"):
                    self.assertEqual(resolve_interval(interval), 25)


class NameRouteTests(SimpleTestCase):
    def test_index_based_names(self):
        routes = [
            RouteData(202.44, 195, None, {}),
            RouteData(197.60, 210, None, {}),
            RouteData(210.02, 200, None, {}),
        ]

        self.assertEqual(name_route(routes[0], 0, routes), "Fastest")
        self.assertEqual(name_route(routes[1], 1, routes), "Shortest")
        self.assertEqual(name_route(routes[2], 2, routes), "Balanced")

    def test_fallback_compares_route_metrics(self):
        others = [RouteData(500.0, 400, None, {})]
        fastest = RouteData(500.0, 100, None, {})
        shortest = RouteData(100.0, 500, None, {})
        neither = RouteData(900.0, 900, None, {})

        self.assertEqual(name_route(fastest, 7, others + [fastest]), "Fastest")
        self.assertEqual(name_route(shortest, 8, others + [shortest]), "Shortest")
        self.assertEqual(name_route(neither, 9, others + [neither]), "Alternative 10")


class ToLinestringTests(SimpleTestCase):
    def test_converts_geojson_to_wgs84_linestring(self):
        geometry = {"type": "LineString", "coordinates": [[-89.65, 39.78], [-87.63, 41.88]]}

        line = to_linestring(geometry)

        self.assertIsInstance(line, LineString)
        self.assertEqual(line.srid, 4326)
        self.assertEqual(line.coords[0], (-89.65, 39.78))

    def test_rejects_encoded_polyline_string(self):
        with self.assertRaises(RoutingProviderError) as ctx:
            to_linestring("encoded_polyline")

        self.assertEqual(ctx.exception.code, "ROUTE_GENERATION_FAILED")

    def test_rejects_wrong_geojson_type(self):
        with self.assertRaises(RoutingProviderError):
            to_linestring({"type": "Point", "coordinates": [-89.65, 39.78]})

    def test_rejects_degenerate_geometry(self):
        with self.assertRaises(RoutingProviderError):
            to_linestring({"type": "LineString", "coordinates": [[-89.65, 39.78]]})

    def test_rejects_invalid_coordinates(self):
        with self.assertRaises(RoutingProviderError):
            to_linestring({"type": "LineString", "coordinates": [["a", "b"], ["c", "d"]]})


@override_settings(OPENROUTESERVICE_API_KEY="test-key")
class GenerateRoutesTests(TestCase):
    """F02 pipeline: fetch -> persist routes -> sample checkpoints."""

    @responses.activate
    def test_creates_three_named_routes_with_checkpoints(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()

        routes = generate_routes(route_request)

        self.assertEqual(len(routes), 3)
        self.assertEqual([route.route_index for route in routes], [0, 1, 2])
        self.assertEqual([route.name for route in routes], ["Fastest", "Shortest", "Balanced"])
        self.assertEqual([route.duration_minutes for route in routes], [195, 210, 200])
        self.assertEqual(float(routes[0].distance_miles), 202.44)
        self.assertEqual(routes[0].summary, {"distance": 325800, "duration": 11700})

        first = routes[0]
        self.assertEqual(first.geometry.geom_type, "LineString")
        self.assertEqual(first.geometry.coords[0], (-89.65, 39.78))
        markers = [checkpoint.mile_marker for checkpoint in first.checkpoints.all()]
        self.assertEqual(markers[0], Decimal("0.00"))
        self.assertEqual(markers[-1], Decimal("202.44"))
        self.assertGreaterEqual(len(markers), 2)

        route_request.refresh_from_db()
        self.assertEqual(route_request.progress, 60)

    @responses.activate
    def test_single_route_payload_yields_one_route(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_1_ROUTE)
        route_request = make_route_request()

        routes = generate_routes(route_request)

        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].name, "Fastest")
        self.assertEqual(routes[0].checkpoints.count(), 10)

    @responses.activate
    def test_empty_response_raises_no_route_found(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_EMPTY)
        route_request = make_route_request()

        with self.assertRaises(NoRouteFoundError):
            generate_routes(route_request)

        self.assertEqual(route_request.routes.count(), 0)

    @responses.activate
    def test_unusable_geometry_raises_provider_error(self):
        payload = {"routes": [{"geometry": "...", "distance": 325800, "duration": 11700}]}
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=payload)
        route_request = make_route_request()

        with self.assertRaises(RoutingProviderError):
            generate_routes(route_request)

        self.assertEqual(route_request.routes.count(), 0)

    @responses.activate
    def test_rerun_replaces_previous_output(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_3_ROUTES)
        route_request = make_route_request()

        generate_routes(route_request)
        generate_routes(route_request)

        self.assertEqual(route_request.routes.count(), 3)
        self.assertEqual(
            Checkpoint.objects.filter(route__request=route_request).count(),
            sum(route.checkpoints.count() for route in route_request.routes.all()),
        )

    @override_settings(OPENROUTESERVICE_API_KEY="")
    def test_missing_api_key_raises_provider_error(self):
        route_request = make_route_request()

        with self.assertRaises(RoutingProviderError):
            generate_routes(route_request)

    @responses.activate
    def test_progress_advances_through_documented_milestones(self):
        responses.add(responses.POST, ORS_DIRECTIONS_URL, json=MOCK_ORS_RESPONSE_1_ROUTE)
        route_request = make_route_request()
        self.assertEqual(route_request.progress, 0)

        generate_routes(route_request)

        route_request.refresh_from_db()
        self.assertEqual(route_request.progress, 60)  # 30 (routing) -> 60 (checkpoints)
