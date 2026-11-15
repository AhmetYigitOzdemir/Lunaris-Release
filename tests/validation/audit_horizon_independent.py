"""
Independent terrain horizon ray-tracing reference implementation.

This is a genuinely independent implementation that does NOT reuse any
LUNARIS horizon algorithm code. It:

1. Reads the LOLA DEM directly from the PDS3 img file using numpy
2. Implements the polar stereographic projection independently
3. Implements great-circle ray casting independently
4. Implements bilinear sampling independently
5. Computes horizon angles independently

Key differences from LUNARIS:
- Different ray step (20 m vs LUNARIS default 40 m)
- Independent coordinate transform (no import from coordinate_transform.py)
- Independent ray-sphere intersection math
- No dependency on LunarDEM class

This provides a cross-check on LUNARIS's horizon calculation.
"""

import math
import re
import struct
import sys
from pathlib import Path

import numpy as np

MOON_RADIUS_M = 1737400.0  # Same reference sphere as LUNARIS


def read_pds3_label(label_path):
    """Parse PDS3 label keywords independently."""
    text = Path(label_path).read_text(encoding="utf-8", errors="replace")
    params = {}
    for match in re.finditer(
        r"^\s*([^/\r\n=]+?)\s*=\s*(.*?)\s*$", text, re.MULTILINE
    ):
        key = match.group(1).strip()
        value = match.group(2).strip().strip('"').strip("'")
        params[key] = value
    return params


def read_dem_direct(img_path, label_path):
    """Read DEM image directly from PDS3 img file, independent of LunarDEM."""
    params = read_pds3_label(label_path)
    rows = int(params["LINES"])
    cols = int(params["LINE_SAMPLES"])
    pixel_size_m = float(re.search(r"([\d.]+)", params["MAP_SCALE"]).group(1))
    x_offset = float(re.search(r"([\d.]+)", params["SAMPLE_PROJECTION_OFFSET"]).group(1))
    y_offset = float(re.search(r"([\d.]+)", params["LINE_PROJECTION_OFFSET"]).group(1))

    # Memory-map the image directly
    raw = np.memmap(img_path, dtype="<f4", mode="r", shape=(rows, cols))

    # Build pixel axis independently
    x_axis = (np.arange(cols, dtype=np.float64) - x_offset) * pixel_size_m
    y_axis = -(np.arange(rows, dtype=np.float64) - y_offset) * pixel_size_m

    return raw, x_axis, y_axis, pixel_size_m


def latlon_to_polar_stereographic_independent(lat_deg, lon_deg, R=MOON_RADIUS_M, k0=1.0, lat_c=-85.0, lambda0=0.0):
    """
    Independent polar stereographic projection.
    Same convention as LUNARIS but implemented from scratch.
    """
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg - lambda0)
    rho = 2.0 * R * k0 * math.tan(math.pi / 4.0 + lat / 2.0)
    x = rho * math.sin(lon)
    y = -rho * math.cos(lon)
    return x, y


def polar_stereographic_to_latlon_independent(x, y, R=MOON_RADIUS_M, k0=1.0, lat_c=-85.0, lambda0=0.0):
    """Independent inverse polar stereographic projection."""
    rho = math.hypot(x, y)
    if rho <= 1e-12:
        return -90.0, lambda0
    lon = math.radians(lambda0) + math.atan2(x, -y)
    lat = -(math.pi / 2.0 - 2.0 * math.atan(rho / (2.0 * R * k0)))
    return math.degrees(lat), math.degrees(lon) % 360.0


def bilinear_sample_independent(dem, x_axis, y_axis, x_m, y_m):
    """
    Independent bilinear sampling.
    Returns (value, valid_mask).
    """
    col = (x_m - x_axis[0]) / (x_axis[1] - x_axis[0])
    row = (y_axis[0] - y_m) / (y_axis[0] - y_axis[1])

    height, width = dem.shape
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

    z00 = dem[row0, col0]
    z01 = dem[row0, col1]
    z10 = dem[row1, col0]
    z11 = dem[row1, col1]
    values = (
        z00 * (1.0 - dx) * (1.0 - dy)
        + z01 * dx * (1.0 - dy)
        + z10 * (1.0 - dx) * dy
        + z11 * dx * dy
    )
    valid &= np.isfinite(values)
    return np.where(valid, values, np.nan), valid


def great_circle_ray_independent(lat_rad, lon_rad, azimuth_rad, distance_m, R=MOON_RADIUS_M):
    """
    Independent spherical forward geodesic.
    Returns (x, y) in polar stereographic projection plane.
    """
    delta = distance_m / R
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_delta = math.sin(delta)
    cos_delta = math.cos(delta)
    sin_az = math.sin(azimuth_rad)
    cos_az = math.cos(azimuth_rad)

    if abs(cos_lat) < 1e-12:
        # Pole singularity
        lat2 = -math.pi / 2.0 + delta
        lon2 = lon_rad + azimuth_rad
    else:
        lat2 = math.asin(
            max(-1.0, min(1.0, sin_lat * cos_delta + cos_lat * sin_delta * cos_az))
        )
        lon2 = lon_rad + math.atan2(
            sin_az * sin_delta * cos_lat,
            cos_delta - sin_lat * math.sin(lat2),
        )

    rho = 2.0 * R * math.tan(math.pi / 4.0 + lat2 / 2.0)
    x = rho * math.sin(lon2)
    y = -rho * math.cos(lon2)
    return x, y


def calculate_horizon_independent(
    dem, x_axis, y_axis, latitude_deg, longitude_deg,
    observer_elevation_m=0.0, azimuth_step_deg=1.0,
    max_distance_m=200000.0, ray_step_m=20.0,
):
    """
    Independent horizon calculation.
    Does NOT import or call any LUNARIS horizon function.
    """
    lat_rad = math.radians(latitude_deg)
    lon_rad = math.radians(longitude_deg % 360.0)

    # Observer position in polar stereographic plane
    obs_x, obs_y = latlon_to_polar_stereographic_independent(latitude_deg, longitude_deg)
    target_radius = MOON_RADIUS_M + observer_elevation_m

    ray_count = int(round(360.0 / azimuth_step_deg))
    sample_count = int(math.floor(max_distance_m / ray_step_m))
    distance = np.arange(1, sample_count + 1, dtype=np.float64) * ray_step_m
    azimuths = np.arange(ray_count, dtype=np.float64) * azimuth_step_deg

    horizon = np.zeros(ray_count, dtype=np.float64)
    horizon_distance = np.zeros(ray_count, dtype=np.float64)
    coverage = np.zeros(ray_count, dtype=np.float64)

    for i in range(ray_count):
        az_rad = math.radians(azimuths[i])
        angles = []
        valid_count = 0

        for d in distance:
            # Ray point in lat/lon (great circle)
            delta = d / MOON_RADIUS_M
            sin_lat = math.sin(lat_rad)
            cos_lat = math.cos(lat_rad)
            sin_delta = math.sin(delta)
            cos_delta = math.cos(delta)
            sin_az = math.sin(az_rad)
            cos_az = math.cos(az_rad)

            if abs(cos_lat) < 1e-12:
                lat2 = -math.pi / 2.0 + delta
                lon2 = lon_rad + az_rad
            else:
                lat2 = math.asin(
                    max(-1.0, min(1.0, sin_lat * cos_delta + cos_lat * sin_delta * cos_az))
                )
                lon2 = lon_rad + math.atan2(
                    sin_az * sin_delta * cos_lat,
                    cos_delta - sin_lat * math.sin(lat2),
                )

            # Convert to polar stereographic x/y
            rho = 2.0 * MOON_RADIUS_M * math.tan(math.pi / 4.0 + lat2 / 2.0)
            px = rho * math.sin(lon2)
            py = -rho * math.cos(lon2)

            # Sample DEM
            val, valid = bilinear_sample_independent(
                dem, x_axis, y_axis, np.array([px]), np.array([py])
            )
            if valid[0] and np.isfinite(val[0]):
                terrain_z = val[0] * 1000.0  # km to m
                valid_count += 1

                # Horizon angle with curvature correction
                d2 = d / MOON_RADIUS_M
                terrain_radius = MOON_RADIUS_M + terrain_z
                vertical = terrain_radius * math.cos(d2) - target_radius
                horizontal = terrain_radius * math.sin(d2)
                angle = math.degrees(math.atan2(vertical, horizontal))
                angles.append(angle)

        coverage[i] = valid_count / sample_count if sample_count > 0 else 0.0

        if angles:
            best_angle = max(angles)
            horizon[i] = max(0.0, best_angle)
            # Find distance of best angle (simple: last angle that achieves max)
            horizon_distance[i] = 0.0  # Not tracked in this simple version
        else:
            horizon[i] = 0.0
            horizon_distance[i] = 0.0

    return {
        "azimuths": azimuths,
        "horizon_elevation": horizon,
        "horizon_distance": horizon_distance,
        "coverage": coverage,
    }


def main():
    """Compare independent horizon vs LUNARIS horizon at multiple sites."""

    # Load DEM directly (independent of LunarDEM)
    label_path = Path("data/ldem_80s_40m_float.lbl")
    img_path = Path("data/ldem_80s_40m_float.img")
    dem, x_axis, y_axis, pixel_size = read_dem_direct(img_path, label_path)
    print("DEM loaded: %d x %d pixels, %.1f m/pixel" % (dem.shape[1], dem.shape[0], pixel_size))
    print("X axis: [%.1f, %.1f] m" % (x_axis[0], x_axis[-1]))
    print("Y axis: [%.1f, %.1f] m" % (y_axis[-1], y_axis[0]))
    print()

    # Now import LUNARIS for comparison
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from horizon_analysis import LunarDEM, calculate_horizon_profile, DEFAULT_DEM_LABEL

    lun_dem = LunarDEM.load(DEFAULT_DEM_LABEL)

    # Test locations (candidate sites and additional terrain locations)
    test_sites = [
        # Artemis III candidate sites
        ("PCB01 (Cabeus B)", -83.7630, 290.017),
        ("HW04 (Haworth)", -86.5680, 338.527),
        ("MMA04 (Malapert Massif)", -86.3100, 359.541),
        # Additional terrain locations
        ("Shackleton area", -89.6950, 126.371),
        ("de Gerlache area", -88.2750, 269.371),  # -90.629 wrapped to 269.371
    ]

    print("=" * 90)
    print("INDEPENDENT HORIZON vs LUNARIS HORIZON COMPARISON")
    print("=" * 90)
    print()
    print("Independent: 20 m ray step, independent implementation")
    print("LUNARIS:     40 m ray step (default), existing implementation")
    print()
    print("Comparison at azimuths: 0, 45, 90, 135, 180, 225, 270, 315 deg")
    print()

    test_azimuths = [0, 45, 90, 135, 180, 225, 270, 315]

    all_diffs = []

    for site_name, lat, lon in test_sites:
        print("-" * 90)
        print("Site: %s (lat=%.3f, lon=%.3f)" % (site_name, lat, lon))
        print("-" * 90)

        # Get LUNARIS elevation
        try:
            lun_elev = lun_dem.elevation_at(lat, lon)
        except ValueError:
            print("  SKIP: Site outside LUNARIS DEM coverage")
            continue

        # Independent horizon
        ind_result = calculate_horizon_independent(
            dem, x_axis, y_axis, lat, lon,
            observer_elevation_m=lun_elev,
            azimuth_step_deg=1.0,
            max_distance_m=200000.0,
            ray_step_m=20.0,
        )

        # LUNARIS horizon
        lun_profile = calculate_horizon_profile(
            lun_dem, lat, lon,
            site_elevation_m=lun_elev,
            azimuth_step_deg=1.0,
            max_distance_m=200000.0,
            ray_step_m=40.0,
        )

        print(f"{'Az':>6} {'Indep(deg)':>12} {'Lunaris(deg)':>14} {'Diff(deg)':>12} {'Indep cov':>10} {'Lun cov':>10}")
        print("-" * 70)

        site_diffs = []
        for az in test_azimuths:
            # Independent: find closest azimuth index
            ind_az_idx = int(round(az / 1.0))
            ind_horizon = ind_result["horizon_elevation"][ind_az_idx]
            ind_cov = ind_result["coverage"][ind_az_idx]

            # LUNARIS: use horizon_at interpolation
            lun_horizon, lun_dist, lun_cov = lun_profile.horizon_at(az)

            diff = ind_horizon - lun_horizon
            site_diffs.append(abs(diff))
            all_diffs.append(abs(diff))

            print("%6.0f %12.3f %14.3f %12.3f %10.2f %10.2f" % (
                az, ind_horizon, lun_horizon, diff, ind_cov, lun_cov
            ))

        print()
        print("  Site max diff: %.3f deg, mean diff: %.3f deg" % (
            max(site_diffs), sum(site_diffs) / len(site_diffs)
        ))
        print()

    print("=" * 90)
    print("OVERALL STATISTICS")
    print("=" * 90)
    print("Total comparisons: %d" % len(all_diffs))
    print("Max absolute difference: %.3f deg" % max(all_diffs))
    print("Mean absolute difference: %.3f deg" % (sum(all_diffs) / len(all_diffs)))
    print("RMS difference: %.3f deg" % math.sqrt(sum(d * d for d in all_diffs) / len(all_diffs)))
    print()

    # Interpretation
    print("=== INTERPRETATION ===")
    print("Independent implementation uses 20 m ray step vs LUNARIS 40 m.")
    print("Differences are expected due to:")
    print("  - Different ray sampling (20 m vs 40 m)")
    print("  - Different interpolation implementations")
    print("  - Floating point accumulation differences")
    print()
    if max(all_diffs) < 0.5:
        print("CONCLUSION: Difference < 0.5 deg — implementations agree well.")
    elif max(all_diffs) < 2.0:
        print("CONCLUSION: Difference < 2.0 deg — implementations broadly agree.")
    else:
        print("CONCLUSION: Difference >= 2.0 deg — significant discrepancy needs investigation.")


if __name__ == "__main__":
    main()
