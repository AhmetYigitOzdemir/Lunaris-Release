# LUNARIS — DEM and Terrain Analysis Validation

**Date:** 2026-11-15  
**Status:** VALIDATED (coordinate geometry + existing tests)  
**Validation type:** PDS3 label inspection + coordinate round-trip tests + existing synthetic DEM tests

---

## 1. DEM Specification

**Product:** LRO-L-LOLA-4-GDR-V1.0, `LDEM_80S_40M_FLOAT`

| Parameter | Value | Source |
|-----------|-------|--------|
| Projection | Polar stereographic (south pole) | PDS3 label line 75 |
| Reference sphere | 1737.4 km | PDS3 label line 58, 78-80 |
| Resolution | 40 m/pixel | PDS3 label line 93 |
| Grid size | 15200 × 15200 pixels | PDS3 label lines 50-51 |
| Data type | 32-bit float (PC_REAL) | PDS3 label lines 54-55 |
| Units | km above reference sphere | PDS3 label line 56 |
| Offsets | LINE=7599.5, SAMPLE=7599.5 | PDS3 label lines 98-99 |
| Coverage | 80°S to 90°S | PDS3 label lines 94-95 |
| Coordinate system | MEAN EARTH/POLAR AXIS OF DE421 | PDS3 label line 101 |
| Elevation range | -7.297 to +7.027 km | PDS3 label lines 52-53 |
| Erroneous points flagged | ~0.004% | PDS3 label lines 28-30 |

---

## 2. Coordinate Geometry Validation (Phase 1 Acceptance)

The DEM pixel axes and the `latlon_to_polar_stereographic` projection are **consistent**. Both use the same polar stereographic parameters (R=1737400 m, k0=1.0 at pole).

### 2.1 Verified test points (real DEM)

| Lat (°S) | Lon (°E) | Col | Row | In Raster | Round-trip error (m) |
|----------|----------|-----|-----|-----------|---------------------|
| 90.0 | 0 | 7599.5 | 7599.5 | Yes | 28.28 |
| 89.0 | 0 | 7599.5 | 8357.6 | Yes | 25.54 |
| 85.0 | 0 | 7599.5 | 11392.3 | Yes | 23.83 |
| 80.5 | 0 | 7599.5 | 14817.8 | Yes | 20.85 |
| 85.0 | 90 | 11392.3 | 7599.5 | Yes | 23.83 |
| 85.0 | 180 | 7599.5 | 3806.7 | Yes | 23.83 |
| 85.0 | 270 | 3806.7 | 7599.5 | Yes | 23.83 |

All round-trip errors are < 40 m (one pixel), consistent with pixel-center quantization. No negative row or out-of-bounds issues with the real DEM.

### 2.2 DEM axis parameters

| Parameter | Expected | Actual | Match |
|-----------|----------|--------|-------|
| Pixel size X | 40.0 m | 40.0 m | Yes |
| Pixel size Y | 40.0 m | 40.0 m | Yes |
| Grid size X | 15200 | 15200 | Yes |
| Grid size Y | 15200 | 15200 | Yes |
| X axis center | ±20 m at pixels 7599/7600 | Confirmed | Yes |
| Y axis direction | Descends (north→south) | Confirmed | Yes |

---

## 3. Terrain Analysis Components

### 3.1 Slope calculation (`horizon_analysis.py:637-638`)

**Method:** Central differences via `np.gradient(elevation, spacing, spacing)`  
**Formula:** `slope = degrees(arctan(hypot(dz/dx, dz/dy)))`

**Validation:** `test_planar_landing_patch_reports_slope_without_false_roughness`  
- Tilted plane `z = 0.2x + 0.1y` returns expected analytic slope `atan(sqrt(0.2² + 0.1²))`  
- Flat plane returns 0° slope  
- Roughness near zero for planar surfaces

**Limitation:** First-order central differences; 40 m pixels cannot resolve sub-pixel terrain features.

### 3.2 Roughness calculation (`horizon_analysis.py:789-804`)

**Method:** Planar detrending over 3×3 windows via least squares  
**Formula:** `roughness = sqrt(mean(residuals²))` where residuals are from fitting `z = c₀ + c₁x + c₂y`

**Validation:** `test_flat_landing_patch_is_fully_low_slope_and_smooth`  
- Flat plane returns roughness ≈ 0 m  
- Tilted plane returns near-zero roughness (planar surfaces have zero residuals after detrending)

**Limitation:** 3×3 window at 40 m spacing = 120 m scale; not comparable to standard RMS height or Hurst exponent roughness metrics.

### 3.3 Terrain horizon calculation (`horizon_analysis.py:351-447`)

**Method:** Ray-casting along great-circle bearings with spherical curvature correction  
**Formula:** `angle = atan2((R+z)·cos(delta) − (R+h), (R+z)·sin(delta))`

**Validation:** `test_flat_dem_has_zero_horizon_and_full_coverage`  
- Flat DEM returns 0° horizon at all azimuths with 100% coverage  
- Curvature correction included via spherical geometry  
- Rays sample DEM bilinearly at 40 m intervals (default = native resolution)

**Limitation:** Default max distance 200 km; horizon beyond this range is not assessed.

### 3.4 Raster edge handling

| Situation | Behavior |
|-----------|----------|
| Coordinate inside raster, valid elevation | Sampled normally |
| Coordinate outside raster bounds | `valid = False`, returns NaN |
| Coordinate inside raster, NaN elevation | `valid = False`, excluded from analysis |
| Horizon ray extends beyond DEM | Coverage fraction < 1.0; angle clamped to -∞ for invalid samples |
| Site outside DEM coverage | `ValueError: Selected site is outside the available DEM coverage` |

No silent substitution of zero or arbitrary values for missing data.

---

## 4. NoData Handling

**File:** `horizon_analysis.py:289-324` (`_bilinear_sample`)

| Step | Action |
|------|--------|
| Coordinate to pixel conversion | Linear interpolation between pixel centers |
| Bounds check | `0 ≤ col ≤ width-1`, `0 ≤ row ≤ height-1` |
| Finite check | `np.isfinite(col) & np.isfinite(row)` |
| Bilinear interpolation | Weighted average of 4 surrounding pixels |
| NaN propagation | `valid &= np.isfinite(values)` — NaN inputs produce NaN output |
| Final output | `np.where(valid, values, NaN)` — invalid samples are NaN |

NoData values are **never silently replaced with zero**. Invalid samples propagate as NaN and are excluded from downstream calculations.

---

## 5. Resolution Limitations

| Analysis | DEM resolution | Effective resolution | Limitation |
|----------|---------------|---------------------|------------|
| Terrain horizon | 40 m | 40 m (ray step = native) | Sub-pixel ridges not resolved |
| Slope | 40 m | 40 m (central differences) | Slopes at scales < 40 m not captured |
| Roughness | 40 m | 120 m (3×3 window) | Small-scale roughness not captured |
| LSI | 40 m | 40–120 m | Landing hazards at lander scale not resolved |

**Key limitation:** 40 m/pixel DEM cannot resolve individual rocks, boulders, crater rims, or lander-footprint-scale hazards. This is documented in code comments, API responses, and the README.

---

## 6. Regional vs Local Assessment

| Assessment type | Spatial scale | Appropriate for LUNARIS? |
|----------------|---------------|--------------------------|
| Regional terrain characterization | 10–1000 km | Yes (DEM covers 80–90°S, ~600 km across) |
| Local landing site screening | 1–2 km | Yes (radius up to 5000 m supported) |
| Lander-scale hazard assessment | < 100 m | No (40 m DEM insufficient) |
| Individual rock/boulder detection | < 10 m | No |

---

## 7. Conclusion

The DEM and terrain analysis components are **validated**:
- Coordinate geometry is consistent with the PDS3 label (round-trip errors < 40 m)
- Slope calculation returns analytically correct results for planar surfaces
- Roughness calculation returns near-zero for planar surfaces
- Horizon calculation returns 0° for flat DEM with full coverage
- NoData values are never silently replaced with zero
- Raster edge handling is correct (bounds checking, NaN propagation)

The primary limitation is the 40 m/pixel resolution, which cannot resolve lander-scale hazards. This is explicitly documented throughout the codebase.

---

## 8. Reproduction

Run DEM/terrain tests:

```bash
python -m pytest tests/test_horizon_analysis.py -k "flat or planar or slope or horizon or dem" -v
```

Run coordinate validation tests:

```bash
python -m pytest tests/test_horizon_analysis.py -k "DemCoordinate" -v
```