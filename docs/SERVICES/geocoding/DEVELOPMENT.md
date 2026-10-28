# Development Guide: Geocoding Service

## Quick Start

```bash
# 1. Start infrastructure
docker compose up -d postgres redis

# 2. Run migrations
python manage.py migrate

# 3. Create superuser (optional)
python manage.py createsuperuser

# 4. Run tests
pytest apps/geocoding/tests/ -v

# 5. Start dev server
python manage.py runserver 0.0.0.0:8000

# 6. Test API
curl "http://localhost:8000/api/v1/geocoding/search/?q=Springfield&limit=3"
```

## Project Structure

```
apps/geocoding/
├── __init__.py
├── admin.py              # Django admin registration
├── apps.py               # App config
├── models.py             # GeocodeCache
├── managers.py           # CacheManager
├── clients/
│   ├── __init__.py
│   └── openrouteservice.py
├── services.py           # search(), reverse(), cache logic
├── tasks.py              # (Future) cache warming
├── views.py              # SearchView, ReverseView
├── serializers.py        # GeocodeRequestSerializer, GeocodeResultSerializer
├── urls.py
├── validators.py         # Query validation
├── exceptions.py         # GeocodingError, RateLimitError
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_client.py
│   ├── test_services.py
│   ├── test_views.py
│   └── fixtures.py
└── migrations/
    └── 0001_initial.py
```

## Key Implementation Details

### Models
```python
# models.py
class GeocodeCache(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    query_text = models.TextField()
    query_type = models.CharField(max_length=20, choices=QueryType.choices)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    display_name = models.TextField()
    address_components = models.JSONField()
    raw_response = models.JSONField()
    source = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        indexes = [
            models.Index(fields=['query_text', 'query_type']),
            models.Index(fields=['expires_at']),
        ]
```

### Client Configuration
```python
# clients/openrouteservice.py
class GeocodingClient:
    BASE_URL = "https://api.openrouteservice.org"
    
    def __init__(self, api_key: str = None, timeout: float = 5.0):
        self.api_key = api_key or settings.OPENROUTESERVICE_API_KEY
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({'Authorization': self.api_key})
    
    def search(self, query: str, limit: int = 5, lat: float = None, lon: float = None):
        params = {'text': query, 'size': limit}
        if lat and lon:
            params['focus.point.lat'] = lat
            params['focus.point.lon'] = lon
        return self._request('GET', '/geocode/search', params=params)
```

### Cache Strategy
- **Redis**: Hot cache (1 hour TTL) for sub-ms reads
- **PostgreSQL**: Persistent cache (30 day TTL) for durability
- **Cache Key**: `{type}:{normalized_query}:{lat}:{lon}:{limit}`

## Common Tasks

### Adding New Geocoding Provider
1. Create `clients/{provider}.py` implementing `GeocodingClientProtocol`
2. Update `services.py` to use provider factory
3. Add provider-specific tests
4. Update feature flags/settings

### Extending Cache TTL
```python
# services.py
CACHE_TTL_DAYS = {
    'forward': 30,
    'reverse': 30,
    'autocomplete': 7,  # Shorter for autocomplete
}
```

### Handling Rate Limits
```python
# clients/openrouteservice.py
def _handle_rate_limit(self, response):
    if response.status_code == 429:
        retry_after = int(response.headers.get('Retry-After', 60))
        raise RateLimitError(f"Rate limited, retry after {retry_after}s", retry_after)
```

## Debugging

```bash
# View SQL queries
python manage.py shell -c "
import logging
logging.basicConfig()
logging.getLogger('django.db.backends').setLevel(logging.DEBUG)
"

# Test client directly
python manage.py shell -c "
from apps.geocoding.clients.openrouteservice import GeocodingClient
client = GeocodingClient()
print(client.search('Springfield, IL', limit=3))
"

# Check cache
redis-cli GET "geocode:search:springfield il:5::"
```

## Performance Tips

1. **Batch geocoding**: Not needed for autocomplete (single query)
2. **Connection pooling**: Use `requests.Session()` reuse
3. **Async**: Consider `httpx.AsyncClient` for high throughput
4. **Database indexes**: Ensure `(query_text, query_type)` index exists