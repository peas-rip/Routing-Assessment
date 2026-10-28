from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.test import SimpleTestCase
from rest_framework import exceptions, status
from rest_framework.exceptions import Throttled

from common.exceptions import APIError, api_exception_handler


class ApiExceptionHandlerTests(SimpleTestCase):
    def _handle(self, exc):
        return api_exception_handler(exc, {})

    def test_api_error_uses_code_and_details(self):
        exc = APIError(
            code="GEOCODING_FAILED",
            message="Could not geocode address.",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"field": "q"},
        )

        response = self._handle(exc)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data,
            {
                "error": {
                    "code": "GEOCODING_FAILED",
                    "message": "Could not geocode address.",
                    "details": {"field": "q"},
                }
            },
        )

    def test_throttled_maps_to_rate_limited(self):
        response = self._handle(Throttled(wait=12))

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data["error"]["code"], "RATE_LIMITED")
        self.assertEqual(response.data["error"]["details"], {"retry_after": 12})

    def test_throttled_without_wait_has_empty_details(self):
        response = self._handle(Throttled())

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data["error"]["details"], {})

    def test_validation_error_maps_to_validation_error_code(self):
        exc = exceptions.ValidationError({"q": ["This field is required."]})

        response = self._handle(exc)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("fields", response.data["error"]["details"])

    def test_http404_maps_to_not_found(self):
        response = self._handle(Http404())

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"]["code"], "NOT_FOUND")

    def test_generic_api_exception_uses_default_code(self):
        response = self._handle(exceptions.ParseError())

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "PARSE_ERROR")

    def test_unhandled_exception_maps_to_internal_error(self):
        response = self._handle(ValueError("boom"))

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        body = response.data["error"]
        self.assertEqual(body["code"], "INTERNAL_ERROR")
        self.assertNotIn("boom", body["message"])  # No internals leaked
        self.assertEqual(body["details"], {})

    def test_django_validation_error_is_not_swallowed(self):
        # django.core.exceptions.ValidationError is not a DRF exception; it must
        # surface as a 500 rather than being silently converted to success.
        response = self._handle(DjangoValidationError("bad"))

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
