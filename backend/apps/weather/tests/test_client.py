"""NWS client parsing and transport errors."""

import requests
import responses
from django.test import TestCase

from apps.weather.clients.nws import WeatherClient
from apps.weather.exceptions import WeatherProviderError, WeatherRateLimitError

from .fixtures import NWS_FORECAST_URL, NWS_POINTS_URL, register_nws


class WeatherClientTests(TestCase):
    def setUp(self):
        self.client = WeatherClient(timeout=10.0)

    @responses.activate
    def test_parse_rain(self):
        register_nws(pop=8, short="Light Rain")

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        fc = forecasts[0]
        self.assertEqual(fc.precipitation_type, "rain")
        self.assertEqual(fc.precipitation_rate_in_hr, 0.08)
        self.assertEqual(fc.snowfall_rate_in_hr, 0)
        self.assertEqual(fc.conditions, "Light Rain")

    @responses.activate
    def test_parse_snow(self):
        register_nws(pop=90, short="Heavy Snow")

        fc = self.client.fetch_hourly(39.78, -89.65)[0]

        self.assertEqual(fc.precipitation_type, "snow")
        self.assertEqual(fc.snowfall_rate_in_hr, 0.9)

    @responses.activate
    def test_parse_clear(self):
        register_nws(pop=0, short="Clear")

        fc = self.client.fetch_hourly(39.78, -89.65)[0]

        self.assertEqual(fc.precipitation_type, "none")
        self.assertEqual(fc.precipitation_rate_in_hr, 0)
        self.assertEqual(fc.conditions, "Clear")

    @responses.activate
    def test_two_step_lookup_points_then_forecast(self):
        register_nws()

        self.client.fetch_hourly(39.78, -89.65)

        # Both the /points resolution and the hourly forecast were requested.
        urls = [c.request.url for c in responses.calls]
        self.assertTrue(any("/points/" in u for u in urls))
        self.assertTrue(any("forecast/hourly" in u for u in urls))

    @responses.activate
    def test_requires_no_api_key(self):
        register_nws()

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        self.assertTrue(forecasts)
        self.assertNotIn("appid", responses.calls[0].request.url)

    @responses.activate
    def test_hourly_truncated_to_48(self):
        register_nws(hours=50)

        forecasts = self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(len(forecasts), 48)

    @responses.activate
    def test_points_missing_forecast_url_raises(self):
        responses.add(responses.GET, NWS_POINTS_URL, json={"properties": {}})

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_missing_periods_raises(self):
        responses.add(
            responses.GET, NWS_POINTS_URL, json={"properties": {"forecastHourly": NWS_FORECAST_URL}}
        )
        responses.add(responses.GET, NWS_FORECAST_URL, json={"properties": {}})

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)

    @responses.activate
    def test_rate_limit_raises_rate_limit_error(self):
        responses.add(
            responses.GET,
            NWS_POINTS_URL,
            json={},
            status=429,
            headers={"Retry-After": "30"},
        )

        with self.assertRaises(WeatherRateLimitError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.retry_after, 30)

    @responses.activate
    def test_server_error_raises_provider_error(self):
        responses.add(responses.GET, NWS_POINTS_URL, json={}, status=500)

        with self.assertRaises(WeatherProviderError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.details["status_code"], 500)

    @responses.activate
    def test_timeout_raises_provider_error(self):
        responses.add(responses.GET, NWS_POINTS_URL, body=requests.Timeout("slow"))

        with self.assertRaises(WeatherProviderError) as ctx:
            self.client.fetch_hourly(39.78, -89.65)

        self.assertEqual(ctx.exception.details["reason"], "Timeout")

    @responses.activate
    def test_invalid_json_raises_provider_error(self):
        responses.add(responses.GET, NWS_POINTS_URL, body="not json", status=200)

        with self.assertRaises(WeatherProviderError):
            self.client.fetch_hourly(39.78, -89.65)
