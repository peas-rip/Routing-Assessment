# Feature to Service Mapping

## Overview

Each feature is owned by exactly one service. Services may implement multiple features. Clear ownership avoids ambiguity and enables independent development.

---

## Mapping Table

| Feature ID | Feature Name | Owning Service | API Endpoints | Database Tables |
|------------|--------------|----------------|---------------|-----------------|
| F01 | Route Input & Geocoding | **Geocoding Service** | `GET /geocoding/search/`, `GET /geocoding/reverse/` | `geocode_cache` |
| F02 | Route Generation | **Routing Service** | `POST /routes/generate/`, `GET /routes/{id}/` | `route_requests`, `routes`, `checkpoints` |
| F03 | Checkpoint Sampling | **Routing Service** | (Part of route generation) | `checkpoints` |
| F04 | Weather Fetching & Caching | **Weather Service** | `GET /weather/checkpoints/`, `GET /weather/heatmap/` | `weather_observations`, `heatmap_cache` |
| F05 | Risk Calculation | **Risk Service** | `POST /risk/calculate/` | `risk_assessments` |
| F06 | Route Scoring & Recommendation | **Risk Service** | `GET /risk/recommendation/{route_id}/` | `route_scores` |
| F07 | Map Visualization | **Frontend** (consumes Routing + Risk APIs) | `GET /routes/{id}/`, `GET /risk/recommendation/` | (Read-only) |
| F08 | Weather Heatmap | **Weather Service** + **Frontend** | `GET /weather/heatmap/` | `heatmap_cache` |

---

## Service Ownership Details

### Geocoding Service
**Owns**: F01 - Route Input & Geocoding

**Responsibilities**:
- Address autocomplete/search
- Forward geocoding (address → lat/lon)
- Reverse geocoding (lat/lon → address)
- Caching geocoding results (TTL: 30 days)
- Rate limiting external geocoding API

**APIs Exposed**:
- `GET /api/v1/geocoding/search/?q={query}&limit=5`
- `GET /api/v1/geocoding/reverse/?lat={lat}&lon={lon}`

**Events Produced**: None
**Events Consumed**: None

**Data Owned**: `geocode_cache` table

---

### Routing Service
**Owns**: F02 - Route Generation, F03 - Checkpoint Sampling

**Responsibilities**:
- Call external routing API (OpenRouteService/OSRM) for 3 route options
- Store route geometries, distances, durations
- Sample checkpoints at 10/25/50 mile intervals
- Calculate estimated arrival time at each checkpoint
- Enqueue weather fetching for checkpoints
- Track route generation status (async)

**APIs Exposed**:
- `POST /api/v1/routes/generate/`
- `GET /api/v1/routes/{task_id}/` (status + results)
- `GET /api/v1/routes/{route_id}/` (single route details)

**Events Produced**:
- `route.generated` - Route created with checkpoints
- `route.failed` - Generation failed

**Events Consumed**: None

**Data Owned**: `route_requests`, `routes`, `checkpoints` tables

**Dependencies**:
- External: OpenRouteService (routing)
- Internal: Weather Service (via async task enqueue)

---

### Weather Service
**Owns**: F04 - Weather Fetching & Caching, F08 - Weather Heatmap

**Responsibilities**:
- Fetch weather forecasts for checkpoints at estimated arrival times
- Cache weather data (TTL: 15 minutes)
- Handle API rate limits (OpenWeatherMap: 60/min)
- Generate weather heatmap grids along route corridors
- Pre-compute heatmap for 0-48 hour slider
- Bulk fetch for multiple checkpoints (parallel)

**APIs Exposed**:
- `GET /api/v1/weather/checkpoints/?checkpoint_ids=uuid1,uuid2,...`
- `GET /api/v1/weather/heatmap/?route_id={id}&hour={0-48}`

**Events Produced**:
- `weather.fetched` - Weather data stored for checkpoint(s)
- `weather.heatmap.ready` - Heatmap grid computed

**Events Consumed**:
- `route.generated` → Enqueue weather fetching for new checkpoints

**Data Owned**: `weather_observations`, `heatmap_cache` tables

**Dependencies**:
- External: OpenWeatherMap API
- Internal: Routing Service (consumes route.generated event)

---

### Risk Service
**Owns**: F05 - Risk Calculation, F06 - Route Scoring & Recommendation

**Responsibilities**:
- Classify weather conditions per risk thresholds (wind, rain, snow)
- Apply load-based escalation rules
- Calculate combined risk per checkpoint
- Score routes per priority rules (Severe miles → High miles → Avg risk → Duration)
- Determine recommended route
- Pure business logic - no external dependencies

**APIs Exposed**:
- `POST /api/v1/risk/calculate/`
- `GET /api/v1/risk/recommendation/{route_id}/`

**Events Produced**:
- `risk.calculated` - Risk assessments stored
- `route.scored` - Route scores computed

**Events Consumed**:
- `weather.fetched` → Trigger risk calculation for affected checkpoints

**Data Owned**: `risk_assessments`, `route_scores` tables

**Dependencies**:
- Internal: Routing Service (reads routes/checkpoints), Weather Service (reads weather)

---

### Frontend (React Application)
**Owns**: F07 - Map Visualization (presentation layer)

**Responsibilities**:
- User input form (origin, destination, departure, load weight)
- Display 3 routes on map with color-coded risk segments
- Show checkpoint markers with risk levels
- Display route summaries (distance, time, risk breakdown)
- Interactive weather heatmap with 0-48 hour slider
- Poll for async route generation status
- Error handling & loading states

**APIs Consumed**:
- Geocoding: `/geocoding/search/`, `/geocoding/reverse/`
- Routing: `/routes/generate/`, `/routes/{id}/`
- Risk: `/risk/calculate/`, `/risk/recommendation/{route_id}/`
- Weather: `/weather/heatmap/`

**No Database Ownership** - Pure consumer of backend APIs

---

## Cross-Service Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Geocoding  │────▶│   Routing   │────▶│   Weather   │────▶│    Risk     │
│   Service   │     │   Service   │     │   Service   │     │   Service   │
│   (F01)     │     │   (F02,F03) │     │   (F04)     │     │   (F05,F06) │
└─────────────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
                           │                     │                  │
                           │                     ▼                  │
                           │              ┌─────────────┐           │
                           └────────────▶│  Frontend   │◀──────────┘
                                         │   (F07,F08) │
                                         └─────────────┘
```

### Async Flow Details

1. **User submits route request** → Frontend calls `POST /routes/generate/`
2. **Routing Service** creates `RouteRequest`, enqueues `generate_routes` task, returns `task_id`
3. **Celery Worker** (Routing):
   - Calls OpenRouteService for 3 routes
   - Saves `Route` + `Checkpoint` records
   - Emits `route.generated` event (or directly enqueues weather tasks)
4. **Celery Worker** (Weather):
   - Consumes `route.generated` / receives task
   - Fetches weather for all checkpoints in parallel
   - Saves `WeatherObservation` records
   - Emits `weather.fetched` event
5. **Celery Worker** (Risk):
   - Consumes `weather.fetched`
   - Calculates risk for each checkpoint
   - Saves `RiskAssessment` records
   - Computes route scores, saves `RouteScore`
   - Emits `route.scored` event
6. **Frontend** polls `/routes/{task_id}/` → Gets complete routes
7. **Frontend** calls `/risk/calculate/` per route → Gets risk data
8. **Frontend** calls `/risk/recommendation/{route_id}/` → Gets scored routes + recommendation
9. **Frontend** renders map with all data

---

## Ownership Rules

### 1. Single Writer Principle
Each table has exactly one service that writes to it:
- `geocode_cache` → Geocoding Service
- `route_requests`, `routes`, `checkpoints` → Routing Service
- `weather_observations`, `heatmap_cache` → Weather Service
- `risk_assessments`, `route_scores` → Risk Service

### 2. Read Access
Services may read tables owned by other services for:
- Generating responses (Risk Service reads routes/checkpoints/weather)
- Building API responses (Frontend reads via API only)

### 3. No Direct Database Access Across Services
All cross-service communication via:
- REST APIs (synchronous)
- Celery tasks / Events (asynchronous)

### 4. Shared Models = Coupling
Django models are defined in the owning service's app. Other services import models only for:
- ForeignKey references (with `related_name`)
- Type hints (using `TYPE_CHECKING`)

---

## API Contract Ownership

| Endpoint | Owner | Version |
|----------|-------|---------|
| `/geocoding/*` | Geocoding Service | v1 |
| `/routes/*` | Routing Service | v1 |
| `/weather/*` | Weather Service | v1 |
| `/risk/*` | Risk Service | v1 |

Each service owns its URL namespace and can version independently.

---

## Testing Boundaries

### Unit Tests (Per Service)
- **Geocoding**: Client wrapper, cache logic, search parsing
- **Routing**: Route parsing, checkpoint sampling math, geometry handling
- **Weather**: Forecast time matching, cache logic, heatmap grid generation
- **Risk**: **All risk rules** (thresholds, load escalation, scoring priority) - most critical

### Integration Tests (Per Service)
- **Geocoding**: External API mocking
- **Routing**: External routing API mocking, async task flow
- **Weather**: External weather API mocking, bulk fetch
- **Risk**: End-to-end with real Route/Checkpoint/Weather fixtures

### Contract Tests
- API schema validation (drf-spectacular)
- Frontend API client matches backend schema

### E2E Tests (Frontend)
- Full user flow: Input → Routes → Risk → Map → Heatmap
- Critical paths only (5-10 tests)

---

## Deployment Independence

| Service | Can Deploy Independently? | Notes |
|---------|---------------------------|-------|
| Geocoding | Yes | No dependencies on other services |
| Routing | Yes | Only needs DB + Redis + External API |
| Weather | Yes | Only needs DB + Redis + External API |
| Risk | Yes | Only needs DB (reads other tables) |
| Frontend | Yes | Only needs backend APIs |

**Shared Infrastructure**: PostgreSQL, Redis, Nginx
**Deployment Order**: Any order (database migrations run automatically)

---

## Future Service Extraction Candidates

If scale demands:

| Candidate | Current Location | Extraction Trigger |
|-----------|------------------|-------------------|
| **Map Tile Service** | Frontend (Mapbox) | Self-hosted tiles, cost optimization |
| **Notification Service** | N/A (future) | Push alerts, driver notifications |
| **Analytics Service** | N/A (future) | Route history, risk trends, reporting |
| **Auth Service** | N/A (future) | Multi-user, roles, SSO |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-10-27 | Risk calculation + scoring in same service | Tightly coupled logic, same domain, no external deps |
| 2026-10-27 | Checkpoint sampling in Routing Service | Part of route generation, needs route geometry |
| 2026-10-27 | Heatmap in Weather Service | Weather data aggregation, same caching strategy |
| 2026-10-27 | Geocoding separate from Routing | Different external API, different caching, reusable |