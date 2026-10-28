# Deployment Architecture

## Overview

Single VPS deployment using Docker Compose for the small-scale target (100-1,000 users). Designed for simplicity, cost predictability, and operational ease.

---

## Infrastructure Design

### Target Environment
- **Provider**: DigitalOcean / Hetzner / Linode (VPS)
- **Specs**: 4 GB RAM, 2 vCPU, 80 GB SSD (~$24-40/month)
- **OS**: Ubuntu 22.04 LTS
- **Container Runtime**: Docker Engine + Docker Compose v2

### Network Architecture
```
Internet
    │
    ▼
┌─────────────────────────────────────┐
│         VPS (Public IP)             │
│  ┌─────────────────────────────┐    │
│  │        Nginx (443/80)       │    │
│  │  SSL Termination            │    │
│  │  Static Files (React)       │    │
│  │  Rate Limiting              │    │
│  │  Proxy → Backend:8000       │    │
│  └──────────────┬──────────────┘    │
│                 │                   │
│  ┌──────────────┼──────────────┐    │
│  │              │              │    │
│  ▼              ▼              ▼    │
│ ┌──────┐    ┌────────┐    ┌──────┐  │
│ │Django│    │Postgres│    │Redis │  │
│ │:8000 │    │:5432   │    │:6379 │  │
│ └──────┘    └────────┘    └──────┘  │
│       ▲                                │
│       │ Celery Workers                 │
│       ▼                                │
│ ┌──────────┐                           │
│ │ Celery   │                           │
│ │ Workers  │                           │
│ └──────────┘                           │
└─────────────────────────────────────┘
```

### Component Details

#### Nginx (Reverse Proxy)
- **Image**: `nginx:alpine`
- **Ports**: 80 (redirect), 443 (HTTPS)
- **Volumes**: 
  - `./nginx/conf.d:/etc/nginx/conf.d`
  - `./certbot/conf:/etc/letsencrypt`
  - `./certbot/www:/var/www/certbot`
  - `./frontend/dist:/var/www/frontend` (static files)
- **Features**:
  - SSL termination (Let's Encrypt)
  - Gzip/Brotli compression
  - Rate limiting zones
  - Security headers (HSTS, CSP, X-Frame-Options)
  - Static file caching (1 year for hashed assets)

#### Django Application
- **Image**: Custom (multi-stage Dockerfile)
- **Process**: Gunicorn (3 workers, sync)
- **Port**: 8000 (internal)
- **Env**: Production settings
- **Health Check**: `GET /health/`

#### Celery Workers
- **Image**: Same as Django
- **Process**: `celery -A config worker -l info -c 2`
- **Queues**: `default`, `routing`, `weather`, `risk`
- **Concurrency**: 2 per worker (adjustable)
- **Monitoring**: Flower (optional, port 5555)

#### PostgreSQL + PostGIS
- **Image**: `postgis/postgis:16-3.4`
- **Port**: 5432 (internal)
- **Volumes**: `postgres_data:/var/lib/postgresql/data`
- **Extensions**: postgis, uuid-ossp, pg_trgm
- **Config**: `shared_buffers=512MB`, `max_connections=100`

#### Redis
- **Image**: `redis:7-alpine`
- **Port**: 6379 (internal)
- **Volumes**: `redis_data:/data`
- **Config**: `maxmemory 256mb`, `maxmemory-policy allkeys-lru`
- **Databases**: 0 (cache), 1 (Celery broker), 2 (results)

---

## Docker Compose Production

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  nginx:
    build: ./infrastructure/nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./infrastructure/nginx/conf.d:/etc/nginx/conf.d
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
      - frontend_static:/var/www/frontend
    depends_on:
      - django
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  django:
    build:
      context: ./backend
      dockerfile: Dockerfile.prod
    expose:
      - "8000"
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.production
      - DATABASE_URL=postgres://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - CELERY_RESULT_BACKEND=redis://redis:6379/2
      - OPENROUTESERVICE_API_KEY=${OPENROUTESERVICE_API_KEY}
      - OPENWEATHERMAP_API_KEY=${OPENWEATHERMAP_API_KEY}
      - SECRET_KEY=${SECRET_KEY}
      - ALLOWED_HOSTS=${ALLOWED_HOSTS}
      - FRONTEND_URL=https://${DOMAIN}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M

  celery:
    build:
      context: ./backend
      dockerfile: Dockerfile.prod
    command: celery -A config worker -l info -c 2 -Q default,routing,weather,risk
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.production
      - DATABASE_URL=postgres://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - CELERY_RESULT_BACKEND=redis://redis:6379/2
      - OPENROUTESERVICE_API_KEY=${OPENROUTESERVICE_API_KEY}
      - OPENWEATHERMAP_API_KEY=${OPENWEATHERMAP_API_KEY}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G

  celery-beat:
    build:
      context: ./backend
      dockerfile: Dockerfile.prod
    command: celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.production
      - DATABASE_URL=postgres://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  postgres:
    image: postgis/postgis:16-3.4
    environment:
      - POSTGRES_DB=${DB_NAME}
      - POSTGRES_USER=${DB_USER}
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./infrastructure/postgres/init:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M

volumes:
  postgres_data:
  redis_data:
  frontend_static:
```

---

## Networking Design

### DNS & SSL
- **Domain**: `app.example.com` (A record → VPS IP)
- **SSL**: Let's Encrypt via Certbot (auto-renewal)
- **Certbot**: Runs in separate container or host cron

### Firewall (UFW)
```bash
# Allow SSH (rate limited)
ufw limit 22/tcp

# Allow HTTP/HTTPS
ufw allow 80/tcp
ufw allow 443/tcp

# Deny all other incoming
ufw default deny incoming
ufw default allow outgoing

# Enable
ufw enable
```

### Internal Network
- All containers on `default` bridge network
- No exposed ports except Nginx (80/443)
- Database/Redis only accessible internally

---

## Scaling Strategy

### Vertical Scaling (Current)
- Increase VPS size (RAM/CPU)
- Adjust Gunicorn workers: `(2 * CPU) + 1`
- Adjust Celery concurrency
- Increase PostgreSQL `shared_buffers`

### Horizontal Scaling (Future)
| Component | Strategy |
|-----------|----------|
| Django | Add 2nd VPS, load balance with Nginx upstream |
| Celery | Add worker containers on new VPS, same Redis |
| PostgreSQL | Read replicas (managed service) |
| Redis | Redis Cluster or managed ElastiCache |
| Static Files | CDN (Cloudflare, CloudFront) |

### Trigger Points
- CPU > 70% sustained → Scale up
- Request queue > 100 → Add workers
- DB connections > 80% → Read replica
- Redis memory > 80% → Increase/Cluster

---

## Monitoring Strategy

### Health Checks
```bash
# Nginx
curl -f http://localhost/health || exit 1

# Django
curl -f http://django:8000/health/ || exit 1

# Celery
celery -A config inspect ping
```

### Log Aggregation
- **Driver**: `json-file` with rotation (10MB, 3 files)
- **Future**: Loki + Grafana or ELK stack
- **Key Logs**:
  - Nginx access/error
  - Django application (JSON structured)
  - Celery task success/failure/retries
  - PostgreSQL slow queries

### Metrics (Future)
- **Prometheus Exporters**:
  - `django-prometheus` (Django)
  - `redis_exporter` (Redis)
  - `postgres_exporter` (PostgreSQL)
  - `node_exporter` (Host)
- **Grafana Dashboards**:
  - Request latency (p50, p95, p99)
  - Error rate
  - Queue depth
  - DB connections
  - Cache hit rate

### Alerting (Future)
- **Channels**: Email, Slack, PagerDuty
- **Rules**:
  - Service down > 1 min
  - Error rate > 5%
  - Queue depth > 500
  - Disk > 80%
  - SSL cert expiry < 30 days

---

## Backup Strategy

### PostgreSQL
- **Tool**: `pg_dump` in container
- **Schedule**: Daily 2:00 AM UTC
- **Retention**: 30 days
- **Storage**: S3-compatible (MinIO, Wasabi, R2, or AWS S3)
- **Script**: `scripts/backup-db.sh`
```bash
#!/bin/bash
docker exec postgres pg_dump -U $DB_USER $DB_NAME | gzip > /backups/spotter-$(date +%F).sql.gz
# Upload to S3
aws s3 cp /backups/spotter-$(date +%F).sql.gz s3://my-bucket/backups/
# Cleanup local > 7 days
find /backups -name "spotter-*.sql.gz" -mtime +7 -delete
```

### Redis
- **Strategy**: RDB snapshots (non-critical, cache only)
- **Schedule**: Every 6 hours (Redis default)
- **Recovery**: Accept data loss (re-fetchable)

### Application Code & Config
- **Source**: GitHub (source of truth)
- **Config**: `.env` file backed up separately (encrypted)
- **Docker Images**: Pushed to registry (GHCR, Docker Hub)

---

## Disaster Recovery

### RTO (Recovery Time Objective): < 1 hour
### RPO (Recovery Point Objective): < 24 hours

### Recovery Procedure
1. **Provision new VPS** (same specs)
2. **Install Docker + Docker Compose**
3. **Clone repository** & checkout release tag
4. **Restore `.env`** from secure backup
5. **Restore database**:
   ```bash
   # Download latest backup
   aws s3 cp s3://my-bucket/backups/latest.sql.gz .
   gunzip -c latest.sql.gz | docker exec -i postgres psql -U $DB_USER $DB_NAME
   ```
6. **Start services**: `docker compose -f docker-compose.prod.yml up -d`
7. **Verify health checks**
8. **Update DNS** if IP changed

### Test Schedule
- **Monthly**: Restore to staging environment
- **Quarterly**: Full DR drill (document time)

---

## Cost Considerations

### Monthly Estimate (DigitalOcean/Hetzner)
| Component | Cost |
|-----------|------|
| VPS (4GB/2vCPU/80GB) | $24-40 |
| Domain | ~$1/mo |
| SSL (Let's Encrypt) | Free |
| Object Storage (backups) | $1-5 |
| **Total** | **$26-46/month** |

### External API Costs
| API | Free Tier | Paid Estimate |
|-----|-----------|---------------|
| OpenRouteService | 2,000 req/day | $50-200/mo |
| OpenWeatherMap | 1,000 calls/day | $40/mo |
| Mapbox | 50k map loads/mo | $5/mo per 1k |

**Note**: At 1,000 users, likely within free tiers.

---

## Operational Considerations

### Deployment Process
```bash
# 1. Pull latest images
docker compose -f docker-compose.prod.yml pull

# 2. Run migrations
docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate

# 3. Collect static files
docker compose -f docker-compose.prod.yml run --rm django python manage.py collectstatic --noinput

# 4. Restart services (zero-downtime with Nginx)
docker compose -f docker-compose.prod.yml up -d --no-deps django celery
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

### Rollback
```bash
# Tag-based rollback
git checkout v1.2.3
docker compose -f docker-compose.prod.yml up -d --build
```

### Maintenance Windows
- **Weekly**: Sunday 3:00 AM UTC (apt updates, reboot if needed)
- **Monthly**: Dependency updates, security patches
- **Annual**: OS upgrade (LTS to LTS)

### Security Hardening
- Non-root containers (Dockerfile `USER appuser`)
- Read-only root filesystem where possible
- No SSH passwords (keys only)
- Fail2ban on SSH
- Regular `apt update && apt upgrade`
- Audit: `docker scan` images, `trivy` vulnerabilities

---

## Environment Variables (Production)

```bash
# .env.production
# Django
DJANGO_SETTINGS_MODULE=config.settings.production
SECRET_KEY=generated-50-char-secret
DEBUG=False
ALLOWED_HOSTS=api.example.com,www.example.com
FRONTEND_URL=https://app.example.com

# Database
DB_NAME=spotter
DB_USER=spotter
DB_PASSWORD=generated-secure-password
DATABASE_URL=postgres://spotter:${DB_PASSWORD}@postgres:5432/spotter

# Redis
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# External APIs
OPENROUTESERVICE_API_KEY=ors_xxx
OPENWEATHERMAP_API_KEY=owm_xxx
MAPBOX_TOKEN=pk.xxx

# Email (for alerts)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASSWORD=xxx
```

---

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build & push backend
        uses: docker/build-push-action@v5
        with:
          context: ./backend
          push: true
          tags: ghcr.io/${{ github.repository }}/backend:${{ github.ref_name }}
      - name: Build & push frontend
        uses: docker/build-push-action@v5
        with:
          context: ./frontend
          push: true
          tags: ghcr.io/${{ github.repository }}/frontend:${{ github.ref_name }}

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to VPS
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_HOST }}
          username: root
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /opt/spotter
            git pull origin main
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml run --rm django python manage.py migrate
            docker compose -f docker-compose.prod.yml run --rm django python manage.py collectstatic --noinput
            docker compose -f docker-compose.prod.yml up -d
```