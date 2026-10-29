import pytest

from apps.weather.clients.nws import clear_points_cache


@pytest.fixture(autouse=True)
def _clear_nws_points_cache():
    clear_points_cache()
    yield
    clear_points_cache()
