from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import DatabaseError
from django.test import TestCase
from django.utils import timezone

from apps.geocoding import services
from apps.geocoding.clients.nominatim import GeocodeResponse
from apps.geocoding.exceptions import GeocodingNotFoundError, GeocodingProviderError
from apps.geocoding.models import GeocodeCache, QueryType

from .fixtures import EXPECTED_FIRST_RESULT, MOCK_REVERSE_RESPONSE, MOCK_SEARCH_RESPONSE


class GeocodingServiceTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.client_mock = Mock()
        self.search_response = GeocodeResponse(
            results=[
                {
                    "place_id": "4726946",
                    "display_name": "123 Main St, Springfield, IL 62701, United States",
                    "latitude": 39.7817,
                    "longitude": -89.6501,
                    "address": EXPECTED_FIRST_RESULT["address"],
                    "type": "house",
                },
                {
                    "place_id": "4726947",
                    "display_name": "456 Oak Ave, Springfield, IL 62701, United States",
                    "latitude": 39.7917,
                    "longitude": -89.6401,
                    "address": {"house_number": "456", "road": "Oak Ave"},
                    "type": "house",
                },
            ],
            raw=MOCK_SEARCH_RESPONSE,
        )
        self.reverse_result = {
            "place_id": "4726946",
            "display_name": "123 Main St, Springfield, IL 62701, United States",
            "latitude": 39.7817,
            "longitude": -89.6501,
            "address": EXPECTED_FIRST_RESULT["address"],
            "type": "house",
        }
        self.reverse_response = GeocodeResponse(
            results=[self.reverse_result], raw=MOCK_REVERSE_RESPONSE
        )
        self.client_mock.search.return_value = self.search_response
        self.client_mock.reverse.return_value = self.reverse_response
        self._original_get_client = services._get_client
        services._get_client = lambda: self.client_mock

    def tearDown(self):
        services._get_client = self._original_get_client
        cache.clear()


class SearchServiceTests(GeocodingServiceTestBase):
    def test_cache_miss_calls_provider_and_returns_results(self):
        results, was_cached = services.search("Springfield", limit=2)

        self.assertFalse(was_cached)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["place_id"], "4726946")
        self.client_mock.search.assert_called_once_with("Springfield", limit=2, lat=None, lon=None)

    def test_cache_miss_stores_db_row(self):
        services.search("Springfield", limit=2)

        entry = GeocodeCache.objects.get(
            query_text="springfield", query_type=QueryType.AUTOCOMPLETE
        )
        self.assertEqual(entry.display_name, EXPECTED_FIRST_RESULT["display_name"])
        self.assertEqual(entry.latitude, 39.7817)
        self.assertEqual(entry.raw_response, MOCK_SEARCH_RESPONSE)
        self.assertEqual(entry.source, "nominatim")
        self.assertGreater(entry.expires_at, timezone.now() + timedelta(days=29))

    def test_second_call_served_from_redis_cache(self):
        services.search("Springfield", limit=2)
        results, was_cached = services.search("Springfield", limit=2)

        self.assertTrue(was_cached)
        self.assertEqual(len(results), 2)
        self.client_mock.search.assert_called_once()

    def test_query_normalization_reuses_cache(self):
        services.search("  Springfield  ", limit=2)
        results, was_cached = services.search("SPRINGFIELD", limit=2)

        self.assertTrue(was_cached)
        self.assertEqual(len(results), 2)
        self.client_mock.search.assert_called_once()

    def test_db_cache_fallback_when_redis_empty(self):
        services.search("Springfield", limit=2)
        cache.clear()  # Simulate Redis restart / eviction

        results, was_cached = services.search("Springfield", limit=2)

        self.assertTrue(was_cached)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], self.search_response.results[0])
        self.client_mock.search.assert_called_once()  # Not called again

    def test_db_cache_is_sliced_to_requested_limit(self):
        services.search("Springfield", limit=2)
        cache.clear()

        results, _ = services.search("Springfield", limit=1)

        self.assertEqual(len(results), 1)
        self.client_mock.search.assert_called_once()

    def test_db_cache_refetched_when_insufficient_results(self):
        services.search("Springfield", limit=2)
        cache.clear()

        results, was_cached = services.search("Springfield", limit=5)

        self.assertFalse(was_cached)
        self.assertEqual(self.client_mock.search.call_count, 2)
        self.assertEqual(len(results), 2)  # Provider only had 2

    def test_expired_db_cache_triggers_provider_call(self):
        GeocodeCache.objects.create(
            query_text="springfield",
            query_type=QueryType.AUTOCOMPLETE,
            display_name="old",
            address_components={},
            raw_response=MOCK_SEARCH_RESPONSE,
            source="nominatim",
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        results, was_cached = services.search("Springfield", limit=2)

        self.assertFalse(was_cached)
        self.assertEqual(len(results), 2)
        self.client_mock.search.assert_called_once()
        entry = GeocodeCache.objects.get(query_text="springfield")
        self.assertGreater(entry.expires_at, timezone.now())

    def test_different_limits_use_separate_cache_entries(self):
        services.search("Springfield", limit=2)
        services.search("Springfield", limit=2)
        self.assertEqual(self.client_mock.search.call_count, 1)  # Redis hit

        # A larger limit is a distinct cache entry and the DB row (2 results)
        # is insufficient, so the provider is queried again.
        services.search("Springfield", limit=5)
        self.assertEqual(self.client_mock.search.call_count, 2)

    def test_provider_error_propagates(self):
        self.client_mock.search.side_effect = GeocodingProviderError()

        with self.assertRaises(GeocodingProviderError):
            services.search("Springfield")

    def test_cache_failure_does_not_break_search(self):
        broken_cache = Mock()
        broken_cache.get.side_effect = ConnectionError("redis down")
        broken_cache.set.side_effect = ConnectionError("redis down")

        with patch.object(services, "cache", broken_cache):
            results, was_cached = services.search("Springfield", limit=2)

        self.assertFalse(was_cached)
        self.assertEqual(len(results), 2)
        self.assertTrue(GeocodeCache.objects.filter(query_text="springfield").exists())

    def test_empty_provider_results_are_valid(self):
        self.client_mock.search.return_value = GeocodeResponse(results=[], raw={"features": []})

        results, was_cached = services.search("Nowhere", limit=5)

        self.assertEqual(results, [])
        self.assertFalse(was_cached)

    def test_db_cache_write_failure_does_not_break_search(self):
        with patch.object(
            services.GeocodeCache.objects, "update_or_create", side_effect=DatabaseError("down")
        ):
            results, was_cached = services.search("Springfield", limit=2)

        self.assertFalse(was_cached)
        self.assertEqual(len(results), 2)


class ReverseServiceTests(GeocodingServiceTestBase):
    def test_reverse_cache_miss_calls_provider(self):
        result, was_cached = services.reverse(39.7817, -89.6501)

        self.assertFalse(was_cached)
        self.assertEqual(result["place_id"], "4726946")
        self.client_mock.reverse.assert_called_once_with(39.7817, -89.6501)

    def test_reverse_stores_db_row_with_coordinate_key(self):
        services.reverse(39.7817, -89.6501)

        entry = GeocodeCache.objects.get(query_type=QueryType.REVERSE)
        self.assertEqual(entry.query_text, "39.78170,-89.65010")
        self.assertEqual(entry.raw_response, MOCK_REVERSE_RESPONSE)

    def test_reverse_second_call_served_from_cache(self):
        services.reverse(39.7817, -89.6501)
        result, was_cached = services.reverse(39.7817, -89.6501)

        self.assertTrue(was_cached)
        self.assertEqual(result["place_id"], "4726946")
        self.client_mock.reverse.assert_called_once()

    def test_reverse_db_fallback_when_redis_empty(self):
        services.reverse(39.7817, -89.6501)
        cache.clear()

        result, was_cached = services.reverse(39.7817, -89.6501)

        self.assertTrue(was_cached)
        self.assertEqual(result, self.reverse_result)
        self.client_mock.reverse.assert_called_once()

    def test_reverse_without_provider_result_raises_not_found(self):
        self.client_mock.reverse.return_value = None

        with self.assertRaises(GeocodingNotFoundError) as ctx:
            services.reverse(0.0, 0.0)

        self.assertEqual(ctx.exception.code, "GEOCODING_FAILED")
        self.assertEqual(ctx.exception.details, {"latitude": 0.0, "longitude": 0.0})
