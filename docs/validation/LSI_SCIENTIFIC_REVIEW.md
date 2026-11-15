# LUNARIS — LSI Scientific Review

**Date:** 2026-11-15  
**Status:** REVIEWED (heuristic, not calibrated)  
**Validation type:** Code inspection + monotonicity verification

---

## 1. Review Objective

Evaluate the Landing Suitability Index (LSI) for scientific soundness, monotonicity, missing-data handling, and calibration status.

---

## 2. Implementation Summary

**File:** `horizon_analysis.py:729-866` (`calculate_landing_suitability_index`)

### 2.1 Inputs

| Parameter | Default | Range |
|-----------|---------|-------|
| latitude_deg | required | [-90, 0] |
| longitude_deg | required | any (wrapped to [0,360)) |
| radius_m | 1000 | (0, 5000] |
| cell_size_m | native resolution (40 m) | (0, 1000] |

### 2.2 Computation Pipeline

1. Project site to polar-stereographic x/y (`latlon_to_polar_stereographic`)
2. Sample elevation grid within radius at cell spacing
3. Compute slope: `degrees(arctan(hypot(dz/dx, dz/dy)))` using central differences
4. Compute roughness: RMS of planar detrending residuals over 3×3 windows
5. Apply per-cell scoring functions
6. Weighted sum: `LSI = 0.7 × slope_score + 0.3 × roughness_score`
7. Average over valid cells, clamp to [0, 100]
8. Assign class: A (≥85), B (≥70), C (≥50), D (<50)

### 2.3 Scoring Functions

**Slope score** (`_slope_score`, line 709):

| Slope (°) | Score |
|-----------|-------|
| ≤ 5 | 100 |
| 5–8 | 100 − (s−5)/3 × 40 |
| 8–15 | 60 − (s−8)/7 × 60 |
| > 15 | 0 |

**Roughness score** (`_roughness_score`, line 719):

| Roughness (m) | Score |
|---------------|-------|
| ≤ 0.5 | 100 |
| 0.5–2.0 | 100 − (r−0.5)/1.5 × 50 |
| > 2.0 | max(0, 50 − (r−2) × 10) |

---

## 3. Verification Results

### 3.1 Monotonicity (verified)

| Function | Status | Key values |
|----------|--------|------------|
| `_slope_score` | MONOTONIC non-increasing | score(5°)=100, score(8°)=60, score(15°)=0 |
| `_roughness_score` | MONOTONIC non-increasing | score(0.5m)=100, score(2.0m)=50, score(7m)=0 |
| LSI (weighted sum) | MONOTONIC non-increasing | Range [0, 100] |

Both component scores and the weighted LSI are monotonically non-increasing with respect to their inputs. No non-monotonic behavior detected.

### 3.2 Score range (verified)

LSI = 0.7 × slope_score + 0.3 × roughness_score, where both components are in [0, 100]. Therefore LSI ∈ [0, 100]. Confirmed by code inspection and test.

### 3.3 Class thresholds (verified)

| Score range | Class |
|-------------|-------|
| ≥ 85 | A |
| ≥ 70 | B |
| ≥ 50 | C |
| < 50 | D |

Confirmed correct at boundary values (85, 70, 50).

### 3.4 Missing data handling

| Situation | Behavior |
|-----------|----------|
| Non-finite roughness | Score = 100 (best) |
| Invalid DEM cell (NaN) | Skipped from LSI average |
| Cell without full 3×3 neighborhood | slope_valid = False → slope_component = 0 |
| Patch border cells | Allowed slope (edge gradient), no roughness |
| All cells invalid | LSI = 0.0 |

Non-finite roughness receiving score 100 is a design choice that may overestimate suitability in areas where roughness cannot be computed.

---

## 4. Calibration Status

### 4.1 Heuristic, not calibrated

| Parameter | Value | Source |
|-----------|-------|--------|
| Slope weight | 0.7 | Heuristic (undocumented rationale) |
| Roughness weight | 0.3 | Heuristic (undocumented rationale) |
| Slope thresholds | 5°, 8°, 15° | "Commonly used lunar landing screens" (code comment, no citation) |
| Roughness thresholds | 0.5 m, 2.0 m, 7.0 m | Heuristic (undocumented rationale) |
| Class thresholds | 85, 70, 50 | Heuristic (undocumented rationale) |

**No published lunar landing standard supports these specific values.** The code comment states "Slope thresholds follow commonly used lunar landing screens (5° goal, 8° limit)" but provides no citation.

### 4.2 Compatibility of scales

- Slope score spans 0–100 over 0–15° slope
- Roughness score spans 0–100 over 0–7 m roughness
- Both use the same 0–100 scale, making the weighted sum dimensionally consistent
- However, the relative importance of slope vs. roughness (70/30) is not justified by any cited source

---

## 5. Limitations

| Limitation | Impact |
|------------|--------|
| **Uncalibrated weights** | LSI score has no empirical meaning; Class A/B/C/D cannot be interpreted as landing safety probabilities |
| **No published citation** | 5°/8° slope thresholds attributed to "commonly used" screens without source |
| **Roughness = 100 for non-finite** | May overestimate suitability where roughness is uncomputable |
| **40 m DEM resolution** | Cannot resolve small rocks, crater rims, or lander-footprint hazards (documented) |
| **Single-point score** | LSI is averaged over a patch; local hazards within the patch are smoothed over |
| **No landing architecture inputs** | Does not account for lander mass, leg span, approach vector, etc. |

---

## 6. Recommendations

1. **Document as heuristic:** Explicitly state in API responses and documentation that LSI is an exploratory scoring model, not a certified landing-safety assessment
2. **Do not present as probability:** The 0–100 score and A–D class should not be interpreted as probability of successful landing
3. **Consider alternative weights:** If credible literature supports different slope/roughness weights or thresholds, document the source and applicability
4. **Add uncertainty reporting:** Report the spread of LSI scores within the patch (e.g., standard deviation) alongside the mean

---

## 7. Conclusion

The LSI implementation is **internally consistent and numerically well-behaved** (monotonic, correct range, correct class thresholds). However, it is **heuristic and uncalibrated** — the 0.7/0.3 weights, slope thresholds, and roughness thresholds are not supported by any cited publication. The LSI should be presented as a comparative research indicator, not a certified landing-safety assessment.

---

## 8. Reproduction

Run the monotonicity verification:

```bash
python tests/validation/test_lsi_monotonicity.py
```

Run the existing LSI tests:

```bash
python -m pytest tests/test_horizon_analysis.py -k "landing" -v
```