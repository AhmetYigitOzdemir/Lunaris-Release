"""Phase 3 WP3: Time-step convergence of sunlight-period illumination.

Compares analyze_sunlight_period (discrete sampling) and find_sun_transitions
(bracketed bisection) across time steps 60/30/15/5/1 min for representative
south-pole sites over a common window. Uses the same ephemeris source
(compute_site_ephemeris / compute_sun_ephemerides) and the same terrain
horizon profile for every step.

Read-only: creates result JSON under tests/validation/; no production
calculation logic is modified.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from horizon_analysis import HorizonAnalysisService, analyze_sunlight_period, find_sun_transitions
from ephemeris_engine import init_ephemeris, EphemerisError

RESULTS_PATH = Path(__file__).resolve().parent / "wp3_timestep_convergence_results.json"

SITES = [
    {"name": "Shackleton (representative)", "lat": -89.9, "lon": 0.0, "elevation_m": 0.0},
    {"name": "MMA04 (Malapert Massif)", "lat": -86.31, "lon": -0.459, "elevation_m": 0.0},
    {"name": "PCB01 (Peak near Cabeus B)", "lat": -83.763, "lon": -69.983, "elevation_m": 0.0},
]

STEPS_MIN = [60, 30, 15, 5, 1]
START_UTC = "2026-11-14T00:00:00Z"
END_UTC = "2026-11-17T00:00:00Z"  # 3 days, captures multiple transitions


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def main() -> int:
    try:
        init_ephemeris(kernel_dir=str(ROOT / "data" / "Ephemeris"))
    except EphemerisError as exc:
        print("FATAL: ephemeris engine unavailable: %s" % exc)
        return 2
    svc = HorizonAnalysisService()
    results = {"sites": [], "steps_min": STEPS_MIN,
               "start_utc": START_UTC, "end_utc": END_UTC}

    for site in SITES:
        site_result = {
            "name": site["name"], "lat": site["lat"], "lon": site["lon"],
            "elevation_m": site["elevation_m"],
            "steps": {},
        }
        print("=== %s ===" % site["name"])
        t0 = time.time()
        profile = svc.horizon_profile(
            site["lat"], site["lon"],
            azimuth_step_deg=1.0, max_distance_m=200000.0,
        )
        print("  horizon profile: %.2fs" % (time.time() - t0))

        # Finest step as reference for transitions.
        ref = analyze_sunlight_period(
            profile, start_time=START_UTC, end_time=END_UTC, step_minutes=1.0,
        )
        ref_trans = find_sun_transitions(
            profile, site["lat"], site["lon"], site["elevation_m"],
            START_UTC, END_UTC, step_minutes=10.0, reference="terrain",
        )

        for step in STEPS_MIN:
            t1 = time.time()
            out = analyze_sunlight_period(
                profile, start_time=START_UTC, end_time=END_UTC,
                step_minutes=float(step),
            )
            trans = find_sun_transitions(
                profile, site["lat"], site["lon"], site["elevation_m"],
                START_UTC, END_UTC, step_minutes=float(step), reference="terrain",
            )
            dur_s = out["sunlit_duration_seconds"]
            pct = out["sunlit_percentage"]
            site_result["steps"][str(step)] = {
                "sample_count": out["sample_count"],
                "sunlit_duration_hours": round(out["sunlit_duration_hours"], 4),
                "sunlit_percentage": pct,
                "known_illumination_coverage_percentage": out["known_illumination_coverage_percentage"],
                "compute_seconds": round(time.time() - t1, 3),
                "transition_count": trans["transition_count"],
                "transitions": trans["transitions"],
            }
            print("  step=%3d min: sunlit=%.4f h (%.1f%%), transitions=%d, %.3fs"
                  % (step, dur_s / 3600.0, (pct or 0.0), trans["transition_count"],
                     time.time() - t1))

        # Compare each coarser step to the 1-min reference.
        ref_dur = ref["sunlit_duration_seconds"]
        ref_transitions = ref_trans["transitions"]
        site_result["reference_1min"] = {
            "sunlit_duration_hours": round(ref_dur / 3600.0, 4),
            "sunlit_percentage": ref["sunlit_percentage"],
            "transition_count": ref_trans["transition_count"],
        }
        comps = []
        for step in STEPS_MIN:
            if step == 1:
                continue
            s = site_result["steps"][str(step)]
            dur_err_h = abs(s["sunlit_duration_hours"] - site_result["reference_1min"]["sunlit_duration_hours"])
            # Compare transition times to nearest reference transition.
            trans = s["transitions"]
            time_errs = []
            for tr in trans:
                tt = datetime.fromisoformat(tr["timestamp_utc"].replace("Z", "+00:00"))
                best = None
                for r in ref_transitions:
                    rt = datetime.fromisoformat(r["timestamp_utc"].replace("Z", "+00:00"))
                    d = abs((tt - rt).total_seconds())
                    if best is None or d < best:
                        best = d
                if best is not None:
                    time_errs.append(best)
            comps.append({
                "step": step,
                "sunlit_duration_error_hours": round(dur_err_h, 4),
                "sunlit_duration_error_seconds": round(dur_err_h * 3600.0, 2),
                "transition_count": s["transition_count"],
                "ref_transition_count": len(ref_transitions),
                "max_transition_time_error_seconds": round(max(time_errs), 2) if time_errs else None,
                "mean_transition_time_error_seconds": round(sum(time_errs) / len(time_errs), 2) if time_errs else None,
            })
        site_result["convergence_vs_1min"] = comps
        results["sites"].append(site_result)

    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nResults written to", RESULTS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
