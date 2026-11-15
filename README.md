# Lunaris — Lunar South Pole Mission Planning Suite

Lunaris is a mission-analysis prototype for lunar south-pole operations, developed for the NASA Space Apps Challenge. It combines NASA Lunar Orbiter Laser Altimeter (LOLA) topography, SPICE-based Sun and Earth geometry, and a concise mission-control HUD to help teams explore terrain, illumination, communications, and landing constraints at a selected surface site.

The application is a decision-support tool, not a landing-certification system. Its 40 m DEM cannot resolve hazards at lander-foot or rover-wheel scale.

## Core Capabilities

- **Interactive 3D DEM:** Renders `LDEM_80S_40M_FLOAT.IMG` as a Plotly `go.Surface` model of the 80°–90° south latitude region. Use `Plasma`, `Turbo`, or another Plotly scale to inspect elevation relief.
- **Terrain horizon and illumination:** Computes a 360° terrain horizon using curvature-aware DEM rays, then compares it with SPICE solar geometry to identify terrain shadow and solar visibility.
- **Slope and roughness screening:** Produces a local slope grid, preferred (≤5°) and acceptable (≤8°) area fractions, DEM coverage, and planar-detrended roughness metrics.
- **Earth line-of-sight assessment:** Evaluates direct-to-Earth visibility against the local terrain horizon and reports the geometry and coverage confidence.
- **Landing Suitability Index (LSI):** Combines terrain slope, roughness, and surface-safety factors into a transparent local suitability score and class.
- **Candidate comparison and PSR pre-screens:** Compares representative Artemis III candidate regions for a shared mission epoch and duration, and supports draconic-year (~346.62 day) and 18.6-year nodal-cycle illumination pre-screens.

## Architecture

| Component | Responsibility |
| --- | --- |
| `main.py` | FastAPI service and validated English-language REST API contracts. |
| `south_pole_3d.py` | DEM reader, Plotly scene generator, and dark-mode mission-control HUD. |
| `horizon_analysis.py` | DEM sampling, terrain horizon, slope, roughness, LSI, LOS, and sunlight analysis. |
| `ephemeris_engine.py` | NASA SPICE/Skyfield ephemeris initialization and lunar surface geometry. |
| `coordinate_transform.py` | Lunar polar-stereographic, geographic, and selenocentric coordinate transforms. |
| `horizon_analysis_view.html` | Standalone 360° terrain-horizon viewer for a selected site. |

## Requirements

- Python 3.11 or later
- The LOLA PDS3 label and image in `data/`:
  - `ldem_80s_40m_float.lbl`
  - `ldem_80s_40m_float.img`
- SPICE kernels in `data/Ephemeris/` (included in the project data layout)

## Setup

```powershell
git clone <repository-url>
cd "Lunaris Ana Dosya"
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Keep the `.img` file beside its `.lbl` PDS3 label. The application can use the generated Plotly surface as a limited fallback for visualisation, but full terrain analysis requires the source DEM.

## Run Locally

Start the API service in one terminal:

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000
```

Generate the interactive viewer in a second terminal:

```powershell
python south_pole_3d.py --colorscale Plasma
```

For a non-interactive build:

```powershell
python south_pole_3d.py --no-show --output outputs/south_pole_3d.html
```

Open `outputs/south_pole_3d.html` in a browser while the API is running. Select a DEM point to populate the HUD. The default API endpoint is `http://127.0.0.1:8000`; use `--api-base` when deploying it elsewhere.

## API Overview

The interactive client calls these primary endpoints:

- `POST /calculate` — selenocentric coordinates plus Sun/Earth ephemeris.
- `POST /analysis/horizon` — 360° local terrain horizon.
- `POST /analysis/solar-visibility` and `POST /analysis/sunlight-period` — terrain-aware sunlight assessments.
- `POST /analysis/landing-safety` — slope, roughness, and local coverage.
- `POST /analysis/lsi-score` — Landing Suitability Index score and class.
- `POST /analysis/earth-los` — terrain-aware geometric Earth line-of-sight (not a communication link assessment).
- `GET /analysis/candidate-sites` and `POST /analysis/candidate-comparison` — representative region comparison.
- `POST /analysis/psr-screen` and `POST /analysis/psr-cycle-screen` — PSR pre-screening (draconic-year and 18.6-year nodal-cycle intervals).

Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs` while the server is running.

## Validation

Run the automated test suite before presenting or deploying changes:

```powershell
python -m pytest tests -q
```

## DEM Projection and Coordinate Reference System

The DEM is the NASA LRO LOLA `LDEM_80S_40M_FLOAT` product (PDS3, `LRO-L-LOLA-4-GDR-V1.0`):

- **Projection:** Polar stereographic, south pole centered
- **Reference sphere:** 1737.4 km (MOON_MEAN_RADIUS)
- **Resolution:** 40 m/pixel
- **Grid:** 15200 × 15200 pixels, 32-bit float, height in km above the reference sphere
- **Projection offsets:** LINE_PROJECTION_OFFSET = 7599.5, SAMPLE_PROJECTION_OFFSET = 7599.5 pixels
- **Coordinate system:** Mean Earth/Polar Axis of DE421 (MOON_ME frame), planetocentric latitude, east-positive longitude
- **Elevation convention:** Height above the 1737.4 km reference sphere, in kilometres (stored), converted to metres in code

The Python `latlon_to_polar_stereographic` and `LunarDEM.from_pds3` use the same polar stereographic projection parameters (R = 1737400 m, k0 = 1.0 at the pole), so geographic coordinates map consistently onto the DEM pixel grid.

## DEM Coverage Boundaries

- **Geographic coverage:** 80°S to 90°S (south polar cap only)
- **All coordinates outside this band are outside DEM coverage** and will be reported with `coverage_status: "outside_dem"`.
- Candidate site PCB01 (Peak near Cabeus B) at −83.7630° latitude is within the DEM coverage band.
- The candidate comparison endpoint reports per-site coverage status; one invalid site does not fail the entire comparison.

## DEM Availability and Feature Scope

Without the raw LOLA DEM, LUNARIS can display the available pre-rendered 3D surface, but DEM-dependent scientific analyses are limited or unavailable. Full terrain analysis requires both the \.img\ and \.lbl\ files.

When the raw DEM is unavailable but \outputs/south_pole_3d.html\ exists, the application may use its embedded lower-resolution surface as a fallback for visualization and limited terrain calculations. This fallback is not equivalent to the 40 m LOLA DEM.

Feature status without the raw DEM:

- Application startup: available if the Plotly fallback surface is present; otherwise an explicit file error is raised.
- Pre-rendered 3D surface: available as a precomputed visualization fallback.
- Terrain horizon: limited, because the fallback surface has 1600 m effective spacing instead of 40 m.
- Slope and roughness: limited for the same reason.
- Landing Suitability Index (LSI): limited for the same reason.
- Sunlight analysis: limited because it depends on the available horizon profile.
- PSR analysis: limited because it depends on the available horizon profile.
- Candidate comparison: limited when DEM-dependent calculations use the fallback; unavailable with an explicit error when no DEM or fallback exists.

For full functionality, both files are mandatory:

- \data/ldem_80s_40m_float.img- \data/ldem_80s_40m_float.lbl
External runtime data package installation:

1. Download or obtain the official LOLA \LDEM_80S_40M_FLOAT\ PDS3 label and image.
2. Place them at:
   - \data/ldem_80s_40m_float.lbl   - \data/ldem_80s_40m_float.img3. Verify both files against \data/SHA256SUMS\.
4. Start LUNARIS normally.

## Earth Visibility Limitations

The `/analysis/earth-los` endpoint performs a **geometric line-of-sight test only**: it compares Earth's apparent elevation against the local terrain horizon. It does **not** model:

- Communication link budget
- Antenna gain or signal strength
- Frequency-dependent propagation
- Earth angular extent
- Spacecraft-to-Earth communication constraints

An unobstructed geometric line of sight (`geometric_earth_visibility: "visible"`) is necessary but not sufficient for a communication link. The deprecated `communication_status` field is retained for backward compatibility.

## Known Scientific Limitations

- **40 m/pixel DEM** cannot resolve lander-footprint or rover-wheel-scale hazards.
- **Elevations are above a reference sphere**, not the lunar geoid; no geoid correction is applied.
- **Horizon is fixed** for the duration of a sunlight-period analysis; no temporal terrain change is modeled.
- **Illumination is binary per time step** (sunlit/shadowed/unknown); sunrise/sunset transitions are not interpolated.
- **LSI weights (0.7 slope / 0.3 roughness)** are heuristic, not empirically calibrated against lunar landing data.
- **PSR classifications are pre-screens only**; no-sun results do not establish permanent shadow.
- **Independent scientific validation** is documented in docs/validation/ (Phase 2.2 ephemeris validation, Phase 3 temporal audit, and Phase 4 provenance/spatial audit). Validation remains a pre-screen and model-comparison exercise, not NASA certification.

## Phase 4 Provenance and Spatial Sampling

- Analysis responses can include a provenance block describing terrain source, configured DEM resolution, ephemeris backend and loaded kernels, UTC time window, sampling interval, transition tolerances, and spatial sampling parameters.
- Spatial neighborhood utilities sample a regular grid in the polar-stereographic projection plane; reported distances are projection-plane (Euclidean) distances, not lunar surface geodesic distances.
- Provenance metadata documents configuration and runtime kernel coverage. It is not a certification of data accuracy or site safety.

## Scientific Use Notes

Lunaris reports model-derived terrain and geometry indicators. DEM gaps, grid resolution, horizon ray sampling, ephemeris availability, and time-step selection are reported because they constrain confidence. A no-sun result from the PSR workflows is a pre-screen outcome only; it is not proof of permanent shadow or a certification of site safety.
