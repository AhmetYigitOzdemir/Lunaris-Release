# LUNARIS — Phase 2.1 LSI Scientific Claim Audit

**Date:** 2026-11-15  
**Status:** PARTIALLY VERIFIED  
**Stage:** 5 — LSI Scientific Claim Audit

---

## 1. Audit Objective

Independently verify the Landing Suitability Index (LSI) implementation:
- Mathematical formula and normalization
- Weighting (0.7 slope / 0.3 roughness)
- Missing-data handling
- Boundary behavior
- Monotonicity
- Score interpretation and class thresholds
- Empirical justification for weights and thresholds

---

## 2. Implementation Review

**File:** `horizon_analysis.py:709-872`

### 2.1 Mathematical Formula

```
LSI = 0.7 × slope_component + 0.3 × roughness_component
```

Where both components are in [0, 100], so LSI ∈ [0, 100].

### 2.2 Slope Score Function (`_slope_score`, line 709)

| Slope (°) | Score | Formula |
|-----------|-------|---------|
| ≤ 5.0 | 100.0 | Constant |
| 5.0–8.0 | 100 − (s−5)/3 × 40 | Linear decay, 40 points over 3° |
| 8.0–15.0 | 60 − (s−8)/7 × 60 | Linear decay, 60 points over 7° |
| > 15.0 | 0.0 | Constant |

### 2.3 Roughness Score Function (`_roughness_score`, line 719)

| Roughness (m) | Score | Formula |
|---------------|-------|---------|
| ≤ 0.5 | 100.0 | Constant |
| 0.5–2.0 | 100 − (r−0.5)/1.5 × 50 | Linear decay, 50 points over 1.5 m |
| > 2.0 | max(0, 50 − (r−2) × 10) | Linear decay, 10 points per m |

### 2.4 Class Thresholds

| Score | Class |
|-------|-------|
| ≥ 85 | A |
| ≥ 70 | B |
| ≥ 50 | C |
| < 50 | D |

---

## 3. Verification Results

### 3.1 Monotonicity — VERIFIED

Both component scores are monotonically non-increasing:
- `_slope_score`: score(5°)=100, score(8°)=60, score(15°)=0
- `_roughness_score`: score(0.5m)=100, score(2.0m)=50, score(7m)=0
- LSI weighted sum: monotonically non-increasing

**Source:** `tests/validation/test_lsi_monotonicity.py` — all 4 tests pass.

### 3.2 Score Range — VERIFIED

LSI = 0.7 × [0,100] + 0.3 × [0,100] = [0, 100]. Confirmed by code inspection and test.

### 3.3 Class Thresholds — VERIFIED

Boundary values (85, 70, 50) produce correct class assignments.

---

## 4. Issues Identified

### 4.1 No Empirical Justification for Weights (MAJOR)

| Parameter | Value | Justification in Code | Published Source |
|-----------|-------|----------------------|------------------|
| Slope weight | 0.7 | None (hardcoded) | None cited |
| Roughness weight | 0.3 | None (hardcoded) | None cited |
| Slope threshold 1 | 5.0° | "Commonly used lunar landing screens" (comment) | No citation |
| Slope threshold 2 | 8.0° | Same comment | No citation |
| Slope threshold 3 | 15.0° | None | None cited |
| Roughness threshold 1 | 0.5 m | None | None cited |
| Roughness threshold 2 | 2.0 m | None | None cited |
| Roughness threshold 3 | 7.0 m | None | None cited |
| Class threshold A | 85 | None | None cited |
| Class threshold B | 70 | None | None cited |
| Class threshold C | 50 | None | None cited |

**Finding:** The 0.7/0.3 weights and all thresholds are heuristic with no cited empirical or published justification. The code comment states "Slope thresholds follow commonly used lunar landing screens (5° goal, 8° limit)" but provides no reference.

### 4.2 Missing-Data Handling Asymmetry

| Cell Type | Slope Component | Roughness Component | Result |
|-----------|----------------|---------------------|--------|
| Border cell (no full 3×3) | Computed via edge gradient | NaN → score 100 (best) | slope + 100 roughness |
| Interior cell (no full 3×3) | 0.0 (worst) | NaN → score 100 (best) | 0 + 100 roughness |
| Valid interior cell | Computed | Computed | Normal |

**Finding:** The handling is asymmetric:
- Border cells get a computed slope but best-possible roughness (100)
- Interior cells without full 3×3 get worst-possible slope (0) but best-possible roughness (100)

This means a cell lacking a 3×3 neighborhood gets LSI = 0.7 × 0 + 0.3 × 100 = 30 (Class D), purely due to missing roughness data. This is harsh and not well-justified.

Additionally, non-finite roughness returns score 100 (best), which could artificially inflate LSI in areas where roughness cannot be computed.

### 4.3 Slope Calculation Uses `safe_elevation` (NaN → 0)

Line 773-774:
```python
safe_elevation = np.where(valid, elevation, 0.0)
gradient_y, gradient_x = np.gradient(safe_elevation, spacing, spacing)
```

Invalid DEM cells (NaN) are replaced with 0.0 before computing gradients. This means:
- Cells adjacent to invalid data get artificially steep or shallow slopes depending on the 0.0 replacement
- A cliff edge next to a NoData cell would show an extreme gradient (real elevation vs 0.0)
- This is a form of silent data substitution that could distort slope calculations near DEM edges

### 4.4 LSI Score Interpretation

The code does NOT state that the LSI is:
- A probability of landing success
- Calibrated against empirical landing data
- Comparable across different landing architectures

The docstring says "Compute a 0-100 landing suitability index" but does not qualify it as heuristic. The note at the end says "Screening only" but does not explicitly state the weights are uncalibrated.

---

## 5. Comparison with Published Lunar Landing Standards

Published lunar landing site selection criteria typically consider:
- Slope: Typically < 5-10° for safe landing (varies by lander design)
- Roughness: Typically measured at lander scale (1-10 m), not 120 m (3×3 at 40 m)
- Boulder abundance: Critical for lander safety, not modeled
- Approach vector, lighting, comms: Not modeled

The LUNARIS LSI does not cite any of these standards. The 5°/8° slope thresholds mentioned in the code comment are consistent with some published guidelines, but the specific scoring functions and weights are not.

---

## 6. Recommendations

1. **Explicitly label as heuristic:** Add documentation stating the LSI is an exploratory scoring model with uncalibrated weights
2. **Do not present as probability:** The 0-100 score and A-D class should not be interpreted as landing success probability
3. **Fix missing-data asymmetry:** Either exclude cells without full 3×3 neighborhoods from LSI computation, or assign them a neutral score rather than best/worst extremes
4. **Fix NoData substitution:** Do not replace NaN with 0.0 before gradient computation; use masked arrays or exclude edge cells adjacent to invalid data
5. **Cite sources if adopting standard thresholds:** If 5°/8° slope thresholds are from a published standard, cite it

---

## 7. Conclusion

| Aspect | Status |
|--------|--------|
| Mathematical formula | VERIFIED (0.7 slope + 0.3 roughness, range [0,100]) |
| Monotonicity | VERIFIED (all component scores monotonically non-increasing) |
| Class thresholds | VERIFIED (correct at boundaries) |
| Weight justification (0.7/0.3) | NOT VERIFIED — no empirical or published source |
| Threshold justification (5°, 8°, 15°, 0.5m, 2m, 7m) | NOT VERIFIED — no citations |
| Missing-data handling | ISSUE IDENTIFIED — asymmetric treatment of border/interior cells |
| NoData handling | ISSUE IDENTIFIED — NaN replaced with 0.0 before gradient |
| Score interpretation | NOT DOCUMENTED as heuristic |

**Overall: PARTIALLY VERIFIED** — The LSI implementation is numerically well-behaved (monotonic, correct range), but the weights and thresholds are uncalibrated heuristics with no published justification. Missing-data handling has asymmetries that could distort results.