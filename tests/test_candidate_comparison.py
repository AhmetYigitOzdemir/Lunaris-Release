from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from main import (
    CandidateComparisonRequest,
    LandingSafetyRequest,
    PSRNodalCycleRequest,
    candidate_sites,
    compare_candidate_sites,
    landing_safety,
    psr_cycle_screen,
)
from horizon_analysis import HorizonProfile, LUNAR_NODAL_CYCLE_DAYS


def _profile() -> HorizonProfile:
    azimuths = tuple(float(value) for value in range(360))
    return HorizonProfile(
        latitude_deg=-86.0,
        longitude_deg=20.0,
        site_elevation_m=100.0,
        azimuth_step_deg=1.0,
        max_distance_m=150_000.0,
        ray_step_m=40.0,
        dem_resolution_m=40.0,
        dem_source="synthetic test DEM",
        azimuths_deg=azimuths,
        horizon_elevation_deg=(0.0,) * 360,
        horizon_distance_m=(0.0,) * 360,
        coverage_fraction=(1.0,) * 360,
    )


def test_candidate_catalog_contains_nine_regions() -> None:
    result = candidate_sites()
    assert result["success"] is True
    assert len(result["regions"]) == 9
    assert len({item["site_id"] for item in result["regions"]}) == 9
    assert all(0.0 <= item["longitude_deg"] < 360.0 for item in result["regions"])


def test_candidate_comparison_uses_one_shared_window_for_all_regions() -> None:
    service = Mock()
    service.horizon_profile.return_value = _profile()
    ephemeris = {
        "sun": {"azimuth_deg": 90.0, "elevation_deg": 5.0},
        "earth": {"azimuth_deg": 180.0, "elevation_deg": 10.0},
    }
    samples = [
        {"is_sunlit": True},
        {"is_sunlit": False},
        {"is_sunlit": True},
        {"is_sunlit": True},
    ]
    illumination = {
        "sunlit_duration_hours": 18.0,
        "sunlit_percentage": 75.0,
        "known_illumination_coverage_percentage": 100.0,
        "samples": samples,
    }

    with (
        patch("main._horizon_service", return_value=service),
        patch("main.compute_site_ephemeris", return_value=ephemeris),
        patch("main.analyze_sunlight_period", return_value=illumination) as analyze,
        patch(
            "main.find_sun_transitions",
            return_value={
                "transition_count": 1,
                "transitions": [{"timestamp_utc": "2026-11-14T13:47:40Z", "type": "sunrise"}],
            },
        ) as transitions,
        patch(
            "main.calculate_landing_safety_patch",
            return_value={
                "slope_below_5_deg_percentage": 75.0,
                "slope_below_8_deg_percentage": 92.0,
                "coverage_percentage": 100.0,
            },
        ),
        patch(
            "main.validate_dem_coverage",
            return_value={
                "status": "available",
                "coverage_percentage": 100.0,
                "elevation_m": 100.0,
                "error_message": None,
            },
        ),
    ):
        result = compare_candidate_sites(
            CandidateComparisonRequest(
                timestamp="2026-11-14T00:00:00Z",
                duration_days=1.0,
                step_minutes=360.0,
            )
        )

    assert result["success"] is True
    assert len(result["results"]) == 9
    assert {item["sunlit_percentage"] for item in result["results"]} == {75.0}
    assert all(item["longest_sunlit_run_hours"] == 12.0 for item in result["results"])
    assert all(item["transition_count"] == 1 for item in result["results"])
    assert all(item["first_sunrise_utc"] == "2026-11-14T13:47:40Z" for item in result["results"])
    assert {item["slope_below_8_deg_percentage"] for item in result["results"]} == {92.0}
    assert analyze.call_count == 9
    assert all(call.kwargs["start_time"] == datetime(2026, 11, 14, tzinfo=UTC) for call in analyze.call_args_list)


def test_landing_safety_endpoint_labels_dem_and_returns_grid() -> None:
    service = Mock()
    service.dem.source = "test DEM"
    safety_result = {
        "slope_deg": [[0.0, 9.0], [None, 4.0]],
        "slope_below_5_deg_percentage": 50.0,
        "slope_below_8_deg_percentage": 66.0,
        "coverage_percentage": 75.0,
    }
    with (
        patch("main._horizon_service", return_value=service),
        patch("main.calculate_landing_safety_patch", return_value=safety_result),
    ):
        result = landing_safety(
            LandingSafetyRequest(lat=-86.5, lon=22.0, radius_m=1000.0)
        )

    assert result["success"] is True
    assert result["dem_source"] == "test DEM"
    assert result["slope_deg"] == safety_result["slope_deg"]


@pytest.mark.parametrize(
    ("sunlit_seconds", "coverage", "expected"),
    [
        (0.0, 100.0, "candidate"),
        (3600.0, 100.0, "not_candidate"),
        (0.0, 80.0, "unknown"),
    ],
)
def test_nodal_cycle_screen_reports_quality_and_never_claims_permanent_shadow(
    sunlit_seconds: float,
    coverage: float,
    expected: str,
) -> None:
    service = Mock()
    service.horizon_profile.return_value = _profile()
    analysis = {
        "sunlit_duration_seconds": sunlit_seconds,
        "sunlit_duration_hours": sunlit_seconds / 3600.0,
        "sunlit_percentage": 0.0 if sunlit_seconds == 0 else 0.01,
        "known_illumination_coverage_percentage": coverage,
        "sample_count": 163_048,
        "start_time_utc": "2026-11-14T00:00:00Z",
        "end_time_utc": "2045-06-30T15:00:00Z",
        "horizon": {"max_distance_m": 150000.0},
    }
    with (
        patch("main._horizon_service", return_value=service),
        patch("main.analyze_sunlight_period", return_value=analysis) as analyze,
    ):
        result = psr_cycle_screen(
            PSRNodalCycleRequest(
                lat=-86.0,
                lon=20.0,
                elevation=100.0,
                timestamp="2026-11-14T00:00:00Z",
            )
        )

    assert result["classification"] == expected
    assert result["is_permanently_shadowed"] is None
    assert result["cycle_years"] == 18.6
    assert result["analysis_quality"]["coverage"] == (
        "complete" if coverage >= 99.9 else "partial"
    )
    call = analyze.call_args.kwargs
    assert (call["end_time"] - call["start_time"]).total_seconds() == pytest.approx(
        LUNAR_NODAL_CYCLE_DAYS * 86400.0
    )
    assert call["max_samples"] == 200_000
    assert call["include_samples"] is False
