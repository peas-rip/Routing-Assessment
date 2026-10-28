"""Threshold boundaries and load rules - the most critical risk tests.

docs/SERVICES/risk/TESTING.md requires 100% coverage of apps/risk/rules.py.
The rain/snow top boundaries follow the confirmed SERVICE_SPEC/TESTING.md
decision: exactly 1.00 in/hr rain and exactly 3.0 in/hr snow are No Travel.
"""

from decimal import Decimal

import pytest

from apps.risk.rules import (
    RISK_SCORE_MAP,
    RiskLevel,
    _classify,
    apply_load_rules,
    classify_rain,
    classify_snow,
    classify_wind,
)


class TestRiskLevel:
    def test_severity_ordering(self):
        assert RiskLevel.LOW < RiskLevel.MODERATE < RiskLevel.HIGH
        assert RiskLevel.HIGH < RiskLevel.SEVERE < RiskLevel.NO_TRAVEL

    def test_value_labels(self):
        assert RiskLevel.LOW.value_label == "low"
        assert RiskLevel.NO_TRAVEL.value_label == "no_travel"

    def test_from_value_round_trip(self):
        for level in RiskLevel:
            assert RiskLevel.from_value(level.value_label) == level

    def test_from_value_rejects_unknown(self):
        with pytest.raises(KeyError):
            RiskLevel.from_value("catastrophic")

    def test_score_map_covers_every_level(self):
        assert set(RISK_SCORE_MAP) == set(RiskLevel)
        scores = [RISK_SCORE_MAP[level] for level in RiskLevel]
        assert scores == sorted(scores)


class TestClassifyWithoutSentinel:
    def test_value_above_all_thresholds_defaults_to_no_travel(self):
        # A table lacking the (None, NO_TRAVEL) sentinel falls through to
        # the conservative default instead of returning a lower band.
        result = _classify(Decimal("10"), [(Decimal("5"), RiskLevel.LOW)])
        assert result == RiskLevel.NO_TRAVEL


class TestWindThresholds:
    """docs/SERVICES/risk/TESTING.md wind boundaries (100% exact)."""

    def test_wind_low(self):
        assert classify_wind(Decimal("0")) == RiskLevel.LOW
        assert classify_wind(Decimal("12.5")) == RiskLevel.LOW
        assert classify_wind(Decimal("24.9")) == RiskLevel.LOW

    def test_wind_moderate(self):
        assert classify_wind(Decimal("25.0")) == RiskLevel.MODERATE
        assert classify_wind(Decimal("34.9")) == RiskLevel.MODERATE

    def test_wind_high(self):
        assert classify_wind(Decimal("35.0")) == RiskLevel.HIGH
        assert classify_wind(Decimal("44.9")) == RiskLevel.HIGH

    def test_wind_severe(self):
        assert classify_wind(Decimal("45.0")) == RiskLevel.SEVERE
        assert classify_wind(Decimal("54.9")) == RiskLevel.SEVERE

    def test_wind_no_travel(self):
        assert classify_wind(Decimal("55.0")) == RiskLevel.NO_TRAVEL
        assert classify_wind(Decimal("100")) == RiskLevel.NO_TRAVEL

    def test_wind_accepts_float_input(self):
        assert classify_wind(34.9) == RiskLevel.MODERATE
        assert classify_wind(55) == RiskLevel.NO_TRAVEL


class TestRainThresholds:
    """Rain boundaries; exactly 1.00 in/hr is No Travel (boundary decision)."""

    def test_rain_low(self):
        assert classify_rain(Decimal("0")) == RiskLevel.LOW
        assert classify_rain(Decimal("0.09")) == RiskLevel.LOW

    def test_rain_moderate(self):
        assert classify_rain(Decimal("0.10")) == RiskLevel.MODERATE
        assert classify_rain(Decimal("0.24")) == RiskLevel.MODERATE

    def test_rain_high(self):
        assert classify_rain(Decimal("0.25")) == RiskLevel.HIGH
        assert classify_rain(Decimal("0.49")) == RiskLevel.HIGH

    def test_rain_severe(self):
        assert classify_rain(Decimal("0.50")) == RiskLevel.SEVERE
        assert classify_rain(Decimal("0.99")) == RiskLevel.SEVERE

    def test_rain_no_travel(self):
        assert classify_rain(Decimal("1.00")) == RiskLevel.NO_TRAVEL
        assert classify_rain(Decimal("2.00")) == RiskLevel.NO_TRAVEL


class TestSnowThresholds:
    """Snow boundaries; exactly 3.0 in/hr is No Travel (boundary decision)."""

    def test_snow_low(self):
        assert classify_snow(Decimal("0")) == RiskLevel.LOW
        assert classify_snow(Decimal("0.49")) == RiskLevel.LOW

    def test_snow_moderate(self):
        assert classify_snow(Decimal("0.5")) == RiskLevel.MODERATE
        assert classify_snow(Decimal("0.99")) == RiskLevel.MODERATE

    def test_snow_high(self):
        assert classify_snow(Decimal("1.0")) == RiskLevel.HIGH
        assert classify_snow(Decimal("1.99")) == RiskLevel.HIGH

    def test_snow_severe(self):
        assert classify_snow(Decimal("2.0")) == RiskLevel.SEVERE
        assert classify_snow(Decimal("2.99")) == RiskLevel.SEVERE

    def test_snow_no_travel(self):
        assert classify_snow(Decimal("3.0")) == RiskLevel.NO_TRAVEL
        assert classify_snow(Decimal("5.0")) == RiskLevel.NO_TRAVEL


class TestLoadRules:
    """ALL load escalation combinations (docs/SERVICES/risk/TESTING.md)."""

    # Rule 1: wind >= 55 mph -> No Travel for ANY load.
    def test_wind_ge_55_any_load(self):
        assert apply_load_rules(RiskLevel.NO_TRAVEL, Decimal("55"), 10000) == (
            RiskLevel.NO_TRAVEL,
            "wind_ge_55_any_load",
        )
        assert apply_load_rules(RiskLevel.NO_TRAVEL, Decimal("60"), 25000) == (
            RiskLevel.NO_TRAVEL,
            "wind_ge_55_any_load",
        )
        assert apply_load_rules(RiskLevel.NO_TRAVEL, Decimal("100"), 80000) == (
            RiskLevel.NO_TRAVEL,
            "wind_ge_55_any_load",
        )

    # Rule 2: wind 45-54 mph (Severe) + load > 30,000 -> No Travel.
    def test_wind_45_54_under_30k_stays_severe(self):
        assert apply_load_rules(RiskLevel.SEVERE, Decimal("45"), 10000) == (RiskLevel.SEVERE, "")
        assert apply_load_rules(RiskLevel.SEVERE, Decimal("50"), 25000) == (RiskLevel.SEVERE, "")
        # Exactly 30,000 lbs does NOT trigger the rule.
        assert apply_load_rules(RiskLevel.SEVERE, Decimal("54"), 30000) == (RiskLevel.SEVERE, "")

    def test_wind_45_54_over_30k_becomes_no_travel(self):
        assert apply_load_rules(RiskLevel.SEVERE, Decimal("45"), 30001) == (
            RiskLevel.NO_TRAVEL,
            "wind_45_54_over_30k",
        )
        assert apply_load_rules(RiskLevel.SEVERE, Decimal("50"), 35000) == (
            RiskLevel.NO_TRAVEL,
            "wind_45_54_over_30k",
        )
        assert apply_load_rules(RiskLevel.SEVERE, Decimal("54"), 40000) == (
            RiskLevel.NO_TRAVEL,
            "wind_45_54_over_30k",
        )

    # Rule 3: wind 35-44 mph (High) + load > 40,000 -> Severe.
    def test_wind_35_44_under_40k_stays_high(self):
        assert apply_load_rules(RiskLevel.HIGH, Decimal("35"), 10000) == (RiskLevel.HIGH, "")
        assert apply_load_rules(RiskLevel.HIGH, Decimal("40"), 35000) == (RiskLevel.HIGH, "")
        # Exactly 40,000 lbs does NOT trigger the rule.
        assert apply_load_rules(RiskLevel.HIGH, Decimal("44"), 40000) == (RiskLevel.HIGH, "")

    def test_wind_35_44_over_40k_becomes_severe(self):
        assert apply_load_rules(RiskLevel.HIGH, Decimal("35"), 40001) == (
            RiskLevel.SEVERE,
            "wind_35_44_over_40k",
        )
        assert apply_load_rules(RiskLevel.HIGH, Decimal("40"), 45000) == (
            RiskLevel.SEVERE,
            "wind_35_44_over_40k",
        )
        assert apply_load_rules(RiskLevel.HIGH, Decimal("44"), 80000) == (
            RiskLevel.SEVERE,
            "wind_35_44_over_40k",
        )

    def test_no_rule_for_moderate_or_lower_wind(self):
        assert apply_load_rules(RiskLevel.MODERATE, Decimal("30"), 80000) == (
            RiskLevel.MODERATE,
            "",
        )
        assert apply_load_rules(RiskLevel.LOW, Decimal("10"), 80000) == (RiskLevel.LOW, "")

    def test_wind_ge_55_dominates_given_risk_level(self):
        # The speed check fires first regardless of the passed risk level.
        assert apply_load_rules(RiskLevel.HIGH, Decimal("55"), 10000) == (
            RiskLevel.NO_TRAVEL,
            "wind_ge_55_any_load",
        )
