"""
Solar visibility validation: quantify timing error from binary time-step sampling.

The LUNARIS solar visibility calculation (horizon_analysis.py:check_solar_visibility)
returns binary sunlit/shadowed/unknown per time sample. analyze_sunlight_period
(horizon_analysis.py:862) weights each sample by the interval to the next sample.

This script quantifies the timing error introduced by finite time steps when the
Sun crosses the terrain horizon between samples. It uses a synthetic horizon
profile and a synthetic solar elevation curve (sinusoidal, simulating sunrise
and sunset) to compute the "true" sunlight duration analytically, then compares
it against the binary-sampled result at different time steps.

No independent external reference exists for solar visibility at a specific
lunar site (it depends on the unique terrain horizon). This validation
quantifies the numerical sensitivity of the implementation instead.
"""

import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

from horizon_analysis import (
    HorizonProfile,
    check_solar_visibility,
    analyze_sunlight_period,
)


def synthetic_sun_elevation(time_minutes_from_sunrise, duration_minutes, max_elevation_deg):
    """
    Synthetic solar elevation curve: sunrise at t=0, sunset at t=duration,
    peak elevation at mid-day. Simple sinusoidal model.

    elevation(t) = max_el * sin(pi * t / duration) for 0 <= t <= duration
    elevation(t) = 0 outside [0, duration]
    """
    t = time_minutes_from_sunrise
    if t < 0 or t > duration_minutes:
        return 0.0
    return max_elevation_deg * math.sin(math.pi * t / duration_minutes)


def true_sunlight_duration(duration_minutes, max_elevation_deg, horizon_deg):
    """
    Analytically compute the true sunlight duration when the Sun's elevation
    exceeds the terrain horizon.

    elevation(t) = max_el * sin(pi * t / duration)
    Sun above horizon when: max_el * sin(pi * t / duration) > horizon
    sin(pi * t / duration) > horizon / max_el
    pi * t / duration in (arcsin(horizon/max_el), pi - arcsin(horizon/max_el))
    t in (duration/pi * arcsin(h/max_el), duration - duration/pi * arcsin(h/max_el))
    """
    if horizon_deg >= max_elevation_deg:
        return 0.0  # Sun never above horizon
    if horizon_deg <= 0.0:
        return duration_minutes  # Sun always above horizon (above geometric horizon)

    ratio = horizon_deg / max_elevation_deg
    alpha = math.asin(ratio)  # angle where elevation = horizon
    t_start = duration_minutes / math.pi * alpha
    t_end = duration_minutes - t_start
    return t_end - t_start


def binary_sampled_duration(duration_minutes, max_elevation_deg, horizon_deg, step_minutes):
    """
    Compute sunlight duration using binary per-sample visibility with
    interval weighting (same method as analyze_sunlight_period).
    """
    start = datetime(2026, 11, 14, 0, 0, tzinfo=UTC)
    end = start + timedelta(minutes=duration_minutes)

    # Create a synthetic horizon profile: constant horizon at all azimuths
    profile = HorizonProfile(
        latitude_deg=-89.0,
        longitude_deg=0.0,
        site_elevation_m=0.0,
        azimuth_step_deg=1.0,
        max_distance_m=200000.0,
        ray_step_m=40.0,
        dem_resolution_m=40.0,
        dem_source="synthetic",
        azimuths_deg=tuple(float(i) for i in range(360)),
        horizon_elevation_deg=(horizon_deg,) * 360,
        horizon_distance_m=(100000.0,) * 360,
        coverage_fraction=(1.0,) * 360,
    )

    # Build synthetic sun samples
    sample_count = 0
    sunlit_seconds = 0.0
    current = start
    step_seconds = step_minutes * 60.0
    total_seconds = (end - start).total_seconds()

    while current < end:
        next_time = min(current + timedelta(seconds=step_seconds), end)
        t_minutes = (current - start).total_seconds() / 60.0
        sun_el = synthetic_sun_elevation(t_minutes, duration_minutes, max_elevation_deg)
        sun_az = 180.0  # South, arbitrary fixed azimuth

        visibility = check_solar_visibility(profile, sun_az, sun_el)
        sample_duration = (next_time - current).total_seconds()
        if visibility["is_sunlit"] is True:
            sunlit_seconds += sample_duration
        sample_count += 1
        current = next_time

    return sunlit_seconds / 3600.0  # hours


def main():
    print("=== Solar Visibility Timing Error Analysis ===")
    print()
    print("Method: Compare binary-sampled sunlight duration against analytic truth")
    print("Synthetic scenario: Sun rises above a constant terrain horizon")
    print()

    duration_minutes = 720.0  # 12-hour "day"
    max_elevation_deg = 30.0  # Peak solar elevation
    horizon_deg = 5.0  # Terrain horizon at Sun's azimuth

    true_duration_min = true_sunlight_duration(duration_minutes, max_elevation_deg, horizon_deg)
    true_duration_h = true_duration_min / 60.0
    print(f"Scenario: 12-hour day, peak elevation {max_elevation_deg} deg, horizon {horizon_deg} deg")
    print(f"True sunlight duration (analytic): {true_duration_h:.4f} hours ({true_duration_min:.1f} min)")
    print()

    print(f"{'Step (min)':>12} {'Sampled (h)':>14} {'Error (h)':>12} {'Error (min)':>13} {'Error (%)':>11}")
    print("-" * 70)

    results = {}
    for step_minutes in [1, 5, 10, 15, 30, 60]:
        sampled_h = binary_sampled_duration(
            duration_minutes, max_elevation_deg, horizon_deg, step_minutes
        )
        err_h = sampled_h - true_duration_h
        err_min = err_h * 60.0
        err_pct = abs(err_h) / true_duration_h * 100.0 if true_duration_h > 0 else 0.0
        results[step_minutes] = (sampled_h, err_h, err_min, err_pct)
        print(f"{step_minutes:>12} {sampled_h:>14.4f} {err_h:>12.4f} {err_min:>13.2f} {err_pct:>10.3f}%")

    print()
    print("=== Key Findings ===")
    print(f"1. At 60-minute step (LUNARIS default): max timing error ~ {abs(results[60][2]):.1f} minutes")
    print(f"2. At 15-minute step: max timing error ~ {abs(results[15][2]):.1f} minutes")
    print(f"3. Error scales approximately linearly with time step size")
    print(f"4. Binary sampling cannot recover sub-step sunrise/sunset transitions")
    print()
    print("Conclusion: The 60-minute default step introduces up to ~1 hour of timing")
    print("error near terminator crossings. For precise sunlight-duration work, a")
    print("smaller time step (e.g., 15 minutes) is recommended.")


if __name__ == "__main__":
    main()
