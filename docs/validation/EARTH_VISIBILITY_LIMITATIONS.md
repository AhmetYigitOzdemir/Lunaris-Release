# LUNARIS — Earth Visibility Limitations

**Date:** 2026-11-15  
**Status:** DOCUMENTED  
**Validation type:** Code inspection + terminology correction

---

## 1. What the Earth Visibility Calculation Does

**File:** `horizon_analysis.py:891-943` (`check_earth_los`)  
**File:** `main.py:539-573` (`earth_los` endpoint)

The Earth visibility calculation performs a **geometric line-of-sight test**:

1. Computes Earth's apparent position (azimuth/elevation) from SPICE ephemeris at the lunar surface site
2. Interpolates the terrain horizon at Earth's azimuth from the pre-computed horizon profile
3. Compares: `visible = earth_elevation > terrain_horizon`
4. Returns `geometric_earth_visibility: "visible"/"not_visible"` and (deprecated) `communication_status: "OPEN"/"BLOCKED"`

The same geometric test is used for solar visibility (`check_solar_visibility`, line 946).

### What IS modeled:
- Lunar topography obstruction (terrain horizon)
- Earth's apparent position relative to the local horizon
- DEM coverage fraction (confidence in the horizon measurement)

### What is NOT modeled:
| Factor | Status | Required for communication link |
|--------|--------|--------------------------------|
| Antenna gain | Not modeled | Required |
| Transmitter power | Not modeled | Required |
| Receiver sensitivity | Not modeled | Required |
| Frequency/wavelength | Not modeled | Required |
| Link budget (EIRP, G/T, margin) | Not modeled | Required |
| Path loss (free-space loss) | Not modeled | Required |
| Pointing constraints | Not modeled | Required |
| Earth angular extent | Not modeled (point source) | Not strictly required but relevant for link margin |
| Occultation by Moon body | Not modeled (terrain only) | Required for non-line-of-sight |
| Atmospheric effects | N/A (airless Moon) | N/A |
| Time-varying Earth position | Single epoch only | Required for contact windows |
| Lunar libration | Included via SPICE ephemeris | — |
| Solar conjunction | Not modeled | Relevant for communication blackouts |

---

## 2. Terminology

### 2.1 Fields in API response (`/analysis/earth-los`)

| Field | Type | Meaning | Deprecated? |
|-------|------|---------|-------------|
| `geometric_earth_visibility` | String | "visible" / "not_visible" — terrain-obstruction test only | No |
| `earth_visible` | Boolean | True if Earth elevation > terrain horizon | No |
| `communication_status` | String | "OPEN" / "BLOCKED" — **deprecated** | Yes |
| `terrain_horizon_deg` | Float | Horizon angle at Earth's azimuth (degrees) | No |
| `dem_coverage_fraction` | Float | Fraction of horizon ray within valid DEM (0–1) | No |
| `horizon_coverage_complete` | Boolean | True if coverage ≥ minimum_coverage (0.9) | No |

### 2.2 Frontend labels (`south_pole_3d.js`)

| Element | Label | Status |
|---------|-------|--------|
| HUD metric | "Earth geometric visibility: visible/not_visible" | Corrected (was "Direct-to-Earth available") |
| Badge | "Above geometric horizon" / "Below geometric horizon" | Corrected (was "Direct-to-Earth available" / "Below terrain horizon") |

---

## 3. Key Distinction: Geometric Visibility ≠ Communication Availability

**Geometric line of sight** is **necessary but not sufficient** for a communication link.

```
Geometric visibility (terrain unobstructed)
    ↓
Antenna pointing (Earth within antenna beam)
    ↓
Link budget (sufficient EIRP, G/T, margin)
    ↓
Frequency selection (compatible with equipment)
    ↓
Contact window (Earth above horizon for sufficient duration)
    ↓
COMMUNICATION AVAILABLE
```

LUNARIS only performs step 1. All subsequent steps require additional mission architecture inputs that are not available in the application.

---

## 4. What Would Be Required for a Communication-Link Analysis

To extend LUNARIS from geometric visibility to communication-link assessment, the following inputs would be needed:

| Input | Description | Example values |
|-------|-------------|----------------|
| Antenna gain (transmit/receive) | dBi, depends on antenna size and frequency | 20–40 dBi |
| Transmitter power | Watts or dBW | 5–100 W |
| Receiver sensitivity | Minimum detectable signal, dBm | -100 to -140 dBm |
| Frequency | GHz, affects path loss and antenna gain | X-band (8 GHz), S-band (2 GHz), Ka-band (26 GHz) |
| Data rate requirement | bps, affects required link margin | 1–100 kbps |
| Pointing accuracy | Degrees, affects effective gain | 0.1–1.0° |
| Earth station parameters | G/T, elevation mask, weather | DSN station characteristics |
| Link margin requirement | dB, design margin for fading | 3–10 dB |

With these inputs, one could compute:
- Free-space path loss: `L = (4πd/λ)²`
- Received power: `Pr = Pt + Gt + Gr - L`
- Link margin: `M = Pr - Pr_min`
- Contact duration: time Earth is above horizon with sufficient margin

---

## 5. Current Status

The Earth visibility calculation is **geometrically correct** (ephemeris validated against JPL Horizons, terrain horizon test correct) but is **limited to geometric line-of-sight only**. The deprecated `communication_status` field is retained for backward compatibility but should not be interpreted as a communication-link assessment.

API documentation and frontend labels have been updated to use accurate terminology ("geometric_earth_visibility", "Above geometric horizon", "Below geometric horizon").

---

## 6. Reproduction

The Earth visibility calculation can be tested via the API:

```bash
curl -X POST http://127.0.0.1:8000/analysis/earth-los \
  -H "Content-Type: application/json" \
  -d '{"lat": -89.0, "lon": 0.0, "elevation_m": 0}'
```

Response includes both `geometric_earth_visibility` (accurate) and `communication_status` (deprecated).