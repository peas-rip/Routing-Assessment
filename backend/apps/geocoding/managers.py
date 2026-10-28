from django.db import models
from django.utils import timezone


class GeocodeCacheQuerySet(models.QuerySet):
    def valid(self):
        """Entries that have not passed their TTL."""
        return self.filter(expires_at__gt=timezone.now())

    def expired(self):
        return self.filter(expires_at__lte=timezone.now())
