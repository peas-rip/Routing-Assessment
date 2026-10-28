"""Model validation, defaults and PostGIS geometry behavior."""

from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.routing.models import Checkpoint, Route, RouteRequest

from .fixtures import make_route, make_route_request


class RouteRequestTests(TestCase):
    def test_defaults_match_spec(self):
        route_request = make_route_request()

        self.assertEqual(route_request.status, RouteRequest.Status.PENDING)
        self.assertEqual(route_request.checkpoint_interval_miles, 25)
        self.assertEqual(route_request.progress, 0)
        self.assertIsNone(route_request.error_message)
        self.assertIsNone(route_request.completed_at)

    def test_origin_and_destination_points_are_wgs84(self):
        route_request = make_route_request()

        origin = route_request.origin_point
        destination = route_request.destination_point

        self.assertIsInstance(origin, Point)
        self.assertEqual(origin.x, -89.6501)
        self.assertEqual(origin.y, 39.7817)
        self.assertEqual(origin.srid, 4326)
        self.assertEqual(destination.x, -87.6298)
        self.assertEqual(destination.y, 41.8781)
        self.assertEqual(destination.srid, 4326)

    def test_str_contains_addresses_and_status(self):
        route_request = make_route_request()

        text = str(route_request)

        self.assertIn("Springfield, IL", text)
        self.assertIn("Chicago, IL", text)
        self.assertIn("pending", text)

    def test_load_weight_must_be_positive_and_legal(self):
        route_request = make_route_request()

        route_request.load_weight_lbs = 0
        with self.assertRaises(ValidationError):
            route_request.full_clean()

        route_request.load_weight_lbs = 90_001
        with self.assertRaises(ValidationError):
            route_request.full_clean()

        route_request.load_weight_lbs = 45_000
        route_request.full_clean()

    def test_departure_time_is_stored_timezone_aware(self):
        route_request = make_route_request()

        self.assertTrue(timezone.is_aware(route_request.departure_time))


class RouteTests(TestCase):
    def test_geometry_is_stored_as_linestring(self):
        route = make_route()

        self.assertEqual(route.geometry.geom_type, "LineString")
        self.assertEqual(route.geometry.srid, 4326)
        self.assertEqual(len(route.geometry.coords), 2)

    def test_str_contains_name_and_distance(self):
        route = make_route()

        self.assertIn("Fastest", str(route))
        self.assertIn("100.00", str(route))

    def test_routes_are_cascaded_from_request(self):
        route_request = make_route_request()
        make_route(route_request)
        make_route(route_request, route_index=1, name="Shortest")

        self.assertEqual(route_request.routes.count(), 2)


class CheckpointTests(TestCase):
    def test_checkpoints_order_by_sequence(self):
        route = make_route()
        departure = timezone.now()
        for sequence in (2, 0, 1):
            Checkpoint.objects.create(
                route=route,
                sequence=sequence,
                mile_marker=sequence * 25,
                latitude=39.78,
                longitude=-89.65,
                location=Point(-89.65, 39.78, srid=4326),
                estimated_arrival=departure,
            )

        sequences = [checkpoint.sequence for checkpoint in route.checkpoints.all()]

        self.assertEqual(sequences, [0, 1, 2])

    def test_checkpoint_manager_helpers(self):
        route = make_route()
        departure = timezone.now()
        Checkpoint.objects.create(
            route=route,
            sequence=0,
            mile_marker=0,
            latitude=39.78,
            longitude=-89.65,
            location=Point(-89.65, 39.78, srid=4326),
            estimated_arrival=departure,
        )

        ordered = route.checkpoints.ordered()
        self.assertEqual(len(ordered), 1)
        self.assertEqual(route.checkpoints.for_route(route).count(), 1)

    def test_checkpoint_location_is_geography_point(self):
        route = make_route()
        checkpoint = Checkpoint.objects.create(
            route=route,
            sequence=0,
            mile_marker=0,
            latitude=39.78,
            longitude=-89.65,
            location=Point(-89.65, 39.78, srid=4326),
            estimated_arrival=timezone.now(),
        )

        self.assertEqual(checkpoint.location.geom_type, "Point")
        self.assertEqual(checkpoint.location.srid, 4326)
        self.assertEqual(checkpoint.location.x, -89.65)

    def test_checkpoint_str_contains_sequence_and_mile_marker(self):
        route = make_route()
        checkpoint = Checkpoint.objects.create(
            route=route,
            sequence=3,
            mile_marker=75,
            latitude=39.78,
            longitude=-89.65,
            location=Point(-89.65, 39.78, srid=4326),
            estimated_arrival=timezone.now(),
        )

        self.assertEqual(str(checkpoint), "cp seq=3 mi=75")

    def test_route_manager_queryset_helpers(self):
        route_request = make_route_request()
        make_route(route_request, is_recommended=True)
        make_route(route_request, route_index=1, name="Shortest", is_recommended=False)

        for_request = Route.objects.for_request(route_request)
        self.assertEqual([route.route_index for route in for_request], [0, 1])

        recommended = Route.objects.recommended()
        self.assertEqual(recommended.count(), 1)
        self.assertEqual(recommended[0].name, "Fastest")
