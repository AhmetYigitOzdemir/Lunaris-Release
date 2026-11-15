# LUNARIS — Phase 3 Independent Audit

**Overall status: PASS WITH QUALIFICATIONS**

**Date:** 2026-11-15
**Auditor:** Independent Phase 3 audit (resumed and completed)
**Scope:** WP1 temporal constants, WP2 sunrise/sunset transition interpolation, WP3 temporal sampling convergence, WP4 18.6-year PSR pre-screen
**Production code modified:** `horizon_analysis.py` (minimal, justified)
**No commits created. No pushes performed. LSI not modified.**

---

## 1. Executive summary

Phase 3 functionality is substantially sound, but the repository as inherited contained a **syntax error** in the Phase 3 WP2 addition (`find_sun_transitions`) that made the entire `horizon_analysis` module unimportable and broke all 47+ tests. This was corrected minimally. A second, smaller **boundary-condition defect** (the final coarse sampling interval was not bracketed) was also corrected.

Independent recalculation confirmed the **PCB01 denominator inconsistency** in the Phase 3 report: sunlit and shadowed percentages were computed with mixed denominators (known samples vs. all samples). Corrected values are 30.03% sunlit / 69.97% shadowed of **known** samples, or 22.42% / 52.25% of **all** samples, with 25.33% unknown.

WP3 strict monotonic convergence is **not** demonstrated: duration errors are 739 s for 60/30/15-minute sampling and transition-time errors are non-monotonic (161 s, 161 s, 289 s) under the default elevation tolerance. The cause is identified as (a) left-endpoint interval weighting in `analyze_sunlight_period`, (b) coarse-bracket alignment, and (c) early acceptance of a midpoint within `elev_tol_deg = 0.01°`. With a tighter tolerance, all steps reproduce the high-accuracy transition to within ~0–11 s. The 1-minute reference is not ground truth; a bisection-derived reference (sunrise at 2026-11-14T13:47:40.84Z) is used here as the refined reference.

WP4 kernel coverage was independently verified against the actual kernel files: SPK `de440s.bsp` covers 1849-12-25 to 2150-01-21; lunar orientation PCK covers 1949-12-31 to 2050-12-30; `MOON_ME` is available at both interval endpoints. The 18.6-year screen is supported, but remains a **point** pre-screen, not a regional PSR certification.

Final test status: `tests/` 47 passed; `tests/validation/` 4 passed. No LSI changes were made. Overall: **PASS WITH QUALIFICATIONS**.

---

## 2. Repository recovery status

Initial `git status --short` (before this audit's edits):

- Modified: `horizon_analysis.py` (242 insertions, uncommitted) — the previous agent's WP2 addition.
- Untracked: `docs/validation/phase_2_2_independent_audit.md`, `docs/validation/phase_2_2_surface_ephemeris_validation.md`, `docs/validation/phase_3_temporal_analysis.md`, `tests/test_sun_transitions.py`, `tests/validation/wp3_timestep_convergence.py`, `tests/validation/wp3_timestep_convergence_results.json`, `tests/validation/wp4_nodal_cycle_psr.py`, `tests/validation/wp4_nodal_cycle_psr_results.json`, plus prior Phase 2.2 artifacts.

Completed by the previous agent (verified, not assumed correct):

- WP1 constant review and documentation.
- WP2 `find_sun_transitions` implementation + 5 unit tests.
- WP3 convergence script and result JSON.
- WP4 nodal-cycle PSR script and result JSON.
- Phase 3 report `docs/validation/phase_3_temporal_analysis.md`.

Incomplete / not done by the previous agent:

- Final independent audit report `docs/validation/phase_3_independent_audit.md` (did not exist).
- Independent recalculation of WP3 statistics.
- PCB01 denominator correction.
- Actual kernel-file coverage verification (claims were not checked against files).
- The WP2 code did not compile (indentation error), so its tests never actually ran in the reported state.

Existing corrections made during this audit:

- Fixed indentation error in `find_sun_transitions` bisection loop (`horizon_analysis.py`).
- Fixed boundary omission: the final coarse sampling interval is now bracketed.
- Created independent recalculation artifacts (WP3, WP4) and kernel coverage check script, without overwriting historical results.

Unresolved findings:

- WP2 grazing/tangent contacts without a sign change are still missed (documented limitation).
- WP2 short illumination intervals shorter than the coarse step can be missed (documented limitation).
- WP3 monotonicity claim is not supported (see §6).
- WP4 remains point analysis only; no regional PSR certification.

Files modified by the previous agent (verified):

- `horizon_analysis.py` (WP2 addition).
- Created tests and validation scripts/results and Phase 3 report.

Exact next action taken after recovery: compile-check `horizon_analysis.py`, which failed; fix applied before any substantive audit work.

---

## 3. Audit methodology

1. Inspected repository state, git status, and all Phase 3 artifacts before editing.
2. Reproduced the import failure (`IndentationError` at the WP2 bisection block).
3. Fixed only the compile defect and the boundary defect; reran the full test suite.
4. Independently parsed raw result JSON and recomputed WP3/WP4 statistics.
5. Established a refined WP3 reference using bisection with `tol_seconds=0.1`, `elev_tol_deg=1e-6`.
6. Verified kernel coverage directly with SPICE (`spkcov`, `pckcov`, `pxform`) against `de440s.bsp` and `moon_pa_de418_1950-2050.bpc`.
7. Recomputed WP4 longest-shadow runs and percentages using actual interval durations rather than a uniform step assumption.
8. Created revised outputs (`*_independent_recalculation_results.json`, `kernel_coverage_check.py`) without overwriting historical results.
9. Ran full test suites and validation scripts; recorded actual results.

No LSI code was modified. No unrelated refactoring was performed.

---

## 4. WP1 findings — temporal constants

Constants in `horizon_analysis.py`:

| Constant | Value | Interpretation | Usage |
|---|---:|---|---|
| `DRACONIC_YEAR_DAYS` | 346.62 d | Draconic/eclipse year (Sun returns to same lunar node) | `psr_screen` (`main.py`) annual screen |
| `LUNAR_YEAR_DAYS` | 354.367 d | 12 synodic months (12 × 29.53059 d) | Reference only |
| `LUNAR_NODAL_CYCLE_YEARS` | 18.6 yr | Lunar nodal precession | `psr_cycle_screen` |
| `EARTH_YEAR_DAYS` | 365.25 d | Earth year | Derives nodal cycle |
| `LUNAR_NODAL_CYCLE_DAYS` | 18.6 × 365.25 ≈ 6793.65 d | One lunar nodal precession cycle | `psr_cycle_screen` |

Verification:

- 12 × 29.53059 d = 354.36708 d, so `LUNAR_YEAR_DAYS = 354.367` is correct.
- `LUNAR_YEAR_DAYS` (354.367 d) is distinct from the draconic year (346.62 d) and from the nodal cycle (6793.65 d). No conflation found in code.
- Constants are not incorrectly used: the draconic year drives the annual PSR screen, the nodal cycle drives the 18.6-year screen, and `LUNAR_YEAR_DAYS` is reference-only.
- The 18.6-year nodal cycle modulates polar illumination geometry; it is **not** an intrinsic PSR repetition period. The report correctly qualifies this.

**WP1 conclusion: no defect; no code change required.**

---

## 5. WP2 findings — sunrise/sunset transition interpolation

Function: `find_sun_transitions(...)` in `horizon_analysis.py`.

### 5.1 Defects found and corrected

1. **Syntax error (blocking).** The bisection `try` block was over-indented, causing `IndentationError` at import time. This made `horizon_analysis` (and therefore `main.py` and all tests) unimportable. **Corrected.**
2. **Boundary omission.** `sample_times` did not include `end`, so the final coarse interval was never bracketed and a transition in the last step could be missed. **Corrected** by appending `end` when missing.

### 5.2 Verified behavior

- Root bracketing by sign changes of `f(t) = solar_elevation − reference_horizon`.
- Bisection refinement until `|f| ≤ elev_tol_deg`, bracket width `≤ tol_seconds`, or `max_iter`.
- Terrain and astronomical references are distinct.
- UTC timestamps, azimuth/elevation, horizon, coverage, convergence flag, iteration count, and bracket endpoints are returned.
- Invalid inputs are rejected.
- Missing/non-finite coverage samples are skipped (NaN propagation).

### 5.3 Known limitations (not fixed; documented)

- **Grazing/tangent contacts without a sign change are missed.** The algorithm only detects sign changes, not extrema that touch zero. This is a real detection limit, not merely a performance issue.
- **Short illumination intervals shorter than the coarse step can be missed** if no sample brackets them.
- **Tolerance affects reported time.** `elev_tol_deg = 0.01°` can accept a midpoint ~1–5 minutes from the true root (see §6.4). Use tighter tolerances for high-accuracy work.

### 5.4 Regression tests

`tests/test_sun_transitions.py`: 5 tests, all pass (always-sunlit, always-shadowed, converged crossing, invalid inputs, importability). Full suite: 47 passed.

---

## 6. WP3 independent recalculations

### 6.1 Raw data and methodology

- Sites: Shackleton (-89.9, 0.0), MMA04/Malapert (-86.31, -0.459), PCB01 (-83.763, -69.983).
- Window: 2026-11-14T00:00Z to 2026-11-17T00:00Z (72 h).
- Steps: 60, 30, 15, 5, 1 minute.
- `analyze_sunlight_period` uses left-endpoint classification with interval weighting.
- Refined reference: bisection with `tol_seconds=0.1`, `elev_tol_deg=1e-6` (see `audit_wp3_independent.py`).

### 6.2 Shackleton results

Initial state in window: shadowed. One sunrise. Refined transition (sunrise): **2026-11-14T13:47:40.84Z**.
Refined sunlit duration: **58.2053 h (209539.2 s)**.

| Step (min) | Sunlit (h) | Duration error vs refined (s) | Transition timestamp (default tol) | Transition error (default tol) (s) | Transition timestamp (tight tol) | Transition error (tight tol) (s) |
|---:|---:|---:|---|---:|---|---:|
| 60 | 58.0000 | -739.16 | 13:45:00 | 160.84 | 13:47:40.84 | ~0 |
| 30 | 58.0000 | -739.16 | 13:45:00 | 160.84 | 13:47:40.84 | ~0 |
| 15 | 58.0000 | -739.16 | 13:52:30 | 289.16 | 13:47:40.84 | ~0 |
| 5 | 58.1667 | -139.16 | 13:47:30 | 10.84 | 13:47:40.84 | ~0 |
| 1 (ref) | 58.2000 | -19.16 | 13:47:30 | 10.84 | 13:47:40.84 | ~0 |

MMA04 and PCB01: **0 sunlit hours, 0 transitions** at every step in this window (stable).

### 6.3 Interpretation of non-monotonicity

- Duration error is 739 s for 60/30/15 minutes because the single sunrise (13:47:41) falls inside the 13:00–14:00 coarse interval; left-endpoint weighting assigns that entire hour to the pre-sunrise (shadowed) state regardless of step until the step is small enough to place a sunlit sample before the transition. This is a discretization effect, not a code defect.
- Duration error then drops to 139 s (5 min) and 19 s (1 min) as the step shrinks.
- Transition-time errors are non-monotonic under the default `elev_tol_deg = 0.01°` because bisection stops as soon as the midpoint clearance is within tolerance; bracket alignment differs by step, so the accepted midpoint jumps (13:45 → 13:52:30 → 13:47:30).
- With a tight tolerance, all steps agree to within ~0–11 s, confirming the underlying root is stable and the non-monotonicity is a tolerance/bracketing artifact.

### 6.4 Qualification

- The 1-minute discrete reference is **not** ground truth (it still carries ~19 s of left-endpoint discretization error).
- The refined bisection reference (13:47:40.84Z) is more accurate but depends on ephemeris and tolerance.
- No short illumination interval is exercised in this 3-day window; the missed-short-interval scenario is not tested here.

---

## 7. WP4 independent recalculations

### 7.1 PCB01 denominator investigation (critical)

Original report table mixed denominators:

| Site | Sunlit | Shadowed | Unknown | Known coverage |
|---|---:|---:|---:|---:|
| Shackleton | 3.73% | 96.27% | 0% | 100% |
| Haworth | 34.79% | 65.21% | 0% | 100% |
| PCB01 | 30.03% | 52.25% | 25.33% | 74.67% |

For PCB01, 30.03% was of **known** samples while 52.25% was of **all** samples. This is confirmed by independent recalculation:

- Total samples: 163,048
- Sunlit: 36,563; Shadowed: 85,186; Unknown: 41,299
- Known: 121,749 (74.67% coverage)
- Sunlit of known: **30.03%**; Shadowed of known: **69.97%** (sum ≈ 100%)
- Sunlit of all: **22.42%**; Shadowed of all: **52.25%**; Unknown of all: **25.33%**

Corrected table (consistent denominators):

| Site | Sunlit (% known) | Shadowed (% known) | Unknown (% all) | Known coverage |
|---|---:|---:|---:|---:|
| Shackleton | 3.73% | 96.27% | 0% | 100% |
| Haworth | 34.79% | 65.21% | 0% | 100% |
| PCB01 | 30.03% | 69.97% | 25.33% | 74.67% |

Unknown samples were **not** counted as shadowed.

### 7.2 WP4 results (one nodal cycle, 60-min sampling)

| Site | Sunlit (h) | Shadowed (h) | Unknown (h) | Sunlit % (known) | Shadowed % (known) | Longest continuous shadow (h) |
|---|---:|---:|---:|---:|---:|---:|
| Shackleton | 6084×1h ≈ 6084 | 156964 | 0 | 3.73% | 96.27% | 6908 (~288 d) |
| Haworth | 56729 | 106319 | 0 | 34.79% | 65.21% | 539 (~22.5 d) |
| PCB01 | 36563 | 85186 | 41299 | 30.03% | 69.97% | 411 (~17 d) |

Longest-shadow runs were recomputed using actual interval durations (the final partial interval is no longer assumed to be a full 60 min). Values are unchanged to the reported precision.

### 7.3 Scientific qualification

- Point analysis only (one coordinate + terrain horizon), not regional PSR mapping.
- A dark point over one nodal cycle is a pre-screen, not a permanent-shadow certification.
- 60-min sampling may miss sub-hour sunlit intervals (false-PSR risk).
- 40 m DEM cannot resolve small-scale shadowing.
- PCB01 has 25.33% unknown samples due to DEM coverage limits.
- Selected coordinates may not represent entire named regions.
- Ground-truth PSR classifications were not sourced from primary literature.

---

## 8. Kernel coverage verification

Verified directly against bundled kernel files (see `tests/validation/kernel_coverage_check.py`):

Kernel files present:

- `de440s.bsp` (32,726,016 bytes)
- `moon_pa_de418_1950-2050.bpc` (1,186,816 bytes)
- `moon_080317.tf` (21,428 bytes)
- `pck00011.tpc` (131,225 bytes)

SPK coverage (`de440s.bsp`):

- Object 10 (Sun): 1849-12-25 to 2150-01-21
- Object 301 (Moon): 1849-12-25 to 2150-01-21
- Object 399 (Earth): 1849-12-25 to 2150-01-21

PCK coverage (`moon_pa_de418_1950-2050.bpc`):

- Frame 31004 (`MOON_PA_DE418`): 1949-12-31 to 2050-12-30
- Frame 31005 (`MOON_ME_DE418`): 0 intervals in this PCK (expected; registered via embedded DE418 frames)

Engine state:

- Frame selected: `MOON_ME`, source "embedded DE418 lunar frames".
- `spice.pxform("J2000", "MOON_ME", et)` succeeds at both interval endpoints:
  - 2026-11-14T00:00:00Z: OK
  - 2045-06-20T15:36:00Z: OK

Conclusion: the WP4 interval (2026-11-14 to 2045-06-20) is supported by both SPK and PCK coverage. The earlier coverage claim is confirmed, not merely asserted. Stop condition not triggered.

---

## 9. Corrections made

| # | Defect | Impact | Correction |
|---|---|---|---|
| 1 | `IndentationError` in `find_sun_transitions` bisection block | Module unimportable; all tests fail | Fixed indentation (minimal) |
| 2 | Final coarse interval not bracketed | Possible missed transition in last step | Append `end` to `sample_times` |
| 3 | PCB01 mixed denominators in report | Overstated shadowed fraction consistency | Corrected percentages documented; unknowns not counted as shadowed |
| 4 | WP3 monotonicity claim unsupported | Misleading convergence claim | Recalculated with refined reference; non-monotonicity explained |
| 5 | WP4 longest-run/fraction used uniform step | Minor overestimate at final partial interval | Recomputed with actual durations (values unchanged at reported precision) |

No LSI code changed. No constants changed. No unrelated refactoring.

---

## 10. Regression test results

Actual results after corrections:

- `python -m pytest tests/ -q -p no:cacheprovider`: **47 passed, 0 failed**.
- `python -m pytest tests/validation/ -q -p no:cacheprovider`: **4 passed, 0 failed**.
- `tests/validation/audit_wp3_independent.py`: ran successfully; wrote `wp3_independent_recalculation_results.json`.
- `tests/validation/audit_wp4_independent.py`: ran successfully; wrote `wp4_independent_recalculation_results.json`.
- `tests/validation/kernel_coverage_check.py`: ran successfully; confirmed SPK/PCK coverage and endpoint frame availability.

Historical claims of "47 passed / 4 passed" are confirmed by actual rerun.

---

## 11. Remaining scientific limitations

- WP2 misses grazing/tangent contacts without sign change.
- WP2 may miss illumination intervals shorter than the coarse step.
- WP2 default `elev_tol_deg = 0.01°` can introduce ~minutes of transition-time error; tighten for high-accuracy work.
- WP3: 1-minute reference is not ground truth; only one transition in the tested window; missed-short-interval scenario not exercised.
- WP4: point analysis, not regional PSR mapping; not a permanent-shadow certification.
- 60-min WP4 sampling may miss sub-hour sunlit intervals (false-PSR risk).
- 40 m DEM cannot resolve small-scale shadowing; PCB01 has 25.33% unknown samples.
- Selected coordinates may not represent entire named regions.
- Primary literature was not used as ground truth for PSR classifications.
- `LUNAR_YEAR_DAYS` remains reference-only (correct, but not used in calculations).

---

## 12. Reproducibility instructions

```text
# Full test suite
python -m pytest tests/ -q -p no:cacheprovider
python -m pytest tests/validation/ -q -p no:cacheprovider

# WP3 original (historical) script
python tests/validation/wp3_timestep_convergence.py

# WP3 independent recalculation (refined reference)
python tests/validation/audit_wp3_independent.py

# WP4 original (historical) script
python tests/validation/wp4_nodal_cycle_psr.py

# WP4 independent recalculation (corrected denominators, actual durations)
python tests/validation/audit_wp4_independent.py

# Kernel coverage verification
python tests/validation/kernel_coverage_check.py
```

Original historical artifacts were preserved; revised outputs are in `*_independent_recalculation_results.json`. No commits or pushes were made.

---

## 13. Final acceptance decision

**Status: PASS WITH QUALIFICATIONS**

Justification:

- Core Phase 3 functionality (constants, transition interpolation, temporal sampling, nodal-cycle PSR pre-screen) is implemented and now compiles and tests pass.
- A blocking syntax defect was found and corrected; a boundary defect was corrected.
- The PCB01 denominator inconsistency was confirmed and corrected in reporting.
- Kernel coverage claims were independently verified against actual kernel files.
- WP3 convergence is quantified and its non-monotonicity is explained as a discretization/tolerance artifact, not a silent failure.
- Qualifications remain: WP2 detection limits, WP3 reference accuracy and limited test coverage, WP4 point-analysis and sampling limits, DEM resolution, and lack of primary-literature ground truth. These prevent an unqualified PASS, but do not constitute a FAIL because they are explicitly documented and do not invalidate the implemented functionality.

---

## 14. Final response summary

- Initial state: `horizon_analysis.py` modified but unimportable due to indentation error; multiple untracked Phase 3 artifacts present.
- Previous agent had completed WP1–WP4 scripts, results, tests, and report, but the WP2 code did not compile and the final audit report did not exist.
- Independently verified: WP1 constants, WP2 behavior after fix, WP3 statistics via refined bisection reference, WP4 sample counts and corrected denominators, kernel coverage against actual files.
- Defects discovered: blocking indentation error; boundary omission; PCB01 mixed denominators; unsupported monotonicity claim; tolerance-induced transition-time variability.
- Corrected: indentation; boundary; documentation/reporting; added independent recalculation and kernel-verification artifacts.
- Files changed: `horizon_analysis.py`; added `tests/validation/audit_wp3_independent.py`, `tests/validation/audit_wp4_independent.py`, `tests/validation/kernel_coverage_check.py`, `tests/validation/wp3_independent_recalculation_results.json`, `tests/validation/wp4_independent_recalculation_results.json`, `docs/validation/phase_3_independent_audit.md`.
- Test results: 47 passed (`tests/`), 4 passed (`tests/validation/`).
- Final audit status: PASS WITH QUALIFICATIONS.
- Remaining risks: WP2 grazing/short-interval detection limits, WP3 reference accuracy and limited stress coverage, WP4 point-analysis/sampling/DEM limits, no primary-literature ground truth.
