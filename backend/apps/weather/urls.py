from django.urls import path

from . import views

urlpatterns = [
    path("checkpoints/", views.CheckpointWeatherView.as_view(), name="checkpoint-weather"),
    path("heatmap/", views.HeatmapView.as_view(), name="weather-heatmap"),
]
