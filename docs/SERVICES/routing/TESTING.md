# Testing Guide: Routing Service

## Test Strategy

| Test Type | Coverage Target | Priority |
|-----------|-----------------|----------|
| Unit Tests | 90% | Critical |
| Integration Tests | 85% | High |
| Contract Tests | 100% | Critical |

## Test Organization

```
apps/routing/tests/
├── __init__.py
├── fixtures.py              # Mock ORS responses
├── test_models.py           # Model validation, PostGIS
├── test_client.py           # ORS client behavior
├── test_services.py         # Checkpoint sampling, ETA calculation
├── test_tasks.py            # Async task flow
├── test_views.py            # API endpoints
└── test_integration.py      # Full flow tests
```

## Unit Tests

### Client Tests (`test_client.py`)
```python
class TestRoutingClient:
    @pytest.fixture
    def client(self):
        return RoutingClient(api_key="test-key", timeout=30.0)
    
    @pytest.fixture
    def mock_ors_response(self):
        return {
            "routes": [
                {"geometry": "encoded_polyline_1", "distance": 325800, "duration": 11700, "segments": []},
                {"geometry": "encoded_polyline_2", "distance": 318000, "duration": 12600, "segments": []},
                {"geometry": "encoded_polyline_3", "distance": 338000, "duration": 12000, "segments": []},
            ]
        }
    
    def test_get_routes_success(self, client, mock_ors_response, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url="https://api.openrouteservice.org/v2/directions/driving-hgv",
            json=mock_ors_response,
            match_headers={"Authorization": "test-key"}
        )
        routes = client.get_routes(Point(-89.65, 39.78), Point(-87.63, 41.88))
        
        assert len(routes) == 3
        assert all(r.distance_miles > 0 for r in routes)
        assert all(r.duration_minutes > 0 for r in routes)
        assert all(r.geometry is not None for r in routes)
    
    def test_get_routes_fewer_than_3(self, client, httpx_mock):
        """Handle case where ORS returns < 3 alternatives."""
        httpx_mock.add_response(json={"routes": [{"geometry": "...", "distance": 100000, "duration": 3600}]})
        routes = client.get_routes(Point(-89.65, 39.78), Point(-87.63, 41.88))
        assert len(routes) == 1
    
    def test_get_routes_no_route_found(self, client, httpx_mock):
        httpx_mock.add_response(json={"routes": []})
        with pytest.raises(NoRouteFoundError):
            client.get_routes(Point(-89.65, 39.78), Point(-87.63, 41.88))
    
    def test_get_routes_timeout(self, client, httpx_mock):
        httpx_mock.add_exception(httpx.TimeoutException)
        with pytest.raises(RoutingAPIError):
            client.get_routes(Point(-89.65, 39.78), Point(-87.63, 41.88))
```

### Service Tests (`test_services.py`)
```python
class TestCheckpointSampling:
    @pytest.fixture
    def route(self):
        """Create a route with known geometry (straight line ~100 miles)."""
        line = LineString([(-89.65, 39.78), (-87.63, 41.88)])
        route = Route.objects.create(
            geometry=line, distance_miles=Decimal('100.00'),
            duration_minutes=120, request=...
        )
        return route
    
    def test_origin_checkpoint(self, route):
        checkpoints = create_checkpoints(route, 25, timezone.now())
        origin = checkpoints[0]
        assert origin.sequence == 0
        assert origin.mile_marker == Decimal('0.00')
        assert origin.latitude == 39.78
        assert origin.longitude == -89.65
    
    def test_destination_checkpoint(self, route):
        checkpoints = create_checkpoints(route, 25, timezone.now())
        dest = checkpoints[-1]
        assert dest.mile_marker == Decimal('100.00')
        assert dest.latitude == 41.88
        assert dest.longitude == -87.63
    
    def test_interval_checkpoints(self, route):
        """Test 25-mile intervals on 100-mile route."""
        checkpoints = create_checkpoints(route, 25, timezone.now())
        # Origin + 25, 50, 75 + Destination = 5 checkpoints
        assert len(checkpoints) == 5
        markers = [c.mile_marker for c in checkpoints]
        assert markers == [0, 25, 50, 75, 100]
    
    def test_10_mile_intervals(self, route):
        checkpoints = create_checkpoints(route, 10, timezone.now())
        assert len(checkpoints) == 11  # 0, 10, 20, ..., 100
    
    def test_50_mile_intervals(self, route):
        checkpoints = create_checkpoints(route, 50, timezone.now())
        assert len(checkpoints) == 3  # 0, 50, 100
    
    def test_eta_calculation(self, route):
        departure = timezone.make_aware(datetime(2026, 10, 27, 8, 0, 0))
        checkpoints = create_checkpoints(route, 25, departure)
        
        # At 25 miles (1/4 of route), should be 30 minutes (1/4 of 120)
        cp_25 = checkpoints[1]
        expected = departure + timedelta(minutes=30)
        assert cp_25.estimated_arrival == expected
    
    def test_short_route_only_origin_dest(self):
        """Route < interval should have only origin + destination."""
        line = LineString([(-89.65, 39.78), (-89.60, 39.80)])  # ~2 miles
        route = Route.objects.create(geometry=line, distance_miles=Decimal('2.0'), duration_minutes=5, ...)
        
        checkpoints = create_checkpoints(route, 25, timezone.now())
        assert len(checkpoints) == 2
        assert checkpoints[0].mile_marker == 0
        assert checkpoints[1].mile_marker == Decimal('2.00')
```

### Task Tests (`test_tasks.py`)
```python
class TestGenerateRoutesTask:
    @pytest.mark.django_db
    def test_task_success(self, mock_ors_client):
        request = RouteRequest.objects.create(...)
        
        result = generate_routes_task(request.id)
        
        request.refresh_from_db()
        assert request.status == 'completed'
        assert request.routes.count() == 3
        assert all(r.checkpoints.exists() for r in request.routes.all())
    
    @pytest.mark.django_db
    def test_task_retry_on_failure(self, mock_ors_client):
        mock_ors_client.side_effect = RoutingAPIError("Service unavailable")
        request = RouteRequest.objects.create(...)
        
        with pytest.raises(RoutingAPIError):
            generate_routes_task(request.id)
        
        request.refresh_from_db()
        # Should still be pending/processing for retry
        assert request.status in ['pending', 'processing']
    
    @pytest.mark.django_db
    def test_task_enqueues_weather(self, mock_ors_client, mock_weather_task):
        request = RouteRequest.objects.create(...)
        
        generate_routes_task(request.id)
        
        # Verify weather task enqueued for each route's checkpoints
        assert mock_weather_task.delay.call_count == 3
        for call in mock_weather_task.delay.call_args_list:
            cp_ids = call[0][0]
            assert len(cp_ids) > 0
```

## Integration Tests (`test_integration.py`)
```python
class TestRoutingIntegration:
    @pytest.mark.django_db
    def test_full_generation_flow(self, client, mock_ors_client, mock_weather_task):
        """Test: POST generate → Poll status → Get results"""
        
        # 1. Start generation
        response = client.post("/api/v1/routes/generate/", {
            "origin": {"address": "Springfield, IL", "latitude": 39.78, "longitude": -89.65},
            "destination": {"address": "Chicago, IL", "latitude": 41.88, "longitude": -87.63},
            "departure_time": "2026-10-27T08:00:00-05:00",
            "load_weight_lbs": 45000
        }, format='json')
        
        assert response.status_code == 202
        task_id = response.data['task_id']
        
        # 2. Poll until complete (in test, run task synchronously)
        from apps.routing.tasks import generate_routes_task
        generate_routes_task(task_id)
        
        # 3. Get results
        response = client.get(f"/api/v1/routes/{task_id}/")
        assert response.status_code == 200
        assert response.data['status'] == 'completed'
        assert len(response.data['routes']) == 3
        
        for route in response.data['routes']:
            assert 'id' in route
            assert 'geometry' in route
            assert 'checkpoints' in route
            assert len(route['checkpoints']) > 0
    
    @pytest.mark.django_db
    def test_route_detail_endpoint(self, client, completed_route_request):
        route = completed_route_request.routes.first()
        response = client.get(f"/api/v1/routes/{route.id}/")
        
        assert response.status_code == 200
        assert response.data['id'] == str(route.id)
        assert 'geometry' in response.data
```

## Contract Tests

```python
class TestRoutingAPIContract:
    def test_generate_response_schema(self, client, mock_ors_client):
        response = client.post("/api/v1/routes/generate/", VALID_REQUEST, format='json')
        
        assert response.status_code == 202
        assert 'task_id' in response.data
        assert 'status' in response.data
        assert 'poll_url' in response.data
    
    def test_status_response_schema(self, client, completed_task):
        response = client.get(f"/api/v1/routes/{completed_task}/")
        
        assert response.status_code == 200
        assert response.data['status'] == 'completed'
        assert 'routes' in response.data
        
        for route in response.data['routes']:
            required = ['id', 'route_index', 'name', 'distance_miles', 'duration_minutes', 'geometry', 'checkpoints']
            for field in required:
                assert field in route
```

## Fixtures (`fixtures.py`)
```python
MOCK_ORS_RESPONSE_3_ROUTES = {
    "routes": [
        {"geometry": {"type": "LineString", "coordinates": [[-89.65, 39.78], [-87.63, 41.88]]}, "distance": 325800, "duration": 11700},
        {"geometry": {"type": "LineString", "coordinates": [[-89.65, 39.78], [-88.00, 40.50], [-87.63, 41.88]]}, "distance": 318000, "duration": 12600},
        {"geometry": {"type": "LineString", "coordinates": [[-89.65, 39.78], [-88.50, 40.00], [-87.63, 41.88]]}, "distance": 338000, "duration": 12000},
    ]
}

VALID_GENERATE_REQUEST = {
    "origin": {"address": "Springfield, IL", "latitude": 39.7817, "longitude": -89.6501},
    "destination": {"address": "Chicago, IL", "latitude": 41.8781, "longitude": -87.6298},
    "departure_time": "2026-10-27T08:00:00-05:00",
    "load_weight_lbs": 45000
}

@pytest.fixture
def mock_ors_client(httpx_mock):
    httpx_mock.add_response(json=MOCK_ORS_RESPONSE_3_ROUTES)
    return httpx_mock

@pytest.fixture
def mock_weather_task():
    with patch('apps.weather.tasks.fetch_weather_for_checkpoints.delay') as mock:
        yield mock
```

## Running Tests

```bash
# All routing tests
pytest apps/routing/tests/ -v

# With coverage
pytest apps/routing/tests/ --cov=apps.routing --cov-report=term-missing --cov-fail-under=85

# Specific areas
pytest apps/routing/tests/test_services.py -v  # Checkpoint logic
pytest apps/routing/tests/test_tasks.py -v     # Async flow
pytest apps/routing/tests/test_integration.py -v  # Full flow
```