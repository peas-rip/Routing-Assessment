# Deployment Guide: Weather Service

## Configuration

### Environment Variables
```bash
# Required
NWS_BASE_URL=owm_xxx

# Celery
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# Cache TTLs
WEATHER_CACHE_TTL_MINUTES=15
HEATMAP_CACHE_TTL_MINUTES=10

# Rate Limiting
WEATHER_API_RATE_LIMIT=60/minute  # OWM free tier
HEATMAP_API_RATE_LIMIT=20/minute
```

### Celery Queue Configuration
```python
# config/celery.py
app.conf.task_routes = {
    'apps.weather.tasks.fetch_weather_for_checkpoints': {'queue': 'weather'},
    'apps.weather.tasks.generate_heatmap_task': {'queue': 'weather'},
}
```

## Health Checks

```python
# apps/weather/health.py
def check_weather():
    try:
        client = WeatherClient()
        forecasts = client.fetch_hourly(39.78, -89.65)
        if forecasts and len(forecasts) > 0:
            return {"status": "healthy", "provider": "nws", "forecast_hours": len(forecasts)}
        return {"status": "degraded", "reason": "No forecast data"}
    except RateLimitError as e:
        return {"status": "degraded", "reason": f"Rate limited, retry after {e.retry_after}s"}
    except Exception as e:
        return {"status": "unhealthy", "reason": str(e)}
```

## Scaling

### Celery Workers
```bash
# Dedicated weather workers
celery -A config worker -l info -Q weather -c 4

# For heatmap generation (CPU intensive), consider fewer workers with more memory
```

### Redis Cache Optimization
```python
# Cache key structure
# weather:{lat:.4f}:{lon:.4f}:{hour} -> JSON
# Heatmap cache in PostgreSQL with 10-min TTL

# Monitor cache hit rate
# Target: >80% for repeated routes
```

### Rate Limit Management
```python
# Token bucket in Redis for OWM calls
# Key: rate_limit:owm:{minute_window}
# Limit: 60 per minute (free tier)

# Graceful degradation:
# 1. Serve stale cache (up to 1 hour old)
# 2. Queue excess requests with exponential backoff
# 3. Return 429 with Retry-After header
```

## Monitoring

### Key Metrics
- Fetch latency (p50, p95)
- Cache hit rate (target >80%)
- API error rate
- Rate limit hits
- Heatmap generation time
- Grid points per heatmap

### Alerts
```yaml
- alert: WeatherHighErrorRate
  expr: rate(weather_fetch_errors_total[5m]) > 0.1
  for: 2m
  labels:
    severity: warning

- alert: WeatherRateLimited
  expr: rate(weather_rate_limited_total[5m]) > 0.01
  for: 1m
  labels:
    severity: warning

- alert: HeatmapGenerationSlow
  expr: histogram_quantile(0.95, heatmap_generation_duration_seconds) > 30
  for: 5m
  labels:
    severity: warning
```

## Deployment Steps

### Initial Deployment
```bash
# 1. Run migrations
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate

# 2. Verify OWM connectivity
docker compose exec django python manage.py shell -c "
from apps.weather.clients.nws import WeatherClient
client = WeatherClient()
f = client.fetch_hourly(39.78, -89.65)
print(f'Fetched {len(f)} hourly forecasts')
"

# 3. Start services
docker compose -f docker-compose.prod.yml up -d
```

### Updates
```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate
docker compose -f docker-compose.prod.yml up -d --no-deps django celery
```

## Troubleshooting

### Common Issues

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| No weather data | OWM returns empty hourly | Check coordinates, API key |
| Cache miss storm | Many checkpoints same time | Pre-warm cache for popular routes |
| Heatmap slow | Too many grid points | Auto-reduce resolution |
| Rate limited | 429 from OWM | Implement token bucket, backoff |

### Debug Commands
```bash
# Check OWM connectivity
curl "https://api.nws.org/data/3.0/onecall?lat=39.78&lon=-89.65&exclude=minutely,daily,alerts&units=imperial&appid=$OWM_KEY"

# Check Redis weather cache
redis-cli KEYS "weather:*" | head -20
redis-cli GET "weather:39.7817:-89.6501:8"

# Check DB observations
docker compose exec django python manage.py shell -c "
from apps.weather.models import WeatherObservation
print(f'Total: {WeatherObservation.objects.count()}')
print(f'Last hour: {WeatherObservation.objects.filter(fetched_at__gte=timezone.now()-timedelta(hours=1)).count()}')
"

# View worker logs
docker compose logs -f celery | grep weather
```

## Backup/Recovery

### Data Retention
- `WeatherObservation`: 7 days (auto-cleanup via cron)
- `HeatmapCache`: 48 hours (TTL-based expiry)
- Not critical - re-fetchable from OWM

### Recovery
```bash
# No critical data loss - just re-fetch
# Clear stale cache if needed
docker compose exec django python manage.py shell -c "
from apps.weather.models import WeatherObservation, HeatmapCache
WeatherObservation.objects.filter(fetched_at__lt=timezone.now()-timedelta(days=7)).delete()
HeatmapCache.objects.filter(expires_at__lt=timezone.now()).delete()
"
```

## Performance Tuning

### Bulk Fetch Optimization
```python
# Use asyncio for parallel fetches
# Limit concurrent connections to respect rate limits
semaphore = asyncio.Semaphore(10)  # Max 10 concurrent

async def fetch_with_semaphore(lat, lon):
    async with semaphore:
        return await client.fetch_hourly(lat, lon)
```

### Heatmap Generation
```python
# Cache heatmaps for popular routes
# Pre-generate for hours 0, 6, 12, 18, 24, 36, 48
# Background task: generate_heatmap_for_route(route_id)
```