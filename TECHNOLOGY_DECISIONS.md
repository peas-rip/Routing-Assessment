# Technology Decisions

## Project Context
- **Project**: Weather-Aware Truck Routing
- **Stack**: React + Django (confirmed)
- **Scale**: Small (100-1,000 users)
- **APIs**: OpenStreetMap/OSRM + National Weather Service (NWS) (confirmed)

---

## Database Evaluation

### Recommended Options

| Option | Pros | Cons | Cost | Scaling | Operational Complexity |
|--------|------|------|------|---------|------------------------|
| **PostgreSQL** (Recommended) | ACID compliant, JSONB support, PostGIS for geospatial, mature, excellent Django ORM support | Slightly more complex than SQLite | Free (open source) | Vertical + read replicas, partitioning | Medium |
| **SQLite** | Zero config, file-based, simple | No concurrent writes, no geospatial (without extensions), not production-ready for web | Free | Very limited | Low |
| **MySQL** | Good Django support, widely used | Weaker geospatial vs PostGIS, JSON support less mature | Free | Vertical + read replicas | Medium |

### Recommendation: **PostgreSQL with PostGIS**

**Reasoning**:
1. **Geospatial requirements**: Route coordinates, checkpoints, heatmap data need PostGIS
2. **Django ORM**: First-class support with `django.contrib.gis`
3. **JSONB**: Weather API responses, route metadata storage
4. **Scale**: Handles 1,000 users easily with room to grow
5. **Cost**: Free, runs on any VPS/cloud

**Decision Status**: ✅ **APPROVED** (aligns with requirements)

---

## Cache Evaluation

### Recommended Options

| Option | Pros | Cons | Cost | Scaling | Operational Complexity |
|--------|------|------|------|---------|------------------------|
| **Redis** (Recommended) | Sub-ms latency, pub/sub, TTL, persistence options, Django cache backend | Additional service to manage | Free (self-hosted) | Cluster mode, sentinel | Low-Medium |
| **Memcached** | Simple, fast, multi-threaded | No persistence, no pub/sub, limited data types | Free | Horizontal sharding | Low |
| **Django Local Memory** | No extra infrastructure | Not shared across workers, lost on restart | Free | None | Very Low |
| **Database Cache (PostgreSQL)** | No extra service | Slower, adds DB load | Included | With DB | Low |

### Recommendation: **Redis**

**Reasoning**:
1. **Weather API caching**: Cache forecast data (TTL 10-30 min)
2. **Route caching**: Cache computed routes for repeated queries
3. **Session storage**: Django sessions
4. **Rate limiting**: API rate limit tracking
5. **Celery broker**: If async tasks needed later

**Decision Status**: ⏳ **PENDING APPROVAL**

---

## Queue Evaluation

### Recommended Options

| Option | Pros | Cons | Cost | Scaling | Operational Complexity |
|--------|------|------|------|---------|------------------------|
| **Celery + Redis** (Recommended) | Mature Django integration, scheduled tasks, retries, monitoring | Additional components | Free (self-hosted) | Horizontal workers | Medium |
| **Django-Q** | Simpler, uses DB/Redis, built-in admin | Less features, smaller community | Free | Limited | Low |
| **RQ (Redis Queue)** | Simple, Pythonic, good dashboard | Less features than Celery | Free | Horizontal | Low |
| **No queue (sync)** | Simplest | Blocks request, timeouts on slow APIs | Free | None | None |

### Recommendation: **Celery + Redis**

**Reasoning**:
1. **Weather API calls**: Multiple parallel requests per route (3 routes × checkpoints)
2. **Route computation**: Non-blocking route generation
3. **Scheduled tasks**: Cache warming, cleanup
4. **Django integration**: `django-celery-beat` for periodic tasks
5. **Scale**: Handles small scale easily, grows with needs

**Decision Status**: ⏳ **PENDING APPROVAL**

---

## Search Engine Evaluation

### Recommended Options

| Option | Pros | Cons | Cost | Scaling | Operational Complexity |
|--------|------|------|------|---------|------------------------|
| **PostgreSQL Full Text Search** (Recommended) | Built-in, no extra service, good for location search | Less advanced than dedicated engines | Included | With DB | Low |
| **Elasticsearch** | Powerful, fuzzy search, analytics | Heavy, complex, extra cost | Higher | Horizontal | High |
| **Meilisearch** | Fast, typo-tolerant, easy setup | Extra service, younger | Free (self-hosted) | Horizontal | Medium |
| **Algolia** | Managed, excellent DX | Expensive at scale, vendor lock-in | Pay per request | Managed | Low |

### Recommendation: **PostgreSQL Full Text Search**

**Reasoning**:
1. **Use case**: Geocoding search (origin/destination autocomplete)
2. **Scale**: Small (1,000 users) - Postgres FTS sufficient
3. **Simplicity**: No extra infrastructure
4. **Integration**: `django.contrib.postgres.search` built-in
5. **Cost**: Zero additional

**Decision Status**: ✅ **APPROVED** (no extra infrastructure needed)

---

## Cloud/Deployment Evaluation

### Recommended Options

| Option | Pros | Cons | Cost (Monthly Est.) | Scaling | Operational Complexity |
|--------|------|------|---------------------|---------|------------------------|
| **VPS (DigitalOcean/Hetzner/Linode)** (Recommended) | Full control, predictable cost, simple | Manual scaling, no managed services | $20-40 (2-4 GB RAM) | Vertical + manual horizontal | Medium |
| **AWS (EC2 + RDS + ElastiCache)** | Managed services, auto-scaling, global | Complex, unpredictable costs | $50-200+ | Excellent | High |
| **Azure/GCP** | Similar to AWS, good enterprise features | Similar complexity | $50-200+ | Excellent | High |
| **Railway/Render/Fly.io** | Simple deploy, managed DB/Redis, auto-scale | Less control, vendor-specific | $20-100 | Good | Low |
| **Docker + Kubernetes (Self-hosted)** | Full control, portable | Overkill for small scale, complex | Varies | Excellent | Very High |

### Recommendation: **VPS (DigitalOcean/Hetzner) with Docker Compose**

**Reasoning**:
1. **Scale**: Small (1,000 users) - single VPS sufficient
2. **Cost**: Predictable $20-40/month vs variable cloud costs
3. **Simplicity**: Docker Compose for orchestration
4. **Control**: Full root access, no vendor lock-in
5. **Migration path**: Can move to Kubernetes later if needed

**Components on VPS**:
- Nginx (reverse proxy, SSL termination)
- React (static files via Nginx)
- Django (Gunicorn)
- PostgreSQL + PostGIS
- Redis
- Celery workers

**Decision Status**: ⏳ **PENDING APPROVAL**

---

## Frontend Technology Details

### Confirmed: React

| Component | Choice | Reason |
|-----------|--------|--------|
| **Build Tool** | Vite | Fast, modern, React template |
| **State Management** | React Query (TanStack Query) + Zustand | Server state + client state |
| **Routing** | React Router v6 | Standard |
| **Maps** | Mapbox GL JS or Leaflet | Mapbox for heatmap, Leaflet lighter |
| **UI Library** | Tailwind CSS + Headless UI | Utility-first, accessible components |
| **Charts** | Recharts or Chart.js | Risk visualization |
| **Date/Time** | date-fns or Day.js | Lightweight |

**Decision Status**: ✅ **APPROVED** (standard React stack)

---

## Backend Technology Details

### Confirmed: Django

| Component | Choice | Reason |
|-----------|--------|--------|
| **API Framework** | Django REST Framework | Mature, serialization, auth, viewsets |
| **Geospatial** | GeoDjango + PostGIS | Built-in, powerful |
| **Async Tasks** | Celery + Redis | Background weather/route processing |
| **Auth** | JWT (djangorestframework-simplejwt) | Stateless, scalable |
| **API Docs** | drf-spectacular (OpenAPI 3) | Auto-generated Swagger/ReDoc |
| **Testing** | pytest + pytest-django | Modern, fixtures |
| **Code Quality** | Ruff (linting) + Black (formatting) | Fast, consistent |

**Decision Status**: ✅ **APPROVED** (standard Django stack)

---

## External API Integration

### Routing: OSRM (Open Source Routing Machine)
- **Hosting**: Self-hosted on VPS or public demo server (rate limited)
- **Alternative**: OpenRouteService (free tier: 2,000 req/day)
- **Data**: OpenStreetMap extracts

### Geocoding: Nominatim (OSM) or OpenRouteService
- **Self-hosted**: Nominatim on VPS (requires ~50GB+ disk)
- **Managed**: OpenRouteService, LocationIQ (free tiers available)

### Weather: National Weather Service (NWS)
- **Free Tier**: 1,000 calls/day, 60 calls/min
- **Paid**: $40/month for higher limits
- **Data**: Current, forecast (48hr), historical

**Decision Status**: ⏳ **PENDING APPROVAL** (self-hosted vs managed APIs)

---

## Summary of Pending Decisions

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| 1 | Cache | Redis / Memcached / None | **Redis** |
| 2 | Queue | Celery+Redis / Django-Q / RQ / None | **Celery + Redis** |
| 3 | Deployment | VPS / AWS / PaaS / K8s | **VPS + Docker Compose** |
| 4 | Routing API Hosting | Self-hosted OSRM / OpenRouteService / Other | **OpenRouteService (start), self-host later** |
| 5 | Geocoding | Self-hosted Nominatim / OpenRouteService / LocationIQ | **OpenRouteService/LocationIQ (start)** |

---

## Next Steps

1. **Review and approve** pending decisions above
2. **Confirm** deployment target (VPS provider preference)
3. **Proceed** to architecture design phase (PRD, System Architecture, etc.)