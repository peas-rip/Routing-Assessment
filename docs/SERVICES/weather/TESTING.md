# Testing Guide: Weather Service

## Test Strategy

| Test Type | Coverage Target | Priority |
|-----------|-----------------|----------|
| Unit Tests | 95% | Critical |
| Integration Tests | 90% | High |
| Contract Tests | 100% | Critical |

## Test Organization

```
apps/weather/tests/
├── __init__.py
├── fixtures.py              # Mock OWM responses
├── test_models.py
├── test_client.py           # OWM client parsing
├── test_services.py         # Bulk fetch, deduplication, heatmap
├── test_tasks.py            # Celery tasks
├── test_views.py            # API endpoints
└── test_integration.py      # Full flow tests
```

## Unit Tests

### Client Tests (`test_client.py`) - CRITICAL
```python
class TestWeatherClient:
    @pytest.fixture
    def client(self):
        return WeatherClient(api_key="test-key", timeout=10.0)
    
    @pytest.fixture
    def mock_owm_response(self):
        return {
            "lat": 39.78, "lon": -89.65, "timezone": "America/Chicago",
            "hourly": [{
                "dt": 1703664000, "temp": 45.2, "humidity": 65,
                "wind_speed": 12.5, "wind_deg": 230, "wind_gust": 18.0,
                "weather": [{"id": 500, "main": "Rain", "description": "light rain"}],
                "pop": 0.3, "rain": {"1h": 0.08}
            }, {
                "dt": 1703667600, "temp": 32.1, "humidity": 85,
                "wind_speed": 38.0, "wind_deg": 310, "wind_gust": 45.0,
                "weather": [{"id": 600, "main": "Snow", "description": "heavy snow"}],
                "pop": 0.9, "snow": {"1h": 1.5}
            }]
        }
    
    def test_parse_rain_only(self, client, mock_owm_response, httpx_mock):
        httpx_mock.add_response(json=mock_owm_response)
        forecasts = client.fetch_hourly(39.78, -89.65)
        
        rain_fc = forecasts[0]
        assert rain_fc.precipitation_type == 'rain'
        assert rain_fc.precipitation_rate_in_hr == 0.08
        assert rain_fc.snowfall_rate_in_hr == 0
    
    def test_parse_snow_only(self, client, mock_owm_response, httpx_mock):
        httpx_mock.add_response(json=mock_owm_response)
        forecasts = client.fetch_hourly(39.78, -89.65)
        
        snow_fc = forecasts[1]
        assert snow_fc.precipitation_type == 'snow'
        assert snow_fc.precipitation_rate_in_hr == 1.5
        assert snow_fc.snowfall_rate_in_hr == 1.5
    
    def test_parse_mixed_precipitation(self, client, httpx_mock):
        mixed = {
            "hourly": [{
                "dt": 1703664000, "temp": 34.0, "humidity": 80,
                "wind_speed": 10.0, "wind_deg": 180,
                "weather": [{"main": "Rain"}],
                "rain": {"1h": 0.2}, "snow": {"1h": 0.5}
            }]
        }
        httpx_mock.add_response(json=mixed)
        forecasts = client.fetch_hourly(39.78, -89.65)
        
        fc = forecasts[0]
        assert fc.precipitation_type == 'mixed'
        assert fc.precipitation_rate_in_hr == 0.7
        assert fc.snowfall_rate_in_hr == 0.5
    
    def test_parse_no_precipitation(self, client, httpx_mock):
        clear = {"hourly": [{"dt": 1703664000, "temp": 70, "humidity": 40, "wind_speed": 5, "wind_deg": 90, "weather": [{"main": "Clear"}]}]}
        httpx_mock.add_response(json=clear)
        forecasts = client.fetch_hourly(39.78, -89.65)
        
        fc = forecasts[0]
        assert fc.precipitation_type == 'none'
        assert fc.precipitation_rate_in_hr == 0
        assert fc.snowfall_rate_in_hr == 0
    
    def test_units_imperial(self, client, mock_owm_response, httpx_mock):
        """Verify all units are imperial (mph, °F, inches)."""
        httpx_mock.add_response(json=mock_owm_response)
        forecasts = client.fetch_hourly(39.78, -89.65)
        
        fc = forecasts[0]
        assert fc.temp_f == 45.2  # Fahrenheit
        assert fc.wind_speed_mph == 12.5  # mph
        assert fc.precipitation_rate_in_hr == 0.08  # inches/hr
```

### Service Tests (`test_services.py`)
```python
class TestBulkFetchDeduplication:
    @pytest.fixture
    def checkpoints(self):
        """Create checkpoints with some duplicate (lat, lon, hour) combinations."""
        base_time = timezone.make_aware(datetime(2026, 10, 27, 8, 0, 0))
        
        # 3 checkpoints, but 2 share same rounded coords + hour
        return [
            Checkpoint(id=uuid4(), latitude=39.7817, longitude=-89.6501, estimated_arrival=base_time),
            Checkpoint(id=uuid4(), latitude=39.7817, longitude=-89.6501, estimated_arrival=base_time),  # Duplicate
            Checkpoint(id=uuid4(), latitude=40.0000, longitude=-89.0000, estimated_arrival=base_time + timedelta(hours=1)),
        ]
    
    @pytest.mark.asyncio
    async def test_deduplicates_by_rounded_coords_and_hour(self, checkpoints, mock_weather_client):
        """Should only make 2 API calls for 3 checkpoints with 1 duplicate."""
        observations = await fetch_weather_batch(checkpoints)
        
        # Should have results for all 3 checkpoints
        assert len(observations) == 3
        
        # But only 2 unique (lat, lon, hour) combinations fetched
        assert mock_weather_client.fetch_hourly.call_count == 2
    
    @pytest.mark.asyncio
    async def test_partial_failure_continues(self, checkpoints, mock_weather_client):
        """One failed fetch shouldn't block others."""
        # Make second call fail
        async def side_effect(*args, **kwargs):
            if args[:2] == (39.78, -89.65):
                raise Exception("API Error")
            return [HourlyForecast(...)]
        
        mock_weather_client.fetch_hourly.side_effect = side_effect
        observations = await fetch_weather_batch(checkpoints)
        
        # Should still have results for successful call
        assert len(observations) >= 1


class TestHeatmapGeneration:
    @pytest.fixture
    def route(self):
        line = LineString([(-89.65, 39.78), (-87.63, 41.88)])
        route = Route.objects.create(geometry=line, distance_miles=Decimal('200'), duration_minutes=240, ...)
        return route
    
    def test_grid_generation_within_bounds(self, route, mock_weather_client):
        """Grid points should be within route corridor."""
        heatmap = generate_heatmap_grid(route, 6, resolution_miles=10)
        
        assert len(heatmap.grid_data) > 0
        assert len(heatmap.grid_data) <= 5000
        
        for point in heatmap.grid_data:
            assert 'lat' in point and 'lon' in point
            assert 'risk_level' in point
            assert point['risk_level'] in ['low', 'moderate', 'high', 'severe', 'no_travel']
            assert 1.0 <= point['risk_score'] <= 5.0
    
    def test_resolution_limits_points(self, route, mock_weather_client):
        """High resolution should be auto-reduced if too many points."""
        heatmap = generate_heatmap_grid(route, 6, resolution_miles=5)
        
        assert len(heatmap.grid_data) <= 5000
        assert heatmap.resolution_miles >= Decimal('5.0')
    
    def test_heatmap_cache_expiry(self, route, mock_weather_client):
        heatmap = generate_heatmap_grid(route, 6, 10)
        
        assert heatmap.expires_at > timezone.now()
        assert heatmap.expires_at <= timezone.now() + timedelta(minutes=15)
```

### Task Tests (`test_tasks.py`)
```python
class TestWeatherTasks:
    @pytest.mark.django_db
    def test_fetch_weather_task_creates_observations(self, checkpoints, mock_weather_client):
        cp_ids = [str(cp.id) for cp in checkpoints]
        
        fetch_weather_for_checkpoints(cp_ids)
        
        assert WeatherObservation.objects.count() == 3
        for cp in checkpoints:
            obs = WeatherObservation.objects.get(checkpoint_id=cp.id)
            assert obs.forecast_time == cp.estimated_arrival
    
    @pytest.mark.django_db
    def test_fetch_weather_task_enqueues_risk(self, checkpoints, mock_weather_client, mock_risk_task):
        cp_ids = [str(cp.id) for cp in checkpoints]
        
        fetch_weather_for_checkpoints(cp_ids)
        
        assert mock_risk_task.delay.call_count == 3
        for call in mock_risk_task.delay.call_args_list:
            assert call[0][0] in cp_ids
    
    @pytest.mark.django_db
    def test_generate_heatmap_task(self, route, mock_weather_client):
        generate_heatmap_task(str(route.id), 6)
        
        heatmap = HeatmapCache.objects.get(route=route, forecast_hour=6)
        assert len(heatmap.grid_data) > 0
        assert heatmap.forecast_hour == 6
```

## Integration Tests (`test_integration.py`)
```python
class TestWeatherIntegration:
    @pytest.mark.django_db
    def test_checkpoint_weather_endpoint(self, client, checkpoints, mock_weather_client):
        cp_ids = ','.join(str(cp.id) for cp in checkpoints)
        
        response = client.get(f"/api/v1/weather/checkpoints/?checkpoint_ids={cp_ids}")
        
        assert response.status_code == 200
        assert len(response.data) == 3
        for item in response.data:
            assert 'checkpoint_id' in item
            assert 'temperature_f' in item
            assert 'conditions' in item
            assert 'wind_speed_mph' in item
    
    @pytest.mark.django_db
    def test_heatmap_endpoint(self, client, route, mock_weather_client):
        response = client.get(f"/api/v1/weather/heatmap/?route_id={route.id}&hour=6")
        
        assert response.status_code == 200
        assert response.data['forecast_hour'] == 6
        assert 'grid' in response.data
        assert len(response.data['grid']) > 0
        assert 'bounds' in response.data
```

## Fixtures (`fixtures.py`)
```python
MOCK_OWM_RESPONSE = {
    "lat": 39.78, "lon": -89.65, "timezone": "America/Chicago",
    "hourly": [
        {"dt": 1703664000, "temp": 45.2, "humidity": 65, "wind_speed": 12.5, "wind_deg": 230, "wind_gust": 18.0,
         "weather": [{"id": 500, "main": "Rain", "description": "light rain"}], "pop": 0.3, "rain": {"1h": 0.08}},
        {"dt": 1703667600, "temp": 32.1, "humidity": 85, "wind_speed": 38.0, "wind_deg": 310, "wind_gust": 45.0,
         "weather": [{"id": 600, "main": "Snow", "description": "heavy snow"}], "pop": 0.9, "snow": {"1h": 1.5}},
    ]
}

@pytest.fixture
def mock_weather_client(httpx_mock):
    httpx_mock.add_response(json=MOCK_OWM_RESPONSE)
    return httpx_mock

@pytest.fixture
def checkpoints():
    base = timezone.make_aware(datetime(2026, 10, 27, 8, 0, 0))
    return [
        Checkpoint.objects.create(latitude=39.7817, longitude=-89.6501, estimated_arrival=base, ...),
        Checkpoint.objects.create(latitude=39.7817, longitude=-89.6501, estimated_arrival=base, ...),  # Dup
        Checkpoint.objects.create(latitude=40.0000, longitude=-89.0000, estimated_arrival=base + timedelta(hours=1), ...),
    ]
```

## Running Tests

```bash
# All weather tests
pytest apps/weather/tests/ -v

# With coverage
pytest apps/weather/tests/ --cov=apps.weather --cov-report=term-missing --cov-fail-under=90

# Critical: client parsing tests
pytest apps/weather/tests/test_client.py -v

# Async tests
pytest apps/weather/tests/test_services.py::TestBulkFetchDeduplication -v
```