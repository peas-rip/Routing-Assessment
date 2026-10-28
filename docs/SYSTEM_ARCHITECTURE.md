# System Architecture

## Overview

Weather-Aware Truck Routing follows a **Service-Oriented Architecture** with a Django backend API and React frontend. The system is decomposed into independent services that communicate via REST APIs and async message queues.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT (Browser)                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   Route     │  │   Map       │  │  Heatmap    │  │  Route      │        │
│  │   Input     │  │   View      │  │   View      │  │  Summary    │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
│         │                │                │                │                │
│         └────────────────┴────────────────┴────────────────┘                │
│                                  │                                          │
│                    ┌─────────────▼─────────────┐                            │
│                    │      React App            │                            │
│                    │   (Vite + TanStack Query) │                            │
│                    └─────────────┬─────────────┘                            │
└──────────────────────────────────│──────────────────────────────────────────┘
                                   │ HTTPS/REST
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NGINX (Reverse Proxy)                             │
│                    SSL Termination │ Static Files │ Rate Limit             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
               ┌───────────────────┼───────────────────┐
               ▼                   ▼                   ▼
┌─────────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   Django API        │ │   Django API    │ │   Django API    │
│   (Gunicorn Worker) │ │   (Gunicorn     │ │   (Gunicorn     │
│                     │ │    Worker)      │ │    Worker)      │
└─────────┬───────────┘ └────────┬────────┘ └────────┬────────┘
          │                      │                    │
          └──────────────────────┼────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│  PostgreSQL   │      │    Redis      │      │   Celery      │
│  + PostGIS    │      │   (Cache +    │      │   Workers     │
│  (Primary DB) │      │    Broker)    │      │   (Async)     │
└───────────────┘      └───────────────┘      └───────────────┘
        │                        │                        │
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│  Routes,      │      │  Weather      │      │  Route Gen,   │
│  Checkpoints, │      │  Cache,       │      │  Weather      │
│  Risk Scores, │      │  Sessions,    │      │  Fetch,       │
│  User Data    │      │  Rate Limits  │      │  Risk Calc    │
└───────────────┘      └───────────────┘      └───────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
            ┌───────────────┐         ┌───────────────┐
            │ OpenRoute     │         │ OpenWeather   │
            │ Service       │         │ Map           │
            │ (Routing +    │         │ (Weather      │
            │  Geocoding)   │         │  Forecasts)   │
            └───────────────┘         └───────────────┘
```

---

## Service Decomposition

### 1. API Gateway (Nginx)
- **Responsibility**: SSL termination, static file serving, rate limiting, request routing
- **Technology**: Nginx
- **Ports**: 80 (HTTP→HTTPS redirect), 443 (HTTPS)

### 2. Frontend Service (React)
- **Responsibility**: UI rendering, user interaction, state management, API communication
- **Technology**: React 18, Vite, TanStack Query, React Router, Mapbox GL JS/Leaflet
- **Deployment**: Static files served by Nginx

### 3. Routing Service (Django App: `routing`)
- **Responsibility**: Route generation, checkpoint sampling, route persistence
- **API**: `POST /api/routes/generate/`, `GET /api/routes/{id}/`
- **Dependencies**: OpenRouteService, PostgreSQL/PostGIS, Redis (cache)
- **Async**: Celery task for route generation

### 4. Weather Service (Django App: `weather`)
- **Responsibility**: Weather fetching, caching, forecast retrieval
- **API**: `GET /api/weather/checkpoints/`, `GET /api/weather/heatmap/`
- **Dependencies**: OpenWeatherMap, Redis (cache), PostgreSQL
- **Async**: Celery task for bulk weather fetching

### 5. Risk Service (Django App: `risk`)
- **Responsibility**: Risk calculation, route scoring, recommendation logic
- **API**: `POST /api/risk/calculate/`, `GET /api/risk/recommendation/{route_id}/`
- **Dependencies**: Routing Service, Weather Service, PostgreSQL
- **Pure Logic**: No external dependencies, fully testable

### 6. Geocoding Service (Django App: `geocoding`)
- **Responsibility**: Address autocomplete, forward/reverse geocoding
- **API**: `GET /api/geocoding/search/`, `GET /api/geocoding/reverse/`
- **Dependencies**: OpenRouteService/Nominatim, Redis (cache)
- **Async**: None (fast responses needed)

---

## Data Flow

### Route Generation Flow (Async)

```
User Request
    │
    ▼
POST /api/routes/generate/ ────▶ Django API (Routing Service)
    │                              │
    │                              ▼
    │                        Create RouteRequest record
    │                              │
    │                              ▼
    │                        Enqueue Celery task: generate_routes
    │                              │
    │                              ▼
    │                    ┌─────────────────────┐
    │                    │  Celery Worker      │
    │                    │  1. Call OSRM/ORS   │
    │                    │  2. Get 3 routes    │
    │                    │  3. Sample checkpts │
    │                    │  4. Enqueue weather │
    │                    └──────────┬──────────┘
    │                               │
    ▼                               ▼
Return task_id              For each route:
    │                          1. Save Route + Checkpoints
    │                          2. Enqueue fetch_weather(checkpoints)
    │                          3. Return route_id to client
    │
    ▼
Client polls GET /api/routes/{task_id}/status/
    │
    ▼
When complete: return routes with checkpoints
    │
    ▼
Client calls POST /api/risk/calculate/ for each route
    │
    ▼
Risk Service calculates risk per checkpoint
    │
    ▼
Client calls GET /api/risk/recommendation/{route_id}/
    │
    ▼
Returns scored routes + recommended route
```

### Weather Heatmap Flow

```
User moves time slider (0-48hr)
    │
    ▼
GET /api/weather/heatmap/?route_id=X&hour=Y
    │
    ▼
Weather Service checks Redis cache
    │
    ├─ Hit → Return cached grid
    │
    └─ Miss → 
         │
         ▼
    Generate heatmap grid along route corridor
         │
         ▼
    Fetch weather for grid points (parallel)
         │
         ▼
    Calculate risk per grid point
         │
         ▼
    Cache in Redis (TTL: 10 min)
         │
         ▼
    Return to client
```

---

## Communication Patterns

### Synchronous (REST)
- Frontend ↔ Django API (all user-facing operations)
- Django ↔ External APIs (with timeouts & retries)

### Asynchronous (Celery)
- Route generation (long-running)
- Bulk weather fetching (many checkpoints)
- Heatmap pre-computation (optional)
- Periodic cache warming

### Events (Future)
- Route completed → notify frontend (WebSockets/SSE)
- Weather alert → push notification

---

## Technology Stack Summary

| Layer | Technology | Version |
|-------|------------|---------|
| Frontend | React | 18.x |
| Build Tool | Vite | 5.x |
| State Management | TanStack Query + Zustand | 5.x / 4.x |
| Maps | Mapbox GL JS | 3.x |
| UI | Tailwind CSS + Headless UI | 3.x / 1.x |
| Backend | Django | 5.x |
| API Framework | Django REST Framework | 3.15.x |
| Geospatial | GeoDjango + PostGIS | 3.x / 3.4 |
| Database | PostgreSQL | 16.x |
| Cache/Queue | Redis | 7.x |
| Async Tasks | Celery | 5.x |
| Auth | JWT (simplejwt) | 5.x |
| API Docs | drf-spectacular | 0.27.x |
| Testing | pytest + pytest-django | 8.x / 4.x |
| Linting | Ruff | 0.5.x |
| Formatting | Black | 24.x |
| Reverse Proxy | Nginx | 1.26.x |
| Process Manager | systemd / Docker Compose | - |

---

## Security Architecture

### Network
```
Internet → Nginx (443) → Django (8000, internal)
                    → Redis (6379, internal)
                    → PostgreSQL (5432, internal)
```

### Authentication
- **v1**: No auth (single-user demo)
- **Future**: JWT tokens, refresh rotation, role-based access

### Data Protection
- HTTPS enforced via Nginx
- Secrets in environment variables (not code)
- Database passwords rotated
- API keys encrypted at rest

### Rate Limiting
- Nginx: 100 req/min per IP (general)
- Django: 30 req/min per IP (API endpoints)
- External APIs: Respect provider limits

---

## Observability

### Logging
- **Django**: Structured JSON logs (stdout)
- **Nginx**: Access + error logs
- **Celery**: Task success/failure/retries
- **Level**: INFO (prod), DEBUG (dev)

### Metrics (Future)
- Prometheus exporters for Django, Redis, PostgreSQL
- Grafana dashboards: latency, error rate, queue depth

### Health Checks
- `GET /health/` - DB, Redis, external API connectivity
- Kubernetes-style liveness/readiness probes

### Error Tracking (Future)
- Sentry integration for frontend + backend

---

## Scaling Strategy

### Current (Small Scale)
- Single VPS (4 GB RAM, 2 vCPU)
- All services on one machine via Docker Compose
- PostgreSQL + Redis local

### Medium Scale (1,000-10,000 users)
- Separate VPS for DB (managed PostgreSQL)
- Separate VPS for Redis (managed or self-hosted)
- 2+ Django workers behind load balancer
- CDN for static assets

### Large Scale (10,000+ users)
- Kubernetes deployment
- Read replicas for PostgreSQL
- Redis Cluster
- Multiple Celery worker pools
- Regional deployments

---

## Disaster Recovery

### Backup Strategy
- **PostgreSQL**: Daily pg_dump to object storage (S3-compatible), 30-day retention
- **Redis**: RDB snapshots every 6 hours (non-critical, cache only)
- **Code/Config**: Git repository (source of truth)

### Recovery Time Objective (RTO)
- **Target**: <1 hour for full restore
- **Process**: Provision VPS → Docker Compose up → Restore DB dump

### Recovery Point Objective (RPO)
- **Target**: <24 hours data loss
- **Achieved by**: Daily DB backups

---

## Development Architecture

### Local Development
```yaml
# docker-compose.yml
services:
  postgres:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_DB: spotter
      POSTGRES_USER: spotter
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: [redis_data:/data]

  django:
    build: ./backend
    command: python manage.py runserver 0.0.0.0:8000
    volumes: [./backend:/app]
    ports: ["8000:8000"]
    depends_on: [postgres, redis]
    environment:
      - DATABASE_URL=postgres://spotter:${DB_PASSWORD}@postgres:5432/spotter
      - REDIS_URL=redis://redis:6379/0
      - DEBUG=1

  celery:
    build: ./backend
    command: celery -A config worker -l info
    volumes: [./backend:/app]
    depends_on: [postgres, redis]
    environment:
      - DATABASE_URL=postgres://spotter:${DB_PASSWORD}@postgres:5432/spotter
      - REDIS_URL=redis://redis:6379/0

  frontend:
    build: ./frontend
    command: npm run dev -- --host
    volumes: [./frontend:/app, /app/node_modules]
    ports: ["5173:5173"]
```

### CI/CD Pipeline (GitHub Actions)
1. **Lint**: Ruff, Black, TypeScript/ESLint
2. **Test**: pytest (backend), Vitest (frontend)
3. **Build**: Docker images
4. **Deploy**: SSH to VPS → docker compose pull && up -d

---

## API Versioning
- **Strategy**: URL versioning (`/api/v1/`)
- **Current**: v1 only
- **Deprecation**: 6-month notice, sunset headers

---

## Cross-Cutting Concerns

| Concern | Implementation |
|---------|----------------|
| Correlation IDs | Middleware adds `X-Request-ID` to all requests |
| Request Timeout | Nginx: 30s, Django: 25s, External APIs: 10s |
| CORS | Django CORS headers for frontend origin |
| Compression | Nginx gzip for API responses, Brotli for static |
| Caching Headers | `Cache-Control` on static assets, `ETag` on API |
| Input Validation | DRF serializers + custom validators |
| SQL Injection | Django ORM only, no raw SQL |
| XSS | React auto-escaping, Django template escaping |
| CSRF | DRF session auth (if enabled), SameSite cookies |