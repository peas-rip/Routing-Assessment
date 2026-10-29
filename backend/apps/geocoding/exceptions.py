"""Geocoding-specific exceptions.

These map to the error codes defined in docs/API_CONTRACTS.md.
"""

from rest_framework import status

from common.exceptions import APIError


class GeocodingError(APIError):
    """Base class for geocoding failures."""


class GeocodingProviderError(GeocodingError):
    """The upstream geocoding provider failed or returned an unusable response."""

    def __init__(self, message="Geocoding provider request failed.", details=None):
        merged = {"provider": "nominatim"}
        if details:
            merged.update(details)
        super().__init__(
            code="GEOCODING_FAILED",
            message=message,
            status_code=status.HTTP_502_BAD_GATEWAY,
            details=merged,
        )


class RateLimitError(GeocodingError):
    """The upstream provider rate limit was exceeded."""

    def __init__(self, retry_after=60):
        super().__init__(
            code="RATE_LIMITED",
            message=f"Geocoding provider rate limit exceeded. Retry after {retry_after}s.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after


class GeocodingNotFoundError(GeocodingError):
    """No geocoding result exists for the supplied input."""

    def __init__(self, details=None):
        super().__init__(
            code="GEOCODING_FAILED",
            message="Could not geocode address.",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )
