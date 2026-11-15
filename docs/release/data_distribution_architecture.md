# LUNARIS Data Distribution Architecture

## 1. Recommended repository structure

GitHub repository should contain:

- Application source code.
- Tests and validation scripts.
- Documentation and audit reports.
- CI workflow.
- `data/SHA256SUMS`.
- Small configuration files.

External data distribution should contain:

- `data/ldem_80s_40m_float.img` (881.35 MB)
- `data/ldem_80s_40m_float.lbl`
- `data/Ephemeris/de440s.bsp`
- `data/Ephemeris/moon_pa_de418_1950-2050.bpc`
- `data/Ephemeris/pck00011.tpc`
- `data/Ephemeris/moon_080317.tf`

Generated outputs such as `outputs/south_pole_3d.html` may be included as release artifacts or regenerated locally.

## 2. DEM distribution strategy

The DEM is 881.35 MB and exceeds GitHub's 100 MB hard limit. It should not be committed to ordinary Git.

Recommended strategy:

- Distribute the DEM as a release asset or external data package.
- Preserve the original PDS3 `.lbl` and `.img` pair.
- Verify both files with `data/SHA256SUMS`.
- Install them at:
  - `data/ldem_80s_40m_float.lbl`
  - `data/ldem_80s_40m_float.img`

The application can use the Plotly HTML surface as a fallback, but full terrain analysis requires the source DEM.

## 3. SPICE kernel distribution strategy

Recommended strategy:

- Commit small kernels if desired:
  - `moon_080317.tf` (0.02 MB)
  - `pck00011.tpc` (0.13 MB)
- Evaluate `moon_pa_de418_1950-2050.bpc` (1.13 MB) for direct commit or external distribution.
- Distribute `de440s.bsp` (31.21 MB) separately or through Git LFS, depending on repository size policy.
- Preserve the six-file checksum manifest.

## 4. Git ignore and attributes corrections

Current `.gitignore`:

- Ignores `data/` and `*.img`.
- This prevents accidental DEM commits but also ignores `data/SHA256SUMS`.

Recommended corrections:

- Keep `data/` ignored for large runtime data.
- Explicitly un-ignore the checksum manifest:
  - `!data/SHA256SUMS`
- Keep `*.img` ignored unless Git LFS is used.
- If using Git LFS, keep the existing `*.IMG` attributes and consider adding lowercase `*.img`.

## 5. Runtime behavior when data is missing

- Missing DEM image or label: `FileNotFoundError` from `LunarDEM.load()`.
- Missing SPICE SPK: `EphemerisError` from `init_ephemeris()`.
- Missing orientation kernel: `IAU_MOON` fallback may be used if `pck00011.tpc` is present.
- Partial DEM coverage is reported as `unknown`, `partial_coverage`, or reduced `known_illumination_coverage_percentage`.
- Unknown illumination samples are never counted as shadowed.

## 6. Licensing and attribution requirements

- MIT license applies to original LUNARIS code.
- NASA/PDS/NAIF datasets retain their respective source terms.
- README should state that third-party datasets are not owned by the project.
- No unsupported redistribution claims should be made.

## 7. Migration steps

1. Publish source code, tests, documentation, and small configuration files.
2. Publish or attach the DEM separately.
3. Publish or attach SPICE kernels according to the chosen size policy.
4. Publish `data/SHA256SUMS`.
5. Document installation paths and checksum verification.
6. Configure `LUNARIS_DATA_DIR`, `LUNARIS_API_BASE`, and `LUNARIS_CORS_ORIGINS` in deployment.

## 8. Remaining decisions requiring user approval

- Whether to use Git LFS for the DEM and/or `de440s.bsp`.
- Whether to attach datasets as GitHub release assets.
- Whether to commit small kernels directly.
- Production API URL and CORS origin.
- Final public documentation wording for third-party data terms.
PY