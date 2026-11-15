# LUNARIS — Phase 2 Baseline: Scientific Audit

**Date:** 2026-11-15  
**Status:** Baseline established — no scientific algorithms modified  
**Test results:** 38/38 passed (see below)

---

## 1. Existing Architecture

Lunaris is a single-repository Python/FastAPI backend with an embedded HTML/JavaScript frontend. Components:

| Component | File | Responsibility |
|-----------|------|----------------|
| API service | `main.py` | FastAPI REST endpoints, Pydantic request/response schemas |
| Scientific engine | `horizon_analysis.py` | DEM loading, terrain horizon, slope, roughness, LSI, solar/Earth visibility, sunlight-period analysis |
| Ephemeris engine | `ephemeris_engine.py` | SPICE kernel initialization, Sun/Earth/Moon ephemeris, topocentric angles |
| Coordinate transforms | `coordinate_transform.py` | Polar-stereographic ↔ geographic ↔ selenocentric Cartesian |
| Candidate sites | `candidate_sites.py` | Nine Artemis III candidate region representative coordinates |
| Frontend / 3D viewer | `south_pole_3d.py` | DEM reader, Plotly 3D surface, embedded HTML+JS HUD |
| Standalone horizon viewer | `horizon_analysis_view.html` | 360° terrain horizon profile canvas |

**Dependencies** (`requirements.txt`):
- fastapi>=0.110, uvicorn[standard]>=0.27
- skyfield>=1.49, spiceypy>=6.0
- numpy>=1.24, pydantic>=2.0, plotly>=5.18, rasterio>=1.3

**Data files** (present on disk, gitignored):
- `data/ldem_80s_40m_float.img` — LOLA LDEM_80S_40M_FLOAT, 15200×15200 float32, km above 1737.4 km sphere
- `data/ldem_80s_40m_float.lbl` — PDS3 label
- `data/Ephemeris/de440s.bsp` — DE440 planetary ephemeris SPK
- `data/Ephemeris/moon_pa_de418_1950-2050.bpc` — Binary lunar PCK (DE418)
- `data/Ephemeris/moon_080317.tf` — Lunar frame kernel
- `data/Ephemeris/pck00011.tpc` — IAU Moon text PCK (fallback)

---

## 2. Scientific Algorithms

### 2.1 Ephemeris calculations (`ephemeris_engine.py`)

**`compute_site_ephemeris(lat, lon, elevation, timestamp_utc)`** (line 253):
1. Parse UTC timestamp → `datetime`
2. Convert to Skyfield `Time` object
3. Compute ET: `(time.tdb - J2000_JD_TDB) * 86400` seconds
4. Get SPICE rotation matrix J2000 → body-fixed frame (`pxform`)
5. Observer position in body frame: `(R+h)·[cos(lat)cos(lon), cos(lat)sin(lon), sin(lat)]`
6. Rotate observer to ICRF
7. For Sun and Earth: `moon.at(time).observe(target).apparent()` → ICRF position
8. Line-of-sight ICRF = target − observer; rotate to body frame
9. Local basis: up/east/north from lat/lon
10. Azimuth = `atan2(east, north) mod 360`; Elevation = `atan2(up, horizontal)`

**`compute_sun_ephemerides(lat, lon, elevation, timestamps_utc)`** (line 362):
- Vectorized Skyfield evaluation for multiple timestamps
- SPICE rotation matrix computed per epoch
- Same angle computation as scalar path

**Frame selection** (`init_ephemeris`, line 106):
- Prefers `MOON_ME`, falls back to `MOON_PA`, then `IAU_MOON`
- Embedded DE418 frame constants as fallback if binary PCK uses DE418 class IDs

**Time scale:** UTC input → Skyfield `from_datetime` → TDB for ET computation. J2000 JD = 2451545.0.

### 2.2 Terrain horizon (`horizon_analysis.py:351`)

**`calculate_horizon_profile(dem, lat, lon, ...)`**:
1. For each azimuth (default 1° step, 0°=north clockwise):
   - Compute great-circle ray points via spherical forward geodesic (`_geodesic_rays`, line 318)
   - Sample DEM bilinearly at each ray point (`_bilinear_sample`, line 289)
   - Compute elevation angle: `atan2(vertical, horizontal)` where:
     - `vertical = (R+z)·cos(delta) − (R+h_obs)`
     - `horizontal = (R+z)·sin(delta)`
     - `delta = distance / R`
2. Horizon angle = max(0, max angle over all distances)
3. Curvature correction included via spherical geometry
4. Default: max_distance=200 km, ray_step = DEM native resolution (40 m)

### 2.3 Solar visibility (`horizon_analysis.py:796`)

**`check_solar_visibility(profile, solar_az, solar_el, minimum_coverage=0.9)`**:
- Interpolate horizon at Sun's azimuth
- `is_night = elevation ≤ 0`
- `terrain_blocks_sun = elevation > 0 AND elevation ≤ horizon`
- If night or blocked → `is_sunlit = False`
- If DEM coverage ≥ 0.9 → `is_sunlit = True`
- Otherwise → `is_sunlit = None` (unknown)
- Binary per-sample; no sunrise/sunset interpolation

### 2.4 Sunlight period analysis (`horizon_analysis.py:862`)

**`analyze_sunlight_period(profile, start, end, step_minutes, ...)`**:
1. Horizon computed once, reused for all samples
2. Sun ephemerides sampled at `step_minutes` intervals (default 60)
3. Each sample weighted by interval to next sample
4. `sunlit_seconds` = sum of durations where `is_sunlit is True`
5. `known_seconds` = sum where `is_sunlit is not None`
6. `sunlit_percentage` = sunlit/total only if known == total, else None
7. Max 200,000 samples cap

### 2.5 Earth geometric visibility (`horizon_analysis.py:751`)

**`check_earth_los(profile, earth_az, earth_el, minimum_coverage=0.9)`**:
- Identical geometric test to solar visibility
- `visible = earth_elevation > horizon`
- Returns `communication_status: "OPEN"/"BLOCKED"` (deprecated in favor of `geometric_earth_visibility`)
- No link budget, no Earth angular size, no occultation modeling

### 2.6 Slope and roughness (`horizon_analysis.py:450`)

**`calculate_landing_safety_patch(dem, lat, lon, radius_m=1000, cell_size_m=None)`**:
1. Project site to polar-stereographic x/y
2. Sample grid within radius at cell spacing (default 40 m)
3. `gradient_y, gradient_x = np.gradient(elevation, spacing, spacing)`
4. `slope = degrees(atan(hypot(gradient_x, gradient_y)))`
5. Roughness: planar detrending over 3×3 windows via least squares; RMS of residuals
6. Reports % area ≤5°, ≤8°, median slope, P95 slope, median/P95 roughness

### 2.7 Landing Suitability Index (`horizon_analysis.py:589`)

**`calculate_landing_suitability_index(...)`**:
- Same slope/roughness computation as safety patch
- Per-cell scores:
  - `_slope_score(s)`: 100 if ≤5°, linear decay to 0 at >15°
  - `_roughness_score(r)`: 100 if ≤0.5 m, decay to 0 at higher roughness
- `LSI = 0.7·slope_component + 0.3·roughness_component`
- Score 0–100; classes A (≥85), B (≥70), C (≥50), D (<50)
- **Heuristic weights; not empirically calibrated**

### 2.8 PSR pre-screening (`main.py:662`, `horizon_analysis.py:33`)

- `DRACONIC_YEAR_DAYS = 346.62` (renamed from `LUNAR_YEAR_DAYS` in Phase 1)
- `LUNAR_YEAR_DAYS = 354.367` (reference constant, not used in PSR endpoints)
- `psr_screen`: start + 346.62 days, default 60 min step, min 15/max 180
- `psr_cycle_screen`: start + 18.6×365.25 days, default 60 min step, max 200,000 samples
- Classification: `not_candidate` (sun observed), `candidate` (no sun + ≥99.9% coverage), `unknown` (partial coverage)
- `is_permanently_shadowed` always `None`

---

## 3. Input Datasets

| Dataset | Source | Format | Resolution | Coverage | Units |
|---------|--------|--------|------------|----------|-------|
| LOLA LDEM_80S_40M_FLOAT | LRO/LOLA GDR V1.0 | PDS3 img+lbl | 40 m/pixel | 80°S–90°S | km above 1737.4 km sphere |
| DE440 SPK | JPL | Binary SPK | — | Planetary ephemeris | km |
| Lunar PCK (DE418) | NAIF | Binary bpc | — | Moon orientation | — |
| Lunar TF kernel | NAIF | Text tf | — | Moon frame | — |
| IAU Moon PCK | NAIF | Text tpc | — | IAU_MOON frame | — |

---

## 4. Coordinate Systems

| System | Definition | Used by |
|--------|-----------|---------|
| Planetocentric lat/lon | Latitude negative south, longitude east-positive [0,360) | PDS3 label, API inputs |
| Polar stereographic (PS70S-style) | X/Y meters from south pole, k0=1.0, R=1737400 m | DEM grid, horizon rays |
| Selenocentric Cartesian | X through prime meridian, Y east-positive, Z through north pole | `lunar_geodetic_to_cartesian` |
| J2000/ICRF | Inertial frame | SPICE ephemeris |
| MOON_ME | Mean Earth/Polar Axis (DE421) | Preferred body-fixed frame |

---

## 5. Time Standards

| Standard | Implementation |
|----------|---------------|
| UTC input | ISO 8601 strings parsed by `parse_timestamp_utc` |
| Skyfield Time | `timescale.from_datetime(utc)` |
| TDB/ET | `(time.tdb − J2000_JD_TDB) × 86400` seconds for SPICE |
| J2000 epoch | JD 2451545.0 |

---

## 6. Known Limitations (from Phase 1 audit)

| # | Limitation | Severity | Source |
|---|-----------|----------|--------|
| 1 | 40 m/pixel DEM cannot resolve lander-scale hazards | HIGH | PDS3 label, code comments |
| 2 | Elevations above sphere, not geoid | MEDIUM | PDS3 label lines 66-68 |
| 3 | Fixed horizon over time interval | MEDIUM | `analyze_sunlight_period` computes horizon once |
| 4 | Binary illumination per time step | MEDIUM | No sunrise/sunset interpolation |
| 5 | Earth visibility is geometric only | HIGH | No link budget, no Earth angular size |
| 6 | LSI weights heuristic (0.7/0.3) | HIGH | No empirical calibration |
| 7 | Draconic year (346.62 d) ≠ lunar year (354.367 d) | CORRECTED | Phase 1 fix |
| 8 | No independent scientific validation | HIGH | No external reference comparison |

---

## 7. Existing Test Results

**Total: 38 tests, all passing**

| Test File | Tests | Type |
|-----------|-------|------|
| `test_horizon_analysis.py` | 14 | Unit + synthetic DEM + real-DEM integration |
| `test_earth_los.py` | 3 | Unit (synthetic profiles) |
| `test_candidate_comparison.py` | 5 | API (mocked services) |
| `test_candidate_regions.py` | 10 (+9 parametrized) | Real-DEM smoke tests at 9 candidate sites |

**Test categories covered:**
- Polar-stereographic round-trip
- Synthetic DEM elevation sampling
- Flat/tilted DEM slope and roughness
- Solar visibility (shadow, open sky, partial coverage)
- Sunlight period interval weighting
- Batched vs scalar ephemeris agreement (1e-5 deg tolerance)
- Earth LOS visible/blocked/invalid input
- Candidate catalog (9 regions, unique IDs)
- Candidate comparison (shared window, mocked)
- Nodal cycle classification states
- DEM axis parameters vs PDS3 label
- Draconic vs lunar year constant
- Coordinate round-trip at multiple latitudes/longitudes
- DEM coverage validation (available, outside, partial)
- Real-DEM reference point matching (rasterio cross-check)

**Test categories NOT covered:**
- No comparison against JPL Horizons or external ephemeris reference
- No validation of horizon accuracy against independent implementation
- No validation of LSI against empirical landing data
- No PSR classification validation against known PSR locations
- No test of API error responses (422, 503, 500)
- No test of CORS or deployment configuration

---

## 8. Files Available for Modification

| File | Phase 1 Changes | Phase 2 Planned Changes |
|------|----------------|------------------------|
| `horizon_analysis.py` | DRACONIC_YEAR_DAYS, validate_dem_coverage, geometric_earth_visibility | Possible solar visibility improvements, LSI documentation |
| `ephemeris_engine.py` | None | None planned (validation only) |
| `coordinate_transform.py` | None | None planned |
| `main.py` | PSR endpoint, candidate comparison, Earth LOS endpoint | Documentation updates only |
| `south_pole_3d.py` | Frontend labels updated | Documentation updates only |
| `README.md` | Documentation sections added | Validation results to be added |

---

## 9. Baseline Conclusion

The software is internally consistent and executes as designed. However, **no scientific calculation has been independently validated against external reference data**. All existing tests are synthetic-unit, API-mock, or self-consistency (real-DEM smoke) tests. Phase 2 will focus on obtaining independent reference data for validation where available, and explicitly documenting limitations where external validation is not possible.