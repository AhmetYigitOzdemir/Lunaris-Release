"""Topographic horizon and solar-visibility analysis for the LOLA south-pole DEM.

The full PDS3 image is memory-mapped when present. When the large, ignored IMG
file is unavailable, the already generated Plotly HTML can supply its embedded
surface matrix as a lower-resolution fallback.
"""

from __future__ import annotations
import os

import base64
import json
import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np

from coordinate_transform import (
    MOON_MEAN_RADIUS_M,
    latlon_to_polar_stereographic,
    polar_stereographic_to_latlon,
)
from ephemeris_engine import (
    compute_site_ephemeris,
    compute_sun_ephemerides,
    get_engine_status,
    get_kernel_coverage,
    parse_timestamp_utc,
)

DRACONIC_YEAR_DAYS = 346.62
"""Draconic (eclipse) year in days: the time for the Sun to return to the same
lunar node. Approximately 346.62 days. Used for the annual PSR pre-screen
interval. This is NOT a conventional lunar year (12 synodic months)."""

LUNAR_YEAR_DAYS = 354.367
"""Conventional lunar year in days: 12 synodic months at 29.53059 days each,
approximately 354.367 days. Provided for reference; not used by the PSR
pre-screen endpoints."""

LUNAR_NODAL_CYCLE_YEARS = 18.6
EARTH_YEAR_DAYS = 365.25
LUNAR_NODAL_CYCLE_DAYS = LUNAR_NODAL_CYCLE_YEARS * EARTH_YEAR_DAYS
_DATA_ROOT = Path(os.environ.get("LUNARIS_DATA_DIR", str(Path(__file__).resolve().parent))).expanduser()
DEFAULT_DEM_LABEL = _DATA_ROOT / "data" / "ldem_80s_40m_float.lbl"
DEFAULT_PLOTLY_HTML = Path(__file__).resolve().parent / "outputs" / "south_pole_3d.html"
_PDS_VALUE = re.compile(
    r"^[ \t]*([^/\r\n=]+?)[ \t]*=[ \t]*(.*?)[ \t]*$", re.MULTILINE
)
_PLOTLY_DTYPES = {
    "f4": "<f4",
    "f8": "<f8",
    "i1": "i1",
    "u1": "u1",
    "i2": "<i2",
    "u2": "<u2",
    "i4": "<i4",
    "u4": "<u4",
    "i8": "<i8",
    "u8": "<u8",
}


def _pds_value(text: str, key: str) -> str:
    for name, value in _PDS_VALUE.findall(text):
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    raise ValueError(f"PDS3 label is missing {key}")


def _pds_number(text: str, key: str) -> float:
    value = _pds_value(text, key)
    match = re.match(r"\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)", value)
    if not match:
        raise ValueError(f"PDS3 value {key} is not numeric: {value}")
    return float(match.group(1))


def _resolve_image(label_path: Path, image_name: str) -> Path:
    candidate = label_path.parent / image_name
    if candidate.is_file():
        return candidate
    for item in label_path.parent.iterdir():
        if item.is_file() and item.name.casefold() == image_name.casefold():
            return item
    raise FileNotFoundError(f"DEM image not found: {image_name}")


def _decode_plotly_array(value: Any) -> np.ndarray:
    if isinstance(value, list):
        return np.asarray(value, dtype=np.float64)
    if not isinstance(value, dict):
        raise ValueError("Unsupported Plotly surface array")
    if "bdata" not in value:
        return np.asarray(value, dtype=np.float64)

    dtype = _PLOTLY_DTYPES.get(str(value.get("dtype", "")))
    if dtype is None:
        raise ValueError(f"Unsupported Plotly array dtype: {value.get('dtype')}")
    array = np.frombuffer(base64.b64decode(value["bdata"]), dtype=np.dtype(dtype))
    shape = value.get("shape")
    if shape:
        dimensions = tuple(int(part.strip()) for part in str(shape).split(","))
        array = array.reshape(dimensions)
    return array.copy()


def _plotly_surface_from_html(html_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    html = html_path.read_text(encoding="utf-8")
    marker = "Plotly.newPlot("
    start = html.find(marker)
    if start < 0:
        raise ValueError(f"No Plotly chart found in {html_path}")
    decoder = json.JSONDecoder()
    cursor = start + len(marker)
    while html[cursor].isspace():
        cursor += 1
    _, cursor = decoder.raw_decode(html, cursor)  # chart div id
    cursor = html.index(",", cursor) + 1
    while html[cursor].isspace():
        cursor += 1
    traces, _ = decoder.raw_decode(html, cursor)

    surface = next(
        (trace for trace in traces if trace.get("type") == "surface" and "z" in trace),
        None,
    )
    if surface is None:
        raise ValueError(f"No surface DEM trace found in {html_path}")
    x = _decode_plotly_array(surface["x"]).reshape(-1)
    y = _decode_plotly_array(surface["y"]).reshape(-1)
    elevation = _decode_plotly_array(surface["z"])
    if elevation.ndim != 2 or elevation.shape != (y.size, x.size):
        raise ValueError("Plotly DEM axes do not match the embedded elevation grid")
    return elevation.astype(np.float32, copy=False), x * 1000.0, y * 1000.0


@dataclass(frozen=True)
class LunarDEM:
    """Regular polar-stereographic DEM grid with elevations in metres."""

    elevation_m: np.ndarray
    x_axis_m: np.ndarray
    y_axis_m: np.ndarray
    source: str
    elevation_scale_to_m: float = 1.0

    def __post_init__(self) -> None:
        values = np.asarray(self.elevation_m)
        x = np.asarray(self.x_axis_m, dtype=np.float64).reshape(-1)
        y = np.asarray(self.y_axis_m, dtype=np.float64).reshape(-1)
        if values.ndim != 2 or values.shape != (y.size, x.size):
            raise ValueError("DEM matrix shape must match its X/Y axes")
        if x.size < 2 or y.size < 2:
            raise ValueError("DEM must have at least two rows and columns")
        dx = np.diff(x)
        dy = np.diff(y)
        if np.any(dx <= 0.0) or not np.allclose(dx, dx[0], rtol=1e-4, atol=1e-3):
            raise ValueError("DEM X axis must be regularly spaced and ascending")
        if not (np.all(dy < 0.0) or np.all(dy > 0.0)) or not np.allclose(
            np.abs(dy), abs(dy[0]), rtol=1e-4, atol=1e-3
        ):
            raise ValueError("DEM Y axis must be regularly spaced")
        if dy[0] > 0.0:
            raise ValueError("DEM Y axis must descend from image row 0")

    @property
    def pixel_size_x_m(self) -> float:
        return float(self.x_axis_m[1] - self.x_axis_m[0])

    @property
    def pixel_size_y_m(self) -> float:
        return float(self.y_axis_m[0] - self.y_axis_m[1])

    def elevation_at(self, latitude_deg: float, longitude_deg: float) -> float:
        """Bilinearly sample the native DEM at a geographic site coordinate."""
        x_m, y_m = latlon_to_polar_stereographic(latitude_deg, longitude_deg)
        value, valid = _bilinear_sample(self, np.asarray(x_m), np.asarray(y_m))
        if not bool(valid):
            raise ValueError("Selected site is outside the available DEM coverage")
        return float(value)

    @classmethod
    def from_pds3(cls, label_path: Path) -> LunarDEM:
        """Memory-map a detached PDS3 PC_REAL/IEEE_REAL image."""
        label_path = Path(label_path).expanduser().resolve()
        label = label_path.read_text(encoding="utf-8", errors="replace")
        rows = int(_pds_number(label, "LINES"))
        cols = int(_pds_number(label, "LINE_SAMPLES"))
        bits = int(_pds_number(label, "SAMPLE_BITS"))
        sample_type = _pds_value(label, "SAMPLE_TYPE").upper()
        if bits != 32 or sample_type not in {"PC_REAL", "IEEE_REAL"}:
            raise ValueError("Horizon analysis supports 32-bit PDS3 real DEMs")
        image_path = _resolve_image(label_path, _pds_value(label, "^IMAGE"))
        expected_bytes = rows * cols * 4
        if image_path.stat().st_size < expected_bytes:
            raise ValueError(f"DEM image is truncated: {image_path}")

        dtype = "<f4" if sample_type == "PC_REAL" else ">f4"
        raw = np.memmap(image_path, mode="r", dtype=dtype, shape=(rows, cols))
        # PDS OFFSET is the reference radius; the stored float is the terrain
        # height relative to that radius and this project expresses it in km.
        pixel_size_m = _pds_number(label, "MAP_SCALE")
        x_offset = _pds_number(label, "SAMPLE_PROJECTION_OFFSET")
        y_offset = _pds_number(label, "LINE_PROJECTION_OFFSET")
        x_axis = (np.arange(cols, dtype=np.float64) - x_offset) * pixel_size_m
        y_axis = -(np.arange(rows, dtype=np.float64) - y_offset) * pixel_size_m
        return cls(raw, x_axis, y_axis, str(image_path), elevation_scale_to_m=1000.0)

    @classmethod
    def from_plotly_html(cls, html_path: Path) -> LunarDEM:
        """Load the pre-rendered surface when the raw IMG is not available."""
        elevation_m, x_axis_m, y_axis_m = _plotly_surface_from_html(Path(html_path))
        return cls(elevation_m, x_axis_m, y_axis_m, f"embedded surface: {html_path}")

    @classmethod
    def load(
        cls,
        label_path: Path = DEFAULT_DEM_LABEL,
        fallback_html_path: Path = DEFAULT_PLOTLY_HTML,
    ) -> LunarDEM:
        label_path = Path(label_path).expanduser()
        if label_path.is_file():
            try:
                return cls.from_pds3(label_path)
            except FileNotFoundError:
                if not Path(fallback_html_path).is_file():
                    raise
        if Path(fallback_html_path).is_file():
            return cls.from_plotly_html(Path(fallback_html_path))
        raise FileNotFoundError(
            f"No DEM image or pre-rendered Plotly surface found for {label_path}"
        )


@dataclass(frozen=True)
class HorizonProfile:
    latitude_deg: float
    longitude_deg: float
    site_elevation_m: float
    azimuth_step_deg: float
    max_distance_m: float
    ray_step_m: float
    dem_resolution_m: float
    dem_source: str
    azimuths_deg: tuple[float, ...]
    horizon_elevation_deg: tuple[float, ...]
    horizon_distance_m: tuple[float, ...]
    coverage_fraction: tuple[float, ...]

    def horizon_at(self, azimuth_deg: float) -> tuple[float, float, float]:
        """Circularly interpolate horizon angle, distance, and coverage."""
        if not self.azimuths_deg:
            raise ValueError("Horizon profile has no azimuth samples")
        if (
            len(self.horizon_elevation_deg) != len(self.azimuths_deg)
            or len(self.horizon_distance_m) != len(self.azimuths_deg)
            or len(self.coverage_fraction) != len(self.azimuths_deg)
        ):
            raise ValueError("Horizon profile arrays have inconsistent lengths")
        if not math.isfinite(self.azimuth_step_deg) or self.azimuth_step_deg <= 0.0:
            raise ValueError("azimuth_step_deg must be positive and finite")
        azimuth = float(azimuth_deg) % 360.0
        position = azimuth / self.azimuth_step_deg
        lower = int(math.floor(position)) % len(self.azimuths_deg)
        upper = (lower + 1) % len(self.azimuths_deg)
        fraction = position - math.floor(position)
        horizon = (
            self.horizon_elevation_deg[lower] * (1.0 - fraction)
            + self.horizon_elevation_deg[upper] * fraction
        )
        coverage = (
            self.coverage_fraction[lower] * (1.0 - fraction)
            + self.coverage_fraction[upper] * fraction
        )
        distance = (
            self.horizon_distance_m[lower] * (1.0 - fraction)
            + self.horizon_distance_m[upper] * fraction
        )
        horizon = float(horizon)
        coverage = float(coverage)
        distance = float(distance)
        if not math.isfinite(horizon) or not math.isfinite(coverage) or not math.isfinite(distance):
            raise ValueError("Horizon profile contains non-finite values")
        return horizon, distance, coverage


def _bilinear_sample(
    dem: LunarDEM, x_m: np.ndarray, y_m: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized bilinear sample; returns values and an in-DEM mask."""
    col = (x_m - dem.x_axis_m[0]) / dem.pixel_size_x_m
    row = (dem.y_axis_m[0] - y_m) / dem.pixel_size_y_m
    height, width = dem.elevation_m.shape
    valid = (
        np.isfinite(col)
        & np.isfinite(row)
        & (col >= 0.0)
        & (col <= width - 1)
        & (row >= 0.0)
        & (row <= height - 1)
    )
    safe_col = np.clip(np.where(valid, col, 0.0), 0.0, width - 1.0)
    safe_row = np.clip(np.where(valid, row, 0.0), 0.0, height - 1.0)
    col0 = np.floor(safe_col).astype(np.intp)
    row0 = np.floor(safe_row).astype(np.intp)
    col1 = np.minimum(col0 + 1, width - 1)
    row1 = np.minimum(row0 + 1, height - 1)
    dx = safe_col - col0
    dy = safe_row - row0

    z00 = dem.elevation_m[row0, col0]
    z01 = dem.elevation_m[row0, col1]
    z10 = dem.elevation_m[row1, col0]
    z11 = dem.elevation_m[row1, col1]
    values = (
        z00 * (1.0 - dx) * (1.0 - dy)
        + z01 * dx * (1.0 - dy)
        + z10 * (1.0 - dx) * dy
        + z11 * dx * dy
    ) * dem.elevation_scale_to_m
    valid &= np.isfinite(values)
    return np.where(valid, values, np.nan), valid


def validate_dem_coverage(
    dem: LunarDEM,
    latitude_deg: float,
    longitude_deg: float,
    *,
    radius_m: float | None = None,
    cell_size_m: float | None = None,
) -> dict[str, Any]:
    """Assess DEM coverage for a geographic site and optional analysis area.

    Returns a dictionary with coverage status and diagnostics. The status
    distinguishes between a coordinate outside the DEM's projected raster,
    a coordinate inside the raster with invalid elevation data, and a valid
    coordinate with full or partial surrounding coverage.

    Parameters
    ----------
    dem:
        The loaded DEM.
    latitude_deg, longitude_deg:
        Site coordinates in planetocentric degrees.
    radius_m:
        Optional analysis radius in metres for surrounding coverage check.
    cell_size_m:
        Optional sampling cell size for the surrounding coverage check.

    Returns
    -------
    dict[str, Any]
        Keys: ``status`` (one of ``available``, ``partial_coverage``,
        ``outside_dem``, ``invalid_dem_data``), ``coverage_percentage``,
        ``elevation_m``, ``error_message``.
    """
    latitude = float(latitude_deg)
    longitude = float(longitude_deg) % 360.0

    # Step 1: Check if the site coordinate projects into the DEM raster.
    try:
        x_m, y_m = latlon_to_polar_stereographic(latitude, longitude)
    except ValueError:
        return {
            "status": "outside_dem",
            "coverage_percentage": 0.0,
            "elevation_m": None,
            "error_message": (
                f"Latitude {latitude_deg} is outside the valid range "
                "[-90, 0] for the south-polar DEM."
            ),
        }

    col = (x_m - dem.x_axis_m[0]) / dem.pixel_size_x_m
    row = (dem.y_axis_m[0] - y_m) / dem.pixel_size_y_m
    height, width = dem.elevation_m.shape

    in_raster = (
        0.0 <= col <= width - 1
        and 0.0 <= row <= height - 1
    )

    if not in_raster:
        return {
            "status": "outside_dem",
            "coverage_percentage": 0.0,
            "elevation_m": None,
            "error_message": (
                f"Site ({latitude_deg}, {longitude_deg}) projects to pixel "
                f"({col:.1f}, {row:.1f}) outside the DEM raster "
                f"({width} x {height})."
            ),
        }

    # Step 2: Sample the site elevation.
    site_value, site_valid = _bilinear_sample(
        dem, np.asarray(x_m), np.asarray(y_m)
    )
    site_elevation = float(site_value) if bool(site_valid) else None

    if site_elevation is None or not math.isfinite(site_elevation):
        return {
            "status": "invalid_dem_data",
            "coverage_percentage": 0.0,
            "elevation_m": None,
            "error_message": (
                f"Site ({latitude_deg}, {longitude_deg}) is inside the DEM "
                f"raster but contains invalid elevation data."
            ),
        }

    # Step 3: If no analysis radius requested, the site itself is available.
    if radius_m is None:
        return {
            "status": "available",
            "coverage_percentage": 100.0,
            "elevation_m": site_elevation,
            "error_message": None,
        }

    # Step 4: Check surrounding analysis area coverage.
    native_resolution = max(dem.pixel_size_x_m, dem.pixel_size_y_m)
    spacing = (
        float(cell_size_m)
        if cell_size_m is not None
        else native_resolution
    )
    center_x, center_y = x_m, y_m
    half_cells = int(math.ceil(radius_m / spacing))
    offsets = np.arange(-half_cells, half_cells + 1, dtype=np.float64) * spacing
    x_grid, y_grid = np.meshgrid(center_x + offsets, center_y + offsets)
    patch_elevation, patch_valid = _bilinear_sample(dem, x_grid, y_grid)
    patch_valid = np.asarray(patch_valid, dtype=bool) & np.isfinite(
        np.asarray(patch_elevation, dtype=np.float64)
    )
    coverage_pct = float(np.mean(patch_valid) * 100.0)

    if coverage_pct >= 99.0:
        status = "available"
    elif coverage_pct > 0.0:
        status = "partial_coverage"
    else:
        status = "outside_dem"

    return {
        "status": status,
        "coverage_percentage": coverage_pct,
        "elevation_m": site_elevation,
        "error_message": None
        if status == "available"
        else f"Surrounding analysis coverage is {coverage_pct:.1f}%.",
    }


def _geodesic_rays(
    latitude_rad: float,
    longitude_rad: float,
    azimuth_rad: np.ndarray,
    distance_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Spherical forward geodesic for ray cells; azimuth is clockwise from north."""
    delta = distance_m[None, :] / MOON_MEAN_RADIUS_M
    sin_lat = math.sin(latitude_rad)
    cos_lat = math.cos(latitude_rad)
    sin_delta = np.sin(delta)
    cos_delta = np.cos(delta)
    sin_az = np.sin(azimuth_rad)[:, None]
    cos_az = np.cos(azimuth_rad)[:, None]
    if abs(cos_lat) < 1e-12:
        # Longitude is singular at the pole. In this limit the initial bearing
        # itself selects the destination meridian.
        lat2 = np.broadcast_to(-np.pi / 2.0 + delta, (azimuth_rad.size, distance_m.size))
        lon2 = longitude_rad + azimuth_rad[:, None]
    else:
        lat2 = np.arcsin(
            np.clip(sin_lat * cos_delta + cos_lat * sin_delta * cos_az, -1.0, 1.0)
        )
        lon2 = longitude_rad + np.arctan2(
            sin_az * sin_delta * cos_lat,
            cos_delta - sin_lat * np.sin(lat2),
        )
    rho = 2.0 * MOON_MEAN_RADIUS_M * np.tan(np.pi / 4.0 + lat2 / 2.0)
    x_m = rho * np.sin(lon2)
    y_m = -rho * np.cos(lon2)
    return x_m, y_m


def calculate_horizon_profile(
    dem: LunarDEM,
    latitude_deg: float,
    longitude_deg: float,
    *,
    site_elevation_m: float | None = None,
    azimuth_step_deg: float = 1.0,
    max_distance_m: float = 200_000.0,
    ray_step_m: float | None = None,
    azimuth_chunk_size: int = 32,
) -> HorizonProfile:
    """Calculate terrain skyline angles around a lunar site.

    Rays follow great-circle bearings, sample the DEM bilinearly, and account
    for lunar curvature. Returned azimuths use 0°=north and 90°=east. The
    geometric limb is treated as a 0° minimum horizon. ``coverage_fraction``
    reports how much of each requested ray remained inside valid DEM cells.
    """
    latitude = float(latitude_deg)
    longitude = float(longitude_deg) % 360.0
    az_step = float(azimuth_step_deg)
    max_distance = float(max_distance_m)
    if not math.isfinite(latitude) or not -90.0 <= latitude <= 0.0:
        raise ValueError("latitude_deg must be within [-90, 0] degrees")
    if not math.isfinite(longitude):
        raise ValueError("longitude_deg must be finite")
    if not math.isfinite(az_step) or az_step <= 0.0 or az_step > 10.0:
        raise ValueError("azimuth_step_deg must be in (0, 10]")
    ray_count = int(round(360.0 / az_step))
    if not math.isclose(ray_count * az_step, 360.0, rel_tol=1e-7, abs_tol=1e-7):
        raise ValueError("azimuth_step_deg must divide 360 evenly")
    if not math.isfinite(max_distance) or max_distance <= 0.0:
        raise ValueError("max_distance_m must be positive and finite")

    native_resolution = max(dem.pixel_size_x_m, dem.pixel_size_y_m)
    ray_step = native_resolution if ray_step_m is None else float(ray_step_m)
    if not math.isfinite(ray_step) or ray_step <= 0.0:
        raise ValueError("ray_step_m must be positive and finite")
    if azimuth_chunk_size < 1:
        raise ValueError("azimuth_chunk_size must be positive")

    terrain_site_elevation = dem.elevation_at(latitude, longitude)
    observer_elevation = (
        terrain_site_elevation
        if site_elevation_m is None
        else float(site_elevation_m)
    )
    if not math.isfinite(observer_elevation):
        raise ValueError("site_elevation_m must be finite")

    sample_count = int(math.floor(max_distance / ray_step))
    if sample_count < 1:
        raise ValueError("No ray samples fit within max_distance_m")
    distance = np.arange(1, sample_count + 1, dtype=np.float64) * ray_step
    azimuths = np.arange(ray_count, dtype=np.float64) * az_step
    azimuth_rad = np.deg2rad(azimuths)
    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)
    horizon = np.zeros(ray_count, dtype=np.float64)
    horizon_distance = np.zeros(ray_count, dtype=np.float64)
    coverage = np.zeros(ray_count, dtype=np.float64)
    target_radius = MOON_MEAN_RADIUS_M + observer_elevation

    for start in range(0, ray_count, azimuth_chunk_size):
        stop = min(start + azimuth_chunk_size, ray_count)
        ray_x, ray_y = _geodesic_rays(
            lat_rad, lon_rad, azimuth_rad[start:stop], distance
        )
        terrain, valid = _bilinear_sample(dem, ray_x, ray_y)
        coverage[start:stop] = np.mean(valid, axis=1)

        delta = distance[None, :] / MOON_MEAN_RADIUS_M
        terrain_radius = MOON_MEAN_RADIUS_M + terrain
        vertical = terrain_radius * np.cos(delta) - target_radius
        horizontal = terrain_radius * np.sin(delta)
        angles = np.rad2deg(np.arctan2(vertical, horizontal))
        angles[~valid] = -np.inf
        best_index = np.argmax(angles, axis=1)
        best_angle = np.max(angles, axis=1)
        horizon[start:stop] = np.maximum(0.0, best_angle)
        best_distance = distance[best_index]
        horizon_distance[start:stop] = np.where(best_angle > 0.0, best_distance, 0.0)

    return HorizonProfile(
        latitude_deg=latitude,
        longitude_deg=longitude,
        site_elevation_m=observer_elevation,
        azimuth_step_deg=az_step,
        max_distance_m=max_distance,
        ray_step_m=ray_step,
        dem_resolution_m=native_resolution,
        dem_source=dem.source,
        azimuths_deg=tuple(float(value) for value in azimuths),
        horizon_elevation_deg=tuple(float(value) for value in horizon),
        horizon_distance_m=tuple(float(value) for value in horizon_distance),
        coverage_fraction=tuple(float(value) for value in coverage),
    )


def calculate_landing_safety_patch(
    dem: LunarDEM,
    latitude_deg: float,
    longitude_deg: float,
    *,
    radius_m: float = 1000.0,
    cell_size_m: float | None = None,
) -> dict[str, Any]:
    """Build a local slope screen and planar-detrended roughness summary.

    The patch is sampled in the DEM's polar-stereographic map plane. Slope
    thresholds follow commonly used lunar landing screens (5° goal, 8° limit);
    40 m source pixels cannot resolve small rocks or lander-scale hazards.
    """
    latitude = float(latitude_deg)
    longitude = float(longitude_deg) % 360.0
    radius = float(radius_m)
    native_resolution = max(dem.pixel_size_x_m, dem.pixel_size_y_m)
    if cell_size_m is not None:
        requested_cell_size = float(cell_size_m)
        if (
            not math.isfinite(requested_cell_size)
            or requested_cell_size <= 0.0
            or requested_cell_size > 1000.0
        ):
            raise ValueError("cell_size_m must be within (0, 1000]")
    else:
        requested_cell_size = None
    spacing = native_resolution if requested_cell_size is None else requested_cell_size
    if not math.isfinite(latitude) or not -90.0 <= latitude <= 0.0:
        raise ValueError("latitude_deg must be within [-90, 0] degrees")
    if not math.isfinite(longitude):
        raise ValueError("longitude_deg must be finite")
    if not math.isfinite(radius) or radius <= 0.0 or radius > 5000.0:
        raise ValueError("radius_m must be within (0, 5000]")
    if not math.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("cell_size_m must be within (0, 1000]")

    center_x, center_y = latlon_to_polar_stereographic(latitude, longitude)
    half_cells = int(math.ceil(radius / spacing))
    offsets = np.arange(-half_cells, half_cells + 1, dtype=np.float64) * spacing
    x_grid, y_grid = np.meshgrid(center_x + offsets, center_y + offsets)
    elevation, valid = _bilinear_sample(dem, x_grid, y_grid)
    elevation = np.asarray(elevation, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool) & np.isfinite(elevation)

    safe_elevation = np.where(valid, elevation, 0.0)
    gradient_y, gradient_x = np.gradient(safe_elevation, spacing, spacing)
    slope_deg = np.degrees(np.arctan(np.hypot(gradient_x, gradient_y)))
    neighborhood_valid = np.zeros_like(valid)
    valid_windows = np.lib.stride_tricks.sliding_window_view(valid, (3, 3)).all(
        axis=(-2, -1)
    )
    neighborhood_valid[1:-1, 1:-1] = valid_windows
    # Patch borders have no full 3x3 neighbourhood inside the matrix, but their
    # immediate gradient is still well defined by NumPy's edge mode. Keep the
    # invalid-neighbour protection for interior cells while allowing valid
    # border cells to receive a slope instead of becoming grey.
    border_valid = np.zeros_like(valid)
    border_valid[0, :] = True
    border_valid[-1, :] = True
    border_valid[:, 0] = True
    border_valid[:, -1] = True
    slope_valid = valid & np.isfinite(slope_deg) & (neighborhood_valid | border_valid)

    windows = np.lib.stride_tricks.sliding_window_view(
        safe_elevation, (3, 3)
    ).reshape(-1, 9)
    roughness_valid = valid_windows.reshape(-1)
    local_axis = np.arange(-1, 2, dtype=np.float64) * spacing
    local_x, local_y = np.meshgrid(local_axis, local_axis)
    design = np.column_stack(
        (np.ones(9, dtype=np.float64), local_x.reshape(-1), local_y.reshape(-1))
    )
    coefficients = windows @ np.linalg.pinv(design).T
    residuals = windows - coefficients @ design.T
    roughness = np.sqrt(np.mean(residuals * residuals, axis=1))
    roughness = roughness[roughness_valid & np.isfinite(roughness)]

    slope_values = slope_deg[slope_valid]
    if slope_values.size:
        below_five_pct = float(np.mean(slope_values <= 5.0) * 100.0)
        below_eight_pct = float(np.mean(slope_values <= 8.0) * 100.0)
    else:
        below_five_pct = None
        below_eight_pct = None

    return {
        "latitude_deg": latitude,
        "longitude_deg": longitude,
        "radius_m": radius,
        "cell_size_m": spacing,
        "grid_size": int(offsets.size),
        "dem_resolution_m": native_resolution,
        "coverage_percentage": float(np.mean(valid) * 100.0),
        "slope_coverage_percentage": float(np.mean(slope_valid) * 100.0),
        "slope_below_5_deg_percentage": below_five_pct,
        "slope_below_8_deg_percentage": below_eight_pct,
        "slope_median_deg": float(np.median(slope_values))
        if slope_values.size
        else None,
        "slope_p95_deg": float(np.percentile(slope_values, 95))
        if slope_values.size
        else None,
        "roughness_median_m": float(np.median(roughness)) if roughness.size else None,
        "roughness_p95_m": float(np.percentile(roughness, 95))
        if roughness.size
        else None,
        "slope_deg": [
            [float(round(value, 2)) if slope_valid[row, col] else None for col, value in enumerate(row_values)]
            for row, row_values in enumerate(slope_deg)
        ],
        "note": (
            "Screening only: DEM pixel resolution does not resolve small rocks, "
            "crater rims, or lander-footprint hazards."
        ),
    }


def _slope_score(slope_deg: float) -> float:
    if slope_deg <= 5.0:
        return 100.0
    if slope_deg <= 8.0:
        return 100.0 - (slope_deg - 5.0) / 3.0 * 40.0
    if slope_deg <= 15.0:
        return 60.0 - (slope_deg - 8.0) / 7.0 * 60.0
    return 0.0


def _roughness_score(roughness_m: float) -> float:
    if not math.isfinite(roughness_m):
        return 100.0
    if roughness_m <= 0.5:
        return 100.0
    if roughness_m <= 2.0:
        return 100.0 - (roughness_m - 0.5) / 1.5 * 50.0
    return max(0.0, 50.0 - (roughness_m - 2.0) * 10.0)


def calculate_landing_suitability_index(
    dem: LunarDEM,
    latitude_deg: float,
    longitude_deg: float,
    *,
    radius_m: float = 1000.0,
    cell_size_m: float | None = None,
) -> dict[str, Any]:
    """Compute a 0-100 landing suitability index for a local DEM patch."""
    latitude = float(latitude_deg)
    longitude = float(longitude_deg) % 360.0
    radius = float(radius_m)
    native_resolution = max(dem.pixel_size_x_m, dem.pixel_size_y_m)
    if cell_size_m is not None:
        requested_cell_size = float(cell_size_m)
        if (
            not math.isfinite(requested_cell_size)
            or requested_cell_size <= 0.0
            or requested_cell_size > 1000.0
        ):
            raise ValueError("cell_size_m must be within (0, 1000]")
    else:
        requested_cell_size = None
    if (
        not math.isfinite(latitude)
        or not -90.0 <= latitude <= 0.0
        or not math.isfinite(longitude)
        or not math.isfinite(radius)
        or radius <= 0.0
        or radius > 5000.0
    ):
        raise ValueError("Invalid landing suitability inputs")
    spacing = native_resolution if requested_cell_size is None else requested_cell_size
    if not math.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("cell_size_m must be within (0, 1000]")

    center_x, center_y = latlon_to_polar_stereographic(latitude, longitude)
    half_cells = int(math.ceil(radius / spacing))
    offsets = np.arange(-half_cells, half_cells + 1, dtype=np.float64) * spacing
    x_grid, y_grid = np.meshgrid(center_x + offsets, center_y + offsets)
    elevation, valid = _bilinear_sample(dem, x_grid, y_grid)
    elevation = np.asarray(elevation, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool) & np.isfinite(elevation)

    safe_elevation = np.where(valid, elevation, 0.0)
    gradient_y, gradient_x = np.gradient(safe_elevation, spacing, spacing)
    slope_deg = np.degrees(np.arctan(np.hypot(gradient_x, gradient_y)))

    neighborhood_valid = np.zeros_like(valid)
    valid_windows = np.lib.stride_tricks.sliding_window_view(valid, (3, 3)).all(
        axis=(-2, -1)
    )
    neighborhood_valid[1:-1, 1:-1] = valid_windows
    border_valid = np.zeros_like(valid)
    border_valid[0, :] = True
    border_valid[-1, :] = True
    border_valid[:, 0] = True
    border_valid[:, -1] = True
    slope_valid = valid & np.isfinite(slope_deg) & (neighborhood_valid | border_valid)

    roughness_grid = np.full(slope_deg.shape, np.nan, dtype=np.float64)
    if valid.shape[0] >= 3 and valid.shape[1] >= 3:
        windows = np.lib.stride_tricks.sliding_window_view(
            safe_elevation, (3, 3)
        ).reshape(-1, 9)
        local_axis = np.arange(-1, 2, dtype=np.float64) * spacing
        local_x, local_y = np.meshgrid(local_axis, local_axis)
        design = np.column_stack(
            (np.ones(9, dtype=np.float64), local_x.reshape(-1), local_y.reshape(-1))
        )
        coefficients = windows @ np.linalg.pinv(design).T
        residuals = windows - coefficients @ design.T
        roughness_values = np.sqrt(np.mean(residuals * residuals, axis=1))
        roughness_grid[1:-1, 1:-1] = roughness_values.reshape(
            valid.shape[0] - 2, valid.shape[1] - 2
        )

    lsi_grid = np.full(slope_deg.shape, np.nan, dtype=np.float64)
    for row in range(slope_deg.shape[0]):
        for col in range(slope_deg.shape[1]):
            if not valid[row, col]:
                continue
            if slope_valid[row, col]:
                slope_component = _slope_score(float(slope_deg[row, col]))
            else:
                slope_component = 0.0
            roughness_component = _roughness_score(float(roughness_grid[row, col]))
            lsi_grid[row, col] = 0.7 * slope_component + 0.3 * roughness_component

    valid_lsi = lsi_grid[valid]
    if valid_lsi.size:
        score = float(np.nanmean(valid_lsi))
    else:
        score = 0.0
    if not math.isfinite(score):
        score = 0.0
    score = min(100.0, max(0.0, score))

    if score >= 85.0:
        suitability_class = "A"
    elif score >= 70.0:
        suitability_class = "B"
    elif score >= 50.0:
        suitability_class = "C"
    else:
        suitability_class = "D"

    slope_values = slope_deg[slope_valid]
    roughness_values_flat = roughness_grid[np.isfinite(roughness_grid)]
    below_five_pct = (
        float(np.mean(slope_values <= 5.0) * 100.0) if slope_values.size else None
    )
    below_eight_pct = (
        float(np.mean(slope_values <= 8.0) * 100.0) if slope_values.size else None
    )

    return {
        "latitude_deg": latitude,
        "longitude_deg": longitude,
        "radius_m": radius,
        "cell_size_m": spacing,
        "grid_size": int(offsets.size),
        "dem_resolution_m": native_resolution,
        "coverage_percentage": float(np.mean(valid) * 100.0),
        "slope_coverage_percentage": float(np.mean(slope_valid) * 100.0),
        "slope_below_5_deg_percentage": below_five_pct,
        "slope_below_8_deg_percentage": below_eight_pct,
        "slope_median_deg": float(np.median(slope_values)) if slope_values.size else None,
        "slope_p95_deg": float(np.percentile(slope_values, 95)) if slope_values.size else None,
        "roughness_median_m": float(np.median(roughness_values_flat))
        if roughness_values_flat.size
        else None,
        "roughness_p95_m": float(np.percentile(roughness_values_flat, 95))
        if roughness_values_flat.size
        else None,
        "lsi_score": score,
        "lsi": score,
        "score": score,
        "suitability_score": score,
        "lsi_class": suitability_class,
        "suitability_class": suitability_class,
        "class": suitability_class,
        "lsi_grid": [
            [None if not np.isfinite(value) else float(round(value, 2)) for value in row]
            for row in lsi_grid
        ],
        "suitability_grid": [
            [None if not np.isfinite(value) else float(round(value, 2)) for value in row]
            for row in lsi_grid
        ],
        "note": (
            "Screening only: LSI combines slope and roughness; DEM pixel resolution "
            "does not resolve small rocks, crater rims, or lander-footprint hazards."
        ),
    }


calculate_lsi = calculate_landing_suitability_index
calculate_lsi_score = calculate_landing_suitability_index
landing_suitability_index = calculate_landing_suitability_index


def check_earth_los(
    profile: HorizonProfile,
    earth_azimuth_deg: float,
    earth_elevation_deg: float,
    *,
    minimum_coverage: float = 0.9,
) -> dict[str, Any]:
    """Compare an Earth line-of-sight vector with the local terrain horizon.

    ``earth_visible`` is true when the Earth's angular elevation is above the
    topographic horizon in its azimuth direction.  This is the same geometric
    test used for instantaneous solar visibility, but exposed separately for
    Earth-visibility screening.

    This is a geometric line-of-sight test only. An unobstructed view of Earth
    is necessary but not sufficient for a communication link; link budget,
    antenna gain, frequency, and other propagation factors are not modeled.
    Use ``geometric_earth_visibility`` for the terrain-obstruction result.
    The ``communication_status`` field is deprecated; prefer
    ``geometric_earth_visibility``.
    """
    azimuth = float(earth_azimuth_deg) % 360.0
    elevation = float(earth_elevation_deg)
    if not math.isfinite(azimuth) or not math.isfinite(elevation):
        raise ValueError("Earth azimuth and elevation must be finite")
    if not math.isfinite(minimum_coverage) or not 0.0 <= minimum_coverage <= 1.0:
        raise ValueError("minimum_coverage must be within [0, 1]")
    if profile is None or not hasattr(profile, "horizon_at"):
        raise ValueError("profile must be a valid HorizonProfile")
    horizon, horizon_distance, coverage = profile.horizon_at(azimuth)
    horizon = float(horizon)
    horizon_distance = float(horizon_distance)
    coverage = float(coverage)
    if not math.isfinite(horizon) or not math.isfinite(horizon_distance) or not math.isfinite(coverage):
        raise ValueError("Terrain horizon values must be finite")
    known = coverage >= minimum_coverage
    visible = elevation > horizon
    geometric_visibility = "visible" if visible else "not_visible"
    return {
        "earth_azimuth_deg": azimuth,
        "earth_azimuth": azimuth,
        "earth_elevation_deg": elevation,
        "earth_elevation": elevation,
        "terrain_horizon_deg": horizon,
        "terrain_horizon_distance_m": horizon_distance,
        "dem_coverage_fraction": coverage,
        "minimum_coverage": minimum_coverage,
        "horizon_coverage_complete": bool(known),
        "earth_visible": bool(visible),
        "geometric_earth_visibility": geometric_visibility,
        # Deprecated: geometric visibility is not a communication link assessment.
        "communication_status": "OPEN" if visible else "BLOCKED",
    }


def check_solar_visibility(
    profile: HorizonProfile,
    solar_azimuth_deg: float,
    solar_elevation_deg: float,
    *,
    minimum_coverage: float = 0.9,
) -> dict[str, Any]:
    """Compare SPICE solar angles against the interpolated terrain horizon.

    A single observation is reported as current shadow/sunlight, never as a
    permanent-shadow classification. Low DEM coverage yields ``unknown``.
    """
    azimuth = float(solar_azimuth_deg) % 360.0
    elevation = float(solar_elevation_deg)
    if not math.isfinite(azimuth) or not math.isfinite(elevation):
        raise ValueError("Solar azimuth and elevation must be finite")
    horizon, horizon_distance, coverage = profile.horizon_at(azimuth)
    known = coverage >= minimum_coverage
    is_night = elevation <= 0.0
    terrain_blocks_sun = elevation > 0.0 and elevation <= horizon
    if is_night or terrain_blocks_sun:
        # Night is dark regardless of terrain coverage. A DEM-observed ridge
        # that already rises above the Sun also proves a shadow even when the
        # remainder of that ray extends beyond the DEM footprint.
        is_sunlit = False
    elif known:
        is_sunlit = True
    else:
        is_sunlit = None
    return {
        "solar_azimuth_deg": azimuth,
        "solar_elevation_deg": elevation,
        "terrain_horizon_deg": horizon,
        "terrain_horizon_distance_m": horizon_distance,
        "horizon_coverage_complete": known,
        "dem_coverage_fraction": coverage,
        "visibility": (
            "unknown" if is_sunlit is None else "sunlit" if is_sunlit else "shadowed"
        ),
        "is_sunlit": is_sunlit,
        "is_night": is_night,
        "is_topographically_shadowed": (
            bool(terrain_blocks_sun)
            if is_sunlit is not None
            else None
        ),
        "is_permanently_shadowed": None,
        "analysis_distance_m": profile.max_distance_m,
    }


def _sun_az_el_at(
    lat: float, lon: float, elevation_m: float, when: datetime
) -> tuple[float, float]:
    """Apparent Sun azimuth/elevation (deg) at a UTC instant."""
    result = compute_site_ephemeris(
        lat, lon, elevation_m, when.isoformat().replace("+00:00", "Z")
    )
    return float(result["sun"]["azimuth_deg"]), float(result["sun"]["elevation_deg"])


def _sun_clearance_deg(
    when: datetime,
    profile: HorizonProfile,
    lat: float,
    lon: float,
    elevation_m: float,
    reference: str,
    *,
    coverage_min: float = 0.9,
) -> float:
    """Solar elevation minus the reference horizon (deg).

    Positive => Sun above the reference horizon (sunlit); negative => below
    (shadowed/night). Zero crossings are sunrise/sunset transitions.

    Returns ``nan`` when the DEM coverage at the solar azimuth is below
    ``coverage_min`` so that callers cannot mistake an unreliable (extrapolated
    or out-of-footprint) horizon for a valid transition.
    """
    az, el = _sun_az_el_at(lat, lon, elevation_m, when)
    if reference == "astronomical":
        horizon = 0.0
        coverage = 1.0
    else:
        horizon, _distance, coverage = profile.horizon_at(az)
    if not math.isfinite(coverage) or coverage < coverage_min:
        return float("nan")
    return el - horizon


def find_sun_transitions(
    profile: HorizonProfile,
    lat: float,
    lon: float,
    elevation_m: float,
    start_time: str | datetime,
    end_time: str | datetime,
    *,
    step_minutes: float = 10.0,
    reference: str = "terrain",
    tol_seconds: float = 60.0,
    elev_tol_deg: float = 0.01,
    max_iter: int = 60,
    coverage_min: float = 0.9,
) -> dict[str, Any]:
    """Bracket and refine Sun/reference-horizon transitions (sunrise/sunset).

    Coarse sunlight samples locate sign changes of the Sun-clearance function
    (solar elevation minus the reference horizon); each bracket is refined
    with bisection. Returns transition events with interpolated UTC time,
    type, and convergence diagnostics. This is additive to the discrete
    sunlight-percentage estimate and does not alter it.

    Parameters
    ----------
    profile:
        Terrain horizon profile for the site.
    lat, lon:
        Site planetocentric/east-positive longitude in degrees.
    elevation_m:
        Site height above the 1737.4 km reference sphere in metres.
    start_time, end_time:
        UTC interval bounds.
    step_minutes:
        Coarse sampling interval used to bracket transitions.
    reference:
        ``"terrain"`` (default) uses the interpolated DEM horizon;
        ``"astronomical`` uses a flat horizon at elevation 0 deg.
    tol_seconds:
        Convergence tolerance on the transition time (seconds).
    elev_tol_deg:
        Convergence tolerance on the Sun clearance (degrees).
    max_iter:
        Maximum bisection iterations per bracket.
    coverage_min:
        Minimum DEM coverage fraction (0-1) required at the solar azimuth for
        a clearance sample to be considered valid. Samples below this
        threshold are treated as unknown and do not generate transitions.
    """
    start, end = _time_range(start_time, end_time)
    step = float(step_minutes)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("step_minutes must be positive and finite")
    reference = str(reference).lower()
    if reference not in ("terrain", "astronomical"):
        raise ValueError("reference must be 'terrain' or 'astronomical'")
    tol = float(tol_seconds)
    if not math.isfinite(tol) or tol <= 0.0:
        raise ValueError("tol_seconds must be positive and finite")
    elev_tol = float(elev_tol_deg)
    if not math.isfinite(elev_tol) or elev_tol <= 0.0:
        raise ValueError("elev_tol_deg must be positive and finite")
    cov_min = float(coverage_min)
    if not math.isfinite(cov_min) or not 0.0 <= cov_min <= 1.0:
        raise ValueError("coverage_min must be within [0, 1]")

    interval_seconds = step * 60.0
    sample_times: list[datetime] = []
    current = start
    while current < end:
        sample_times.append(current)
        current = min(current + timedelta(seconds=interval_seconds), end)
    if not sample_times or sample_times[-1] != end:
        sample_times.append(end)

    clearances: list[float] = []
    for t in sample_times:
        try:
            clearances.append(
                _sun_clearance_deg(
                    t, profile, lat, lon, elevation_m, reference,
                    coverage_min=cov_min,
                )
            )
        except Exception:
            clearances.append(float("nan"))

    def _sgn(v: float) -> int:
        if v > 0.0:
            return 1
        if v < 0.0:
            return -1
        return 0

    transitions: list[dict[str, Any]] = []
    for i in range(len(sample_times) - 1):
        t0, t1 = sample_times[i], sample_times[i + 1]
        f0, f1 = clearances[i], clearances[i + 1]
        if not (math.isfinite(f0) and math.isfinite(f1)):
            continue
        s0, s1 = _sgn(f0), _sgn(f1)
        if s0 == 0:
            az, el = _safe_sun_az_el(lat, lon, elevation_m, t0)
            horizon, _dist, coverage = (
                profile.horizon_at(az) if reference == "terrain" else (0.0, 0.0, 1.0)
            )
            transitions.append(
                {
                    "timestamp_utc": t0.isoformat().replace("+00:00", "Z"),
                    "type": "sunrise" if f1 > 0.0 else "sunset" if f1 < 0.0 else "crossing",
                    "sun_azimuth_deg": round(float(az), 6),
                    "sun_elevation_deg": round(float(el), 6),
                    "reference_horizon_deg": round(float(horizon), 6),
                    "clearance_deg": 0.0,
                    "dem_coverage_fraction": round(float(coverage), 4),
                    "converged": True,
                    "iterations": 0,
                    "bracket_start_utc": t0.isoformat().replace("+00:00", "Z"),
                    "bracket_end_utc": t1.isoformat().replace("+00:00", "Z"),
                }
            )
            continue
        if s0 * s1 >= 0:
            continue
        # Bisection refinement of the zero crossing.
        a, b = t0, t1
        fa, fb = f0, f1
        iterations = 0
        converged = False
        while (b - a).total_seconds() > tol and iterations < max_iter:
            mid = a + (b - a) / 2.0
            try:
                fm = _sun_clearance_deg(
                    mid, profile, lat, lon, elevation_m, reference,
                    coverage_min=cov_min,
                )
            except Exception:
                break
            if not math.isfinite(fm):
                break
            iterations += 1
            if abs(fm) <= elev_tol:
                converged = True
                a = b = mid
                break
            if (fa > 0.0) == (fm > 0.0):
                a, fa = mid, fm
            else:
                b, fb = mid, fm
        else:
            # Exited without a break: converged only if the width tolerance
            # was met before max_iter was exhausted.
            converged = iterations < max_iter
        t_trans = a + (b - a) / 2.0
        if f0 < 0.0 and f1 > 0.0:
            t_type = "sunrise"
        elif f0 > 0.0 and f1 < 0.0:
            t_type = "sunset"
        else:
            t_type = "crossing"
        az, el = _safe_sun_az_el(lat, lon, elevation_m, t_trans)
        horizon, _dist, coverage = (
            profile.horizon_at(az) if reference == "terrain" else (0.0, 0.0, 1.0)
        )
        transitions.append(
            {
                "timestamp_utc": t_trans.isoformat().replace("+00:00", "Z"),
                "type": t_type,
                "sun_azimuth_deg": round(float(az), 6),
                "sun_elevation_deg": round(float(el), 6),
                "reference_horizon_deg": round(float(horizon), 6),
                "clearance_deg": round(float(el - horizon), 6),
                "dem_coverage_fraction": round(float(coverage), 4),
                "converged": bool(converged),
                "iterations": int(iterations),
                "bracket_start_utc": t0.isoformat().replace("+00:00", "Z"),
                "bracket_end_utc": t1.isoformat().replace("+00:00", "Z"),
            }
        )

    return {
        "start_time_utc": start.isoformat().replace("+00:00", "Z"),
        "end_time_utc": end.isoformat().replace("+00:00", "Z"),
        "step_minutes": step,
        "reference": reference,
        "tol_seconds": tol,
        "elev_tol_deg": elev_tol,
        "max_iter": max_iter,
        "sample_count": len(sample_times),
        "transition_count": len(transitions),
        "transitions": transitions,
        "provenance": {
            "terrain": terrain_provenance(profile=profile),
            "ephemeris": ephemeris_provenance(),
            "temporal": temporal_provenance(
                start, end, step_minutes=step, tol_seconds=tol,
                elev_tol_deg=elev_tol, max_iter=max_iter, reference=reference,
            ),
            "software": software_provenance(),
        },
    }


def _safe_sun_az_el(
    lat: float, lon: float, elevation_m: float, when: datetime
) -> tuple[float, float]:
    """Sun azimuth/elevation, returning NaNs on failure instead of raising."""
    try:
        return _sun_az_el_at(lat, lon, elevation_m, when)
    except Exception:
        return float("nan"), float("nan")


def _time_range(start: str | datetime, end: str | datetime) -> tuple[datetime, datetime]:
    def as_utc(value: str | datetime) -> datetime:
        if isinstance(value, str):
            return parse_timestamp_utc(value)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    start_time = as_utc(start)
    end_time = as_utc(end)
    if end_time <= start_time:
        raise ValueError("end_time must be later than start_time")
    return start_time, end_time


def analyze_sunlight_period(
    profile: HorizonProfile,
    *,
    start_time: str | datetime,
    end_time: str | datetime,
    step_minutes: float = 60.0,
    ephemeris_provider: Callable[..., dict[str, Any]] = compute_site_ephemeris,
    max_samples: int = 200_000,
    include_samples: bool = True,
) -> dict[str, Any]:
    """Sample SPICE solar angles over a time interval and estimate illumination.

    The skyline is computed once and reused for all samples. Each sample is
    weighted by the following interval, so an incomplete final step is handled.
    """
    start, end = _time_range(start_time, end_time)
    step = float(step_minutes)
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("step_minutes must be positive and finite")
    interval_seconds = step * 60.0
    total_seconds = (end - start).total_seconds()
    estimated_samples = math.ceil(total_seconds / interval_seconds) + 1
    if estimated_samples > max_samples:
        raise ValueError(
            f"Time range needs about {estimated_samples} samples; limit is {max_samples}. "
            "Increase step_minutes or shorten the interval."
        )

    sample_rows: list[dict[str, Any]] = []
    sample_intervals: list[tuple[datetime, datetime]] = []
    current = start
    while current < end:
        next_time = min(current + timedelta(seconds=interval_seconds), end)
        sample_intervals.append((current, next_time))
        current = next_time

    if ephemeris_provider is compute_site_ephemeris:
        timestamps = [
            current.isoformat().replace("+00:00", "Z")
            for current, _ in sample_intervals
        ]
        sun_samples = compute_sun_ephemerides(
            profile.latitude_deg,
            profile.longitude_deg,
            profile.site_elevation_m,
            timestamps,
        )
    else:
        sun_samples = [
            ephemeris_provider(
                profile.latitude_deg,
                profile.longitude_deg,
                profile.site_elevation_m,
                current.isoformat().replace("+00:00", "Z"),
            )["sun"]
            for current, _ in sample_intervals
        ]

    sample_count = 0
    sunlit_seconds = 0.0
    known_seconds = 0.0
    for (current, next_time), sun in zip(sample_intervals, sun_samples):
        visibility = check_solar_visibility(
            profile, sun["azimuth_deg"], sun["elevation_deg"]
        )
        duration = (next_time - current).total_seconds()
        if visibility["is_sunlit"] is True:
            sunlit_seconds += duration
        if visibility["is_sunlit"] is not None:
            known_seconds += duration
        sample_count += 1
        if include_samples:
            sample_rows.append(
                {
                    "timestamp_utc": current.isoformat().replace("+00:00", "Z"),
                    **visibility,
                }
            )

    known_percentage = (
        100.0 * known_seconds / total_seconds if total_seconds > 0.0 else 0.0
    )
    return {
        "start_time_utc": start.isoformat().replace("+00:00", "Z"),
        "end_time_utc": end.isoformat().replace("+00:00", "Z"),
        "step_minutes": step,
        "sample_count": sample_count,
        "sunlit_duration_seconds": sunlit_seconds,
        "sunlit_duration_hours": sunlit_seconds / 3600.0,
        "sunlit_percentage": (
            100.0 * sunlit_seconds / total_seconds if known_seconds == total_seconds else None
        ),
        "sunlit_percentage_of_known_time": (
            100.0 * sunlit_seconds / known_seconds if known_seconds > 0.0 else None
        ),
        "known_illumination_coverage_percentage": known_percentage,
        "horizon": {
            "azimuth_step_deg": profile.azimuth_step_deg,
            "max_distance_m": profile.max_distance_m,
            "ray_step_m": profile.ray_step_m,
            "dem_resolution_m": profile.dem_resolution_m,
            "dem_source": profile.dem_source,
        },
        "samples": sample_rows,
        "provenance": {
            "terrain": terrain_provenance(profile=profile),
            "ephemeris": ephemeris_provenance(),
            "temporal": temporal_provenance(start, end, step_minutes=step),
            "software": software_provenance(),
        },
    }


class HorizonAnalysisService:
    """Lazy DEM loader with a small thread-safe cache of site horizon profiles."""

    def __init__(
        self,
        label_path: Path = DEFAULT_DEM_LABEL,
        fallback_html_path: Path = DEFAULT_PLOTLY_HTML,
        *,
        profile_cache_size: int = 64,
    ) -> None:
        self.label_path = Path(label_path).expanduser()
        self.fallback_html_path = Path(fallback_html_path).expanduser()
        self.profile_cache_size = max(1, int(profile_cache_size))
        self._dem: LunarDEM | None = None
        self._profiles: OrderedDict[tuple[Any, ...], HorizonProfile] = OrderedDict()
        self._lock = threading.RLock()

    @property
    def dem(self) -> LunarDEM:
        with self._lock:
            if self._dem is None:
                self._dem = LunarDEM.load(self.label_path, self.fallback_html_path)
            return self._dem

    def horizon_profile(
        self,
        latitude_deg: float,
        longitude_deg: float,
        **options: Any,
    ) -> HorizonProfile:
        requested_site_elevation = options.get("site_elevation_m")
        requested_ray_step = options.get("ray_step_m")
        key = (
            round(float(latitude_deg), 6),
            round(float(longitude_deg) % 360.0, 6),
            None
            if requested_site_elevation is None
            else round(float(requested_site_elevation), 2),
            round(float(options.get("azimuth_step_deg", 1.0)), 4),
            round(float(options.get("max_distance_m", 200_000.0)), 1),
            round(
                self.dem.pixel_size_x_m
                if requested_ray_step is None
                else float(requested_ray_step),
                1,
            ),
        )
        with self._lock:
            cached = self._profiles.get(key)
            if cached is not None:
                self._profiles.move_to_end(key)
                return cached
            profile = calculate_horizon_profile(
                self.dem, latitude_deg, longitude_deg, **options
            )
            self._profiles[key] = profile
            if len(self._profiles) > self.profile_cache_size:
                self._profiles.popitem(last=False)
            return profile


def profile_to_dict(profile: HorizonProfile) -> dict[str, Any]:
    """Convert a profile to JSON-friendly lists for API responses."""
    return {
        "latitude_deg": profile.latitude_deg,
        "longitude_deg": profile.longitude_deg,
        "site_elevation_m": profile.site_elevation_m,
        "azimuth_step_deg": profile.azimuth_step_deg,
        "max_distance_m": profile.max_distance_m,
        "ray_step_m": profile.ray_step_m,
        "dem_resolution_m": profile.dem_resolution_m,
        "dem_source": profile.dem_source,
        "azimuths_deg": list(profile.azimuths_deg),
        "horizon_elevation_deg": list(profile.horizon_elevation_deg),
        "horizon_distance_m": list(profile.horizon_distance_m),
        "coverage_fraction": list(profile.coverage_fraction),
    }

def neighborhood_coordinates(
    latitude_deg: float,
    longitude_deg: float,
    *,
    radius_m: float = 1000.0,
    step_m: float = 500.0,
) -> list[tuple[float, float]]:
    """Generate a square neighborhood grid around a site in lat/lon.

    Offsets are applied in the polar-stereographic projection plane and
    converted back to planetocentric coordinates. This is a spatial
    sensitivity scaffold: it samples points, it does not create a continuous
    regional map.
    """
    latitude = float(latitude_deg)
    longitude = float(longitude_deg)
    radius = float(radius_m)
    step = float(step_m)
    if not math.isfinite(latitude) or not -90.0 <= latitude <= 0.0:
        raise ValueError("latitude_deg must be within [-90, 0]")
    if not math.isfinite(longitude):
        raise ValueError("longitude_deg must be finite")
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("radius_m must be positive and finite")
    if not math.isfinite(step) or step <= 0.0:
        raise ValueError("step_m must be positive and finite")

    center_x, center_y = latlon_to_polar_stereographic(latitude, longitude)
    half = int(math.ceil(radius / step))
    coordinates: list[tuple[float, float]] = []
    for ix in range(-half, half + 1):
        for iy in range(-half, half + 1):
            lat, lon = polar_stereographic_to_latlon(
                center_x + ix * step, center_y + iy * step
            )
            coordinates.append((float(lat), float(lon)))
    return coordinates


def summarize_neighborhood_values(values: list[float | None]) -> dict[str, Any]:
    """Summary statistics for a list of neighborhood sample values.

    Non-finite or None entries are excluded from statistics but counted in
    sample_count. This supports spatial-sensitivity reporting without
    implying regional coverage.
    """
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if finite:
        mean = sum(finite) / len(finite)
        variance = sum((value - mean) ** 2 for value in finite) / len(finite)
        std = math.sqrt(variance)
        minimum = min(finite)
        maximum = max(finite)
    else:
        mean = std = minimum = maximum = None
    return {
        "sample_count": len(values),
        "valid_count": len(finite),
        "mean": mean,
        "std": std,
        "min": minimum,
        "max": maximum,
        "range": (maximum - minimum) if finite else None,
    }

def _provenance_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def terrain_provenance(profile: HorizonProfile | None = None, dem: LunarDEM | None = None) -> dict[str, Any]:
    source = None
    resolution = None
    if profile is not None:
        source = profile.dem_source
        resolution = profile.dem_resolution_m
    if dem is not None:
        source = dem.source
        resolution = max(dem.pixel_size_x_m, dem.pixel_size_y_m)
    source_name = None
    if source is not None:
        source_name = Path(str(source)).name
    return {
        "dem_identifier": "LDEM_80S_40M_FLOAT",
        "dem_source": source_name,
        "configured_resolution_m": resolution,
        "reference_radius_m": MOON_MEAN_RADIUS_M,
        "projection": "south polar stereographic (planetocentric latitude, east-positive longitude)",
        "documented_coverage": "80 deg S to 90 deg S south polar cap",
        "resolution_status": "configured DEM resolution; effective resolution is limited by pixel size and ray sampling",
    }


def ephemeris_provenance() -> dict[str, Any]:
    status = get_engine_status()
    coverage = get_kernel_coverage() if status.get("ready") else {"ready": False}
    kernels = list(status.get("kernels", []))
    return {
        "backend": "NASA SPICE + Skyfield",
        "ready": bool(status.get("ready", False)),
        "frame": status.get("frame"),
        "frame_source": status.get("frame_source"),
        "spk": status.get("spk"),
        "loaded_kernels": kernels,
        "loaded_kernel_count": len(kernels),
        "kernel_coverage": coverage,
        "coverage_status": coverage.get("spk_coverage_status", "unavailable"),
    }


def temporal_provenance(
    start_time: Any,
    end_time: Any,
    step_minutes: float | None = None,
    *,
    tol_seconds: float | None = None,
    elev_tol_deg: float | None = None,
    max_iter: int | None = None,
    reference: str | None = None,
) -> dict[str, Any]:
    return {
        "start_time_utc": _provenance_iso(start_time),
        "end_time_utc": _provenance_iso(end_time),
        "time_standard": "UTC",
        "sampling_interval_minutes": step_minutes,
        "transition_tol_seconds": tol_seconds,
        "transition_elev_tol_deg": elev_tol_deg,
        "transition_max_iter": max_iter,
        "reference_horizon": reference,
    }


def spatial_provenance(
    latitude_deg: float,
    longitude_deg: float,
    *,
    radius_m: float,
    step_m: float,
    sample_count: int,
    valid_count: int,
) -> dict[str, Any]:
    return {
        "center_latitude_deg": float(latitude_deg),
        "center_longitude_deg": float(longitude_deg) % 360.0,
        "radius_m": float(radius_m),
        "step_m": float(step_m),
        "distance_convention": (
            "polar stereographic projection-plane Euclidean distance; "
            "not a lunar surface geodesic distance"
        ),
        "sample_count": int(sample_count),
        "valid_sample_count": int(valid_count),
        "standard_deviation_convention": "population standard deviation (divide by n)",
        "coverage_claim": "point sampling only; not continuous regional mapping",
    }


def software_provenance() -> dict[str, Any]:
    return {
        "application": "LUNARIS",
        "metadata_schema_version": "1.0",
        "phase": "4",
        "algorithm_versions": {
            "transition_detection": "Phase 3 bracketed bisection",
            "neighborhood_sampling": "Phase 4.2 projection-plane grid",
        },
    }


def neighborhood_provenance(
    latitude_deg: float,
    longitude_deg: float,
    *,
    radius_m: float,
    step_m: float,
    sample_count: int,
    valid_count: int,
) -> dict[str, Any]:
    return {
        "terrain": terrain_provenance(),
        "ephemeris": ephemeris_provenance(),
        "spatial": spatial_provenance(
            latitude_deg,
            longitude_deg,
            radius_m=radius_m,
            step_m=step_m,
            sample_count=sample_count,
            valid_count=valid_count,
        ),
        "software": software_provenance(),
    }
