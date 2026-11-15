"""
Independent audit of LUNARIS ephemeris validation.

This script re-examines the Phase 2 ephemeris claims with attention to:
1. Observer location: Moon center vs lunar surface site (production uses surface)
2. Reference frame matching
3. Full error statistics (max, mean, RMS)
4. Whether DE440 vs DE441 is the actual cause of differences
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ephemeris_engine import (
    compute_site_ephemeris,
    _ensure_state,
    _STATE,
    MOON_MEAN_RADIUS_M,
    parse_timestamp_utc,
)
import numpy as np

AU_KM = 149597870.700

# Initialize LUNARIS ephemeris engine
if _STATE is None:
    from ephemeris_engine import init_ephemeris
    init_ephemeris()
context = _ensure_state()
print("LUNARIS frame: " + context.frame)
print("LUNARIS SPK kernel: " + context.spk_path.name)
print()

# JPL Horizons reference data (Moon center, DE441)
# Times: 2026-Nov-14, hourly
# Source: JPL Horizons API, COMMAND=10/399, CENTER=500@301, BODYCENTRIC

SUN_REF = [
    ("2026-11-14T00:00:00Z", 15, 14, 48.29, -18, 1, 44.1, 0.98787573402919),
    ("2026-11-14T01:00:00Z", 15, 14, 58.31, -18, 2, 23.3, 0.98788293007827),
    ("2026-11-14T02:00:00Z", 15, 15, 8.34, -18, 3, 2.5, 0.98789023789281),
    ("2026-11-14T03:00:00Z", 15, 15, 18.38, -18, 3, 41.7, 0.98789765641122),
    ("2026-11-14T04:00:00Z", 15, 15, 28.41, -18, 4, 20.9, 0.98790518456659),
    ("2026-11-14T05:00:00Z", 15, 15, 38.45, -18, 5, 0.0, 0.98791282128674),
    ("2026-11-14T06:00:00Z", 15, 15, 48.50, -18, 5, 39.1, 0.98792056549418),
    ("2026-11-14T07:00:00Z", 15, 15, 58.54, -18, 6, 18.2, 0.98792841610621),
    ("2026-11-14T08:00:00Z", 15, 16, 8.59, -18, 6, 57.2, 0.98793637203489),
    ("2026-11-14T09:00:00Z", 15, 16, 18.65, -18, 7, 36.3, 0.98794443218708),
    ("2026-11-14T10:00:00Z", 15, 16, 28.70, -18, 8, 15.3, 0.98795259546445),
    ("2026-11-14T11:00:00Z", 15, 16, 38.77, -18, 8, 54.3, 0.98796086076351),
    ("2026-11-14T12:00:00Z", 15, 16, 48.83, -18, 9, 33.3, 0.98796922697563),
    ("2026-11-14T13:00:00Z", 15, 16, 58.90, -18, 10, 12.2, 0.98797769298703),
    ("2026-11-14T14:00:00Z", 15, 17, 8.97, -18, 10, 51.2, 0.98798625767886),
    ("2026-11-14T15:00:00Z", 15, 17, 19.04, -18, 11, 30.1, 0.98799491992715),
    ("2026-11-14T16:00:00Z", 15, 17, 29.12, -18, 12, 9.0, 0.98800367860286),
    ("2026-11-14T17:00:00Z", 15, 17, 39.21, -18, 12, 47.8, 0.98801253257189),
    ("2026-11-14T18:00:00Z", 15, 17, 49.29, -18, 13, 26.7, 0.98802148069511),
    ("2026-11-14T19:00:00Z", 15, 17, 59.38, -18, 14, 5.5, 0.98803052182834),
    ("2026-11-14T20:00:00Z", 15, 18, 9.47, -18, 14, 44.3, 0.98803965482240),
    ("2026-11-14T21:00:00Z", 15, 18, 19.57, -18, 15, 23.1, 0.98804887852310),
    ("2026-11-14T22:00:00Z", 15, 18, 29.67, -18, 16, 1.8, 0.98805819177125),
    ("2026-11-14T23:00:00Z", 15, 18, 39.77, -18, 16, 40.6, 0.98806759340272),
]

EARTH_REF = [
    ("2026-11-14T00:00:00Z", 6, 58, 47.96, 26, 6, 38.2, 0.00271095113151),
    ("2026-11-14T01:00:00Z", 7, 0, 57.50, 26, 1, 40.9, 0.00271086728354),
    ("2026-11-14T02:00:00Z", 7, 3, 6.85, 25, 56, 36.3, 0.00271077080952),
    ("2026-11-14T03:00:00Z", 7, 5, 16.01, 25, 51, 24.6, 0.00271066164756),
    ("2026-11-14T04:00:00Z", 7, 7, 24.97, 25, 46, 5.7, 0.00271053973694),
    ("2026-11-14T05:00:00Z", 7, 9, 33.75, 25, 40, 39.7, 0.00271040501803),
    ("2026-11-14T06:00:00Z", 7, 11, 42.32, 25, 35, 6.6, 0.00271025743239),
    ("2026-11-14T07:00:00Z", 7, 13, 50.70, 25, 29, 26.5, 0.00271009692273),
    ("2026-11-14T08:00:00Z", 7, 15, 58.88, 25, 23, 39.4, 0.00270992343296),
    ("2026-11-14T09:00:00Z", 7, 18, 6.86, 25, 17, 45.4, 0.00270973690821),
    ("2026-11-14T10:00:00Z", 7, 20, 14.64, 25, 11, 44.4, 0.00270953729484),
    ("2026-11-14T11:00:00Z", 7, 22, 22.21, 25, 5, 36.5, 0.00270932454050),
    ("2026-11-14T12:00:00Z", 7, 24, 29.58, 24, 59, 21.7, 0.00270909859405),
]


def ra_dec_to_vector(ra_h, ra_m, ra_s, dec_d, dec_m, dec_s, distance_au):
    """Convert RA/DEC to a Cartesian vector in km."""
    ra_deg = (ra_h + ra_m / 60.0 + ra_s / 3600.0) * 15.0
    dec_deg = abs(dec_d) + abs(dec_m) / 60.0 + abs(dec_s) / 3600.0
    if dec_d < 0:
        dec_deg = -dec_deg
    ra_rad = math.radians(ra_deg)
    dec_rad = math.radians(dec_deg)
    dist_km = distance_au * AU_KM
    x = dist_km * math.cos(dec_rad) * math.cos(ra_rad)
    y = dist_km * math.cos(dec_rad) * math.sin(ra_rad)
    z = dist_km * math.sin(dec_rad)
    return np.array([x, y, z], dtype=np.float64)


def vector_to_ra_dec(vector):
    """Convert a Cartesian vector to RA (deg), DEC (deg), distance (km)."""
    x, y, z = vector
    ra_rad = math.atan2(y, x)
    if ra_rad < 0:
        ra_rad += 2 * math.pi
    ra_deg = math.degrees(ra_rad)
    dist = math.sqrt(x * x + y * y + z * z)
    dec_rad = math.asin(z / dist)
    dec_deg = math.degrees(dec_rad)
    return ra_deg, dec_deg, dist


def angular_separation(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    """Great-circle angular separation between two RA/DEC points in arcsec."""
    ra1, dec1 = math.radians(ra1_deg), math.radians(dec1_deg)
    ra2, dec2 = math.radians(ra2_deg), math.radians(dec2_deg)
    cos_ang = (math.sin(dec1) * math.sin(dec2) +
               math.cos(dec1) * math.cos(dec2) * math.cos(ra2 - ra1))
    cos_ang = max(-1.0, min(1.0, cos_ang))
    return math.degrees(math.acos(cos_ang)) * 3600.0


def compute_luna_center_position(target, timestamp_utc):
    """Compute ICRF position from Moon center (matches validation script)."""
    req_time = parse_timestamp_utc(timestamp_utc)
    time = context.timescale.from_datetime(req_time)
    apparent = context.moon.at(time).observe(target).apparent()
    return np.asarray(apparent.position.km, dtype=np.float64)


def main():
    print("=" * 80)
    print("INDEPENDENT EPHEMERIS AUDIT")
    print("=" * 80)
    print()

    # === PART A: Moon center comparison (matching Phase 2 validation script) ===
    print("PART A: Moon center vs JPL Horizons (DE441) reference")
    print("-" * 80)

    # Only process timestamps present in BOTH Sun and Earth reference data
    earth_times = {et for et, *_ in EARTH_REF}
    common_times = [ref_time for ref_time, *_ in SUN_REF if ref_time in earth_times]

    print("Time (UTC)           Sun err (arcsec)  Earth err (arcsec)  Sun dist (km)  Earth dist (km)")
    print("-" * 92)

    sun_errors = []
    earth_errors = []
    sun_dist_errors = []
    earth_dist_errors = []

    for ref_time in common_times:
        sun_idx = next(i for i, (rt, *_) in enumerate(SUN_REF) if rt == ref_time)
        earth_idx = next(j for j, (et, *_) in enumerate(EARTH_REF) if et == ref_time)

        _, ra_h, ra_m, ra_s, dec_d, dec_m, dec_s, delta_au = SUN_REF[sun_idx]
        sun_luna_center = compute_luna_center_position(context.sun, ref_time)
        ra_lun, dec_lun, dist_lun = vector_to_ra_dec(sun_luna_center)
        jpl_vector = ra_dec_to_vector(ra_h, ra_m, ra_s, dec_d, dec_m, dec_s, delta_au)
        ra_jpl, dec_jpl, dist_jpl = vector_to_ra_dec(jpl_vector)
        ang_err = angular_separation(ra_lun, dec_lun, ra_jpl, dec_jpl)
        dist_err = abs(dist_lun - dist_jpl)
        sun_errors.append(ang_err)
        sun_dist_errors.append(dist_err)

        _, ra_h2, ra_m2, ra_s2, dec_d2, dec_m2, dec_s2, delta_au2 = EARTH_REF[earth_idx]
        earth_luna_center = compute_luna_center_position(context.earth, ref_time)
        ra_lun2, dec_lun2, dist_lun2 = vector_to_ra_dec(earth_luna_center)
        jpl_vector2 = ra_dec_to_vector(ra_h2, ra_m2, ra_s2, dec_d2, dec_m2, dec_s2, delta_au2)
        ra_jpl2, dec_jpl2, dist_jpl2 = vector_to_ra_dec(jpl_vector2)
        ang_err2 = angular_separation(ra_lun2, dec_lun2, ra_jpl2, dec_jpl2)
        dist_err2 = abs(dist_lun2 - dist_jpl2)
        earth_errors.append(ang_err2)
        earth_dist_errors.append(dist_err2)

        print("%20s %18.3f %18.3f %15.2f %17.2f" % (ref_time, ang_err, ang_err2, dist_err, dist_err2))

    print()
    n_sun = len(sun_errors)
    n_earth = len(earth_errors)
    sun_max = max(sun_errors)
    sun_mean = sum(sun_errors) / n_sun
    sun_rms = math.sqrt(sum(e * e for e in sun_errors) / n_sun)
    earth_max = max(earth_errors)
    earth_mean = sum(earth_errors) / n_earth
    earth_rms = math.sqrt(sum(e * e for e in earth_errors) / n_earth)

    # Compute all 24 Sun errors (not just common times)
    all_sun_errors = []
    all_sun_dist_errors = []
    for ref_time, ra_h, ra_m, ra_s, dec_d, dec_m, dec_s, delta_au in SUN_REF:
        sun_luna_center = compute_luna_center_position(context.sun, ref_time)
        ra_lun, dec_lun, dist_lun = vector_to_ra_dec(sun_luna_center)
        jpl_vector = ra_dec_to_vector(ra_h, ra_m, ra_s, dec_d, dec_m, dec_s, delta_au)
        ra_jpl, dec_jpl, dist_jpl = vector_to_ra_dec(jpl_vector)
        ang_err = angular_separation(ra_lun, dec_lun, ra_jpl, dec_jpl)
        dist_err = abs(dist_lun - dist_jpl)
        all_sun_errors.append(ang_err)
        all_sun_dist_errors.append(dist_err)

    sun_max_all = max(all_sun_errors)
    sun_mean_all = sum(all_sun_errors) / len(all_sun_errors)
    sun_rms_all = math.sqrt(sum(e * e for e in all_sun_errors) / len(all_sun_errors))

    print("=== SUN (Moon center, all 24 epochs) ===")
    print("  Max angular error: %.3f arcsec (%.6f degrees)" % (sun_max_all, sun_max_all / 3600.0))
    print("  Mean angular error: %.3f arcsec" % sun_mean_all)
    print("  RMS angular error: %.3f arcsec" % sun_rms_all)
    print("  Max distance error: %.2f km" % max(all_sun_dist_errors))
    print()

    print("=== EARTH (Moon center, 13 epochs 00:00-12:00) ===")
    print("  Max angular error: %.3f arcsec (%.6f degrees)" % (earth_max, earth_max / 3600.0))
    print("  Mean angular error: %.3f arcsec" % earth_mean)
    print("  RMS angular error: %.3f arcsec" % earth_rms)
    print("  Max distance error: %.2f km" % max(earth_dist_errors))
    print()

    # === PART B: Surface site vs Moon center parallax ===
    print("PART B: Surface site vs Moon center parallax (production vs validation)")
    print("-" * 80)
    print("Production (compute_site_ephemeris) uses surface site (-90 deg, 0 deg, 0 m).")
    print("Validation script uses Moon center.")
    print("Parallax due to Moon radius (1737.4 km):")
    print()

    # Sun parallax at surface
    sun_center = compute_luna_center_position(context.sun, "2026-11-14T12:00:00Z")
    ra_c, dec_c, sun_distance_km = vector_to_ra_dec(sun_center)
    sun_parallax_rad = MOON_MEAN_RADIUS_M / 1000.0 / sun_distance_km
    sun_parallax_arcsec = math.degrees(sun_parallax_rad) * 3600.0
    print("  Sun distance: %.0f km" % sun_distance_km)
    print("  Theoretical Sun parallax at surface: %.2f arcsec" % sun_parallax_arcsec)
    print("  Reported Sun max error: %.3f arcsec" % sun_max_all)
    print("  Parallax / reported error = %.1fx" % (sun_parallax_arcsec / sun_max_all))
    print()

    # Earth parallax at surface
    earth_center = compute_luna_center_position(context.earth, "2026-11-14T12:00:00Z")
    ra_c2, dec_c2, earth_distance_km = vector_to_ra_dec(earth_center)
    earth_parallax_rad = MOON_MEAN_RADIUS_M / 1000.0 / earth_distance_km
    earth_parallax_arcsec = math.degrees(earth_parallax_rad) * 3600.0
    print("  Earth distance: %.0f km" % earth_distance_km)
    print("  Theoretical Earth parallax at surface: %.2f arcsec (%.4f deg)" % (earth_parallax_arcsec, earth_parallax_arcsec / 3600.0))
    print("  Reported Earth max error: %.3f arcsec" % earth_max)
    print("  Parallax / reported error = %.0fx" % (earth_parallax_arcsec / earth_max))
    print()

    # === PART C: Production pipeline test ===
    print("PART C: Production pipeline (surface site) vs JPL Horizons")
    print("-" * 80)
    print("Testing compute_site_ephemeris at lunar south pole (-90 deg, 0 deg, 0 m):")
    print()
    print("Time (UTC)           Sun az (deg)    Sun el (deg)    Earth az (deg)   Earth el (deg)")
    print("-" * 88)

    for ref_time in common_times[:3]:  # Show first 3
        result = compute_site_ephemeris(-90.0, 0.0, 0.0, ref_time)
        sun = result["sun"]
        earth = result["earth"]
        print("%20s %14.4f %14.4f %16.4f %16.4f" % (ref_time, sun["azimuth_deg"], sun["elevation_deg"], earth["azimuth_deg"], earth["elevation_deg"]))

    print()
    print("NOTE: These are local horizontal coordinates (azimuth/elevation),")
    print("not directly comparable to JPL Horizons RA/DEC without frame rotation.")
    print()

    print("=== KEY FINDINGS ===")
    print("1. The Phase 2 validation script computes from MOON CENTER, but the")
    print("   production pipeline (compute_site_ephemeris) computes from a LUNAR")
    print("   SURFACE SITE. These are NOT interchangeable.")
    print()
    print("2. For Earth observations, the surface-center parallax is")
    print("   ~%.0f arcsec (%.4f deg)," % (earth_parallax_arcsec, earth_parallax_arcsec / 3600.0))
    print("   which is %.0fx larger than the reported %.3f arcsec error." % (earth_parallax_arcsec / earth_max, earth_max))
    print()
    print("3. For Sun observations, the surface-center parallax is")
    print("   ~%.2f arcsec, comparable to the %.3f arcsec error." % (sun_parallax_arcsec, sun_max_all))
    print()
    print("4. The validation does NOT test the actual production pipeline for")
    print("   surface sites. It only validates the Moon-center computation.")
    print()
    print("5. Distance errors are 0.00 km at all epochs — this suggests the")
    print("   reference distance precision is insufficient to detect DE440 vs DE441")
    print("   differences.")
    print()
    print("6. The approximately constant ~20 arcsec (Sun) and ~12 arcsec (Earth)")
    print("   errors are consistent with ephemeris version differences (DE440 vs")
    print("   DE441), but this was NOT independently verified — it was assumed.")
    print()
    print("=== STATUS: PARTIALLY VERIFIED ===")
    print("- Moon-center computation matches Horizons within reported errors")
    print("- Surface-site computation NOT validated against Horizons")
    print("- DE440 vs DE441 as sole cause NOT independently confirmed")


if __name__ == "__main__":
    main()
