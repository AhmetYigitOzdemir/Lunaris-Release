# LUNARIS Data Distribution

## Required runtime data

| File | Size | Purpose | Required |
|---|---:|---|---|
| `data/ldem_80s_40m_float.img` | 881.35 MB | LOLA south-polar DEM elevation raster | Yes |
| `data/ldem_80s_40m_float.lbl` | <1 MB | PDS3 label for the DEM | Yes |
| `data/Ephemeris/de440s.bsp` | 31.21 MB | SPK ephemeris for Sun, Earth, Moon | Yes |
| `data/Ephemeris/moon_pa_de418_1950-2050.bpc` | 1.13 MB | Lunar orientation PCK | Yes |
| `data/Ephemeris/pck00011.tpc` | 0.13 MB | Text PCK fallback | Yes |
| `data/Ephemeris/moon_080317.tf` | 0.02 MB | Lunar frame definitions | Yes |

## Authoritative sources

- DEM: NASA LRO LOLA `LDEM_80S_40M_FLOAT` PDS3 product.
- Ephemeris: NASA/JPL SPICE kernels (`de440s.bsp`, lunar orientation and frame kernels).

No download URLs are invented in this document. Obtain the files from their official NASA/PDS/NAIF distributions and verify them with the checksums in `data/SHA256SUMS`.

## Installation

1. Place the DEM label and image at:
   - `data/ldem_80s_40m_float.lbl`
   - `data/ldem_80s_40m_float.img`
2. Place SPICE kernels under:
   - `data/Ephemeris/`
3. Verify checksums:
   - `cd <release-root>`
   - Compare files against `data/SHA256SUMS`.

## Configurable external data directories

The application uses project-relative paths by default. To use an external data directory, set the environment variable before starting the application:

```text
LUNARIS_DATA_DIR=<path containing data/ and data/Ephemeris/>
```

If the variable is not set, the application uses the repository root.

## Missing-data diagnostics

- Missing DEM image or label: `FileNotFoundError` from `LunarDEM.load()`.
- Missing SPICE SPK: `EphemerisError` from `init_ephemeris()`.
- Missing orientation kernel: IAU_MOON fallback may be used if `pck00011.tpc` is present.
- Partial DEM coverage is reported as `unknown`, `partial_coverage`, or reduced `known_illumination_coverage_percentage`.
- Unknown illumination samples are never counted as shadowed.

## Checksums

See `data/SHA256SUMS`.

## Size strategy

The DEM is approximately 881 MB and is not suitable for ordinary Git storage. It should be distributed through Git LFS, a release asset, or an external data package. The release candidate includes it locally for independent validation only.
PY


## DEM Availability and Feature Scope

Without the raw LOLA DEM, LUNARIS can display the available pre-rendered 3D surface, but DEM-dependent scientific analyses are limited or unavailable. Full terrain analysis requires both the .img and .lbl files.

When the raw DEM is unavailable but outputs/south_pole_3d.html exists, the application may use its embedded lower-resolution surface as a fallback. This fallback has 1600 m effective spacing and is not equivalent to the 40 m LOLA DEM.

Feature status without the raw DEM:

- Application startup: available if the Plotly fallback surface is present; otherwise an explicit file error is raised.
- Pre-rendered 3D surface: available as a precomputed visualization fallback.
- Terrain horizon: limited.
- Slope and roughness: limited.
- Landing Suitability Index (LSI): limited.
- Sunlight analysis: limited.
- PSR analysis: limited.
- Candidate comparison: limited when using the fallback; unavailable with an explicit error when no DEM or fallback exists.

