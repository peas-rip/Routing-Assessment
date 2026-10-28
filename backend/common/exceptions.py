"""API error handling.

All API errors render the envelope defined in docs/API_CONTRACTS.md:

    {"error": {"code": "ERROR_CODE", "message": "Human readable", "details": {}}}
"""

import logging

from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response

logger = logging.getLogger(__name__)

INTERNAL_ERROR_CODE = "INTERNAL_ERROR"
INTERNAL_ERROR_MESSAGE = "An unexpected error occurred."


class APIError(exceptions.APIException):
    """Base class for errors that map directly to the API error envelope."""

    def __init__(self, code, message, status_code=status.HTTP_400_BAD_REQUEST, details=None):
        super().__init__(detail=message)
        self.status_code = status_code
        self.code = code
        self.details = details or {}


def error_response(code, message, status_code, details=None):
    """Build the standard error envelope response."""
    return Response(
        {"error": {"code": code, "message": message, "details": details or {}}},
        status=status_code,
    )


def api_exception_handler(exc, context):
    """Render every exception through the documented error envelope."""
    if isinstance(exc, APIError):
        return error_response(exc.code, str(exc.detail), exc.status_code, exc.details)

    if isinstance(exc, exceptions.Throttled):
        details = {"retry_after": exc.wait} if getattr(exc, "wait", None) else {}
        return error_response(
            "RATE_LIMITED",
            "Too many requests. Please retry later.",
            status.HTTP_429_TOO_MANY_REQUESTS,
            details,
        )

    if isinstance(exc, exceptions.ValidationError):
        return error_response(
            "VALIDATION_ERROR",
            "Invalid request parameters.",
            status.HTTP_400_BAD_REQUEST,
            {"fields": exc.detail},
        )

    if isinstance(exc, Http404):
        return error_response("NOT_FOUND", "Resource not found.", status.HTTP_404_NOT_FOUND)

    if isinstance(exc, exceptions.APIException):
        code = str(getattr(exc, "default_code", "error")).upper()
        return error_response(code, str(exc.detail), exc.status_code)

    logger.exception("Unhandled exception during request", exc_info=exc)
    return error_response(
        INTERNAL_ERROR_CODE,
        INTERNAL_ERROR_MESSAGE,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
