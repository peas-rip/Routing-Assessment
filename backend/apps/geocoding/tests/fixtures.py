"""Shared fixtures: mocked OpenRouteService (Pelias) payloads."""

MOCK_SEARCH_RESPONSE = {
    "geocoding": {"attribution": "test", "query": {"text": "springfield"}},
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-89.6501, 39.7817]},
            "properties": {
                "id": "4726946",
                "gid": "openstreetmap/address/4726946",
                "layer": "address",
                "source": "openstreetmap",
                "source_id": "4726946",
                "name": "123 Main St",
                "housenumber": "123",
                "street": "Main St",
                "locality": "Springfield",
                "region_a": "IL",
                "region": "Illinois",
                "postalcode": "62701",
                "country": "United States",
                "label": "123 Main St, Springfield, IL 62701, United States",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-89.6401, 39.7917]},
            "properties": {
                "id": "4726947",
                "gid": "openstreetmap/address/4726947",
                "layer": "address",
                "source": "openstreetmap",
                "source_id": "4726947",
                "name": "456 Oak Ave",
                "housenumber": "456",
                "street": "Oak Ave",
                "locality": "Springfield",
                "region_a": "IL",
                "postalcode": "62701",
                "country": "United States",
                "label": "456 Oak Ave, Springfield, IL 62701, United States",
            },
        },
    ],
}

MOCK_REVERSE_RESPONSE = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [-89.6501, 39.7817]},
    "properties": {
        "id": "4726946",
        "gid": "openstreetmap/address/4726946",
        "layer": "address",
        "source": "openstreetmap",
        "source_id": "4726946",
        "name": "123 Main St",
        "housenumber": "123",
        "street": "Main St",
        "locality": "Springfield",
        "region_a": "IL",
        "postalcode": "62701",
        "country": "United States",
        "label": "123 Main St, Springfield, IL 62701, United States",
    },
}

EXPECTED_FIRST_RESULT = {
    "place_id": "openstreetmap_4726946",
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
    "type": "address",
}
