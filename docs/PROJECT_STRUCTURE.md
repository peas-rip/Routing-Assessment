# Project Structure

## Repository Layout

```
routing-assessment/
├── .github/
│   └── workflows/
│       ├── ci.yml              # CI pipeline
│       └── deploy.yml          # CD pipeline
├── docs/
│   ├── PRD.md
│   ├── SYSTEM_ARCHITECTURE.md
│   ├── DATABASE_SCHEMA.md
│   ├── API_CONTRACTS.md
│   ├── PROJECT_STRUCTURE.md
│   ├── FEATURE_SERVICE_MAPPING.md
│   ├── ROADMAP.md
│   ├── IMPLEMENTATION_ORDER.md
│   ├── DEPLOYMENT_ARCHITECTURE.md
│   ├── AI_IMPLEMENTATION_GUIDE.md
│   ├── FEATURES/
│   │   ├── FEATURE_01_ROUTE_INPUT.md
│   │   ├── FEATURE_02_ROUTE_GENERATION.md
│   │   ├── FEATURE_03_CHECKPOINT_SAMPLING.md
│   │   ├── FEATURE_04_WEATHER_FETCHING.md
│   │   ├── FEATURE_05_RISK_CALCULATION.md
│   │   ├── FEATURE_06_ROUTE_SCORING.md
│   │   ├── FEATURE_07_MAP_VISUALIZATION.md
│   │   └── FEATURE_08_WEATHER_HEATMAP.md
│   └── SERVICES/
│       ├── routing/
│       │   ├── SERVICE_SPEC.md
│       │   ├── DEVELOPMENT.md
│       │   ├── TESTING.md
│       │   └── DEPLOYMENT.md
│       ├── weather/
│       │   ├── SERVICE_SPEC.md
│       │   ├── DEVELOPMENT.md
│       │   ├── TESTING.md
│       │   └── DEPLOYMENT.md
│       ├── risk/
│       │   ├── SERVICE_SPEC.md
│       │   ├── DEVELOPMENT.md
│       │   ├── TESTING.md
│       │   └── DEPLOYMENT.md
│       └── geocoding/
│           ├── SERVICE_SPEC.md
│           ├── DEVELOPMENT.md
│           ├── TESTING.md
│           └── DEPLOYMENT.md
├── backend/
│   ├── config/                 # Django project settings
│   │   ├── __init__.py
│   │   ├── settings/
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # Shared settings
│   │   │   ├── development.py  # Dev overrides
│   │   │   ├── production.py   # Prod overrides
│   │   │   └── testing.py      # Test settings
│   │   ├── urls.py             # Root URL config
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── apps/
│   │   ├── __init__.py
│   │   ├── routing/            # Route generation service
│   │   │   ├── __init__.py
│   │   │   ├── models.py
│   │   │   ├── views.py
│   │   │   ├── serializers.py
│   │   │   ├── urls.py
│   │   │   ├── services.py     # Business logic
│   │   │   ├── tasks.py        # Celery tasks
│   │   │   ├── clients/        # External API clients
│   │   │   │   ├── __init__.py
│   │   │   │   └── openrouteservice.py
│   │   │   ├── managers.py
│   │   │   ├── migrations/
│   │   │   └── tests/
│   │   │       ├── __init__.py
│   │   │       ├── test_models.py
│   │   │       ├── test_views.py
│   │   │       ├── test_services.py
│   │   │       └── test_clients.py
│   │   ├── weather/            # Weather service
│   │   │   ├── __init__.py
│   │   │   ├── models.py
│   │   │   ├── views.py
│   │   │   ├── serializers.py
│   │   │   ├── urls.py
│   │   │   ├── services.py
│   │   │   ├── tasks.py
│   │   │   ├── clients/
│   │   │   │   ├── __init__.py
│   │   │   │   └── nws.py
│   │   │   ├── managers.py
│   │   │   ├── migrations/
│   │   │   └── tests/
│   │   ├── risk/               # Risk calculation service
│   │   │   ├── __init__.py
│   │   │   ├── models.py
│   │   │   ├── views.py
│   │   │   ├── serializers.py
│   │   │   ├── urls.py
│   │   │   ├── services.py     # Pure risk logic
│   │   │   ├── rules.py        # Risk thresholds & rules
│   │   │   ├── migrations/
│   │   │   └── tests/
│   │   │       ├── __init__.py
│   │   │       ├── test_rules.py
│   │   │       ├── test_services.py
│   │   │       └── test_views.py
│   │   └── geocoding/          # Geocoding service
│   │       ├── __init__.py
│   │       ├── models.py
│   │       ├── views.py
│   │       ├── serializers.py
│   │       ├── urls.py
│   │       ├── services.py
│   │       ├── clients/
│   │       │   ├── __init__.py
│   │       │   └── openrouteservice.py
│   │       ├── migrations/
│   │       └── tests/
│   ├── common/                 # Shared utilities
│   │   ├── __init__.py
│   │   ├── exceptions.py
│   │   ├── pagination.py
│   │   ├── permissions.py
│   │   ├── validators.py
│   │   ├── mixins.py
│   │   └── utils.py
│   ├── manage.py
│   ├── requirements/
│   │   ├── base.txt
│   │   ├── development.txt
│   │   ├── production.txt
│   │   └── testing.txt
│   ├── Dockerfile
│   ├── docker-entrypoint.sh
│   └── .env.example
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── main.tsx            # Entry point
│   │   ├── App.tsx             # Root component
│   │   ├── vite-env.d.ts
│   │   ├── api/                # API client layer
│   │   │   ├── client.ts       # Axios/fetch wrapper
│   │   │   ├── routes.ts       # Route API calls
│   │   │   ├── risk.ts         # Risk API calls
│   │   │   ├── weather.ts      # Weather API calls
│   │   │   └── geocoding.ts    # Geocoding API calls
│   │   ├── components/         # Reusable UI components
│   │   │   ├── ui/             # Base components (Button, Input, etc.)
│   │   │   ├── layout/         # Layout components (Header, Sidebar)
│   │   │   ├── map/            # Map-specific components
│   │   │   │   ├── MapView.tsx
│   │   │   │   ├── RouteLayer.tsx
│   │   │   │   ├── CheckpointMarkers.tsx
│   │   │   │   ├── RiskLegend.tsx
│   │   │   │   └── HeatmapLayer.tsx
│   │   │   ├── forms/          # Form components
│   │   │   │   ├── RouteInputForm.tsx
│   │   │   │   ├── AddressAutocomplete.tsx
│   │   │   │   └── LoadWeightInput.tsx
│   │   │   └── display/        # Display components
│   │   │       ├── RouteSummary.tsx
│   │   │       ├── RiskBadge.tsx
│   │   │       ├── TimeSlider.tsx
│   │   │       └── LoadingSpinner.tsx
│   │   ├── hooks/              # Custom React hooks
│   │   │   ├── useRoutes.ts
│   │   │   ├── useRisk.ts
│   │   │   ├── useWeather.ts
│   │   │   ├── useGeocoding.ts
│   │   │   └── useDebounce.ts
│   │   ├── stores/             # Zustand stores
│   │   │   ├── routeStore.ts
│   │   │   ├── uiStore.ts
│   │   │   └── settingsStore.ts
│   │   ├── pages/              # Page components
│   │   │   ├── HomePage.tsx
│   │   │   ├── RouteResultsPage.tsx
│   │   │   └── ErrorPage.tsx
│   │   ├── utils/              # Utility functions
│   │   │   ├── format.ts       # Formatting helpers
│   │   │   ├── geometry.ts     # GeoJSON helpers
│   │   │   ├── risk.ts         # Risk color/label helpers
│   │   │   └── date.ts         # Date/time helpers
│   │   ├── types/              # TypeScript types
│   │   │   ├── api.ts          # API response types
│   │   │   ├── route.ts
│   │   │   ├── risk.ts
│   │   │   └── weather.ts
│   │   ├── styles/
│   │   │   ├── globals.css
│   │   │   └── tailwind.css
│   │   └── constants/
│   │       ├── risk.ts         # Risk thresholds, colors
│   │       ├── map.ts          # Map config
│   │       └── api.ts          # API endpoints
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── eslint.config.js
│   ├── Dockerfile
│   └── .env.example
├── infrastructure/
│   ├── docker-compose.yml          # Local development
│   ├── docker-compose.prod.yml     # Production
│   ├── nginx/
│   │   ├── nginx.conf
│   │   ├── conf.d/
│   │   │   ├── upstream.conf
│   │   │   ├── ssl.conf
│   │   │   └── rate-limit.conf
│   │   └── Dockerfile
│   ├── postgres/
│   │   ├── init/
│   │   │   └── 01-extensions.sql   # PostGIS setup
│   │   └── Dockerfile
│   └── redis/
│       └── redis.conf
├── scripts/
│   ├── deploy.sh
│   ├── backup-db.sh
│   ├── restore-db.sh
│   └── seed-data.py
├── .gitignore
├── .env.example
├── README.md
├── LICENSE
└── Makefile
```

---

## Directory Responsibilities

### `/docs`
**Owner**: Architecture team
**Purpose**: All architecture documentation, feature specs, service specs
**Contents**: PRD, system architecture, database schema, API contracts, roadmaps, feature specs, service specs

### `/backend`
**Owner**: Backend team
**Purpose**: Django REST API application
**Structure**:
- `config/` - Django project configuration (settings, URLs, WSGI/ASGI)
- `apps/` - Django applications (one per service)
  - Each app: models, views, serializers, services, tasks, clients, tests
- `common/` - Shared code across apps (exceptions, pagination, permissions, validators)
- `requirements/` - Pip requirements split by environment
- `Dockerfile` - Backend container definition

### `/frontend`
**Owner**: Frontend team
**Purpose**: React single-page application
**Structure**:
- `src/api/` - API client layer (TanStack Query hooks + raw clients)
- `src/components/` - Reusable UI components (organized by domain)
- `src/hooks/` - Custom React hooks for data fetching & logic
- `src/stores/` - Zustand stores for client state
- `src/pages/` - Top-level page components
- `src/utils/` - Pure utility functions
- `src/types/` - TypeScript type definitions
- `src/styles/` - Global styles, Tailwind entry
- `src/constants/` - Application constants
- `Dockerfile` - Frontend container definition

### `/infrastructure`
**Owner**: DevOps/Platform team
**Purpose**: Deployment & infrastructure as code
**Structure**:
- `docker-compose.yml` - Local development stack
- `docker-compose.prod.yml` - Production stack
- `nginx/` - Reverse proxy configuration
- `postgres/` - Database initialization (PostGIS)
- `redis/` - Redis configuration

### `/scripts`
**Owner**: DevOps/Platform team
**Purpose**: Operational scripts
**Contents**: Deployment, backup, restore, seeding scripts

---

## Service Structure (per Django app)

```
apps/{service_name}/
├── __init__.py
├── models.py           # Database models
├── views.py            # DRF ViewSets/Views
├── serializers.py      # DRF Serializers
├── urls.py             # URL routing for this app
├── services.py         # Business logic (pure Python, testable)
├── tasks.py            # Celery tasks (async operations)
├── clients/            # External API clients
│   ├── __init__.py
│   └── {provider}.py
├── managers.py         # Custom model managers/querysets
├── migrations/         # Django migrations
│   └── __init__.py
└── tests/              # Service-specific tests
    ├── __init__.py
    ├── test_models.py
    ├── test_views.py
    ├── test_services.py
    ├── test_clients.py
    └── test_tasks.py
```

### Key Principles

1. **Services layer** (`services.py`) contains all business logic - pure functions, easily testable
2. **Views** are thin - delegate to services, handle HTTP concerns only
3. **Clients** encapsulate external API communication - retries, timeouts, error handling
4. **Tasks** handle async work - Celery tasks call services
5. **Tests** mirror structure - test services directly, test views via API client

---

## Shared Code (`/backend/common`)

| Module | Purpose |
|--------|---------|
| `exceptions.py` | Custom exception classes (APIException subclasses) |
| `pagination.py` | Custom pagination classes |
| `permissions.py` | Custom permission classes (future: RBAC) |
| `validators.py` | Reusable validators (coordinates, weight, etc.) |
| `mixins.py` | View mixins (logging, caching, etc.) |
| `utils.py` | General utilities (date parsing, geo helpers) |

---

## Frontend Component Organization

### By Domain (not type)
```
components/
├── map/           # All map-related components
├── forms/         # All form components
├── display/       # All data display components
└── ui/            # Generic reusable primitives
```

### Component Rules
- **Presentational components**: Pure UI, no data fetching, receive props
- **Container components**: Use hooks/stores, fetch data, pass to presentational
- **Custom hooks**: Encapsulate data fetching logic (TanStack Query)
- **Stores**: Only for truly global client state (UI state, settings)

---

## Configuration Management

### Environment Variables

**Backend** (`.env`):
```bash
# Django
DJANGO_SETTINGS_MODULE=config.settings.production
SECRET_KEY=...
DEBUG=False
ALLOWED_HOSTS=api.example.com,localhost

# Database
DATABASE_URL=postgres://user:pass@host:5432/db

# Redis
REDIS_URL=redis://host:6379/0

# External APIs
OPENROUTESERVICE_API_KEY=...
NWS_BASE_URL=...

# Celery
CELERY_BROKER_URL=redis://host:6379/0
CELERY_RESULT_BACKEND=redis://host:6379/1

# Frontend URL (CORS)
FRONTEND_URL=https://app.example.com
```

**Frontend** (`.env`):
```bash
VITE_API_BASE_URL=https://api.example.com/api/v1
VITE_MAPBOX_TOKEN=...
VITE_APP_TITLE=Weather-Aware Truck Routing
```

---

## Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Django Apps | lowercase, singular | `routing`, `weather`, `risk` |
| Models | PascalCase, singular | `RouteRequest`, `Checkpoint` |
| Model Fields | snake_case | `departure_time`, `load_weight_lbs` |
| Database Tables | snake_case, plural | `route_requests`, `checkpoints` |
| API Endpoints | kebab-case, plural | `/routes/generate/`, `/risk/calculate/` |
| Serializer Fields | snake_case | `departure_time`, `load_weight_lbs` |
| React Components | PascalCase | `RouteInputForm`, `MapView` |
| React Hooks | camelCase, `use` prefix | `useRoutes`, `useDebounce` |
| TypeScript Types | PascalCase | `RouteResponse`, `RiskLevel` |
| Constants | UPPER_SNAKE_CASE | `RISK_THRESHOLDS`, `MAP_CONFIG` |
| CSS Classes | Tailwind utilities | No custom classes preferred |
| Git Branches | `feature/`, `fix/`, `chore/` | `feature/route-generation` |

---

## Import Organization

### Python (Ruff/Black enforced)
```python
# Standard library
import uuid
from datetime import datetime
from decimal import Decimal

# Third party
from django.db import models
from rest_framework import serializers

# Local (same app)
from .models import Route
from .services import calculate_route_score

# Local (other apps)
from apps.weather.models import WeatherObservation
```

### TypeScript (ESLint enforced)
```typescript
// External
import React from 'react';
import { useQuery } from '@tanstack/react-query';

// Internal - absolute imports via path aliases
import { Route } from '@/types/route';
import { useRoutes } from '@/hooks/useRoutes';
import { Button } from '@/components/ui/Button';
```

---

## Monorepo vs Polyrepo

**Decision**: Monorepo (single repository)

**Rationale**:
- Small team, single deployable unit
- Shared types between frontend/backend (via OpenAPI spec)
- Atomic commits across frontend/backend
- Simpler CI/CD
- Easy code sharing (constants, types)

**Future split criteria**: Team >5, independent deploy cadence, separate ownership