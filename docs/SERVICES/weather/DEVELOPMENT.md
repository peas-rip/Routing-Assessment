# Development Guide: Weather Service

## Quick Start

```bash
# 1. Start infrastructure
docker compose up -d postgres redis

# 2. Run migrations
python manage.py migrate

# 3. Run tests
pytest apps/weather/tests/ -v

# 4. Start Celery worker (terminal 1)
celery -A config worker -l info -Q weather

# 5. Start dev server (terminal 2)
python manage.py runserver 0.0.0.0:8000

# 6. Test API
curl "http://localhost:8000/api/v1/weather/checkpoints/?checkpoint_ids=uuid1,uuid2"
curl "http://localhost:8000/api/v1/weather/heatmap/?route_id=uuid&hour=6"
```

## Project Structure

```
apps/weather/
├── __init__.py
├── admin.py
├── apps.py
├── models.py              # WeatherObservation, HeatmapCache
├── managers.py            # WeatherObservationManager
├── clients/
│   ├── __init__.py
│   └── nws.py
├── services.py            # fetch_batch, generate_heatmap, deduplication
├── tasks.py               # fetch_weather_task, generate_heatmap_task
├── views.py               # CheckpointWeatherView, HeatmapView
├── serializers.py         # WeatherSerializer, HeatmapSerializer
├── urls.py
├── utils.py               # Unit conversions, precipitation parsing
├── tests/
│   ├── __init__.py
│   ├── fixtures.py
│   ├── test_models.py
│   ├── test_client.py
│   ├── test_services.py
│   ├── test_tasks.py
│   └── test_views.py
└── migrations/
    ├── 0001_initial.py
    └── 0002_heatmap_cache.py
```

## Key Implementation Details

### Models
```python
# models.py
class WeatherObservation(models.Model):
    PRECIP_TYPES = [('rain', 'Rain'), ('snow', 'Snow'), ('none', 'None'), ('mixed', 'Mixed')]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    checkpoint = models.ForeignKey('routing.Checkpoint', on_delete=models.CASCADE, related_name='weather_observations')
    forecast_time = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    
    # Wind
    wind_speed_mph = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    wind_direction_deg = models.IntegerField(null=True)
    wind_gust_mph = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    
    # Precipitation
    precipitation_rate_in_hr = models.DecimalField(max_digits=5, decimal_places=3, null=True)
    precipitation_type = models.CharField(max_length=20, choices=PRECIP_TYPES)
    snowfall_rate_in_hr = models.DecimalField(max_digits=5, decimal_places=3, null=True)
    snow_depth_in = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    
    # General
    temperature_f = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    humidity_pct = models.IntegerField(null=True)
    visibility_mi = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    conditions = models.CharField(max_length=100, blank=True)
    
    raw_response = models.JSONField()
    source = models.CharField(max_length=50, default='nws')
    
    class Meta:
        indexes = [
            models.Index(fields=['checkpoint', 'forecast_time']),
            models.Index(fields=['fetched_at']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['checkpoint', 'forecast_time', 'source'], name='unique_weather_obs')
        ]

class HeatmapCache(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    route = models.ForeignKey('routing.Route', on_delete=models.CASCADE, related_name='heatmaps')
    forecast_hour = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(48)])
    grid_data = models.JSONField()  # [{"lat": ..., "lon": ..., "risk_level": ..., "risk_score": ...}]
    bounds = models.JSONField()     # {"north": ..., "south": ..., "east": ..., "west": ...}
    resolution_miles = models.DecimalField(max_digits=5, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        indexes = [
            models.Index(fields=['route', 'forecast_hour']),
            models.Index(fields=['expires_at']),
        ]
```

### Weather Client
```python
# clients/nws.py
class WeatherClient:
    BASE_URL = "https://api.nws.org/data/3.0/onecall"
    
    def __init__(self, api_key: str = None, timeout: float = 10.0):
        self.api_key = api_key or settings.NWS_BASE_URL
        self.timeout = timeout
        self.session = requests.Session()
    
    def fetch_hourly(self, lat: float, lon: float) -> List[HourlyForecast]:
        params = {
            'lat': lat, 'lon': lon,
            'exclude': 'minutely,daily,alerts',
            'units': 'imperial',  # mph, °F, inches
            'appid': self.api_key
        }
        response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
        response.raise_for_status()
        return self._parse_hourly(response.json()['hourly'])
    
    def _parse_hourly(self, hourly_data: List[dict]) -> List[HourlyForecast]:
        results = []
        for h in hourly_data[:48]:  # 48 hours
            weather = h['weather'][0] if h['weather'] else {}
            rain = h.get('rain', {}).get('1h', 0)
            snow = h.get('snow', {}).get('1h', 0)
            
            precip_type = 'none'
            if rain > 0 and snow > 0:
                precip_type = 'mixed'
            elif rain > 0:
                precip_type = 'rain'
            elif snow > 0:
                precip_type = 'snow'
            
            results.append(HourlyForecast(
                dt=datetime.fromtimestamp(h['dt'], tz=timezone.utc),
                temp_f=h['temp'],
                humidity=h['humidity'],
                wind_speed_mph=h['wind_speed'],
                wind_deg=h['wind_deg'],
                wind_gust_mph=h.get('wind_gust'),
                precipitation_rate_in_hr=rain + snow,
                precipitation_type=precip_type,
                snowfall_rate_in_hr=snow,
                conditions=weather.get('description', ''),
            ))
        return results
```

### Bulk Fetch with Deduplication
```python
# services.py
async def fetch_weather_batch(checkpoints: List[Checkpoint]) -> Dict[UUID, Dict]:
    """Fetch weather for multiple checkpoints, deduplicating by (lat, lon, hour)."""
    
    # Group by rounded coordinates + forecast hour
    groups = defaultdict(list)
    for cp in checkpoints:
        hour = cp.estimated_arrival.hour
        key = (round(cp.latitude, 4), round(cp.longitude, 4), hour)
        groups[key].append(cp)
    
    async def fetch_group(lat: float, lon: float, hour: int, cps: List[Checkpoint]):
        try:
            forecasts = await client.fetch_hourly(lat, lon)
            target = next((f for f in forecasts if f.dt.hour == hour), None)
            if not target:
                return {}
            
            return {cp.id: parse_weather_to_dict(target) for cp in cps}
        except Exception as e:
            logger.error(f"Weather fetch failed for {lat},{lon}@{hour}: {e}")
            return {}
    
    tasks = [fetch_group(lat, lon, hour, cps) for (lat, lon, hour), cps in groups.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    observations = {}
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Weather fetch task failed: {result}")
            continue
        observations.update(result)
    
    return observations
```

### Heatmap Generation
```python
def generate_heatmap_grid(route: Route, hour: int, resolution_miles: float = 10) -> HeatmapCache:
    """Generate risk grid along route corridor."""
    from apps.risk.services import calculate_risk
    
    # 1. Create corridor buffer
    corridor_buffer_miles = max(20, resolution_miles * 2)
    corridor = route.geometry.buffer(corridor_buffer_miles * 1609.34)
    
    # 2. Generate grid points
    bounds = corridor.bounds
    lat_step = resolution_miles / 69.0
    lon_step = resolution_miles / (69.0 * math.cos(math.radians((bounds[1] + bounds[3]) / 2)))
    
    grid_points = []
    lat = bounds[1]
    while lat <= bounds[3]:
        lon = bounds[0]
        while lon <= bounds[2]:
            pt = Point(lon, lat)
            if corridor.contains(pt):
                wgs84 = transform(web_mercator_to_wgs84, pt)
                grid_points.append((wgs84.y, wgs84.x))
            lon += lon_step
        lat += lat_step
    
    # 3. Limit points
    if len(grid_points) > 5000:
        return generate_heatmap_grid(route, hour, resolution_miles * 1.5)
    
    # 4. Fetch weather + calculate risk
    target_time = route.request.departure_time + timedelta(hours=hour)
    grid = []
    
    for lat, lon in grid_points:
        # Create mock checkpoint for risk calculation
        mock_cp = Checkpoint(latitude=lat, longitude=lon, estimated_arrival=target_time)
        weather = fetch_single_point_weather(lat, lon, target_time)
        risk = calculate_risk(weather, route.request.load_weight_lbs)
        
        grid.append({
            'lat': lat, 'lon': lon,
            'risk_level': risk.combined_risk,
            'risk_score': RISK_SCORE_MAP[risk.combined_risk]
        })
    
    # 5. Save cache
    return HeatmapCache.objects.create(
        route=route, forecast_hour=hour, grid_data=grid,
        bounds=dict(zip(['west', 'south', 'east', 'north'], bounds)),
        resolution_miles=Decimal(str(resolution_miles)),
        expires_at=timezone.now() + timedelta(minutes=10)
    )
```

## Debugging

```bash
# Test client directly
python manage.py shell -c "
from apps.weather.clients.nws import WeatherClient
client = WeatherClient()
forecasts = client.fetch_hourly(39.78, -89.65)
for f in forecasts[:3]:
    print(f'{f.dt}: {f.temp_f}°F, {f.conditions}, wind {f.wind_speed_mph}mph, rain {f.precipitation_rate_in_hr}in/hr')
"

# Check cache
python manage.py shell -c "
from apps.weather.models import WeatherObservation, HeatmapCache
print(f'Observations: {WeatherObservation.objects.count()}')
print(f'Heatmaps: {HeatmapCache.objects.count()}')
for h in HeatmapCache.objects.all()[:3]:
    print(f'  Route {h.route_id} hour {h.forecast_hour}: {len(h.grid_data)} points')
"

# Test heatmap generation
python manage.py shell -c "
from apps.routing.models import Route
from apps.weather.services import generate_heatmap_grid
route = Route.objects.first()
hm = generate_heatmap_grid(route, 6, 10)
print(f'Generated {len(hm.grid_data)} grid points')
"
```