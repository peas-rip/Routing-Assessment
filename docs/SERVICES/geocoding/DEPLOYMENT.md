# Deployment Guide: Geocoding Service

## Configuration

### Environment Variables
```bash
# Required
OPENROUTESERVICE_API_KEY=ors_xxx
OPENROUTESERVICE_BASE_URL=https://api.openrouteservice.org

# Optional
GEOCODING_CACHE_TTL_DAYS=30
GEOCODING_RATE_LIMIT=30/minute
```

### Django Settings
```python
# config/settings/production.py
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': env('REDIS_URL'),
        'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
    }
}

# Rate limiting
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'geocoding': '30/minute',
    }
}
```

## Health Checks

```python
# apps/geocoding/health.py
def check_geocoding():
    """Health check for load balancer."""
    try:
        client = GeocodingClient()
        # Quick test with known location
        result = client.search("Springfield, IL", limit=1)
        if result:
            return {"status": "healthy", "provider": "openrouteservice"}
        return {"status": "degraded", "reason": "No results"}
    except RateLimitError:
        return {"status": "degraded", "reason": "Rate limited"}
    except Exception as e:
        return {"status": "unhealthy", "reason": str(e)}
```

## Docker Configuration

### Dockerfile (shared with Django)
```dockerfile
# No service-specific Dockerfile needed
# Uses main backend/Dockerfile
```

### Docker Compose (Production)
```yaml
# Service runs as part of Django container
# No separate container needed
```

## Scaling

### Horizontal Scaling
- Stateless Django workers behind Nginx
- Shared Redis cache (all instances)
- Shared PostgreSQL (all instances)
- Scale by adding Django worker containers

### Vertical Scaling
- Increase Gunicorn workers: `(2 * CPU) + 1`
- Increase Redis memory if cache hit rate drops

### Capacity Planning
| Metric | Threshold | Action |
|--------|-----------|--------|
| Cache hit rate | < 70% | Increase Redis memory |
| API latency p95 | > 2s | Check ORS status, add timeout |
| Rate limit hits | > 5/min | Increase limit or add caching |

## Monitoring

### Key Metrics
- Request rate (req/s)
- Latency p50/p95/p99
- Cache hit rate
- External API error rate
- Rate limit rejections

### Alerts
```yaml
# Prometheus rules
- alert: GeocodingHighErrorRate
  expr: rate(geocoding_errors_total[5m]) > 0.1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Geocoding error rate > 10%"

- alert: GeocodingRateLimited
  expr: rate(geocoding_rate_limited_total[5m]) > 0.01
  for: 1m
  labels:
    severity: warning
```

## Deployment Steps

### Initial Deployment
```bash
# 1. Ensure .env.production has ORS API key
# 2. Run migrations
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate

# 3. Collect static (includes any geocoding-related admin)
docker compose -f docker-compose.prod.yml run --rm django python manage.py collectstatic --noinput

# 4. Start services
docker compose -f docker-compose.prod.yml up -d
```

### Updates
```bash
# Zero-downtime deploy
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate
docker compose -f docker-compose.prod.yml up -d --no-deps django
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

### Rollback
```bash
# Tag-based rollback
git checkout v1.2.3
docker compose -f docker-compose.prod.yml up -d --build
```

## Troubleshooting

### Common Issues

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| High latency | Check ORS API status | Add circuit breaker |
| Rate limited | Check `Retry-After` header | Implement exponential backoff |
| Cache miss storm | Cache expired simultaneously | Stagger TTLs, pre-warm |
| No results | Query too specific | Fallback to broader search |

### Debug Commands
```bash
# Check ORS connectivity
curl -H "Authorization: $ORS_KEY" "https://api.openrouteservice.org/geocode/search?text=Springfield"

# Check Redis cache
redis-cli KEYS "geocode:*"
redis-cli GET "geocode:search:springfield il:5::"

# Check DB cache
docker compose exec django python manage.py shell -c "
from apps.geocoding.models import GeocodeCache
print(GeocodeCache.objects.filter(query_type='autocomplete').count())
"

# View logs
docker compose logs -f django | grep geocoding
```

## Backup/Recovery

- **Cache data**: Not critical (re-fetchable from ORS)
- **Configuration**: API key in `.env` (backup separately)
- **No database migrations** typically needed for this service