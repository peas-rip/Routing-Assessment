# Service Specification: Weather Service

## Service Overview

**Name**: Weather Service
**Purpose**: Fetch weather forecasts for checkpoints, cache results, generate heatmap grids
**Business Ownership**: Route Planning team
**Technical Ownership**: Backend team

## Service Boundaries

### Owns
- Weather fetching for checkpoints at estimated arrival times
- Weather caching (Redis + PostgreSQL)
- Heatmap grid generation along route corridors
- Weather observation storage (`weather_observations`, `heatmap_cache` tables)
- External weather API integration (NWS / NOAA)

### Must Never Own
- Route generation
- Checkpoint sampling
- Risk calculation
- Geocoding

## Data Ownership

### Entities Owned
- `WeatherObservation` - Per-checkpoint weather at forecast time
- `HeatmapCache` - Pre-computed heatmap grids

### Relationships Owned
- WeatherObservation → Checkpoint (Many:1)
- HeatmapCache → Route (Many:1)

## Dependencies

### Internal
- **Routing Service** - Consumes checkpoints (read-only, async trigger)
- **Risk Service** - Produces weather for (async trigger)

### External
- **National Weather Service (NWS) Forecast API** - Primary weather
  - Endpoint: `/data/3.0/onecall`
  - Params: `lat, lon, exclude=minutely,daily,alerts, units=imperial`
  - Rate limit: 1,000 calls/day, 60/min (free tier)
  - Forecast: 48 hours hourly

## Communication

### APIs Exposed
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/weather/checkpoints/` | Bulk weather for checkpoints |
| GET | `/api/v1/weather/heatmap/` | Heatmap grid for route + hour |

### Events Produced
- `weather.fetched` - Weather saved for checkpoints
- `weather.heatmap.ready` - Heatmap grid computed

### Events Consumed
- `route.generated` → Enqueue `fetch_weather_for_checkpoints`

## Security Requirements

### Authentication
- v1: No auth
- Future: JWT required

### Authorization
- Rate limit: 60 req/min per IP (checkpoints)
- Rate limit: 20 req/min per IP (heatmap)

### Data Protection
- API key in env var only
- No PII in weather data
- Cache TTL: 15 min (checkpoints), 10 min (heatmap)

## Observability Requirements

### Logging
- Log: checkpoint count, cache hit/miss, API calls, errors
- Structured JSON

### Metrics
- Fetch latency (p50, p95)
- Cache hit rate (target >80%)
- API error rate
- Rate limit hits

### Monitoring
- Health check: OWM API connectivity
- Alert: API error rate > 10%
- Alert: Rate limit near capacity

---

## Development Guide

### Local Development
```bash
# Start dependencies
docker compose up -d postgres redis

# Run migrations
python manage.py migrate

# Run service tests
pytest apps/weather/tests/ -v

# Run Celery worker
celery -A config worker -l info -Q weather

# Run server
python manage.py runserver 0.0.0.0:8000
```

### Key Files
```
apps/weather/
├── models.py          # WeatherObservation, HeatmapCache
├── clients/
│   └── nws.py  # WeatherClient
├── services.py        # fetch_batch, generate_heatmap, deduplication
├── tasks.py           # fetch_weather_task, generate_heatmap_task
├── views.py           # CheckpointWeatherView, HeatmapView
├── serializers.py     # WeatherSerializer, HeatmapSerializer
├── urls.py            # URL routing
└── tests/
    ├── test_client.py
    ├── test_services.py
    ├── test_tasks.py
    └── test_views.py
```

### Implementation Patterns

#### Weather Client
```python
# apps/weather/clients/nws.py
class WeatherClient:
    def __init__(self):
        self.base_url = "https://api.nws.org/data/3.0/onecall"
        self.api_key = settings.NWS_BASE_URL
        self.timeout = 10.0
    
    def fetch_hourly(self, lat: float, lon: float) -> List[HourlyForecast]:
        """Fetch 48-hour hourly forecast."""
        params = {
            'lat': lat, 'lon': lon,
            'exclude': 'minutely,daily,alerts',
            'units': 'imperial',  # mph, °F, inches
            'appid': self.api_key
        }
        # GET with retry, timeout, rate limit handling
        # Parse hourly[] array to HourlyForecast objects
```

#### Bulk Fetch with Deduplication
```python
# apps/weather/services.py
async def fetch_weather_batch(checkpoints: List[Checkpoint]) -> Dict[UUID, WeatherObservation]:
    """Fetch weather for multiple checkpoints, deduplicating by (lat, lon, hour)."""
    
    # Group by rounded coordinates + forecast hour
    groups = defaultdict(list)
    for cp in checkpoints:
        hour = cp.estimated_arrival.hour
        key = (round(cp.latitude, 4), round(cp.longitude, 4), hour)
        groups[key].append(cp)
    
    # Fetch unique locations
    async def fetch_group(lat, lon, hour, cps):
        forecast = await client.fetch_hourly(lat, lon)
        # Find matching hour in forecast
        target = next((f for f in forecast if f.dt.hour == hour), None)
        if not target:
            return None
        return {cp.id: parse_weather(target) for cp in cps}
    
    tasks = [fetch_group(lat, lon, hour, cps) for (lat, lon, hour), cps in groups.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Merge and handle errors
    observations = {}
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Weather fetch failed: {result}")
            continue
        if result:
            observations.update(result)
    
    return observations
```

#### Heatmap Grid Generation
```python
def generate_heatmap_grid(route: Route, hour: int, resolution_miles: float = 10) -> HeatmapCache:
    """Generate risk grid along route corridor."""
    # 1. Create corridor buffer
    corridor = route.geometry.buffer(max(20, resolution_miles * 2) * 1609.34)
    
    # 2. Generate grid points
    grid_points = generate_grid_in_polygon(corridor, resolution_miles)
    
    # 3. Limit points
    if len(grid_points) > 5000:
        resolution_miles *= math.sqrt(len(grid_points) / 5000)
        return generate_heatmap_grid(route, hour, resolution_miles)
    
    # 4. Fetch weather for all points at target hour
    target_time = route.request.departure_time + timedelta(hours=hour)
    weather_data = fetch_weather_batch_for_coords(grid_points, target_time)
    
    # 5. Calculate risk for each point
    grid = []
    for (lat, lon), weather in zip(grid_points, weather_data):
        risk = risk_service.calculate_risk(weather, route.request.load_weight_lbs)
        grid.append({
            'lat': lat, 'lon': lon,
            'risk_level': risk.combined_risk,
            'risk_score': RISK_SCORE_MAP[risk.combined_risk]
        })
    
    # 6. Save to cache
    return HeatmapCache.objects.create(
        route=route, forecast_hour=hour, grid_data=grid,
        bounds=corridor.bounds, resolution_miles=resolution_miles,
        expires_at=timezone.now() + timedelta(minutes=10)
    )
```

#### Celery Tasks
```python
# apps/weather/tasks.py
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def fetch_weather_for_checkpoints(self, checkpoint_ids: List[str]):
    checkpoints = Checkpoint.objects.filter(id__in=checkpoint_ids)
    observations = fetch_weather_batch(checkpoints)
    
    # Bulk create observations
    WeatherObservation.objects.bulk_create([
        WeatherObservation(checkpoint_id=cp_id, **data)
        for cp_id, data in observations.items()
    ], ignore_conflicts=True)
    
    # Trigger risk calculation
    for cp_id in checkpoint_ids:
        calculate_risk_for_checkpoint.delay(cp_id)

@celery_app.task(bind=True, max_retries=2)
def generate_heatmap_task(self, route_id: str, hour: int):
    route = Route.objects.get(id=route_id)
    generate_heatmap_grid(route, hour)
```

---

## Testing Guide

### Unit Tests
- **Client**: Mock OWM responses, test parsing (rain/snow/none), unit conversions
- **Services**: Deduplication logic, heatmap grid math, cache behavior
- **Tasks**: Retry logic, error handling, bulk create

### Integration Tests
- Full flow: Checkpoints → Weather → Risk trigger
- Rate limit handling (mock 429 responses)
- Heatmap generation for various route lengths

### Test Fixtures
```python
# Mock OWM One Call 3.0 response
MOCK_OWM_RESPONSE = {
    "lat": 39.78, "lon": -89.65, "timezone": "America/Chicago",
    "hourly": [{
        "dt": 1703664000, "temp": 45.2, "humidity": 65,
        "wind_speed": 12.5, "wind_deg": 230, "wind_gust": 18.0,
        "weather": [{"id": 500, "main": "Rain", "description": "light rain"}],
        "pop": 0.3, "rain": {"1h": 0.08}
    }]
}
```

### Coverage Targets
- Client: 100% (external API parsing critical)
- Services: 90%
- Tasks: 90%
- Views: 85%

---

## Deployment Guide

### Configuration
```bash
NWS_BASE_URL=owm_xxx
CELERY_BROKER_URL=redis://redis:6379/1
```

### Health Check
```python
def check_weather():
    try:
        client = WeatherClient()
        client.fetch_hourly(39.78, -89.65)
        return "ok"
    except Exception as e:
        return f"degraded: {e}"
```

### Scaling
- Celery workers: `-Q weather` for dedicated workers
- Redis: Cache hit rate monitoring
- Consider: Pre-warming cache for popular routes

### Rate Limit Management
- Token bucket in Redis for OWM calls
- Respect `Retry-After` headers
- Queue excess requests with backoff

## Weather Provider: National Weather Service (NWS / NOAA)

The weather integration uses the **NWS Forecast API**
(`https://api.weather.gov`) as its data source. Coverage is **US-only**.

### Integration Notes
- **No API key required.** The client (`apps/weather/clients/nws.py`)
  resolves a grid office via `/points/{lat},{lon}` and fetches the hourly
  forecast from the returned `forecastHourly` URL.
- Responses are parsed into the shared `HourlyForecast` shape and cached for
  15 minutes per (lat, lon, hour) bucket, unchanged from prior behavior.
- NWS provides temperature, wind speed/direction, and probability of
  precipitation; humidity and visibility are not available, so they are
  stored as `None`/`0`.
- Precipitation rate is approximated from the probability of precipitation
  (0-1 in/hr) since NWS does not provide an hourly rate directly.

### Configuration
- `NWS_BASE_URL` - API base URL (default `https://api.weather.gov`).
- `NWS_USER_AGENT` - required descriptive User-Agent (default
  `Routing-Assessment/1.0`).
- `NWS_HEALTHCHECK_ENABLED` - opt-in flag (default `False`) that enables a
  live NWS probe in `/health/`; kept off by default so health checks stay
  fast and deterministic.
- `WEATHER_TIMEOUT` - request timeout in seconds (default `30.0`).

### Licensing
The NWS API is a **free US-government service** with no API key, no credit
card, and no commercial-use restriction. Polite usage is expected
(~1 req/sec).
