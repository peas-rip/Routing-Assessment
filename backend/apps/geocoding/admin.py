from django.contrib import admin

from .models import GeocodeCache


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(admin.ModelAdmin):
    list_display = (
        "query_type",
        "query_text",
        "display_name",
        "source",
        "created_at",
        "expires_at",
    )
    list_filter = ("query_type", "source")
    search_fields = ("query_text", "display_name")
    readonly_fields = ("created_at",)
