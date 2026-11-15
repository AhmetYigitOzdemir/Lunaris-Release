# Plan 2 — Local Slope and Landing-Safety Pre-Screen

## Objective

Make local terrain slope and roughness visible around a selected site, and compare representative candidates using the same local metrics.

## Scope

1. Generate slope samples in a local projected plane within a 1 km radius of the selected site from the LOLA DEM.
2. Classify each pixel as preferred (≤5°), marginal (5–8°), or steep (>8°), while excluding invalid DEM samples from coverage.
3. Calculate a planar-detrended 3×3 roughness RMS summary.
4. Expose the slope grid and area fractions through the API, then include the ≤8° fraction in the HUD map and candidate-comparison table.
5. Clearly state that a 40 m DEM cannot resolve individual rocks or landing-gear-scale hazards.

## Acceptance Criteria

- A flat synthetic DEM returns 100% ≤5° area and near-zero roughness.
- A tilted plane returns the expected analytic slope while retaining low roughness.
- Partial DEM coverage appears as empty map cells with a separate coverage fraction.
- Candidate comparison returns slope metrics for every region using the operational DEM.
