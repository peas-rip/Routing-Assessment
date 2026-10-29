"""Shared fixtures: mocked Nominatim payloads."""

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

MOCK_SEARCH_RESPONSE = [
    {
        "place_id": 4726946,
        "display_name": "123 Main St, Springfield, IL 62701, United States",
        "lat": "39.7817",
        "lon": "-89.6501",
        "type": "house",
        "class": "building",
        "importance": 0.9,
        "address": {
            "house_number": "123",
            "road": "Main St",
            "city": "Springfield",
            "state": "IL",
            "postcode": "62701",
            "country": "United States",
        },
    },
    {
        "place_id": 4726947,
        "display_name": "456 Oak Ave, Springfield, IL 62701, United States",
        "lat": "39.7917",
        "lon": "-89.6401",
        "type": "house",
        "class": "building",
        "importance": 0.85,
        "address": {
            "house_number": "456",
            "road": "Oak Ave",
            "city": "Springfield",
            "state": "IL",
            "postcode": "62701",
            "country": "United States",
        },
    },
]

MOCK_REVERSE_RESPONSE = {
    "place_id": 4726946,
    "display_name": "123 Main St, Springfield, IL 62701, United States",
    "lat": "39.7817",
    "lon": "-89.6501",
    "type": "house",
    "class": "building",
    "address": {
        "house_number": "123",
        "road": "Main St",
        "city": "Springfield",
        "state": "IL",
        "postcode": "62701",
        "country": "United States",
    },
}

EXPECTED_FIRST_RESULT = {
    "place_id": "4726946",
    "display_name": "123 Main St, Springfield, IL 62701, United States",
    "latitude": 39.7817,
    "longitude": -89.6501,
    "address": {
        "house_number": "123",
        "road": "Main St",
        "city": "Springfield",
        "state": "IL",
        "postcode": "62701",
        "country": "United States",
    },
    "type": "house",
}


from apps.routing.tests.fixtures import make_route as _make_route  # noqa: E402
from apps.routing.tests.fixtures import make_route_request as _make_route_request  # noqa: E402


def make_route(route_request=None, **overrides):
    return _make_route(route_request, **overrides)


def make_route_request(**overrides):
    return _make_route_request(**overrides)
