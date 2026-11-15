"""NASA SPICE + Skyfield ephemeris engine for lunar surface sites.

The engine loads the SPICE kernels from a kernel directory, establishes a
Moon body-fixed frame (``MOON_ME`` whenever possible) and computes the local
azimuth/elevation of the Sun and Earth for any selenographic site.

The module owns one process-wide SPICE kernel pool. Call
:func:`init_ephemeris` once at start-up; :func:`compute_site_ephemeris` also
initialises the engine lazily when required.
"""

from __future__ import annotations
import os

import logging
import math
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import spiceypy as spice
from skyfield.api import Loader, load_file
from skyfield.jpllib import SpiceKernel
from skyfield.timelib import Time, Timescale
from skyfield.vectorlib import VectorFunction
from spiceypy.utils.exceptions import SpiceyError

logger = logging.getLogger(__name__)

MOON_MEAN_RADIUS_M: Final[float] = 1_737_400.0
J2000_JD_TDB: Final[float] = 2_451_545.0
SECONDS_PER_DAY: Final[float] = 86_400.0
J2000_UNIX_TIMESTAMP: Final[float] = 946_728_000.0
_DATA_ROOT = os.environ.get("LUNARIS_DATA_DIR")
DEFAULT_KERNEL_DIR: Final[str] = str(Path(_DATA_ROOT).expanduser() / "data" / "Ephemeris") if _DATA_ROOT else "spice_data"
_FALLBACK_KERNEL_DIRS: Final[tuple[str, ...]] = (
    "spice_data",
    "data/Ephemeris",
    "data/ephemeris",
)
_PREFERRED_FRAMES: Final[tuple[str, ...]] = ("MOON_ME", "MOON_PA")
_FALLBACK_FRAMES: Final[tuple[str, ...]] = ("IAU_MOON",)

_DE418_NUMERIC_VARIABLES: Final[dict[str, tuple[float, ...]]] = {
    "FRAME_MOON_PA": (31000,),
    "FRAME_31000_CLASS": (4,),
    "FRAME_31000_CLASS_ID": (31000,),
    "FRAME_31000_CENTER": (301,),
    "TKFRAME_31000_MATRIX": (1, 0, 0, 0, 1, 0, 0, 0, 1),
    "FRAME_MOON_ME": (31001,),
    "FRAME_31001_CLASS": (4,),
    "FRAME_31001_CLASS_ID": (31001,),
    "FRAME_31001_CENTER": (301,),
    "TKFRAME_31001_MATRIX": (1, 0, 0, 0, 1, 0, 0, 0, 1),
    "FRAME_MOON_PA_DE418": (31004,),
    "FRAME_31004_CLASS": (2,),
    "FRAME_31004_CLASS_ID": (31004,),
    "FRAME_31004_CENTER": (301,),
    "FRAME_MOON_ME_DE418": (31005,),
    "FRAME_31005_CLASS": (4,),
    "FRAME_31005_CLASS_ID": (31005,),
    "FRAME_31005_CENTER": (301,),
    "TKFRAME_31005_ANGLES": (68.00, 78.62, 0.27),
    "TKFRAME_31005_AXES": (3, 2, 1),
}

_DE418_STRING_VARIABLES: Final[dict[str, str]] = {
    "FRAME_31000_NAME": "MOON_PA",
    "TKFRAME_31000_SPEC": "MATRIX",
    "TKFRAME_31000_RELATIVE": "MOON_PA_DE418",
    "FRAME_31001_NAME": "MOON_ME",
    "TKFRAME_31001_SPEC": "MATRIX",
    "TKFRAME_31001_RELATIVE": "MOON_ME_DE418",
    "FRAME_31004_NAME": "MOON_PA_DE418",
    "FRAME_31005_NAME": "MOON_ME_DE418",
    "TKFRAME_31005_SPEC": "ANGLES",
    "TKFRAME_31005_RELATIVE": "MOON_PA_DE418",
    "TKFRAME_31005_UNITS": "ARCSECONDS",
}


class EphemerisError(RuntimeError):
    """Raised when the ephemeris engine cannot be initialised or queried."""


@dataclass(frozen=True)
class EphemerisContext:
    kernel_dir: Path
    frame: str
    frame_source: str
    spk_path: Path
    kernels: tuple[Path, ...]
    timescale: Timescale
    ephemeris: SpiceKernel
    sun: VectorFunction
    earth: VectorFunction
    moon: VectorFunction


_STATE: EphemerisContext | None = None
_STATE_LOCK = threading.RLock()


def init_ephemeris(
    kernel_dir: str | Path = DEFAULT_KERNEL_DIR,
    *,
    frame: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Load SPICE kernels and prepare the Skyfield/SPICE environment.

    Parameters
    ----------
    kernel_dir:
        Directory containing the SPICE kernels. Relative paths are resolved
        against the current working directory, the project directory and the
        bundled ``data/Ephemeris`` directory, in that order.
    frame:
        Optional body-fixed frame name to force (for example ``"MOON_ME"``).
        When omitted the engine prefers ``MOON_ME`` and falls back to
        ``MOON_PA`` and ``IAU_MOON``.
    force:
        Rebuild the engine even if it is already initialised.

    Returns
    -------
    dict[str, Any]
        A JSON-serialisable summary of the loaded kernels and frame.
    """
    global _STATE

    with _STATE_LOCK:
        if _STATE is not None and not force:
            return _summary(_STATE)

        directory = _resolve_kernel_dir(kernel_dir)
        groups = _discover_kernels(directory)

        spk_files = groups.get(".bsp", [])
        if not spk_files:
            raise EphemerisError(f"No SPICE SPK (*.bsp) kernel found in {directory}")

        _STATE = None
        spice.kclear()

        loaded: list[Path] = []
        for path in groups.get(".tls", []):
            spice.furnsh(str(path))
            loaded.append(path)

        for path in spk_files:
            spice.furnsh(str(path))
            loaded.append(path)

        tpc_files = groups.get(".tpc", [])
        for path in tpc_files:
            spice.furnsh(str(path))
            loaded.append(path)

        bpc_files = groups.get(".bpc", [])
        pc_classes: set[int] = set()
        for path in bpc_files:
            spice.furnsh(str(path))
            loaded.append(path)
            pc_classes |= _pck_frame_class_ids(path)

        if not tpc_files:
            logger.warning("No text PCK (*.tpc) found; IAU_MOON will be unavailable")

        test_et = _approximate_et_now()

        if frame is not None:
            preferred_frames: tuple[str, ...] = (frame,)
            fallback_frames: tuple[str, ...] = ()
        else:
            preferred_frames = _PREFERRED_FRAMES
            fallback_frames = _FALLBACK_FRAMES

        chosen = _select_frame(preferred_frames, test_et)
        frame_source = "kernel pool"

        if chosen is None:
            for tf_path in groups.get(".tf", []):
                spice.furnsh(str(tf_path))
                chosen = _select_frame(preferred_frames, test_et)
                if chosen is not None:
                    loaded.append(tf_path)
                    frame_source = tf_path.name
                    break
                spice.unload(str(tf_path))

        if chosen is None and 31004 in pc_classes:
            logger.info(
                "Binary lunar PCK uses the DE418 frame class; registering "
                "DE418 MOON_PA/MOON_ME frames from the NAIF moon_071218.tf data"
            )
            _register_de418_lunar_frames()
            chosen = _select_frame(preferred_frames, test_et)
            frame_source = "embedded DE418 lunar frames"

        if chosen is None and fallback_frames:
            chosen = _select_frame(fallback_frames, test_et)
            frame_source = "IAU text PCK"

        if chosen is None:
            raise EphemerisError(
                "Could not establish a lunar body-fixed frame. Provide a frame "
                "kernel matching the binary lunar PCK, or add pck00011.tpc for "
                "the IAU_MOON fallback."
            )

        cache_dir = Path(tempfile.gettempdir()) / "lunaris_skyfield"
        cache_dir.mkdir(parents=True, exist_ok=True)
        timescale = Loader(str(cache_dir)).timescale(builtin=True)

        spk_path = _select_spk(spk_files)
        ephemeris = load_file(str(spk_path))

        try:
            sun = ephemeris["sun"]
            earth = ephemeris["earth"]
            moon = ephemeris["moon"]
        except KeyError as exc:
            raise EphemerisError(
                f"SPK kernel {spk_path.name} does not provide Sun/Earth/Moon"
            ) from exc

        _STATE = EphemerisContext(
            kernel_dir=directory,
            frame=chosen,
            frame_source=frame_source,
            spk_path=spk_path,
            kernels=tuple(loaded),
            timescale=timescale,
            ephemeris=ephemeris,
            sun=sun,
            earth=earth,
            moon=moon,
        )

        summary = _summary(_STATE)
        logger.info(
            "Ephemeris engine ready: frame=%s, kernels=%d, spk=%s",
            summary["frame"],
            len(summary["kernels"]),
            summary["spk"],
        )
        return summary


def compute_site_ephemeris(
    lat: float,
    lon: float,
    elevation: float,
    timestamp_utc: str,
) -> dict[str, Any]:
    """Compute Sun and Earth azimuth/elevation for a lunar surface site.

    Parameters
    ----------
    lat:
        Planetocentric latitude in degrees, ``[-90, 90]``.
    lon:
        East-positive longitude in degrees. Values outside ``[0, 360)`` are
        wrapped.
    elevation:
        Height above the 1737.4 km reference sphere in metres (GDRDEM value).
    timestamp_utc:
        ISO 8601 UTC timestamp, for example ``"2026-11-14T12:00:00Z"``.

    Returns
    -------
    dict[str, Any]
        Nested dictionary with observer metadata, the active body-fixed frame
        and ``sun``/``earth`` azimuth, elevation, distance and visibility.
        Azimuth is measured clockwise from local north (0 deg = north,
        90 deg = east) and elevation is measured above the local horizon.
    """
    latitude_deg = float(lat)
    longitude_deg = float(lon) % 360.0
    height_m = float(elevation)

    if not math.isfinite(latitude_deg) or not -90.0 <= latitude_deg <= 90.0:
        raise ValueError("lat must be a finite value within [-90, 90] degrees")
    if not math.isfinite(longitude_deg):
        raise ValueError("lon must be a finite value")
    if not math.isfinite(height_m):
        raise ValueError("elevation must be a finite value")

    radius_m = MOON_MEAN_RADIUS_M + height_m
    if radius_m <= 0.0:
        raise ValueError("R_moon + elevation must be positive")

    requested_time = parse_timestamp_utc(timestamp_utc)

    with _STATE_LOCK:
        context = _ensure_state()

        time = context.timescale.from_datetime(requested_time)
        et = (float(time.tdb) - J2000_JD_TDB) * SECONDS_PER_DAY

        try:
            icrf_to_body = np.asarray(
                spice.pxform("J2000", context.frame, et), dtype=np.float64
            )
        except SpiceyError as exc:
            raise EphemerisError(
                f"SPICE could not rotate to frame {context.frame!r}"
            ) from exc

        latitude = math.radians(latitude_deg)
        longitude = math.radians(longitude_deg)
        cos_lat = math.cos(latitude)
        sin_lat = math.sin(latitude)
        cos_lon = math.cos(longitude)
        sin_lon = math.sin(longitude)

        up = np.array([cos_lat * cos_lon, cos_lat * sin_lon, sin_lat])
        east = np.array([-sin_lon, cos_lon, 0.0])
        north = np.array([-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat])

        observer_body_km = (radius_m / 1000.0) * up
        observer_icrf_km = icrf_to_body.T @ observer_body_km

        sun = _body_angles(
            context,
            time,
            context.sun,
            observer_icrf_km,
            icrf_to_body,
            east,
            north,
            up,
        )
        earth = _body_angles(
            context,
            time,
            context.earth,
            observer_icrf_km,
            icrf_to_body,
            east,
            north,
            up,
        )

    return {
        "timestamp_utc": _format_timestamp(requested_time),
        "frame": context.frame,
        "observer": {
            "latitude_deg": latitude_deg,
            "longitude_deg": longitude_deg,
            "elevation_m": height_m,
            "radius_m": radius_m,
        },
        "sun": sun,
        "earth": earth,
    }


def compute_sun_ephemerides(
    lat: float,
    lon: float,
    elevation: float,
    timestamps_utc: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    """Compute topocentric Sun angles for many times with vectorized Skyfield.

    This is intended for illumination time series: lunar orientation matrices
    are still evaluated by SPICE per epoch, while the more expensive apparent
    Sun ephemeris is evaluated as one Skyfield time array.
    """
    latitude_deg = float(lat)
    longitude_deg = float(lon) % 360.0
    height_m = float(elevation)
    if not math.isfinite(latitude_deg) or not -90.0 <= latitude_deg <= 90.0:
        raise ValueError("lat must be a finite value within [-90, 90] degrees")
    if not math.isfinite(longitude_deg) or not math.isfinite(height_m):
        raise ValueError("lon and elevation must be finite values")
    radius_m = MOON_MEAN_RADIUS_M + height_m
    if radius_m <= 0.0:
        raise ValueError("R_moon + elevation must be positive")
    if not timestamps_utc:
        return []

    requested_times = [parse_timestamp_utc(value) for value in timestamps_utc]
    with _STATE_LOCK:
        context = _ensure_state()
        times = context.timescale.from_datetimes(requested_times)
        sun_icrf_km = np.asarray(
            context.moon.at(times).observe(context.sun).apparent().position.km,
            dtype=np.float64,
        )
        tdb_days = np.asarray(times.tdb, dtype=np.float64).reshape(-1)
        try:
            rotations = np.stack(
                [
                    np.asarray(
                        spice.pxform(
                            "J2000",
                            context.frame,
                            (float(jd_tdb) - J2000_JD_TDB) * SECONDS_PER_DAY,
                        ),
                        dtype=np.float64,
                    )
                    for jd_tdb in tdb_days
                ],
                axis=0,
            )
        except SpiceyError as exc:
            raise EphemerisError(
                f"SPICE could not rotate to frame {context.frame!r}"
            ) from exc

    latitude = math.radians(latitude_deg)
    longitude = math.radians(longitude_deg)
    sin_lat, cos_lat = math.sin(latitude), math.cos(latitude)
    sin_lon, cos_lon = math.sin(longitude), math.cos(longitude)
    up = np.array([cos_lat * cos_lon, cos_lat * sin_lon, sin_lat])
    east = np.array([-sin_lon, cos_lon, 0.0])
    north = np.array([-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat])
    observer_body_km = (radius_m / 1000.0) * up

    # R @ (Sun - R.T @ observer) == R @ Sun - observer, since R is orthogonal.
    sun_body_km = np.einsum("nij,jn->in", rotations, sun_icrf_km) - observer_body_km[:, None]
    east_component = east @ sun_body_km
    north_component = north @ sun_body_km
    up_component = up @ sun_body_km
    horizontal = np.hypot(east_component, north_component)
    azimuth = np.degrees(np.arctan2(east_component, north_component)) % 360.0
    elevation_deg = np.degrees(np.arctan2(up_component, horizontal))
    distance = np.linalg.norm(sun_body_km, axis=0)

    return [
        {
            "azimuth_deg": round(float(azimuth[index]), 6),
            "elevation_deg": round(float(elevation_deg[index]), 6),
            "distance_km": round(float(distance[index]), 6),
            "above_horizon": bool(elevation_deg[index] > 0.0),
        }
        for index in range(len(requested_times))
    ]


def get_engine_status() -> dict[str, Any]:
    """Return a small status dictionary without forcing initialisation."""
    with _STATE_LOCK:
        if _STATE is None:
            return {"ready": False}
        return _summary(_STATE)


def get_kernel_coverage() -> dict[str, Any]:
    """Return SPK and PCK coverage intervals for the loaded kernels.

    Coverage is queried from the loaded kernels at call time. Intervals are
    reported in UTC using the engine timescale. This does not by itself
    certify that every requested analysis time is supported; callers must
    compare their interval against these bounds.
    """
    with _STATE_LOCK:
        if _STATE is None:
            return {"ready": False, "loaded_kernels": [], "spk": None, "pck": None}
        context = _STATE

        def et_to_utc(et_value: float) -> str:
            return context.timescale.tdb(
                jd=J2000_JD_TDB + et_value / SECONDS_PER_DAY
            ).utc_strftime("%Y-%m-%dT%H:%M:%SZ")

        spk_intervals: list[dict[str, str]] = []
        spk_query_error: str | None = None
        try:
            cover = spice.cell_double(1000)
            spice.spkcov(str(context.spk_path), 10, cover)
            for index in range(0, cover.card, 2):
                spk_intervals.append(
                    {
                        "start_utc": et_to_utc(float(cover[index])),
                        "end_utc": et_to_utc(float(cover[index + 1])),
                    }
                )
        except SpiceyError as exc:
            spk_query_error = str(exc)

        pck_intervals: list[dict[str, str]] = []
        pck_query_errors: list[dict[str, str]] = []
        bpc_candidates = [
            path for path in context.kernels if path.suffix.lower() == ".bpc"
        ]
        for bpc_path in bpc_candidates:
            try:
                cover = spice.cell_double(1000)
                spice.pckcov(str(bpc_path), 31004, cover)
                for index in range(0, cover.card, 2):
                    pck_intervals.append(
                        {
                            "kernel": bpc_path.name,
                            "start_utc": et_to_utc(float(cover[index])),
                            "end_utc": et_to_utc(float(cover[index + 1])),
                        }
                    )
            except SpiceyError as exc:
                pck_query_errors.append({"kernel": bpc_path.name, "error": str(exc)})

        if spk_query_error is not None:
            spk_coverage_status = "query_failed"
        elif spk_intervals:
            spk_coverage_status = "verified"
        else:
            spk_coverage_status = "no_coverage_reported"
        if pck_query_errors:
            pck_coverage_status = "query_failed"
        elif pck_intervals:
            pck_coverage_status = "verified"
        else:
            pck_coverage_status = "no_coverage_reported"

        return {
            "ready": True,
            "spk": context.spk_path.name,
            "spk_object": 10,
            "spk_intervals": spk_intervals,
            "spk_query_error": spk_query_error,
            "spk_coverage_status": spk_coverage_status,
            "pck": [path.name for path in bpc_candidates],
            "pck_frame": 31004,
            "pck_intervals": pck_intervals,
            "pck_query_errors": pck_query_errors,
            "pck_coverage_status": pck_coverage_status,
            "loaded_kernels": [path.name for path in context.kernels],
            "frame": context.frame,
        }


def parse_timestamp_utc(timestamp_utc: str) -> datetime:
    """Parse an ISO 8601 timestamp and normalise it to UTC."""
    if not isinstance(timestamp_utc, str) or not timestamp_utc.strip():
        raise ValueError("timestamp must be a non-empty ISO 8601 string")

    text = timestamp_utc.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "timestamp must be ISO 8601, for example 2026-11-14T12:00:00Z"
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _body_angles(
    context: EphemerisContext,
    time: Time,
    target: VectorFunction,
    observer_icrf_km: np.ndarray,
    icrf_to_body: np.ndarray,
    east: np.ndarray,
    north: np.ndarray,
    up: np.ndarray,
) -> dict[str, Any]:
    apparent = context.moon.at(time).observe(target).apparent()
    target_icrf_km = np.asarray(apparent.position.km, dtype=np.float64)

    line_of_sight_icrf_km = target_icrf_km - observer_icrf_km
    line_of_sight_body_km = icrf_to_body @ line_of_sight_icrf_km

    east_component = float(line_of_sight_body_km @ east)
    north_component = float(line_of_sight_body_km @ north)
    up_component = float(line_of_sight_body_km @ up)
    horizontal = math.hypot(east_component, north_component)

    azimuth_deg = math.degrees(math.atan2(east_component, north_component)) % 360.0
    elevation_deg = math.degrees(math.atan2(up_component, horizontal))
    distance_km = float(np.linalg.norm(line_of_sight_icrf_km))

    return {
        "azimuth_deg": round(azimuth_deg, 6),
        "elevation_deg": round(elevation_deg, 6),
        "distance_km": round(distance_km, 6),
        "above_horizon": elevation_deg > 0.0,
    }


def _ensure_state() -> EphemerisContext:
    with _STATE_LOCK:
        if _STATE is None:
            init_ephemeris()
        assert _STATE is not None
        return _STATE


def _resolve_kernel_dir(kernel_dir: str | Path) -> Path:
    requested = Path(kernel_dir).expanduser()
    project_root = Path(__file__).resolve().parent

    if requested.is_absolute():
        if requested.is_dir():
            return requested.resolve()
        raise EphemerisError(f"Kernel directory not found: {requested}")

    candidates = [Path.cwd() / requested, project_root / requested]
    if requested.parts == (DEFAULT_KERNEL_DIR,):
        candidates.extend(project_root / item for item in _FALLBACK_KERNEL_DIRS[1:])

    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()

    searched = ", ".join(str(path) for path in candidates)
    raise EphemerisError(f"Kernel directory not found. Searched: {searched}")


def _discover_kernels(directory: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in sorted(directory.iterdir()):
        if path.is_file():
            groups.setdefault(path.suffix.lower(), []).append(path)
    return groups


def _select_spk(spk_files: list[Path]) -> Path:
    for candidate in spk_files:
        if candidate.name.lower().startswith("de440s"):
            return candidate
    for candidate in spk_files:
        if "de440" in candidate.name.lower():
            return candidate
    return max(spk_files, key=lambda path: path.stat().st_size)


def _pck_frame_class_ids(path: Path) -> set[int]:
    try:
        cell = spice.cell_int(256)
        spice.pckfrm(str(path), cell)
        return {int(cell[index]) for index in range(cell.card)}
    except (OSError, SpiceyError) as exc:
        logger.warning("Could not read frame classes from %s: %s", path.name, exc)
        return set()


def _select_frame(candidates: tuple[str, ...], et: float) -> str | None:
    for name in candidates:
        try:
            spice.pxform("J2000", name, et)
            return name
        except SpiceyError:
            logger.debug("Body-fixed frame %r is not available", name)
            continue
    return None


def _approximate_et_now() -> float:
    now = datetime.now(UTC).timestamp()
    return now - J2000_UNIX_TIMESTAMP


def _register_de418_lunar_frames() -> None:
    for name, values in _DE418_NUMERIC_VARIABLES.items():
        spice.pdpool(name, [float(value) for value in values])
    for name, value in _DE418_STRING_VARIABLES.items():
        spice.pcpool(name, [value])


def _summary(context: EphemerisContext) -> dict[str, Any]:
    return {
        "ready": True,
        "kernel_dir": str(context.kernel_dir),
        "frame": context.frame,
        "frame_source": context.frame_source,
        "spk": context.spk_path.name,
        "kernels": [path.name for path in context.kernels],
    }
