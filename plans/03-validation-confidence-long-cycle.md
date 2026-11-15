# Plan 3 — Validation, Data Confidence, and Long-Cycle PSR Screening

## Objective

Make the data quality and sampling resolution behind each result explicit, and extend annual permanently shadowed region (PSR) pre-screening across the Moon's 18.6-Earth-year nodal cycle.

## Scope

1. Bind candidate tests to one coordinate catalogue and continue validating DEM coverage, terrain horizons, and solar ephemerides at all nine regions.
2. Add a PSR nodal-cycle screening API using hourly illumination samples over the 18.6-Earth-year interval.
3. Return DEM coverage, DEM pixel size, horizon-ray range, and analysis time step as separate quality indicators.
4. Run annual and 18.6-year screens separately from the HUD; label a candidate indeterminate when coverage is partial.
5. Retain candidate classifications as pre-screen results and ensure tests verify the expected coverage and resolution.

## Acceptance Criteria

- The 18.6-Earth-year hourly screen remains within the 200,000-sample cap.
- No observed Sun across a fully known interval yields a cycle pre-candidate; an observed Sun yields not a candidate; incomplete data yields an indeterminate result.
- Results never assert `is_permanently_shadowed=true`.
- Long-duration results show time coverage, DEM resolution, ray step, and terrain-horizon range.
- Pytest covers every candidate site and long-cycle classification state.
