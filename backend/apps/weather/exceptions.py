"""Weather-specific exceptions.

These map to the error codes defined in docs/API_CONTRACTS.md.
"""

from rest_framework import status

from common.exceptions import APIError


class WeatherError(APIError):
    """Base class for weather failures."""


class WeatherProviderError(WeatherError):
    """The upstream weather provider failed or returned an unusable response."""

    def __init__(self, message="Weather provider request failed.", details=None):
        merged = {"provider": "nws"}
        if details:
            merged.update(details)
        super().__init__(
            code="WEATHER_API_ERROR",
            message=message,
            status_code=status.HTTP_502_BAD_GATEWAY,
            details=merged,
        )


class WeatherRateLimitError(WeatherError):
    """The upstream provider rate limit was exceeded."""

    def __init__(self, retry_after=60):
        super().__init__(
            code="RATE_LIMITED",
            message=f"Weather provider rate limit exceeded. Retry after {retry_after}s.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after


class WeatherNotFoundError(WeatherError):
    """No weather data exists for the requested checkpoints."""

    def __init__(self, message="No weather data for the requested checkpoints.", details=None):
        super().__init__(
            code="WEATHER_NOT_FOUND",
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )


class HeatmapRouteNotFoundError(WeatherError):
    """The route referenced by a heatmap request does not exist (F08)."""

    def __init__(self, message="Route not found for heatmap.", details=None):
        super().__init__(
            code="ROUTE_NOT_FOUND",
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )
