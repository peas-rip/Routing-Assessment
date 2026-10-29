from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.geocoding.models import GeocodeCache, QueryType


class GeocodeCacheModelTests(TestCase):
    def _make_cache(self, **overrides):
        defaults = {
            "query_text": "springfield",
            "query_type": QueryType.AUTOCOMPLETE,
            "display_name": "Springfield, IL",
            "address_components": {"city": "Springfield"},
            "raw_response": {"features": []},
            "source": "nominatim",
            "expires_at": timezone.now() + timedelta(days=30),
        }
        defaults.update(overrides)
        return GeocodeCache.objects.create(**defaults)

    def test_is_expired_false_for_future_expiry(self):
        cache_entry = self._make_cache()
        self.assertFalse(cache_entry.is_expired)

    def test_is_expired_true_for_past_expiry(self):
        cache_entry = self._make_cache(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(cache_entry.is_expired)

    def test_valid_queryset_excludes_expired(self):
        fresh = self._make_cache(query_text="fresh")
        self._make_cache(query_text="stale", expires_at=timezone.now() - timedelta(minutes=1))

        results = GeocodeCache.objects.valid()
        self.assertEqual([entry.query_text for entry in results], ["fresh"])
        self.assertEqual(fresh.query_text, "fresh")

    def test_expired_queryset_returns_only_expired(self):
        self._make_cache(query_text="fresh")
        self._make_cache(query_text="stale", expires_at=timezone.now() - timedelta(minutes=1))

        results = list(GeocodeCache.objects.expired())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].query_text, "stale")

    def test_str_includes_type_and_query(self):
        cache_entry = self._make_cache()
        self.assertEqual(str(cache_entry), "[autocomplete] springfield")
