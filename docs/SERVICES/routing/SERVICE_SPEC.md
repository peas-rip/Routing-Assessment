# Service Specification: Routing Service

## Service Overview

**Name**: Routing Service
**Purpose**: Generate route options, sample checkpoints, calculate ETAs
**Business Ownership**: Route Planning team
**Technical Ownership**: Backend team

## Service Boundaries

### Owns
- Route generation from origin to destination
- Checkpoint sampling at 10/25/50 mile intervals
- Estimated arrival time calculation
- Route request tracking (`route_requests`, `routes`, `checkpoints` tables)
- External routing API integration (OpenRouteService)

### Must Never Own
- Weather data fetching
- Risk calculation
- Geocoding (consumes Geocoding Service)
- User authentication

## Data Ownership

### Entities Owned
- `RouteRequest` - Generation request tracking
- `Route` - Route geometry, distance, duration, metadata
- `Checkpoint` - Sampling points with ETAs

### Relationships Owned
- RouteRequest → Routes (1:3)
- Route → Checkpoints (1:N)

## Dependencies

### Internal
- **Geocoding Service** - Consumes for input validation (read-only)
- **Weather Service** - Produces checkpoints for (async enqueue)
- **Risk Service** - Produces routes/checkpoints for (read-only)

### External
- **OpenRouteService Directions API** - Primary routing
  - Endpoint: `/v2/directions/driving-hgv`
  - Profile: `driving-hgv` (heavy goods vehicle)
  - Alternatives: `target_count=3`
  - Rate limit: 2,000 req/day

## Communication

### APIs Exposed
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/routes/generate/` | Start async route generation |
| GET | `/api/v1/routes/{task_id}/` | Poll generation status/results |
| GET | `/api/v1/routes/{route_id}/` | Get single route detail |

### Events Produced
- `route.generated` - Routes + checkpoints saved, triggers weather fetch
- `route.failed` - Generation failed

### Events Consumed
- None

## Security Requirements

### Authentication
- v1: No auth
- Future: JWT required

### Authorization
- Rate limit: 10 req/min per IP on generate
- Rate limit: 60 req/min per IP on status/detail

### Data Protection
- Route geometries stored in PostGIS
- No PII in route data
- Task IDs are UUIDs (unguessable)

## Observability Requirements

### Logging
- Log: request_id, provider, route count, duration, checkpoint count
- Structured JSON with correlation IDs

### Metrics
- Generation latency (p50, p95, p99)
- Success/failure rate
- External API latency
- Checkpoints per route

### Monitoring
- Health check: routing API connectivity
- Alert: Generation failure rate > 5%
- Alert: P95 latency > 15s

---

## Development Guide

### Local Development
```bash
# Start dependencies
docker compose up -d postgres redis

# Run migrations
python manage.py migrate

# Run service tests
pytest apps/routing/tests/ -v

# Run Celery worker (separate terminal)
celery -A config worker -l info -Q routing

# Run server
python manage.py runserver 0.0.0.0:8000
```

### Key Files
```
apps/routing/
├── models.py          # RouteRequest, Route, Checkpoint
├── clients/
│   └── openrouteservice.py  # RoutingClient
├── services.py        # generate_routes, create_checkpoints, calculate_etas
├── tasks.py           # generate_routes_task
├── views.py           # GenerateView, StatusView, DetailView
├── serializers.py     # RouteSerializer, CheckpointSerializer
├── urls.py            # URL routing
├── managers.py        # Custom querysets
└── tests/
    ├── test_models.py
    ├── test_services.py
    ├── test_tasks.py
    └── test_views.py
```

### Implementation Patterns

#### Routing Client
```python
# apps/routing/clients/openrouteservice.py
class RoutingClient:
    def __init__(self):
        self.base_url = settings.OPENROUTESERVICE_BASE_URL
        self.api_key = settings.OPENROUTESERVICE_API_KEY
        self.timeout = 30.0  # Longer for routing
    
    def get_routes(self, origin: Point, destination: Point) -> List[RouteData]:
        """Call ORS with alternatives for 3 routes."""
        params = {
            'coordinates': [[origin.x, origin.y], [destination.x, destination.y]],
            'profile': 'driving-hgv',
            'alternative_routes': {
                'target_count': 3,
                'share_factor': 0.6,
                'weight_factor': 1.5
            },
            'instructions': True,
            'geometry': True,
            'units': 'mi'
        }
        # POST to /v2/directions/driving-hgv
        # Parse response to RouteData objects
```

#### Checkpoint Sampling (PostGIS)
```python
# apps/routing/services.py
def create_checkpoints(route: Route, interval_miles: float, departure: datetime) -> List[Checkpoint]:
    """Sample checkpoints along route geometry at mile intervals."""
    from django.contrib.gis.geos import LineString
    from django.contrib.gis.measure import Distance
    
    line = route.geometry  # LineString in WGS84
    total_miles = route.distance_miles
    
    # Use PostGIS for accurate distance interpolation
    checkpoints = []
    sequence = 0
    
    # Origin
    checkpoints.append(Checkpoint(
        route=route, sequence=sequence, mile_marker=0,
        latitude=line.coords[0][1], longitude=line.coords[0][0],
        estimated_arrival=departure
    ))
    sequence += 1
    
    # Intermediate points
    miles = interval_miles
    while miles < total_miles:
        fraction = miles / total_miles
        point = line.interpolate(fraction, normalized=True)
        
        # Calculate ETA proportionally
        elapsed_minutes = (miles / total_miles) * route.duration_minutes
        eta = departure + timedelta(minutes=elapsed_minutes)
        
        checkpoints.append(Checkpoint(
            route=route, sequence=sequence, mile_marker=round(miles, 2),
            latitude=point.y, longitude=point.x, estimated_arrival=eta
        ))
        sequence += 1
        miles += interval_miles
    
    # Destination (always include)
    if checkpoints[-1].mile_marker != total_miles:
        checkpoints.append(Checkpoint(
            route=route, sequence=sequence, mile_marker=round(total_miles, 2),
            latitude=line.coords[-1][1], longitude=line.coords[-1][0],
            estimated_arrival=departure + timedelta(minutes=route.duration_minutes)
        ))
    
    return Checkpoint.objects.bulk_create(checkpoints)
```

#### Celery Task
```python
# apps/routing/tasks.py
@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def generate_routes_task(self, request_id: str):
    request = RouteRequest.objects.get(id=request_id)
    request.status = 'processing'
    request.save()
    
    try:
        # 1. Call routing API
        client = RoutingClient()
        routes_data = client.get_routes(request.origin_point, request.destination_point)
        
        # 2. Save routes
        routes = []
        for i, rd in enumerate(routes_data):
            route = Route.objects.create(
                request=request, route_index=i, name=name_route(rd, i, routes_data),
                distance_miles=rd.distance_miles, duration_minutes=rd.duration_minutes,
                geometry=rd.geometry, summary=rd.summary
            )
            routes.append(route)
        
        # 3. Create checkpoints for each route
        for route in routes:
            create_checkpoints(route, request.checkpoint_interval_miles, request.departure_time)
        
        # 4. Enqueue weather fetching
        for route in routes:
            checkpoint_ids = list(route.checkpoints.values_list('id', flat=True))
            fetch_weather_for_checkpoints.delay(checkpoint_ids)
        
        request.status = 'completed'
        request.completed_at = timezone.now()
        
    except RoutingAPIError as e:
        request.status = 'failed'
        request.error_message = str(e)
        raise self.retry(exc=e)
    finally:
        request.save()
```

---

## Testing Guide

### Unit Tests
- **Client**: Mock ORS responses, test parsing, alternative route handling
- **Services**: Checkpoint sampling math, ETA calculation, geometry handling
- **Tasks**: Retry logic, status transitions, weather enqueue

### Integration Tests
- Full async flow: Generate → Poll → Complete
- Partial failures (1 of 3 routes fails)
- Geometry edge cases (short routes, long routes, loops)

### Test Fixtures
```python
# Mock ORS response with 3 alternatives
MOCK_ORS_RESPONSE = {
    "routes": [
        {"geometry": "...", "distance": 325800, "duration": 11700, "segments": [...]},
        {"geometry": "...", "distance": 318000, "duration": 12600, "segments": [...]},
        {"geometry": "...", "distance": 338000, "duration": 12000, "segments": [...]}
    ]
}
```

### Coverage Targets
- Client: 95%
- Services: 90% (geometry math critical)
- Tasks: 90%
- Views: 85%

---

## Deployment Guide

### Configuration
```bash
OPENROUTESERVICE_API_KEY=ors_xxx
OPENROUTESERVICE_BASE_URL=https://api.openrouteservice.org
CELERY_BROKER_URL=redis://redis:6379/1
```

### Health Check
```python
def check_routing():
    try:
        client = RoutingClient()
        # Quick test with known coordinates
        client.get_routes(Point(-89.65, 39.78), Point(-87.63, 41.88))
        return "ok"
    except Exception as e:
        return f"degraded: {e}"
```

### Scaling
- Celery workers: Scale `-c` concurrency or add worker containers
- Queue separation: `-Q routing` for dedicated workers
- Database: Read replicas for status polling

### Database Migrations
- Always backward compatible
- Test migration + rollback locally
- Run before deploy: `python manage.py migrate`