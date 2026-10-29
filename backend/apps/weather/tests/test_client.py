"""Open-Meteo client parsing and transport errors (docs/SERVICES/weather/TESTING.md)."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import requests
import responses
from django.test import TestCase

from apps.weather.clients.openmeteo import WeatherClient
from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError

from .fixtures import (
    MOCK_METEO_CLEAR,
    MOCK_METEO_MIXED,
    MOCK_METEO_RESPONSE,
    OPENMETEO_URL,
)


class WeatherClientTests(TestCase):
    def setUp(self):
        self.client = WeatherClient(timeout=10.0)

    @responses.activate
    def test_parse_rain_only(self):
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_RESPONSE)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        rain_fc = forecasts[0]
        self.assertEqual(rain_fc.precipitation_type, "rain")
        self.assertEqual(rain_fc.precipitation_rate_in_hr, 0.08)
        self.assertEqual(rain_fc.snowfall_rate_in_hr, 0)
        self.assertEqual(rain_fc.dt, datetime(2023, 12, 27, 8, 0, tzinfo=UTC))
        self.assertEqual(rain_fc.conditions, "slight rain")  # WMO 61
        self.assertEqual(rain_fc.wind_gust_mph, 18.0)

    @responses.activate
    def test_parse_snow_only(self):
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_RESPONSE)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        snow_fc = forecasts[1]
        self.assertEqual(snow_fc.precipitation_type, "snow")
        self.assertEqual(snow_fc.precipitation_rate_in_hr, 1.5)
        self.assertEqual(snow_fc.snowfall_rate_in_hr, 1.5)
        self.assertEqual(snow_fc.dt, datetime(2023, 12, 27, 9, 0, tzinfo=UTC))
        self.assertEqual(snow_fc.conditions, "heavy snow")  # WMO 75

    @responses.activate
    def test_parse_mixed_precipitation(self):
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_MIXED)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        fc = forecasts[0]
        self.assertEqual(fc.precipitation_type, "mixed")
        self.assertEqual(fc.precipitation_rate_in_hr, 0.7)  # rain + snow
        self.assertEqual(fc.snowfall_rate_in_hr, 0.5)

    @responses.activate
    def test_parse_no_precipitation(self):
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_CLEAR)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        fc = forecasts[0]
        self.assertEqual(fc.precipitation_type, "none")
        self.assertEqual(fc.precipitation_rate_in_hr, 0)
        self.assertEqual(fc.snowfall_rate_in_hr, 0)
        self.assertEqual(fc.conditions, "clear sky")  # WMO 0
        self.assertIsNone(fc.wind_gust_mph)

    @responses.activate
    def test_unknown_weather_code_maps_to_unknown(self):
        payload = {
            "hourly": {
                "time": ["2023-12-27T08:00"],
                "temperature_2m": [45.2],
                "relative_humidity_2m": [65],
                "wind_speed_10m": [12.5],
                "wind_direction_10m": [230],
                "wind_gusts_10m": [None],
                "rain": [0],
                "snowfall": [0],
                "weather_code": [1234],
            }
        }
        responses.add(responses.GET, OPENMETEO_URL, json=payload)

        fc = self.client.fetch_hourly(39.78, -89.65)[0]

        self.assertEqual(fc.conditions, "unknown")

    @responses.activate
    def test_units_are_imperial(self):
        """All values pass through in imperial units (mph, °F, inches)."""
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_RESPONSE)

        fc = self.client.fetch_hourly(39.78, -89.65)[0]

        self.assertEqual(fc.temp_f, 45.2)  # Fahrenheit
        self.assertEqual(fc.wind_speed_mph, 12.5)  # mph
        self.assertEqual(fc.precipitation_rate_in_hr, 0.08)  # inches/hr
        self.assertEqual(fc.humidity, 65)
        self.assertEqual(fc.wind_deg, 230)

    @responses.activate
    def test_request_sends_contract_params(self):
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_RESPONSE)

        self.client.fetch_hourly(39.78, -89.65)

        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        self.assertEqual(query["latitude"], ["39.78"])
        self.assertEqual(query["longitude"], ["-89.65"])
        self.assertEqual(query["temperature_unit"], ["fahrenheit"])
        self.assertEqual(query["wind_speed_unit"], ["mph"])
        self.assertEqual(query["precipitation_unit"], ["inch"])
        self.assertEqual(query["timezone"], ["UTC"])
        self.assertIn("weather_code", query["hourly"][0])

    @responses.activate
    def test_request_requires_no_api_key(self):
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_RESPONSE)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        self.assertTrue(forecasts)
        # No credential is attached to the outgoing request.
        self.assertNotIn("appid", responses.calls[0].request.url)

    @responses.activate
    def test_invalid_coordinates_map_to_provider_error(self):
        responses.add(
            responses.GET,
            OPENMETEO_URL,
            json={"error": True, "reason": "Invalid coordinate"},
            status=400,
        )

        with self.assertRaises(WeatherProviderError) as ctx:
            self.client.fetch_hourly(999, 999)

        self.assertEqual(ctx.exception.details["status_code"], 400)

    @responses.activate
    def test_rate_limit_maps_to_rate_limit_error(self):
        responses.add(
            responses.GET,
            OPENMETEO_URL,
            json={"message": "slow down"},
            status=429,
            headers={"Retry-After": "42"},
        )

        with self.assertRaises(WeatherRateLimitError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.retry_after, 42)
        self.assertEqual(ctx.exception.status_code, 429)

    @responses.activate
    def test_rate_limit_defaults_retry_after_to_60(self):
        responses.add(responses.GET, OPENMETEO_URL, json={}, status=429)

        with self.assertRaises(WeatherRateLimitError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.retry_after, 60)

    @responses.activate
    def test_server_error_maps_to_provider_error(self):
        responses.add(responses.GET, OPENMETEO_URL, json={"error": "boom"}, status=500)

        with self.assertRaises(WeatherProviderError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.details["status_code"], 500)
        self.assertEqual(ctx.exception.details["provider"], "open-meteo")

    @responses.activate
    def test_network_error_maps_to_provider_error(self):
        responses.add(responses.GET, OPENMETEO_URL, body=requests.Timeout("timed out"))

        with self.assertRaises(WeatherProviderError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.details["reason"], "Timeout")

    @responses.activate
    def test_timeout_maps_to_provider_error(self):
        responses.add(responses.GET, OPENMETEO_URL, body=requests.ConnectTimeout("connect timeout"))

        with self.assertRaises(WeatherProviderError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.details["reason"], "ConnectTimeout")

    @responses.activate
    def test_invalid_json_maps_to_provider_error(self):
        responses.add(responses.GET, OPENMETEO_URL, body="not json", status=200)

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_missing_hourly_block_maps_to_provider_error(self):
        responses.add(responses.GET, OPENMETEO_URL, json={"latitude": 39.78})

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_missing_required_series_maps_to_provider_error(self):
        # hourly is a dict but omits temperature_2m (a required series).
        responses.add(
            responses.GET,
            OPENMETEO_URL,
            json={"hourly": {"time": ["2023-12-27T08:00"], "relative_humidity_2m": [65]}},
        )

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_hourly_truncated_to_48_entries(self):
        hours = 50
        base = datetime(2023, 12, 27, 0, 0, tzinfo=UTC)
        time_series = [
            (base.replace(day=27 + h // 24, hour=h % 24)).strftime("%Y-%m-%dT%H:%M")
            for h in range(hours)
        ]
        payload = {
            "hourly": {
                "time": time_series,
                "temperature_2m": [45.2] * hours,
                "relative_humidity_2m": [65] * hours,
                "wind_speed_10m": [12.5] * hours,
                "wind_direction_10m": [230] * hours,
                "wind_gusts_10m": [None] * hours,
                "rain": [0] * hours,
                "snowfall": [0] * hours,
                "weather_code": [0] * hours,
            }
        }
        responses.add(responses.GET, OPENMETEO_URL, json=payload)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(len(forecasts), 48)

    @responses.activate
    def test_empty_series_maps_to_provider_error(self):
        responses.add(responses.GET, OPENMETEO_URL, json={"hourly": {"time": []}})

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_fetch_returns_raw_payload_for_debugging(self):
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_RESPONSE)

        forecasts, payload = self.client.fetch(39.78, -89.65)

        self.assertEqual(len(forecasts), 2)
        self.assertEqual(payload["timezone"], "UTC")
        self.assertIn("time", payload["hourly"])

    @responses.activate
    def test_visibility_always_none(self):
        """Open-Meteo exposes no visibility field, so it stays unset."""
        responses.add(responses.GET, OPENMETEO_URL, json=MOCK_METEO_RESPONSE)

        fc = self.client.fetch_hourly(39.78, -89.65)[0]

        self.assertIsNone(fc.visibility_mi)
