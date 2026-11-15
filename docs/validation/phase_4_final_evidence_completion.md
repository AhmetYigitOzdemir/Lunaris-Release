# LUNARIS — Phase 4 Final Evidence Completion Audit

**Audit type:** Supplementary, audit-only
**Date:** 2026-11-15
**Branch:** main
**Phase 4 status:** ACCEPTED — PHASE 4 COMPLETE WITH QUALIFICATIONS

This document supplements, but does not replace, `docs/validation/phase_4_comprehensive_independent_final_audit.md`.

---

## 1. Kernel provenance findings

Source references:

- `ephemeris_engine.py:454` `get_kernel_coverage()`
- `ephemeris_engine.py:469-475` `_STATE` access and loaded-kernel use
- `ephemeris_engine.py:477-485` SPK coverage query
- `ephemeris_engine.py:487-503` PCK coverage query
- `ephemeris_engine.py:138-213` `init_ephemeris()` kernel loading
- `horizon_analysis.py:1557-1571` `ephemeris_provenance()`

Findings:

- **Kernel file exists vs. kernel loaded:** VERIFIED. `init_ephemeris()` calls `spice.furnsh()` and stores loaded paths in `EphemerisContext.kernels` (`ephemeris_engine.py:148-167`). `get_kernel_coverage()` uses `context.spk_path` and `context.kernels`, not a directory scan.
- **Kernels merely present on disk cannot appear as loaded:** VERIFIED. Coverage is queried only from loaded kernel objects.
- **SPK coverage:** VERIFIED. `spice.spkcov(str(context.spk_path), 10, cover)` is used (`ephemeris_engine.py:478`).
- **PCK coverage:** VERIFIED. `spice.pckcov(str(bpc_path), 31004, cover)` is used (`ephemeris_engine.py:492`).
- **Per kernel and target/frame:** VERIFIED WITH QUALIFICATIONS. SPK coverage is queried for object 10 only; PCK coverage is queried for frame 31004 only. The metadata does not report separate coverage for every body or frame.
- **MOON_ME availability at requested epochs:** NOT VERIFIED. `get_kernel_coverage()` does not call `spice.pxform("J2000", "MOON_ME", et)` for requested epochs. Frame selection checks availability only at `_approximate_et_now()` (`ephemeris_engine.py:172`, `570`).
- **Unloaded or failed kernels:** VERIFIED WITH QUALIFICATIONS. SPK query failure leaves an empty interval list; PCK query failures are skipped. The metadata does not explicitly mark a failed coverage query as failed.
- **Staleness after kernel-pool changes:** VERIFIED WITH QUALIFICATIONS. `get_kernel_coverage()` reads `_STATE` under `_STATE_LOCK` at call time, so normal reinitialization is reflected. External kernel-pool changes without updating `_STATE` would make metadata stale.

## 2. Provenance input accuracy findings

Source references:

- `horizon_analysis.py:1268-1360` `analyze_sunlight_period()`
- `horizon_analysis.py:1040-1241` `find_sun_transitions()`
- `horizon_analysis.py:1534-1654` provenance helpers
- `main.py:387-598` `compare_candidate_sites()`

Findings:

- **Temporal metadata uses actual start/end times and sampling parameters:** VERIFIED. `temporal_provenance()` receives the parsed `start`, `end`, and `step` values used by the calculation (`horizon_analysis.py:1356-1358`, `main.py:468-474`).
- **Transition tolerances and reference-horizon settings reflect runtime arguments:** VERIFIED. `find_sun_transitions()` passes `tol`, `elev_tol`, `max_iter`, and `reference` into `temporal_provenance()` (`horizon_analysis.py:1233-1241`).
- **Spatial metadata reflects actual center, radius, step, and distance convention:** VERIFIED. `spatial_provenance()` uses the supplied latitude, longitude, radius, step, sample count, and valid count (`horizon_analysis.py:1596-1618`).
- **Terrain metadata distinguishes configured resolution from measured effective resolution:** VERIFIED WITH QUALIFICATIONS. `configured_resolution_m` comes from the DEM/profile; `resolution_status` states that effective resolution is limited by pixel size and ray sampling (`horizon_analysis.py:1534-1554`).
- **Ephemeris metadata reflects backend, frame, and loaded kernels:** VERIFIED. `ephemeris_provenance()` uses `get_engine_status()` and `get_kernel_coverage()` (`horizon_analysis.py:1557-1571`).
- **Software and algorithm versions are not fabricated or misleading:** VERIFIED WITH QUALIFICATIONS. `software_provenance()` reports a metadata schema version and algorithm labels, not an application release version (`horizon_analysis.py:1621-1631`).
- **Missing information is represented explicitly:** VERIFIED. Unavailable sites return `provenance: None`; unavailable ephemeris returns `ready: False`; missing transition tolerances in `analyze_sunlight_period` are `None`.

## 3. API backward-compatibility findings

Source references:

- `main.py:387-598` `compare_candidate_sites()`
- `main.py:441`, `531`, `579` provenance placement
- `main.py:420-443` and `548-581` existing response fields

Findings:

- **Existing endpoint paths unchanged:** VERIFIED.
- **Existing request schemas unchanged:** VERIFIED.
- **Existing response keys and data types preserved:** VERIFIED. The diff adds only `provenance` fields.
- **New provenance block is additive:** VERIFIED.
- **Error responses remain compatible:** VERIFIED. Exception handling paths are unchanged except for additive `provenance: None`.
- **Frontend consumers do not break:** VERIFIED WITH QUALIFICATIONS. No frontend tests were run, but the change is additive and existing keys are preserved.
- **No unexpected serialization failures:** VERIFIED. JSON serialization of a real candidate-comparison response and kernel-coverage response succeeded.

## 4. Serialization and test-quality findings

Source references:

- `tests/test_provenance.py`
- `horizon_analysis.py:1524-1654`
- `ephemeris_engine.py:454-518`

Findings:

- **NumPy values:** VERIFIED WITH QUALIFICATIONS. Provenance values are converted to Python floats/ints or strings; no NumPy arrays are placed in provenance. Direct NumPy scalar serialization was not explicitly tested.
- **Python datetime values and UTC timestamps:** VERIFIED. `_provenance_iso()` converts `datetime` values to UTC ISO strings (`horizon_analysis.py:1524-1531`).
- **`None`, NaN, and infinity:** VERIFIED WITH QUALIFICATIONS. `None` is handled in `_provenance_iso()` and spatial summaries. NaN/infinity in provenance inputs were not explicitly tested.
- **Missing kernel information:** VERIFIED WITH QUALIFICATIONS. `ephemeris_provenance()` handles `ready: False` and returns `loaded_kernel_count: 0`. The test is conditional and does not force a missing-kernel scenario.
- **Empty or unavailable metadata:** VERIFIED WITH QUALIFICATIONS. `neighborhood_provenance()` can receive zero valid samples, but this path was not explicitly tested.
- **JSON serialization of actual API responses:** VERIFIED. A real candidate-comparison response and kernel-coverage response were serialized successfully.
- **Tests verify actual values and runtime configuration:** VERIFIED WITH QUALIFICATIONS. Some tests check exact values (`terrain_provenance`, `temporal_provenance`, `spatial_provenance`). `test_ephemeris_provenance_loaded_kernels` is conditional and only checks partial kernel information. No test verifies candidate-comparison provenance or missing-kernel behavior.

## 5. Repository integrity findings

Source references:

- `git status --short`
- `git diff --stat`

Findings:

- **Tracked modifications:** `ephemeris_engine.py`, `horizon_analysis.py`, `main.py`, `tests/test_candidate_comparison.py`.
- **Untracked Phase 3/4 artifacts:** preserved.
- **No deletions detected.**
- **No staging, commit, or push performed.**

**VERIFIED**

## 6. Defects found

No critical or major defects were found.

Moderate defects:

1. Provenance does not verify `MOON_ME` availability at requested calculation epochs.
2. Provenance does not compare loaded kernel coverage intervals against the requested analysis interval.
3. Terrain provenance uses a fixed DEM identifier even when the Plotly fallback is used.
4. SPK/PCK coverage is reported for one object/frame rather than all relevant bodies/frames.

Minor defects:

1. No test for candidate-comparison provenance.
2. No test for missing-kernel or empty-metadata behavior.
3. `loaded_kernels` includes all loaded kernel types, while coverage is reported for selected kernels only.
4. `kernel_coverage` reports an empty interval list as success rather than an explicit failure.

## 7. Final decision

**1. ACCEPTED — PHASE 4 COMPLETE WITH QUALIFICATIONS**

Phase 4 is complete at the implemented scope. The remaining items are evidence and metadata-coverage qualifications, not blockers to acceptance. No Phase 5 work was started.
