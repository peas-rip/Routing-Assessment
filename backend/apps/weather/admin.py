from django.contrib import admin

from .models import HeatmapCache, WeatherObservation


@admin.register(WeatherObservation)
class WeatherObservationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "checkpoint",
        "forecast_time",
        "temperature_f",
        "precipitation_type",
        "fetched_at",
    )
    list_filter = ("precipitation_type", "source")
    search_fields = ("id", "checkpoint__id")
    readonly_fields = ("fetched_at",)


@admin.register(HeatmapCache)
class HeatmapCacheAdmin(admin.ModelAdmin):
    list_display = ("id", "route", "forecast_hour", "resolution_miles", "expires_at")
    list_filter = ("forecast_hour",)
    search_fields = ("id", "route__id")
    readonly_fields = ("created_at",)
