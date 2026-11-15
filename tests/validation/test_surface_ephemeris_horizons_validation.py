"""
LUNARIS Phase 2.2 — Independent Surface-Site Ephemeris Validation
-----------------------------------------------------------------

Compares LUNARIS Sun/Earth apparent azimuth/elevation (computed from a lunar
surface observer) against JPL Horizons apparent azimuth/elevation computed for
the *same* surface observer.

Reference: JPL Horizons (https://ssd.jpl.nasa.gov/api/horizons.api)
  - COMMAND  = 10 (Sun) / 399 (Earth)
  - CENTER   = coord@301   (user-defined geodetic site on the Moon, body 301)
  - COORD_TYPE = GEODETIC
  - SITE_COORD = 'longitude,latitude,height'  (E-lon deg, lat deg, height km)
  - QUANTITIES = 4         (apparent azimuth & elevation, airless)
  - EPHEM_TYPE = OBSERVER
  - Times in UTC

Frame consistency (verified from Horizons header output):
  - Center pole/equ : MEAN_ME (high precision), East-longitude positive
    -> matches LUNARIS MOON_ME frame (ephemeris_engine.py:43)
  - Center radii    : 1737.4, 1737.4, 1737.4 km (spherical)
    -> matches LUNARIS MOON_MEAN_RADIUS_M = 1737400 m
  - Center geodetic : E-lon(deg), Lat(deg), Alt(km)
    -> LUNARIS uses planetocentric latitude, east-positive longitude,
       height above the 1737.4 km sphere (coordinate_transform.py)
  - Time scale      : UTC
  - Ephemeris source: DE441 (Horizons) vs DE440 (LUNARIS de440s.bsp)
  - Rel. light bend : Sun, EARTH  (relativistic deflection applied)
  - Atmos refraction: NO (AIRLESS)

LUNARIS pipeline under test (ephemeris_engine.py compute_site_ephemeris):
  1. apparent target position from Moon center (Skyfield .apparent())
  2. observer geometric position subtracted (no observer-dependent light-time)
  3. vector rotated J2000 -> body-fixed (MOON_ME) and projected to local ENU

This script makes NO changes to production code. It reads only.
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Allow running both as a script and via pytest from the repo root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ephemeris_engine import (  # noqa: E402
    EphemerisError,
    compute_site_ephemeris,
    init_ephemeris,
    parse_timestamp_utc,
)

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
RAW_DIR = Path(__file__).resolve().parent / "horizons_raw"
RESULTS_PATH = Path(__file__).resolve().parent / "surface_ephemeris_validation_results.json"

TARGETS = {
    "sun": ("10", "Sun"),
    "earth": ("399", "Earth"),
}

# Observer locations. Candidate sites use the exact published coordinates from
# candidate_sites.py (verified, within the 80S-90S DEM band). Shackleton is a
# representative near-pole site (coordinates approximate, flagged below).
OBSERVERS = [
    {"name": "Shackleton (representative, near-pole)", "lat": -89.9, "lon": 0.0,
     "height_m": 0.0, "source": "representative; Shackleton crater ~ lunar south pole"},
    {"name": "PCB01 (Peak near Cabeus B)", "lat": -83.7630, "lon": -69.9830,
     "height_m": 0.0, "source": "candidate_sites.py (Wueller et al. 2026, Table A1)"},
    {"name": "HW04 (Haworth)", "lat": -86.5680, "lon": -21.4730,
     "height_m": 0.0, "source": "candidate_sites.py (Wueller et al. 2026, Table A1)"},
    {"name": "MMA04 (Malapert Massif)", "lat": -86.3100, "lon": -0.4590,
     "height_m": 0.0, "source": "candidate_sites.py (Wueller et al. 2026, Table A1)"},
    {"name": "dGR2_K2023 (de Gerlache Rim 2)", "lat": -88.4500, "lon": -67.8590,
     "height_m": 0.0, "source": "candidate_sites.py (Wueller et al. 2026, Table A1)"},
]

# UTC epochs spanning different illumination / solar elevation conditions.
# Uniform 6-hour spacing so a single Horizons request (START/STOP/STEP_SIZE,
# the call pattern verified to work) covers every epoch exactly.
EPOCHS_UTC = [
    "2026-11-14T00:00:00Z",
    "2026-11-14T06:00:00Z",
    "2026-11-14T12:00:00Z",
    "2026-11-14T18:00:00Z",
    "2026-11-15T00:00:00Z",
    "2026-11-15T06:00:00Z",
    "2026-11-15T12:00:00Z",
    "2026-11-15T18:00:00Z",
]

REQUEST_DELAY_S = 0.6  # be polite to the Horizons service


def horizon_angle_distance_deg(a1: float, a2: float) -> float:
    """Circular angular distance between two azimuths in degrees [0, 180]."""
    d = abs((a1 - a2) % 360.0)
    return min(d, 360.0 - d)


def format_horizons_time(dt: datetime) -> str:
    """Format a UTC datetime for a Horizons TLIST calendar entry."""
    return dt.strftime("%Y-%b-%d %H:%M:%S")


def horizons_request(target_id: str, obs: dict, epochs: list[datetime]) -> str:
    """Build and submit one Horizons observer request for all epochs.

    Uses START_TIME/STOP_TIME/STEP_SIZE (verified to work) with a uniform
    6-hour step so every requested epoch is returned exactly.

    Returns the raw text response. Raises on HTTP/URL errors so the caller can
    record the failure rather than crashing the whole run.
    """
    site_coord = f"{obs['lon']},{obs['lat']},{obs['height_m'] / 1000.0}"
    params = {
        "format": "text",
        "COMMAND": target_id,
        "EPHEM_TYPE": "OBSERVER",
        "CENTER": "coord@301",
        "COORD_TYPE": "GEODETIC",
        "SITE_COORD": f"'{site_coord}'",
        "QUANTITIES": "'4'",  # apparent azimuth & elevation (airless)
        "START_TIME": epochs[0].strftime("%Y-%m-%dT%H:%M"),
        "STOP_TIME": epochs[-1].strftime("%Y-%m-%dT%H:%M"),
        "STEP_SIZE": "6h",
        "MAKE_EPHEM": "YES",
    }
    query = urllib.parse.urlencode(params)
    url = f"{HORIZONS_URL}?{query}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_horizons_az_el(raw: str) -> dict[str, tuple[float, float]]:
    """Parse the $$SOE..$$EOE block into {timestamp_key: (az_deg, el_deg)}.

    timestamp_key is the output "DD-Mon-YYYY HH:MM" string normalised for
    matching against the requested epochs.
    """
    out: dict[str, tuple[float, float]] = {}
    lines = raw.splitlines()
    in_block = False
    for line in lines:
        if "$$SOE" in line:
            in_block = True
            continue
        if "$$EOE" in line:
            in_block = False
            continue
        if not in_block or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        # First two tokens are the date, e.g. "2026-Nov-14 12:00", then zero or
        # more presence/marker tokens (e.g. '*', 'i', '*i'), then Az and Elev.
        date_str = f"{parts[0]} {parts[1]}"
        try:
            dt = datetime.strptime(date_str, "%Y-%b-%d %H:%M").replace(tzinfo=UTC)
        except ValueError:
            continue
        idx = 2
        # Skip any non-numeric marker tokens between the time and the angles.
        while idx < len(parts):
            try:
                float(parts[idx])
                break
            except ValueError:
                idx += 1
        if idx + 1 >= len(parts):
            continue
        try:
            az = float(parts[idx])
            el = float(parts[idx + 1])
        except ValueError:
            continue
        out[dt.isoformat().replace("+00:00", "Z")] = (az, el)
    return out


def lunaris_az_el(obs: dict, timestamp_utc: str, target: str) -> dict:
    """Call LUNARIS compute_site_ephemeris and extract az/el/distance."""
    result = compute_site_ephemeris(
        obs["lat"], obs["lon"], obs["height_m"], timestamp_utc
    )
    body = result[target]
    return {
        "azimuth_deg": body["azimuth_deg"],
        "elevation_deg": body["elevation_deg"],
        "distance_km": body["distance_km"],
        "above_horizon": body["above_horizon"],
        "frame": result["frame"],
    }


def stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    n = len(values)
    mean = sum(values) / n
    rms = math.sqrt(sum(v * v for v in values) / n)
    return {
        "count": n,
        "mean": mean,
        "rms": rms,
        "max": max(values),
        "min": min(values),
    }


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Initialise LUNARIS engine (fails clearly if kernels are missing).
    try:
        init_ephemeris(kernel_dir=str(ROOT / "data" / "Ephemeris"))
    except EphemerisError as exc:
        print(f"FATAL: LUNARIS ephemeris engine could not be initialised: {exc}")
        return 2

    epochs_dt = [parse_timestamp_utc(e) for e in EPOCHS_UTC]

    records: list[dict] = []
    failed: list[dict] = []

    for obs in OBSERVERS:
        for target_key, (target_id, target_name) in TARGETS.items():
            url = None
            raw = None
            try:
                raw = horizons_request(target_id, obs, epochs_dt)
                # Preserve raw reference response for reproducibility.
                safe_name = obs["name"].replace(" ", "_").replace("(", "").replace(")", "")
                (RAW_DIR / f"{safe_name}_{target_key}.txt").write_text(
                    raw, encoding="utf-8"
                )
                # Reconstruct the request URL for the report.
                site_coord = f"{obs['lon']},{obs['lat']},{obs['height_m'] / 1000.0}"
                params = {
                    "format": "text", "COMMAND": target_id,
                    "EPHEM_TYPE": "OBSERVER", "CENTER": "coord@301",
                    "COORD_TYPE": "GEODETIC", "SITE_COORD": f"'{site_coord}'",
                    "QUANTITIES": "'4'",
                    "START_TIME": epochs_dt[0].strftime("%Y-%m-%dT%H:%M"),
                    "STOP_TIME": epochs_dt[-1].strftime("%Y-%m-%dT%H:%M"),
                    "STEP_SIZE": "6h", "MAKE_EPHEM": "YES",
                }
                url = f"{HORIZONS_URL}?{urllib.parse.urlencode(params)}"
            except Exception as exc:  # network / HTTP error -> record, continue
                failed.append({
                    "observer": obs["name"],
                    "target": target_key,
                    "error": str(exc),
                })
                print(f"  [unavailable] {obs['name']} / {target_key}: {exc}")
                time.sleep(REQUEST_DELAY_S)
                continue

            ref = parse_horizons_az_el(raw or "")

            for ts in EPOCHS_UTC:
                dt = parse_timestamp_utc(ts)
                key = dt.isoformat().replace("+00:00", "Z")
                ref_az_el = ref.get(key)
                if ref_az_el is None:
                    failed.append({
                        "observer": obs["name"],
                        "target": target_key,
                        "timestamp_utc": ts,
                        "error": "no Horizons row for requested epoch",
                    })
                    continue

                try:
                    lun = lunaris_az_el(obs, ts, target_key)
                except Exception as exc:
                    failed.append({
                        "observer": obs["name"],
                        "target": target_key,
                        "timestamp_utc": ts,
                        "error": f"LUNARIS computation failed: {exc}",
                    })
                    continue

                ref_az, ref_el = ref_az_el
                az_err = horizon_angle_distance_deg(lun["azimuth_deg"], ref_az)
                el_err = abs(lun["elevation_deg"] - ref_el)

                records.append({
                    "observer": obs["name"],
                    "observer_lat": obs["lat"],
                    "observer_lon": obs["lon"],
                    "observer_height_m": obs["height_m"],
                    "observer_source": obs["source"],
                    "target": target_key,
                    "target_name": target_name,
                    "timestamp_utc": ts,
                    "lunaris_azimuth_deg": round(lun["azimuth_deg"], 6),
                    "lunaris_elevation_deg": round(lun["elevation_deg"], 6),
                    "lunaris_distance_km": lun["distance_km"],
                    "lunaris_above_horizon": lun["above_horizon"],
                    "lunaris_frame": lun["frame"],
                    "horizons_azimuth_deg": round(ref_az, 6),
                    "horizons_elevation_deg": round(ref_el, 6),
                    "azimuth_error_deg": round(az_err, 6),
                    "elevation_error_deg": round(el_err, 6),
                    "request_url": url,
                })
                print(
                    f"  {obs['name'][:28]:28} {target_key:5} {ts} "
                    f"az_err={az_err:7.4f} el_err={el_err:7.4f}"
                )
            time.sleep(REQUEST_DELAY_S)

    # ---- Statistics ----
    def group_stats(pred):
        vals = [r["azimuth_error_deg"] for r in records if pred(r)]
        elvals = [r["elevation_error_deg"] for r in records if pred(r)]
        return {"azimuth": stats(vals), "elevation": stats(elvals)}

    summary = {
        "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "horizons_url": HORIZONS_URL,
        "targets": TARGETS,
        "observers": OBSERVERS,
        "epochs_utc": EPOCHS_UTC,
        "quantity_code": "4 (apparent azimuth & elevation, airless)",
        "frame_assumptions": {
            "lunaris_frame": "MOON_ME (preferred) / 1737.4 km sphere / planetocentric lat / east-positive lon / UTC",
            "horizons_frame": "MEAN_ME (high precision) / 1737.4 km sphere / E-lon deg / lat deg / alt km / UTC",
            "ephemeris": "LUNARIS DE440 (de440s.bsp) vs Horizons DE441",
        },
        "sun": group_stats(lambda r: r["target"] == "sun"),
        "earth": group_stats(lambda r: r["target"] == "earth"),
        "by_observer": {},
    }
    for obs in OBSERVERS:
        oname = obs["name"]
        summary["by_observer"][oname] = {
            "sun": group_stats(
                lambda r, o=oname: r["target"] == "sun" and r["observer"] == o
            ),
            "earth": group_stats(
                lambda r, o=oname: r["target"] == "earth" and r["observer"] == o
            ),
        }

    summary["counts"] = {
        "successful_comparisons": len(records),
        "failed_or_unavailable": len(failed),
    }

    print("\n=== ERROR STATISTICS ===")
    for label, key in (("SUN", "sun"), ("EARTH", "earth")):
        s = summary[key]
        az = s["azimuth"]; el = s["elevation"]
        print(f"{label}: n={az['count']}  az mean={az.get('mean',0):.4f} "
              f"rms={az.get('rms',0):.4f} max={az.get('max',0):.4f} min={az.get('min',0):.4f} | "
              f"el mean={el.get('mean',0):.4f} rms={el.get('rms',0):.4f} "
              f"max={el.get('max',0):.4f} min={el.get('min',0):.4f}")
    print(f"\nSuccessful comparisons: {summary['counts']['successful_comparisons']}")
    print(f"Failed/unavailable: {summary['counts']['failed_or_unavailable']}")

    RESULTS_PATH.write_text(
        json.dumps({"summary": summary, "records": records, "failed": failed},
                   indent=2), encoding="utf-8")
    print(f"\nResults written to {RESULTS_PATH}")
    print(f"Raw Horizons responses in {RAW_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
