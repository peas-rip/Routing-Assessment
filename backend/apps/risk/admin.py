from django.contrib import admin

from .models import RiskAssessment, RouteScore


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ("id", "checkpoint", "combined_risk", "load_weight_lbs", "calculated_at")
    list_filter = ("combined_risk", "load_rule_applied")
    search_fields = ("id", "checkpoint__id")
    readonly_fields = ("calculated_at",)


@admin.register(RouteScore)
class RouteScoreAdmin(admin.ModelAdmin):
    list_display = ("id", "route", "severe_miles", "high_miles", "composite_score", "calculated_at")
    search_fields = ("id", "route__id")
    readonly_fields = ("calculated_at",)
