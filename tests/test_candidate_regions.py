"""DEM-backed smoke tests at representative lunar south-pole landing sites.

Coordinates are representative candidate landing sites from Table A1 of
Wueller et al. (2026), rather than region centroids or exhaustive area tests.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from candidate_sites import CANDIDATE_SITES as PUBLISHED_CANDIDATE_SITES
from ephemeris_engine import compute_site_ephemeris, compute_sun_ephemerides
from horizon_analysis import (
    DEFAULT_DEM_LABEL,
    LunarDEM,
    calculate_horizon_profile,
    check_solar_visibility,
)


# Current Artemis III candidate-region set, with one published representative
# landing point per region (Table A1; coordinates are planetocentric degrees).
CANDIDATE_SITES = tuple(
    pytest.param(
        site["region"],
        site["site_id"],
        site["latitude_deg"],
        site["longitude_deg"],
        id=site["site_id"].lower().replace("_", "-"),
    )
    for site in PUBLISHED_CANDIDATE_SITES
)
REFERENCE_SITE = (-86.5680, -21.4730)  # HW04, representative Artemis candidate site


@pytest.fixture(scope="module")
def candidate_dem() -> LunarDEM:
    if not DEFAULT_DEM_LABEL.is_file():
        pytest.skip(f"LOLA PDS label not installed: {DEFAULT_DEM_LABEL}")
    try:
        return LunarDEM.from_pds3(DEFAULT_DEM_LABEL)
    except FileNotFoundError as error:
        pytest.skip(str(error))


@pytest.mark.parametrize("region,site_id,latitude,longitude", CANDIDATE_SITES)
def test_candidate_site_has_dem_horizon_and_solar_result(
    candidate_dem: LunarDEM,
    region: str,
    site_id: str,
    latitude: float,
    longitude: float,
) -> None:
    elevation_m = candidate_dem.elevation_at(latitude, longitude)
    assert math.isfinite(elevation_m), f"{region}/{site_id}: DEM elevation is not finite"

    profile = calculate_horizon_profile(
        candidate_dem,
        latitude,
        longitude,
        azimuth_step_deg=1.0,
        max_distance_m=150_000.0,
        ray_step_m=160.0,
    )
    assert len(profile.azimuths_deg) == 360, f"{region}/{site_id}: expected 360 azimuths"
    assert all(math.isfinite(value) for value in profile.horizon_elevation_deg), (
        f"{region}/{site_id}: horizon contains a non-finite angle"
    )
    assert all(0.0 <= value <= 1.0 for value in profile.coverage_fraction), (
        f"{region}/{site_id}: invalid DEM ray coverage"
    )
    assert max(profile.coverage_fraction) > 0.0, f"{region}/{site_id}: no DEM ray coverage"

    ephemeris = compute_site_ephemeris(
        latitude,
        longitude,
        elevation_m,
        "2026-11-14T12:00:00Z",
    )
    sun = ephemeris["sun"]
    visibility = check_solar_visibility(
        profile,
        sun["azimuth_deg"],
        sun["elevation_deg"],
    )
    assert visibility["visibility"] in {"sunlit", "shadowed", "unknown"}, (
        f"{region}/{site_id}: unexpected visibility state {visibility['visibility']!r}"
    )
    assert math.isfinite(visibility["terrain_horizon_deg"]), (
        f"{region}/{site_id}: solar-direction horizon is not finite"
    )
    if sun["elevation_deg"] <= 0.0 or sun["elevation_deg"] <= visibility["terrain_horizon_deg"]:
        expected_visibility = "shadowed"
    elif visibility["dem_coverage_fraction"] >= 0.9:
        expected_visibility = "sunlit"
    else:
        expected_visibility = "unknown"
    assert visibility["visibility"] == expected_visibility, (
        f"{region}/{site_id}: solar elevation, horizon and coverage imply "
        f"{expected_visibility}, got {visibility['visibility']}"
    )


def test_vectorized_sun_ephemeris_matches_scalar_reference(
    candidate_dem: LunarDEM,
) -> None:
    latitude, longitude = REFERENCE_SITE
    elevation_m = candidate_dem.elevation_at(latitude, longitude)
    timestamps = [
        "2026-11-14T00:00:00Z",
        "2026-11-14T12:00:00Z",
        "2026-11-15T00:00:00Z",
    ]

    batched = compute_sun_ephemerides(latitude, longitude, elevation_m, timestamps)
    scalar = [
        compute_site_ephemeris(latitude, longitude, elevation_m, timestamp)["sun"]
        for timestamp in timestamps
    ]

    assert len(batched) == len(scalar)
    for actual, expected in zip(batched, scalar):
        assert actual["azimuth_deg"] == pytest.approx(expected["azimuth_deg"], abs=1e-5)
        assert actual["elevation_deg"] == pytest.approx(expected["elevation_deg"], abs=1e-5)
        assert actual["distance_km"] == pytest.approx(expected["distance_km"], abs=1e-5)
