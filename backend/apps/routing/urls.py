from django.urls import path

from . import views

urlpatterns = [
    path("generate/", views.GenerateView.as_view(), name="route-generate"),
    path("<uuid:route_id>/", views.RouteDetailView.as_view(), name="route-detail"),
]
