# Service Specification: Geocoding Service

## Service Overview

**Name**: Geocoding Service
**Purpose**: Provide address search, autocomplete, and reverse geocoding for route input
**Business Ownership**: Route Planning team
**Technical Ownership**: Backend team

## Service Boundaries

### Owns
- Address autocomplete/search (`/geocoding/search/`)
- Reverse geocoding (`/geocoding/reverse/`)
- Geocoding cache (`geocode_cache` table)
- External geocoding API integration (OpenRouteService)

### Must Never Own
- Route generation logic
- Weather data
- Risk calculation
- User authentication

## Data Ownership

### Entities Owned
- `GeocodeCache` - Cached geocoding results (forward, reverse, autocomplete)

### Relationships Owned
- None (leaf service)

## Dependencies

### Internal
- None (independent service)

### External
- **OpenRouteService Geocoding API** - Primary provider
  - Endpoint: `/geocode/search`, `/geocode/reverse`
  - Rate limit: 2,000 req/day (free tier)
  - Auth: API key in header

## Communication

### APIs Exposed
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/geocoding/search/` | Address autocomplete |
| GET | `/api/v1/geocoding/reverse/` | Reverse geocoding |

### Events Produced
- None

### Events Consumed
- None

## Security Requirements

### Authentication
- v1: No auth (public endpoints with rate limiting)
- Future: JWT required for authenticated users

### Authorization
- Public read access
- Rate limiting: 30 req/min per IP

### Data Protection
- No PII stored beyond address strings
- Cache TTL: 30 days
- API key in environment variable only

## Observability Requirements

### Logging
- Structured JSON logs
- Log: query, cache hit/miss, response count, latency
- Level: INFO for requests, DEBUG for cache details

### Metrics
- Request latency (p50, p95, p99)
- Cache hit rate
- External API error rate
- Rate limit rejections

### Monitoring
- Health check: `GET /health/` includes geocoding API connectivity
- Alert: External API error rate > 10%

---

## Development Guide

### Local Development
```bash
# Start dependencies
docker compose up -d postgres redis

# Run migrations
python manage.py migrate

# Run service tests
pytest apps/geocoding/tests/ -v

# Run server
python manage.py runserver 0.0.0.0:8000
```

### Key Files
```
apps/geocoding/
├── models.py          # GeocodeCache
├── clients/
│   └── openrouteservice.py  # External API client
├── services.py        # Business logic (search, reverse, cache)
├── views.py           # DRF views
├── serializers.py     # Request/response serializers
├── urls.py            # URL routing
├── tasks.py           # (Future) Cache warming
└── tests/
    ├── test_client.py
    ├── test_services.py
    └── test_views.py
```

### Implementation Patterns

#### Client Wrapper
```python
# apps/geocoding/clients/openrouteservice.py
class GeocodingClient:
    def __init__(self):
        self.base_url = settings.OPENROUTESERVICE_BASE_URL
        self.api_key = settings.OPENROUTESERVICE_API_KEY
        self.timeout = 5.0
    
    def search(self, query: str, limit: int = 5, lat: float = None, lon: float = None) -> List[GeocodeResult]:
        # Implement with retry, timeout, error handling
    
    def reverse(self, lat: float, lon: float) -> GeocodeResult:
        # Implement reverse geocoding
```

#### Cache Strategy
```python
# apps/geocoding/services.py
def search(query: str, limit: int = 5, lat: float = None, lon: float = None) -> List[GeocodeResult]:
    cache_key = f"geocode:search:{normalize(query)}:{limit}:{lat}:{lon}"
    
    # Try Redis first
    cached = redis.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # Fallback to DB cache
    db_cached = GeocodeCache.objects.filter(
        query_text=query, query_type='autocomplete'
    ).first()
    if db_cached and not db_cached.is_expired:
        redis.setex(cache_key, 3600, json.dumps(db_cached.results))
        return db_cached.results
    
    # Call external API
    results = client.search(query, limit, lat, lon)
    
    # Store in both caches
    redis.setex(cache_key, 3600, json.dumps(results))
    GeocodeCache.objects.update_or_create(
        query_text=query, query_type='autocomplete',
        defaults={'results': results, 'expires_at': now() + timedelta(days=30)}
    )
    return results
```

---

## Testing Guide

### Unit Tests
- **Client**: Mock HTTP responses, test parsing, error handling, retries
- **Services**: Test cache logic (hit/miss/expiry), normalization, deduplication
- **Validators**: Test coordinate validation, query sanitization

### Integration Tests
- Full flow: Request → Cache miss → API → Cache store → Response
- Rate limiting behavior
- Fallback to DB cache when Redis unavailable

### Test Data
```python
# Fixtures for consistent testing
MOCK_SEARCH_RESPONSE = {
    "features": [{
        "properties": {
            "label": "123 Main St, Springfield, IL 62701",
            "lat": 39.7817,
            "lon": -89.6501,
            "housenumber": "123",
            "street": "Main St",
            "city": "Springfield",
            "state": "IL",
            "postalcode": "62701",
            "country": "USA"
        }
    }]
}
```

### Coverage Targets
- Client: 100% (error paths critical)
- Services: 95%
- Views: 90%

---

## Deployment Guide

### Configuration
```bash
# Environment variables
OPENROUTESERVICE_API_KEY=ors_xxx
OPENROUTESERVICE_BASE_URL=https://api.openrouteservice.org
REDIS_URL=redis://redis:6379/0
DATABASE_URL=postgres://...
```

### Health Check
```python
# Included in main health endpoint
def check_geocoding():
    try:
        client = GeocodingClient()
        client.search("test", limit=1)
        return "ok"
    except Exception as e:
        return f"degraded: {e}"
```

### Scaling
- Stateless - scale horizontally behind load balancer
- Redis cache shared across instances
- DB cache shared across instances

### Rollback
- No database migrations in typical deployments
- Docker image tag rollback sufficient