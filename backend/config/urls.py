from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from common.health import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", HealthCheckView.as_view(), name="health"),
    path("api/v1/geocoding/", include("apps.geocoding.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

# The routing app hosts geospatial models: it is dropped from INSTALLED_APPS
# when PostGIS/GeoDjango is unavailable (local runs without Docker), and its
# URLs cannot be imported then either.
if "apps.routing" in settings.INSTALLED_APPS:
    urlpatterns.append(path("api/v1/routes/", include("apps.routing.urls")))

# apps.weather depends on the routing models; it is dropped together with
# them when PostGIS/GeoDjango is unavailable.
if "apps.weather" in settings.INSTALLED_APPS:
    urlpatterns.append(path("api/v1/weather/", include("apps.weather.urls")))

# apps.risk reads the routing + weather models and is dropped with them.
if "apps.risk" in settings.INSTALLED_APPS:
    urlpatterns.append(path("api/v1/risk/", include("apps.risk.urls")))
