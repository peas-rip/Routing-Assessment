# AI Implementation Guide

## Project Overview

**Project**: Weather-Aware Truck Routing (Spotter)
**Stack**: React + Django (Service-Oriented Architecture)
**Target**: Truck drivers choosing safest routes based on weather, load weight, travel time
**Scale**: Small (100-1,000 users)
**Deliverables**: GitHub repo, hosted app, 5-10 min Loom walkthrough

---

## Architecture Summary

### Service Decomposition
| Service | Responsibility | Port | Key Tables |
|---------|---------------|------|------------|
| Geocoding | Address search, autocomplete, reverse geocode | 8000 | `geocode_cache` |
| Routing | Route generation, checkpoint sampling, ETA | 8000 | `route_requests`, `routes`, `checkpoints` |
| Weather | Weather fetching, caching, heatmap grids | 8000 | `weather_observations`, `heatmap_cache` |
| Risk | Risk calculation, route scoring, recommendation | 8000 | `risk_assessments`, `route_scores` |
| Frontend | UI, map, heatmap, user interaction | 5173/443 | (Consumes APIs) |

### Communication
- **Sync**: REST APIs (JSON)
- **Async**: Celery + Redis (route gen, weather fetch, risk calc)
- **Data Flow**: Geocoding → Routing → Weather → Risk → Frontend

---

## Development Order

1. **Geocoding Service** (Independent - start here)
2. **Routing Service** (Depends on Geocoding for input)
3. **Weather Service** (Depends on Routing for checkpoints)
4. **Risk Service** (Depends on Routing + Weather)
5. **Frontend** (Integrates all APIs)

---

## Key Constraints

### Non-Negotiable Requirements
1. **Risk thresholds MUST match specification exactly**:
   - Wind: <25/25-34/35-44/45-54/≥55 mph
   - Rain: <0.10/0.10-0.25/0.25-0.50/0.50-1.00/>1.00 in/hr
   - Snow: <0.5/0.5-1.0/1.0-2.0/2.0-3.0/>3.0 in/hr

2. **Load escalation rules MUST apply**:
   - Wind ≥55 → No Travel (any load)
   - Wind 45-54 + Load >30,000 → No Travel
   - Wind 35-44 + Load >40,000 → Severe

3. **Route recommendation priority (in order)**:
   1. Fewest Severe+No Travel miles
   2. Fewest High miles
   3. Lowest average risk score
   4. Shortest travel time

4. **Checkpoint intervals**: 10, 25, or 50 miles (user selectable)

5. **Heatmap**: 0-48 hour slider with smooth animation

### Technical Constraints
- **External APIs**: OpenRouteService (routing/geocoding), OpenWeatherMap (weather)
- **Rate limits**: ORS 2,000/day, OWM 1,000/day/60/min
- **Forecast horizon**: 48 hours max
- **Cache TTLs**: Weather 15min, Geocode 30 days, Heatmap 10 min

---

## Security Requirements

- HTTPS only (Let's Encrypt)
- Rate limiting on all endpoints
- API keys in environment variables only
- No PII stored (addresses cached but not linked to users)
- Input validation on all user inputs
- CORS restricted to frontend domain

---

## Quality Requirements

### Testing
- **Unit tests**: >90% coverage on business logic (especially Risk Service)
- **Integration tests**: Happy path + error paths per service
- **E2E tests**: Critical user flows (5-10 Playwright tests)
- **Property-based tests**: Risk calculation boundaries

### Code Quality
- **Backend**: Ruff (lint), Black (format), mypy (types)
- **Frontend**: ESLint, Prettier, TypeScript strict mode
- **Pre-commit hooks**: All quality checks

### Performance
- Route generation: <10s P95
- Map render: <2s initial
- Heatmap slider: 60fps
- API responses: <500ms cached

---

## Important Decisions (From TECHNOLOGY_DECISIONS.md)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Database | PostgreSQL + PostGIS | Geospatial, JSONB, Django ORM |
| Cache/Queue | Redis | Sub-ms, pub/sub, Celery broker |
| Async | Celery + Redis | Mature Django integration |
| Deployment | VPS + Docker Compose | Cost predictability, simplicity |
| Routing API | OpenRouteService | Free tier, HGV profile, alternatives |
| Geocoding | OpenRouteService | Same provider, free tier |
| Weather API | OpenWeatherMap One Call 3.0 | 48hr hourly, free tier |
| Maps | Mapbox GL JS | Native heatmap, WebGL performance |
| Frontend State | TanStack Query + Zustand | Server/client state separation |

---

## Service Specifications (Reference)

### Geocoding Service (`apps/geocoding/`)
- `GET /geocoding/search/?q={query}&limit=5` - Autocomplete
- `GET /geocoding/reverse/?lat={lat}&lon={lon}` - Reverse
- Cache: Redis + DB (30 day TTL)

### Routing Service (`apps/routing/`)
- `POST /routes/generate/` - Returns task_id (202)
- `GET /routes/{task_id}/` - Poll for status/results
- `GET /routes/{route_id}/` - Single route detail
- Celery: `generate_routes` task
- Checkpoints at 10/25/50 mile intervals

### Weather Service (`apps/weather/`)
- `GET /weather/checkpoints/?checkpoint_ids=...` - Bulk fetch
- `GET /weather/heatmap/?route_id=...&hour=6` - Heatmap grid
- Celery: `fetch_weather_for_checkpoints`, `generate_heatmap`
- Cache: Redis 15min + DB persistence

### Risk Service (`apps/risk/`)
- `POST /risk/calculate/` - Risk per checkpoint
- `GET /risk/recommendation/{route_id}/` - Scored routes + recommendation
- **Pure logic** - no external calls
- Celery: `calculate_risk_for_checkpoint`, `score_route`

---

## File Structure Reference

```
backend/
├── config/settings/          # Django settings (base, dev, prod, test)
├── apps/
│   ├── geocoding/           # F01
│   ├── routing/             # F02, F03
│   ├── weather/             # F04, F08
│   └── risk/                # F05, F06
├── common/                   # Shared utilities
└── requirements/             # Pip deps per env

frontend/
├── src/
│   ├── api/                 # API client + TanStack Query hooks
│   ├── components/
│   │   ├── map/             # MapView, RouteLayer, HeatmapLayer
│   │   ├── forms/           # RouteInputForm, AddressAutocomplete
│   │   └── display/         # RouteSummary, RiskBadge, TimeSlider
│   ├── hooks/               # useRoutes, useRisk, useWeather
│   ├── stores/              # Zustand stores
│   ├── pages/               # HomePage, RouteResultsPage
│   └── types/               # TypeScript interfaces
```

---

## Implementation Checklist

### Phase 1: Foundation
- [ ] Docker Compose dev environment
- [ ] Django project + PostGIS + Redis
- [ ] React + Vite + TS + Tailwind + Mapbox
- [ ] Geocoding Service (F01) complete
- [ ] Basic map with search

### Phase 2: Routing
- [ ] Routing Service (F02, F03) complete
- [ ] 3 routes render on map
- [ ] Checkpoint markers visible
- [ ] Async polling UI works

### Phase 3: Weather & Risk
- [ ] Weather Service (F04) complete
- [ ] Risk Service (F05, F06) complete
- [ ] Risk colors on map
- [ ] Route comparison table
- [ ] Recommendation logic verified

### Phase 4: Heatmap & Polish
- [ ] Heatmap (F08) complete
- [ ] 0-48hr slider + animation
- [ ] Mobile responsive
- [ ] Accessibility audit
- [ ] Performance optimization

### Phase 5: Deploy
- [ ] Production VPS setup
- [ ] SSL + Domain
- [ ] CI/CD pipeline
- [ ] Backups configured
- [ ] Loom walkthrough recorded
- [ ] GitHub repo public

---

## Testing Priorities

### Critical (Must Pass)
1. **Risk calculation** - Every threshold boundary, every load rule
2. **Route scoring** - All 4 priority levels, tie-breaking
3. **Checkpoint sampling** - Correct intervals, ETAs
4. **Weather fetching** - Deduplication, caching, rate limiting

### Important
1. API contract compliance
2. Async task flows (success, retry, failure)
3. Map rendering correctness
4. Heatmap data accuracy

### Nice to Have
1. Load testing
2. Chaos engineering (API failures)
3. Visual regression tests

---

## Common Pitfalls to Avoid

| Pitfall | Prevention |
|---------|------------|
| Floating point precision in risk thresholds | Use `Decimal`, test boundaries exactly |
| Load rule logic errors | Exhaustive unit tests with all combinations |
| Timezone bugs in ETAs | Use timezone-aware datetimes everywhere |
| Weather cache stampede | Use Redis `SETNX` or Celery singleton |
| Map geometry crossing antimeridian | Normalize longitudes, test Pacific routes |
| Heatmap memory leaks | Clean up Mapbox sources on unmount |
| Celery task duplication | Idempotency keys, DB unique constraints |
| API rate limit exhaustion | Token bucket, respect `Retry-After` headers |

---

## Debugging Tips

### Backend
```bash
# View logs
docker compose logs -f django
docker compose logs -f celery

# Django shell
docker compose exec django python manage.py shell

# Run tests
docker compose exec django pytest apps/risk/tests/ -v

# Check Celery tasks
docker compose exec django python manage.py shell -c "
from apps.routing.tasks import generate_routes
print(generate_routes.delay('uuid').get())
"
```

### Frontend
```bash
# Dev server
cd frontend && npm run dev

# Type check
npm run typecheck

# Lint
npm run lint

# Test
npm run test
```

### Database
```bash
# Connect
docker compose exec postgres psql -U spotter -d spotter

# Check PostGIS
SELECT PostGIS_Version();

# Query routes
SELECT * FROM routes WHERE request_id = '...';
```

---

## API Testing Examples

```bash
# Geocoding
curl "http://localhost:8000/api/v1/geocoding/search/?q=Springfield&limit=3"

# Generate routes
curl -X POST http://localhost:8000/api/v1/routes/generate/ \
  -H "Content-Type: application/json" \
  -d '{"origin":{"address":"...","latitude":39.78,"longitude":-89.65},"destination":{"address":"...","latitude":41.88,"longitude":-87.63},"departure_time":"2026-10-27T08:00:00-05:00","load_weight_lbs":45000}'

# Poll status
curl http://localhost:8000/api/v1/routes/{task_id}/

# Calculate risk
curl -X POST http://localhost:8000/api/v1/risk/calculate/ \
  -H "Content-Type: application/json" \
  -d '{"route_id":"...","load_weight_lbs":45000,"checkpoint_interval_miles":25}'

# Get recommendation
curl http://localhost:8000/api/v1/risk/recommendation/{route_id}/

# Heatmap
curl "http://localhost:8000/api/v1/weather/heatmap/?route_id=...&hour=6"
```

---

## Deployment Commands

```bash
# Initial deploy
git clone <repo> /opt/spotter
cd /opt/spotter
cp .env.example .env.production  # Edit with real values
docker compose -f docker-compose.prod.yml up -d

# Update deploy
cd /opt/spotter
git pull
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate
docker compose -f docker-compose.prod.yml run --rm django python manage.py collectstatic --noinput
docker compose -f docker-compose.prod.yml up -d

# Backup
/opt/spotter/scripts/backup-db.sh

# Logs
docker compose -f docker-compose.prod.yml logs -f --tail=100
```

---

## Next Steps for Implementation Agent

1. **Start with Geocoding Service** - Simplest, no dependencies
2. **Follow IMPLEMENTATION_ORDER.md** task breakdown
3. **Write tests FIRST** for Risk Service (TDD critical here)
4. **Use FEATURE_XX.md** specs as implementation contracts
5. **Match API_CONTRACTS.md** exactly for frontend integration
6. **Deploy early** to catch environment issues
7. **Record Loom** as you build features

---

## Questions for Clarification

If any requirement is ambiguous, check:
1. **PRD.md** - Business requirements
2. **FEATURE_XX.md** - Detailed feature specs
3. **API_CONTRACTS.md** - Exact request/response formats
4. **DATABASE_SCHEMA.md** - Data models
5. **TECHNOLOGY_DECISIONS.md** - Approved tech choices

**Do not guess** - architecture documents are the source of truth.