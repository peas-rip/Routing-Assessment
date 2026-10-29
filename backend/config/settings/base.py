"""Base settings shared across all environments."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", default="insecure-dev-secret-key-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    # Local apps
    "apps.geocoding",
    "apps.routing",
    "apps.weather",
    "apps.risk",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database (PostgreSQL + PostGIS in docker/production; DATABASE_URL driven)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

# GeoDjango: swap in the PostGIS engine whenever PostgreSQL is configured so
# the routing models (LineString/Point columns) work. Non-PostgreSQL databases
# keep the plain engine and cannot host apps.routing's geospatial models.
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"
    INSTALLED_APPS.append("django.contrib.gis")

# ---------------------------------------------------------------------------
# Cache / Broker (Redis)
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            # The DB cache tier remains the durable fallback, so a Redis outage
            # must degrade gracefully instead of failing requests.
            "IGNORE_EXCEPTIONS": True,
        },
        "KEY_PREFIX": "spotter",
    }
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
# Upstash free tier supports only DB 0; use a key prefix conceptually via the
# broker's namespace. TLS verification uses the system CA bundle.
if CELERY_BROKER_URL.startswith("rediss://"):
    CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": "required"}
if CELERY_RESULT_BACKEND.startswith("rediss://"):
    CELERY_REDIS_BACKEND_USE_SSL = {"ssl_cert_reqs": "required"}
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

# ---------------------------------------------------------------------------
# External APIs
# ---------------------------------------------------------------------------
OPENROUTESERVICE_API_KEY = env("OPENROUTESERVICE_API_KEY", default="")
OPENROUTESERVICE_BASE_URL = env(
    "OPENROUTESERVICE_BASE_URL", default="https://api.openrouteservice.org"
)
# Geocoding provider toggle: "openrouteservice" or "photon" (keyless).
GEOCODING_PROVIDER = env("GEOCODING_PROVIDER", default="openrouteservice")
PHOTON_BASE_URL = env("PHOTON_BASE_URL", default="https://photon.komoot.io")
PHOTON_HEALTHCHECK_ENABLED = env.bool("PHOTON_HEALTHCHECK_ENABLED", default=False)
OSRM_BASE_URL = env("OSRM_BASE_URL", default="https://router.project-osrm.org")
EXTERNAL_API_TIMEOUT = env.float("EXTERNAL_API_TIMEOUT", default=5.0)
# Routing calls carry full geometries + alternatives; they get a longer budget.
ROUTING_TIMEOUT = env.float("ROUTING_TIMEOUT", default=30.0)

OPENWEATHERMAP_API_KEY = env("OPENWEATHERMAP_API_KEY", default="")
OPENWEATHERMAP_BASE_URL = env(
    "OPENWEATHERMAP_BASE_URL", default="https://api.openweathermap.org/data/3.0/onecall"
)
NWS_BASE_URL = env("NWS_BASE_URL", default="https://api.weather.gov")
NWS_USER_AGENT = env("NWS_USER_AGENT", default="Routing-Assessment/1.0")
NWS_HEALTHCHECK_ENABLED = env.bool("NWS_HEALTHCHECK_ENABLED", default=False)
WEATHER_TIMEOUT = env.float("WEATHER_TIMEOUT", default=30.0)

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    # v1 is a single-user demo: public access, future JWT.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    # Rate limits from docs/API_CONTRACTS.md (per IP).
    "DEFAULT_THROTTLE_RATES": {
        "geocoding": "30/min",
        "route-generate": "10/min",
        "route-status": "60/min",
        "weather": "60/min",
        "risk": "30/min",
        "heatmap": "20/min",
    },
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
    # Contract payloads render decimals as JSON numbers (distance_miles, ...).
    "COERCE_DECIMAL_TO_STRING": False,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Weather-Aware Truck Routing API",
    "DESCRIPTION": "Geocoding, routing, weather and risk services for truck route planning.",
    "VERSION": "1.0.0",
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])

# ---------------------------------------------------------------------------
# Internationalization / Time
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "level": "INFO" if not DEBUG else "DEBUG",
        },
        "apps": {
            "level": "DEBUG" if DEBUG else "INFO",
        },
    },
}
