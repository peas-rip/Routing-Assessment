from django.contrib import admin

from .models import Checkpoint, Route, RouteRequest


class CheckpointInline(admin.TabularInline):
    model = Checkpoint
    extra = 0
    readonly_fields = (
        "sequence",
        "mile_marker",
        "latitude",
        "longitude",
        "estimated_arrival",
        "created_at",
    )
    can_delete = False


@admin.register(RouteRequest)
class RouteRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "departure_time", "load_weight_lbs", "created_at")
    list_filter = ("status",)
    search_fields = ("origin_address", "destination_address")
    readonly_fields = ("created_at", "updated_at", "completed_at", "progress")


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "route_index", "name", "distance_miles", "duration_minutes")
    list_filter = ("name",)
    search_fields = ("id", "request__origin_address", "request__destination_address")
    inlines = [CheckpointInline]
    readonly_fields = ("created_at",)


@admin.register(Checkpoint)
class CheckpointAdmin(admin.ModelAdmin):
    list_display = ("id", "route", "sequence", "mile_marker", "estimated_arrival")
    list_filter = ("estimated_arrival",)
    readonly_fields = ("created_at",)
