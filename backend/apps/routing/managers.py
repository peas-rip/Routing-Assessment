"""Custom querysets/managers for routing models (docs/SERVICES/routing)."""

from django.db import models


class RouteQuerySet(models.QuerySet):
    def for_request(self, route_request):
        """Routes belonging to a generation request, in option order."""
        return self.filter(request=route_request).order_by("route_index")

    def ordered(self):
        return self.order_by("route_index")

    def recommended(self):
        return self.filter(is_recommended=True)


class RouteManager(models.Manager.from_queryset(RouteQuerySet)):
    """Manager for :class:`~apps.routing.models.Route`."""


class CheckpointQuerySet(models.QuerySet):
    def for_route(self, route):
        return self.filter(route=route)

    def ordered(self):
        """Checkpoints in traversal order along the route."""
        return self.order_by("sequence")


class CheckpointManager(models.Manager.from_queryset(CheckpointQuerySet)):
    """Manager for :class:`~apps.routing.models.Checkpoint`."""
