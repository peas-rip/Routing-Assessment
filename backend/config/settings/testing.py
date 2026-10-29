"""Testing overrides: local-memory cache, eager Celery, throttling off.

The full suite (including the geospatial ``apps.routing`` models) runs against
PostGIS inside docker compose::

    docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.testing django pytest

When PostGIS/GeoDjango is unavailable (local runs without GDAL), the settings
fall back to in-memory SQLite and drop the geospatial app so the remaining
suites stay runnable; ``backend/conftest.py`` then skips the routing tests.
"""

from .base import *  # noqa: F401,F403

DEBUG = False

# Keep provider keys empty in tests so missing-credential behavior is deterministic.
OPENROUTESERVICE_API_KEY = ""
OPENWEATHERMAP_API_KEY = ""
PHOTON_HEALTHCHECK_ENABLED = False

POSTGIS_ENGINE = "django.contrib.gis.db.backends.postgis"


def _postgis_available() -> bool:
    """True when the configured engine is PostGIS and GEOS loads locally."""
    if DATABASES["default"]["ENGINE"] != POSTGIS_ENGINE:  # noqa: F405
        return False
    try:
        from django.contrib.gis import geos  # noqa: F401
    except Exception:
        return False
    return True


if _postgis_available():
    # Docker/CI: exercise the real PostGIS backend for every suite.
    DATABASES["default"].setdefault("TEST", {})  # noqa: F405
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
    # Geospatial models cannot be created on plain SQLite: drop the routing
    # app (and the GIS contrib app) so non-geospatial suites still run.
    # apps.weather and apps.risk reference routing models, so they go with them.
    INSTALLED_APPS = [  # noqa: F405
        app
        for app in INSTALLED_APPS  # noqa: F405
        if app not in ("apps.routing", "apps.weather", "apps.risk", "django.contrib.gis")
    ]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "spotter-test-cache",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Deterministic async behavior in tests.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Rate limiting remains configured (views declare throttle classes) but is set
# high enough that it never interferes with test execution.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "geocoding": "100000/min",
        "route-generate": "100000/min",
        "route-status": "100000/min",
        "weather": "100000/min",
        "risk": "100000/min",
        "heatmap": "100000/min",
    },
}

# Never redirect in tests (SECURE_SSL_REDIRECT would break plain http calls).
SECURE_SSL_REDIRECT = False
