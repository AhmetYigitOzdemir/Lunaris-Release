from __future__ import annotations

import json
import math

import pytest

from horizon_analysis import (
    HorizonProfile,
    analyze_sunlight_period,
    ephemeris_provenance,
    find_sun_transitions,
    neighborhood_provenance,
    spatial_provenance,
    summarize_neighborhood_values,
    temporal_provenance,
    terrain_provenance,
)


def _flat_profile() -> HorizonProfile:
    return HorizonProfile(
        latitude_deg=-89.9,
        longitude_deg=0.0,
        site_elevation_m=0.0,
        azimuth_step_deg=1.0,
        max_distance_m=200000.0,
        ray_step_m=40.0,
        dem_resolution_m=40.0,
        dem_source="synthetic",
        azimuths_deg=tuple(float(i) for i in range(360)),
        horizon_elevation_deg=(0.0,) * 360,
        horizon_distance_m=(0.0,) * 360,
        coverage_fraction=(1.0,) * 360,
    )


def test_terrain_provenance_fields() -> None:
    profile = _flat_profile()
    result = terrain_provenance(profile=profile)
    assert result["dem_source"] == "synthetic"
    assert result["configured_resolution_m"] == 40.0
    assert result["reference_radius_m"] == 1737400.0
    assert "projection" in result


def test_temporal_provenance_round_trip() -> None:
    result = temporal_provenance("2026-11-14T00:00:00Z", "2026-11-17T00:00:00Z", 60.0, tol_seconds=1.0)
    assert result["start_time_utc"] == "2026-11-14T00:00:00Z"
    assert result["end_time_utc"] == "2026-11-17T00:00:00Z"
    assert result["sampling_interval_minutes"] == 60.0
    assert result["transition_tol_seconds"] == 1.0
    assert result["time_standard"] == "UTC"


def test_spatial_provenance_fields() -> None:
    result = spatial_provenance(-89.9, 0.0, radius_m=1000.0, step_m=500.0, sample_count=25, valid_count=25)
    assert result["sample_count"] == 25
    assert result["valid_sample_count"] == 25
    assert "projection-plane" in result["distance_convention"]
    assert "point sampling only" in result["coverage_claim"]


def test_neighborhood_provenance_json_serializable() -> None:
    result = neighborhood_provenance(-89.9, 0.0, radius_m=500.0, step_m=500.0, sample_count=9, valid_count=9)
    json.dumps(result)
    assert "spatial" in result
    assert result["spatial"]["center_latitude_deg"] == -89.9


def test_analyze_sunlight_period_has_provenance() -> None:
    profile = _flat_profile()
    result = analyze_sunlight_period(profile, start_time="2026-11-14T00:00:00Z", end_time="2026-11-14T01:00:00Z", step_minutes=60.0)
    assert "provenance" in result
    assert set(result["provenance"]).issuperset({"terrain", "ephemeris", "temporal", "software"})
    assert result["provenance"]["temporal"]["sampling_interval_minutes"] == 60.0


def test_ephemeris_provenance_loaded_kernels() -> None:
    result = ephemeris_provenance()
    if result["ready"]:
        assert result["loaded_kernel_count"] >= 1
        assert any("de440s" in name for name in result["loaded_kernels"])
        assert result["kernel_coverage"]["ready"] is True
    else:
        assert result["loaded_kernel_count"] == 0

import os
from pathlib import Path

try:
    from ephemeris_engine import init_ephemeris

    init_ephemeris(kernel_dir=str(Path("data/Ephemeris")))
    _KERNELS_OK = True
except Exception:
    _KERNELS_OK = False


@pytest.mark.skipif(not _KERNELS_OK, reason="SPICE kernels unavailable")
def test_find_sun_transitions_has_provenance() -> None:
    profile = _flat_profile()
    result = find_sun_transitions(
        profile,
        -89.9,
        0.0,
        0.0,
        "2026-11-14T00:00:00Z",
        "2026-11-14T01:00:00Z",
        step_minutes=30.0,
        reference="astronomical",
    )
    assert "provenance" in result
    assert result["provenance"]["temporal"]["transition_tol_seconds"] == 60.0
    assert result["provenance"]["temporal"]["reference_horizon"] == "astronomical"
