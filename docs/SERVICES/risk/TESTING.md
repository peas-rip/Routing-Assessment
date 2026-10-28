# Testing Guide: Risk Service

## Test Strategy

| Test Type | Coverage Target | Priority |
|-----------|-----------------|----------|
| Unit Tests (Rules) | **100%** | **CRITICAL - Non-negotiable** |
| Unit Tests (Services) | 95% | Critical |
| Property-Based Tests | 100% of properties | Critical |
| Integration Tests | 90% | High |
| Contract Tests | 100% | Critical |

## Test Organization

```
apps/risk/tests/
├── __init__.py
├── fixtures.py              # Mock weather, checkpoints, routes
├── test_rules.py            # **MOST CRITICAL - All thresholds & load rules**
├── test_services.py         # Risk calculation, scoring, recommendation
├── test_property_based.py   # Hypothesis tests for monotonicity
├── test_views.py            # API endpoints
└── test_integration.py      # Full pipeline tests
```

## Unit Tests - Rules (`test_rules.py`) - **100% COVERAGE REQUIRED**

### Wind Threshold Tests
```python
class TestWindThresholds:
    """Test EXACT boundaries from specification."""
    
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
```

### Rain Threshold Tests
```python
class TestRainThresholds:
    def test_rain_low(self):
        assert classify_rain(Decimal('0.09')) == RiskLevel.LOW
        assert classify_rain(Decimal('0.10')) == RiskLevel.MODERATE
        assert classify_rain(Decimal('0.24')) == RiskLevel.MODERATE
    
    def test_rain_high(self):
        assert classify_rain(Decimal('0.25')) == RiskLevel.HIGH
        assert classify_rain(Decimal('0.49')) == RiskLevel.HIGH
    
    def test_rain_severe(self):
        assert classify_rain(Decimal('0.50')) == RiskLevel.SEVERE
        assert classify_rain(Decimal('0.99')) == RiskLevel.SEVERE
    
    def test_rain_no_travel(self):
        assert classify_rain(Decimal('1.00')) == RiskLevel.NO_TRAVEL
        assert classify_rain(Decimal('2.0')) == RiskLevel.NO_TRAVEL
```

### Snow Threshold Tests
```python
class TestSnowThresholds:
    def test_snow_low(self):
        assert classify_snow(Decimal('0.49')) == RiskLevel.LOW
        assert classify_snow(Decimal('0.50')) == RiskLevel.MODERATE
        assert classify_snow(Decimal('0.99')) == RiskLevel.MODERATE
    
    def test_snow_high(self):
        assert classify_snow(Decimal('1.0')) == RiskLevel.HIGH
        assert classify_snow(Decimal('1.99')) == RiskLevel.HIGH
    
    def test_snow_severe(self):
        assert classify_snow(Decimal('2.0')) == RiskLevel.SEVERE
        assert classify_snow(Decimal('2.99')) == RiskLevel.SEVERE
    
    def test_snow_no_travel(self):
        assert classify_snow(Decimal('3.0')) == RiskLevel.NO_TRAVEL
        assert classify_snow(Decimal('5.0')) == RiskLevel.NO_TRAVEL
```

### Load Rule Tests - **ALL COMBINATIONS**
```python
class TestLoadRules:
    """Test ALL load escalation rule combinations."""
    
    # Rule 1: Wind ≥55 mph → No Travel (ANY load)
    def test_wind_ge_55_any_load_no_travel(self):
        assert apply_load_rules(RiskLevel.NO_TRAVEL, Decimal('55'), 10000) == (RiskLevel.NO_TRAVEL, "wind_ge_55_any_load")
        assert apply_load_rules(RiskLevel.NO_TRAVEL, Decimal('60'), 25000) == (RiskLevel.NO_TRAVEL, "wind_ge_55_any_load")
        assert apply_load_rules(RiskLevel.NO_TRAVEL, Decimal('100'), 80000) == (RiskLevel.NO_TRAVEL, "wind_ge_55_any_load")
    
    # Rule 2: Wind 45-54 mph + Load >30,000 → No Travel
    def test_wind_45_54_under_30k_stays_severe(self):
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('45'), 10000) == (RiskLevel.SEVERE, "")
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('50'), 25000) == (RiskLevel.SEVERE, "")
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('54'), 30000) == (RiskLevel.SEVERE, "")  # Exactly 30k
    
    def test_wind_45_54_over_30k_becomes_no_travel(self):
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('45'), 30001) == (RiskLevel.NO_TRAVEL, "wind_45_54_over_30k")
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('50'), 35000) == (RiskLevel.NO_TRAVEL, "wind_45_54_over_30k")
        assert apply_load_rules(RiskLevel.SEVERE, Decimal('54'), 40000) == (RiskLevel.NO_TRAVEL, "wind_45_54_over_30k")
    
    # Rule 3: Wind 35-44 mph + Load >40,000 → Severe
    def test_wind_35_44_under_40k_stays_high(self):
        assert apply_load_rules(RiskLevel.HIGH, Decimal('35'), 10000) == (RiskLevel.HIGH, "")
        assert apply_load_rules(RiskLevel.HIGH, Decimal('40'), 35000) == (RiskLevel.HIGH, "")
        assert apply_load_rules(RiskLevel.HIGH, Decimal('44'), 40000) == (RiskLevel.HIGH, "")  # Exactly 40k
    
    def test_wind_35_44_over_40k_becomes_severe(self):
        assert apply_load_rules(RiskLevel.HIGH, Decimal('35'), 40001) == (RiskLevel.SEVERE, "wind_35_44_over_40k")
        assert apply_load_rules(RiskLevel.HIGH, Decimal('40'), 45000) == (RiskLevel.SEVERE, "wind_35_44_over_40k")
        assert apply_load_rules(RiskLevel.HIGH, Decimal('44'), 80000) == (RiskLevel.SEVERE, "wind_35_44_over_40k")
    
    # Rain/Snow NOT affected by load
    def test_rain_no_travel_not_affected_by_load(self):
        """Rain No Travel should stay No Travel regardless of load."""
        rain_obs = create_mock_weather(precipitation_rate=1.5, precip_type='rain')
        risk = calculate_checkpoint_risk(rain_obs, 80000, Decimal('25'))
        assert risk.combined_risk == RiskLevel.NO_TRAVEL
    
    def test_snow_no_travel_not_affected_by_load(self):
        """Snow No Travel should stay No Travel regardless of load."""
        snow_obs = create_mock_weather(snowfall_rate=4.0)
        risk = calculate_checkpoint_risk(snow_obs, 10000, Decimal('25'))
        assert risk.combined_risk == RiskLevel.NO_TRAVEL
```

### Combined Risk Calculation Tests
```python
class TestCombinedRisk:
    def test_max_of_three_risks(self):
        """Combined risk = max(wind, rain, snow) before load rules."""
        weather = create_mock_weather(wind=30, rain=0.2, snow=0)  # Moderate, Moderate, Low
        risk = calculate_checkpoint_risk(weather, 25000, Decimal('25'))
        assert risk.combined_risk == RiskLevel.MODERATE
    
    def test_load_escalation_applies(self):
        """Load rules should escalate wind-based risk."""
        # Wind 40mph (High) + Load 45000 (>40k) → Severe
        weather = create_mock_weather(wind=40, rain=0, snow=0)
        risk = calculate_checkpoint_risk(weather, 45000, Decimal('25'))
        assert risk.combined_risk == RiskLevel.SEVERE
        assert risk.load_rule_applied == "wind_35_44_over_40k"
    
    def test_no_travel_overrides_all(self):
        """No Travel from any condition should propagate."""
        weather = create_mock_weather(wind=60)  # Wind No Travel
        risk = calculate_checkpoint_risk(weather, 10000, Decimal('25'))
        assert risk.combined_risk == RiskLevel.NO_TRAVEL
        assert risk.load_rule_applied == "wind_ge_55_any_load"
```

## Service Tests (`test_services.py`)

### Route Scoring Priority Tests
```python
class TestRouteScoring:
    def test_priority_1_fewest_severe_miles(self):
        """Route with fewer severe miles wins regardless of other factors."""
        route_a = create_route_with_risks(severe=0, high=50, avg=2.5, duration=300)
        route_b = create_route_with_risks(severe=10, high=0, avg=1.0, duration=100)
        assert route_a.score.composite_score < route_b.score.composite_score
    
    def test_priority_2_fewest_high_miles(self):
        """Tie on severe → fewer high miles wins."""
        route_a = create_route_with_risks(severe=0, high=10, avg=2.0, duration=200)
        route_b = create_route_with_risks(severe=0, high=5, avg=2.0, duration=200)
        assert route_b.score.composite_score < route_a.score.composite_score
    
    def test_priority_3_lowest_avg_risk(self):
        """Tie on severe+high → lower avg risk wins."""
        route_a = create_route_with_risks(severe=0, high=0, avg=1.5, duration=200)
        route_b = create_route_with_risks(severe=0, high=0, avg=2.0, duration=200)
        assert route_a.score.composite_score < route_b.score.composite_score
    
    def test_priority_4_shortest_duration(self):
        """Tie on all above → shorter duration wins."""
        route_a = create_route_with_risks(severe=0, high=0, avg=1.5, duration=195)
        route_b = create_route_with_risks(severe=0, high=0, avg=1.5, duration=210)
        assert route_a.score.composite_score < route_b.score.composite_score
    
    def test_composite_score_monotonic(self):
        """Better on any priority should never increase composite score."""
        base = create_route_with_risks(severe=5, high=10, avg=2.0, duration=200)
        better_severe = create_route_with_risks(severe=4, high=10, avg=2.0, duration=200)
        better_high = create_route_with_risks(severe=5, high=9, avg=2.0, duration=200)
        better_avg = create_route_with_risks(severe=5, high=10, avg=1.9, duration=200)
        better_time = create_route_with_risks(severe=5, high=10, avg=2.0, duration=199)
        
        assert better_severe.score.composite_score < base.score.composite_score
        assert better_high.score.composite_score < base.score.composite_score
        assert better_avg.score.composite_score < base.score.composite_score
        assert better_time.score.composite_score < base.score.composite_score
```

### Recommendation Tests
```python
class TestRecommendation:
    def test_exactly_one_recommended(self):
        routes = create_three_routes_with_different_scores()
        result = get_recommendation(routes[0].request_id)
        
        recommended = [r for r in result.routes if r.is_recommended]
        assert len(recommended) == 1
    
    def test_recommended_is_lowest_composite(self):
        routes = create_three_routes_with_different_scores()
        result = get_recommendation(routes[0].request_id)
        
        recommended = next(r for r in result.routes if r.is_recommended)
        assert recommended.route_id == min(routes, key=lambda r: r.score.composite_score).id
    
    def test_all_routes_returned_with_scores(self):
        routes = create_three_routes_with_different_scores()
        result = get_recommendation(routes[0].request_id)
        
        assert len(result.routes) == 3
        for r in result.routes:
            assert hasattr(r, 'score')
            assert 'severe_miles' in r.score
            assert 'high_miles' in r.score
            assert 'average_risk_score' in r.score
```

## Property-Based Tests (`test_property_based.py`) - **CRITICAL**

```python
from hypothesis import given, settings, strategies as st
from decimal import Decimal

class TestRiskProperties:
    @settings(max_examples=1000)
    @given(st.decimals(min_value=0, max_value=100, places=1))
    def test_wind_classification_monotonic(self, speed):
        """Higher wind speed never results in lower risk level."""
        risk1 = classify_wind(speed)
        risk2 = classify_wind(speed + Decimal('0.1'))
        assert risk2 >= risk1
    
    @settings(max_examples=1000)
    @given(st.decimals(min_value=0, max_value=5, places=2))
    def test_rain_classification_monotonic(self, rate):
        """Higher rain rate never results in lower risk level."""
        risk1 = classify_rain(rate)
        risk2 = classify_rain(rate + Decimal('0.01'))
        assert risk2 >= risk1
    
    @settings(max_examples=1000)
    @given(st.decimals(min_value=0, max_value=5, places=1))
    def test_snow_classification_monotonic(self, rate):
        """Higher snow rate never results in lower risk level."""
        risk1 = classify_snow(rate)
        risk2 = classify_snow(rate + Decimal('0.1'))
        assert risk2 >= risk1
    
    @settings(max_examples=500)
    @given(
        st.decimals(min_value=0, max_value=100, places=1),
        st.integers(min_value=10000, max_value=80000)
    )
    def test_load_rules_monotonic_in_load(self, wind_speed, load):
        """For same wind speed, higher load never improves risk."""
        base_risk = classify_wind(wind_speed)
        risk1, _ = apply_load_rules(base_risk, wind_speed, load)
        risk2, _ = apply_load_rules(base_risk, wind_speed, load + 1000)
        assert risk2 >= risk1
    
    @settings(max_examples=500)
    @given(
        st.integers(min_value=0, max_value=1000),
        st.integers(min_value=0, max_value=1000),
        st.decimals(min_value=1, max_value=5, places=1),
        st.integers(min_value=1, max_value=500)
    )
    def test_scoring_priority_order(self, severe, high, avg_risk, duration):
        """Composite score respects priority order lexicographically."""
        # This is implicitly tested by the composite formula
        # But we verify the encoding works
        composite = (
            Decimal(str(severe)) * Decimal('10000') +
            Decimal(str(high)) * Decimal('100') +
            avg_risk * Decimal('10') +
            Decimal(str(duration)) / Decimal('1000')
        )
        
        # Verify components don't overlap
        severe_component = Decimal(str(severe)) * Decimal('10000')
        high_component = Decimal(str(high)) * Decimal('100')
        assert high_component < Decimal('10000')  # High can't overflow into severe
        assert (avg_risk * Decimal('10')) < Decimal('100')  # Avg can't overflow into high
        assert (Decimal(str(duration)) / Decimal('1000')) < Decimal('10')  # Duration can't overflow into avg
```

## Integration Tests (`test_integration.py`)

```python
class TestRiskIntegration:
    @pytest.mark.django_db
    def test_full_risk_pipeline(self, route_with_weather, mock_risk_rules):
        """Weather → Risk → Score → Recommendation"""
        route = route_with_weather
        
        # Calculate risk for all checkpoints
        calculate_risk_for_checkpoint(str(cp.id)) for cp in route.checkpoints.all()
        
        # Score route
        score_route(str(route.id))
        
        # Get recommendation
        result = get_recommendation(str(route.request_id))
        
        assert result.recommended_route_id is not None
        assert len(result.routes) == 3
        for r in result.routes:
            assert r.score is not None
    
    @pytest.mark.django_db
    def test_calculate_endpoint(self, client, route_with_weather):
        response = client.post("/api/v1/risk/calculate/", {
            "route_id": str(route_with_weather.id),
            "load_weight_lbs": 45000,
            "checkpoint_interval_miles": 25
        }, format='json')
        
        assert response.status_code == 200
        assert 'checkpoints' in response.data
        for cp in response.data['checkpoints']:
            assert 'risk' in cp
            assert cp['risk']['combined_risk'] in ['low', 'moderate', 'high', 'severe', 'no_travel']
    
    @pytest.mark.django_db
    def test_recommendation_endpoint(self, client, scored_routes):
        request_id = scored_routes[0].request_id
        response = client.get(f"/api/v1/risk/recommendation/{scored_routes[0].id}/")
        
        assert response.status_code == 200
        assert response.data['recommended_route_id'] is not None
        assert len(response.data['routes']) == 3
```

## Fixtures (`fixtures.py`)

```python
def create_mock_weather(wind=0, rain=0, snow=0, precip_type='none'):
    return WeatherObservation(
        wind_speed_mph=Decimal(str(wind)),
        wind_direction_deg=180,
        precipitation_rate_in_hr=Decimal(str(rain + snow)),
        precipitation_type=precip_type,
        snowfall_rate_in_hr=Decimal(str(snow)),
        temperature_f=Decimal('50'),
        humidity_pct=50,
        visibility_mi=Decimal('10'),
        conditions='Test',
        raw_response={}
    )

def create_route_with_risks(severe=0, high=0, avg=1.0, duration=200):
    route = Route.objects.create(distance_miles=100, duration_minutes=duration, ...)
    RouteScore.objects.create(
        route=route,
        severe_miles=Decimal(str(severe)),
        high_miles=Decimal(str(high)),
        average_risk_score=Decimal(str(avg)),
        duration_minutes=duration,
        composite_score=Decimal(str(severe * 10000 + high * 100 + float(avg) * 10 + duration / 1000)),
        risk_breakdown={'severe': severe, 'high': high, 'moderate': 50, 'low': 50 - severe - high}
    )
    return route
```

## Running Tests

```bash
# ALL risk tests (MUST PASS)
pytest apps/risk/tests/ -v

# Critical: Rules tests only
pytest apps/risk/tests/test_rules.py -v --tb=short

# Property-based tests
pytest apps/risk/tests/test_property_based.py -v

# With coverage (rules MUST be 100%)
pytest apps/risk/tests/ --cov=apps.risk --cov-report=term-missing --cov-fail-under=95

# CI: Fail if rules not 100%
pytest apps/risk/tests/test_rules.py --cov=apps.risk.rules --cov-fail-under=100
```

## CI Gate

```yaml
# .github/workflows/test.yml
- name: Test Risk Service
  run: |
    # Rules MUST have 100% coverage
    docker compose -f docker-compose.test.yml run --rm django \
      pytest apps/risk/tests/test_rules.py --cov=apps.risk.rules --cov-fail-under=100
    
    # All risk tests with 95% overall
    docker compose -f docker-compose.test.yml run --rm django \
      pytest apps/risk/tests/ --cov=apps.risk --cov-fail-under=95
```

## Mutation Testing (Optional but Recommended)

```bash
# Install mutmut
pip install mutmut

# Run mutation testing on rules.py
mutmut run --paths-to-mutate=apps/risk/rules.py

# Results
mutmut results
mutmut html
```