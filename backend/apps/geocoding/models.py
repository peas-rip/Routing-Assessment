import uuid

from django.db import models
from django.utils import timezone

from .managers import GeocodeCacheQuerySet


class QueryType(models.TextChoices):
    FORWARD = "forward", "Forward"
    REVERSE = "reverse", "Reverse"
    AUTOCOMPLETE = "autocomplete", "Autocomplete"


class GeocodeCache(models.Model):
    """Durable geocoding cache (docs/DATABASE_SCHEMA.md table 7).

    One row per query. ``raw_response`` stores the full provider payload so
    cache hits replay through the same parser as fresh results. The singular
    columns summarize the top result for admin/debugging convenience.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    query_text = models.TextField()
    query_type = models.CharField(max_length=20, choices=QueryType.choices)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    display_name = models.TextField(blank=True)
    address_components = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    objects = GeocodeCacheQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["query_text", "query_type"], name="idx_geocode_query"),
            models.Index(fields=["expires_at"], name="idx_geocode_expires"),
            models.Index(fields=["latitude", "longitude"], name="idx_geocode_location"),
        ]

    def __str__(self):
        return f"[{self.query_type}] {self.query_text}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()
