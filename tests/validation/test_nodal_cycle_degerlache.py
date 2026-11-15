import sys
sys.path.insert(0, '.')
from horizon_analysis import LunarDEM, DEFAULT_DEM_LABEL, calculate_horizon_profile, analyze_sunlight_period
from ephemeris_engine import init_ephemeris
from datetime import UTC, datetime, timedelta

init_ephemeris()
dem = LunarDEM.load(DEFAULT_DEM_LABEL)

lat, lon = -88.275, -90.629  # de Gerlache PSR
elev = dem.elevation_at(lat, lon)
print(f'de Gerlache: lat={lat}, lon={lon}, elev={elev:.1f} m')

profile = calculate_horizon_profile(dem, lat, lon, site_elevation_m=elev,
    azimuth_step_deg=1.0, max_distance_m=200000.0, ray_step_m=40.0)

start = datetime(2026, 11, 14, 0, 0, tzinfo=UTC)
end = start + timedelta(days=18.6 * 365.25)

print(f'Running 18.6-year nodal cycle screen...')
analysis = analyze_sunlight_period(
    profile, start_time=start, end_time=end,
    step_minutes=60.0, max_samples=200000, include_samples=False
)

print(f'Sunlit hours: {analysis["sunlit_duration_hours"]:.2f}')
print(f'Sunlit seconds: {analysis["sunlit_duration_seconds"]:.1f}')
print(f'Coverage %: {analysis["known_illumination_coverage_percentage"]:.2f}')
print(f'Sample count: {analysis["sample_count"]}')

if analysis["sunlit_duration_seconds"] > 0:
    classification = "not_candidate"
elif analysis["known_illumination_coverage_percentage"] >= 99.9:
    classification = "candidate"
else:
    classification = "unknown"
print(f'Classification: {classification}')
