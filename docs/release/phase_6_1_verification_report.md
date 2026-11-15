# Phase 6.1 Data Distribution Verification Report

**Date:** 2026-11-15
**Release directory:** `C:\Users\asus\OneDrive\Desktop\LUNARIS-Release`
**Architecture report:** `docs/release/data_distribution_architecture.md`

## 1. Verified facts

- Required runtime data files present:
  - `data/ldem_80s_40m_float.img`
  - `data/ldem_80s_40m_float.lbl`
  - `data/Ephemeris/de440s.bsp`
  - `data/Ephemeris/moon_080317.tf`
  - `data/Ephemeris/moon_pa_de418_1950-2050.bpc`
  - `data/Ephemeris/pck00011.tpc`
- `data/SHA256SUMS` is present and all six checksums match.
- DEM label identifies product `LDEM_80S_40M`, version `V2.1`, dataset `LRO-L-LOLA-4-GDR-V1.0`, LOLA instrument, 40 m/pixel, reference radius 1737.4 km.
- Runtime code uses `LUNARIS_DATA_DIR` for DEM and kernel discovery in the release implementation.
- Missing DEM can fall back to the pre-rendered Plotly surface when available.
- Missing SPK kernel raises `EphemerisError`.
- Missing orientation kernel may use `IAU_MOON` if `pck00011.tpc` is available.
- API endpoints catch `FileNotFoundError`, `OSError`, and `EphemerisError` and return HTTP 503 for data-dependent failures.
- Candidate comparison isolates per-candidate analysis failures.

## 2. Failed checks

- `git check-ignore -v` could not be executed because the release directory is not a Git repository. Therefore actual Git ignore behavior is NOT VERIFIED.
- The current `.gitignore` uses `data/`, which would ignore the entire `data` directory, including `data/SHA256SUMS`.
- `.gitattributes` uses `*.IMG`, while the actual DEM filename uses lowercase `.img`. On case-sensitive systems this attribute may not match.

## 3. Unverified assumptions

- Third-party redistribution terms for the LOLA DEM and NAIF SPICE kernels are not present in repository metadata. These require manual verification against official NASA/PDS/NAIF terms.
- No published production URL or `LUNARIS_API_BASE` value is documented.
- No Docker image build was performed because Docker is unavailable.

## 4. Exact proposed `.gitignore` and `.gitattributes` changes

Proposed `.gitignore`:

```gitignore
# Python caches
__pycache__/
*.pyc
*.pyo
*.pyd
.ruff_cache/

# Generated outputs
outputs/

# Runtime scientific data
data/*
!data/SHA256SUMS

# Additional DEM safety rule
*.img
```

Proposed `.gitattributes`:

```gitattributes
*.img filter=lfs diff=lfs merge=lfs -text
*.IMG filter=lfs diff=lfs merge=lfs -text
outputs/*.html filter=lfs diff=lfs merge=lfs -text
outputs/*.gltf filter=lfs diff=lfs merge=lfs -text
outputs/*.glb filter=lfs diff=lfs merge=lfs -text
outputs/*.bin filter=lfs diff=lfs merge=lfs -text
```

These changes are proposed only. They were not applied during this audit.

## 5. Runtime compatibility with an external data package

Status: PASS WITH QUALIFICATIONS

- A valid external root containing `data/ldem_80s_40m_float.img`, `data/ldem_80s_40m_float.lbl`, and `data/Ephemeris/` can be used through `LUNARIS_DATA_DIR`.
- Missing raw DEM can use the Plotly surface fallback if present.
- Missing SPK kernel raises an explicit error.
- Missing orientation kernel may use the IAU_MOON fallback.
- The application does not silently substitute incomplete data for known calculation paths, except for the documented DEM surface fallback.

## 6. Dataset provenance and attribution findings

Verified:

- DEM product: `LDEM_80S_40M`, version `V2.1`, dataset `LRO-L-LOLA-4-GDR-V1.0`.
- Instrument: Lunar Orbiter Laser Altimeter (LOLA) on Lunar Reconnaissance Orbiter.
- DEM resolution: 40 m/pixel, true at the pole.
- Reference radius: 1737.4 km.
- SPICE kernels present: `de440s.bsp`, `moon_pa_de418_1950-2050.bpc`, `pck00011.tpc`, `moon_080317.tf`.

Not verified:

- Exact redistribution and attribution requirements for the DEM and SPICE kernels.
- Whether third-party terms permit direct repository hosting or require external distribution.

## 7. Recommended next implementation steps

1. Apply the proposed `.gitignore` and `.gitattributes` changes after review.
2. Keep the DEM and large kernel outside ordinary Git or use Git LFS.
3. Distribute `data/SHA256SUMS` with the repository.
4. Document the production API base URL and CORS origin.
5. Add dedicated tests for candidate-comparison provenance and missing-kernel behavior if desired.

## 8. Final status

PASS WITH QUALIFICATIONS

The proposed data distribution architecture is compatible with the actual release directory. The main unresolved items are Git ignore behavior, which could not be tested without initializing Git, and third-party redistribution terms, which require manual verification.
PY