import sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ephemeris_engine import init_ephemeris
import spiceypy as spice
from skyfield.api import Loader

kernel_dir = ROOT / "data" / "Ephemeris"
summary = init_ephemeris(kernel_dir=str(kernel_dir))
print("Engine summary:", summary)

ts = Loader(str(Path.home() / "AppData" / "Local" / "Temp" / "opencode")).timescale(builtin=True)

# SPK coverage
spk = kernel_dir / "de440s.bsp"
for obj in [10, 301, 399]:
    cover = spice.cell_double(1000)
    spice.spkcov(str(spk), obj, cover)
    print(f"SPK {spk.name} object {obj}: {cover.card // 2} interval(s)")
    for i in range(0, cover.card, 2):
        print("  ", ts.tdb(jd=2451545.0 + cover[i] / 86400.0).utc_strftime("%Y-%m-%dT%H:%M:%SZ"),
              "to", ts.tdb(jd=2451545.0 + cover[i + 1] / 86400.0).utc_strftime("%Y-%m-%dT%H:%M:%SZ"))

# PCK coverage
bpc = kernel_dir / "moon_pa_de418_1950-2050.bpc"
for fid in [31004, 31005]:
    cover = spice.cell_double(1000)
    try:
        spice.pckcov(str(bpc), fid, cover)
        print(f"PCK {bpc.name} frame {fid}: {cover.card // 2} interval(s)")
        for i in range(0, cover.card, 2):
            print("  ", ts.tdb(jd=2451545.0 + cover[i] / 86400.0).utc_strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "to", ts.tdb(jd=2451545.0 + cover[i + 1] / 86400.0).utc_strftime("%Y-%m-%dT%H:%M:%SZ"))
    except Exception as exc:
        print(f"PCK frame {fid}: {exc}")

# Endpoint pxform check
for ts_str in ["2026-11-14T00:00:00Z", "2045-06-20T15:36:00Z"]:
    from ephemeris_engine import parse_timestamp_utc
    dt = parse_timestamp_utc(ts_str)
    et = dt.timestamp() - 946728000.0
    try:
        m = spice.pxform("J2000", "MOON_ME", et)
        print(f"MOON_ME pxform at {ts_str}: OK")
    except Exception as exc:
        print(f"MOON_ME pxform at {ts_str}: FAIL {exc}")

print("Kernel files:")
for f in sorted(kernel_dir.iterdir()):
    print(" ", f.name, f.stat().st_size, "bytes")
