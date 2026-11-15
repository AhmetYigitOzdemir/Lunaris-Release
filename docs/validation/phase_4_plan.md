# LUNARIS — Phase 4 Plan

**Status:** COMPLETE (WP4.1, WP4.2, and WP4.3 implemented)
**Date:** 2026-11-15
**Predecessor:** Phase 3 PASS WITH QUALIFICATIONS

---

## 1. Phase 4 objective

Improve the scientific usefulness and interpretability of point-based lunar south-pole analysis by (a) integrating Phase 3 transition timing into candidate-site comparison, and (b) adding spatial representativeness/uncertainty scaffolding so that point results are not mistaken for regional conclusions.

## 2. Scientific motivation

Phase 3 established temporal illumination behavior and long-cycle PSR pre-screens, but the independent audit identified a recurring limitation: results are point analyses. Candidate comparison currently reports instantaneous visibility and aggregated illumination, but not transition timing or local spatial sensitivity. Phase 4 addresses these gaps without overstating regional coverage.

## 3. Current limitations being addressed

- Point analysis is reported as if it represented a region.
- Candidate comparison does not expose sunrise/sunset transition times.
- Temporal and spatial (slope/LSI) results are not jointly summarized.
- No explicit provenance metadata accompanies analysis outputs.

## 4. Relevant source modules

- `main.py` — FastAPI endpoints and candidate comparison.
- `horizon_analysis.py` — illumination, transitions, horizon, slope, LSI.
- `candidate_sites.py` — representative site catalogue.
- `coordinate_transform.py` — projection/inverse projection for spatial neighborhoods.
- `ephemeris_engine.py` — Sun/Earth geometry.
- `tests/` — regression tests.

## 5. Proposed architecture

- Add transition timing fields to candidate comparison output using `find_sun_transitions`.
- Add pure spatial-neighborhood coordinate generation and summary statistics for future regional sensitivity analysis.
- Add provenance metadata (constants, kernel filenames, DEM source, parameters) to analysis responses.

## 6. Mathematical methods

- Transition timing: bisection on `f(t) = solar_elevation(t) − terrain_horizon(azimuth(t))`, as in Phase 3.
- Spatial neighborhood: offsets in the polar-stereographic plane converted to latitude/longitude via `polar_stereographic_to_latlon`; summary statistics (mean, standard deviation, min, max, valid count) over sampled point values.
- No new physical model is introduced; LSI and illumination equations are unchanged.

## 7. Data requirements

- Existing LOLA DEM and SPICE kernels.
- Candidate catalogue coordinates.
- No new datasets.

## 8. Validation methodology

- Unit tests for transition-field propagation in candidate comparison.
- Unit tests for neighborhood coordinate generation and statistics.
- Regression test suite after each work package.
- Independent verification of sample counts and denominators.

## 9. Acceptance criteria

- Candidate comparison includes transition count and first sunrise/sunset times when available.
- Transition failures do not fail the entire comparison.
- Neighborhood utilities are pure, tested, and documented as point-sensitivity scaffolding, not regional mapping.
- No LSI modification without demonstrated dependency.
- All tests pass.

## 10. Risks and limitations

- Transition detection remains subject to WP2 limitations (grazing, short intervals, tolerance).
- Spatial neighborhood analysis is still point sampling, not continuous regional mapping.
- Runtime increases with transition detection and neighborhood size.

## 11. Work packages

### WP4.1 — Transition-aware candidate comparison

- Objective: expose sunrise/sunset transition timing for each candidate in the shared mission window.
- Inputs: candidate site, horizon profile, mission window, step_minutes.
- Outputs: transition_count, first_sunrise_utc, first_sunset_utc (nullable).
- Scope: modify `compare_candidate_sites`; update tests and mocks.
- Tests: candidate comparison transition fields.
- Validation: mocked unit tests; no fabricated runtime values.
- Completion: tests pass and fields present.

### WP4.2 — Spatial representativeness scaffolding (planned)

- Objective: generate and summarize small neighborhoods around a site.
- Inputs: latitude, longitude, radius_m, step_m.
- Outputs: neighbor coordinates and summary statistics.
- Scope: pure utilities in `horizon_analysis.py` or a new module; no endpoint yet.
- Tests: coordinate round-trip and statistics.
- Validation: synthetic inputs.
- Completion: tests pass.

### WP4.3 � Provenance metadata (implemented)

- Objective: attach analysis parameters and data-source identifiers to outputs.
- Inputs: request parameters, DEM source, kernel filenames.
- Outputs: provenance block.
- Scope: helper function + endpoint integration.
- Tests: provenance fields.
- Validation: schema checks.
- Completion: tests pass.

## 12. Estimated implementation complexity

- WP4.1: Low–Medium.
- WP4.2: Medium.
- WP4.3: Low.

WP4.1, WP4.2, and WP4.3 are implemented. Phase 4 is complete with qualifications.
