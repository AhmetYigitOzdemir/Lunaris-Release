from __future__ import annotations

import math

from horizon_analysis import HorizonProfile, check_earth_los


def _profile(
    *,
    horizon: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0),
    coverage: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0),
) -> HorizonProfile:
    return HorizonProfile(
        latitude_deg=-89.0,
        longitude_deg=0.0,
        site_elevation_m=0.0,
        azimuth_step_deg=90.0,
        max_distance_m=1000.0,
        ray_step_m=40.0,
        dem_resolution_m=40.0,
        dem_source="synthetic",
        azimuths_deg=(0.0, 90.0, 180.0, 270.0),
        horizon_elevation_deg=horizon,
        horizon_distance_m=(0.0, 0.0, 0.0, 0.0),
        coverage_fraction=coverage,
    )


def test_earth_above_horizon_is_visible() -> None:
    result = check_earth_los(_profile(horizon=(0.0, 0.0, 0.0, 0.0)), 0.0, 5.0)

    assert result["earth_visible"] is True
    assert result["communication_status"] == "OPEN"
    assert result["earth_azimuth_deg"] == 0.0
    assert result["earth_elevation_deg"] == 5.0


def test_earth_blocked_by_terrain_is_blackout() -> None:
    result = check_earth_los(_profile(horizon=(10.0, 0.0, 0.0, 0.0)), 0.0, 5.0)

    assert result["earth_visible"] is False
    assert result["communication_status"] == "BLOCKED"


def test_invalid_earth_los_input_raises() -> None:
    try:
        check_earth_los(_profile(), float("nan"), 5.0)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for non-finite Earth azimuth")
