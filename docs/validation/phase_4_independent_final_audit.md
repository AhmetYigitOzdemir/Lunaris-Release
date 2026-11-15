# LUNARIS — Phase 4 Independent Final Audit

**Date:** 2026-11-15
**Phase 4 status:** COMPLETE WITH QUALIFICATIONS
**Phase 3 status preserved:** PASS WITH QUALIFICATIONS

---

## A. Initial repository state

- Branch: `main`.
- Uncommitted changes in `horizon_analysis.py`, `main.py`, `tests/test_candidate_comparison.py`.
- New untracked Phase 3/4 artifacts present and preserved.
- No commits or pushes performed.

## B. WP4.3 implementation

Files changed:

- `ephemeris_engine.py` — added `get_kernel_coverage()` querying loaded SPK/PCK intervals.
- `horizon_analysis.py` — added provenance helpers: `terrain_provenance`, `ephemeris_provenance`, `temporal_provenance`, `spatial_provenance`, `software_provenance`, `neighborhood_provenance`, plus `_provenance_iso`.
- `main.py` — candidate comparison now includes a `provenance` block.
- `analyze_sunlight_period` and `find_sun_transitions` outputs include `provenance`.
- `tests/test_provenance.py` — 7 focused tests.

Metadata schema:

- Terrain: DEM identifier, basename source, configured resolution, reference radius, projection, documented coverage, resolution status.
- Ephemeris: backend, readiness, frame, frame source, SPK, loaded kernels, loaded kernel count, runtime kernel coverage, coverage status.
- Temporal: UTC start/end, time standard, sampling interval, transition tolerances, reference horizon.
- Spatial: center coordinates, radius, step, distance convention, sample/valid counts, standard-deviation convention, coverage claim.
- Software: application, metadata schema version, phase, algorithm versions.

Limitations:

- Terrain coverage is documented nominal coverage, not runtime-measured.
- DEM source path is reduced to basename to avoid leaking machine-specific paths.
- Metadata is additive and does not alter scientific calculations.

## C. WP4.1 verification

- Transition integration uses `find_sun_transitions()` per candidate.
- Shared mission window is used for illumination and transitions.
- `transition_count` counts detected events.
- `first_sunrise_utc` and `first_sunset_utc` are first events of each type or `None`.
- Exceptions are isolated per candidate.
- Real integration: 9 candidates processed; transitions detected for HW04 and MMP01.

Status: **PASS WITH QUALIFICATIONS** (default tolerance and WP2 detection limits remain).

## D. WP4.2 verification

- Neighborhood coordinates are generated in the polar-stereographic plane and converted back to lat/lon.
- Forward/inverse projection round-trip error = 0.0° in tested cases.
- Center point is included.
- All generated coordinates finite and unique in tested grids.
- Statistics use population standard deviation and exclude non-finite values.
- `radius_m` and `step_m` are projection-plane distances, not lunar surface geodesic distances.

Status: **PASS WITH QUALIFICATIONS** (sampling scaffold, not regional mapping).

## E. Test results

Commands:

```text
python -m pytest tests/ -q -p no:cacheprovider
python -m pytest tests/test_provenance.py -q -p no:cacheprovider
python tests/validation/audit_wp3_independent.py
python tests/validation/audit_wp4_independent.py
python tests/validation/kernel_coverage_check.py
```

Results:

- `tests/`: **58 passed, 0 failed**.
- `tests/test_provenance.py`: **7 passed**.
- Candidate comparison integration: **9 sites**, provenance present.
- WP3/WP4 independent scripts: successful.
- Kernel coverage: SPK 1849-12-25 to 2150-01-21; PCK 1949-12-31 to 2050-12-30; `MOON_ME` available at WP4 endpoints.

Unit vs integration:

- Unit: provenance structure, terrain/temporal/spatial fields, mocked candidate comparison.
- Integration: full candidate comparison with real DEM/kernels, neighborhood coordinate generation, kernel coverage queries.

## F. Scientific limitations

- Grazing transition detection is not supported by sign-change bracketing.
- Short illumination intervals shorter than the coarse step can be missed.
- Transition timing depends on `elev_tol_deg` and coarse-step alignment.
- Neighborhood distances are projection-plane (Euclidean) approximations.
- Population standard deviation is used, not sample standard deviation.
- Point sampling is not continuous regional mapping.
- Terrain coverage is documented nominal coverage, not runtime-measured.
- No primary-literature ground truth was used for PSR classifications.
- WP4.3 provenance documents configuration but does not certify data accuracy.

## G. Final decision

- WP4.1: **PASS WITH QUALIFICATIONS**
- WP4.2: **PASS WITH QUALIFICATIONS**
- WP4.3: **PASS WITH QUALIFICATIONS**
- Phase 4 overall: **COMPLETE WITH QUALIFICATIONS**

Phase 4 is complete at the implemented scope. WP4.3 is implemented. No Phase 5 work was started. No commits or pushes were performed.
