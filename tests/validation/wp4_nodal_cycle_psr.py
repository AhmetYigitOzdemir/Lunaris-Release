"""Phase 3 WP4: 18.6-year lunar nodal-cycle PSR screen.

Staged, computationally bounded analysis:
  * One horizon profile per site (computed once).
  * One 18.6-year (one lunar nodal precession cycle) illumination screen at
    60-minute sampling using the vectorized ephemeris + terrain horizon.
  * Reports sunlight fraction, known-illumination coverage, longest continuous
    shadow run, and sample counts (sunlit/shadowed/unknown).

This is a POINT analysis (one surface coordinate + its terrain horizon), not a
regional PSR map. Results are a pre-screen, not a permanent-shadow
certification: short sunlit intervals below the 60-minute sampling interval
can be missed, so a "dark" result does not prove permanent shadow.

Read-only: creates result JSON under tests/validation/; no production logic
modified.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from horizon_analysis import (
    HorizonAnalysisService,
    analyze_sunlight_period,
    LUNAR_NODAL_CYCLE_DAYS,
)
from ephemeris_engine import init_ephemeris, EphemerisError

RESULTS_PATH = Path(__file__).resolve().parent / "wp4_nodal_cycle_psr_results.json"

# Known south-polar PSR candidate locations (documented in lunar science
# literature as containing permanently shadowed regions). These are used as
# independent reference context, not as ground truth computed here.
SITES = [
    {"name": "Shackleton (representative)", "lat": -89.9, "lon": 0.0,
     "elevation_m": 0.0,
     "context": "near-polar crater; documented PSR candidate"},
    {"name": "HW04 (Haworth)", "lat": -86.568, "lon": -21.473,
     "elevation_m": 0.0,
     "context": "Haworth crater; documented PSR candidate"},
    {"name": "PCB01 (Peak near Cabeus B)", "lat": -83.763, "lon": -69.983,
     "elevation_m": 0.0,
     "context": "off-pole comparison site; expected to receive sunlight"},
]

START_UTC = "2026-11-14T00:00:00Z"
STEP_MIN = 60


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def longest_run(samples, start, step_minutes):
    """Longest consecutive run of is_sunlit == False (shadow) in hours."""
    step_s = step_minutes * 60.0
    total = (samples[-1][0] - samples[0][0]).total_seconds() if samples else 0.0
    longest = cur = 0.0
    for t, sunlit in samples:
        if sunlit is False:
            cur += step_s
            longest = max(longest, cur)
        else:
            cur = 0.0
    return longest / 3600.0, total / 3600.0


def main() -> int:
    try:
        init_ephemeris(kernel_dir=str(ROOT / "data" / "Ephemeris"))
    except EphemerisError as exc:
        print("FATAL: ephemeris engine unavailable: %s" % exc)
        return 2

    svc = HorizonAnalysisService()
    start = datetime.fromisoformat(START_UTC.replace("Z", "+00:00"))
    end = start + timedelta(days=LUNAR_NODAL_CYCLE_DAYS)
    results = {
        "start_utc": START_UTC,
        "end_utc": end.isoformat().replace("+00:00", "Z"),
        "nodal_cycle_days": LUNAR_NODAL_CYCLE_DAYS,
        "step_minutes": STEP_MIN,
        "sites": [],
    }
    print("Window: %s to %s (%.1f days = 1 nodal cycle)" % (
        START_UTC, iso(end), LUNAR_NODAL_CYCLE_DAYS))

    for site in SITES:
        site_result = {
            "name": site["name"], "lat": site["lat"], "lon": site["lon"],
            "elevation_m": site["elevation_m"], "context": site["context"],
        }
        print("\n=== %s ===" % site["name"])
        t0 = time.time()
        profile = svc.horizon_profile(
            site["lat"], site["lon"],
            azimuth_step_deg=1.0, max_distance_m=200000.0,
        )
        print("  horizon profile: %.2fs" % (time.time() - t0))

        t1 = time.time()
        out = analyze_sunlight_period(
            profile, start_time=START_UTC, end_time=iso(end),
            step_minutes=float(STEP_MIN),
        )
        compute_s = time.time() - t1

        # Replay samples to get longest shadow run and per-state counts.
        samples = []
        sunlit_n = shadow_n = unknown_n = 0
        for row in out["samples"]:
            t = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            s = row["is_sunlit"]
            samples.append((t, s))
            if s is True:
                sunlit_n += 1
            elif s is False:
                shadow_n += 1
            else:
                unknown_n += 1
        longest_shadow_h, window_h = longest_run(samples, start, STEP_MIN)

        site_result.update({
            "horizon_profile_source": profile.dem_source,
            "horizon_resolution_m": profile.dem_resolution_m,
            "sample_count": out["sample_count"],
            "compute_seconds": round(compute_s, 2),
            "window_hours": round(window_h, 1),
            "sunlit_duration_hours": round(out["sunlit_duration_hours"], 4),
            "sunlit_percentage": out["sunlit_percentage"],
            "sunlit_percentage_of_known": out["sunlit_percentage_of_known_time"],
            "known_illumination_coverage_percentage": out[
                "known_illumination_coverage_percentage"],
            "sunlit_samples": sunlit_n,
            "shadowed_samples": shadow_n,
            "unknown_samples": unknown_n,
            "longest_continuous_shadow_hours": round(longest_shadow_h, 2),
            "fraction_of_window_shadowed": round(
                shadow_n / out["sample_count"] * 100.0, 4
            ) if out["sample_count"] else None,
        })
        print("  samples=%d sunlit=%d shadowed=%d unknown=%d" % (
            out["sample_count"], sunlit_n, shadow_n, unknown_n))
        print("  sunlit h=%.2f (%.2f%% of known), known coverage=%.2f%%" % (
            out["sunlit_duration_hours"],
            (out["sunlit_percentage_of_known_time"] or 0.0),
            out["known_illumination_coverage_percentage"]))
        print("  longest continuous shadow=%.2f h; shadowed fraction=%.2f%%" % (
            longest_shadow_h, site_result["fraction_of_window_shadowed"]))
        results["sites"].append(site_result)

    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nResults written to", RESULTS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
