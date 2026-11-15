import sys, json, time
from pathlib import Path
from datetime import datetime, timedelta
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from horizon_analysis import HorizonAnalysisService, analyze_sunlight_period, LUNAR_NODAL_CYCLE_DAYS
from ephemeris_engine import init_ephemeris

init_ephemeris(kernel_dir=str(ROOT / "data" / "Ephemeris"))

svc = HorizonAnalysisService()
SITES = [
    ("Shackleton (representative)", -89.9, 0.0),
    ("HW04 (Haworth)", -86.568, -21.473),
    ("PCB01 (Peak near Cabeus B)", -83.763, -69.983),
]
START = "2026-11-14T00:00:00Z"
end = datetime.fromisoformat(START.replace("Z", "+00:00")) + timedelta(days=LUNAR_NODAL_CYCLE_DAYS)
END = end.isoformat().replace("+00:00", "Z")
RESULTS_PATH = Path(__file__).resolve().parent / "wp4_independent_recalculation_results.json"

out = {
    "start_utc": START,
    "end_utc": END,
    "nodal_cycle_days": LUNAR_NODAL_CYCLE_DAYS,
    "step_minutes": 60,
    "sites": [],
}
for name, lat, lon in SITES:
    t0 = time.time()
    prof = svc.horizon_profile(lat, lon, azimuth_step_deg=1.0, max_distance_m=200000.0)
    o = analyze_sunlight_period(prof, start_time=START, end_time=END, step_minutes=60.0, include_samples=True)

    samples = o["samples"]
    dts = [datetime.fromisoformat(r["timestamp_utc"].replace("Z", "+00:00")) for r in samples]
    intervals = []
    total_s = 0.0
    for i, r in enumerate(samples):
        t0s = dts[i]
        t1s = dts[i + 1] if i + 1 < len(samples) else datetime.fromisoformat(END.replace("Z", "+00:00"))
        dur = (t1s - t0s).total_seconds()
        intervals.append((r, dur))
        total_s += dur

    sunlit_s = shadow_s = unknown_s = 0.0
    for r, dur in intervals:
        if r["is_sunlit"] is True:
            sunlit_s += dur
        elif r["is_sunlit"] is False:
            shadow_s += dur
        else:
            unknown_s += dur

    longest = 0.0
    longest_samples = 0
    cur = 0.0
    cur_samples = 0
    for r, dur in intervals:
        if r["is_sunlit"] is False:
            cur += dur
            cur_samples += 1
            if cur > longest:
                longest = cur
                longest_samples = cur_samples
        else:
            cur = 0.0
            cur_samples = 0

    sunlit_n = sum(1 for r in samples if r["is_sunlit"] is True)
    shadow_n = sum(1 for r in samples if r["is_sunlit"] is False)
    unknown_n = sum(1 for r in samples if r["is_sunlit"] is None)
    known_s = sunlit_s + shadow_s
    site = {
        "name": name,
        "lat": lat,
        "lon": lon,
        "horizon_profile_source": prof.dem_source,
        "horizon_resolution_m": prof.dem_resolution_m,
        "sample_count": len(samples),
        "window_hours": round(total_s / 3600.0, 3),
        "total_duration_seconds": round(total_s, 3),
        "sunlit_samples": sunlit_n,
        "shadowed_samples": shadow_n,
        "unknown_samples": unknown_n,
        "known_sample_count": sunlit_n + shadow_n,
        "known_coverage_percentage": round(100.0 * (sunlit_n + shadow_n) / len(samples), 6),
        "known_coverage_duration_percentage": round(100.0 * known_s / total_s, 6),
        "sunlit_duration_hours": round(sunlit_s / 3600.0, 6),
        "shadowed_duration_hours": round(shadow_s / 3600.0, 6),
        "unknown_duration_hours": round(unknown_s / 3600.0, 6),
        "sunlit_percentage_of_total_time": round(100.0 * sunlit_s / total_s, 6),
        "shadowed_percentage_of_total_time": round(100.0 * shadow_s / total_s, 6),
        "unknown_percentage_of_total_time": round(100.0 * unknown_s / total_s, 6),
        "sunlit_percentage_of_known_time": round(100.0 * sunlit_s / known_s, 6) if known_s > 0 else None,
        "shadowed_percentage_of_known_time": round(100.0 * shadow_s / known_s, 6) if known_s > 0 else None,
        "longest_continuous_shadow_hours": round(longest / 3600.0, 3),
        "longest_continuous_shadow_samples": longest_samples,
        "compute_seconds": round(time.time() - t0, 2),
    }
    out["sites"].append(site)
    print(name, "done", round(time.time() - t0, 1), "s")

RESULTS_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
print("Wrote", RESULTS_PATH)
