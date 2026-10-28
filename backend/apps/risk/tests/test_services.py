"""Risk calculation, scoring and recommendation services (F05/F06)."""

from decimal import Decimal

import pytest
from django.test import TestCase

from apps.risk.exceptions import InsufficientRiskDataError
from apps.risk.models import RiskAssessment, RouteScore
from apps.risk.services import (
    assess_checkpoint,
    assess_conditions,
    assess_route,
    calculate_checkpoint_risk,
    calculate_route_score,
    extract_precip_rates,
    rank_routes,
    segment_miles_by_checkpoint,
)
from apps.routing.tests.fixtures import make_route, make_route_request
from apps.weather.models import WeatherObservation
from apps.weather.tests.fixtures import make_checkpoint, make_observation

from .fixtures import create_mock_weather, make_scored_route

ZERO = Decimal("0")


def persist_assessment(checkpoint, observation, combined="low", miles="25.00"):
    """Persist one assessment row directly (scoring fixtures)."""
    return RiskAssessment.objects.create(
        checkpoint=checkpoint,
        weather_observation=observation,
        load_weight_lbs=45000,
        wind_risk=combined,
        rain_risk="low",
        snow_risk="low",
        combined_risk=combined,
        load_rule_applied=None,
        segment_miles=Decimal(miles),
    )


def scored_and_assessed(route_request, **kwargs):
    """Route with both a RouteScore and an assessment (ranking eligibility)."""
    route = make_scored_route(route_request, **kwargs)
    checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)
    observation = make_observation(checkpoint)
    persist_assessment(checkpoint, observation)
    return route


class TestExtractPrecipRates:
    def test_rain_counts_fully_as_rain(self):
        weather = create_mock_weather(rain=0.7, precip_type="rain")
        assert extract_precip_rates(weather) == (Decimal("0.7"), ZERO)

    def test_snow_counts_fully_as_snow(self):
        weather = create_mock_weather(snow=1.5, precip_type="snow")
        assert extract_precip_rates(weather) == (ZERO, Decimal("1.5"))

    def test_snow_type_without_snowfall_uses_total_rate(self):
        weather = create_mock_weather(rain=1.2, precip_type="snow", snow=0)
        assert extract_precip_rates(weather) == (ZERO, Decimal("1.2"))

    def test_mixed_splits_total_minus_snow_as_rain(self):
        weather = WeatherObservation(
            precipitation_rate_in_hr=Decimal("0.7"),
            snowfall_rate_in_hr=Decimal("0.5"),
            precipitation_type="mixed",
            raw_response={},
        )
        assert extract_precip_rates(weather) == (Decimal("0.2"), Decimal("0.5"))

    def test_mixed_never_produces_negative_rain(self):
        weather = WeatherObservation(
            precipitation_rate_in_hr=Decimal("0.3"),
            snowfall_rate_in_hr=Decimal("0.5"),
            precipitation_type="mixed",
            raw_response={},
        )
        assert extract_precip_rates(weather) == (ZERO, Decimal("0.5"))

    def test_none_yields_zero_rates(self):
        weather = create_mock_weather(rain=0.5, snow=0.2, precip_type="none")
        assert extract_precip_rates(weather) == (ZERO, ZERO)

    def test_missing_rates_yield_zero(self):
        weather = WeatherObservation(precipitation_type="none", raw_response={})
        assert extract_precip_rates(weather) == (ZERO, ZERO)

    def test_missing_rain_rates_yield_zero(self):
        weather = WeatherObservation(precipitation_type="rain", raw_response={})
        assert extract_precip_rates(weather) == (ZERO, ZERO)


class TestAssessConditions:
    def test_combined_is_max_of_three(self):
        weather = create_mock_weather(wind=30, rain=0.2, precip_type="rain")
        risks = assess_conditions(weather, 25000)
        assert risks["wind_risk"].value_label == "moderate"
        assert risks["rain_risk"].value_label == "moderate"
        assert risks["snow_risk"].value_label == "low"
        assert risks["combined_risk"].value_label == "moderate"
        assert risks["load_rule_applied"] is None

    def test_snow_dominates_combination(self):
        weather = create_mock_weather(wind=10, snow=1.5, precip_type="snow")
        assert assess_conditions(weather, 10000)["combined_risk"].value_label == "high"

    def test_load_escalation_applies_to_wind(self):
        weather = create_mock_weather(wind=40)
        risks = assess_conditions(weather, 45000)
        assert risks["combined_risk"].value_label == "severe"
        assert risks["load_rule_applied"] == "wind_35_44_over_40k"

    def test_wind_no_travel_with_any_load(self):
        weather = create_mock_weather(wind=60)
        risks = assess_conditions(weather, 10000)
        assert risks["combined_risk"].value_label == "no_travel"
        assert risks["load_rule_applied"] == "wind_ge_55_any_load"

    def test_rain_no_travel_not_affected_by_load(self):
        weather = create_mock_weather(rain=1.5, precip_type="rain")
        risks = assess_conditions(weather, 80000)
        assert risks["combined_risk"].value_label == "no_travel"
        assert risks["load_rule_applied"] is None

    def test_snow_no_travel_not_affected_by_load(self):
        weather = create_mock_weather(snow=4.0, precip_type="snow")
        risks = assess_conditions(weather, 10000)
        assert risks["combined_risk"].value_label == "no_travel"
        assert risks["load_rule_applied"] is None

    def test_escalation_never_lowers_combined_risk(self):
        # Wind 40 (High) with light load stays High, but rain is No Travel.
        weather = create_mock_weather(wind=40, rain=1.5, precip_type="rain")
        risks = assess_conditions(weather, 10000)
        assert risks["combined_risk"].value_label == "no_travel"
        assert risks["load_rule_applied"] is None

    def test_moderate_wind_never_triggers_rules(self):
        weather = create_mock_weather(wind=30)
        risks = assess_conditions(weather, 80000)
        assert risks["combined_risk"].value_label == "moderate"
        assert risks["load_rule_applied"] is None

    def test_missing_wind_speed_counts_as_calm(self):
        weather = WeatherObservation(precipitation_type="none", raw_response={})
        assert assess_conditions(weather, 45000)["combined_risk"].value_label == "low"


@pytest.mark.django_db
class TestCalculateCheckpointRisk:
    def test_builds_unsaved_assessment_with_labels(self):
        weather = create_mock_weather(wind=40)
        assessment = calculate_checkpoint_risk(weather, 45000, Decimal("25.00"))
        assert not RiskAssessment.objects.exists()  # built in memory, not saved
        assert assessment.load_weight_lbs == 45000
        assert assessment.wind_risk == "high"
        assert assessment.rain_risk == "low"
        assert assessment.snow_risk == "low"
        assert assessment.combined_risk == "severe"
        assert assessment.load_rule_applied == "wind_35_44_over_40k"
        assert assessment.segment_miles == Decimal("25.00")

    def test_no_rule_stores_none(self):
        weather = create_mock_weather(wind=10)
        assessment = calculate_checkpoint_risk(weather, 10000, ZERO)
        assert assessment.combined_risk == "low"
        assert assessment.load_rule_applied is None


class TestSegmentMilesByCheckpoint(TestCase):
    def test_segments_run_from_each_checkpoint_forward(self):
        route = make_scored_route(distance_miles=Decimal("100.00"))
        markers = [Decimal("0.00"), Decimal("50.00"), Decimal("100.00")]
        checkpoints = [
            make_checkpoint(route=route, sequence=index, mile_marker=marker)
            for index, marker in enumerate(markers)
        ]

        segments = segment_miles_by_checkpoint(route)

        # API_CONTRACTS: the origin covers the miles to the next checkpoint;
        # the destination checkpoint sits at the route end, so it covers 0.
        assert segments[checkpoints[0].id] == Decimal("50.00")
        assert segments[checkpoints[1].id] == Decimal("50.00")
        assert segments[checkpoints[2].id] == ZERO
        assert sum(segments.values()) == route.distance_miles

    def test_destination_checkpoint_covers_remaining_distance(self):
        route = make_scored_route(distance_miles=Decimal("75.00"))
        markers = [Decimal("0.00"), Decimal("25.00"), Decimal("50.00")]
        checkpoints = [
            make_checkpoint(route=route, sequence=index, mile_marker=marker)
            for index, marker in enumerate(markers)
        ]

        segments = segment_miles_by_checkpoint(route)

        # FEATURE_05 edge case 8: the destination checkpoint covers the
        # remaining distance to the route's end.
        assert segments[checkpoints[2].id] == Decimal("25.00")
        assert sum(segments.values()) == Decimal("75.00")

    def test_orders_by_sequence_not_creation(self):
        route = make_scored_route(distance_miles=Decimal("100.00"))
        late = make_checkpoint(route=route, sequence=1, mile_marker=Decimal("40.00"))
        early = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)

        segments = segment_miles_by_checkpoint(route)

        assert segments[early.id] == Decimal("40.00")  # to the next checkpoint
        assert segments[late.id] == Decimal("60.00")  # remaining to the end

    def test_duplicate_mile_marker_yields_zero_segment(self):
        route = make_scored_route(distance_miles=Decimal("100.00"))
        markers = [Decimal("0.00"), Decimal("0.00"), Decimal("40.00")]
        checkpoints = [
            make_checkpoint(route=route, sequence=index, mile_marker=marker)
            for index, marker in enumerate(markers)
        ]

        segments = segment_miles_by_checkpoint(route)

        assert segments[checkpoints[0].id] == ZERO
        assert sum(segments.values()) == route.distance_miles

    def test_regressing_mile_marker_clamps_at_zero(self):
        route = make_scored_route(distance_miles=Decimal("60.00"))
        markers = [Decimal("0.00"), Decimal("40.00"), Decimal("20.00"), Decimal("60.00")]
        checkpoints = [
            make_checkpoint(route=route, sequence=index, mile_marker=marker)
            for index, marker in enumerate(markers)
        ]

        segments = segment_miles_by_checkpoint(route)

        # The next marker regresses (40 -> 20), so the segment clamps at 0.
        assert segments[checkpoints[1].id] == ZERO

    def test_single_checkpoint_represents_full_route(self):
        route = make_scored_route(distance_miles=Decimal("80.00"))
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)

        segments = segment_miles_by_checkpoint(route)

        assert segments == {checkpoint.id: Decimal("80.00")}

    def test_route_without_checkpoints(self):
        route = make_scored_route()
        assert segment_miles_by_checkpoint(route) == {}

    def test_accepts_explicit_checkpoint_list(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)

        segments = segment_miles_by_checkpoint(route, [checkpoint])

        # A lone origin checkpoint covers the whole route (last = remaining
        # distance to the end).
        assert segments == {checkpoint.id: route.distance_miles}


class TestAssessCheckpoint(TestCase):
    def test_persists_assessment(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)
        observation = make_observation(checkpoint, wind_speed_mph=Decimal("40.00"))

        assessment = assess_checkpoint(checkpoint, observation, 45000, Decimal("25.00"))

        stored = RiskAssessment.objects.get(checkpoint=checkpoint)
        assert stored.id == assessment.id
        assert stored.combined_risk == "severe"
        assert stored.load_rule_applied == "wind_35_44_over_40k"
        assert stored.weather_observation_id == observation.id
        assert stored.segment_miles == Decimal("25.00")

    def test_upserts_one_row_per_checkpoint(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)
        observation = make_observation(checkpoint)

        assess_checkpoint(checkpoint, observation, 10000, ZERO)
        assess_checkpoint(checkpoint, observation, 45000, ZERO)

        stored = RiskAssessment.objects.get(checkpoint=checkpoint)
        assert RiskAssessment.objects.count() == 1
        assert stored.load_weight_lbs == 45000

    def test_refreshes_calculated_at_on_update(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)
        observation = make_observation(checkpoint)

        first = assess_checkpoint(checkpoint, observation, 10000, ZERO)
        old_timestamp = first.calculated_at.replace(year=2020)
        RiskAssessment.objects.filter(id=first.id).update(calculated_at=old_timestamp)

        second = assess_checkpoint(checkpoint, observation, 10000, ZERO)

        assert second.calculated_at > old_timestamp


class TestAssessRoute(TestCase):
    def test_assesses_only_checkpoints_with_weather(self):
        route = make_scored_route()
        with_weather = [
            make_checkpoint(route=route, sequence=index, mile_marker=Decimal(f"{index * 50}.00"))
            for index in range(3)
        ]
        make_observation(with_weather[0], wind_speed_mph=Decimal("40.00"))
        make_observation(with_weather[1])
        bare = make_checkpoint(route=route, sequence=3, mile_marker=Decimal("150.00"))

        assessments = assess_route(route, 45000)

        assert RiskAssessment.objects.count() == 2
        assert bare.id not in {assessment.checkpoint_id for assessment in assessments}
        by_checkpoint = {assessment.checkpoint_id: assessment for assessment in assessments}
        assert by_checkpoint[with_weather[0].id].combined_risk == "severe"
        assert by_checkpoint[with_weather[1].id].segment_miles == Decimal("50.00")

    def test_route_without_checkpoints_is_empty(self):
        route = make_scored_route()
        assert assess_route(route, 45000) == []


class TestCalculateRouteScore(TestCase):
    def test_aggregates_breakdown_and_priorities(self):
        route = make_scored_route(distance_miles=Decimal("100.00"))
        first = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)
        second = make_checkpoint(route=route, sequence=1, mile_marker=Decimal("50.00"))
        observation = make_observation(first)
        persist_assessment(first, observation, combined="high", miles="50.00")
        persist_assessment(second, observation, combined="no_travel", miles="50.00")

        score = calculate_route_score(route)

        assert score.severe_miles == Decimal("50.00")
        assert score.high_miles == Decimal("50.00")
        assert score.average_risk_score == Decimal("4.000")
        assert score.duration_minutes == 200
        # 50 severe * 10000 + 50 high * 100 + 4.0 avg * 10 + 200/1000
        assert score.composite_score == Decimal("505040.200")
        assert score.risk_breakdown == {
            "low": 0.0,
            "moderate": 0.0,
            "high": 50.0,
            "severe": 0.0,
            "no_travel": 50.0,
        }

    def test_weighted_average_risk(self):
        route = make_scored_route(duration=100)
        checkpoints = [
            make_checkpoint(route=route, sequence=index, mile_marker=Decimal(f"{index * 25}.00"))
            for index in range(2)
        ]
        observation = make_observation(checkpoints[0])
        persist_assessment(checkpoints[0], observation, combined="low", miles="25.00")
        persist_assessment(checkpoints[1], observation, combined="moderate", miles="75.00")

        score = calculate_route_score(route)

        # (1 * 25 + 2 * 75) / 100 = 1.75
        assert score.average_risk_score == Decimal("1.750")
        assert score.risk_breakdown["moderate"] == 75.0

    def test_route_without_assessments_scores_minimal(self):
        route = make_scored_route(duration=200)

        score = calculate_route_score(route)

        assert score.severe_miles == ZERO
        assert score.high_miles == ZERO
        assert score.average_risk_score == Decimal("1.000")
        # avg 1.0 * 10 + duration 200 / 1000 = 10.200
        assert score.composite_score == Decimal("10.200")
        assert score.risk_breakdown == {
            "low": 0.0,
            "moderate": 0.0,
            "high": 0.0,
            "severe": 0.0,
            "no_travel": 0.0,
        }

    def test_rescoring_updates_a_single_row(self):
        route = make_scored_route()
        checkpoint = make_checkpoint(route=route, sequence=0, mile_marker=ZERO)
        observation = make_observation(checkpoint)
        persist_assessment(checkpoint, observation, combined="severe", miles="100.00")

        first = calculate_route_score(route)
        second = calculate_route_score(route)

        assert first.id == second.id
        assert RouteScore.objects.count() == 1
        assert second.severe_miles == Decimal("100.00")


class TestRankRoutes(TestCase):
    def test_ranks_by_composite_ascending(self):
        request = make_route_request()
        worse = scored_and_assessed(request, severe=10, avg=1.0, duration=100, route_index=0)
        better = scored_and_assessed(request, high=50, avg=2.5, duration=300, route_index=1)

        ranked, recommended_id = rank_routes(better)

        assert [route.id for route, _ in ranked] == [better.id, worse.id]
        assert recommended_id == better.id

    def test_scores_missing_routes_lazily(self):
        request = make_route_request()
        scored_and_assessed(request, route_index=0)
        unscored = make_route(request, route_index=1)
        checkpoint = make_checkpoint(route=unscored, sequence=0, mile_marker=ZERO)
        observation = make_observation(checkpoint)
        persist_assessment(checkpoint, observation)

        ranked, recommended_id = rank_routes(unscored)

        assert len(ranked) == 2
        assert RouteScore.objects.filter(route=unscored).exists()
        assert recommended_id in {route.id for route, _ in ranked}

    def test_routes_without_assessments_are_not_ranked(self):
        request = make_route_request()
        first = scored_and_assessed(request, route_index=0)
        second = scored_and_assessed(request, avg=2.0, route_index=1)
        make_route(request, route_index=2)  # never assessed

        ranked, recommended_id = rank_routes(first)

        assert {route.id for route, _ in ranked} == {first.id, second.id}
        assert recommended_id == first.id

    def test_single_route_request_cannot_be_ranked(self):
        request = make_route_request()
        route = scored_and_assessed(request)

        with pytest.raises(InsufficientRiskDataError) as excinfo:
            rank_routes(route)

        assert excinfo.value.status_code == 400
        assert excinfo.value.code == "VALIDATION_ERROR"

    def test_fewer_than_two_assessed_routes_raises(self):
        request = make_route_request()
        assessed = scored_and_assessed(request, route_index=0)
        make_route(request, route_index=1)

        with pytest.raises(InsufficientRiskDataError):
            rank_routes(assessed)

    def test_lazy_scoring_recomputes_from_assessments(self):
        request = make_route_request()
        first = scored_and_assessed(request, route_index=0)
        second = scored_and_assessed(request, avg=2.0, route_index=1)
        RouteScore.objects.filter(route=second).delete()

        ranked, recommended_id = rank_routes(first)

        recomputed = dict(ranked)[second]
        # The assessment says "low" over 25 miles, so the recomputed average
        # is 1.0 - and the lighter-typed route wins.
        assert recomputed.average_risk_score == Decimal("1.000")
        assert recommended_id == second.id
