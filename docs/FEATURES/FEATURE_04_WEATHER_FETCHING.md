# Feature Specification: F04 - Weather Fetching & Caching

## Business Goal
Fetch weather forecasts for each checkpoint at its estimated arrival time, cache results to minimize API calls, and handle rate limits gracefully.

## User Flow

### Primary Flow (Internal)
1. Route generation completes → Checkpoints created (F03)
2. Routing Service enqueues `fetch_weather_for_checkpoints` Celery task
3. Weather Service worker:
   - Groups checkpoints by forecast time (hourly buckets)
   - For each unique (lat, lon, hour): Check Redis cache
   - Cache miss → Call National Weather Service (NWS) Forecast API
   - Cache hit → Return cached data
   - Save WeatherObservation records
   - Enqueue risk calculation (F05)
4. Frontend polls or receives WebSocket update when weather ready

### Heatmap Flow
1. Frontend requests heatmap for route + hour (0-48)
2. Weather Service checks `heatmap_cache` table
3. Cache miss → Generate grid along route corridor → Fetch weather for grid points → Cache → Return

---

## Service Ownership
**Owner**: Weather Service
**Frontend Components**: Weather data display in RouteSummary, HeatmapLayer

---

## Database Requirements

### Tables
- `weather_observations` - Per-checkpoint weather at forecast time
- `heatmap_cache` - Pre-computed heatmap grids

### weather_observations Fields
| Field | Type | Description |
|-------|------|-------------|
| checkpoint_id | UUID | FK to checkpoints |
| forecast_time | DateTimeTZ | Time forecast is valid for |
| fetched_at | DateTimeTZ | When we fetched it |
| wind_speed_mph | Decimal(5,2) | Wind speed |
| wind_direction_deg | Integer | Wind direction (0-360) |
| wind_gust_mph | Decimal(5,2) | Wind gust |
| precipitation_rate_in_hr | Decimal(5,3) | Precip rate (in/hr) |
| precipitation_type | Enum | 'rain', 'snow', 'none', 'mixed' |
| snowfall_rate_in_hr | Decimal(5,3) | Snow rate (in/hr) |
| snow_depth_in | Decimal(5,2) | Snow accumulation |
| temperature_f | Decimal(5,2) | Temperature |
| humidity_pct | Integer | Humidity % |
| visibility_mi | Decimal(5,2) | Visibility |
| conditions | String | Human readable |
| raw_response | JSONB | Full API response |

---

## API Requirements

### GET /api/v1/weather/checkpoints/
**Query**: `?checkpoint_ids=uuid1,uuid2,...&forecast_time=2026-10-27T08:25:00Z`

**Response**:
```json
{
  "data": [
    {
      "checkpoint_id": "uuid",
      "forecast_time": "2026-10-27T08:25:00-05:00",
      "temperature_f": 32.1,
      "conditions": "Heavy snow",
      "wind_speed_mph": 38.0,
      "wind_direction_deg": 310,
      "precipitation_rate_in_hr": 1.5,
      "precipitation_type": "snow",
      "snowfall_rate_in_hr": 1.5,
      "humidity_pct": 85,
      "visibility_mi": 0.5
    }
  ]
}
```

### GET /api/v1/weather/heatmap/
**Query**: `?route_id=uuid&hour=6&resolution_miles=10`

**Response**:
```json
{
  "route_id": "uuid",
  "forecast_hour": 6,
  "bounds": {"north": 42.0, "south": 39.5, "east": -87.0, "west": -90.0},
  "resolution_miles": 10.0,
  "grid": [
    {"lat": 39.78, "lon": -89.65, "risk_level": "low", "risk_score": 1.0},
    {"lat": 39.85, "lon": -89.50, "risk_level": "high", "risk_score": 3.0}
  ]
}
```

---

## Validation Requirements

### Weather Data
- Temperature: -100°F to 150°F
- Wind speed: 0-200 mph
- Precipitation rate: 0-10 in/hr
- Forecast time: Within 48 hours of now
- Coordinates: Valid lat/lon

### Cache Validation
- TTL: 15 minutes for checkpoint weather
- TTL: 10 minutes for heatmap grids
- Stale-while-revalidate: Serve stale, refresh async

---

## Security Requirements
- Rate limiting: 60 req/min per IP on weather endpoints
- API key stored in env var, never logged
- Sanitize coordinates before external API call
- No PII in weather data

---

## Dependencies

### External
- **National Weather Service (NWS) Forecast API** - Primary
  - Free tier: 1,000 calls/day, 60/min
  - Provides: Current, minutely, hourly (48h), daily (8d)
  - Parameters: lat, lon, exclude=minutely,daily,alerts

### Internal
- Redis: Cache layer (TTL 15 min)
- PostgreSQL: Persistent storage
- Celery: Async fetching
- Routing Service: Produces checkpoints

---

## Edge Cases

1. **Checkpoint time > 48 hours**: Use daily forecast (less accurate) or extrapolate
2. **Multiple checkpoints same hour/location**: Deduplicate API calls
3. **API rate limit hit**: Queue requests, exponential backoff, serve stale cache
4. **Partial API response**: Save what we have, mark missing fields
5. **Snow vs Rain classification**: Use temperature threshold (≤32°F = snow)
6. **Mixed precipitation**: API returns both → Set type='mixed', use highest rate
7. **Coordinate precision**: Round to 4 decimals (~11m) for cache key
8. **Timezone**: National Weather Service (NWS) returns UTC, convert to checkpoint TZ

---

## Error Handling Expectations

| Scenario | Handling |
|----------|----------|
| API timeout (10s) | Retry 2x, then use stale cache or fail |
| API rate limit (429) | Backoff 60s, queue, retry |
| API error (5xx) | Retry 3x with backoff, then fail |
| Invalid response | Log, skip checkpoint, continue others |
| Network error | Retry with exponential backoff |
| All retries exhausted | Mark checkpoint weather as failed, alert |

---

## Acceptance Criteria

1. ✅ Fetches weather for all checkpoints in parallel (batched by time)
2. ✅ Cache hit rate >80% for repeated route requests
3. ✅ Respects National Weather Service (NWS) rate limits (60/min)
4. ✅ Returns data within 5 seconds for 50 checkpoints
5. ✅ Handles snow/rain classification correctly (temp-based)
6. ✅ Heatmap generates grid at specified resolution
7. ✅ Heatmap slider (0-48hr) returns data <500ms (cached)
8. ✅ Failed checkpoints don't block others
9. ✅ Raw API response stored for debugging
10. ✅ Cache TTL respected, stale data refreshed async

---

## Success Criteria

- Weather fetch success rate: >99% (with cache fallback)
- API cost: <500 calls/day at 1,000 users
- Heatmap render: 60fps slider interaction
- Zero data loss on API failures

---

## Implementation Notes

### National Weather Service (NWS) One Call 3.0 Request
```python
# One Call API 3.0
url = "https://api.nws.org/data/3.0/onecall"
params = {
    'lat': checkpoint.latitude,
    'lon': checkpoint.longitude,
    'exclude': 'minutely,daily,alerts',
    'units': 'imperial',  # mph, °F, inches
    'appid': API_KEY
}

# Response includes hourly[] for 48 hours
# Each hourly item: dt, temp, humidity, wind_speed, wind_deg, wind_gust,
# weather[0].id/main/description, pop, rain.1h, snow.1h
```

### Cache Key Strategy
```python
def cache_key(lat: float, lon: float, hour: int) -> str:
    # Round coordinates to ~11m precision
    lat_r = round(lat, 4)
    lon_r = round(lon, 4)
    return f"weather:{lat_r}:{lon_r}:{hour}"
```

### Bulk Fetching Optimization
```python
async def fetch_weather_batch(checkpoints: List[Checkpoint]) -> Dict:
    """Fetch weather for multiple checkpoints efficiently."""
    # Group by (lat, lon, hour) to deduplicate
    groups = defaultdict(list)
    for cp in checkpoints:
        hour = cp.estimated_arrival.hour
        key = (round(cp.latitude, 4), round(cp.longitude, 4), hour)
        groups[key].append(cp)
    
    # Fetch unique locations
    tasks = []
    for (lat, lon, hour), cps in groups.items():
        tasks.append(fetch_single(lat, lon, hour, cps))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return merge_results(groups, results)
```

### Heatmap Grid Generation
```python
def generate_heatmap_grid(route_geometry: LineString, hour: int, 
                          resolution_miles: float = 10) -> List[GridPoint]:
    """Generate grid points along route corridor."""
    # Create buffer around route (e.g., 20 miles each side)
    corridor = route_geometry.buffer(resolution_miles * 1609.34 / 2)
    
    # Generate grid within bounds
    bounds = corridor.bounds  # (minx, miny, maxx, maxy)
    grid_points = []
    
    for lat in frange(bounds[1], bounds[3], resolution_miles * 0.0145):  # ~1 mile = 0.0145°
        for lon in frange(bounds[0], bounds[2], resolution_miles * 0.0145 / cos(lat)):
            pt = Point(lon, lat)
            if corridor.contains(pt):
                grid_points.append((lat, lon))
    
    # Fetch weather for all grid points at hour
    # Calculate risk for each
    return grid_points
```

### Celery Task Structure
```python
@celery_app.task(bind=True, max_retries=3)
def fetch_weather_for_checkpoints(self, checkpoint_ids: List[str]):
    checkpoints = Checkpoint.objects.filter(id__in=checkpoint_ids)
    weather_data = fetch_weather_batch(checkpoints)
    save_weather_observations(weather_data)
    # Trigger risk calculation
    for cp_id in checkpoint_ids:
        calculate_risk_for_checkpoint.delay(cp_id)
```