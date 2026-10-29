"""Routing-specific exceptions.

These map to the error codes defined in docs/API_CONTRACTS.md.
"""

from rest_framework import status

from common.exceptions import APIError


class RoutingError(APIError):
    """Base class for routing failures."""


class RoutingProviderError(RoutingError):
    """The upstream routing provider failed or returned an unusable response."""

    def __init__(self, message="Routing provider request failed.", details=None):
        merged = {"provider": "osrm"}
        if details:
            merged.update(details)
        super().__init__(
            code="ROUTE_GENERATION_FAILED",
            message=message,
            status_code=status.HTTP_502_BAD_GATEWAY,
            details=merged,
        )


class RoutingRateLimitError(RoutingError):
    """The upstream provider rate limit was exceeded."""

    def __init__(self, retry_after=60):
        super().__init__(
            code="RATE_LIMITED",
            message=f"Routing provider rate limit exceeded. Retry after {retry_after}s.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after


class NoRouteFoundError(RoutingError):
    """No drivable route exists for the supplied input, or an id is unknown."""

    def __init__(
        self,
        message="No drivable route found between the provided locations.",
        details=None,
    ):
        super().__init__(
            code="ROUTE_NOT_FOUND",
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )
