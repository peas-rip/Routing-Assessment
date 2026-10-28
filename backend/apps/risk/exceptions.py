"""Risk-specific exceptions.

These map to the error codes defined in docs/API_CONTRACTS.md.
"""

from rest_framework import status

from common.exceptions import APIError


class RiskError(APIError):
    """Base class for risk failures."""


class RouteNotFoundError(RiskError):
    """The referenced route does not exist."""

    def __init__(self, message="Route not found.", details=None):
        super().__init__(
            code="ROUTE_NOT_FOUND",
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )


class InsufficientRiskDataError(RiskError):
    """Not enough stored data (checkpoints/weather/routes) to answer."""

    def __init__(self, message="Insufficient route data.", details=None):
        super().__init__(
            code="VALIDATION_ERROR",
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details,
        )


class RiskCalculationError(RiskError):
    """Unexpected internal failure while computing risk or a recommendation."""

    def __init__(self, message="Risk calculation failed.", details=None):
        super().__init__(
            code="RISK_CALCULATION_FAILED",
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details=details,
        )
