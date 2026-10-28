"""OWM client parsing and transport errors (docs/SERVICES/weather/TESTING.md)."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import requests
import responses
from django.test import TestCase

from apps.weather.clients.openweathermap import WeatherClient
from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError

from .fixtures import (
    MOCK_OWM_CLEAR,
    MOCK_OWM_MIXED,
    MOCK_OWM_RESPONSE,
    OWM_ONECALL_URL,
)


class WeatherClientTests(TestCase):
    def setUp(self):
        self.client = WeatherClient(api_key="test-key", timeout=10.0)

    @responses.activate
    def test_parse_rain_only(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        rain_fc = forecasts[0]
        self.assertEqual(rain_fc.precipitation_type, "rain")
        self.assertEqual(rain_fc.precipitation_rate_in_hr, 0.08)
        self.assertEqual(rain_fc.snowfall_rate_in_hr, 0)
        self.assertEqual(rain_fc.dt, datetime(2023, 12, 27, 8, 0, tzinfo=UTC))
        self.assertEqual(rain_fc.conditions, "light rain")
        self.assertEqual(rain_fc.wind_gust_mph, 18.0)

    @responses.activate
    def test_parse_snow_only(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        snow_fc = forecasts[1]
        self.assertEqual(snow_fc.precipitation_type, "snow")
        self.assertEqual(snow_fc.precipitation_rate_in_hr, 1.5)
        self.assertEqual(snow_fc.snowfall_rate_in_hr, 1.5)
        self.assertEqual(snow_fc.dt, datetime(2023, 12, 27, 9, 0, tzinfo=UTC))

    @responses.activate
    def test_parse_mixed_precipitation(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_MIXED)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        fc = forecasts[0]
        self.assertEqual(fc.precipitation_type, "mixed")
        self.assertEqual(fc.precipitation_rate_in_hr, 0.7)  # rain + snow
        self.assertEqual(fc.snowfall_rate_in_hr, 0.5)

    @responses.activate
    def test_parse_no_precipitation(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_CLEAR)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        fc = forecasts[0]
        self.assertEqual(fc.precipitation_type, "none")
        self.assertEqual(fc.precipitation_rate_in_hr, 0)
        self.assertEqual(fc.snowfall_rate_in_hr, 0)
        self.assertEqual(fc.conditions, "")
        self.assertIsNone(fc.wind_gust_mph)

    @responses.activate
    def test_units_are_imperial(self):
        """All values pass through in imperial units (mph, °F, inches)."""
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)

        fc = self.client.fetch_hourly(39.78, -89.65)[0]

        self.assertEqual(fc.temp_f, 45.2)  # Fahrenheit
        self.assertEqual(fc.wind_speed_mph, 12.5)  # mph
        self.assertEqual(fc.precipitation_rate_in_hr, 0.08)  # inches/hr
        self.assertEqual(fc.humidity, 65)
        self.assertEqual(fc.wind_deg, 230)

    @responses.activate
    def test_request_sends_contract_params(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)

        self.client.fetch_hourly(39.78, -89.65)

        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        self.assertEqual(query["lat"], ["39.78"])
        self.assertEqual(query["lon"], ["-89.65"])
        self.assertEqual(query["exclude"], ["minutely,daily,alerts"])
        self.assertEqual(query["units"], ["imperial"])
        self.assertEqual(query["appid"], ["test-key"])

    @responses.activate
    def test_missing_api_key_raises_before_request(self):
        client = WeatherClient(api_key="")

        with self.assertRaises(WeatherProviderError) as ctx:
            client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.code, "WEATHER_API_ERROR")
        self.assertEqual(len(responses.calls), 0)

    @responses.activate
    def test_rate_limit_maps_to_rate_limit_error(self):
        responses.add(
            responses.GET,
            OWM_ONECALL_URL,
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
        responses.add(responses.GET, OWM_ONECALL_URL, json={}, status=429)

        with self.assertRaises(WeatherRateLimitError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.retry_after, 60)

    @responses.activate
    def test_server_error_maps_to_provider_error(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json={"error": "boom"}, status=500)

        with self.assertRaises(WeatherProviderError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.details["status_code"], 500)
        self.assertEqual(ctx.exception.details["provider"], "openweathermap")

    @responses.activate
    def test_network_error_maps_to_provider_error(self):
        responses.add(responses.GET, OWM_ONECALL_URL, body=requests.Timeout("timed out"))

        with self.assertRaises(WeatherProviderError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.details["reason"], "Timeout")

    @responses.activate
    def test_invalid_json_maps_to_provider_error(self):
        responses.add(responses.GET, OWM_ONECALL_URL, body="not json", status=200)

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_missing_hourly_block_maps_to_provider_error(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json={"lat": 39.78})

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_malformed_hourly_entry_maps_to_provider_error(self):
        responses.add(
            responses.GET,
            OWM_ONECALL_URL,
            json={"hourly": [{"dt": 1703664000, "humidity": 65}]},  # no temp
        )

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_hourly_truncated_to_48_entries(self):
        entry = {
            "dt": 1703664000,
            "temp": 45.2,
            "humidity": 65,
            "wind_speed": 12.5,
            "wind_deg": 230,
            "weather": [],
        }
        responses.add(responses.GET, OWM_ONECALL_URL, json={"hourly": [entry] * 50})

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(len(forecasts), 48)
        self.assertEqual(forecasts[0].conditions, "")  # empty weather list

    @responses.activate
    def test_fetch_returns_raw_payload_for_debugging(self):
        responses.add(responses.GET, OWM_ONECALL_URL, json=MOCK_OWM_RESPONSE)

        forecasts, payload = self.client.fetch(39.78, -89.65)

        self.assertEqual(len(forecasts), 2)
        self.assertEqual(payload["timezone"], "America/Chicago")
        self.assertEqual(len(payload["hourly"]), 2)

    @responses.activate
    def test_visibility_converted_to_miles_when_present(self):
        entry = {
            "dt": 1703664000,
            "temp": 45.2,
            "humidity": 65,
            "wind_speed": 12.5,
            "wind_deg": 230,
            "weather": [],
            "visibility": 16093.44,  # meters == 10 miles
        }
        responses.add(responses.GET, OWM_ONECALL_URL, json={"hourly": [entry]})

        fc = self.client.fetch_hourly(39.78, -89.65)[0]

        self.assertEqual(fc.visibility_mi, 10.0)
