from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ephemeris_engine import (
    EphemerisError,
    get_engine_status,
    get_kernel_coverage,
    init_ephemeris,
)
from horizon_analysis import (
    ephemeris_provenance,
    neighborhood_provenance,
    spatial_provenance,
    temporal_provenance,
    terrain_provenance,
)
from main import compare_candidate_sites, CandidateComparisonRequest


def test_moon_me_ephemeris_at_wp4_endpoints() -> None:
    init_ephemeris(kernel_dir="data/Ephemeris", force=True)
    for timestamp in ("2026-11-14T00:00:00Z", "2045-06-20T15:36:00Z"):
        result = __import__("ephemeris_engine").compute_site_ephemeris(
            -89.9, 0.0, 0.0, timestamp
        )
        assert result["frame"] == "MOON_ME"
        assert result["sun"]["azimuth_deg"] is not None


def test_kernel_coverage_contains_wp4_interval() -> None:
    init_ephemeris(kernel_dir="data/Ephemeris", force=True)
    coverage = get_kernel_coverage()
    assert coverage["ready"] is True
    assert coverage["spk_intervals"]
    start = coverage["spk_intervals"][0]["start_utc"]
    end = coverage["spk_intervals"][0]["end_utc"]
    assert start <= "2026-11-14T00:00:00Z"
    assert end >= "2045-06-20T15:36:00Z"


def test_missing_kernel_directory_raises() -> None:
    with pytest.raises(EphemerisError):
        init_ephemeris(kernel_dir="data/does-not-exist", force=True)


def test_empty_terrain_metadata_is_explicit() -> None:
    result = terrain_provenance()
    assert result["dem_source"] is None
    assert result["configured_resolution_m"] is None


def test_ephemeris_provenance_not_ready_shape() -> None:
    # get_engine_status may already be ready in the process; only check shape.
    result = ephemeris_provenance()
    assert "ready" in result
    assert "loaded_kernel_count" in result
    assert "kernel_coverage" in result


def test_kernel_coverage_query_failure_is_not_crash() -> None:
    import spiceypy as spice

    init_ephemeris(kernel_dir="data/Ephemeris", force=True)
    original = spice.spkcov

    from spiceypy.utils.exceptions import SpiceyError

    def failing_spkcov(*args, **kwargs):
        raise SpiceyError("simulated coverage query failure")

    spice.spkcov = failing_spkcov
    try:
        coverage = get_kernel_coverage()
    finally:
        spice.spkcov = original
    assert coverage["spk_intervals"] == []


def test_candidate_comparison_provenance_inputs() -> None:
    result = compare_candidate_sites(
        CandidateComparisonRequest(
            timestamp="2026-11-14T00:00:00Z",
            duration_days=1.0,
            step_minutes=60.0,
        )
    )
    assert result["success"] is True
    entry = result["results"][0]
    if entry["provenance"] is not None:
        temporal = entry["provenance"]["temporal"]
        assert temporal["start_time_utc"] == "2026-11-14T00:00:00Z"
        assert temporal["sampling_interval_minutes"] == 60.0
        assert "spatial" not in entry["provenance"]


def test_spatial_provenance_serializes() -> None:
    result = spatial_provenance(-89.9, 0.0, radius_m=500.0, step_m=250.0, sample_count=25, valid_count=24)
    assert json.dumps(result)
    assert result["valid_sample_count"] == 24
    assert "projection-plane" in result["distance_convention"]

def test_coverage_status_distinguishes_query_failure() -> None:
    import spiceypy as spice
    from spiceypy.utils.exceptions import SpiceyError

    init_ephemeris(kernel_dir="data/Ephemeris", force=True)
    original = spice.spkcov

    def failing_spkcov(*args, **kwargs):
        raise SpiceyError("simulated coverage query failure")

    spice.spkcov = failing_spkcov
    try:
        coverage = get_kernel_coverage()
    finally:
        spice.spkcov = original

    assert coverage["spk_coverage_status"] == "query_failed"
    assert coverage["spk_query_error"] is not None
    assert coverage["spk_intervals"] == []
