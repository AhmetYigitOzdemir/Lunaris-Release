"""Coordinate transformations for lunar polar stereographic (GDRDEM / LOLA) data.

This module converts planar Polar Stereographic (PS70S-style) projection
coordinates into lunar geographic coordinates and then into Moon-centred
selenocentric Cartesian coordinates.

Conventions
-----------
* ``X_proj``/``Y_proj`` are projection-plane coordinates in metres, measured
  from the pole (the origin of the polar stereographic grid).
* Longitude is east-positive in ``[0, 360)`` degrees.
* Latitude is planetocentric and negative in the southern hemisphere.
* ``elevation`` is the GDRDEM height above the 1737.4 km reference sphere, in
  metres. Negative values (below the reference sphere) are allowed.
* The Cartesian frame has its origin at the Moon's centre, ``+Z`` through the
  north pole, ``+X`` through the prime meridian and east-positive ``Y``.
"""

from __future__ import annotations

import math
from typing import Final

MOON_MEAN_RADIUS_M: Final[float] = 1_737_400.0
PS70S_TRUE_SCALE_LAT_DEG: Final[float] = -85.0
_EPSILON: Final[float] = 1e-12


def _normalize_longitude(longitude_deg: float) -> float:
    """Wrap a longitude into the ``[0, 360)`` interval."""
    return longitude_deg % 360.0


def polar_stereographic_to_latlon(
    X_proj: float,
    Y_proj: float,
    R: float = MOON_MEAN_RADIUS_M,
    k0: float | None = 1.0,
    lat_c: float = PS70S_TRUE_SCALE_LAT_DEG,
    lambda0: float = 0.0,
) -> tuple[float, float]:
    """Convert south-polar stereographic coordinates to latitude/longitude.

    Parameters
    ----------
    X_proj, Y_proj:
        Projection-plane coordinates in metres, measured from the pole.
    R:
        Reference sphere radius in metres.
    k0:
        Scale factor at the pole. Pass ``None`` to derive a scale factor that
        is true at ``lat_c`` (``k0 = (1 + sin|lat_c|) / 2``). The default
        ``1.0`` keeps unity scale at the pole.
    lat_c:
        True-scale latitude of the projection in degrees. It is used for
        validation and to derive ``k0`` when ``k0`` is ``None``.
    lambda0:
        Central meridian in degrees.

    Returns
    -------
    tuple[float, float]
        ``(latitude_deg, longitude_deg)`` with latitude negative in the
        southern hemisphere and longitude wrapped to ``[0, 360)``.
    """
    x = float(X_proj)
    y = float(Y_proj)
    radius = float(R)
    central_meridian = float(lambda0)
    true_scale_lat = float(lat_c)

    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("X_proj and Y_proj must be finite numbers")
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("R must be a positive finite radius")
    if not math.isfinite(central_meridian):
        raise ValueError("lambda0 must be finite")
    if not -90.0 <= true_scale_lat <= 90.0:
        raise ValueError("lat_c must be within [-90, 90] degrees")

    if k0 is None:
        scale = (1.0 + math.sin(math.radians(abs(true_scale_lat)))) / 2.0
    else:
        scale = float(k0)
        if not math.isfinite(scale) or scale <= 0.0:
            raise ValueError("k0 must be a positive finite scale factor")

    rho = math.hypot(x, y)
    if rho <= _EPSILON:
        return -90.0, _normalize_longitude(central_meridian)

    longitude = math.radians(central_meridian) + math.atan2(x, -y)
    latitude = -(math.pi / 2.0 - 2.0 * math.atan(rho / (2.0 * radius * scale)))

    return math.degrees(latitude), _normalize_longitude(math.degrees(longitude))


def latlon_to_polar_stereographic(
    latitude_deg: float,
    longitude_deg: float,
    R: float = MOON_MEAN_RADIUS_M,
    k0: float | None = 1.0,
    lat_c: float = PS70S_TRUE_SCALE_LAT_DEG,
    lambda0: float = 0.0,
) -> tuple[float, float]:
    """Project south-polar planetocentric latitude/longitude to X/Y metres.

    The convention matches :func:`polar_stereographic_to_latlon`: east-positive
    longitude, a south-pole origin, and ``+Y`` toward longitude 180 degrees.
    """
    latitude = float(latitude_deg)
    longitude = float(longitude_deg)
    radius = float(R)
    central_meridian = float(lambda0)
    true_scale_lat = float(lat_c)

    if not math.isfinite(latitude) or not -90.0 <= latitude <= 0.0:
        raise ValueError("latitude_deg must be finite and within [-90, 0] degrees")
    if not math.isfinite(longitude):
        raise ValueError("longitude_deg must be finite")
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("R must be a positive finite radius")
    if not math.isfinite(central_meridian):
        raise ValueError("lambda0 must be finite")
    if not -90.0 <= true_scale_lat <= 90.0:
        raise ValueError("lat_c must be within [-90, 90] degrees")

    if k0 is None:
        scale = (1.0 + math.sin(math.radians(abs(true_scale_lat)))) / 2.0
    else:
        scale = float(k0)
        if not math.isfinite(scale) or scale <= 0.0:
            raise ValueError("k0 must be a positive finite scale factor")

    phi = math.radians(latitude)
    lam = math.radians(longitude - central_meridian)
    rho = 2.0 * radius * scale * math.tan(math.pi / 4.0 + phi / 2.0)
    return rho * math.sin(lam), -rho * math.cos(lam)


def lunar_geodetic_to_cartesian(
    lat: float,
    lon: float,
    elevation: float,
    R_moon: float = MOON_MEAN_RADIUS_M,
) -> tuple[float, float, float]:
    """Convert lunar geodetic coordinates to selenocentric Cartesian metres.

    Parameters
    ----------
    lat:
        Planetocentric latitude in degrees, ``[-90, 90]``.
    lon:
        East-positive longitude in degrees. Any value is normalised to
        ``[0, 360)``.
    elevation:
        Height above the reference sphere in metres (GDRDEM value).
    R_moon:
        Reference sphere radius in metres.

    Returns
    -------
    tuple[float, float, float]
        ``(X, Y, Z)`` in metres relative to the Moon's centre.
    """
    latitude_deg = float(lat)
    longitude_deg = float(lon)
    height = float(elevation)
    radius = float(R_moon)

    if not math.isfinite(latitude_deg) or not -90.0 <= latitude_deg <= 90.0:
        raise ValueError("lat must be a finite value within [-90, 90] degrees")
    if not math.isfinite(longitude_deg):
        raise ValueError("lon must be a finite value")
    if not math.isfinite(height):
        raise ValueError("elevation must be a finite value")
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("R_moon must be a positive finite radius")
    if radius + height <= _EPSILON:
        raise ValueError("R_moon + elevation must be positive")

    phi = math.radians(latitude_deg)
    lam = math.radians(_normalize_longitude(longitude_deg))
    r = radius + height

    x = r * math.cos(phi) * math.cos(lam)
    y = r * math.cos(phi) * math.sin(lam)
    z = r * math.sin(phi)

    return x, y, z
