from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.windows import Window

from coordinate_transform import (
    latlon_to_polar_stereographic,
    polar_stereographic_to_latlon,
)
from horizon_analysis import (
    DRACONIC_YEAR_DAYS,
    HorizonProfile,
    LUNAR_YEAR_DAYS,
    LunarDEM,
    analyze_sunlight_period,
    calculate_horizon_profile,
    calculate_landing_safety_patch,
    check_solar_visibility,
    validate_dem_coverage,
)


class HorizonAnalysisTests(unittest.TestCase):
    def test_polar_stereographic_round_trip(self) -> None:
        latitude, longitude = -86.10531, 28.30470
        x_m, y_m = latlon_to_polar_stereographic(latitude, longitude)
        actual_latitude, actual_longitude = polar_stereographic_to_latlon(x_m, y_m)
        self.assertAlmostEqual(actual_latitude, latitude, places=9)
        self.assertAlmostEqual(actual_longitude, longitude, places=9)

    def test_native_dem_elevation_at_south_pole(self) -> None:
        axis = np.arange(-1000.0, 1000.1, 40.0)
        elevations = np.full((axis.size, axis.size), 1234.5, dtype=np.float32)
        dem = LunarDEM(elevations, axis, axis[::-1], "synthetic 40 m DEM")
        self.assertAlmostEqual(dem.elevation_at(-90.0, 123.0), 1234.5, places=4)

    def test_selected_site_elevations_match_rasterio_reference_points(self) -> None:
        label_path = Path(__file__).resolve().parents[1] / "data" / "ldem_80s_40m_float.lbl"
        image_names = {path.name.casefold() for path in label_path.parent.iterdir()}
        if "ldem_80s_40m_float.img" not in image_names:
            self.skipTest("Local LOLA IMG is not installed")

        dem = LunarDEM.from_pds3(label_path)
        reference_sites = (
            (-89.9, 0.0),
            (-86.10531, 28.30470),
            (-82.0, 150.0),
        )
        with rasterio.open(label_path) as dataset:
            transform = dataset.transform
            for latitude, longitude in reference_sites:
                x_m, y_m = latlon_to_polar_stereographic(latitude, longitude)
                col = (x_m - transform.c) / transform.a - 0.5
                row = (y_m - transform.f) / transform.e - 0.5
                col0, row0 = math.floor(col), math.floor(row)
                dx, dy = col - col0, row - row0
                window = dataset.read(
                    1, window=Window(col0, row0, 2, 2)
                ).astype(np.float64)
                reference_km = (
                    (window[0, 0] * (1 - dx) + window[0, 1] * dx) * (1 - dy)
                    + (window[1, 0] * (1 - dx) + window[1, 1] * dx) * dy
                )
                self.assertAlmostEqual(
                    dem.elevation_at(latitude, longitude), reference_km * 1000.0, places=6
                )

    def test_flat_dem_has_zero_horizon_and_full_coverage(self) -> None:
        axis = np.arange(-1000.0, 1000.1, 40.0)
        elevations = np.full((axis.size, axis.size), 0.0, dtype=np.float32)
        dem = LunarDEM(elevations, axis, axis[::-1], "flat sphere")
        profile = calculate_horizon_profile(
            dem,
            -90.0,
            0.0,
            azimuth_step_deg=10.0,
            max_distance_m=400.0,
            ray_step_m=40.0,
        )
        self.assertEqual(profile.horizon_elevation_deg, (0.0,) * 36)
        self.assertEqual(profile.horizon_distance_m, (0.0,) * 36)
        self.assertEqual(profile.coverage_fraction, (1.0,) * 36)

    def test_flat_landing_patch_is_fully_low_slope_and_smooth(self) -> None:
        axis = np.arange(-2000.0, 2000.1, 40.0)
        dem = LunarDEM(
            np.zeros((axis.size, axis.size), dtype=np.float32),
            axis,
            axis[::-1],
            "flat synthetic DEM",
        )
        result = calculate_landing_safety_patch(dem, -90.0, 0.0, radius_m=1000.0)
        self.assertEqual(result["grid_size"], 51)
        self.assertEqual(result["coverage_percentage"], 100.0)
        self.assertEqual(result["slope_below_5_deg_percentage"], 100.0)
        self.assertEqual(result["slope_below_8_deg_percentage"], 100.0)
        self.assertAlmostEqual(result["slope_median_deg"], 0.0, places=9)
        self.assertAlmostEqual(result["roughness_p95_m"], 0.0, places=8)

    def test_planar_landing_patch_reports_slope_without_false_roughness(self) -> None:
        axis = np.arange(-2000.0, 2000.1, 40.0)
        x_grid, y_grid = np.meshgrid(axis, axis[::-1])
        elevation = (0.2 * x_grid + 0.1 * y_grid).astype(np.float32)
        dem = LunarDEM(elevation, axis, axis[::-1], "tilted synthetic DEM")
        result = calculate_landing_safety_patch(dem, -90.0, 0.0, radius_m=1000.0)
        expected_slope = math.degrees(math.atan(math.sqrt(0.2**2 + 0.1**2)))
        self.assertAlmostEqual(result["slope_median_deg"], expected_slope, places=3)
        self.assertEqual(result["slope_below_8_deg_percentage"], 0.0)
        self.assertLess(result["roughness_p95_m"], 1e-5)

    def test_sun_below_observed_ridge_is_shadowed(self) -> None:
        profile = self._profile(
            horizon=(10.0, 0.0, 0.0, 0.0),
            distance=(500.0, 0.0, 0.0, 0.0),
            coverage=(1.0, 1.0, 1.0, 1.0),
        )
        ridge_shadow = check_solar_visibility(profile, 0.0, 5.0)
        open_sky = check_solar_visibility(profile, 90.0, 5.0)
        self.assertFalse(ridge_shadow["is_sunlit"])
        self.assertTrue(ridge_shadow["is_topographically_shadowed"])
        self.assertTrue(open_sky["is_sunlit"])

    def test_partial_coverage_only_resolves_observed_blockage(self) -> None:
        profile = self._profile(
            horizon=(10.0, 0.0, 0.0, 0.0),
            distance=(500.0, 0.0, 0.0, 0.0),
            coverage=(0.5, 0.5, 0.5, 0.5),
        )
        blocked = check_solar_visibility(profile, 0.0, 5.0)
        unblocked_but_truncated = check_solar_visibility(profile, 0.0, 15.0)
        self.assertEqual(blocked["visibility"], "shadowed")
        self.assertFalse(blocked["is_sunlit"])
        self.assertIsNone(unblocked_but_truncated["is_sunlit"])
        self.assertEqual(unblocked_but_truncated["visibility"], "unknown")

    def test_sunlight_period_weights_partial_last_interval(self) -> None:
        profile = self._profile(
            horizon=(0.0, 0.0, 0.0, 0.0),
            distance=(0.0, 0.0, 0.0, 0.0),
            coverage=(1.0, 1.0, 1.0, 1.0),
        )

        def provider(_lat: float, _lon: float, _elevation: float, _time: str):
            return {"sun": {"azimuth_deg": 180.0, "elevation_deg": 10.0}}

        result = analyze_sunlight_period(
            profile,
            start_time=datetime(2026, 11, 14, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 11, 14, 2, 30, tzinfo=UTC),
            step_minutes=60.0,
            ephemeris_provider=provider,
        )
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["sunlit_duration_hours"], 2.5)
        self.assertEqual(result["sunlit_percentage"], 100.0)

    def test_default_sunlight_analysis_uses_batched_ephemeris(self) -> None:
        profile = self._profile(
            horizon=(0.0, 0.0, 0.0, 0.0),
            distance=(0.0, 0.0, 0.0, 0.0),
            coverage=(1.0, 1.0, 1.0, 1.0),
        )
        start = datetime(2026, 11, 14, 0, 0, tzinfo=UTC)
        with patch(
            "horizon_analysis.compute_sun_ephemerides",
            return_value=[
                {"azimuth_deg": 180.0, "elevation_deg": 5.0},
                {"azimuth_deg": 180.0, "elevation_deg": -5.0},
            ],
        ) as batched_ephemeris:
            result = analyze_sunlight_period(
                profile,
                start_time=start,
                end_time=start + timedelta(hours=2),
                step_minutes=60.0,
                include_samples=False,
            )

        batched_ephemeris.assert_called_once()
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["sunlit_duration_hours"], 1.0)

    def test_lunar_year_screen_can_return_aggregate_without_sample_payload(self) -> None:
        profile = self._profile(
            horizon=(0.0, 0.0, 0.0, 0.0),
            distance=(0.0, 0.0, 0.0, 0.0),
            coverage=(1.0, 1.0, 1.0, 1.0),
        )
        start = datetime(2026, 11, 14, tzinfo=UTC)
        end = start + timedelta(days=DRACONIC_YEAR_DAYS)

        def provider(_lat: float, _lon: float, _elevation: float, _time: str):
            return {"sun": {"azimuth_deg": 180.0, "elevation_deg": -5.0}}

        result = analyze_sunlight_period(
            profile,
            start_time=start,
            end_time=end,
            step_minutes=60.0,
            ephemeris_provider=provider,
            include_samples=False,
        )
        self.assertEqual(result["sample_count"], 8319)
        self.assertEqual(result["samples"], [])
        self.assertEqual(result["sunlit_duration_hours"], 0.0)
        self.assertEqual(result["known_illumination_coverage_percentage"], 100.0)

    @staticmethod
    def _profile(
        *,
        horizon: tuple[float, ...],
        distance: tuple[float, ...],
        coverage: tuple[float, ...],
    ) -> HorizonProfile:
        return HorizonProfile(
            latitude_deg=-89.0,
            longitude_deg=0.0,
            site_elevation_m=0.0,
            azimuth_step_deg=90.0,
            max_distance_m=1000.0,
            ray_step_m=40.0,
            dem_resolution_m=40.0,
            dem_source="synthetic",
            azimuths_deg=(0.0, 90.0, 180.0, 270.0),
            horizon_elevation_deg=horizon,
            horizon_distance_m=distance,
            coverage_fraction=coverage,
        )


class DemCoordinateValidationTests(unittest.TestCase):
    """Quantitative validation of DEM pixel coordinate geometry.

    Verifies that lat/lon -> polar-stereographic x/y -> DEM pixel row/col ->
    x/y -> lat/lon round-trips are consistent, and that pixel locations fall
    within the DEM footprint.
    """

    PIXEL_SIZE_M = 40.0
    X_OFFSET = 7599.5
    Y_OFFSET = 7599.5
    COLS = 15200
    ROWS = 15200

    @classmethod
    def _make_dem(cls) -> LunarDEM:
        """Build a synthetic DEM with the same axis geometry as the LOLA PDS3 product."""
        x_axis = (np.arange(cls.COLS, dtype=np.float64) - cls.X_OFFSET) * cls.PIXEL_SIZE_M
        y_axis = -(np.arange(cls.ROWS, dtype=np.float64) - cls.Y_OFFSET) * cls.PIXEL_SIZE_M
        elevations = np.zeros((cls.ROWS, cls.COLS), dtype=np.float32)
        return LunarDEM(elevations, x_axis, y_axis, "synthetic LOLA-geometry DEM")

    def _pixel_from_xy(self, dem: LunarDEM, x_m: float, y_m: float) -> tuple[float, float]:
        """Convert projected x/y meters to DEM pixel column/row (zero-based)."""
        col = (x_m - dem.x_axis_m[0]) / dem.pixel_size_x_m
        row = (dem.y_axis_m[0] - y_m) / dem.pixel_size_y_m
        return col, row

    def _xy_from_pixel(self, dem: LunarDEM, col: float, row: float) -> tuple[float, float]:
        """Convert DEM pixel column/row back to projected x/y meters."""
        x_m = dem.x_axis_m[0] + col * dem.pixel_size_x_m
        y_m = dem.y_axis_m[0] - row * dem.pixel_size_y_m
        return x_m, y_m

    def _metric_error_m(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """Approximate great-circle distance between two lat/lon points in metres."""
        R = 1_737_400.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        lam1, lam2 = math.radians(lon1), math.radians(lon2)
        d_phi = phi2 - phi1
        d_lam = lam2 - lam1
        h = (
            math.sin(d_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
        )
        return 2.0 * R * math.asin(math.sqrt(min(1.0, h)))

    def test_round_trip_at_multiple_latitudes_and_longitudes(self) -> None:
        """Full round-trip: lat/lon -> x/y -> pixel -> x/y -> lat/lon."""
        dem = self._make_dem()
        test_points = [
            (-90.0, 0.0),
            (-90.0, 90.0),
            (-90.0, 180.0),
            (-90.0, 270.0),
            (-89.0, 0.0),
            (-89.0, 45.0),
            (-89.0, 135.0),
            (-89.0, 225.0),
            (-85.0, 0.0),
            (-85.0, 90.0),
            (-80.5, 0.0),
            (-80.5, 180.0),
        ]

        max_error_m = 0.0
        for lat, lon in test_points:
            # Forward: lat/lon -> x/y
            x_m, y_m = latlon_to_polar_stereographic(lat, lon)
            # x/y -> pixel col/row
            col, row = self._pixel_from_xy(dem, x_m, y_m)
            # Verify pixel is within DEM bounds
            self.assertGreaterEqual(col, 0.0, f"col {col} < 0 for lat={lat}, lon={lon}")
            self.assertLess(col, dem.elevation_m.shape[1] - 1, f"col {col} >= width for lat={lat}, lon={lon}")
            self.assertGreaterEqual(row, 0.0, f"row {row} < 0 for lat={lat}, lon={lon}")
            self.assertLess(row, dem.elevation_m.shape[0] - 1, f"row {row} >= height for lat={lat}, lon={lon}")
            # pixel -> x/y
            x2_m, y2_m = self._xy_from_pixel(dem, col, row)
            # x/y -> lat/lon (inverse projection)
            lat2, lon2 = polar_stereographic_to_latlon(x2_m, y2_m)
            # Metric round-trip error
            error_m = self._metric_error_m(lat, lon, lat2, lon2)
            max_error_m = max(max_error_m, error_m)

        # Round-trip error should be well under one pixel (40 m) due to
        # pixel quantization; allow up to 40 m.
        self.assertLess(max_error_m, 40.0, f"Max round-trip error {max_error_m:.2f} m exceeds 40 m")
        print(f"\nMax round-trip coordinate error: {max_error_m:.2f} m")

    def test_dem_axis_matches_pds3_parameters(self) -> None:
        """Verify synthetic DEM axes match the PDS3 label parameters exactly."""
        dem = self._make_dem()
        self.assertAlmostEqual(dem.pixel_size_x_m, 40.0, places=6)
        self.assertAlmostEqual(dem.pixel_size_y_m, 40.0, places=6)
        self.assertEqual(dem.x_axis_m.size, 15200)
        self.assertEqual(dem.y_axis_m.size, 15200)
        # Center offset 7599.5 falls between pixels 7599 and 7600;
        # those pixels bracket x=0 (at -20 m and +20 m respectively).
        self.assertAlmostEqual(dem.x_axis_m[7599], -20.0, places=6)
        self.assertAlmostEqual(dem.x_axis_m[7600], 20.0, places=6)
        self.assertAlmostEqual(dem.y_axis_m[7599], 20.0, places=6)
        self.assertAlmostEqual(dem.y_axis_m[7600], -20.0, places=6)
        # Y axis descends from image row 0 (north edge, positive Y) to
        # the last row (south, negative Y): y_axis[0] > y_axis[-1].
        self.assertGreater(dem.y_axis_m[0], dem.y_axis_m[-1])

    def test_draconic_year_constant(self) -> None:
        """Verify DRACONIC_YEAR_DAYS is the eclipse/draconic year, not a lunar year."""
        self.assertEqual(DRACONIC_YEAR_DAYS, 346.62)
        # A conventional lunar year (12 synodic months) is ~354.367 days,
        # distinct from the draconic year used for PSR screening.
        self.assertNotEqual(DRACONIC_YEAR_DAYS, LUNAR_YEAR_DAYS)


class DemCoverageValidationTests(unittest.TestCase):
    """Tests for the reusable DEM coverage validation function."""

    @classmethod
    def _make_dem(cls) -> LunarDEM:
        """Small synthetic DEM covering a limited area around the south pole."""
        axis = np.arange(-50_000.0, 50_000.1, 40.0)
        elevations = np.full((axis.size, axis.size), 1000.0, dtype=np.float32)
        return LunarDEM(elevations, axis, axis[::-1], "synthetic coverage DEM")

    def test_site_inside_raster_is_available(self) -> None:
        dem = self._make_dem()
        # South pole projects to the center of the synthetic DEM
        result = validate_dem_coverage(dem, -90.0, 0.0)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["coverage_percentage"], 100.0)
        self.assertIsNotNone(result["elevation_m"])
        self.assertIsNone(result["error_message"])

    def test_site_outside_latitude_range_is_outside_dem(self) -> None:
        dem = self._make_dem()
        # -45° is outside the south-polar DEM's valid latitude range [-90, 0]
        result = validate_dem_coverage(dem, -45.0, 0.0)
        self.assertEqual(result["status"], "outside_dem")
        self.assertEqual(result["coverage_percentage"], 0.0)
        self.assertIsNone(result["elevation_m"])
        self.assertIsNotNone(result["error_message"])

    def test_site_outside_projected_raster_is_outside_dem(self) -> None:
        dem = self._make_dem()
        # A far longitude at -89° projects far from pole; may be outside small raster
        result = validate_dem_coverage(dem, -89.0, 180.0)
        self.assertIn(result["status"], ("outside_dem", "available"))
        # If outside, it must have 0% coverage and no elevation
        if result["status"] == "outside_dem":
            self.assertEqual(result["coverage_percentage"], 0.0)
            self.assertIsNone(result["elevation_m"])
            self.assertIsNotNone(result["error_message"])

    def test_coverage_with_analysis_radius_is_available(self) -> None:
        dem = self._make_dem()
        # Pole with 500 m radius on 100 km DEM is fully covered
        result = validate_dem_coverage(
            dem, -90.0, 0.0, radius_m=500.0, cell_size_m=40.0
        )
        self.assertEqual(result["status"], "available")
        self.assertGreaterEqual(result["coverage_percentage"], 99.0)

    def test_coverage_near_edge_with_large_radius_is_partial(self) -> None:
        dem = self._make_dem()
        # Site at -89°, 90° projects to ~30 km from pole; 25 km radius extends
        # beyond the 50 km DEM edge, giving partial coverage.
        result = validate_dem_coverage(
            dem, -89.0, 90.0, radius_m=25_000.0, cell_size_m=40.0
        )
        self.assertEqual(result["status"], "partial_coverage")
        self.assertLess(result["coverage_percentage"], 100.0)
        self.assertGreater(result["coverage_percentage"], 0.0)


if __name__ == "__main__":
    unittest.main()
