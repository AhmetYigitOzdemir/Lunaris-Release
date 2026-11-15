"""
PSR screening validation: Compare LUNARIS PSR classification against published PSR catalog.

Reference: Ahrens, C. J., Fastook, J. L., et al. (2025). "Diverse Lunar Polar Permanently
Shadowed Regions and Environmental Metrics for Site Planning Decision-Making."
NASA NTRS 20250008823. Table 1: Catalog of PSRs with location coordinates.

Also referenced: Bickel et al. (2024) "Dynamic Secondary Illumination in Permanent
Shadows within Artemis III Candidate Landing Regions" (PSJ).

Known PSR locations (south pole, from Ahrens et al. 2025 Table 1):
- Shackleton:    -89.695,  126.371  (Type A - full shadow at crater floor)
- Haworth:       -87.529,  -4.854   (Type A)
- de Gerlache:   -88.275,  -90.629  (Type B)
- Faustini:      -87.1331,  84.499   (Type B)
- Slater:        -88.1177, 112.068   (Type B)
- Shoemaker:     -88.057,   44.313   (Type B)
- Cabeus B:      -81.64,   -54.49    (Type B)
- Nobile:        -85.363,  51.569    (Type C)

Known non-PSR locations (should receive sun during draconic year):
- Malapert Massif: -86.310, -0.459   (illuminated peak)
- Mons Mouton:     -85.416, 31.851   (illuminated plateau)

Validation method:
- Run LUNARIS PSR screen (draconic year, 346.62 days, 60-min step) at each location
- PSR locations should classify as "candidate" (no sun) or "unknown" (partial coverage)
- Non-PSR locations should classify as "not_candidate" (sun observed)
- Note: draconic year is shorter than full nodal cycle; some PSRs may receive
  occasional sun during 346.62 days even if permanently shadowed over 18.6 years
"""

import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from horizon_analysis import (
    LunarDEM,
    DEFAULT_DEM_LABEL,
    calculate_horizon_profile,
    analyze_sunlight_period,
)
from ephemeris_engine import compute_site_ephemeris, init_ephemeris, parse_timestamp_utc

# Initialize ephemeris
init_ephemeris()

# Load DEM
dem = LunarDEM.load(DEFAULT_DEM_LABEL)

# Known PSR locations from Ahrens et al. (2025) Table 1
PSR_LOCATIONS = [
    ("Shackleton", -89.695, 126.371, "Type A"),
    ("Haworth", -87.529, -4.854, "Type A"),
    ("de Gerlache", -88.275, -90.629, "Type B"),
    ("Faustini", -87.1331, 84.499, "Type B"),
    ("Slater", -88.1177, 112.068, "Type B"),
    ("Shoemaker", -88.057, 44.313, "Type B"),
    ("Cabeus B", -81.64, -54.49, "Type B"),
    ("Nobile", -85.363, 51.569, "Type C"),
]

# Known non-PSR locations (illuminated areas)
NON_PSR_LOCATIONS = [
    ("Malapert Massif", -86.310, -0.459),
    ("Mons Mouton", -85.416, 31.851),
    ("Mons Mouton Plateau", -85.111, 26.710),
]


def classify_psr(lat, lon, elevation_m=None, step_minutes=60.0):
    """Run LUNARIS PSR screen logic at a location."""
    if elevation_m is None:
        elevation_m = dem.elevation_at(lat, lon)

    profile = calculate_horizon_profile(
        dem, lat, lon,
        site_elevation_m=elevation_m,
        azimuth_step_deg=1.0,
        max_distance_m=200000.0,
        ray_step_m=40.0,
    )

    start = datetime(2026, 11, 14, 0, 0, tzinfo=UTC)
    end = start + timedelta(days=346.62)  # Draconic year

    analysis = analyze_sunlight_period(
        profile,
        start_time=start,
        end_time=end,
        step_minutes=step_minutes,
        include_samples=False,
    )

    sunlit_seconds = analysis["sunlit_duration_seconds"]
    coverage = analysis["known_illumination_coverage_percentage"]

    if sunlit_seconds > 0.0:
        classification = "not_candidate"
    elif coverage >= 99.9:
        classification = "candidate"
    else:
        classification = "unknown"

    return {
        "classification": classification,
        "sunlit_hours": analysis["sunlit_duration_hours"],
        "sunlit_seconds": sunlit_seconds,
        "coverage_pct": coverage,
        "sample_count": analysis["sample_count"],
    }


def main():
    print("=" * 95)
    print("PSR SCREENING VALIDATION vs PUBLISHED CATALOG (Ahrens et al. 2025)")
    print("=" * 95)
    print()
    print("Analysis: Draconic year (346.62 days), 60-min step, 2026-11-14 start")
    print("DEM: LOLA LDEM_80S_40M_FLOAT (40 m/pixel, 80-90 S)")
    print()

    # Test known PSR locations
    print("--- KNOWN PSR LOCATIONS (should be candidate or unknown) ---")
    print(f"{'PSR':>16} {'Lat':>8} {'Lon':>9} {'Type':>6} {'Classification':>15} {'Sunlit(h)':>10} {'Cov(%)':>8}")
    print("-" * 95)

    psr_candidate = 0
    psr_unknown = 0
    psr_not_candidate = 0

    for name, lat, lon, ptype in PSR_LOCATIONS:
        try:
            result = classify_psr(lat, lon)
            cls = result["classification"]
            if cls == "candidate":
                psr_candidate += 1
            elif cls == "unknown":
                psr_unknown += 1
            else:
                psr_not_candidate += 1

            print(f"{name:>16} {lat:>8.3f} {lon:>9.3f} {ptype:>6} "
                  f"{cls:>15} {result['sunlit_hours']:>10.2f} {result['coverage_pct']:>8.1f}")
        except Exception as exc:
            print(f"{name:>16} {lat:>8.3f} {lon:>9.3f} {ptype:>6} "
                  f"{'ERROR':>15} {'N/A':>10} {'N/A':>8}  ({exc})")

    print()
    print(f"PSR summary: {psr_candidate} candidate, {psr_unknown} unknown, "
          f"{psr_not_candidate} not_candidate (of {len(PSR_LOCATIONS)} known PSRs)")
    print()

    # Test non-PSR locations
    print("--- KNOWN NON-PSR LOCATIONS (should be not_candidate) ---")
    print(f"{'Location':>24} {'Lat':>8} {'Lon':>9} {'Classification':>15} {'Sunlit(h)':>10}")
    print("-" * 95)

    non_psr_correct = 0
    for name, lat, lon in NON_PSR_LOCATIONS:
        try:
            result = classify_psr(lat, lon)
            cls = result["classification"]
            correct = cls == "not_candidate"
            if correct:
                non_psr_correct += 1
            status = "OK" if correct else "UNEXPECTED"
            print(f"{name:>24} {lat:>8.3f} {lon:>9.3f} {cls:>15} "
                  f"{result['sunlit_hours']:>10.2f}  [{status}]")
        except Exception as exc:
            print(f"{name:>24} {lat:>8.3f} {lon:>9.3f} {'ERROR':>15} {'N/A':>10}  ({exc})")

    print()
    print(f"Non-PSR summary: {non_psr_correct}/{len(NON_PSR_LOCATIONS)} correctly identified")
    print()

    # Important caveats
    print("=== IMPORTANT CAVEATS ===")
    print("1. Draconic year (346.62 days) != full 18.6-year nodal cycle.")
    print("   Some PSRs may receive occasional sun during 346.62 days even if")
    print("   permanently shadowed over 18.6 years. Use psr-cycle-screen for full cycle.")
    print()
    print("2. 'candidate' = pre-screen only, NOT confirmed permanent shadow.")
    print("   LUNARIS never sets is_permanently_shadowed = True.")
    print()
    print("3. Coverage < 99.9% yields 'unknown' even if no sun is observed.")
    print("   This occurs when horizon rays extend beyond the DEM footprint.")
    print()
    print("4. 40 m/pixel DEM cannot resolve small-scale shadowing variations.")
    print("   Sub-pixel terrain features may affect actual illumination.")


if __name__ == "__main__":
    main()
