from django.urls import path

from .views import ReverseView, SearchView

app_name = "geocoding"

urlpatterns = [
    path("search/", SearchView.as_view(), name="search"),
    path("reverse/", ReverseView.as_view(), name="reverse"),
]
