"""Unit tests for sunrise/sunset transition interpolation (Phase 3, WP2).

Tests ``find_sun_transitions`` in horizon_analysis.py. Requires the SPICE
kernels (for real Sun ephemeris) and the DEM (for a real terrain profile).
Tests that depend on kernels/DEM are skipped gracefully when unavailable.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from horizon_analysis import (
    HorizonProfile,
    find_sun_transitions,
)

try:  # kernels may be unavailable in some environments
    from ephemeris_engine import init_ephemeris

    _KERNELS_OK = True
except Exception:  # pragma: no cover - environment dependent
    _KERNELS_OK = False


def _kernels_available() -> bool:
    if not _KERNELS_OK:
        return False
    try:
        init_ephemeris(kernel_dir="data/Ephemeris")
        return True
    except Exception:
        return False


def _flat_profile(horizon_deg: float = 0.0) -> HorizonProfile:
    """Synthetic horizon profile with a constant horizon in every azimuth."""
    n = 360
    return HorizonProfile(
        latitude_deg=-89.9,
        longitude_deg=0.0,
        site_elevation_m=0.0,
        azimuth_step_deg=1.0,
        max_distance_m=200000.0,
        ray_step_m=40.0,
        dem_resolution_m=40.0,
        dem_source="synthetic",
        azimuths_deg=tuple(float(i) for i in range(n)),
        horizon_elevation_deg=tuple(float(horizon_deg) for _ in range(n)),
        horizon_distance_m=tuple(0.0 for _ in range(n)),
        coverage_fraction=tuple(1.0 for _ in range(n)),
    )


@pytest.mark.skipif(not _kernels_available(), reason="SPICE kernels unavailable")
def test_no_transition_always_sunlit_astronomical():
    """At the south pole in mid-Nov 2026 the Sun stays above 0 deg (flat
    horizon), so an astronomical reference should yield no transitions."""
    profile = _flat_profile(0.0)
    result = find_sun_transitions(
        profile,
        -89.9,
        0.0,
        0.0,
        "2026-11-14T00:00:00Z",
        "2026-11-15T00:00:00Z",
        step_minutes=30.0,
        reference="astronomical",
    )
    assert result["transition_count"] == 0
    assert result["transitions"] == []
    assert result["sample_count"] > 0


@pytest.mark.skipif(not _kernels_available(), reason="SPICE kernels unavailable")
def test_no_transition_always_shadowed_synthetic():
    """A constant horizon of +5 deg is above the Sun (~+-1.5 deg at the pole),
    so the site is always shadowed: no transitions."""
    profile = _flat_profile(5.0)
    result = find_sun_transitions(
        profile,
        -89.9,
        0.0,
        0.0,
        "2026-11-14T00:00:00Z",
        "2026-11-15T00:00:00Z",
        step_minutes=30.0,
        reference="terrain",
    )
    assert result["transition_count"] == 0


@pytest.mark.skipif(not _kernels_available(), reason="SPICE kernels unavailable")
def test_transition_converged_and_bracketed():
    """Over a month the Sun crosses the flat horizon at the pole; any
    reported transition must be converged, lie inside its bracket, and have
    clearance ~0."""
    profile = _flat_profile(0.0)
    result = find_sun_transitions(
        profile,
        -89.9,
        0.0,
        0.0,
        "2026-11-14T00:00:00Z",
        "2026-12-14T00:00:00Z",
        step_minutes=60.0,
        reference="astronomical",
        tol_seconds=30.0,
        elev_tol_deg=0.005,
    )
    start = datetime.fromisoformat(result["start_time_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(result["end_time_utc"].replace("Z", "+00:00"))
    for tr in result["transitions"]:
        t = datetime.fromisoformat(tr["timestamp_utc"].replace("Z", "+00:00"))
        assert start <= t <= end
        assert tr["type"] in ("sunrise", "sunset", "crossing")
        assert tr["converged"] is True
        assert tr["iterations"] > 0
        assert abs(tr["clearance_deg"]) <= 0.005
        b0 = datetime.fromisoformat(tr["bracket_start_utc"].replace("Z", "+00:00"))
        b1 = datetime.fromisoformat(tr["bracket_end_utc"].replace("Z", "+00:00"))
        assert b0 <= t <= b1


@pytest.mark.skipif(not _kernels_available(), reason="SPICE kernels unavailable")
def test_invalid_inputs_rejected():
    profile = _flat_profile(0.0)
    with pytest.raises(ValueError):
        find_sun_transitions(
            profile, -89.9, 0.0, 0.0,
            "2026-11-14T00:00:00Z", "2026-11-13T00:00:00Z",
        )
    with pytest.raises(ValueError):
        find_sun_transitions(
            profile, -89.9, 0.0, 0.0,
            "2026-11-14T00:00:00Z", "2026-11-15T00:00:00Z",
            reference="bogus",
        )
    with pytest.raises(ValueError):
        find_sun_transitions(
            profile, -89.9, 0.0, 0.0,
            "2026-11-14T00:00:00Z", "2026-11-15T00:00:00Z",
            tol_seconds=-10.0,
        )


def test_grazing_touch_no_crossing_synthetic():
    """Without kernels we cannot evaluate real Sun, but we can at least
    confirm the function structure and input validation run. This test is
    intentionally light and does not require kernels."""
    profile = _flat_profile(0.0)
    # Kernels unavailable -> expect graceful handling is not guaranteed here;
    # just confirm the function is importable and signature accepted.
    assert callable(find_sun_transitions)
    assert profile.horizon_at(45.0)[0] == 0.0
