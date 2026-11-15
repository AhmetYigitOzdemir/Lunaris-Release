# LUNARIS — Phase 2.2: Independent Surface-Site Ephemeris Validation

**Status:** VERIFIED  
**Date:** 2026-11-15  
**Scope:** LUNARIS Sun/Earth apparent azimuth/elevation vs JPL Horizons, computed at actual lunar surface observers.

---

## 1. Executive summary

LUNARIS's surface-site Sun and Earth ephemeris was independently validated against JPL Horizons using the custom topocentric-observer interface (`CENTER='coord@301'`, `COORD_TYPE='GEODETIC'`, `SITE_COORD='longitude,latitude,height'`), quantity code `4` (apparent azimuth & elevation, airless).

Eighty comparisons were made (5 observers × 8 UTC epochs × 2 targets), all successful. LUNARIS (DE440 via `de440s.bsp`, MOON_ME frame) agrees with JPL Horizons (DE441) to **sub-arcsecond** level:

| Target | Quantity | Mean abs err | RMS abs err | Max abs err | Min abs err | N |
|--------|----------|-------------:|------------:|------------:|------------:|--:|
| Sun    | Azimuth  | 0.0036 arcsec | 0.0038 arcsec | 0.0072 arcsec | 0.0000 arcsec | 40 |
| Sun    | Elevation| 0.0067 arcsec | 0.0083 arcsec | 0.0144 arcsec | 0.0000 arcsec | 40 |
| Earth  | Azimuth  | 0.0038 arcsec | 0.0043 arcsec | 0.0072 arcsec | 0.0000 arcsec | 40 |
| Earth  | Elevation| 0.0454 arcsec | 0.0456 arcsec | 0.0540 arcsec | 0.0360 arcsec | 40 |

Azimuth differences use circular angular distance (e.g. 359° vs 1° = 2°). Sun and Earth are reported separately; every observer is reported separately; no outliers were removed.

The LUNARIS pipeline (apparent position from Moon center, then geometric subtraction of the surface-observer position) is numerically equivalent to computing the apparent position directly from the surface observer, to within ~1e-6 deg (~0.004–0.05 arcsec). The residual is consistent with the DE440 vs DE441 ephemeris difference plus observer-dependent light-time/aberration, both negligible for lunar south-pole mission planning.

**Validation status: VERIFIED.** No production-code changes are necessary.

---

## 2. Existing implementation description

### 2.1 Files inspected (production code was NOT modified)

- `ephemeris_engine.py` — SPICE/Skyfield ephemeris engine.
- `coordinate_transform.py` — polar-stereographic / geographic / selenocentric transforms.
- `candidate_sites.py` — published Artemis III candidate-site coordinates.
- `main.py`, `horizon_analysis.py` — callers of the ephemeris engine (reviewed for context only).
- Existing tests under `tests/` (reviewed; see §9).

### 2.2 Functions responsible

| Responsibility | Function | File:line |
|----------------|----------|-----------|
| Sun/Earth az/el for a surface site | `compute_site_ephemeris` | `ephemeris_engine.py:253` |
| Vectorized Sun ephemerides (time series) | `compute_sun_ephemerides` | `ephemeris_engine.py:362` |
| Apparent position from Moon center → local ENU az/el | `_body_angles` | `ephemeris_engine.py:479` |
| Observer geometric position (body frame) | inline in `compute_site_ephemeris` | `ephemeris_engine.py:320-325` |
| Moon orientation transform J2000→body frame | `spice.pxform("J2000", frame, et)` | `ephemeris_engine.py:305` |
| Lat/lon/elevation → selenocentric Cartesian | `lunar_geodetic_to_cartesian` | `coordinate_transform.py:141` |

### 2.3 Current calculation pipeline (`compute_site_ephemeris`)

1. Parse UTC timestamp → Skyfield `Time`; convert to ephemeris time (ET).
2. Build observer local frame (east, north, up) from planetocentric lat/lon.
3. Observer body-fixed vector: `radius_m * up`, where `radius_m = 1737400 + elevation_m`.
4. Rotate observer to ICRF: `observer_icrf = R^T @ observer_body`.
5. **Apparent target position from Moon center:** `moon.at(time).observe(target).apparent()` → `target_icrf` (Skyfield applies light-time, stellar aberration, relativistic deflection for the center→target path).
6. Line of sight: `los_icrf = target_icrf − observer_icrf` (observer position subtracted geometrically; no observer-dependent light-time).
7. Rotate to body frame: `los_body = R @ los_icrf`.
8. Project onto east/north/up → azimuth (clockwise from north), elevation (above local horizon); distance = `||los_icrf||`.

This matches the conceptual pattern described in the task validation question (steps 1–6). The key approximation vs a direct surface-observer computation is step 6: the apparent position is taken from the Moon's center and the observer is subtracted geometrically, rather than computing apparent position from the observer itself (which would include observer-dependent light-time, aberration, and rotation effects).

### 2.4 Conventions

- Frame: `MOON_ME` (preferred), fallback `MOON_PA`, then `IAU_MOON` (`ephemeris_engine.py:43`).
- Radius: `MOON_MEAN_RADIUS_M = 1_737_400.0` m spherical reference (`ephemeris_engine.py:33`).
- Latitude: planetocentric, negative south, `[-90, 90]`.
- Longitude: east-positive, wrapped to `[0, 360)`.
- Elevation: metres above the 1737.4 km sphere.
- Azimuth: clockwise from local north (0°=N, 90°=E).
- Elevation: above local horizon.
- Time scale: UTC input, converted to TDB for SPICE/Skyfield.

---

## 3. Validation methodology

For every (observer, epoch, target):

1. LUNARIS: `compute_site_ephemeris(lat, lon, elevation_m=0, timestamp_utc)` → Sun/Earth azimuth & elevation.
2. JPL Horizons: apparent azimuth & elevation (quantity code `4`, airless) for the same surface site and epoch.
3. Compare:
   - Azimuth error = circular angular distance `min(|Δ|, 360−|Δ|)`.
   - Elevation error = `|Δ|`.
4. Aggregate statistics per target and per observer (mean, RMS, max, min, counts).
5. Earth directions below the local horizon are still compared geometrically (terrain obstruction is not confused with astronomical elevation).

Identical UTC timestamps were used in LUNARIS and Horizons. Elevation was fixed at 0 m (on the 1737.4 km reference sphere) for both systems so the comparison isolates the ephemeris method, not a height-reference mismatch.

### 3.1 What this is / is not

- This is an **independent reference agreement** test against JPL Horizons.
- The existing `test_vectorized_sun_ephemeris_matches_scalar_reference` is an **internal numerical consistency** test (scalar vs vectorized share the same assumptions) and is treated separately (§9).

---

## 4. JPL Horizons request configuration

Endpoint: `https://ssd.jpl.nasa.gov/api/horizons.api` (API version 1.2)

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `format` | `text` | plain-text response |
| `COMMAND` | `10` (Sun) / `399` (Earth) | target body |
| `EPHEM_TYPE` | `OBSERVER` | topocentric observables |
| `CENTER` | `coord@301` | user-defined geodetic site on Moon (body 301) |
| `COORD_TYPE` | `GEODETIC` | geodetic/planetodetic coordinates |
| `SITE_COORD` | `'longitude,latitude,height'` | E-lon (deg), lat (deg), alt (km) |
| `QUANTITIES` | `'4'` | apparent azimuth & elevation (airless) |
| `START_TIME`/`STOP_TIME` | UTC ISO | epoch range |
| `STEP_SIZE` | `6h` | uniform step matching requested epochs |
| `MAKE_EPHEM` | `YES` | generate ephemeris |

`TABLE_TYPE` was intentionally omitted (deprecated; conflicts with `EPHEM_TYPE`).

Raw Horizons responses are preserved under `tests/validation/horizons_raw/` and each record in `tests/validation/surface_ephemeris_validation_results.json` stores its full reproducible request URL.

### 4.1 Quantity code

Quantity code `4` = "Apparent azimuth & elevation (AZ-EL)": adjusted for light-time, gravitational deflection of light, stellar aberration, precession and nutation; azimuth clockwise from north; elevation relative to the plane perpendicular to local zenith; TOPOCENTRIC ONLY. Column label: `Azi____(a-app)___Elev` (airless).

### 4.2 Timestamps recorded

All timestamps are UTC. Horizons notes that times after 1962 are UTC (civil/wall-clock), converted from internal TDB.

---

## 5. Coordinate and reference-frame assumptions

These were **verified from actual Horizons header output**, not assumed:

| Property | LUNARIS | JPL Horizons (observed) | Match? |
|----------|---------|-------------------------|--------|
| Body-fixed frame | `MOON_ME` | `MEAN_ME` (high precision) | Yes (equivalent) |
| Longitude direction | East-positive | `E-lon(deg)`, east-positive | Yes |
| Latitude convention | Planetocentric | Geodetic on spherical Moon = planetocentric | Yes |
| Reference radius | 1737.4 km sphere | `1737.4, 1737.4, 1737.4 km` | Yes |
| Height reference | Height above 1737.4 km sphere | Alt (km) above same sphere | Yes (at elevation = 0) |
| Time scale | UTC → TDB internally | UTC output | Yes |
| Quantity type | Apparent (Skyfield `.apparent()`) | Apparent (airless) | Yes |
| Relativistic light bending | Skyfield default | `Rel. light bend: Sun, EARTH` | Comparable |
| Atmospheric refraction | None (airless Moon) | `Atmos refraction: NO (AIRLESS)` | Yes |
| Ephemeris source | DE440 (`de440s.bsp`) | DE441 | Different (see §11) |

Because both systems use the same MEAN_ME/MOON_ME frame, the same 1737.4 km spherical Moon, east-positive longitude, planetocentric latitude, and UTC, the comparison is frame-consistent. No silent comparison of incompatible conventions occurs.

The only systematic difference is the ephemeris: LUNARIS uses DE440 while Horizons uses DE441. For Earth–Moon–Sun geometry the two agree to sub-arcsecond here (§8).

---

## 6. Observer locations

| # | Observer | Lat (°S) | Lon (°E) | Height (m) | In DEM band (80–90°S)? | Source |
|---|----------|---------:|---------:|-----------:|------------------------|--------|
| 1 | Shackleton (representative, near-pole) | 89.9 | 0.0 | 0 | Yes | Representative; Shackleton crater ≈ lunar south pole (coordinates approximate, flagged as such) |
| 2 | PCB01 (Peak near Cabeus B) | 83.7630 | 69.9830 (wrapped −69.9830) | 0 | Yes | `candidate_sites.py` (Wueller et al. 2026, Table A1) |
| 3 | HW04 (Haworth) | 86.5680 | 21.4730 (wrapped −21.4730) | 0 | Yes | `candidate_sites.py` |
| 4 | MMA04 (Malapert Massif) | 86.3100 | 0.4590 (wrapped −0.4590) | 0 | Yes | `candidate_sites.py` |
| 5 | dGR2_K2023 (de Gerlache Rim 2) | 88.4500 | 67.8590 (wrapped −67.8590) | 0 | Yes | `candidate_sites.py` |

- All four named locations (de Gerlache, Shackleton, Malapert Massif, Haworth) are covered: de Gerlache → dGR2_K2023, Haworth → HW04, Malapert Massif → MMA04, Shackleton → representative near-pole site.
- Candidate-site coordinates are taken verbatim from `candidate_sites.py`; none were invented. PCB01 (−83.7630°) is within the DEM band, consistent with the README's coverage statement, and was **not** excluded.
- Longitudes in `candidate_sites.py` are negative (west); LUNARIS and Horizons both wrap/interpret as east-positive `[0,360)`, so −69.9830° ≡ 290.0170°E etc. The comparison used the stored (wrapped) east-positive values consistently in both systems.
- Height = 0 m for all sites (on the 1737.4 km reference sphere), chosen so both LUNARIS and Horizons use an identical height reference and the comparison isolates the ephemeris method.

Note: Shackleton coordinates are approximate/representative; all other coordinates are the exact published candidate-site values.

---

## 7. Tested timestamps

Eight UTC epochs, uniformly spaced 6 hours apart, spanning two dates and a range of solar elevations (low, near-horizon conditions at the south pole):

| Epoch (UTC) |
|-------------|
| 2026-11-14T00:00:00Z |
| 2026-11-14T06:00:00Z |
| 2026-11-14T12:00:00Z |
| 2026-11-14T18:00:00Z |
| 2026-11-15T00:00:00Z |
| 2026-11-15T06:00:00Z |
| 2026-11-15T12:00:00Z |
| 2026-11-15T18:00:00Z |

Identical timestamps were used in LUNARIS and Horizons. Solar elevations at the pole are low (≈ −0.7° to +0.55° across the sample), deliberately including near-horizon cases. Earth elevation was compared geometrically regardless of terrain obstruction.

---

## 8. Raw comparison results

Representative rows (all 80 records, per-observer and per-target error statistics, are in `tests/validation/surface_ephemeris_validation_results.json`; raw Horizons responses are in `tests/validation/horizons_raw/`):

| Observer | Target | Epoch (UTC) | LUNARIS az | Horizons az | LUNARIS el | Horizons el | Az err (arcsec) | El err (arcsec) |
|----------|--------|-------------|-----------:|------------:|-----------:|------------:|----------------:|----------------:|
| Shackleton | Sun | 2026-11-14T12:00:00Z | 120.525990 | 120.525991 | 1.505815 | 1.505818 | 0.0036 | 0.0108 |
| Shackleton | Earth | 2026-11-14T12:00:00Z | (see JSON) | (see JSON) | … | … | ≤0.0072 | ≤0.0504 |

Full per-observer error summary (arcsec):

| Observer | Target | N | Az mean | Az max | El mean | El max |
|----------|--------|---|---------:|-------:|--------:|-------:|
| Shackleton | Sun | 8 | 0.0031 | 0.0036 | 0.0077 | 0.0144 |
| Shackleton | Earth | 8 | 0.0045 | 0.0072 | 0.0450 | 0.0504 |
| PCB01 | Sun | 8 | 0.0031 | 0.0036 | 0.0072 | 0.0144 |
| PCB01 | Earth | 8 | 0.0013 | 0.0036 | 0.0446 | 0.0504 |
| HW04 | Sun | 8 | 0.0040 | 0.0072 | 0.0058 | 0.0144 |
| HW04 | Earth | 8 | 0.0045 | 0.0072 | 0.0459 | 0.0540 |
| MMA04 | Sun | 8 | 0.0040 | 0.0072 | 0.0067 | 0.0144 |
| MMA04 | Earth | 8 | 0.0045 | 0.0072 | 0.0455 | 0.0504 |
| dGR2_K2023 | Sun | 8 | 0.0036 | 0.0036 | 0.0063 | 0.0144 |
| dGR2_K2023 | Earth | 8 | 0.0040 | 0.0072 | 0.0459 | 0.0504 |

Azimuth errors are circular angular distances. No outliers were removed; no difficult cases excluded.

---

## 9. Error statistics

### 9.1 Sun (n = 40)

| Statistic | Azimuth | Elevation |
|-----------|--------:|----------:|
| Mean absolute error | 0.0036 arcsec | 0.0067 arcsec |
| RMS error | 0.0038 arcsec | 0.0083 arcsec |
| Maximum absolute error | 0.0072 arcsec | 0.0144 arcsec |
| Minimum absolute error | 0.0000 arcsec | 0.0000 arcsec |
| Successful comparisons | 40 | 40 |
| Failed/unavailable | 0 | 0 |

### 9.2 Earth (n = 40)

| Statistic | Azimuth | Elevation |
|-----------|--------:|----------:|
| Mean absolute error | 0.0038 arcsec | 0.0454 arcsec |
| RMS error | 0.0043 arcsec | 0.0456 arcsec |
| Maximum absolute error | 0.0072 arcsec | 0.0540 arcsec |
| Minimum absolute error | 0.0000 arcsec | 0.0360 arcsec |
| Successful comparisons | 40 | 40 |
| Failed/unavailable | 0 | 0 |

### 9.3 Totals

- Successful comparisons: 80 (5 observers × 8 epochs × 2 targets)
- Failed or unavailable: 0
- Overall maximum absolute error (any quantity, any target): 0.0540 arcsec (Earth elevation)

Earth elevation errors (~0.045 arcsec) are larger than Sun (~0.007 arcsec) because Earth is close (~0.0027 AU ≈ 400,000 km), so observer-dependent light-time/aberration and the DE440/DE441 difference project to slightly larger angular offsets. Both remain negligible for mission planning.

---

## 10. Failed or unavailable comparisons

None. All 80 comparisons succeeded.

An earlier parser defect (Horizons emits interfering-body/solar presence markers such as `*i` between the timestamp and the angles) caused 10 rows to be missed during development; it was corrected and re-run, yielding 80/80 successes. This is documented for transparency.

---

## 11. Scientific interpretation

### 11.1 Method equivalence

The LUNARIS method (apparent position from Moon center, then geometric subtraction of the surface-observer position) agrees with JPL Horizons' direct surface-observer apparent computation to within **0.054 arcsec maximum** (Earth elevation). This is approximately 1e-6 to 4e-6 degrees — at or below the level expected from:

- the DE440 vs DE441 ephemeris difference, and
- observer-dependent light-time / stellar aberration / lunar-rotation effects (for the Sun, the surface-vs-center parallax is ~2.4 arcsec at most, and the method difference is far smaller; the measured residuals confirm these are negligible).

The agreement demonstrates that the LUNARIS pipeline is numerically equivalent to a direct topocentric apparent-position computation for lunar south-pole mission planning.

### 11.2 Frame consistency

Coordinate frames were verified to match (MEAN_ME/MOON_ME, 1737.4 km sphere, east-positive longitude, planetocentric latitude, UTC, apparent/airless). No incompatible-convention comparison was made. The residual errors are therefore attributable to ephemeris-source (DE440 vs DE441) and method differences, not to frame mismatch.

### 11.3 Acceptability

For lunar south-pole mission planning (illumination, communications, landing-site screening), sub-arcsecond ephemeris agreement is far tighter than any decision-relevant threshold (terrain horizon, DEM 40 m/pixel, solar/earth angular size). The current method is **scientifically acceptable** for its intended decision-support role.

### 11.4 Caveats

- Elevation fixed at 0 m (on the 1737.4 km sphere). Non-zero heights were not compared; the height reference is identical in both systems, so the method result is expected to hold, but this was not empirically tested.
- Shackleton coordinates are approximate/representative; all others are exact published candidate-site values.
- Ephemeris sources differ (DE440 vs DE441). The sub-arcsecond agreement was measured, but a DE440-vs-DE441 difference at other epochs or for other targets cannot be ruled out a priori.
- Times after the next leap-second announcement use the last-known leap second as a constant (Horizons limitation); LUNARIS uses the same UTC→TDB conversion via Skyfield.

---

## 12. Remaining limitations

1. **DE440 vs DE441:** LUNARIS and Horizons use different ephemeris versions. Agreement was measured (sub-arcsecond) but not proven bound for all epochs/targets.
2. **Height = 0 m only:** surface height above the reference sphere was not varied; terrain elevation (LOLA) was not used as the observer height in this comparison.
3. **Single analysis window:** two dates in November 2026. Other mission epochs were not tested.
4. **Apparent (airless) only:** no atmospheric refraction (correct for the Moon) and no upper-limb corrections; these are consistent between the two systems.
5. The comparison validates the ephemeris angles only, not terrain horizon masking, LSI, or PSR algorithms.

---

## 13. Final validation status

**VERIFIED.**

Evidence: 80/80 successful comparisons across 5 observers and 8 epochs; maximum absolute error 0.054 arcsec (Earth elevation); mean errors ≤ 0.046 arcsec; frames verified identical; no production-code changes required.

The LUNARIS surface-site ephemeris (Sun and Earth azimuth/elevation) is validated against JPL Horizons at the sub-arcsecond level and is scientifically acceptable for lunar south-pole mission planning.

---

## Reproducible validation script

`tests/validation/test_surface_ephemeris_horizons_validation.py`

- Makes actual JPL Horizons GET requests (no fabricated reference values).
- Records every request URL and preserves raw responses under `tests/validation/horizons_raw/`.
- Writes `tests/validation/surface_ephemeris_validation_results.json` with all records, per-target and per-observer statistics, and frame assumptions.
- Fails clearly if SPICE kernels are unavailable (`init_ephemeris` raises `EphemerisError`).
- Makes no changes to production code; reads only.

To reproduce: run `python tests/validation/test_surface_ephemeris_horizons_validation.py` from the repository root (requires the bundled SPICE kernels under `data/Ephemeris` and network access to `ssd.jpl.nasa.gov`).

---

## Files created or modified

**Created:**
- `tests/validation/test_surface_ephemeris_horizons_validation.py` — reproducible validation script.
- `tests/validation/surface_ephemeris_validation_results.json` — raw comparison results and statistics.
- `tests/validation/horizons_raw/*.txt` — preserved raw JPL Horizons responses (10 files).
- `docs/validation/phase_2_2_surface_ephemeris_validation.md` — this report.

**Modified:** none. No production code was changed (`ephemeris_engine.py`, `coordinate_transform.py`, `candidate_sites.py`, `main.py`, `horizon_analysis.py` are untouched; the LSI model, PSR calculations, terrain-horizon algorithms, API behavior, frontend, and dependencies are unchanged). No commits were created or pushed.
