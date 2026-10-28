# Deployment Guide: Risk Service

## Configuration

### Environment Variables
```bash
# No external API keys needed (pure computation)

# Celery
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# Optional
RISK_CALCULATION_TIMEOUT=30
```

### Celery Queue Configuration
```python
# config/celery.py
app.conf.task_routes = {
    'apps.risk.tasks.calculate_risk_for_checkpoint': {'queue': 'risk'},
    'apps.risk.tasks.score_route': {'queue': 'risk'},
    'apps.risk.tasks.recommend_route': {'queue': 'risk'},
}
```

## Health Checks

```python
# apps/risk/health.py
def check_risk():
    try:
        # Test calculation with known values
        from apps.risk.rules import classify_wind, classify_rain, classify_snow, apply_load_rules
        from decimal import Decimal
        from apps.risk.rules import RiskLevel
        
        # Verify thresholds haven't drifted
        assert classify_wind(Decimal('30')) == RiskLevel.MODERATE
        assert classify_rain(Decimal('0.2')) == RiskLevel.MODERATE
        assert classify_snow(Decimal('1.0')) == RiskLevel.HIGH
        
        # Verify load rules
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('50'), 30001) == (RiskLevel.NO_TRAVEL, "wind_45_54_over_30k")
        assert apply_load_rules(RiskLevel.HIGH, Decimal('40'), 40001) == (RiskLevel.SEVERE, "wind_35_44_over_40k")
        
        return {"status": "healthy", "rules_verified": True}
    except AssertionError:
        return {"status": "unhealthy", "reason": "Risk rule verification failed - thresholds may have changed"}
    except Exception as e:
        return {"status": "unhealthy", "reason": str(e)}
```

## Scaling

### Celery Workers
```bash
# Dedicated risk workers (CPU-bound, fast)
celery -A config worker -l info -Q risk -c 4

# Scale horizontally by adding more containers
# docker compose up -d --scale celery-risk=3
```

### Read Replica Support
```python
# Risk service is READ-ONLY on other services' tables
# Can use read replicas for:
# - Route/Checkpoint queries
# - WeatherObservation queries

# In settings:
DATABASES = {
    'default': {...},  # Primary (writes)
    'replica': {...},  # Read replica
}

# Use in querysets:
RiskAssessment.objects.using('replica').filter(...)
```

### Capacity Planning
| Metric | Threshold | Action |
|--------|-----------|--------|
| Calculation latency p95 | > 100ms | Optimize queries, add indexes |
| Queue depth | > 50 | Add worker |
| DB connections | > 80% | Use read replica |

## Monitoring

### Key Metrics
- Calculation latency (target <50ms/checkpoint)
- Risk distribution histogram
- Recommendation consistency
- Task throughput (checkpoints/sec)

### Alerts
```yaml
- alert: RiskCalculationErrors
  expr: rate(risk_calculation_errors_total[5m]) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Risk calculation errors detected - rules may be broken"

- alert: RiskCalculationSlow
  expr: histogram_quantile(0.95, risk_calculation_duration_seconds) > 0.1
  for: 5m
  labels:
    severity: warning
```

## Deployment Steps

### Initial Deployment
```bash
# 1. Run migrations
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate

# 2. CRITICAL: Run rule verification tests
docker compose -f docker-compose.prod.yml run --rm django \
  pytest apps/risk/tests/test_rules.py -v

# 3. Start services
docker compose -f docker-compose.prod.yml up -d
```

### Updates - **ZERO TOLERANCE FOR RULE CHANGES**

```bash
# 1. Run ALL risk tests BEFORE deploy
docker compose -f docker-compose.prod.yml run --rm django \
  pytest apps/risk/tests/ -v

# 2. If ANY test fails, DO NOT DEPLOY
# 3. Run migrations (if any)
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate

# 4. Deploy
docker compose -f docker-compose.prod.yml up -d --no-deps django celery
```

### Database Migrations
```bash
# Risk service rarely needs migrations
# If needed, test thoroughly:
docker compose exec django python manage.py makemigrations apps.risk --dry-run
docker compose exec django python manage.py migrate apps.risk --plan
```

## Critical Deployment Rules

### ❌ NEVER DO THESE
- Deploy without passing `test_rules.py` at 100%
- Change risk thresholds without full regression test
- Modify `rules.py` without updating `test_rules.py`
- Skip property-based tests in CI
- Deploy with uncommitted threshold changes

### ✅ ALWAYS DO THESE
- Run `pytest apps/risk/tests/test_rules.py -v` before every deploy
- Verify `apply_load_rules` behavior with manual test
- Check `calculate_combined_risk` with edge cases
- Monitor risk distribution after deploy

## Troubleshooting

### Common Issues

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| Risk calculation errors | Rule logic bug | Check `test_rules.py` failures |
| Wrong recommendation | Scoring priority bug | Verify composite score formula |
| Slow calculation | Missing indexes | Add indexes on `RiskAssessment` |
| Inconsistent results | Floating point | Use `Decimal` everywhere |

### Debug Commands
```bash
# Verify rules in production
docker compose exec django python manage.py shell -c "
from apps.risk.rules import *
from decimal import Decimal
print('Wind 30:', classify_wind(Decimal('30')))
print('Wind 50 + 35k load:', apply_load_rules(RiskLevel.SEVERE, Decimal('50'), 35000))
print('Wind 40 + 45k load:', apply_load_rules(RiskLevel.HIGH, Decimal('40'), 45000))
"

# Check risk distribution
docker compose exec django python manage.py shell -c "
from apps.risk.models import RiskAssessment
from django.db.models import Count
dist = RiskAssessment.objects.values('combined_risk').annotate(c=Count('id'))
for d in dist:
    print(f'{d[\"combined_risk\"]}: {d[\"c\"]}')
"

# View worker logs
docker compose logs -f celery | grep risk
```

## Backup/Recovery

### Data
- `RiskAssessment`: 90 days (derived, re-calculable)
- `RouteScore`: 90 days (derived, re-calculable)

### Recovery
```bash
# Recalculate all risk if needed
docker compose exec django python manage.py shell -c "
from apps.routing.models import Route
from apps.risk.tasks import calculate_risk_for_checkpoint, score_route

for route in Route.objects.all():
    for cp in route.checkpoints.all():
        calculate_risk_for_checkpoint.delay(str(cp.id))
    score_route.delay(str(route.id))
"
```

## Performance Tuning

### Database Indexes
```sql
-- For checkpoint risk queries
CREATE INDEX CONCURRENTLY idx_risk_checkpoint_combined 
ON risk_assessments (checkpoint_id, combined_risk);

-- For route scoring
CREATE INDEX CONCURRENTLY idx_risk_route_combined 
ON risk_assessments (combined_risk) 
WHERE checkpoint_id IN (SELECT id FROM checkpoints WHERE route_id = ?);
```

### Bulk Operations
```python
# Use bulk_create for risk assessments
RiskAssessment.objects.bulk_create(assessments, ignore_conflicts=True)

# Use bulk_update for route scores
RouteScore.objects.bulk_update(scores, ['composite_score', 'risk_breakdown'])
```

## Verification Checklist (Post-Deploy)

- [ ] Health check returns "healthy"
- [ ] `pytest apps/risk/tests/test_rules.py -v` passes
- [ ] Risk distribution looks normal (mostly low/moderate)
- [ ] Recommendation endpoint returns valid response
- [ ] No calculation errors in logs
- [ ] Latency < 100ms per checkpoint