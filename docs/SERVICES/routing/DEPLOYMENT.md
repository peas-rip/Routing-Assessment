# Deployment Guide: Routing Service

## Configuration

### Environment Variables
```bash
# Required
OPENROUTESERVICE_API_KEY=ors_xxx
OPENROUTESERVICE_BASE_URL=https://api.openrouteservice.org

# Celery
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# Optional
ROUTING_DEFAULT_INTERVAL_MILES=25
ROUTING_MAX_RETRIES=3
ROUTING_TIMEOUT_SECONDS=30
```

### Celery Queue Configuration
```python
# config/celery.py
app.conf.task_routes = {
    'apps.routing.tasks.generate_routes_task': {'queue': 'routing'},
}
app.conf.worker_prefetch_multiplier = 1  # One task per worker for long tasks
```

## Health Checks

```python
# apps/routing/health.py
def check_routing():
    try:
        client = RoutingClient()
        # Quick test with nearby coordinates
        routes = client.get_routes(Point(-89.65, 39.78), Point(-89.60, 39.80))
        if routes and len(routes) > 0:
            return {"status": "healthy", "provider": "openrouteservice", "test_routes": len(routes)}
        return {"status": "degraded", "reason": "No routes returned"}
    except RateLimitError:
        return {"status": "degraded", "reason": "Rate limited"}
    except Exception as e:
        return {"status": "unhealthy", "reason": str(e)}
```

## Scaling

### Celery Workers
```bash
# Dedicated routing workers
celery -A config worker -l info -Q routing -c 2 --prefetch-multiplier=1

# Scale horizontally by adding more worker containers
# docker compose up -d --scale celery-routing=3
```

### Queue Separation
```yaml
# docker-compose.prod.yml
celery-routing:
  command: celery -A config worker -l info -Q routing -c 2
  deploy:
    resources:
      limits:
        memory: 1G
```

### Capacity Planning
| Metric | Threshold | Action |
|--------|-----------|--------|
| Queue depth | > 10 pending | Add worker |
| Task duration p95 | > 20s | Check ORS latency |
| Failure rate | > 5% | Check ORS status |
| DB connections | > 80% | Add pgbouncer |

## Monitoring

### Key Metrics
- Generation latency (p50, p95, p99)
- Success/failure rate
- Routes per request (should be 3)
- Checkpoints per route
- Weather enqueue rate

### Alerts
```yaml
- alert: RoutingGenerationFailures
  expr: rate(routing_generation_failed_total[5m]) > 0.05
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Route generation failure rate > 5%"

- alert: RoutingHighLatency
  expr: histogram_quantile(0.95, routing_generation_duration_seconds) > 20
  for: 5m
  labels:
    severity: warning
```

## Deployment Steps

### Initial Deployment
```bash
# 1. Run migrations (includes PostGIS indexes)
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate

# 2. Verify PostGIS extension
docker compose exec postgres psql -U spotter -d spotter -c "SELECT PostGIS_Version();"

# 3. Start services
docker compose -f docker-compose.prod.yml up -d
```

### Updates
```bash
# Standard deploy
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate
docker compose -f docker-compose.prod.yml up -d --no-deps django celery
```

### Database Migrations
```bash
# Check for pending migrations
docker compose exec django python manage.py showmigrations apps.routing

# Run specific migration
docker compose exec django python manage.py migrate apps.routing 0002

# Create new migration
docker compose exec django python manage.py makemigrations apps.routing
```

## Troubleshooting

### Common Issues

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| No routes generated | ORS returns empty | Check coordinates, try different profile |
| Task stuck processing | Celery worker down | Check worker logs, restart |
| Checkpoints missing | Sampling error | Check distance calculation |
| Geometry invalid | PostGIS error | Validate LineString before save |

### Debug Commands
```bash
# Check Celery queue
docker compose exec django python manage.py shell -c "
from celery import current_app
i = current_app.control.inspect()
print('Active:', i.active())
print('Scheduled:', i.scheduled())
print('Reserved:', i.reserved())
"

# Check task status
docker compose exec django python manage.py shell -c "
from apps.routing.models import RouteRequest
for r in RouteRequest.objects.all().order_by('-created_at')[:5]:
    print(f'{r.id}: {r.status} ({r.routes.count()} routes)')
"

# View worker logs
docker compose logs -f celery | grep routing

# Test ORS directly
curl -X POST "https://api.openrouteservice.org/v2/directions/driving-hgv" \
  -H "Authorization: $ORS_KEY" -H "Content-Type: application/json" \
  -d '{"coordinates":[[-89.65,39.78],[-87.63,41.88]],"alternative_routes":{"target_count":3}}'
```

## Backup/Recovery

### Critical Data
- `route_requests` - Request history
- `routes` - Generated routes
- `checkpoints` - Sampling points

### Recovery
```bash
# Restore from backup
gunzip -c backup.sql.gz | docker exec -i postgres psql -U spotter -d spotter

# Verify PostGIS data
docker compose exec postgres psql -U spotter -d spotter -c "
SELECT COUNT(*) FROM apps_routing_route;
SELECT COUNT(*) FROM apps_routing_checkpoint;
"
```

## Performance Tuning

### Database
```sql
-- Index for status polling
CREATE INDEX CONCURRENTLY idx_route_requests_status_created 
ON route_requests (status, created_at DESC);

-- Spatial index for checkpoint queries
CREATE INDEX CONCURRENTLY idx_checkpoints_location 
ON checkpoints USING GIST (location);
```

### Celery
```python
# Increase prefetch for short tasks, decrease for long
app.conf.worker_prefetch_multiplier = 1  # For long routing tasks

# Acknowledge after completion (not before)
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
```