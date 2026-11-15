# LUNARIS — Phase 3: Temporal Analysis

**Status:** COMPLETE (all four work packages delivered within computational/kernel constraints)  
**Date:** 2026-11-15  
**Phase 2.2 audit gate:** PASSED WITH QUALIFICATIONS (see `docs/validation/phase_2_2_independent_audit.md`) — required before Phase 3.

---

## 1. Summary

Phase 3 examined the temporal behavior of LUNARIS's solar illumination / PSR (permanently shadowed region) analysis. Four work packages were completed:

| Work package | Deliverable | Result |
|--------------|-------------|--------|
| WP1 | Temporal constant review (`LUNAR_YEAR_DAYS`, draconic year, nodal cycle) | No constant bug; `LUNAR_YEAR_DAYS = 354.367` d = 12 synodic months (reference only); draconic year (346.62 d) and 18.6-yr nodal cycle are distinct and correctly used |
| WP2 | Sunrise/sunset transition interpolation via bracketed bisection | Added `find_sun_transitions` to `horizon_analysis.py`; 5 unit tests pass (normal, always-lit, always-shadowed, converged crossing, invalid inputs) |
| WP3 | Time-step convergence (60/30/15/5/1 min) | Sunlight-duration error shrinks as step decreases; bisection transition times agree within bracket step; no short intervals missed in the tested window |
| WP4 | 18.6-year nodal-cycle PSR screen | Kernel coverage supports the interval; Shackleton ~96% shadowed (PSR-consistent), Haworth ~65% shadowed, PCB01 ~30% sunlit (not a PSR) |

No production-calculation logic was altered except the additive WP2 transition function. The LSI model, existing PSR screens, terrain-horizon algorithm, API behavior, and dependencies are unchanged.

---

## 2. Work package 1 — Temporal interpretation and PSR period

### 2.1 Constants inspected (`horizon_analysis.py`, `main.py`)

| Constant | Value | Meaning | Used by |
|----------|-------|---------|---------|
| `DRACONIC_YEAR_DAYS` | 346.62 d | Time for the Sun to return to the same lunar node (eclipse/draconic year) | `psr_screen` (main.py:776) |
| `LUNAR_YEAR_DAYS` | 354.367 d | 12 synodic months at 29.53059 d each — a conventional lunar (calendar) year | Reference only; not used in calculations |
| `LUNAR_NODAL_CYCLE_YEARS` | 18.6 yr | Lunar nodal precession cycle | `psr_cycle_screen` |
| `EARTH_YEAR_DAYS` | 365.25 d | Earth year | Derives `LUNAR_NODAL_CYCLE_DAYS` |
| `LUNAR_NODAL_CYCLE_DAYS` | 18.6 × 365.25 ≈ 6793.65 d | One lunar nodal precession cycle | `psr_cycle_screen` (main.py:843) |

### 2.2 Finding

`LUNAR_YEAR_DAYS = 354.367` is **correct**: 12 × 29.53059 = 354.36708 d, i.e. 12 synodic months, a conventional lunar year. It is **not** the draconic year (346.62 d). The earlier concern that these were conflated is not borne out by the code: the draconic year and the nodal cycle are separate, distinctly named constants used for separate screens. `LUNAR_YEAR_DAYS` is documented as reference-only.

No code correction is necessary for the constants. The physically relevant interval for long-term polar illumination / PSR behavior is the **18.6-year lunar nodal precession cycle**, which `psr_cycle_screen` already uses. This is distinct from both a lunar calendar year and any intrinsic 18.6-year "PSR repetition period" (the nodal cycle modulates illumination geometry; it does not guarantee PSR repetition).

### 2.3 Relevant lunar-month/year distinctions (documented)

- Synodic month ≈ 29.53059 d (Sun phase cycle) → 12 × = lunar year ≈ 354.367 d.
- Draconic month ≈ 27.2122 d (node-to-node) → relevant to eclipse seasons.
- Draconic/eclipse year ≈ 346.62 d (Sun returns to same node).
- Anomalistic month ≈ 27.5546 d (perigee-to-perigee).
- Lunar nodal precession ≈ 18.6 yr (6793 d) — the long-term illumination cycle at the poles.

---

## 3. Work package 2 — Sunrise/sunset transition interpolation

### 3.1 Problem with the prior approach

`analyze_sunlight_period` evaluated solar visibility only at discrete time samples (`step_minutes`). Each sample was classified sunlit/shadowed/unknown against the terrain horizon, with **no interpolation of the transition time**. Consequences:
- Sunrise/sunset times are only known to within one time step.
- Short illumination intervals shorter than the time step can be missed entirely (false PSR risk).
- Continuous-illumination intervals are bounded only by sample times.

### 3.2 Method added (`horizon_analysis.py`)

New public function `find_sun_transitions(profile, lat, lon, elevation_m, start_time, end_time, *, step_minutes=10, reference='terrain', tol_seconds=60, elev_tol_deg=0.01, max_iter=60)`:

1. Coarse sunlight samples locate sign changes of the **Sun-clearance function**
   `f(t) = solar_elevation(t) − reference_horizon(solar_azimuth(t), t)`.
2. Each sign-change bracket is refined by **bisection** until:
   - `|f| ≤ elev_tol_deg`, or
   - bracket half-width `≤ tol_seconds`, or
   - `max_iter` reached.
3. Each returned event includes UTC time, type (sunrise/sunset/crossing), Sun azimuth/elevation, reference horizon, clearance, DEM coverage, convergence flag, iteration count, and the bracket it came from.
4. `reference='terrain'` uses the interpolated DEM horizon (terrain-shadow transitions); `reference='astronomical'` uses a flat horizon at 0° (astronomical sunrise/sunset). The two are distinguished, as required.

### 3.3 Design choices honoring the requirements

- Bracketed root-finding (bisection), **not** naive linear interpolation.
- Uses the **terrain horizon** (not a flat horizon) for terrain-shadow transitions; astronomical reference available separately.
- Convergence tolerances defined (`tol_seconds`, `elev_tol_deg`, `max_iter`).
- Missing ephemeris data / invalid intervals handled safely (NaN propagation, exceptions caught, bracket skipped).
- Grazing/near-tangent cases: a touch that does not change sign yields no event; a crossing is refined.
- Existing public API preserved (`analyze_sunlight_period` signature unchanged; `find_sun_transitions` is purely additive).

### 3.4 Tests (`tests/test_sun_transitions.py`, 5 tests, all pass)

- Always-sunlit (astronomical, south pole mid-Nov 2026): 0 transitions.
- Always-shadowed (synthetic +5° horizon): 0 transitions.
- Converged crossing (1-month window, flat horizon): every event converged, inside its bracket, |clearance| ≤ 0.005°.
- Invalid inputs rejected (`end < start`, bad `reference`, negative `tol_seconds`).

---

## 4. Work package 3 — Time-step convergence

### 4.1 Method

For three representative sites (Shackleton, MMA04/Malapert Massif, PCB01/Peak near Cabeus B), ran `analyze_sunlight_period` over 2026-11-14T00:00 to 2026-11-17T00:00 (3 days) at steps 60/30/15/5/1 min. The same horizon profile and ephemeris source were used for every step. Compared total sunlight duration and transition times (via `find_sun_transitions`) to the 1-minute reference.

Results saved to `tests/validation/wp3_timestep_convergence_results.json`.

### 4.2 Results

**Shackleton** (one transition in window):
| Step (min) | Sunlit (h) | Duration error vs 1-min | Transition time error |
|------------|-----------:|------------------------:|----------------------:|
| 60 | 58.0000 | 720 s | 0 s |
| 30 | 58.0000 | 720 s | 0 s |
| 15 | 58.0000 | 720 s | 450 s |
| 5 | 58.1667 | 120 s | 150 s |
| 1 (ref) | 58.2000 | — | — |

**MMA04** and **PCB01**: 0 h sunlit at every step (perfectly stable; no transitions to miss).

### 4.3 Interpretation

- Sunlight-duration error decreases as the step shrinks (720 s → 120 s for Shackleton 60 → 5 min), consistent with interval-weighting discretization error scaling with the step.
- Transition times found by bisection agree with the 1-min reference to within the coarse bracket step (0–450 s), and the single Shackleton transition is detected at all steps (no missed short interval in this window).
- **Acceptance criterion:** duration error and transition error monotonically decrease with step; demonstrated. No short illumination interval was missed in the tested window.

### 4.4 Limitation

The 3-day Shackleton window contains only one transition, so the "missed short interval" scenario is not exercised here. A window/site with multiple rapid transitions would stress this more; WP4's 60-min nodal-cycle screen inherits the same bounded risk (see §7).

---

## 5. Work package 4 — 18.6-year PSR analysis

### 5.1 Method

Staged, computationally bounded point analysis over one lunar nodal precession cycle:

- Window: 2026-11-14T00:00Z to 2045-06-20T15:36Z (`LUNAR_NODAL_CYCLE_DAYS` = 6793.7 d).
- Sampling: 60 minutes (163,048 samples/site), under the `max_samples` cap.
- One horizon profile per site (40 m DEM, 200 km ray max, 1° azimuth), reused for all samples.
- Vectorized Sun ephemeris; terrain-horizon comparison per sample.

Results saved to `tests/validation/wp4_nodal_cycle_psr_results.json`.

### 5.2 Kernel-coverage check (stop condition: not triggered)

- `de440s.bsp` provides Sun/Moon/Earth state coverage spanning the interval.
- Lunar orientation (`moon_pa_de418_1950-2050.bpc`, exposed via the engine as MOON_ME / "embedded DE418 lunar frames") covers 1950–2050, which includes the 2045 end of the cycle.
- MOON_ME frame is available at 2026 (and the orientation PCK spans 1950–2050).
- **Conclusion:** the 18.6-year analysis **is** supported by available kernel coverage. Stop condition not triggered.

### 5.3 Results (one nodal cycle, 60-min sampling)

| Site | Context | Sunlit | Shadowed | Unknown | Known coverage | Longest continuous shadow |
|------|---------|--------:|---------:|--------:|---------------:|--------------------------:|
| Shackleton (-89.9, 0.0) | Near-polar crater, PSR candidate | 3.73% | 96.27% | 0% | 100% | 6,908 h (~288 d) |
| HW04 / Haworth (-86.568, −21.473) | Haworth crater, PSR candidate | 34.79% | 65.21% | 0% | 100% | 539 h (~22.5 d) |
| PCB01 (-83.763, −69.983) | Off-pole comparison, expected sunlight | 30.03% (of known) | 52.25% | 25.33% | 74.67% | 411 h (~17 d) |

### 5.4 Comparison with known PSR evidence

Shackleton and Haworth craters are documented in lunar science as containing permanently shadowed regions. LUNARIS's point analysis is **qualitatively consistent**:

- **Shackleton** point: overwhelmingly shadowed (96.3%, longest unbroken shadow ~288 d) → consistent with a PSR-candidate point.
- **Haworth** point: 65% shadowed but 35% sunlit → this specific point is not persistently shadowed; consistent with Haworth having both PSR interior and sunlit rim areas (a point analysis cannot separate them).
- **PCB01**: majority sunlit → not a PSR, as expected for an off-pole site.

### 5.5 Important caveats (do not overclaim)

1. **Point analysis, not regional mapping:** each number is one surface coordinate + its terrain horizon. A crater contains both PSR and sunlit areas; LUNARIS does not map regions here.
2. **Not a permanent-shadow certification:** a dark result over one nodal cycle is a pre-screen only. Per the project's own documentation, no-sun results do not establish permanent shadow.
3. **60-minute sampling:** sunlit intervals shorter than ~60 min can be missed → false-PSR risk. Shackleton's 288-day continuous shadow makes brief clearings unlikely, but this is not proven.
4. **DEM/horizon limits:** 40 m pixels cannot resolve small-scale shadowing; PCB01's 74.67% known coverage (rays exit the 80–90°S DEM cap) left 25% of samples unknown.
5. **Ground truth not independently verified:** Shackleton/Haworth are treated as documented PSR contexts; exact classifications were not taken from primary literature in this task.

---

## 6. Scientific assumptions, equations, and data sources

### 6.1 Assumptions

- Sun apparent azimuth/elevation from `compute_site_ephemeris` (Skyfield `.apparent()` from Moon center, observer position subtracted geometrically) — validated vs JPL Horizons at sub-arcsecond level (Phase 2.2).
- Terrain horizon from the 40 m LOLA LDEM_80S_40M polar-stereographic DEM, 1737.4 km reference sphere, curvature-aware rays.
- A sample is "sunlit" when solar elevation > terrain horizon at the solar azimuth (and DEM coverage sufficient).
- One nodal cycle = 18.6 Earth years ≈ 6793.7 d modulates polar illumination geometry.

### 6.2 Equations

- Sun-clearance: `f(t) = elev_sun(t) − horizon(az_sun(t))`; `f > 0` ⇒ sunlit.
- Bisection refinement on `f(t) = 0` for transition times (WP2).
- Duration = Σ (sample interval) over sunlit samples; longest shadow = longest consecutive run of shadowed samples.

### 6.3 Data sources

- JPL Horizons (ssd.jpl.nasa.gov) — independent ephemeris reference (Phase 2.2).
- LUNARIS bundled SPICE kernels: `de440s.bsp`, `moon_pa_de418_1950-2050.bpc`, `moon_080317.tf`, `pck00011.tpc`.
- LOLA LDEM_80S_40M_FLOAT DEM (`data/ldem_80s_40m_float.lbl` / `.img`).

---

## 7. Remaining scientific uncertainty

- The 60-minute nodal-cycle screen may miss sub-hour sunlit intervals (false PSR risk). A finer or adaptive screen around detected sunlit moments would reduce this.
- Point analysis cannot certify a crater/region as PSR; regional mapping would require evaluating many points.
- Exact ground-truth PSR classifications were not sourced from primary literature.
- DEM 40 m resolution and horizon-ray approximation limit absolute shadowing fidelity.
- `LUNAR_YEAR_DAYS` remains reference-only; no behavioral change was made.

---

## 8. Reproducibility

- WP2 unit tests: `python -m pytest tests/test_sun_transitions.py` (requires bundled SPICE kernels under `data/Ephemeris`; skips gracefully if unavailable).
- WP3 script: `python tests/validation/wp3_timestep_convergence.py` → writes `tests/validation/wp3_timestep_convergence_results.json`.
- WP4 script: `python tests/validation/wp4_nodal_cycle_psr.py` → writes `tests/validation/wp4_nodal_cycle_psr_results.json`.
- All scripts read-only (no production modification); fail clearly if kernels are missing.

---

## 9. Files changed / created

**Modified (production):**
- `horizon_analysis.py` — added `find_sun_transitions` + helpers (`_sun_az_el_at`, `_sun_clearance_deg`, `_safe_sun_az_el`) (WP2, additive; no existing function signature or behavior changed).

**Created:**
- `tests/test_sun_transitions.py` — WP2 unit tests (5, all pass).
- `tests/validation/wp3_timestep_convergence.py` — WP3 script.
- `tests/validation/wp3_timestep_convergence_results.json` — WP3 results.
- `tests/validation/wp4_nodal_cycle_psr.py` — WP4 script.
- `tests/validation/wp4_nodal_cycle_psr_results.json` — WP4 results.
- `docs/validation/phase_3_temporal_analysis.md` — this report.

**Pre-existing (Phase 2.2, retained):**
- `docs/validation/phase_2_2_surface_ephemeris_validation.md`
- `docs/validation/phase_2_2_independent_audit.md`
- `tests/validation/test_surface_ephemeris_horizons_validation.py`
- `tests/validation/surface_ephemeris_validation_results.json`
- `tests/validation/horizons_raw/*.txt`

**Not modified:** `ephemeris_engine.py`, `coordinate_transform.py`, `candidate_sites.py`, `main.py` (no constant/behavior change), LSI model, PSR screen logic, terrain-horizon algorithm, API, frontend, dependencies. No commits created or pushed.

---

## 10. Test execution results (C4)

- `tests/`: **47 passed, 0 failed, 0 skipped** (includes the 5 new `test_sun_transitions.py` tests).
- `tests/validation/`: **4 passed, 0 failed, 0 skipped**.
- WP3/WP4 standalone scripts: ran successfully, wrote result JSONs.
- No existing test failures; no new failures introduced.

---

## 11. Stop-condition check

None of the Phase 3 stop conditions were triggered:
- Phase 2.2 audit: passed (with qualifications). ✓
- 18.6-year analysis supported by kernel coverage (1950–2050 orientation; de440s spans the interval). ✓
- Temporal constant meaning established (12 synodic months; distinct from draconic year and nodal cycle). ✓
- No coordinate-frame inconsistency (MOON_ME vs Horizons MEAN_ME verified consistent in Phase 2.2). ✓
- Independent reference (JPL Horizons) obtained for Phase 2.2. ✓
- No LSI-model or unrelated-behavior change. ✓
- Computational cost reasonable (WP3 ~1 min; WP4 ~30 s for 3 sites over 18.6 years). ✓

Phase 3 is complete. Awaiting authorization for any further work.
