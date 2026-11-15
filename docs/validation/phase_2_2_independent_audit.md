# LUNARIS — Phase 2.2: Independent Audit of Surface-Site Ephemeris Validation

**Audit status:** PASS WITH QUALIFICATIONS  
**Audit date:** 2026-11-15  
**Audited artifact:** `docs/validation/phase_2_2_surface_ephemeris_validation.md`  
**Supporting evidence audited:**
- `tests/validation/test_surface_ephemeris_horizons_validation.py`
- `tests/validation/surface_ephemeris_validation_results.json`
- `tests/validation/horizons_raw/*.txt` (10 raw JPL Horizons responses)
- `ephemeris_engine.py`, `coordinate_transform.py` (production, read-only)

This audit re-inspected all evidence and independently recomputed every statistic from the JSON results. It did **not** modify any production code or overwrite any baseline evidence.

---

## 1. Audit scope and decision rule

The Phase 2.2 report claims:

| Claim | Report value |
|-------|--------------|
| Status | VERIFIED |
| Comparisons | 80 successful (5 observers × 8 epochs × 2 targets), 0 failed |
| Targets | Sun (10), Earth (399) |
| Reference | JPL Horizons apparent az/el, quantity code 4 (airless) |
| LUNARIS ephemeris | DE440 (`de440s.bsp`), MOON_ME frame |
| Horizons ephemeris | DE441 |
| Max abs error | 0.0540 arcsec (Earth elevation) |

Audit decision statuses: PASS / PASS WITH QUALIFICATIONS / FAIL.  
A PASS or PASS WITH QUALIFICATIONS permits Phase 3 to begin.

---

## 2. Evidence inspected (A2)

All of the following were inspected directly; the previous assistant's summary was **not** relied upon as evidence:

1. Complete Phase 2.2 Markdown report (`docs/validation/phase_2_2_surface_ephemeris_validation.md`).
2. Entire validation Python script (`tests/validation/test_surface_ephemeris_horizons_validation.py`).
3. Every record in `surface_ephemeris_validation_results.json` (80 records + summary).
4. Every raw Horizons response in `tests/validation/horizons_raw/` (10 files: 5 observers × 2 targets).
5. The exact Horizons request URLs/parameters stored in each JSON record.
6. Production functions `compute_site_ephemeris`, `_body_angles`, `compute_sun_ephemerides` in `ephemeris_engine.py`; `lunar_geodetic_to_cartesian` in `coordinate_transform.py`.
7. `git status` — confirmed only new untracked files; **no production code modified**, no commits.

---

## 3. Independent statistical recalculation (A3)

Recomputed from the JSON records (read-only). All values match the report exactly.

### 3.1 Counts and completeness

| Check | Result |
|-------|--------|
| Total records | 80 |
| Failed / unavailable | 0 |
| Unique (observer, target, epoch) keys | 80 of 80 |
| Duplicate keys | 0 |
| Observers | 5 (Shackleton, PCB01, HW04, MMA04, dGR2_K2023) |
| Epochs | 8 (2026-11-14/15, 00/06/12/18 UTC) |
| Targets | 2 (sun, earth) |
| Expected combinations | 5 × 8 × 2 = 80 |
| All combinations represented | Yes |

No records were silently omitted; no outliers removed; every observer/epoch/target combination is present exactly once.

### 3.2 Error statistics (recomputed, arcsec)

**Sun (n = 40)**

| Quantity | Mean | RMS | Max | Min |
|----------|------:|----:|----:|----:|
| Azimuth | 0.0036 | 0.0038 | 0.0072 | 0.0000 |
| Elevation | 0.0067 | 0.0083 | 0.0144 | 0.0000 |

**Earth (n = 40)**

| Quantity | Mean | RMS | Max | Min |
|----------|------:|----:|----:|----:|
| Azimuth | 0.0038 | 0.0043 | 0.0072 | 0.0000 |
| Elevation | 0.0454 | 0.0456 | 0.0540 | 0.0360 |

Overall maximum absolute error: **0.0540 arcsec (Earth elevation)**. Matches the report.

### 3.3 Per-observer maxima (arcsec)

| Observer | Sun az max | Sun el max | Earth az max | Earth el max |
|----------|-----------:|-----------:|-------------:|-------------:|
| Shackleton | 0.0036 | 0.0144 | 0.0072 | 0.0504 |
| PCB01 | 0.0036 | 0.0144 | 0.0036 | 0.0504 |
| HW04 | 0.0072 | 0.0144 | 0.0072 | 0.0540 |
| MMA04 | 0.0072 | 0.0144 | 0.0072 | 0.0504 |
| dGR2_K2023 | 0.0036 | 0.0144 | 0.0072 | 0.0504 |

All match the report. All well below 1 arcsec.

---

## 4. Raw Horizons evidence vs JSON (A3 continued)

Spot-checked raw responses against JSON records; all matched exactly:

- **Shackleton Sun:** Horizons `126.619609  1.496957` ↔ JSON horizons `126.619609` / `1.496957`. ✓
- **Shackleton Earth:** Horizons `358.772809  -4.548324` ↔ JSON `358.772809` / `-4.548324`. ✓
- **MMA04 Sun:** Horizons `127.099309  -0.669100` ↔ JSON `127.099309` / `-0.669100`. ✓ (Rows with `i` / `*i` interfering-body markers parsed correctly.)

The parser correctly skips solar-presence (`*`) and interfering-body (`i`, `*i`) marker tokens between the timestamp and the angles (lines 173-181 of the script). All 8 epochs per observer/target were recovered, including the MMA04 rows that initially failed during development due to the `*i` marker.

---

## 5. Precision and rounding audit (A4)

### 5.1 Horizons output precision

Horizons prints azimuth and elevation to **6 decimal places in degrees** (e.g. `126.619609`, `1.496957`).

- Quantum = 1e-6 degree = **0.0036 arcsec**.
- All LUNARIS values are also rounded to 6 decimals by the script (`round(..., 6)`).

### 5.2 Residuals vs quantization interval

| Quantity | Max residual | In quanta (0.0036 as) | Interpretation |
|----------|-------------|----------------------|----------------|
| Sun azimuth | 0.0072 as | 2.0 | At/below quantum — rounding noise |
| Sun elevation | 0.0144 as | 4.0 | At quantum — rounding noise |
| Earth azimuth | 0.0072 as | 2.0 | At/below quantum — rounding noise |
| Earth elevation | 0.0540 as | 15.0 | Above quantum — measurable |

### 5.3 What can and cannot be claimed

- **Agreement demonstrated:** LUNARIS agrees with Horizons to well under 1 arcsec in all 80 cases (max 0.054 arcsec). This is a valid, robust conclusion.
- **Measurement precision:** For Sun azimuth/elevation and Earth azimuth, residuals (≤ 4 quanta) are at or below the Horizons output quantum. They cannot be resolved into a physical error; they reflect the printed precision of the reference values plus LUNARIS's own 6-decimal rounding.
- **Actual physical/model error:** Not isolatable at the sub-quantum level. Only Earth elevation (max 0.054 arcsec, 15 quanta) rises clearly above the quantization floor.
- **DE440 vs DE441 difference:** Cannot be separated from method difference or rounding from these data.

### 5.4 Required report correction (A4)

The report's specific sub-quantum claims (e.g. Sun azimuth mean 0.0036 arcsec, max 0.0072 arcsec) should be recharacterized as **residuals at or below the Horizons output quantization (0.0036 arcsec per 1e-6 deg)**, i.e. measurement precision, not exact physical error. The broader "sub-arcsecond agreement" conclusion remains supported.

---

## 6. Causal-explanation audit (A5)

The report attributes residuals to:
- DE440 vs DE441 ephemeris difference,
- observer-dependent light-time,
- stellar aberration,
- lunar rotation effects.

**Audit finding:** These are **hypotheses, not independently isolated results.** The validation compares two complete pipelines (LUNARIS center-then-subtract vs Horizons direct surface-observer) using different ephemerides (DE440 vs DE441). No controlled experiment was run to isolate any single contributor (e.g. same ephemeris, both methods; or same method, both ephemerides). Therefore:

- The larger Earth elevation residual (0.054 arcsec max) is **consistent with** Earth's proximity (~0.0027 AU ≈ 400,000 km) making observer position subtraction more significant, but the cause is **not demonstrated**.
- The claimed DE440/DE441 contribution is **not measured**.

### Required report correction (A5)

Reword §11.1 and §11.2 to label DE440/DE441, observer light-time, aberration, and lunar rotation as **possible contributors**, not demonstrated causes. State that the residual magnitude is small and negligible for mission planning, but its specific origin was not isolated.

---

## 7. Coordinate and observer consistency audit (A6)

Verified against raw Horizons response headers:

| Property | LUNARIS | Horizons (raw header) | Consistent? |
|----------|---------|----------------------|-------------|
| Body-fixed frame | MOON_ME | `Center pole/equ: MEAN_ME (high precision)` | Yes (equivalent) |
| Longitude | East-positive, wrap [0,360) | `Center geodetic: E-lon(deg)` east-positive | Yes |
| Example wrap | PCB01 lon -69.983 | Horizons `Center geodetic: 290.017, -83.763` (360-69.983) | Yes |
| Example wrap | MMA04 lon -0.459 | Horizons `Center geodetic: 359.541, -86.31` (360-0.459) | Yes |
| Reference radius | 1737.4 km sphere | `Center radii: 1737.4, 1737.4, 1737.4 km` | Yes |
| Height reference | 0 m above sphere | `Alt(km) ≈ 0` (3.85781E-13) | Yes |
| Latitude | Planetocentric, negative south | Geodetic on sphere = planetocentric | Yes |
| Time scale | UTC → TDB internally | UTC output | Yes |
| Quantity type | Apparent (Skyfield `.apparent()`) | Apparent, airless (`Azi____(a-app)___Elev`) | Yes |
| Relativistic light bending | Skyfield default | `Rel. light bend: Sun, EARTH` | Comparable |
| Atmospheric refraction | None | `Atmos refraction: NO (AIRLESS)` | Yes |
| Target IDs | Sun 10, Earth 399 | COMMAND 10 / 399 | Yes |
| Observer config | lat/lon/height=0 | CENTER=coord@301, COORD_TYPE=GEODETIC, SITE_COORD='lon,lat,0.0' | Yes |

**Observer-coordinate consistency:** Both LUNARIS and Horizons wrap negative longitudes to east-positive [0,360) identically (verified via MMA04 and PCB01 raw headers). No longitude-sign inconsistency.

**LUNARIS frame actually used:** All 80 records show `lunaris_frame: "MOON_ME"` — the preferred frame was selected, not a fallback.

Frame consistency is established; no incompatible-convention comparison was made.

---

## 8. Test reproducibility audit (A7)

| Check | Result |
|-------|--------|
| Parses `$$SOE`/`$$EOE` block | Yes |
| Handles `*` / `i` / `*i` markers | Yes (verified on MMA04) |
| UTC timestamp matching | Yes (ISO format, timezone-aware) |
| Target identification | COMMAND 10/399 mapped to sun/earth |
| Circular azimuth error | `min(|Δ|, 360−|Δ|)` implemented correctly |
| Missing/malformed records | Recorded as `failed`, does not crash |
| Reproducible requests | Full `request_url` stored per record |
| Clear failure on missing kernels | `init_ephemeris` raises `EphemerisError`, script returns exit 2 |
| Clear failure on network loss | `urllib.error` caught, recorded as failed |

The script reads only (no production modification). It can be re-run from the repo root with `python tests/validation/test_surface_ephemeris_horizons_validation.py` (requires bundled SPICE kernels under `data/Ephemeris` and network access to `ssd.jpl.nasa.gov`).

**Evidence preservation:** No baseline evidence files were overwritten during this audit. The independent recomputation was performed from a separate temporary script outside the repo.

---

## 9. Git and repository safety (C1)

`git status --short` shows only the four new untracked Phase 2.2 files:
- `docs/validation/phase_2_2_surface_ephemeris_validation.md`
- `tests/validation/test_surface_ephemeris_horizons_validation.py`
- `tests/validation/surface_ephemeris_validation_results.json`
- `tests/validation/horizons_raw/`

No production files modified, no commits created or pushed. Existing working-tree changes preserved.

---

## 10. Audit decision (A8)

**Status: PASS WITH QUALIFICATIONS**

Rationale:
- All 80 comparisons succeeded; raw Horizons evidence supports every JSON value; statistics independently recomputed and match the report exactly.
- Frames, coordinates, longitudes, heights, time scale, quantity code, and target IDs are verified consistent.
- The sub-arcsecond agreement conclusion is robust and supported.

Qualifications (do not invalidate the comparison; required report corrections):
1. **(Precision)** Sun azimuth/elevation and Earth azimuth residuals are at or below the Horizons 6-decimal-degree output quantum (0.0036 arcsec). They represent measurement precision, not isolatable physical error. Recharacterize specific sub-quantum values accordingly; the "sub-arcsecond" conclusion stands.
2. **(Causation)** DE440/DE441, observer light-time, aberration, and lunar rotation are possible contributors to the residual, not demonstrated causes. Reword §11.1/§11.2 accordingly.

This audit **passes** and **permits Phase 3 (Temporal Analysis) to begin**.

---

## 11. Recommended report corrections (minimum)

In `docs/validation/phase_2_2_surface_ephemeris_validation.md`:

1. §1 / §8 / §9 tables: add a footnote that residuals ≤ 0.0144 arcsec (Sun) and ≤ 0.0072 arcsec (Earth az) are at or below the Horizons output quantum of 0.0036 arcsec (1e-6 deg) and should be read as measurement-precision agreement rather than exact physical error.
2. §11.1: reword the causal sentence so DE440/DE441, observer light-time/aberration, and lunar rotation are listed as possible contributors, not demonstrated causes; state the cause was not isolated.
3. §11.2: clarify that frame consistency is established but the residual origin is unattributed.

No production-code change is required for Phase 2.2.

---

## 12. Files created by this audit

- `docs/validation/phase_2_2_independent_audit.md` (this report)

No other files created or modified. Baseline evidence preserved intact.
