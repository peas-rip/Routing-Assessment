# Service Specification: Risk Service

## Service Overview

**Name**: Risk Service
**Purpose**: Calculate weather risk at checkpoints, score routes, recommend optimal route
**Business Ownership**: Route Planning team
**Technical Ownership**: Backend team

## Service Boundaries

### Owns
- Risk classification (wind, rain, snow) per specification thresholds
- Load-based escalation rules
- Route scoring (4-priority algorithm)
- Route recommendation selection
- Risk assessments and route scores (`risk_assessments`, `route_scores` tables)

### Must Never Own
- Route generation
- Weather fetching
- Geocoding
- External API calls (pure computation)

## Data Ownership

### Entities Owned
- `RiskAssessment` - Per-checkpoint risk breakdown
- `RouteScore` - Aggregated route scoring

### Relationships Owned
- RiskAssessment → Checkpoint (1:1)
- RiskAssessment → WeatherObservation (1:1)
- RouteScore → Route (1:1)

## Dependencies

### Internal
- **Routing Service** - Reads routes, checkpoints (read-only)
- **Weather Service** - Reads weather observations (read-only)

### External
- None (pure business logic)

## Communication

### APIs Exposed
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/risk/calculate/` | Calculate risk for route checkpoints |
| GET | `/api/v1/risk/recommendation/{route_id}/` | Get scored routes + recommendation |

### Events Produced
- `risk.calculated` - Risk assessments saved
- `route.scored` - Route scores computed

### Events Consumed
- `weather.fetched` → Trigger `calculate_risk_for_checkpoint`

## Security Requirements

### Authentication
- v1: No auth
- Future: JWT required

### Authorization
- Rate limit: 30 req/min per IP

### Data Protection
- No external calls (no API keys needed)
- Input validation on all parameters
- Read-only access to other services' tables

## Observability Requirements

### Logging
- Log: route_id, checkpoint count, risk distribution, recommendation
- Structured JSON

### Metrics
- Calculation latency (target <50ms/checkpoint)
- Risk distribution (histogram)
- Recommendation consistency

### Monitoring
- Health check: DB connectivity
- Alert: Calculation errors > 0
- Alert: Inconsistent recommendation logic

---

## Development Guide

### Local Development
```bash
# Start dependencies
docker compose up -d postgres redis

# Run migrations
python manage.py migrate

# Run service tests (CRITICAL)
pytest apps/risk/tests/ -v

# Run server
python manage.py runserver 0.0.0.0:8000
```

### Key Files
```
apps/risk/
├── models.py          # RiskAssessment, RouteScore
├── rules.py           # Risk thresholds, load rules, scoring constants
├── services.py        # calculate_risk, score_route, recommend
├── tasks.py           # calculate_risk_task, score_route_task
├── views.py           # CalculateView, RecommendationView
├── serializers.py     # RiskSerializer, ScoreSerializer
├── urls.py            # URL routing
└── tests/
    ├── test_rules.py          # MOST CRITICAL - all thresholds
    ├── test_services.py       # Load rules, scoring priority
    └── test_views.py
```

### Implementation Patterns

#### Risk Thresholds (rules.py)
```python
# apps/risk/rules.py
from enum import IntEnum
from dataclasses import dataclass
from decimal import Decimal

class RiskLevel(IntEnum):
    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5

# Wind thresholds (mph)
WIND_THRESHOLDS = [
    (Decimal('25'), RiskLevel.LOW),
    (Decimal('35'), RiskLevel.MODERATE),
    (Decimal('45'), RiskLevel.HIGH),
    (Decimal('55'), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),  # >= 55
]

# Rain thresholds (in/hr)
RAIN_THRESHOLDS = [
    (Decimal('0.10'), RiskLevel.LOW),
    (Decimal('0.25'), RiskLevel.MODERATE),
    (Decimal('0.50'), RiskLevel.HIGH),
    (Decimal('1.00'), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),  # > 1.00
]

# Snow thresholds (in/hr)
SNOW_THRESHOLDS = [
    (Decimal('0.5'), RiskLevel.LOW),
    (Decimal('1.0'), RiskLevel.MODERATE),
    (Decimal('2.0'), RiskLevel.HIGH),
    (Decimal('3.0'), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),  # > 3.0
]

RISK_SCORE_MAP = {
    RiskLevel.LOW: 1.0,
    RiskLevel.MODERATE: 2.0,
    RiskLevel.HIGH: 3.0,
    RiskLevel.SEVERE: 4.0,
    RiskLevel.NO_TRAVEL: 5.0,
}

def classify_wind(speed_mph: Decimal) -> RiskLevel:
    for threshold, level in WIND_THRESHOLDS:
        if threshold is None or speed_mph < threshold:
            return level
    return RiskLevel.NO_TRAVEL

def classify_rain(rate_in_hr: Decimal) -> RiskLevel:
    for threshold, level in RAIN_THRESHOLDS:
        if threshold is None or rate_in_hr < threshold:
            return level
    return RiskLevel.NO_TRAVEL

def classify_snow(rate_in_hr: Decimal) -> RiskLevel:
    for threshold, level in SNOW_THRESHOLDS:
        if threshold is None or rate_in_hr < threshold:
            return level
    return RiskLevel.NO_TRAVEL
```

#### Load Escalation Rules
```python
def apply_load_rules(wind_risk: RiskLevel, wind_speed: Decimal, load_lbs: int) -> tuple[RiskLevel, str]:
    """Apply load-based escalation. Returns (escalated_risk, rule_name)."""
    
    # Rule 1: Wind ≥55 mph → No Travel (any load)
    if wind_speed >= Decimal('55'):
        return RiskLevel.NO_TRAVEL, "wind_ge_55_any_load"
    
    # Rule 2: Wind 45-54 mph + Load >30,000 → No Travel
    if wind_risk == RiskLevel.SEVERE and load_lbs > 30000:
        return RiskLevel.NO_TRAVEL, "wind_45_54_over_30k"
    
    # Rule 3: Wind 35-44 mph + Load >40,000 → Severe
    if wind_risk == RiskLevel.HIGH and load_lbs > 40000:
        return RiskLevel.SEVERE, "wind_35_44_over_40k"
    
    return wind_risk, ""
```

#### Combined Risk Calculation
```python
# apps/risk/services.py
def calculate_checkpoint_risk(weather: WeatherObservation, load_lbs: int, segment_miles: Decimal) -> RiskAssessment:
    """Calculate complete risk assessment for a checkpoint."""
    
    # Extract precipitation rates
    rain_rate, snow_rate = extract_precip_rates(weather)
    
    # Individual risks
    wind_risk = classify_wind(weather.wind_speed_mph or Decimal('0'))
    rain_risk = classify_rain(rain_rate)
    snow_risk = classify_snow(snow_rate)
    
    # Base combined = max of three
    combined = max(wind_risk, rain_risk, snow_risk)
    load_rule = ""
    
    # Apply load escalation (wind only)
    if wind_risk in (RiskLevel.HIGH, RiskLevel.SEVERE, RiskLevel.NO_TRAVEL):
        combined, load_rule = apply_load_rules(wind_risk, weather.wind_speed_mph, load_lbs)
    
    return RiskAssessment(
        checkpoint_id=...,  # Set by caller
        weather_observation=weather,
        load_weight_lbs=load_lbs,
        wind_risk=wind_risk.name.lower(),
        rain_risk=rain_risk.name.lower(),
        snow_risk=snow_risk.name.lower(),
        combined_risk=combined.name.lower(),
        load_rule_applied=load_rule,
        segment_miles=segment_miles
    )
```

#### Route Scoring (4-Priority)
```python
def calculate_route_score(route: Route) -> RouteScore:
    """Score route per 4-priority rules."""
    risks = RiskAssessment.objects.filter(checkpoint__route=route)
    
    # Aggregate by risk level
    breakdown = defaultdict(Decimal)
    for ra in risks:
        breakdown[ra.combined_risk] += ra.segment_miles
    
    # Priority 1: Severe + No Travel miles
    severe_miles = breakdown.get('severe', Decimal('0')) + breakdown.get('no_travel', Decimal('0'))
    
    # Priority 2: High miles
    high_miles = breakdown.get('high', Decimal('0'))
    
    # Priority 3: Average risk score (weighted)
    total_miles = sum(breakdown.values())
    if total_miles == 0:
        avg_risk = Decimal('1.0')
    else:
        weighted = sum(RISK_SCORE_MAP[RiskLevel[r.upper()]] * miles for r, miles in breakdown.items())
        avg_risk = (weighted / total_miles).quantize(Decimal('0.001'))
    
    # Priority 4: Duration
    duration = route.duration_minutes
    
    # Composite for sorting (lexicographic encoding)
    composite = (
        severe_miles * Decimal('10000') +
        high_miles * Decimal('100') +
        avg_risk * Decimal('10') +
        Decimal(str(duration)) / Decimal('1000')
    )
    
    return RouteScore.objects.create(
        route=route,
        severe_miles=severe_miles,
        high_miles=high_miles,
        average_risk_score=avg_risk,
        duration_minutes=duration,
        composite_score=composite.quantize(Decimal('0.001')),
        risk_breakdown={k: float(v) for k, v in breakdown.items()}
    )
```

#### Recommendation
```python
def get_recommendation(request_id: str) -> RecommendationResponse:
    routes = Route.objects.filter(request_id=request_id).prefetch_related('score')
    
    scored = []
    for route in routes:
        if hasattr(route, 'score'):
            scored.append((route.score.composite_score, route, route.score))
    
    scored.sort(key=lambda x: x[0])  # Ascending = better
    
    return RecommendationResponse(
        request_id=request_id,
        recommended_route_id=scored[0][1].id if scored else None,
        routes=[
            RouteScoreResponse(
                route_id=r.id, name=r.name,
                distance_miles=r.distance_miles, duration_minutes=r.duration_minutes,
                score=s, is_recommended=(i == 0)
            )
            for i, (_, r, s) in enumerate(scored)
        ]
    )
```

---

## Testing Guide

### Unit Tests (CRITICAL - 100% Coverage Required)

#### Threshold Boundaries
```python
# apps/risk/tests/test_rules.py
class TestWindThresholds:
    def test_wind_low(self):
        assert classify_wind(Decimal('24.9')) == RiskLevel.LOW
        assert classify_wind(Decimal('25.0')) == RiskLevel.MODERATE
        assert classify_wind(Decimal('34.9')) == RiskLevel.MODERATE
    
    def test_wind_high(self):
        assert classify_wind(Decimal('35.0')) == RiskLevel.HIGH
        assert classify_wind(Decimal('44.9')) == RiskLevel.HIGH
    
    def test_wind_severe(self):
        assert classify_wind(Decimal('45.0')) == RiskLevel.SEVERE
        assert classify_wind(Decimal('54.9')) == RiskLevel.SEVERE
    
    def test_wind_no_travel(self):
        assert classify_wind(Decimal('55.0')) == RiskLevel.NO_TRAVEL
        assert classify_wind(Decimal('100')) == RiskLevel.NO_TRAVEL

class TestLoadRules:
    def test_wind_ge_55_any_load(self):
        assert apply_load_rules(RiskLevel.NO_TRAVEL, Decimal('60'), 10000) == (RiskLevel.NO_TRAVEL, "wind_ge_55_any_load")
        assert apply_load_rules(RiskLevel.NO_TRAVEL, Decimal('55'), 80000) == (RiskLevel.NO_TRAVEL, "wind_ge_55_any_load")
    
    def test_wind_45_54_over_30k(self):
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('50'), 25000) == (RiskLevel.SEVERE, "")
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('50'), 30001) == (RiskLevel.NO_TRAVEL, "wind_45_54_over_30k")
    
    def test_wind_35_44_over_40k(self):
        assert apply_load_rules(RiskLevel.HIGH, Decimal('40'), 35000) == (RiskLevel.HIGH, "")
        assert apply_load_rules(RiskLevel.HIGH, Decimal('40'), 40001) == (RiskLevel.SEVERE, "wind_35_44_over_40k")
    
    def test_rain_snow_not_affected_by_load(self):
        # Rain No Travel should stay No Travel regardless of load
        rain_obs = create_mock_weather(rain_rate=1.5)
        risk = calculate_checkpoint_risk(rain_obs, 80000, Decimal('25'))
        assert risk.combined_risk == RiskLevel.NO_TRAVEL
        
        # Snow No Travel should stay No Travel regardless of load
        snow_obs = create_mock_weather(snow_rate=4.0)
        risk = calculate_checkpoint_risk(snow_obs, 10000, Decimal('25'))
        assert risk.combined_risk == RiskLevel.NO_TRAVEL
```

#### Route Scoring Priority
```python
class TestRouteScoring:
    def test_priority_1_severe_miles(self):
        # Route A: 0 severe, 10 high | Route B: 5 severe, 0 high
        # A should win
        route_a = create_route_with_risks(severe=0, high=10, avg=1.5, duration=200)
        route_b = create_route_with_risks(severe=5, high=0, avg=1.5, duration=200)
        assert route_a.score.composite_score < route_b.score.composite_score
    
    def test_priority_2_high_miles(self):
        # Both 0 severe | Route A: 10 high | Route B: 5 high
        route_a = create_route_with_risks(severe=0, high=10, avg=2.0, duration=200)
        route_b = create_route_with_risks(severe=0, high=5, avg=2.0, duration=200)
        assert route_b.score.composite_score < route_a.score.composite_score
    
    def test_priority_3_avg_risk(self):
        # Both 0 severe, 0 high | Route A: avg 1.5 | Route B: avg 2.0
        route_a = create_route_with_risks(severe=0, high=0, avg=1.5, duration=200)
        route_b = create_route_with_risks(severe=0, high=0, avg=2.0, duration=200)
        assert route_a.score.composite_score < route_b.score.composite_score
    
    def test_priority_4_duration(self):
        # All equal | Route A: 195 min | Route B: 210 min
        route_a = create_route_with_risks(severe=0, high=0, avg=1.5, duration=195)
        route_b = create_route_with_risks(severe=0, high=0, avg=1.5, duration=210)
        assert route_a.score.composite_score < route_b.score.composite_score
```

### Property-Based Tests
```python
# apps/risk/tests/test_property_based.py
from hypothesis import given, strategies as st

@given(st.decimals(min_value=0, max_value=100, places=1))
def test_wind_classification_monotonic(speed):
    """Higher wind speed never results in lower risk."""
    risk1 = classify_wind(speed)
    risk2 = classify_wind(speed + Decimal('0.1'))
    assert risk2 >= risk1

@given(
    st.decimals(min_value=0, max_value=100, places=1),
    st.integers(min_value=10000, max_value=80000)
)
def test_load_rules_monotonic(wind_speed, load):
    """Higher load never improves risk for same wind."""
    risk1 = apply_load_rules(classify_wind(wind_speed), wind_speed, load)
    risk2 = apply_load_rules(classify_wind(wind_speed), wind_speed, load + 1000)
    assert risk2[0] >= risk1[0]
```

### Integration Tests
- Full pipeline: Weather → Risk → Score → Recommendation
- Concurrent checkpoint processing
- Stale weather data handling

### Coverage Targets
- **rules.py**: 100% (non-negotiable)
- **services.py**: 95%
- **tasks.py**: 90%
- **views.py**: 85%

---

## Deployment Guide

### Configuration
```bash
# No external API keys needed
CELERY_BROKER_URL=redis://redis:6379/1
```

### Health Check
```python
def check_risk():
    try:
        # Test calculation with known values
        from apps.risk.rules import classify_wind
        assert classify_wind(Decimal('30')) == RiskLevel.MODERATE
        return "ok"
    except Exception as e:
        return f"degraded: {e}"
```

### Scaling
- Stateless - scale horizontally
- Celery workers: `-Q risk` for dedicated workers
- Read-only DB access - can use read replicas

### Critical Deployment Notes
- **Never deploy without passing all risk rule tests**
- Run `pytest apps/risk/tests/test_rules.py -v` in CI
- Any threshold change requires full regression test