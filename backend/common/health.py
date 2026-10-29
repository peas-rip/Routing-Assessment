"""Health check endpoint: GET /health/ (docs/API_CONTRACTS.md)."""

import logging

from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

VERSION = "1.0.0"

CHECK_OK = "ok"
CHECK_DEGRADED = "degraded"
CHECK_ERROR = "error"
CHECK_NOT_CONFIGURED = "not_configured"
CHECK_RATE_LIMITED = "rate_limited"

# Statuses that do not make the service unhealthy: the provider is reachable
# (or simply not configured) and cached results still serve traffic.
NON_FATAL_STATUSES = (CHECK_OK, CHECK_NOT_CONFIGURED, CHECK_RATE_LIMITED)


class HealthCheckView(APIView):
    """Liveness/readiness probe. Never exposes internals or credentials."""

    authentication_classes = []

    def get(self, request):
        checks = {
            "database": self.check_database(),
            "redis": self.check_redis(),
            "geocoding": self.check_geocoding(),
            "nws": self.check_nws(),
        }
        healthy = all(v in NON_FATAL_STATUSES for v in checks.values())
        response_status = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(
            {
                "status": "healthy" if healthy else "degraded",
                "checks": checks,
                "version": VERSION,
                "timestamp": timezone.now().isoformat(),
            },
            status=response_status,
        )

    def check_database(self):
        try:
            connection.ensure_connection()
        except Exception:
            logger.exception("Health check: database connection failed")
            return CHECK_ERROR
        return CHECK_OK

    def check_redis(self):
        from django.core.cache import cache

        try:
            cache.set("health:probe", "1", 5)
            cache.get("health:probe")
        except Exception:
            logger.exception("Health check: cache connection failed")
            return CHECK_ERROR
        return CHECK_OK

    def check_geocoding(self):
        provider = settings.GEOCODING_PROVIDER
        if provider == "openrouteservice":
            if not settings.OPENROUTESERVICE_API_KEY:
                return CHECK_NOT_CONFIGURED
        else:
            # Photon is keyless; keep its live probe opt-in.
            if not settings.PHOTON_HEALTHCHECK_ENABLED:
                return CHECK_NOT_CONFIGURED

        from apps.geocoding.exceptions import RateLimitError
        from apps.geocoding.services import _get_client

        try:
            _get_client().search("test", limit=1)
        except RateLimitError:
            return CHECK_RATE_LIMITED
        except Exception:
            logger.exception("Health check: geocoding provider request failed")
            return CHECK_ERROR
        return CHECK_OK

    def check_nws(self):
        # NWS is keyless; keep its live probe opt-in so /health/ stays fast.
        if not settings.NWS_HEALTHCHECK_ENABLED:
            return CHECK_NOT_CONFIGURED

        from apps.weather.clients.nws import WeatherClient
        from apps.weather.exceptions import WeatherRateLimitError

        try:
            WeatherClient().fetch_hourly(39.78, -89.65)
        except WeatherRateLimitError:
            return CHECK_RATE_LIMITED
        except Exception:
            logger.exception("Health check: nws request failed")
            return CHECK_ERROR
        return CHECK_OK
