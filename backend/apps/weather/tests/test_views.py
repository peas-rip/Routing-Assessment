"""Checkpoint weather API contract (docs/API_CONTRACTS.md weather section)."""

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import responses
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.weather.models import WeatherObservation
from apps.weather.tasks import fetch_weather_for_checkpoints
from apps.weather.views import CheckpointWeatherView, HeatmapView

from .fixtures import (
    MOCK_OWM_RESPONSE,
    OWM_ONECALL_URL,
    checkpoint_ids_param,
    future_arrival,
    make_checkpoints,
    make_heatmap_route,
    make_observation,
    mock_onecall_response,
)

WEATHER_URL = "/api/v1/weather/checkpoints/"

# Exact field order of the documented checkpoint weather payload.
CONTRACT_FIELDS = [
    "checkpoint_id",
    "forecast_time",
    "temperature_f",
    "conditions",
    "wind_speed_mph",
    "wind_direction_deg",
    "precipitation_rate_in_hr",
    "precipitation_type",
    "snowfall_rate_in_hr",
    "humidity_pct",
    "visibility_mi",
]


@override_settings(OPENWEATHERMAP_API_KEY="test-key")
class CheckpointWeatherViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def get_weather(self, query: str):
        return self.client.get(f"{WEATHER_URL}?{query}")

    @responses.activate
    def test_returns_stored_weather_with_contract_shape(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        checkpoints = make_checkpoints()
        for checkpoint in checkpoints:
            make_observation(checkpoint)

        response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param(checkpoints)}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual(len(data), 3)
        first = data[0]
        self.assertEqual(list(first), CONTRACT_FIELDS)
        self.assertEqual(first["checkpoint_id"], str(checkpoints[0].id))
        self.assertEqual(first["temperature_f"], 45.2)
        self.assertEqual(first["conditions"], "light rain")
        self.assertEqual(first["wind_speed_mph"], 12.5)
        self.assertEqual(first["wind_direction_deg"], 230)
        self.assertEqual(first["precipitation_rate_in_hr"], 0.08)
        self.assertEqual(first["precipitation_type"], "rain")
        self.assertEqual(first["snowfall_rate_in_hr"], 0.0)
        self.assertEqual(first["humidity_pct"], 65)
        self.assertIsNone(first["visibility_mi"])
        self.assertEqual(
            datetime.fromisoformat(first["forecast_time"]), checkpoints[0].estimated_arrival
        )
        self.assertEqual(len(responses.calls), 0)  # stored data only

    @responses.activate
    def test_returns_stored_weather_for_all_checkpoints(self):
        checkpoints = make_checkpoints()
        for checkpoint in checkpoints:
            make_observation(checkpoint)

        response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param(checkpoints)}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual(
            [item["checkpoint_id"] for item in data], [str(cp.id) for cp in checkpoints]
        )

    def test_unknown_checkpoint_ids_return_weather_not_found(self):
        response = self.get_weather("checkpoint_ids=00000000-0000-0000-0000-000000000000")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        error = response.json()["error"]
        self.assertEqual(error["code"], "WEATHER_NOT_FOUND")

    @responses.activate
    def test_missing_observations_fetched_on_demand(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        checkpoints = make_checkpoints()

        response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param(checkpoints)}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["data"]), 3)
        self.assertEqual(WeatherObservation.objects.count(), 3)
        self.assertEqual(len(responses.calls), 2)  # deduplicated on-demand fetch

    @responses.activate
    def test_on_demand_provider_failure_without_stored_data_returns_502(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json={"error": "boom"}, status=500)
        checkpoints = make_checkpoints()

        response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param(checkpoints)}")

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        error = response.json()["error"]
        self.assertEqual(error["code"], "WEATHER_API_ERROR")
        self.assertEqual(error["details"]["provider"], "openweathermap")

    @responses.activate
    def test_on_demand_rate_limit_without_stored_data_returns_429(self):
        responses.add(
            responses.GET,
            OWM_ONECALL_URL,
            json={"message": "slow down"},
            status=429,
            headers={"Retry-After": "42"},
        )
        checkpoints = make_checkpoints()

        response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param(checkpoints)}")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        error = response.json()["error"]
        self.assertEqual(error["code"], "RATE_LIMITED")
        self.assertEqual(error["details"]["retry_after"], 42)

    @responses.activate
    def test_on_demand_failure_serves_stored_subset(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json={"error": "boom"}, status=500)
        checkpoints = make_checkpoints()
        make_observation(checkpoints[0])

        response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param(checkpoints)}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["checkpoint_id"], str(checkpoints[0].id))

    def test_stale_observations_served_and_refresh_queued(self):
        checkpoints = make_checkpoints()
        stale_at = timezone.now() - timedelta(minutes=16)
        for checkpoint in checkpoints:
            make_observation(checkpoint, fetched_at=stale_at)

        with patch.object(fetch_weather_for_checkpoints, "delay") as delay:
            response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param(checkpoints)}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["data"]), 3)
        delay.assert_called_once()
        self.assertEqual(set(delay.call_args[0][0]), {str(cp.id) for cp in checkpoints})

    def test_fresh_observations_do_not_queue_refresh(self):
        checkpoints = make_checkpoints()
        for checkpoint in checkpoints:
            make_observation(checkpoint)

        with patch.object(fetch_weather_for_checkpoints, "delay") as delay:
            response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param(checkpoints)}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        delay.assert_not_called()

    def test_stale_refresh_enqueue_failure_still_serves_data(self):
        checkpoints = make_checkpoints()
        stale_at = timezone.now() - timedelta(minutes=16)
        make_observation(checkpoints[0], fetched_at=stale_at)

        with patch.object(
            fetch_weather_for_checkpoints, "delay", side_effect=RuntimeError("broker down")
        ):
            response = self.get_weather(f"checkpoint_ids={checkpoint_ids_param([checkpoints[0]])}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["data"]), 1)

    def test_missing_checkpoint_ids_param_returns_400(self):
        response = self.client.get(WEATHER_URL)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_invalid_checkpoint_id_returns_400(self):
        response = self.get_weather("checkpoint_ids=not-a-uuid")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_blank_checkpoint_ids_returns_400(self):
        response = self.get_weather("checkpoint_ids=%20,%20")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_duplicate_checkpoint_ids_return_one_item(self):
        checkpoints = make_checkpoints()
        checkpoint = checkpoints[0]
        make_observation(checkpoint)

        response = self.get_weather(f"checkpoint_ids={checkpoint.id},{checkpoint.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["data"]), 1)

    @responses.activate
    def test_forecast_time_param_refilters_and_fetches_at_that_time(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)
        checkpoints = make_checkpoints()
        make_observation(checkpoints[0])  # stored at the ETA (hour 8)
        explicit = future_arrival(9)  # different time: stored row must not match

        response = self.client.get(
            WEATHER_URL,
            {
                "checkpoint_ids": checkpoint_ids_param([checkpoints[0]]),
                "forecast_time": explicit.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(datetime.fromisoformat(data[0]["forecast_time"]), explicit)
        # Hour-9 fixture entry is the snow forecast.
        self.assertEqual(data[0]["precipitation_type"], "snow")
        stored = WeatherObservation.objects.filter(checkpoint=checkpoints[0])
        self.assertEqual(stored.count(), 2)  # ETA row + explicit-time row

    def test_throttle_scope_is_weather(self):
        self.assertEqual(CheckpointWeatherView.throttle_scope, "weather")


HEATMAP_URL = "/api/v1/weather/heatmap/"


@override_settings(OPENWEATHERMAP_API_KEY="test-key")
class HeatmapViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.route = make_heatmap_route()

    def get_heatmap(self, query):
        return self.client.get(f"{HEATMAP_URL}?{query}")

    @responses.activate
    def test_contract_shape(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=mock_onecall_response())

        response = self.get_heatmap(f"route_id={self.route.id}&hour=6")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()["data"]
        self.assertEqual(
            list(data),
            ["route_id", "forecast_hour", "bounds", "resolution_miles", "grid", "generated_at"],
        )
        self.assertEqual(data["route_id"], str(self.route.id))
        self.assertEqual(data["forecast_hour"], 6)
        self.assertEqual(data["resolution_miles"], 10.0)  # documented default
        self.assertEqual(list(data["bounds"]), ["north", "south", "east", "west"])
        first = data["grid"][0]
        self.assertEqual(list(first), ["lat", "lon", "risk_level", "risk_score"])
        self.assertEqual(first["risk_level"], "low")

    @responses.activate
    def test_custom_resolution_is_honored(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=mock_onecall_response())

        response = self.get_heatmap(f"route_id={self.route.id}&hour=6&resolution_miles=20")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"]["resolution_miles"], 20.0)

    def test_hour_out_of_range_returns_400(self):
        response = self.get_heatmap(f"route_id={self.route.id}&hour=49")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_missing_hour_returns_400(self):
        response = self.get_heatmap(f"route_id={self.route.id}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")

    def test_invalid_resolution_returns_400(self):
        response = self.get_heatmap(f"route_id={self.route.id}&hour=6&resolution_miles=4")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_route_returns_404(self):
        response = self.get_heatmap(f"route_id={uuid.uuid4()}&hour=6")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["error"]["code"], "ROUTE_NOT_FOUND")

    def test_throttle_scope_is_heatmap(self):
        self.assertEqual(HeatmapView.throttle_scope, "heatmap")
