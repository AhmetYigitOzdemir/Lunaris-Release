import sys, json, time
from pathlib import Path
from datetime import datetime, timedelta
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from horizon_analysis import HorizonAnalysisService, analyze_sunlight_period, find_sun_transitions, _sun_clearance_deg
from ephemeris_engine import init_ephemeris

init_ephemeris(kernel_dir=str(ROOT / "data" / "Ephemeris"))

svc = HorizonAnalysisService()
SITES = [
    ("Shackleton (representative)", -89.9, 0.0),
    ("MMA04 (Malapert Massif)", -86.31, -0.459),
    ("PCB01 (Peak near Cabeus B)", -83.763, -69.983),
]
START = "2026-11-14T00:00:00Z"
END = "2026-11-17T00:00:00Z"
STEPS = [60, 30, 15, 5, 1]
RESULTS_PATH = Path(__file__).resolve().parent / "wp3_independent_recalculation_results.json"

out = {"start_utc": START, "end_utc": END, "sites": []}
for name, lat, lon in SITES:
    prof = svc.horizon_profile(lat, lon, azimuth_step_deg=1.0, max_distance_m=200000.0)
    hi = find_sun_transitions(
        prof, lat, lon, 0.0, START, END,
        step_minutes=60.0, reference="terrain",
        tol_seconds=0.1, elev_tol_deg=1e-6, max_iter=200,
    )
    hi_ts = [
        (datetime.fromisoformat(t["timestamp_utc"].replace("Z", "+00:00")), t["type"])
        for t in hi["transitions"]
    ]
    c0 = _sun_clearance_deg(
        datetime.fromisoformat(START.replace("Z", "+00:00")), prof, lat, lon, 0.0, "terrain"
    )
    sunlit_state = bool(c0 > 0)
    boundaries = [datetime.fromisoformat(START.replace("Z", "+00:00"))] + [t[0] for t in hi_ts] + [datetime.fromisoformat(END.replace("Z", "+00:00"))]
    true_sunlit = 0.0
    state = sunlit_state
    for i in range(len(boundaries) - 1):
        if state:
            true_sunlit += (boundaries[i + 1] - boundaries[i]).total_seconds()
        state = not state

    steps_data = {}
    for step in STEPS:
        o = analyze_sunlight_period(prof, start_time=START, end_time=END, step_minutes=float(step))
        tr_def = find_sun_transitions(
            prof, lat, lon, 0.0, START, END, step_minutes=float(step), reference="terrain"
        )
        tr_tight = find_sun_transitions(
            prof, lat, lon, 0.0, START, END, step_minutes=float(step), reference="terrain",
            tol_seconds=0.1, elev_tol_deg=1e-6, max_iter=200,
        )
        def_ts = tr_def["transitions"][0]["timestamp_utc"] if tr_def["transitions"] else None
        tight_ts = tr_tight["transitions"][0]["timestamp_utc"] if tr_tight["transitions"] else None
        steps_data[str(step)] = {
            "sample_count": o["sample_count"],
            "sunlit_duration_hours": round(o["sunlit_duration_seconds"] / 3600.0, 6),
            "sunlit_duration_seconds": o["sunlit_duration_seconds"],
            "known_coverage_percentage": o["known_illumination_coverage_percentage"],
            "transition_count": tr_def["transition_count"],
            "transition_default_timestamp": def_ts,
            "transition_tight_timestamp": tight_ts,
            "duration_error_vs_true_seconds": round(o["sunlit_duration_seconds"] - true_sunlit, 3),
        }
        if def_ts and hi_ts:
            tt = datetime.fromisoformat(def_ts.replace("Z", "+00:00"))
            rt = hi_ts[0][0]
            steps_data[str(step)]["transition_time_error_default_seconds"] = abs((tt - rt).total_seconds())
        else:
            steps_data[str(step)]["transition_time_error_default_seconds"] = None
        if tight_ts and hi_ts:
            tt = datetime.fromisoformat(tight_ts.replace("Z", "+00:00"))
            rt = hi_ts[0][0]
            steps_data[str(step)]["transition_time_error_tight_seconds"] = abs((tt - rt).total_seconds())
        else:
            steps_data[str(step)]["transition_time_error_tight_seconds"] = None

    out["sites"].append({
        "name": name,
        "lat": lat,
        "lon": lon,
        "initial_clearance_deg": round(float(c0), 6),
        "initial_state": "sunlit" if sunlit_state else "shadowed",
        "high_accuracy_transition_count": len(hi_ts),
        "high_accuracy_transitions": [
            {"timestamp_utc": t[0].isoformat().replace("+00:00", "Z"), "type": t[1]} for t in hi_ts
        ],
        "true_sunlit_duration_seconds": round(true_sunlit, 3),
        "true_sunlit_duration_hours": round(true_sunlit / 3600.0, 6),
        "steps": steps_data,
    })

RESULTS_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
print("Wrote", RESULTS_PATH)
