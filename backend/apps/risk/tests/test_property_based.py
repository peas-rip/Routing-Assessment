"""Property-based invariants for risk classification and scoring (F05/F06).

docs/SERVICES/risk/TESTING.md: monotonicity of the classifiers and load
rules, and the non-overlapping composite score encoding.
"""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from apps.risk.rules import (
    RISK_SCORE_MAP,
    RiskLevel,
    apply_load_rules,
    classify_rain,
    classify_snow,
    classify_wind,
)
from apps.risk.services import (
    AVERAGE_RISK_WEIGHT,
    DURATION_WEIGHT,
    HIGH_MILES_WEIGHT,
    SEVERE_MILES_WEIGHT,
)


class TestRiskProperties:
    @settings(max_examples=300)
    @given(st.decimals(min_value=0, max_value=100, places=1))
    def test_wind_classification_monotonic(self, speed):
        """Higher wind speed never results in lower risk."""
        risk1 = classify_wind(speed)
        risk2 = classify_wind(speed + Decimal("0.1"))
        assert risk2 >= risk1

    @settings(max_examples=300)
    @given(st.decimals(min_value=0, max_value=5, places=2))
    def test_rain_classification_monotonic(self, rate):
        """Higher rain rate never results in lower risk."""
        risk1 = classify_rain(rate)
        risk2 = classify_rain(rate + Decimal("0.01"))
        assert risk2 >= risk1

    @settings(max_examples=300)
    @given(st.decimals(min_value=0, max_value=5, places=1))
    def test_snow_classification_monotonic(self, rate):
        """Higher snow rate never results in lower risk."""
        risk1 = classify_snow(rate)
        risk2 = classify_snow(rate + Decimal("0.1"))
        assert risk2 >= risk1

    @settings(max_examples=300)
    @given(
        st.decimals(min_value=0, max_value=100, places=1),
        st.integers(min_value=10000, max_value=79000),
    )
    def test_load_rules_monotonic_in_load(self, wind_speed, load):
        """For the same wind, a heavier load never improves risk."""
        base_risk = classify_wind(wind_speed)
        risk1, _ = apply_load_rules(base_risk, wind_speed, load)
        risk2, _ = apply_load_rules(base_risk, wind_speed, load + 1000)
        assert risk2 >= risk1


class TestScoringEncodingProperties:
    @settings(max_examples=300)
    @given(
        st.integers(min_value=0, max_value=1000),
        st.integers(min_value=0, max_value=99),
        st.decimals(min_value=1, max_value=5, places=3),
        st.integers(min_value=1, max_value=500),
    )
    def test_composite_terms_never_overlap(self, severe, high, avg_risk, duration):
        """No priority term can overflow into the next priority's slot."""
        assert Decimal(str(high)) * HIGH_MILES_WEIGHT < SEVERE_MILES_WEIGHT
        assert avg_risk * AVERAGE_RISK_WEIGHT < HIGH_MILES_WEIGHT
        assert Decimal(str(duration)) / DURATION_WEIGHT < AVERAGE_RISK_WEIGHT

    @settings(max_examples=300)
    @given(
        st.integers(min_value=0, max_value=100),
        st.integers(min_value=0, max_value=100),
        st.decimals(min_value=1, max_value=5, places=2),
        st.integers(min_value=1, max_value=500),
    )
    def test_improving_any_priority_lowers_composite(self, severe, high, avg_risk, duration):
        """Better on any single priority never increases the composite."""

        def composite(severe_miles, high_miles, average, minutes):
            return (
                Decimal(str(severe_miles)) * SEVERE_MILES_WEIGHT
                + Decimal(str(high_miles)) * HIGH_MILES_WEIGHT
                + average * AVERAGE_RISK_WEIGHT
                + Decimal(str(minutes)) / DURATION_WEIGHT
            )

        base = composite(severe, high, avg_risk, duration)
        assert composite(severe - 1 if severe else 0, high, avg_risk, duration) <= base
        assert composite(severe, high - 1 if high else 0, avg_risk, duration) <= base
        assert composite(severe, high, avg_risk - Decimal("0.01"), duration) <= base
        assert composite(severe, high, avg_risk, duration - 1) <= base

    def test_risk_scores_are_strictly_increasing(self):
        scores = [RISK_SCORE_MAP[level] for level in RiskLevel]
        assert all(left < right for left, right in zip(scores, scores[1:], strict=False))
