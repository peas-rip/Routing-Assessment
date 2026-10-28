# Development Guide: Routing Service

## Quick Start

```bash
# 1. Start infrastructure
docker compose up -d postgres redis

# 2. Run migrations
python manage.py migrate

# 3. Run tests
pytest apps/routing/tests/ -v

# 4. Start Celery worker (terminal 1)
celery -A config worker -l info -Q routing

# 5. Start dev server (terminal 2)
python manage.py runserver 0.0.0.0:8000

# 6. Test API
curl -X POST http://localhost:8000/api/v1/routes/generate/ \
  -H "Content-Type: application/json" \
  -d '{"origin":{"address":"...","latitude":39.78,"longitude":-89.65},"destination":{"address":"...","latitude":41.88,"longitude":-87.63},"departure_time":"2026-10-27T08:00:00-05:00","load_weight_lbs":45000}'
```

## Project Structure

```
apps/routing/
├── __init__.py
├── admin.py
├── apps.py
├── models.py              # RouteRequest, Route, Checkpoint
├── managers.py            # RouteManager, CheckpointManager
├── clients/
│   ├── __init__.py
│   └── openrouteservice.py
├── services.py            # generate_routes, create_checkpoints, calculate_etas
├── tasks.py               # generate_routes_task
├── views.py               # GenerateView, StatusView, DetailView
├── serializers.py         # RouteSerializer, CheckpointSerializer
├── urls.py
├── validators.py          # Coordinate, weight validation
├── exceptions.py          # RoutingError, NoRouteFoundError
├── utils.py               # Geometry helpers, naming
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
    └── 0002_add_indexes.py
```

## Key Implementation Details

### Models
```python
# models.py
class RouteRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'), ('processing', 'Processing'),
        ('completed', 'Completed'), ('failed', 'Failed')
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    origin_address = models.TextField()
    origin_lat = models.FloatField()
    origin_lon = models.FloatField()
    destination_address = models.TextField()
    destination_lat = models.FloatField()
    destination_lon = models.FloatField()
    departure_time = models.DateTimeField()
    load_weight_lbs = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True)

class Route(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    request = models.ForeignKey(RouteRequest, on_delete=models.CASCADE, related_name='routes')
    route_index = models.IntegerField(choices=[(0,0),(1,1),(2,2)])
    name = models.CharField(max_length=100, blank=True)
    distance_miles = models.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = models.PositiveIntegerField()
    geometry = models.LineStringField(srid=4326)  # PostGIS
    summary = models.JSONField()
    is_recommended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Checkpoint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='checkpoints')
    sequence = models.PositiveIntegerField()
    mile_marker = models.DecimalField(max_digits=10, decimal_places=2)
    latitude = models.FloatField()
    longitude = models.FloatField()
    location = models.PointField(srid=4326, geography=True)
    estimated_arrival = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['sequence']
        indexes = [
            models.Index(fields=['route', 'sequence']),
            models.Index(fields=['estimated_arrival']),
        ]
```

### Routing Client
```python
# clients/openrouteservice.py
class RoutingClient:
    def __init__(self, api_key: str = None, timeout: float = 30.0):
        self.api_key = api_key or settings.OPENROUTESERVICE_API_KEY
        self.base_url = settings.OPENROUTESERVICE_BASE_URL
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({'Authorization': self.api_key})
    
    def get_routes(self, origin: Point, destination: Point) -> List[RouteData]:
        """Get 3 alternative routes for HGV profile."""
        coords = [[origin.x, origin.y], [destination.x, destination.y]]
        payload = {
            'coordinates': coords,
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
        response = self.session.post(
            f'{self.base_url}/v2/directions/driving-hgv',
            json=payload, timeout=self.timeout
        )
        response.raise_for_status()
        return self._parse_routes(response.json())
```

### Checkpoint Sampling
```python
# services.py
def create_checkpoints(route: Route, interval_miles: float, departure: datetime) -> List[Checkpoint]:
    """Sample checkpoints at mile intervals using PostGIS."""
    from django.contrib.gis.geos import LineString
    from django.contrib.gis.db.models.functions import Length
    
    line = route.geometry  # LineString in WGS84
    total_miles = float(route.distance_miles)
    
    checkpoints = []
    sequence = 0
    
    # Origin
    checkpoints.append(Checkpoint(
        route=route, sequence=sequence, mile_marker=Decimal('0.00'),
        latitude=line.coords[0][1], longitude=line.coords[0][0],
        estimated_arrival=departure
    ))
    sequence += 1
    
    # Intermediate
    miles = interval_miles
    while miles < total_miles:
        fraction = miles / total_miles
        point = line.interpolate(fraction, normalized=True)
        
        elapsed_minutes = (miles / total_miles) * route.duration_minutes
        eta = departure + timedelta(minutes=elapsed_minutes)
        
        checkpoints.append(Checkpoint(
            route=route, sequence=sequence, mile_marker=Decimal(str(round(miles, 2))),
            latitude=point.y, longitude=point.x, estimated_arrival=eta
        ))
        sequence += 1
        miles += interval_miles
    
    # Destination
    if checkpoints[-1].mile_marker != Decimal(str(total_miles)):
        checkpoints.append(Checkpoint(
            route=route, sequence=sequence, mile_marker=Decimal(str(round(total_miles, 2))),
            latitude=line.coords[-1][1], longitude=line.coords[-1][0],
            estimated_arrival=departure + timedelta(minutes=route.duration_minutes)
        ))
    
    return Checkpoint.objects.bulk_create(checkpoints)
```

### Celery Task
```python
# tasks.py
@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def generate_routes_task(self, request_id: str):
    request = RouteRequest.objects.get(id=request_id)
    request.status = 'processing'
    request.save()
    
    try:
        client = RoutingClient()
        routes_data = client.get_routes(request.origin_point, request.destination_point)
        
        routes = []
        for i, rd in enumerate(routes_data):
            route = Route.objects.create(
                request=request, route_index=i,
                name=name_route(rd, i, routes_data),
                distance_miles=rd.distance_miles,
                duration_minutes=rd.duration_minutes,
                geometry=rd.geometry, summary=rd.summary
            )
            routes.append(route)
        
        for route in routes:
            create_checkpoints(route, request.checkpoint_interval_miles, request.departure_time)
        
        # Enqueue weather fetching
        for route in routes:
            cp_ids = list(route.checkpoints.values_list('id', flat=True))
            fetch_weather_for_checkpoints.delay([str(id) for id in cp_ids])
        
        request.status = 'completed'
        request.completed_at = timezone.now()
        
    except RoutingAPIError as e:
        request.status = 'failed'
        request.error_message = str(e)
        raise self.retry(exc=e)
    finally:
        request.save()
```

## Debugging

```bash
# Test client directly
python manage.py shell -c "
from apps.routing.clients.openrouteservice import RoutingClient
from django.contrib.gis.geos import Point
client = RoutingClient()
routes = client.get_routes(Point(-89.65, 39.78), Point(-87.63, 41.88))
for r in routes:
    print(f'{r.distance_miles:.1f} mi, {r.duration_minutes} min')
"

# Check task status
python manage.py shell -c "
from apps.routing.models import RouteRequest
req = RouteRequest.objects.latest('created_at')
print(f'Status: {req.status}')
if req.status == 'completed':
    for r in req.routes.all():
        print(f'  Route {r.route_index}: {r.distance_miles} mi, {r.checkpoints.count()} checkpoints')
"

# Run worker with verbose logging
celery -A config worker -l debug -Q routing
```