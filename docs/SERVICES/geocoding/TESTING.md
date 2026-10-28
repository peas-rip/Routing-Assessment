# Testing Guide: Geocoding Service

## Test Strategy

| Test Type | Coverage Target | Priority |
|-----------|-----------------|----------|
| Unit Tests | 95% | Critical |
| Integration Tests | 90% | High |
| Contract Tests | 100% | Critical |

## Test Organization

```
apps/geocoding/tests/
├── __init__.py
├── fixtures.py              # Mock responses, test data
├── test_models.py           # Model validation, indexes
├── test_client.py           # ORS client behavior
├── test_services.py         # Cache, search, reverse logic
├── test_views.py            # API endpoints
└── test_integration.py      # Full flow tests
```

## Unit Tests

### Client Tests (`test_client.py`)
```python
class TestGeocodingClient:
    @pytest.fixture
    def client(self):
        return GeocodingClient(api_key="test-key", timeout=5.0)
    
    @pytest.fixture
    def mock_response(self):
        return {
            "features": [{
                "properties": {
                    "label": "123 Main St, Springfield, IL 62701",
                    "lat": 39.7817, "lon": -89.6501,
                    "housenumber": "123", "street": "Main St",
                    "city": "Springfield", "state": "IL",
                    "postalcode": "62701", "country": "USA"
                }
            }]
        }
    
    def test_search_success(self, client, mock_response, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url="https://api.openrouteservice.org/geocode/search",
            json=mock_response,
            match_headers={"Authorization": "test-key"}
        )
        results = client.search("Springfield, IL", limit=3)
        assert len(results) == 1
        assert results[0].display_name == "123 Main St, Springfield, IL 62701"
        assert results[0].latitude == 39.7817
    
    def test_search_rate_limit(self, client, httpx_mock):
        httpx_mock.add_response(status_code=429, headers={"Retry-After": "60"})
        with pytest.raises(RateLimitError) as exc:
            client.search("test")
        assert exc.value.retry_after == 60
    
    def test_search_timeout(self, client, httpx_mock):
        httpx_mock.add_exception(httpx.TimeoutException)
        with pytest.raises(GeocodingError):
            client.search("test")
    
    def test_reverse_geocoding(self, client, httpx_mock):
        httpx_mock.add_response(json={"features": [{"properties": {...}}]})
        result = client.reverse(39.7817, -89.6501)
        assert result.latitude == 39.7817
```

### Service Tests (`test_services.py`)
```python
class TestGeocodingService:
    @pytest.fixture(autouse=True)
    def setup(self):
        cache.clear()
        GeocodeCache.objects.all().delete()
    
    def test_search_cache_miss_then_hit(self, mock_ors_search):
        # First call - cache miss
        results1 = search("Springfield, IL")
        assert len(results1) == 1
        
        # Second call - Redis cache hit
        results2 = search("Springfield, IL")
        assert results2 == results1
        
        # Verify external API called once
        assert mock_ors_search.call_count == 1
    
    def test_search_db_cache_fallback(self, mock_ors_search):
        # Pre-populate DB cache
        GeocodeCache.objects.create(
            query_text="springfield il", query_type="autocomplete",
            results=[...], expires_at=timezone.now() + timedelta(days=1)
        )
        # Redis empty, should hit DB
        results = search("Springfield, IL")
        assert len(results) == 1
        assert mock_ors_search.call_count == 0
    
    def test_cache_expiry(self):
        # Expired entry should trigger API call
        GeocodeCache.objects.create(
            query_text="expired", query_type="autocomplete",
            results=[...], expires_at=timezone.now() - timedelta(days=1)
        )
        results = search("expired")
        assert mock_ors_search.called
    
    def test_query_normalization(self):
        # Case insensitive, whitespace normalized
        results1 = search("  Springfield, IL  ")
        results2 = search("springfield, il")
        assert results1 == results2
    
    def test_reverse_geocoding(self, mock_ors_reverse):
        result = reverse(39.7817, -89.6501)
        assert result.latitude == 39.7817
        assert result.longitude == -89.6501
```

### Model Tests (`test_models.py`)
```python
class TestGeocodeCacheModel:
    def test_create_cache_entry(self):
        cache = GeocodeCache.objects.create(
            query_text="test", query_type="autocomplete",
            latitude=1.0, longitude=2.0,
            display_name="Test", address_components={},
            raw_response={}, source="test", expires_at=timezone.now() + timedelta(days=1)
        )
        assert cache.id is not None
        assert not cache.is_expired
    
    def test_expired_property(self):
        cache = GeocodeCache(expires_at=timezone.now() - timedelta(hours=1))
        assert cache.is_expired
    
    def test_unique_constraint(self):
        GeocodeCache.objects.create(query_text="test", query_type="autocomplete", ...)
        with pytest.raises(IntegrityError):
            GeocodeCache.objects.create(query_text="test", query_type="autocomplete", ...)
```

## Integration Tests (`test_integration.py`)
```python
class TestGeocodingIntegration:
    @pytest.mark.django_db
    def test_full_search_flow(self, client):
        """Test: Request → Service → Cache → Response"""
        with patch('apps.geocoding.clients.openrouteservice.GeocodingClient.search') as mock:
            mock.return_value = [GeocodeResult(...)]
            
            response = client.get("/api/v1/geocoding/search/?q=Springfield&limit=3")
            
            assert response.status_code == 200
            assert len(response.data) == 1
            assert "Springfield" in response.data[0]["display_name"]
    
    @pytest.mark.django_db
    def test_rate_limiting(self, client):
        # Make 31 requests in a minute
        for _ in range(31):
            client.get("/api/v1/geocoding/search/?q=test")
        
        response = client.get("/api/v1/geocoding/search/?q=test")
        assert response.status_code == 429
    
    @pytest.mark.django_db
    def test_reverse_geocoding_flow(self, client):
        with patch('apps.geocoding.clients.openrouteservice.GeocodingClient.reverse') as mock:
            mock.return_value = GeocodeResult(...)
            
            response = client.get("/api/v1/geocoding/reverse/?lat=39.7817&lon=-89.6501")
            
            assert response.status_code == 200
            assert response.data["latitude"] == 39.7817
```

## Contract Tests

### API Schema Validation
```python
# test_views.py
class TestGeocodingAPIContract:
    def test_search_response_schema(self, client):
        response = client.get("/api/v1/geocoding/search/?q=Springfield")
        assert response.status_code == 200
        
        # Validate required fields
        for result in response.data:
            assert "place_id" in result
            assert "display_name" in result
            assert "latitude" in result
            assert "longitude" in result
            assert "address" in result
            assert isinstance(result["address"], dict)
    
    def test_reverse_response_schema(self, client):
        response = client.get("/api/v1/geocoding/reverse/?lat=39.78&lon=-89.65")
        assert response.status_code == 200
        assert "place_id" in response.data
        assert "display_name" in response.data
```

## Fixtures (`fixtures.py`)
```python
MOCK_ORS_SEARCH_RESPONSE = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {
            "label": "123 Main St, Springfield, IL 62701, USA",
            "housenumber": "123",
            "street": "Main St",
            "city": "Springfield",
            "state": "IL",
            "postalcode": "62701",
            "country": "USA",
            "lat": 39.7817,
            "lon": -89.6501
        },
        "geometry": {"type": "Point", "coordinates": [-89.6501, 39.7817]}
    }]
}

@pytest.fixture
def mock_ors_search(httpx_mock):
    httpx_mock.add_response(json=MOCK_ORS_SEARCH_RESPONSE)
    return httpx_mock

@pytest.fixture
def mock_ors_reverse(httpx_mock):
    httpx_mock.add_response(json=MOCK_ORS_SEARCH_RESPONSE)
    return httpx_mock
```

## Running Tests

```bash
# All geocoding tests
pytest apps/geocoding/tests/ -v

# With coverage
pytest apps/geocoding/tests/ --cov=apps.geocoding --cov-report=term-missing

# Specific test file
pytest apps/geocoding/tests/test_client.py -v

# Integration tests only
pytest apps/geocoding/tests/test_integration.py -v

# Watch mode (requires pytest-watch)
ptw apps/geocoding/tests/
```

## CI Configuration

```yaml
# .github/workflows/test.yml
- name: Test Geocoding Service
  run: |
    docker compose -f docker-compose.test.yml run --rm django \
      pytest apps/geocoding/tests/ --cov=apps.geocoding --cov-fail-under=90
```