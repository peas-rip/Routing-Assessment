from django.urls import path

from . import views

urlpatterns = [
    path("calculate/", views.CalculateView.as_view(), name="risk-calculate"),
    path(
        "recommendation/<uuid:route_id>/",
        views.RecommendationView.as_view(),
        name="risk-recommendation",
    ),
]
