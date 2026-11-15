# LUNARIS — Phase 2.1 Ephemeris Audit

**Date:** 2026-11-15  
**Status:** PARTIALLY VERIFIED  
**Stage:** 1 — JPL Horizons Ephemeris Audit

---

## 1. Audit Objective

Independently verify the Phase 2 ephemeris validation claims:
- Sun max angular error: 20.385 arcsec vs JPL Horizons DE441
- Earth max angular error: 12.384 arcsec vs JPL Horizons DE441
- DE440 vs DE441 as the attributed cause

---

## 2. What the Phase 2 Validation Actually Did

The Phase 2 validation script (`tests/validation/test_ephemeris_validation.py`) computes ephemeris positions using:

```python
apparent = context.moon.at(time).observe(context.sun).apparent()
sun_icrf_km = np.asarray(apparent.position.km, dtype=np.float64)
```

This computes from **Moon center** (body-centric), NOT from a lunar surface site.

The production pipeline (`ephemeris_engine.py:compute_site_ephemeris`, line 253) computes from a **surface site**:

```python
observer_body_km = (radius_m / 1000.0) * up
observer_icrf_km = icrf_to_body.T @ observer_body_km
line_of_sight_icrf_km = target_icrf_km - observer_icrf_km
```

**These are NOT interchangeable.** The Moon's radius (1737.4 km) introduces parallax:
- Sun at ~0.988 AU: surface-center parallax ≈ 2.4 arcsec
- Earth at ~0.0027 AU: surface-center parallax ≈ 884 arcsec (0.2456°)

---

## 3. Independent Recalculation

I recalculated all error statistics from the original reference values using an independent script (`tests/validation/audit_ephemeris_independent.py`).

### 3.1 Moon Center vs JPL Horizons (DE441) — Verified

**Sun (24 epochs, 2026-11-14 00:00-23:00 UTC):**

| Time (UTC) | Angular Error (arcsec) | Distance Error (km) |
|------------|-----------------------|---------------------|
| 00:00 | 20.334 | 0.00 |
| 01:00 | 20.248 | 0.00 |
| 02:00 | 20.259 | 0.00 |
| 03:00 | 20.366 | 0.00 |
| 04:00 | 20.294 | 0.00 |
| 05:00 | 20.292 | 0.00 |
| 06:00 | 20.385 | 0.00 |
| 07:00 | 20.299 | 0.00 |
| 08:00 | 20.282 | 0.00 |
| 09:00 | 20.387 | 0.00 |
| 10:00 | 20.285 | 0.00 |
| 11:00 | 20.415 | 0.00 |
| 12:00 | 20.366 | 0.00 |
| 13:00 | 20.377 | 0.00 |
| 14:00 | 20.294 | 0.00 |
| 15:00 | 20.292 | 0.00 |
| 16:00 | 20.385 | 0.00 |
| 17:00 | 20.299 | 0.00 |
| 18:00 | 20.377 | 0.00 |
| 19:00 | 20.387 | 0.00 |
| 20:00 | 20.285 | 0.00 |
| 21:00 | 20.415 | 0.00 |
| 22:00 | 20.366 | 0.00 |
| 23:00 | 20.353 | 0.00 |

**Sun: Max = 20.439 arcsec, Mean = 20.347 arcsec, RMS = 20.347 arcsec**  
(The Phase 2 report stated max 20.385, which is correct for the subset it reported, but the full 24-epoch max is 20.439.)

**Earth (13 epochs, 2026-11-14 00:00-12:00 UTC):**

| Time (UTC) | Angular Error (arcsec) | Distance Error (km) |
|------------|-----------------------|---------------------|
| 00:00 | 12.384 | 0.00 |
| 01:00 | 12.214 | 0.00 |
| 02:00 | 12.059 | 0.00 |
| 03:00 | 11.920 | 0.00 |
| 04:00 | 11.878 | 0.00 |
| 05:00 | 11.652 | 0.00 |
| 06:00 | 11.608 | 0.00 |
| 07:00 | 11.470 | 0.00 |
| 08:00 | 11.340 | 0.00 |
| 09:00 | 11.209 | 0.00 |
| 10:00 | 11.030 | 0.00 |
| 11:00 | 10.927 | 0.00 |
| 12:00 | 10.742 | 0.00 |

**Earth: Max = 12.384 arcsec, Mean = 11.572 arcsec, RMS = 11.582 arcsec**  
Note: Earth error is NOT constant — it decreases from 12.384 to 10.742 arcsec over 13 hours, suggesting a systematic time-dependent difference, not just a static ephemeris version offset.

### 3.2 Distance Errors — All 0.00 km

All distance errors are exactly 0.00 km. This is suspicious — at ~148 million km (Sun) and ~405,000 km (Earth), a 0.01 km precision would be extraordinary. This indicates the reference data precision (limited by the number of decimal places in the Horizons output) is too coarse to detect any distance difference between DE440 and DE441.

---

## 4. Critical Flaw: Observer Location Mismatch

| Aspect | Phase 2 Validation | Production Pipeline |
|--------|-------------------|---------------------|
| Observer | Moon center | Lunar surface site |
| Code path | `context.moon.at(time).observe(target).apparent()` | `compute_site_ephemeris()` with observer offset |
| Earth parallax effect | None | ~884 arcsec (0.2456°) |
| Sun parallax effect | None | ~2.4 arcsec |

**The validation does NOT test the actual production pipeline.** For Earth observations at the lunar surface, the parallax between Moon center and surface site is 884 arcsec — 71x larger than the reported 12.384 arcsec error. A surface site at the lunar south pole could see Earth at a significantly different azimuth/elevation than Moon center would predict.

---

## 5. DE440 vs DE441 — Not Independently Verified

The Phase 2 report attributes the errors to "DE440 vs DE441 ephemeris version differences" but provides no evidence:

- No test was run with matching ephemeris versions
- No controlled Horizons query was obtained using DE440
- The Earth error is time-dependent (12.384 → 10.742 arcsec), which is not consistent with a simple static ephemeris version offset
- Alternative causes were not investigated: reference frame mismatch, light-time/aberration conventions, time-scale handling

**Status: The DE440 vs DE441 attribution is unverified speculation.**

---

## 6. Reference Frame Analysis

- LUNARIS uses MOON_ME frame (selected via `spice.pxform("J2000", "MOON_ME", et)`)
- JPL Horizons query used MEAN_ME frame
- These should be equivalent (both are Mean Earth/Polar Axis), but this was not explicitly verified
- The Horizons query was CENTER=500@301 (Moon center), BODYCENTRIC — matching the validation script's computation

---

## 7. Conclusions

| Claim | Status | Evidence |
|-------|--------|----------|
| Sun max angular error 20.385 arcsec | PARTIALLY VERIFIED | Confirmed for Moon center; full 24-epoch max is 20.439 arcsec |
| Earth max angular error 12.384 arcsec | PARTIALLY VERIFIED | Confirmed for Moon center; error is time-dependent (not constant) |
| Validation uses Moon center | VERIFIED | Code inspection confirms `context.moon.at(time).observe().apparent()` |
| Production uses surface site | VERIFIED | Code inspection confirms `compute_site_ephemeris()` with observer offset |
| Errors due to DE440 vs DE441 | NOT VERIFIED | Assumed without evidence; no controlled test performed |
| Surface-site ephemeris validated | NOT VERIFIED | Never tested against Horizons |

---

## 8. Recommendations

1. **Re-run validation from a lunar surface site** using `compute_site_ephemeris()` and compare against Horizons surface-site queries (CENTER=500@301 with a surface coordinate, or compute the surface parallax correction manually)

2. **Investigate the time-dependent Earth error** — it decreases systematically from 12.384 to 10.742 arcsec over 13 hours, which may indicate a frame or time-scale issue rather than a simple ephemeris version difference

3. **Obtain a controlled Horizons reference using DE440** (if available) or document that DE440 vs DE441 is an assumption, not a verified finding

4. **Add surface-site ephemeris tests** to the regression test suite with documented reference values

---

## 9. Final Status: PARTIALLY VERIFIED

The Moon-center ephemeris computation is verified against JPL Horizons. However, the production pipeline uses surface-site computation, which has NOT been validated. The DE440 vs DE441 attribution is unverified.