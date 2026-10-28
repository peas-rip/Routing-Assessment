# Development Guide: Risk Service

## Quick Start

```bash
# 1. Start infrastructure
docker compose up -d postgres redis

# 2. Run migrations
python manage.py migrate

# 3. Run tests (CRITICAL - must pass 100%)
pytest apps/risk/tests/ -v

# 4. Start Celery worker (terminal 1)
celery -A config worker -l info -Q risk

# 5. Start dev server (terminal 2)
python manage.py runserver 0.0.0.0:8000

# 6. Test API
curl -X POST http://localhost:8000/api/v1/risk/calculate/ \
  -H "Content-Type: application/json" \
  -d '{"route_id":"uuid","load_weight_lbs":45000,"checkpoint_interval_miles":25}'
curl http://localhost:8000/api/v1/risk/recommendation/uuid/
```

## Project Structure

```
apps/risk/
├── __init__.py
├── admin.py
├── apps.py
├── models.py              # RiskAssessment, RouteScore
├── rules.py               # THRESHOLDS, LOAD_RULES, SCORING - CORE LOGIC
├── services.py            # calculate_risk, score_route, recommend
├── tasks.py               # calculate_risk_task, score_route_task
├── views.py               # CalculateView, RecommendationView
├── serializers.py         # RiskSerializer, ScoreSerializer
├── urls.py
├── validators.py          # Load weight, risk level validation
├── tests/
│   ├── __init__.py
│   ├── test_rules.py      # MOST CRITICAL - 100% coverage required
│   ├── test_services.py   # Load rules, scoring priority
│   ├── test_views.py
│   ├── test_property_based.py  # Hypothesis tests
│   └── fixtures.py
└── migrations/
    └── 0001_initial.py
```

## Key Implementation Details

### Rules (rules.py) - THE HEART OF THE SERVICE
```python
# rules.py
from enum import IntEnum
from decimal import Decimal
from dataclasses import dataclass

class RiskLevel(IntEnum):
    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5

# Wind thresholds (mph) - EXACT FROM SPEC
WIND_THRESHOLDS = [
    (Decimal('25'), RiskLevel.LOW),
    (Decimal('35'), RiskLevel.MODERATE),
    (Decimal('45'), RiskLevel.HIGH),
    (Decimal('55'), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),  # >= 55
]

# Rain thresholds (in/hr) - EXACT FROM SPEC
RAIN_THRESHOLDS = [
    (Decimal('0.10'), RiskLevel.LOW),
    (Decimal('0.25'), RiskLevel.MODERATE),
    (Decimal('0.50'), RiskLevel.HIGH),
    (Decimal('1.00'), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),  # > 1.00
]

# Snow thresholds (in/hr) - EXACT FROM SPEC
SNOW_THRESHOLDS = [
    (Decimal('0.5'), RiskLevel.LOW),
    (Decimal('1.0'), RiskLevel.MODERATE),
    (Decimal('2.0'), RiskLevel.HIGH),
    (Decimal('3.0'), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),  # > 3.0
]

RISK_SCORE_MAP = {
    RiskLevel.LOW: Decimal('1.0'),
    RiskLevel.MODERATE: Decimal('2.0'),
    RiskLevel.HIGH: Decimal('3.0'),
    RiskLevel.SEVERE: Decimal('4.0'),
    RiskLevel.NO_TRAVEL: Decimal('5.0'),
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

def apply_load_rules(wind_risk: RiskLevel, wind_speed: Decimal, load_lbs: int) -> tuple[RiskLevel, str]:
    """Load escalation rules - EXACT FROM SPEC."""
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

def calculate_combined_risk(weather, load_lbs: int) -> RiskAssessment:
    """Main risk calculation entry point."""
    # Extract precipitation rates
    rain_rate, snow_rate = extract_precip_rates(weather)
    
    # Individual risks
    wind_risk = classify_wind(weather.wind_speed_mph or Decimal('0'))
    rain_risk = classify_rain(rain_rate)
    snow_risk = classify_snow(snow_rate)
    
    # Base combined = max of three
    combined = max(wind_risk, rain_risk, snow_risk)
    load_rule = ""
    
    # Apply load escalation (wind only per spec)
    if wind_risk in (RiskLevel.HIGH, RiskLevel.SEVERE, RiskLevel.NO_TRAVEL):
        combined, load_rule = apply_load_rules(wind_risk, weather.wind_speed_mph, load_lbs)
    
    return RiskAssessment(
        wind_risk=wind_risk.name.lower(),
        rain_risk=rain_risk.name.lower(),
        snow_risk=snow_risk.name.lower(),
        combined_risk=combined.name.lower(),
        load_rule_applied=load_rule,
        load_weight_lbs=load_lbs,
        segment_miles=...,  # Set by caller
    )
```

### Route Scoring (4-Priority)
```python
# services.py
def calculate_route_score(route: Route) -> RouteScore:
    risks = RiskAssessment.objects.filter(checkpoint__route=route)
    
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

### Celery Tasks
```python
# tasks.py
@celery_app.task(bind=True, max_retries=3)
def calculate_risk_for_checkpoint(self, checkpoint_id: str):
    cp = Checkpoint.objects.get(id=checkpoint_id)
    weather = cp.weather_observations.first()
    if not weather:
        return  # Skip if no weather yet
    
    risk = calculate_combined_risk(weather, cp.route.request.load_weight_lbs)
    risk.checkpoint = cp
    risk.weather_observation = weather
    risk.save()

@celery_app.task
def score_route(route_id: str):
    route = Route.objects.get(id=route_id)
    calculate_route_score(route)

@celery_app.task
def recommend_route(request_id: str):
    routes = Route.objects.filter(request_id=request_id)
    for route in routes:
        score_route(route.id)
    # Recommendation view reads from RouteScore
```

## Debugging

```bash
# Test rules directly (CRITICAL)
python manage.py shell -c "
from apps.risk.rules import *
from decimal import Decimal

# Wind thresholds
for w in [24.9, 25, 34.9, 35, 44.9, 45, 54.9, 55, 60]:
    print(f'Wind {w}: {classify_wind(Decimal(str(w))).name}')

# Load rules
print(apply_load_rules(RiskLevel.SEVERE, Decimal('50'), 25000))
print(apply_load_rules(RiskLevel.SEVERE, Decimal('50'), 30001))
print(apply_load_rules(RiskLevel.HIGH, Decimal('40'), 35000))
print(apply_load_rules(RiskLevel.HIGH, Decimal('40'), 40001))
"

# Test full calculation
python manage.py shell -c "
from apps.risk.services import calculate_combined_risk
from apps.weather.models import WeatherObservation
from decimal import Decimal

# Mock weather
weather = WeatherObservation(
    wind_speed_mph=Decimal('40'),
    precipitation_rate_in_hr=Decimal('0.15'),
    snowfall_rate_in_hr=Decimal('0'),
    precipitation_type='rain',
    raw_response={}
)
risk = calculate_combined_risk(weather, 45000)
print(f'Wind: {risk.wind_risk}, Rain: {risk.rain_risk}, Combined: {risk.combined_risk}, Rule: {risk.load_rule_applied}')
"

# Run tests to verify
pytest apps/risk/tests/test_rules.py -v
```