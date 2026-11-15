"""FastAPI service for lunar south-pole site calculations.

Exposes ``POST /calculate`` which combines selenocentric Cartesian conversion
with Sun/Earth ephemeris angles for a clicked or manually entered site.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from candidate_sites import CANDIDATE_SITES
from coordinate_transform import MOON_MEAN_RADIUS_M, lunar_geodetic_to_cartesian
from ephemeris_engine import (
    EphemerisError,
    compute_site_ephemeris,
    get_engine_status,
    init_ephemeris,
    parse_timestamp_utc,
)
from horizon_analysis import (
    DEFAULT_DEM_LABEL,
    DEFAULT_PLOTLY_HTML,
    DRACONIC_YEAR_DAYS,
    LUNAR_NODAL_CYCLE_DAYS,
    LUNAR_NODAL_CYCLE_YEARS,
    LUNAR_YEAR_DAYS,
    HorizonAnalysisService,
    analyze_sunlight_period,
    calculate_landing_safety_patch,
    find_sun_transitions,
    calculate_landing_suitability_index,
    check_earth_los,
    check_solar_visibility,
    profile_to_dict,
    validate_dem_coverage,
)

logger = logging.getLogger(__name__)
_HORIZON_SERVICE: HorizonAnalysisService | None = None
_HORIZON_SERVICE_LOCK = threading.Lock()


class SiteRequest(BaseModel):
    """Input body for a lunar surface site calculation."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "lat": -89.9,
                "lon": 0.0,
                "elevation": 4200.0,
                "timestamp": "2026-11-14T12:00:00Z",
            }
        },
    )

    lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Planetocentric latitude in degrees (negative south).",
    )
    lon: float = Field(
        ...,
        ge=0.0,
        le=360.0,
        description="East-positive longitude in degrees, 0-360.",
    )
    elevation: float = Field(
        ...,
        ge=-20000.0,
        le=20000.0,
        description="GDRDEM elevation above the 1737.4 km sphere, in metres.",
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 UTC timestamp, e.g. 2026-11-14T12:00:00Z.",
    )

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: str) -> str:
        parse_timestamp_utc(value)
        return value


class ObserverInfo(BaseModel):
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    radius_m: float


class BodyAngles(BaseModel):
    azimuth_deg: float
    elevation_deg: float
    distance_km: float
    above_horizon: bool


class EphemerisResult(BaseModel):
    timestamp_utc: str
    frame: str
    observer: ObserverInfo
    sun: BodyAngles
    earth: BodyAngles


class CartesianResult(BaseModel):
    x_m: float
    y_m: float
    z_m: float
    radius_m: float
    units: Literal["meters"] = "meters"
    frame: str


class CalculateResponse(BaseModel):
    success: bool = True
    request: SiteRequest
    cartesian: CartesianResult
    ephemeris: EphemerisResult


class HorizonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90.0, le=0.0)
    lon: float = Field(..., ge=0.0, le=360.0)
    elevation_m: float | None = Field(default=None, ge=-20000.0, le=20000.0)
    azimuth_step_deg: float = Field(default=1.0, gt=0.0, le=10.0)
    max_distance_m: float = Field(default=200000.0, gt=0.0, le=300000.0)
    ray_step_m: float | None = Field(default=None, gt=0.0, le=10000.0)


class SolarVisibilityRequest(SiteRequest):
    lat: float = Field(..., ge=-90.0, le=0.0)
    azimuth_step_deg: float = Field(default=1.0, gt=0.0, le=10.0)
    max_distance_m: float = Field(default=200000.0, gt=0.0, le=300000.0)
    ray_step_m: float | None = Field(default=None, gt=0.0, le=10000.0)


class SunlightPeriodRequest(HorizonRequest):
    start_time: str = Field(..., description="ISO 8601 start time")
    end_time: str = Field(..., description="ISO 8601 end time")
    step_minutes: float = Field(default=60.0, gt=0.0, le=1440.0)

    @field_validator("start_time", "end_time")
    @classmethod
    def _validate_range_timestamp(cls, value: str) -> str:
        parse_timestamp_utc(value)
        return value


class PSRScreenRequest(SolarVisibilityRequest):
    step_minutes: float = Field(default=60.0, ge=15.0, le=180.0)


class PSRNodalCycleRequest(SolarVisibilityRequest):
    step_minutes: float = Field(default=60.0, ge=60.0, le=1440.0)


class CandidateComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(..., description="Mission start time in UTC")
    duration_days: float = Field(default=6.0, gt=0.0, le=30.0)
    step_minutes: float = Field(default=60.0, ge=15.0, le=1440.0)
    azimuth_step_deg: float = Field(default=1.0, gt=0.0, le=10.0)
    max_distance_m: float = Field(default=150000.0, gt=0.0, le=300000.0)
    ray_step_m: float | None = Field(default=None, gt=0.0, le=10000.0)

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: str) -> str:
        parse_timestamp_utc(value)
        return value


class LandingSafetyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90.0, le=0.0)
    lon: float = Field(..., ge=0.0, le=360.0)
    radius_m: float = Field(default=1000.0, gt=0.0, le=5000.0)
    cell_size_m: float | None = Field(default=None, gt=0.0, le=1000.0)


LSIRequest = LandingSafetyRequest
LandingSuitabilityRequest = LandingSafetyRequest


class EarthLOSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90.0, le=0.0)
    lon: float = Field(..., ge=0.0, le=360.0)
    elevation_m: float | None = Field(default=None, ge=-20000.0, le=20000.0)
    elevation: float | None = Field(default=None, ge=-20000.0, le=20000.0)
    minimum_coverage: float = Field(default=0.9, ge=0.0, le=1.0)
    timestamp: str | None = Field(default=None)

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            parse_timestamp_utc(value)
        return value

    @model_validator(mode="after")
    def _resolve_elevation(self) -> "EarthLOSRequest":
        if self.elevation_m is None and self.elevation is not None:
            self.elevation_m = self.elevation
        return self


def _longest_sunlit_run_hours(
    samples: list[dict[str, Any]], *, start: datetime, end: datetime, step_minutes: float
) -> float:
    step_seconds = float(step_minutes) * 60.0
    total_seconds = (end - start).total_seconds()
    longest = current = 0.0
    for index, sample in enumerate(samples):
        duration = min(step_seconds, max(0.0, total_seconds - index * step_seconds))
        if sample.get("is_sunlit") is True:
            current += duration
            longest = max(longest, current)
        else:
            current = 0.0
    return longest / 3600.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        summary = await asyncio.to_thread(init_ephemeris)
        logger.info("Lunaris ephemeris initialised: %s", summary)
    except Exception:
        logger.exception(
            "Ephemeris initialisation failed at start-up; it will be retried lazily"
        )
    yield


app = FastAPI(
    title="Lunaris Lunar South Pole API",
    description=(
        "SPICE/Skyfield ephemeris and GDRDEM selenocentric coordinate "
        "conversion for the lunar south pole."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

_OUTPUTS_DIR = Path(__file__).resolve().parent / "outputs"


@app.get("/viewer", include_in_schema=False)
def frontend_viewer() -> FileResponse:
    """Serve the interactive 3D viewer generated by south_pole_3d.py."""
    viewer_path = _OUTPUTS_DIR / "south_pole_3d.html"
    if not viewer_path.is_file():
        raise HTTPException(status_code=404, detail="Viewer not found. Run south_pole_3d.py.")
    return FileResponse(viewer_path)


@app.get("/horizon-viewer", include_in_schema=False)
def horizon_viewer() -> FileResponse:
    """Serve the standalone terrain-horizon viewer."""
    horizon_path = _OUTPUTS_DIR / "horizon_analysis.html"
    if not horizon_path.is_file():
        raise HTTPException(status_code=404, detail="Horizon viewer not found. Run south_pole_3d.py.")
    return FileResponse(horizon_path)

_origins = [
    origin.strip()
    for origin in os.getenv("LUNARIS_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "Lunaris Lunar South Pole API",
        "docs": "/docs",
        "endpoint": "POST /calculate",
        "analysis": (
            "POST /analysis/horizon, /analysis/solar-visibility, "
            "/analysis/sunlight-period, /analysis/psr-screen, "
            "/analysis/psr-cycle-screen, "
            "/analysis/landing-safety, "
            "GET /analysis/candidate-sites, POST /analysis/candidate-comparison"
        ),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    status = get_engine_status()
    return {"status": "ok" if status.get("ready") else "degraded", **status}


def _horizon_service() -> HorizonAnalysisService:
    global _HORIZON_SERVICE
    if _HORIZON_SERVICE is None:
        with _HORIZON_SERVICE_LOCK:
            if _HORIZON_SERVICE is None:
                label = Path(os.getenv("LUNARIS_DEM_LABEL", str(DEFAULT_DEM_LABEL)))
                html = Path(os.getenv("LUNARIS_DEM_HTML", str(DEFAULT_PLOTLY_HTML)))
                _HORIZON_SERVICE = HorizonAnalysisService(label, html)
    return _HORIZON_SERVICE


def _calculate_horizon(request: HorizonRequest):
    return _horizon_service().horizon_profile(
        request.lat,
        request.lon,
        site_elevation_m=request.elevation_m,
        azimuth_step_deg=request.azimuth_step_deg,
        max_distance_m=request.max_distance_m,
        ray_step_m=request.ray_step_m,
    )


@app.post("/calculate", response_model=CalculateResponse)
def calculate(request: SiteRequest) -> CalculateResponse:
    try:
        x, y, z = lunar_geodetic_to_cartesian(
            request.lat, request.lon, request.elevation
        )
        ephemeris = compute_site_ephemeris(
            request.lat, request.lon, request.elevation, request.timestamp
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EphemerisError as exc:
        logger.error("Ephemeris error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error while calculating site")
        raise HTTPException(
            status_code=500, detail="Internal error while calculating site"
        ) from exc

    cartesian = CartesianResult(
        x_m=x,
        y_m=y,
        z_m=z,
        radius_m=MOON_MEAN_RADIUS_M + request.elevation,
        frame=ephemeris["frame"],
    )

    return CalculateResponse(
        success=True,
        request=request,
        cartesian=cartesian,
        ephemeris=EphemerisResult(**ephemeris),
    )


@app.post("/analysis/horizon")
def horizon(request: HorizonRequest) -> dict[str, Any]:
    """Return a 360-degree terrain horizon mask for one lunar site."""
    try:
        return profile_to_dict(_calculate_horizon(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.exception("Could not load DEM for horizon analysis")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/analysis/candidate-sites")
def candidate_sites() -> dict[str, Any]:
    """List the nine current Artemis III regions and representative points."""
    return {
        "success": True,
        "coordinate_source": "Wueller et al. (2026), Table A1",
        "regions": [
            {**site, "longitude_deg": site["longitude_deg"] % 360.0}
            for site in CANDIDATE_SITES
        ],
    }


@app.post("/analysis/candidate-comparison")
def compare_candidate_sites(request: CandidateComparisonRequest) -> dict[str, Any]:
    """Compare representative candidate sites over the same mission window.

    Each candidate is processed independently. A site that is outside DEM
    coverage or has invalid data is reported with an explicit ``coverage_status``
    and does not cause the entire comparison to fail.
    """
    try:
        start = parse_timestamp_utc(request.timestamp)
        end = start + timedelta(days=request.duration_days)
        results: list[dict[str, Any]] = []
        service = _horizon_service()

        for candidate in CANDIDATE_SITES:
            latitude = candidate["latitude_deg"]
            longitude = candidate["longitude_deg"] % 360.0

            # Assess DEM coverage before any computation.
            coverage = validate_dem_coverage(
                service.dem, latitude, longitude, radius_m=1000.0
            )

            if coverage["status"] != "available":
                results.append(
                    {
                        "region": candidate["region"],
                        "site_id": candidate["site_id"],
                        "latitude_deg": latitude,
                        "longitude_deg": longitude,
                        "coverage_status": coverage["status"],
                        "coverage_percentage": coverage["coverage_percentage"],
                        "elevation_m": coverage["elevation_m"],
                        "error_message": coverage["error_message"],
                        "sunlit_hours": None,
                        "sunlit_percentage": None,
                        "known_illumination_coverage_percentage": None,
                        "longest_sunlit_run_hours": None,
                        "transition_count": None,
                        "first_sunrise_utc": None,
                        "first_sunset_utc": None,
                        "sun_elevation_deg": None,
                        "sun_azimuth_deg": None,
                        "sun_horizon_deg": None,
                        "sun_visibility": None,
                        "earth_elevation_deg": None,
                        "earth_azimuth_deg": None,
                        "earth_horizon_deg": None,
                        "earth_visibility": None,
                        "dem_resolution_m": service.dem.pixel_size_x_m,
                        "dem_source": service.dem.source,
                        "slope_below_5_deg_percentage": None,
                        "slope_below_8_deg_percentage": None,
                        "terrain_coverage_percentage": None,
                        "horizon_coverage_fraction": None,
                        "provenance": None,
                    }
                )
                continue

            try:
                profile = service.horizon_profile(
                    latitude,
                    longitude,
                    azimuth_step_deg=request.azimuth_step_deg,
                    max_distance_m=request.max_distance_m,
                    ray_step_m=request.ray_step_m,
                )
                current = compute_site_ephemeris(
                    latitude,
                    longitude,
                    profile.site_elevation_m,
                    request.timestamp,
                )
                sun = current["sun"]
                earth = current["earth"]
                sun_visibility = check_solar_visibility(
                    profile, sun["azimuth_deg"], sun["elevation_deg"]
                )
                earth_visibility = check_solar_visibility(
                    profile, earth["azimuth_deg"], earth["elevation_deg"]
                )
                illumination = analyze_sunlight_period(
                    profile,
                    start_time=start,
                    end_time=end,
                    step_minutes=request.step_minutes,
                    include_samples=True,
                )
                try:
                    transitions = find_sun_transitions(
                        profile,
                        latitude,
                        longitude,
                        profile.site_elevation_m,
                        start,
                        end,
                        step_minutes=request.step_minutes,
                        reference="terrain",
                    )
                except (ValueError, EphemerisError, FileNotFoundError, OSError):
                    transitions = {"transition_count": 0, "transitions": []}
                safety = calculate_landing_safety_patch(
                    service.dem, latitude, longitude, radius_m=1000.0
                )
                results.append(
                    {
                        "region": candidate["region"],
                        "site_id": candidate["site_id"],
                        "latitude_deg": latitude,
                        "longitude_deg": longitude,
                        "coverage_status": "available",
                        "coverage_percentage": coverage["coverage_percentage"],
                        "elevation_m": profile.site_elevation_m,
                        "error_message": None,
                        "sunlit_hours": illumination["sunlit_duration_hours"],
                        "sunlit_percentage": illumination["sunlit_percentage"],
                        "known_illumination_coverage_percentage": illumination[
                            "known_illumination_coverage_percentage"
                        ],
                        "longest_sunlit_run_hours": _longest_sunlit_run_hours(
                            illumination["samples"],
                            start=start,
                            end=end,
                            step_minutes=request.step_minutes,
                        ),
                        "transition_count": transitions.get("transition_count", 0),
                        "first_sunrise_utc": next(
                            (t["timestamp_utc"] for t in transitions.get("transitions", []) if t.get("type") == "sunrise"),
                            None,
                        ),
                        "first_sunset_utc": next(
                            (t["timestamp_utc"] for t in transitions.get("transitions", []) if t.get("type") == "sunset"),
                            None,
                        ),
                        "sun_elevation_deg": sun["elevation_deg"],
                        "sun_azimuth_deg": sun["azimuth_deg"],
                        "sun_horizon_deg": sun_visibility["terrain_horizon_deg"],
                        "sun_visibility": sun_visibility["visibility"],
                        "earth_elevation_deg": earth["elevation_deg"],
                        "earth_azimuth_deg": earth["azimuth_deg"],
                        "earth_horizon_deg": earth_visibility["terrain_horizon_deg"],
                        "earth_visibility": earth_visibility["visibility"],
                        "dem_resolution_m": profile.dem_resolution_m,
                        "dem_source": profile.dem_source,
                        "provenance": illumination.get("provenance"),
                        "slope_below_5_deg_percentage": safety[
                            "slope_below_5_deg_percentage"
                        ],
                        "slope_below_8_deg_percentage": safety[
                            "slope_below_8_deg_percentage"
                        ],
                        "terrain_coverage_percentage": safety["coverage_percentage"],
                        "horizon_coverage_fraction": sun_visibility[
                            "dem_coverage_fraction"
                        ],
                    }
                )
            except (ValueError, EphemerisError, FileNotFoundError, OSError) as exc:
                logger.exception(
                    "Candidate %s (%s) analysis failed", candidate["site_id"], exc
                )
                results.append(
                    {
                        "region": candidate["region"],
                        "site_id": candidate["site_id"],
                        "latitude_deg": latitude,
                        "longitude_deg": longitude,
                        "coverage_status": "analysis_failed",
                        "coverage_percentage": coverage["coverage_percentage"],
                        "elevation_m": coverage["elevation_m"],
                        "error_message": str(exc),
                        "sunlit_hours": None,
                        "sunlit_percentage": None,
                        "known_illumination_coverage_percentage": None,
                        "longest_sunlit_run_hours": None,
                        "transition_count": None,
                        "first_sunrise_utc": None,
                        "first_sunset_utc": None,
                        "sun_elevation_deg": None,
                        "sun_azimuth_deg": None,
                        "sun_horizon_deg": None,
                        "sun_visibility": None,
                        "earth_elevation_deg": None,
                        "earth_azimuth_deg": None,
                        "earth_horizon_deg": None,
                        "earth_visibility": None,
                        "dem_resolution_m": service.dem.pixel_size_x_m,
                        "dem_source": service.dem.source,
                        "slope_below_5_deg_percentage": None,
                        "slope_below_8_deg_percentage": None,
                        "terrain_coverage_percentage": None,
                        "horizon_coverage_fraction": None,
                        "provenance": None,
                    }
                )

        return {
            "success": True,
            "coordinate_source": "Wueller et al. (2026), Table A1",
            "start_time_utc": start.isoformat().replace("+00:00", "Z"),
            "end_time_utc": end.isoformat().replace("+00:00", "Z"),
            "duration_days": request.duration_days,
            "step_minutes": request.step_minutes,
            "results": results,
            "note": (
                "One published representative point per region; results do not "
                "rank or certify the full region for landing. Earth visibility "
                "is evaluated at the mission start time. Sites outside DEM "
                "coverage are reported with coverage_status and do not fail "
                "the entire comparison."
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EphemerisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.exception("Could not load DEM for candidate comparison")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/analysis/landing-safety")
def landing_safety(request: LandingSafetyRequest) -> dict[str, Any]:
    """Return a local slope grid and low-slope/roughness screening metrics."""
    try:
        service = _horizon_service()
        result = calculate_landing_safety_patch(
            service.dem,
            request.lat,
            request.lon,
            radius_m=request.radius_m,
            cell_size_m=request.cell_size_m,
        )
        result["dem_source"] = service.dem.source
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _calculate_lsi(request: LandingSafetyRequest) -> dict[str, Any]:
    try:
        service = _horizon_service()
        result = calculate_landing_suitability_index(
            service.dem,
            request.lat,
            request.lon,
            radius_m=request.radius_m,
            cell_size_m=request.cell_size_m,
        )
        result["dem_source"] = service.dem.source
        return {"success": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.exception("Could not load DEM for LSI analysis")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/analysis/lsi-score")
def lsi_score(request: LandingSafetyRequest) -> dict[str, Any]:
    """Return a landing suitability index for the selected lunar site."""
    return _calculate_lsi(request)


@app.post("/analysis/landing-suitability")
def landing_suitability(request: LandingSafetyRequest) -> dict[str, Any]:
    """Alias for the landing suitability index endpoint."""
    return _calculate_lsi(request)


@app.post("/analysis/earth-los")
def earth_los(request: EarthLOSRequest) -> dict[str, Any]:
    """Return Earth geometric line-of-sight / terrain visibility for a site.

    This endpoint compares Earth's apparent elevation against the local terrain
    horizon. An unobstructed geometric line of sight is necessary but not
    sufficient for a communication link; link budget, antenna gain, frequency,
    and propagation factors are not modeled. Use ``geometric_earth_visibility``
    for the terrain-obstruction result. The ``communication_status`` field is
    retained for backward compatibility but is deprecated.
    """
    try:
        service = _horizon_service()
        profile = service.horizon_profile(
            request.lat,
            request.lon,
            site_elevation_m=request.elevation_m,
        )
        timestamp = request.timestamp
        if timestamp is None:
            timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            )
        ephemeris = compute_site_ephemeris(
            request.lat,
            request.lon,
            profile.site_elevation_m,
            timestamp,
        )
        earth = ephemeris.get("earth", {})
        earth_azimuth = earth.get("azimuth_deg")
        earth_elevation = earth.get("elevation_deg")
        if earth_azimuth is None or earth_elevation is None:
            raise ValueError("Ephemeris did not return Earth angles")
        result = check_earth_los(
            profile,
            earth_azimuth,
            earth_elevation,
            minimum_coverage=request.minimum_coverage,
        )
        return {
            "success": True,
            "timestamp_utc": ephemeris["timestamp_utc"],
            "site": {
                "latitude_deg": request.lat,
                "longitude_deg": request.lon,
                "elevation_m": profile.site_elevation_m,
            },
            "earth_visible": result["earth_visible"],
            "geometric_earth_visibility": result["geometric_earth_visibility"],
            "communication_status": result["communication_status"],
            "earth_azimuth_deg": result["earth_azimuth_deg"],
            "earth_elevation_deg": result["earth_elevation_deg"],
            "terrain_horizon_deg": result["terrain_horizon_deg"],
            "terrain_horizon_distance_m": result["terrain_horizon_distance_m"],
            "dem_coverage_fraction": result["dem_coverage_fraction"],
            "minimum_coverage": result["minimum_coverage"],
            "horizon_coverage_complete": result["horizon_coverage_complete"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EphemerisError as exc:
        logger.error("Ephemeris error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.exception("Could not load DEM for Earth LOS analysis")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/analysis/solar-visibility")
def solar_visibility(request: SolarVisibilityRequest) -> dict[str, Any]:
    """Compare current SPICE Sun position with the local terrain horizon."""
    try:
        ephemeris = compute_site_ephemeris(
            request.lat, request.lon, request.elevation, request.timestamp
        )
        profile = _horizon_service().horizon_profile(
            request.lat,
            request.lon,
            site_elevation_m=request.elevation,
            azimuth_step_deg=request.azimuth_step_deg,
            max_distance_m=request.max_distance_m,
            ray_step_m=request.ray_step_m,
        )
        return {
            "success": True,
            "ephemeris": ephemeris,
            "horizon": profile_to_dict(profile),
            "solar_visibility": check_solar_visibility(
                profile,
                ephemeris["sun"]["azimuth_deg"],
                ephemeris["sun"]["elevation_deg"],
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EphemerisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.exception("Could not load DEM for solar-visibility analysis")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/analysis/sunlight-period")
def sunlight_period(request: SunlightPeriodRequest) -> dict[str, Any]:
    """Estimate direct-sunlight duration over a time interval."""
    try:
        profile = _calculate_horizon(request)
        analysis = analyze_sunlight_period(
            profile,
            start_time=request.start_time,
            end_time=request.end_time,
            step_minutes=request.step_minutes,
        )
        return {
            "success": True,
            "site": {
                "latitude_deg": request.lat,
                "longitude_deg": request.lon,
                "elevation_m": profile.site_elevation_m,
            },
            **analysis,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EphemerisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.exception("Could not load DEM for sunlight-period analysis")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/analysis/psr-screen")
def psr_screen(request: PSRScreenRequest) -> dict[str, Any]:
    """Run a draconic-year (~346.62 day) PSR candidate screen for a selected site.

    The analysis interval is one draconic year (the time for the Sun to return
    to the same lunar node), not a conventional 12-synodic-month lunar year.
    A no-sun result over this interval is a PSR pre-screen candidate only;
    it does not establish permanent shadow.
    """
    try:
        profile = _horizon_service().horizon_profile(
            request.lat,
            request.lon,
            site_elevation_m=request.elevation,
            azimuth_step_deg=request.azimuth_step_deg,
            max_distance_m=request.max_distance_m,
            ray_step_m=request.ray_step_m,
        )
        start = parse_timestamp_utc(request.timestamp)
        end = start + timedelta(days=DRACONIC_YEAR_DAYS)
        analysis = analyze_sunlight_period(
            profile,
            start_time=start,
            end_time=end,
            step_minutes=request.step_minutes,
            include_samples=False,
        )
        fully_known = analysis["known_illumination_coverage_percentage"] >= 99.9
        sunlit_seconds = analysis["sunlit_duration_seconds"]
        if sunlit_seconds > 0.0:
            classification = "not_candidate"
        elif fully_known:
            classification = "candidate"
        else:
            classification = "unknown"
        return {
            "success": True,
            "site": {
                "latitude_deg": request.lat,
                "longitude_deg": request.lon,
                "elevation_m": profile.site_elevation_m,
            },
            "classification": classification,
            "is_psr_candidate": classification == "candidate",
            "is_permanently_shadowed": None,
            "analysis_scope": "one_draconic_year_pre_screen",
            "draconic_year_days": DRACONIC_YEAR_DAYS,
            "step_minutes": request.step_minutes,
            "sample_count": analysis["sample_count"],
            "start_time_utc": analysis["start_time_utc"],
            "end_time_utc": analysis["end_time_utc"],
            "sunlit_duration_hours": analysis["sunlit_duration_hours"],
            "sunlit_percentage": analysis["sunlit_percentage"],
            "known_illumination_coverage_percentage": analysis[
                "known_illumination_coverage_percentage"
            ],
            "note": (
                "A one-draconic-year no-sun result is a PSR candidate only. "
                "It does not establish permanent shadow over longer orbital cycles. "
                "The draconic year (~346.62 days) differs from a conventional "
                "lunar year (~354.37 days, 12 synodic months)."
            ),
            "horizon": analysis["horizon"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EphemerisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.exception("Could not load DEM for PSR screening")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/analysis/psr-cycle-screen")
def psr_cycle_screen(request: PSRNodalCycleRequest) -> dict[str, Any]:
    """Screen illumination over one 18.6-Earth-year lunar nodal cycle."""
    try:
        profile = _horizon_service().horizon_profile(
            request.lat,
            request.lon,
            site_elevation_m=request.elevation,
            azimuth_step_deg=request.azimuth_step_deg,
            max_distance_m=request.max_distance_m,
            ray_step_m=request.ray_step_m,
        )
        start = parse_timestamp_utc(request.timestamp)
        end = start + timedelta(days=LUNAR_NODAL_CYCLE_DAYS)
        analysis = analyze_sunlight_period(
            profile,
            start_time=start,
            end_time=end,
            step_minutes=request.step_minutes,
            max_samples=200_000,
            include_samples=False,
        )
        known_coverage = analysis["known_illumination_coverage_percentage"]
        if analysis["sunlit_duration_seconds"] > 0.0:
            classification = "not_candidate"
        elif known_coverage >= 99.9:
            classification = "candidate"
        else:
            classification = "unknown"

        return {
            "success": True,
            "site": {
                "latitude_deg": request.lat,
                "longitude_deg": request.lon,
                "elevation_m": profile.site_elevation_m,
            },
            "classification": classification,
            "is_psr_candidate": classification == "candidate",
            "is_permanently_shadowed": None,
            "analysis_scope": "18.6_earth_year_lunar_nodal_cycle_pre_screen",
            "cycle_years": LUNAR_NODAL_CYCLE_YEARS,
            "cycle_days": LUNAR_NODAL_CYCLE_DAYS,
            "step_minutes": request.step_minutes,
            "sample_count": analysis["sample_count"],
            "start_time_utc": analysis["start_time_utc"],
            "end_time_utc": analysis["end_time_utc"],
            "sunlit_duration_hours": analysis["sunlit_duration_hours"],
            "sunlit_percentage": analysis["sunlit_percentage"],
            "known_illumination_coverage_percentage": known_coverage,
            "analysis_quality": {
                "coverage": "complete" if known_coverage >= 99.9 else "partial",
                "dem_resolution_m": profile.dem_resolution_m,
                "ray_step_m": profile.ray_step_m,
                "max_distance_m": profile.max_distance_m,
                "azimuth_step_deg": profile.azimuth_step_deg,
                "time_step_minutes": request.step_minutes,
            },
            "note": (
                "No-sun results across the sampled nodal cycle are a long-period "
                "PSR pre-screen, not proof of permanent shadow. Output resolution "
                "is limited by DEM coverage, pixel size, ray spacing, and time step."
            ),
            "horizon": analysis["horizon"],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EphemerisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (FileNotFoundError, OSError) as exc:
        logger.exception("Could not load lunar nodal-cycle PSR screen")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
