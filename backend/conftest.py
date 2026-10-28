"""Pytest bootstrap for mixed GeoDjango/SQLite environments.

``apps.routing`` models need the PostGIS backend. When the active test
settings fall back to SQLite (no Docker/GeoDjango available), the routing
suite cannot run and is excluded from collection. Run it inside the compose
stack instead::

    docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.testing django pytest
"""

collect_ignore: list[str] = []

try:
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.testing")

    from django.conf import settings

    if not settings.configured:
        # Configure before pytest-django so the container's
        # DJANGO_SETTINGS_MODULE (development) never leaks into test runs.
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.testing"
        import django

        django.setup()

    if "apps.routing" not in settings.INSTALLED_APPS:
        collect_ignore.append("apps/routing/tests")

    # apps.weather depends on the routing models (FKs) and is stripped from
    # INSTALLED_APPS alongside them on plain SQLite.
    if "apps.weather" not in settings.INSTALLED_APPS:
        collect_ignore.append("apps/weather/tests")

    # apps.risk reads the routing + weather models and is stripped with them.
    if "apps.risk" not in settings.INSTALLED_APPS:
        collect_ignore.append("apps/risk/tests")
except Exception:  # pragma: no cover - settings unavailable: report via pytest
    pass
