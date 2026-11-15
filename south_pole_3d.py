#!/usr/bin/env python3
"""
Interactive 3D visualization of the NASA LOLA South Pole DEM.

Required packages:
    pip install rasterio numpy plotly

Usage:
    python south_pole_3d.py
    python south_pole_3d.py --stride 15 --colorscale Viridis
    python south_pole_3d.py --stride 40 --output outputs/south_pole_3d.html

The PDS3 .lbl label is opened directly with rasterio. GDAL's PDS driver reads
the accompanying binary .IMG file referenced by the label.
"""

from __future__ import annotations
import os

import argparse
import json
import re
import sys
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import plotly.graph_objects as go

try:
    import rasterio
    from rasterio.enums import Resampling
except ImportError:
    rasterio = None
    Resampling = None

# Paths are resolved relative to this script so the program can be launched
# from any working directory.
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DEM = BASE_DIR / "data" / "ldem_80s_40m_float.lbl"
DEFAULT_OUTPUT = BASE_DIR / "outputs" / "south_pole_3d.html"

# Metadata taken from the PDS3 label for this specific product:
# MAP_SCALE = 40 m/pixel, projection offsets = 7599.5 pixels,
# CENTER_LATITUDE = -90 (South Pole), OFFSET = 1737.4 km.
PIXEL_SIZE_KM = 0.04
CENTER_PIXEL = 7599.5
REFERENCE_RADIUS_KM = 1737.4
DEFAULT_API_BASE = os.environ.get("LUNARIS_API_BASE", "").rstrip("/")


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Render the LOLA 80S-90S DEM as an interactive 3D surface."
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=40,
        help="Keep every Nth pixel in each direction (default: 40).",
    )
    parser.add_argument(
        "--colorscale",
        default="Plasma",
        help="Plotly colorscale name, e.g. Plasma, Turbo, or Inferno (default: Plasma).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output HTML path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help=(
            "Base URL of the Lunaris FastAPI service used by the interactive HUD "
            f"(default: {DEFAULT_API_BASE})."
        ),
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save the HTML file without opening it in a browser.",
    )
    return parser.parse_args()


def _pds3_value(label_text: str, key: str) -> str:
    """Return a single-line PDS3 keyword value."""
    match = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$",
        label_text,
        re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"PDS3 label is missing {key}")
    return match.group(1).strip().strip('"').strip("'")


def _raw_pds3_dtype(sample_type: str, bits: int) -> str:
    """Map a PDS3 sample type to a NumPy little-endian dtype."""
    if sample_type.upper() not in {"PC_REAL", "IEEE_REAL"}:
        raise ValueError(f"Unsupported PDS3 SAMPLE_TYPE: {sample_type}")
    if bits == 32:
        return "<f4"
    if bits == 64:
        return "<f8"
    raise ValueError(f"Unsupported PDS3 SAMPLE_BITS: {bits}")


def _read_raw_pds3(
    label_path: Path, stride: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read the DEM directly from a PDS3 label and raw image pair."""
    label_text = label_path.read_text(encoding="utf-8", errors="replace")
    lines = int(_pds3_value(label_text, "LINES"))
    samples = int(_pds3_value(label_text, "LINE_SAMPLES"))
    bits = int(_pds3_value(label_text, "SAMPLE_BITS"))
    sample_type = _pds3_value(label_text, "SAMPLE_TYPE")
    image_name = _pds3_value(label_text, "^IMAGE")

    image_path = label_path.parent / image_name
    if not image_path.exists():
        matches = [
            path
            for path in label_path.parent.iterdir()
            if path.name.lower() == image_name.lower()
        ]
        if not matches:
            raise FileNotFoundError(f"DEM image not found: {image_name}")
        image_path = matches[0]

    dtype = _raw_pds3_dtype(sample_type, bits)
    expected_bytes = lines * samples * np.dtype(dtype).itemsize
    if image_path.stat().st_size < expected_bytes:
        raise ValueError(
            f"DEM image is smaller than expected: {image_path} "
            f"({image_path.stat().st_size} < {expected_bytes} bytes)"
        )

    raw = np.memmap(image_path, dtype=dtype, mode="r", shape=(lines, samples))
    dem = np.asarray(raw[::stride, ::stride], dtype=np.float32)
    del raw

    out_h, out_w = dem.shape
    col_idx = np.arange(out_w) * stride
    row_idx = np.arange(out_h) * stride
    x_km = (col_idx - CENTER_PIXEL) * PIXEL_SIZE_KM
    y_km = -(row_idx - CENTER_PIXEL) * PIXEL_SIZE_KM

    print(f"Opened label : {label_path}")
    print(f"Full DEM     : {samples} x {lines} pixels")
    print(f"Driver/dtype : raw PDS3 / {dtype}")

    return dem, x_km, y_km


def read_downsampled_dem(
    label_path: Path, stride: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Read the DEM band with rasterio and return a downsampled elevation grid.

    The raster is decimated while reading (via GDAL's out_shape argument) so
    the full ~0.9 GB array never has to be held in RAM. This produces the same
    visual result as reading the full band and slicing dem[::stride, ::stride].
    """
    if stride < 1:
        raise ValueError("--stride must be a positive integer")

    if not label_path.exists():
        raise FileNotFoundError(f"DEM label not found: {label_path}")

    if rasterio is None:
        return _read_raw_pds3(label_path, stride)

    with rasterio.open(label_path) as src:
        print(f"Opened label : {label_path}")
        print(f"Full DEM     : {src.width} x {src.height} pixels")
        print(f"Driver/dtype : {src.driver} / {src.dtypes[0]}")

        # Number of samples in each direction after [::stride] slicing.
        out_h = (src.height + stride - 1) // stride
        out_w = (src.width + stride - 1) // stride

        # Memory-efficient decimation. GDAL reads only the pixels needed
        # instead of allocating the full 15200 x 15200 float32 array.
        dem = src.read(
            1,
            out_shape=(out_h, out_w),
            resampling=Resampling.nearest,
        ).astype(np.float32, copy=False)

        # Pixel-centre coordinates in kilometres relative to the South Pole.
        col_idx = np.arange(out_w) * stride
        row_idx = np.arange(out_h) * stride
        x_km = (col_idx - CENTER_PIXEL) * PIXEL_SIZE_KM
        # Image row 0 is the northern edge of this south-polar map, so invert Y.
        y_km = -(row_idx - CENTER_PIXEL) * PIXEL_SIZE_KM

    return dem, x_km, y_km


def build_figure(
    dem: np.ndarray,
    x_km: np.ndarray,
    y_km: np.ndarray,
    stride: int,
    colorscale: str,
) -> tuple[go.Figure, float, float, float]:
    """Build the Plotly 3D surface figure and return it with elevation stats."""
    # LOLA DN values are heights in kilometres relative to the 1737.4 km
    # reference sphere; convert to metres for a more intuitive elevation axis.
    elevation_m = dem.astype(np.float64) * 1000.0

    z_min = float(np.nanmin(elevation_m))
    z_max = float(np.nanmax(elevation_m))
    z_mean = float(np.nanmean(elevation_m))
    displayed_pixel_m = PIXEL_SIZE_KM * stride * 1000.0

    fig = go.Figure(
        data=go.Surface(
            x=x_km,
            y=y_km,
            z=elevation_m,
            surfacecolor=elevation_m,
            colorscale=colorscale,
            cmin=z_min,
            cmax=z_max,
            colorbar=dict(
                title="Elevation (m)",
                thickness=18,
                len=0.75,
            ),
            hovertemplate=(
                "X: %{x:,.1f} km<br>"
                "Y: %{y:,.1f} km<br>"
                "Elevation: %{z:,.0f} m<extra></extra>"
            ),
            lighting=dict(
                ambient=0.55,
                diffuse=1.0,
                specular=0.05,
                roughness=0.9,
            ),
            lightposition=dict(x=100000, y=100000, z=100000),
            name="LOLA DEM",
        )
    )

    # Create the selection marker once, hidden, so a click only restyles this
    # lightweight trace instead of injecting a new WebGL trace at runtime.
    fig.add_trace(
        go.Scatter3d(
            x=[0.0],
            y=[0.0],
            z=[z_mean],
            mode="markers",
            name="Selected Point",
            meta="lunaris-selection",
            visible=False,
            hoverinfo="skip",
            marker={
                "size": 7,
                "color": "#f8fafc",
                "symbol": "diamond",
                "line": {"color": "#7dd3fc", "width": 3},
            },
        )
    )

    fig.update_layout(
        template="plotly_dark",
        scene=dict(
            xaxis_title="X from South Pole (km)",
            yaxis_title="Y from South Pole (km)",
            zaxis_title="Elevation (m)",
            # Manual aspect ratio gives the very flat lunar surface enough
            # vertical relief to make craters such as Shackleton visible.
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=0.3),
            camera=dict(eye=dict(x=1.6, y=1.6, z=1.1)),
        ),
        margin=dict(l=0, r=0, t=30, b=0),
        autosize=True,
    )

    return fig, z_min, z_max, z_mean


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Lunaris | Lunar South Pole Mission Control</title>
    <style>
        :root {
            color-scheme: dark;
            --hud-bg: rgba(15, 23, 42, 0.85);
            --hud-border: rgba(255, 255, 255, 0.10);
            --hud-text: #f8fafc;
            --hud-muted: #94a3b8;
            --hud-faint: #64748b;
            --hud-accent: #7dd3fc;
            --hud-sun: #fbbf24;
            --hud-shadow: #a5b4fc;
            --hud-dte: #34d399;
            --hud-danger: #f87171;
            --hud-radius: 16px;
            --hud-mono: "Cascadia Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;
        }

        * {
            box-sizing: border-box;
        }

        html,
        body {
            width: 100%;
            height: 100%;
            margin: 0;
        }

        body {
            overflow: hidden;
            background: #020617;
            color: var(--hud-text);
            font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
        }

        .map-masthead {
            position: fixed;
            top: 12px;
            left: 50%;
            z-index: 800;
            min-width: 340px;
            padding: 8px 16px 9px;
            text-align: center;
            color: var(--hud-text);
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.88), rgba(8, 18, 32, 0.72));
            border: 1px solid rgba(125, 211, 252, 0.18);
            border-radius: 14px;
            box-shadow: 0 10px 28px rgba(0, 0, 0, 0.22), 0 0 24px rgba(56, 189, 248, 0.06) inset;
            transform: translateX(-50%);
            pointer-events: none;
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
        }

        .map-masthead__eyebrow {
            margin: 0 0 2px;
            color: var(--hud-accent);
            font: 600 9px/1.3 var(--hud-mono);
            letter-spacing: 0.2em;
            text-transform: uppercase;
        }

        .map-masthead__title {
            margin: 0;
            font-size: 17px;
            font-weight: 650;
            line-height: 1.2;
            letter-spacing: 0.015em;
        }

        .map-masthead__meta {
            margin: 3px 0 0;
            color: var(--hud-muted);
            font-size: 9px;
            letter-spacing: 0.04em;
        }

        #lunaris-map {
            width: 100% !important;
            height: 100vh !important;
        }

        #lunaris-map .modebar-container {
            top: 12px !important;
            right: auto !important;
            bottom: auto !important;
            left: 12px !important;
        }

        #lunaris-map .modebar {
            top: 0 !important;
            right: auto !important;
            left: 0 !important;
        }

        #lunaris-hud {
            position: fixed;
            top: auto;
            right: 20px;
            left: auto;
            bottom: 20px;
            z-index: 1000;
            width: clamp(320px, 24vw, 420px);
            max-height: calc(100vh - 2rem);
            overflow: visible;
            pointer-events: none;
            scrollbar-width: thin;
            scrollbar-color: rgba(148, 163, 184, 0.35) transparent;
        }

        #lunaris-hud::-webkit-scrollbar {
            width: 8px;
        }

        #lunaris-hud::-webkit-scrollbar-thumb {
            background: rgba(148, 163, 184, 0.35);
            border-radius: 999px;
        }

        .hud-panel {
            pointer-events: auto;
            display: flex;
            flex-direction: column;
            gap: 16px;
            max-height: calc(100vh - 2rem);
            overflow-y: auto;
            padding: 20px;
            color: var(--hud-text);
            background: var(--hud-bg);
            border: 1px solid var(--hud-border);
            border-radius: var(--hud-radius);
            box-shadow:
                0 20px 25px -5px rgba(0, 0, 0, 0.5),
                0 0 0 1px rgba(125, 211, 252, 0.04) inset;
            backdrop-filter: blur(18px) saturate(140%);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            scrollbar-width: thin;
            scrollbar-color: rgba(148, 163, 184, 0.35) transparent;
        }

        #lunaris-hud.dragging .hud-panel {
            user-select: none;
        }

        .hud-panel::-webkit-scrollbar {
            width: 8px;
        }

        .hud-panel::-webkit-scrollbar-thumb {
            background: rgba(148, 163, 184, 0.35);
            border-radius: 999px;
        }

        @supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
            .hud-panel {
                background: rgba(15, 23, 42, 0.97);
            }
        }

        .hud-header {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            padding-bottom: 14px;
            border-bottom: 1px solid rgba(148, 163, 184, 0.14);
            cursor: grab;
            touch-action: none;
        }

        #lunaris-hud.dragging .hud-header {
            cursor: grabbing;
        }

        .hud-heading {
            min-width: 0;
            flex: 1 1 160px;
        }

        .hud-header__actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .hud-toggle {
            flex: 0 0 30px;
            width: 30px;
            height: 30px;
            padding: 0;
            color: var(--hud-text);
            font-family: inherit;
            font-size: 18px;
            font-weight: 600;
            line-height: 1;
            background: rgba(15, 23, 42, 0.75);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 8px;
            cursor: pointer;
        }

        .hud-toggle:hover {
            background: rgba(125, 211, 252, 0.16);
            border-color: rgba(125, 211, 252, 0.4);
        }

        #lunaris-hud.hud-collapsed .hud-panel {
            gap: 0;
            padding: 10px 12px;
            overflow: hidden;
        }

        #lunaris-hud.hud-collapsed .hud-header {
            align-items: center;
            padding: 0;
            border: 0;
        }

        #lunaris-hud.hud-collapsed .hud-eyebrow,
        #lunaris-hud.hud-collapsed .hud-subtitle,
        #lunaris-hud.hud-collapsed .hud-section,
        #lunaris-hud.hud-collapsed .hud-footer,
        #lunaris-hud.hud-collapsed .hud-note,
        #lunaris-hud.hud-collapsed .hud-message {
            display: none;
        }

        .hud-eyebrow {
            margin: 0 0 4px;
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: var(--hud-muted);
        }

        .hud-title {
            margin: 0;
            font-size: 18px;
            font-weight: 600;
            line-height: 1.2;
            letter-spacing: -0.01em;
        }

        .hud-subtitle {
            margin: 4px 0 0;
            font-size: 11px;
            color: var(--hud-faint);
        }

        .hud-section {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .hud-section + .hud-section {
            padding-top: 14px;
            border-top: 1px solid rgba(148, 163, 184, 0.12);
        }

        .hud-section__head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }

        .hud-section__title {
            margin: 0;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: var(--hud-muted);
        }

        .hud-section__tag {
            padding: 2px 6px;
            font-size: 9px;
            letter-spacing: 0.12em;
            color: var(--hud-faint);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 6px;
        }

        .metric-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
            margin: 0;
        }

        .metric {
            min-width: 0;
            padding: 8px 10px;
            background: rgba(2, 6, 23, 0.35);
            border: 1px solid rgba(148, 163, 184, 0.10);
            border-radius: 10px;
        }

        .metric--wide {
            grid-column: 1 / -1;
        }

        .metric dt {
            margin-bottom: 3px;
            font-size: 10px;
            color: var(--hud-muted);
        }

        .metric dd {
            margin: 0;
            overflow-wrap: anywhere;
            font-family: var(--hud-mono);
            font-size: 13px;
            font-variant-numeric: tabular-nums;
            font-feature-settings: "tnum";
            color: var(--hud-text);
        }

        .metric .unit {
            margin-left: 2px;
            font-size: 10px;
            color: var(--hud-faint);
        }

        .hud-status-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 8px 10px;
            background: rgba(2, 6, 23, 0.25);
            border: 1px solid rgba(148, 163, 184, 0.08);
            border-radius: 10px;
        }

        .hud-status-row__label {
            font-size: 11px;
            color: var(--hud-muted);
        }

        .badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 8px;
            font-size: 10px;
            font-weight: 600;
            line-height: 1;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            white-space: nowrap;
            border: 1px solid transparent;
            border-radius: 999px;
        }

        .badge__dot {
            width: 6px;
            height: 6px;
            background: currentColor;
            border-radius: 50%;
            box-shadow: 0 0 8px currentColor;
        }

        .badge--waiting {
            color: #cbd5e1;
            background: rgba(148, 163, 184, 0.12);
            border-color: rgba(148, 163, 184, 0.25);
        }

        .badge--sunlit {
            color: var(--hud-sun);
            background: rgba(251, 191, 36, 0.12);
            border-color: rgba(251, 191, 36, 0.30);
        }

        .badge--shadow {
            color: var(--hud-shadow);
            background: rgba(99, 102, 241, 0.16);
            border-color: rgba(129, 140, 248, 0.32);
        }

        .badge--dte {
            color: var(--hud-dte);
            background: rgba(52, 211, 153, 0.12);
            border-color: rgba(52, 211, 153, 0.30);
        }

        .badge--dte-down,
        .badge--offline,
        .badge--error {
            color: var(--hud-danger);
            background: rgba(248, 113, 113, 0.12);
            border-color: rgba(248, 113, 113, 0.30);
        }

        .hud-time {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .hud-time__value {
            font-family: var(--hud-mono);
            font-size: 13px;
            font-variant-numeric: tabular-nums;
            color: var(--hud-text);
        }

        .hud-time__meta {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            font-size: 10px;
            color: var(--hud-muted);
        }

        .hud-time__controls {
            display: flex;
            gap: 8px;
            margin-top: 2px;
        }

        .hud-button {
            flex: 1 1 0;
            padding: 7px 10px;
            font-family: inherit;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.03em;
            color: var(--hud-text);
            background: rgba(15, 23, 42, 0.75);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 8px;
            cursor: pointer;
            transition:
                background 120ms ease,
                border-color 120ms ease,
                color 120ms ease;
        }

        .hud-button:hover {
            background: rgba(125, 211, 252, 0.12);
            border-color: rgba(125, 211, 252, 0.35);
        }

        .hud-button:disabled {
            opacity: 0.55;
            cursor: not-allowed;
        }

        .hud-button:focus-visible {
            outline: 2px solid var(--hud-accent);
            outline-offset: 2px;
        }

        .hud-button[aria-pressed="true"] {
            color: var(--hud-accent);
            background: rgba(125, 211, 252, 0.16);
            border-color: rgba(125, 211, 252, 0.45);
        }

        .hud-slider {
            width: 100%;
            height: 4px;
            margin: 6px 0 2px;
            accent-color: var(--hud-accent);
            background: linear-gradient(90deg, rgba(125, 211, 252, 0.85), rgba(99, 102, 241, 0.55));
            border-radius: 999px;
            outline: none;
            cursor: pointer;
            -webkit-appearance: none;
            appearance: none;
        }

        .hud-slider::-webkit-slider-thumb {
            width: 14px;
            height: 14px;
            background: #f8fafc;
            border: 2px solid var(--hud-accent);
            border-radius: 50%;
            box-shadow: 0 0 10px rgba(125, 211, 252, 0.5);
            cursor: pointer;
            -webkit-appearance: none;
            appearance: none;
        }

        .hud-slider::-moz-range-thumb {
            width: 14px;
            height: 14px;
            background: #f8fafc;
            border: 2px solid var(--hud-accent);
            border-radius: 50%;
            box-shadow: 0 0 10px rgba(125, 211, 252, 0.5);
            cursor: pointer;
        }

        .hud-footer {
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            gap: 8px;
            padding-top: 12px;
            font-size: 10px;
            color: var(--hud-faint);
            border-top: 1px solid rgba(148, 163, 184, 0.12);
        }

        .hud-footer strong {
            font-weight: 500;
            color: var(--hud-muted);
        }

        .hud-note {
            margin: 0;
            font-size: 10px;
            line-height: 1.5;
            color: var(--hud-faint);
        }

        .candidate-results {
            max-height: 260px;
            overflow: auto;
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 8px;
        }

        .candidate-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 10px;
            text-align: left;
        }

        .candidate-table th,
        .candidate-table td {
            padding: 6px 7px;
            border-bottom: 1px solid rgba(148, 163, 184, 0.12);
            white-space: nowrap;
        }

        .candidate-table th {
            position: sticky;
            top: 0;
            color: var(--hud-muted);
            background: #111827;
            font-weight: 600;
        }

        .candidate-table button {
            padding: 3px 6px;
            color: var(--hud-accent);
            background: transparent;
            border: 1px solid rgba(125, 211, 252, 0.24);
            border-radius: 5px;
            cursor: pointer;
        }

        .candidate-controls {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            align-items: end;
            gap: 8px;
        }

        .candidate-controls label {
            display: grid;
            gap: 4px;
            color: var(--hud-muted);
            font-size: 10px;
        }

        .candidate-controls input {
            width: 100%;
            box-sizing: border-box;
            padding: 7px 8px;
            color: var(--hud-text);
            background: rgba(15, 23, 42, 0.75);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 7px;
        }

        .slope-canvas {
            display: block;
            width: 100%;
            height: auto;
            max-height: 380px;
            background: #0b1220;
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 8px;
            image-rendering: auto;
        }

        .slope-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 6px 12px;
            margin: 7px 0 2px;
            color: var(--hud-muted);
            font-size: 10px;
        }

        .slope-legend__item {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            white-space: nowrap;
        }

        .slope-legend__swatch {
            width: 10px;
            height: 10px;
            border: 1px solid rgba(255, 255, 255, 0.3);
            border-radius: 3px;
        }

        .hud-message {
            margin: 0;
            padding: 8px 10px;
            font-size: 11px;
            line-height: 1.45;
            color: var(--hud-accent);
            background: rgba(125, 211, 252, 0.08);
            border: 1px solid rgba(125, 211, 252, 0.20);
            border-radius: 10px;
        }

        @media (max-width: 640px) {
            .map-masthead {
                top: 10px;
                min-width: 0;
                max-width: calc(100vw - 120px);
                padding: 7px 10px;
            }

            .map-masthead__title {
                font-size: 14px;
            }

            .map-masthead__meta {
                display: none;
            }

            #lunaris-hud {
                top: auto;
                right: 12px;
                left: auto;
                bottom: 12px;
                width: min(360px, calc(100vw - 24px));
                max-height: min(58vh, 480px);
            }

            .hud-panel {
                max-height: min(58vh, 480px);
                padding: 14px;
                gap: 12px;
            }
        }

        @media (max-width: 480px) {
            .metric-grid {
                grid-template-columns: minmax(0, 1fr);
            }

            .metric--wide {
                grid-column: auto;
            }
        }

        @media (prefers-reduced-motion: reduce) {
            * {
                transition-duration: 0.01ms !important;
                animation-duration: 0.01ms !important;
            }
        }
    </style>
</head>
<body>
    __PLOTLY_FRAGMENT__

    <header class="map-masthead" aria-label="NASA LOLA lunar south-pole elevation data">
        <p class="map-masthead__eyebrow">NASA · LOLA DATA</p>
        <h1 class="map-masthead__title">Lunar South Pole <span>·</span> Elevation Model</h1>
        <p class="map-masthead__meta">80°–90° South &nbsp;·&nbsp; Source resolution 40 m/pixel &nbsp;·&nbsp; Display sampling 1/__STRIDE__ &nbsp;·&nbsp; __DISPLAY_PIXEL_M__ m/pixel</p>
    </header>

    <aside id="lunaris-hud" class="hud-collapsed" aria-label="Lunaris Mission Control">
        <div class="hud-panel" role="region" aria-label="Mission control panel">
            <header class="hud-header">
                <div class="hud-heading">
                    <p class="hud-eyebrow">Lunar South Pole</p>
                    <h1 class="hud-title">Lunaris Mission Control</h1>
                    <p class="hud-subtitle">Terrain Intelligence · Flight Review</p>
                </div>
                <div class="hud-header__actions">
                    <span class="badge badge--waiting" id="hud-api-status">
                        <span class="badge__dot"></span>
                        API standby
                    </span>
                    <button class="hud-toggle" id="hud-toggle" type="button"
                        aria-label="Expand control panel" aria-expanded="false" title="Expand control panel">+</button>
                </div>
            </header>

            <section class="hud-section" aria-labelledby="hud-site-title">
                <div class="hud-section__head">
                    <h2 class="hud-section__title" id="hud-site-title">Site Geometry</h2>
                    <span class="hud-section__tag">SITE</span>
                </div>
                <dl class="metric-grid">
                    <div class="metric">
                        <dt>Latitude</dt>
                        <dd id="hud-lat">—</dd>
                    </div>
                    <div class="metric">
                        <dt>Longitude</dt>
                        <dd id="hud-lon">—</dd>
                    </div>
                    <div class="metric metric--wide">
                        <dt>Elevation</dt>
                        <dd id="hud-elevation">—</dd>
                    </div>
                </dl>
            </section>

            <section class="hud-section" aria-labelledby="hud-sun-title">
                <div class="hud-section__head">
                    <h2 class="hud-section__title" id="hud-sun-title">Solar Ephemeris</h2>
                    <span class="hud-section__tag">SUN</span>
                </div>
                <dl class="metric-grid">
                    <div class="metric">
                        <dt>Elevation</dt>
                        <dd id="hud-sun-elevation">—</dd>
                    </div>
                    <div class="metric">
                        <dt>Azimuth</dt>
                        <dd id="hud-sun-azimuth">—</dd>
                    </div>
                </dl>
                <div class="hud-status-row">
                    <span class="hud-status-row__label">Solar state</span>
                    <span class="badge badge--waiting" id="hud-sun-status">
                        <span class="badge__dot"></span>
                        Standby
                    </span>
                </div>
            </section>

            <section class="hud-section" aria-labelledby="hud-candidate-title">
                <div class="hud-section__head">
                    <h2 class="hud-section__title" id="hud-candidate-title">Candidate Region Comparison</h2>
                    <span class="hud-section__tag">ARTEMIS</span>
                </div>
                <div class="candidate-controls">
                    <label for="hud-mission-days">Surface mission duration (days)
                        <input id="hud-mission-days" type="number" min="1" max="30" step="0.25" value="6">
                    </label>
                    <button class="hud-button" id="hud-candidate-run" type="button">Compare 9 regions</button>
                </div>
                <p class="hud-note" id="hud-candidate-message">The selected UTC epoch initializes a representative site analysis for each candidate region.</p>
                <div class="candidate-results" id="hud-candidate-results" hidden>
                    <table class="candidate-table">
                        <thead><tr><th>Region</th><th>Sun</th><th>Continuous</th><th>≤8° slope</th><th>Earth now</th><th>Data</th><th></th></tr></thead>
                        <tbody id="hud-candidate-rows"></tbody>
                    </table>
                </div>
            </section>

            <section class="hud-section" aria-labelledby="hud-terrain-title">
                <div class="hud-section__head">
                    <h2 class="hud-section__title" id="hud-terrain-title">Terrain Assessment</h2>
                    <span class="hud-section__tag">TERRAIN</span>
                </div>
                <dl class="metric-grid">
                    <div class="metric">
                        <dt>Horizon angle · solar bearing</dt>
                        <dd id="hud-horizon-angle">—<span class="unit">°</span></dd>
                    </div>
                    <div class="metric">
                        <dt>Horizon range</dt>
                        <dd id="hud-horizon-distance">—<span class="unit">km</span></dd>
                    </div>
                    <div class="metric metric--wide">
                        <dt>24 h sunlight</dt>
                        <dd id="hud-sunlight-24h">—<span class="unit">h</span></dd>
                    </div>
                </dl>
                <button class="hud-button" id="hud-horizon-open" type="button" disabled>
                    Open 360° terrain horizon profile
                </button>
                <button class="hud-button" id="hud-safety-run" type="button" disabled>
                    Analyze local slope and roughness
                </button>
                <dl class="metric-grid">
                    <div class="metric"><dt>Slope ≤5° target area</dt><dd id="hud-slope-below5">—</dd></div>
                    <div class="metric"><dt>Slope ≤8° acceptable area</dt><dd id="hud-slope-below8">—</dd></div>
                    <div class="metric"><dt>Landing Suitability Index</dt><dd id="hud-lsi-score">—</dd></div>
                    <div class="metric metric--wide"><dt>Surface roughness · P95</dt><dd id="hud-roughness-p95">—<span class="unit">m</span></dd></div>
                    <div class="metric"><dt>Earth Communication Line (LOS)</dt><dd id="hud-earth-los">—</dd></div>
                </dl>
                <canvas class="slope-canvas" id="hud-slope-canvas" width="400" height="400" aria-label="Local slope map around the selected site"></canvas>
                <div class="slope-legend" role="list" aria-label="Slope map legend">
                    <span class="slope-legend__item" role="listitem"><i class="slope-legend__swatch" style="background:#34d399"></i>≤5° preferred</span>
                    <span class="slope-legend__item" role="listitem"><i class="slope-legend__swatch" style="background:#fbbf24"></i>5–8° marginal</span>
                    <span class="slope-legend__item" role="listitem"><i class="slope-legend__swatch" style="background:#fb7185"></i>&gt;8° steep</span>
                    <span class="slope-legend__item" role="listitem"><i class="slope-legend__swatch" style="background:#475569"></i>Unavailable</span>
                </div>
                <p class="hud-note" id="hud-safety-note">The center marker is the selected coordinate. The 40 m/pixel DEM does not resolve individual rocks or landing-gear hazards.</p>
                <div class="hud-status-row">
                    <span class="hud-status-row__label">Terrain shadow</span>
                    <span class="badge badge--waiting" id="hud-terrain-shadow">
                        <span class="badge__dot"></span>
                        Standby
                    </span>
                </div>
                <div class="hud-status-row">
                    <span class="hud-status-row__label">PSR Candidate</span>
                    <span class="badge badge--waiting" id="hud-psr-candidate">
                        <span class="badge__dot"></span>
                        Standby
                    </span>
                </div>
                <button class="hud-button" id="hud-psr-run" type="button" disabled>
                    Run 346.6-day draconic year PSR pre-screen
                </button>
                <button class="hud-button" id="hud-psr-cycle-run" type="button" disabled>
                    Run 18.6-year nodal-cycle pre-screen
                </button>
                <p class="hud-note" id="hud-psr-cycle-quality">Long-duration result quality is reported with the DEM, horizon-ray, and temporal sampling parameters.</p>
                <p class="hud-note">Annual and 18.6-year results are pre-screens; sampling and DEM resolution do not prove permanent shadow.</p>
            </section>

            <section class="hud-section" aria-labelledby="hud-earth-title">
                <div class="hud-section__head">
                    <h2 class="hud-section__title" id="hud-earth-title">Earth / Direct-to-Earth Geometry</h2>
                    <span class="hud-section__tag">EARTH</span>
                </div>
                <dl class="metric-grid">
                    <div class="metric">
                        <dt>Elevation</dt>
                        <dd id="hud-earth-elevation">—</dd>
                    </div>
                    <div class="metric">
                        <dt>Azimuth</dt>
                        <dd id="hud-earth-azimuth">—</dd>
                    </div>
                    <div class="metric metric--wide">
                        <dt>Range</dt>
                        <dd id="hud-earth-distance">—</dd>
                    </div>
                </dl>
                <div class="hud-status-row">
                    <span class="hud-status-row__label">Communication</span>
                    <span class="badge badge--waiting" id="hud-earth-status">
                        <span class="badge__dot"></span>
                        Standby
                    </span>
                </div>
            </section>

            <section class="hud-section" aria-labelledby="hud-cartesian-title">
                <div class="hud-section__head">
                    <h2 class="hud-section__title" id="hud-cartesian-title">Selenocentric XYZ</h2>
                    <span class="hud-section__tag">MOON-CENTERED</span>
                </div>
                <dl class="metric-grid">
                    <div class="metric">
                        <dt>X</dt>
                        <dd id="hud-x">—</dd>
                    </div>
                    <div class="metric">
                        <dt>Y</dt>
                        <dd id="hud-y">—</dd>
                    </div>
                    <div class="metric">
                        <dt>Z</dt>
                        <dd id="hud-z">—</dd>
                    </div>
                    <div class="metric">
                        <dt>Frame</dt>
                        <dd id="hud-frame">—</dd>
                    </div>
                </dl>
            </section>

            <section class="hud-section" aria-labelledby="hud-time-title">
                <div class="hud-section__head">
                    <h2 class="hud-section__title" id="hud-time-title">Time Control</h2>
                    <span class="hud-section__tag">UTC</span>
                </div>
                <div class="hud-time">
                    <span class="hud-time__value" id="hud-time-utc">—</span>
                    <div class="hud-time__meta">
                        <span>Lunar synodic cycle · ±14,765 days</span>
                        <span id="hud-time-label">T+000h</span>
                    </div>
                    <input
                        class="hud-slider"
                        id="hud-time-slider"
                        type="range"
                        min="-354"
                        max="354"
                        step="1"
                        value="0"
                        aria-label="Lunar synodic time slider"
                    />
                    <div class="hud-time__controls">
                        <button class="hud-button" id="hud-time-now" type="button">
                            Reset to current time
                        </button>
                        <button
                            class="hud-button"
                            id="hud-time-play"
                            type="button"
                            aria-pressed="false"
                        >
                            Play
                        </button>
                    </div>
                </div>
            </section>

            <p class="hud-message" id="hud-message" role="status" aria-live="polite">
                Select a surface site by clicking the DEM.
            </p>

            <footer class="hud-footer">
                <span>Generated: <strong>__GENERATED_AT__</strong></span>
                <span>Terrain Intelligence</span>
            </footer>
            <p class="hud-note">
                Elevation is relative to the 1,737.4 km reference sphere. Solar ephemerides
                use the geometric horizon; terrain shadow uses a separate DEM analysis.
            </p>
        </div>
    </aside>

    <script>
        (() => {
            "use strict";

            const MAP_ID = "lunaris-map";
            const API_BASE = __API_BASE__;
            const SELECTED_SITE_STORAGE_KEY = "lunaris-selected-site-v1";
            const MOON_RADIUS_M = 1737400.0;
            const K0 = 1.0;
            const DEFAULT_ELEVATION_M = 4200.0;
            const HOUR_MS = 3600000.0;
            const HALF_RANGE_HOURS = 354;
            const DEBOUNCE_MS = 200;
            const PLAYBACK_INTERVAL_MS = 500;
            const CLICK_DEBOUNCE_MS = 120;
            const SCENE_LOCK_MS = 300;
            const LIGHT_UPDATE_DELAY_MS = 500;
            const LIGHT_MIN_DELTA = 2500.0;
            const MARKER_META = "lunaris-selection";

            const state = {
                requestSeq: 0,
                activeController: null,
                markerTraceIndex: null,
                markerFrame: null,
                pendingMarker: null,
                lastMarker: null,
                clickTimer: null,
                pendingClick: null,
                sceneLockedUntil: 0,
                lightTimer: null,
                pendingLight: null,
                lastLightPosition: null,
                lastSite: null,
                centerUtc: Math.round(Date.now() / HOUR_MS) * HOUR_MS,
                timeTimer: null,
                playbackTimer: null,
                horizonProfile: null,
                horizonSiteKey: null,
                horizonController: null,
                horizonSeq: 0,
                forecastController: null,
                forecastSeq: 0,
                psrController: null,
                psrSeq: 0,
                psrTimestamp: null,
                psrCycleController: null,
                psrCycleSeq: 0,
                psrCycleTimestamp: null,
                safetyController: null,
                safetySeq: 0,
                candidateController: null,
                candidateSeq: 0,
                lastEphemeris: null
            };

            const utcFormatter = new Intl.DateTimeFormat("en-US", {
                dateStyle: "medium",
                timeStyle: "short",
                timeZone: "UTC"
            });

            const $ = (id) => document.getElementById(id);

            const findMarkerTraceIndex = () => {
                const mapDiv = $(MAP_ID);
                if (!mapDiv || !Array.isArray(mapDiv.data)) return -1;
                return mapDiv.data.findIndex(
                    (trace) => trace && trace.meta === MARKER_META
                );
            };

            // Plotly 3D can emit plotly_click again after restyle/relayout,
            // which previously caused an infinite click -> restyle loop.
            const lockSceneClicks = (duration) => {
                const until = performance.now() + duration;
                if (until > state.sceneLockedUntil) {
                    state.sceneLockedUntil = until;
                }
            };

            const sceneClicksLocked = () =>
                performance.now() < state.sceneLockedUntil;

            const requestFrame =
                typeof window.requestAnimationFrame === "function"
                    ? window.requestAnimationFrame.bind(window)
                    : (callback) => window.setTimeout(callback, 16);
            const cancelFrame =
                typeof window.cancelAnimationFrame === "function"
                    ? window.cancelAnimationFrame.bind(window)
                    : window.clearTimeout.bind(window);

            const metricCache = new Map();
            const badgeCache = new WeakMap();

            const numberFormat = (value, digits) => {
                const number = Number(value);
                if (!Number.isFinite(number)) return "—";
                return number.toLocaleString("en-US", {
                    minimumFractionDigits: digits,
                    maximumFractionDigits: digits
                });
            };

            const formatUtc = (iso) => {
                const date = new Date(iso);
                if (Number.isNaN(date.getTime())) return String(iso);
                return `${utcFormatter.format(date)} UTC`;
            };

            const getSliderDate = () => {
                const slider = $("hud-time-slider");
                const hours = slider ? Number(slider.value) : 0;
                return new Date(state.centerUtc + hours * HOUR_MS);
            };

            const getTimestamp = () =>
                getSliderDate().toISOString().replace(/\.\d{3}Z$/, "Z");

            const updateTimeDisplay = () => {
                const slider = $("hud-time-slider");
                if (!slider) return;
                const label = $("hud-time-label");
                const utc = $("hud-time-utc");
                const hours = Number(slider.value);
                const date = getSliderDate();
                const sign = hours < 0 ? "-" : "+";
                const labelText = `T${sign}${String(Math.abs(hours)).padStart(3, "0")}h`;
                const utcText = `${utcFormatter.format(date)} UTC`;
                const ariaText = `${utcText}, ${sign}${Math.abs(hours)} hours`;
                if (label && label.textContent !== labelText) {
                    label.textContent = labelText;
                }
                if (utc && utc.textContent !== utcText) {
                    utc.textContent = utcText;
                }
                if (slider.getAttribute("aria-valuetext") !== ariaText) {
                    slider.setAttribute("aria-valuetext", ariaText);
                }
            };

            const refreshSelectedSite = (refreshForecast = false) => {
                if (!state.lastSite) return;
                const timestamp = getTimestamp();
                if (
                    timestamp !== state.lastSite.timestamp &&
                    (state.psrTimestamp || state.psrCycleTimestamp)
                ) {
                    state.psrTimestamp = null;
                    state.psrCycleTimestamp = null;
                    state.psrSeq += 1;
                    state.psrCycleSeq += 1;
                    if (state.psrController) state.psrController.abort();
                    if (state.psrCycleController) state.psrCycleController.abort();
                    state.psrController = null;
                    state.psrCycleController = null;
                    setBadge($("hud-psr-candidate"), "Time changed \u00b7 rescan required", "waiting");
                    const psrButton = $("hud-psr-run");
                    if (psrButton) psrButton.disabled = !state.horizonProfile;
                    const cycleButton = $("hud-psr-cycle-run");
                    if (cycleButton) cycleButton.disabled = !state.horizonProfile;
                }
                if (
                    timestamp === state.lastSite.timestamp &&
                    state.activeController
                ) {
                    if (refreshForecast) requestSunlightForecast(state.lastSite);
                    return;
                }
                const site = { ...state.lastSite, timestamp };
                state.lastSite = site;
                requestEphemeris(site);
                if (refreshForecast) requestSunlightForecast(site);
            };

            const scheduleSiteRefresh = () => {
                if (!state.lastSite) return;
                clearTimeout(state.timeTimer);
                state.timeTimer = setTimeout(() => {
                    state.timeTimer = null;
                    refreshSelectedSite(false);
                }, DEBOUNCE_MS);
            };

            const flushSiteRefresh = () => {
                clearTimeout(state.timeTimer);
                state.timeTimer = null;
                refreshSelectedSite(true);
            };

            const setPlaybackState = (playing) => {
                const button = $("hud-time-play");
                if (!button) return;
                button.setAttribute("aria-pressed", playing ? "true" : "false");
                button.textContent = playing ? "Pause" : "Play";
            };

            const stopPlayback = () => {
                if (state.playbackTimer !== null) {
                    clearInterval(state.playbackTimer);
                    state.playbackTimer = null;
                }
                setPlaybackState(false);
            };

            const startPlayback = () => {
                const slider = $("hud-time-slider");
                if (!slider || state.playbackTimer !== null) return;
                setPlaybackState(true);
                state.playbackTimer = setInterval(() => {
                    const next = Number(slider.value) + 1;
                    if (next > Number(slider.max)) {
                        stopPlayback();
                        flushSiteRefresh();
                        return;
                    }
                    slider.value = String(next);
                    updateTimeDisplay();
                    scheduleSiteRefresh();
                }, PLAYBACK_INTERVAL_MS);
            };

            const togglePlayback = () => {
                if (state.playbackTimer !== null) {
                    stopPlayback();
                    flushSiteRefresh();
                } else {
                    startPlayback();
                }
            };

            const resetToNow = () => {
                stopPlayback();
                state.centerUtc = Math.round(Date.now() / HOUR_MS) * HOUR_MS;
                const slider = $("hud-time-slider");
                if (slider) slider.value = "0";
                updateTimeDisplay();
                flushSiteRefresh();
            };

            const setMetric = (id, value, unit) => {
                let cached = metricCache.get(id);
                if (!cached) {
                    const element = $(id);
                    if (!element) return;
                    element.textContent = "";
                    const valueNode = document.createElement("span");
                    const unitNode = document.createElement("span");
                    unitNode.className = "unit";
                    element.append(valueNode, unitNode);
                    cached = { valueNode, unitNode };
                    metricCache.set(id, cached);
                }

                const text =
                    value === null || value === undefined || value === ""
                        ? "—"
                        : String(value);
                if (cached.valueNode.textContent !== text) {
                    cached.valueNode.textContent = text;
                }

                const unitText = unit ? String(unit) : "";
                if (cached.unitNode.textContent !== unitText) {
                    cached.unitNode.textContent = unitText;
                }
            };

            const setBadge = (element, text, variant) => {
                if (!element) return;

                const nextClass = `badge badge--${variant}`;
                if (element.className !== nextClass) {
                    element.className = nextClass;
                }

                let cached = badgeCache.get(element);
                if (!cached) {
                    element.textContent = "";
                    const dot = document.createElement("span");
                    dot.className = "badge__dot";
                    const label = document.createElement("span");
                    element.append(dot, label);
                    cached = { dot, label };
                    badgeCache.set(element, cached);
                }

                const value = text === null || text === undefined ? "" : String(text);
                if (cached.label.textContent !== value) {
                    cached.label.textContent = value;
                }
            };

            const setMessage = (text) => {
                const message = $("hud-message");
                if (!message) return;
                const value = text === null || text === undefined ? "" : String(text);
                if (message.textContent !== value) {
                    message.textContent = value;
                }
            };

            const setApiStatus = (text, variant) => {
                setBadge($("hud-api-status"), text, variant);
            };

            const siteCacheKey = (site) =>
                `${Number(site.lat).toFixed(5)}:${Number(site.lon).toFixed(5)}:${Number(site.elevation).toFixed(1)}`;

            const updateTerrainShadow = (sun) => {
                const profile = state.horizonProfile;
                if (!profile || !sun) return;

                const azimuth = ((Number(sun.azimuth_deg) % 360) + 360) % 360;
                const elevation = Number(sun.elevation_deg);
                const step = Number(profile.azimuth_step_deg);
                const count = profile.azimuths_deg.length;
                if (!Number.isFinite(azimuth) || !Number.isFinite(elevation) || !step || !count) return;

                const position = azimuth / step;
                const lower = Math.floor(position) % count;
                const upper = (lower + 1) % count;
                const fraction = position - Math.floor(position);
                const interpolate = (values) =>
                    Number(values[lower]) * (1 - fraction) + Number(values[upper]) * fraction;
                const horizon = interpolate(profile.horizon_elevation_deg);
                const distance = interpolate(profile.horizon_distance_m);
                const coverage = interpolate(profile.coverage_fraction);

                setMetric("hud-horizon-angle", numberFormat(horizon, 2), "°");
                setMetric(
                    "hud-horizon-distance",
                    horizon > 0 && distance > 0 ? numberFormat(distance / 1000, 2) : "—",
                    horizon > 0 && distance > 0 ? "km" : ""
                );

                const shadowBadge = $("hud-terrain-shadow");
                if (elevation <= 0) {
                    setBadge(shadowBadge, "Night", "shadow");
                } else if (elevation <= horizon) {
                    setBadge(shadowBadge, "Shadow", "shadow");
                } else if (coverage < 0.9) {
                    setBadge(shadowBadge, `${numberFormat(coverage * 100, 0)}% coverage`, "waiting");
                } else {
                    setBadge(shadowBadge, "Sunlit", "sunlit");
                }
            };

            const requestSunlightForecast = async (site) => {
                if (!state.horizonProfile || state.horizonSiteKey !== siteCacheKey(site)) return;
                if (state.forecastController) state.forecastController.abort();
                const controller = new AbortController();
                state.forecastController = controller;
                const sequence = ++state.forecastSeq;
                const start = new Date(site.timestamp);
                const end = new Date(start.getTime() + 24 * HOUR_MS);
                setMetric("hud-sunlight-24h", "Calculating", "");
                try {
                    const response = await fetch(`${API_BASE}/analysis/sunlight-period`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Accept: "application/json" },
                        body: JSON.stringify({
                            lat: site.lat,
                            lon: site.lon,
                            elevation_m: site.elevation,
                            start_time: start.toISOString(),
                            end_time: end.toISOString(),
                            step_minutes: 15
                        }),
                        signal: controller.signal
                    });
                    if (!response.ok) {
                        const errorBody = await response.json().catch(() => ({}));
                        throw new Error(errorBody.detail || `HTTP ${response.status}`);
                    }
                    const result = await response.json();
                    if (sequence !== state.forecastSeq || siteCacheKey(state.lastSite || {}) !== siteCacheKey(site)) return;
                    const hours = Number(result.sunlit_duration_hours);
                    const fullyCovered = Number(result.known_illumination_coverage_percentage) >= 99.9;
                    if (fullyCovered) {
                        setMetric("hud-sunlight-24h", numberFormat(hours, 1), "h / 24 h");
                    } else {
                        setMetric(
                            "hud-sunlight-24h",
                            Number.isFinite(hours) && hours > 0 ? `≥ ${numberFormat(hours, 1)}` : "—",
                            Number.isFinite(hours) && hours > 0 ? "h \u00b7 partial" : "coverage incomplete"
                        );
                    }
                } catch (error) {
                    if (error && error.name === "AbortError") return;
                    if (sequence !== state.forecastSeq) return;
                    console.warn("Lunaris: 24-hour sunlight analysis failed:", error);
                    setMetric("hud-sunlight-24h", "—", "");
                } finally {
                    if (state.forecastController === controller) state.forecastController = null;
                }
            };

            const requestPsrScreen = async () => {
                const site = state.lastSite;
                const profile = state.horizonProfile;
                if (!site || !profile || state.horizonSiteKey !== siteCacheKey(site)) return;
                if (state.psrController) state.psrController.abort();
                const controller = new AbortController();
                state.psrController = controller;
                const sequence = ++state.psrSeq;
                state.psrTimestamp = site.timestamp;
                const button = $("hud-psr-run");
                const cycleButton = $("hud-psr-cycle-run");
                if (state.psrCycleController) state.psrCycleController.abort();
                state.psrCycleSeq += 1;
                state.psrCycleController = null;
                state.psrCycleTimestamp = null;
                if (cycleButton) cycleButton.disabled = true;
                if (button) {
                    button.disabled = true;
                    button.textContent = "346.6-day draconic year scan running\u2026";
                }
                setBadge($("hud-psr-candidate"), "Calculating · 1 draconic year", "waiting");
                try {
                    const response = await fetch(`${API_BASE}/analysis/psr-screen`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Accept: "application/json" },
                        body: JSON.stringify({
                            lat: site.lat,
                            lon: site.lon,
                            elevation: site.elevation,
                            timestamp: site.timestamp,
                            azimuth_step_deg: profile.azimuth_step_deg,
                            max_distance_m: profile.max_distance_m,
                            ray_step_m: profile.ray_step_m,
                            step_minutes: 60
                        }),
                        signal: controller.signal
                    });
                    if (!response.ok) {
                        const errorBody = await response.json().catch(() => ({}));
                        throw new Error(errorBody.detail || `HTTP ${response.status}`);
                    }
                    const result = await response.json();
                    if (
                        sequence !== state.psrSeq ||
                        site.timestamp !== (state.lastSite && state.lastSite.timestamp) ||
                        siteCacheKey(state.lastSite || {}) !== siteCacheKey(site)
                    ) return;

                    if (result.classification === "candidate") {
                        setBadge($("hud-psr-candidate"), "Pre-screen candidate \u00b7 1 lunar year dark", "shadow");
                    } else if (result.classification === "not_candidate") {
                        setBadge($("hud-psr-candidate"), "Not candidate \u00b7 Sun observed", "sunlit");
                    } else {
                        setBadge(
                            $("hud-psr-candidate"),
                            `Indeterminate · ${numberFormat(result.known_illumination_coverage_percentage, 0)}% coverage`,
                            "waiting"
                        );
                    }
                } catch (error) {
                    if (error && error.name === "AbortError") return;
                    if (sequence !== state.psrSeq) return;
                    console.warn("Lunaris: Lunar-year PSR scan failed:", error);
                    setBadge($("hud-psr-candidate"), "Could not be calculated", "error");
                } finally {
                    if (state.psrController === controller) state.psrController = null;
                    if (button && sequence === state.psrSeq) {
                        button.disabled = !state.horizonProfile;
                        button.textContent = "346.6-day draconic year PSR scan run";
                    }
                    if (cycleButton) cycleButton.disabled = !state.horizonProfile;
                }
            };

            const requestNodalPsrScreen = async () => {
                const site = state.lastSite;
                const profile = state.horizonProfile;
                if (!site || !profile || state.horizonSiteKey !== siteCacheKey(site)) return;
                if (state.psrController) state.psrController.abort();
                state.psrSeq += 1;
                state.psrController = null;
                const annualButton = $("hud-psr-run");
                if (annualButton) annualButton.disabled = true;
                if (state.psrCycleController) state.psrCycleController.abort();
                const controller = new AbortController();
                state.psrCycleController = controller;
                const sequence = ++state.psrCycleSeq;
                state.psrCycleTimestamp = site.timestamp;
                const button = $("hud-psr-cycle-run");
                const quality = $("hud-psr-cycle-quality");
                if (button) {
                    button.disabled = true;
                    button.textContent = "18.6-year scan running\u2026";
                }
                if (quality) quality.textContent = "About 163,000 hourly samples calculating\u2026";
                setBadge($("hud-psr-candidate"), "Calculating \u00b7 18.6 Earth years", "waiting");
                try {
                    const response = await fetch(`${API_BASE}/analysis/psr-cycle-screen`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Accept: "application/json" },
                        body: JSON.stringify({
                            lat: site.lat,
                            lon: site.lon,
                            elevation: site.elevation,
                            timestamp: site.timestamp,
                            azimuth_step_deg: profile.azimuth_step_deg,
                            max_distance_m: profile.max_distance_m,
                            ray_step_m: profile.ray_step_m,
                            step_minutes: 60
                        }),
                        signal: controller.signal
                    });
                    if (!response.ok) {
                        const errorBody = await response.json().catch(() => ({}));
                        throw new Error(errorBody.detail || `HTTP ${response.status}`);
                    }
                    const result = await response.json();
                    if (
                        sequence !== state.psrCycleSeq ||
                        site.timestamp !== (state.lastSite && state.lastSite.timestamp) ||
                        siteCacheKey(state.lastSite || {}) !== siteCacheKey(site)
                    ) return;
                    if (result.classification === "candidate") {
                        setBadge($("hud-psr-candidate"), "18.6 years \u00b7 PSR pre-screen candidate", "shadow");
                    } else if (result.classification === "not_candidate") {
                        setBadge($("hud-psr-candidate"), "Sun observed within 18.6 years", "sunlit");
                    } else {
                        setBadge($("hud-psr-candidate"), "18.6 years \u00b7 indeterminate data coverage", "waiting");
                    }
                    if (quality) {
                        const q = result.analysis_quality;
                        quality.textContent = `Coverage ${q.coverage} \u00b7 known time ${numberFormat(result.known_illumination_coverage_percentage, 1)}% \u00b7 DEM ${q.dem_resolution_m} m \u00b7 ray ${q.ray_step_m} m \u00b7 horizon ${numberFormat(q.max_distance_m / 1000, 0)} km \u00b7 step ${q.time_step_minutes} min`;
                    }
                } catch (error) {
                    if (error && error.name === "AbortError") return;
                    if (sequence !== state.psrCycleSeq) return;
                    setBadge($("hud-psr-candidate"), "Cycle scan failed", "error");
                    if (quality) quality.textContent = `Cycle analysis failed: ${error.message || error}`;
                } finally {
                    if (state.psrCycleController === controller) state.psrCycleController = null;
                    if (button && sequence === state.psrCycleSeq) {
                        button.disabled = !state.horizonProfile;
                        button.textContent = "18.6-year nodal cycle pre-screen";
                    }
                    if (annualButton) annualButton.disabled = !state.horizonProfile;
                }
            };

            const requestCandidateComparison = async () => {
                if (state.candidateController) state.candidateController.abort();
                const controller = new AbortController();
                state.candidateController = controller;
                const sequence = ++state.candidateSeq;
                const button = $("hud-candidate-run");
                const message = $("hud-candidate-message");
                const duration = Number($("hud-mission-days")?.value || 6);
                const timestamp = getTimestamp();
                if (button) {
                    button.disabled = true;
                    button.textContent = "Calculating regions\u2026";
                }
                if (message) message.textContent = "Computing terrain horizons and mission-duration illumination\u2026";
                try {
                    const response = await fetch(`${API_BASE}/analysis/candidate-comparison`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Accept: "application/json" },
                        body: JSON.stringify({
                            timestamp,
                            duration_days: duration,
                            step_minutes: 60
                        }),
                        signal: controller.signal
                    });
                    if (!response.ok) {
                        const errorBody = await response.json().catch(() => ({}));
                        throw new Error(errorBody.detail || `HTTP ${response.status}`);
                    }
                    const result = await response.json();
                    if (sequence !== state.candidateSeq) return;
                    if (timestamp !== getTimestamp()) {
                        if (message) message.textContent = "Time changed; rerun comparison.";
                        return;
                    }
                    const rows = $("hud-candidate-rows");
                    rows.replaceChildren();
                    for (const candidate of result.results || []) {
                        const row = document.createElement("tr");
                        const values = [
                            `${candidate.region} · ${candidate.site_id}`,
                            candidate.sunlit_percentage === null
                                ? `≥ ${numberFormat(candidate.sunlit_hours, 1)} h`
                                : `${numberFormat(candidate.sunlit_percentage, 0)}%`,
                            `${numberFormat(candidate.longest_sunlit_run_hours, 1)} h`,
                            candidate.slope_below_8_deg_percentage === null
                                ? "Indeterminate"
                                : `${numberFormat(candidate.slope_below_8_deg_percentage, 0)}%`,
                            candidate.earth_visibility === "sunlit"
                                ? "LOS available"
                                : candidate.earth_visibility === "unknown" ? "Indeterminate" : "Below terrain horizon"
                        ];
                        for (const value of values) {
                            const cell = document.createElement("td");
                            cell.textContent = value;
                            row.append(cell);
                        }
                        const coverageCell = document.createElement("td");
                        coverageCell.textContent = `${numberFormat(candidate.known_illumination_coverage_percentage, 0)}%`;
                        row.append(coverageCell);
                        const actionCell = document.createElement("td");
                        const focusButton = document.createElement("button");
                        focusButton.type = "button";
                        focusButton.textContent = "View on map";
                        focusButton.addEventListener("click", () => focusCandidateSite(candidate));
                        actionCell.append(focusButton);
                        row.append(actionCell);
                        rows.append(row);
                    }
                    $("hud-candidate-results").hidden = false;
                    if (message) {
                        message.textContent = `${result.results.length} representative candidate points \u00b7 ${duration} days \u00b7 UTC ${result.start_time_utc}. ${result.note}`;
                    }
                } catch (error) {
                    if (error && error.name === "AbortError") return;
                    if (sequence !== state.candidateSeq) return;
                    if (message) message.textContent = `Comparison failed: ${error.message || error}`;
                } finally {
                    if (state.candidateController === controller) state.candidateController = null;
                    if (button && sequence === state.candidateSeq) {
                        button.disabled = false;
                        button.textContent = "Compare 9 regions";
                    }
                }
            };

            const drawSlopePatch = (grid) => {
                const canvas = $("hud-slope-canvas");
                const context = canvas?.getContext("2d");
                if (!context || !Array.isArray(grid) || !grid.length) return;
                context.clearRect(0, 0, canvas.width, canvas.height);
                const cellWidth = canvas.width / grid[0].length;
                const cellHeight = canvas.height / grid.length;
                for (let row = 0; row < grid.length; row += 1) {
                    for (let column = 0; column < grid[row].length; column += 1) {
                        const slope = grid[row][column];
                        context.fillStyle = slope === null
                            ? "#475569"
                            : slope <= 5 ? "#34d399" : slope <= 8 ? "#fbbf24" : "#fb7185";
                        context.fillRect(
                            column * cellWidth,
                            row * cellHeight,
                            Math.ceil(cellWidth),
                            Math.ceil(cellHeight)
                        );
                    }
                }
                context.strokeStyle = "#f8fafc";
                context.lineWidth = 1.5;
                context.beginPath();
                context.arc(canvas.width / 2, canvas.height / 2, 4, 0, 2 * Math.PI);
                context.stroke();
            };

            const requestLandingSafety = async () => {
                const site = state.lastSite;
                if (!site) return;
                if (state.safetyController) state.safetyController.abort();
                const controller = new AbortController();
                state.safetyController = controller;
                const sequence = ++state.safetySeq;
                const button = $("hud-safety-run");
                const note = $("hud-safety-note");
                const siteKey = siteCacheKey(site);
                if (button) {
                    button.disabled = true;
                    button.textContent = "Calculating slope map\u2026";
                }
                try {
                    const response = await fetch(`${API_BASE}/analysis/landing-safety`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Accept: "application/json" },
                        body: JSON.stringify({ lat: site.lat, lon: site.lon, radius_m: 1000, cell_size_m: 20 }),
                        signal: controller.signal
                    });
                    if (!response.ok) {
                        const errorBody = await response.json().catch(() => ({}));
                        throw new Error(errorBody.detail || `HTTP ${response.status}`);
                    }
                    const result = await response.json();
                    if (sequence !== state.safetySeq || siteCacheKey(state.lastSite || {}) !== siteKey) return;
                    setMetric(
                        "hud-slope-below5",
                        result.slope_below_5_deg_percentage === null
                            ? "Indeterminate"
                            : numberFormat(result.slope_below_5_deg_percentage, 0),
                        result.slope_below_5_deg_percentage === null ? "" : "%"
                    );
                    setMetric(
                        "hud-slope-below8",
                        result.slope_below_8_deg_percentage === null
                            ? "Indeterminate"
                            : numberFormat(result.slope_below_8_deg_percentage, 0),
                        result.slope_below_8_deg_percentage === null ? "" : "%"
                    );
                    setMetric("hud-roughness-p95", numberFormat(result.roughness_p95_m, 2), "m");
                    drawSlopePatch(result.slope_deg);
                    if (note) {
                        note.textContent = `1 km radius \u00b7 ${numberFormat(result.coverage_percentage, 0)}% DEM coverage \u00b7 ${result.dem_resolution_m} m/pixel. ${result.note}`;
                    }
                } catch (error) {
                    if (error && error.name === "AbortError") return;
                    if (sequence !== state.safetySeq) return;
                    if (note) note.textContent = `Slope analysis failed: ${error.message || error}`;
                } finally {
                    if (state.safetyController === controller) state.safetyController = null;
                    if (button && sequence === state.safetySeq) {
                        button.disabled = !state.lastSite;
                        button.textContent = "Analyze local slope and roughness";
                    }
                }
            };

            const requestEarthLos = async () => {
                const site = state.lastSite;
                if (!site) return;
                const note = $("hud-safety-note");
                try {
                    const response = await fetch(`${API_BASE}/analysis/earth-los`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Accept: "application/json" },
                        body: JSON.stringify({ lat: site.lat, lon: site.lon, elevation_m: site.elevation })
                    });
                    if (!response.ok) {
                        const errorBody = await response.json().catch(() => ({}));
                        throw new Error(errorBody.detail || `HTTP ${response.status}`);
                    }
                    const result = await response.json();
                    const visible = result.geometric_earth_visibility === "visible";
                    setMetric("hud-earth-los", visible ? "visible" : "not_visible", "");
                    if (note) {
                        note.textContent = `Earth geometric visibility: ${result.geometric_earth_visibility} · horizon ${numberFormat(result.terrain_horizon_deg, 1)}° · Earth ${numberFormat(result.earth_elevation_deg, 1)}°.`;
                    }
                } catch (error) {
                    setMetric("hud-earth-los", "—", "");
                }
            };

            const requestLsiScore = async () => {
                const site = state.lastSite;
                if (!site) return;
                try {
                    const response = await fetch(`${API_BASE}/analysis/lsi-score`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Accept: "application/json" },
                        body: JSON.stringify({ lat: site.lat, lon: site.lon, radius_m: 1000 })
                    });
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    const result = await response.json();
                    const score = Number(result.lsi_score);
                    const suitabilityClass = result.lsi_class || "";
                    setMetric("hud-lsi-score", Number.isFinite(score) ? `${score.toFixed(1)} · Class ${suitabilityClass}` : "—", "");
                } catch (error) {
                    setMetric("hud-lsi-score", "—", "");
                }
            };

            const focusCandidateSite = (candidate) => {
                const lat = Number(candidate.latitude_deg);
                const lon = ((Number(candidate.longitude_deg) % 360) + 360) % 360;
                const elevation = Number(candidate.elevation_m);
                if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(elevation)) return;
                const phi = (lat * Math.PI) / 180;
                const lambda = (lon * Math.PI) / 180;
                const rho = 2 * MOON_RADIUS_M * Math.tan(Math.PI / 4 + phi / 2);
                const xKm = (rho * Math.sin(lambda)) / 1000;
                const yKm = (-rho * Math.cos(lambda)) / 1000;
                const site = { lat, lon, elevation, timestamp: getTimestamp() };
                state.lastSite = site;
                const safetyButton = $("hud-safety-run");
                if (safetyButton) safetyButton.disabled = false;
                endurationMarker(xKm, yKm, elevation);
                requestEphemeris(site);
                requestHorizonProfile(site);
                try {
                    localStorage.setItem(
                        SELECTED_SITE_STORAGE_KEY,
                        JSON.stringify({ lat, lon, elevation })
                    );
                } catch {}
                setMessage(`${candidate.region} (${candidate.site_id}) selected.`);
            };

            const requestHorizonProfile = async (site) => {
                if (state.horizonController) state.horizonController.abort();
                if (state.forecastController) state.forecastController.abort();
                if (state.psrController) state.psrController.abort();
                if (state.psrCycleController) state.psrCycleController.abort();
                state.psrSeq += 1;
                state.psrCycleSeq += 1;
                state.psrController = null;
                state.psrCycleController = null;
                state.psrTimestamp = null;
                state.psrCycleTimestamp = null;
                const controller = new AbortController();
                state.horizonController = controller;
                const sequence = ++state.horizonSeq;
                state.horizonSiteKey = siteCacheKey(site);
                state.horizonProfile = null;
                setMetric("hud-horizon-angle", "Calculating", "");
                setMetric("hud-horizon-distance", "Calculating", "");
                setMetric("hud-sunlight-24h", "—", "");
                setBadge($("hud-terrain-shadow"), "Calculating", "waiting");
                setBadge($("hud-psr-candidate"), "Terrain horizon pending", "waiting");
                const psrButton = $("hud-psr-run");
                if (psrButton) psrButton.disabled = true;
                const cycleButton = $("hud-psr-cycle-run");
                if (cycleButton) cycleButton.disabled = true;
                const horizonButton = $("hud-horizon-open");
                if (horizonButton) horizonButton.disabled = true;
                try {
                    const response = await fetch(`${API_BASE}/analysis/horizon`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json", Accept: "application/json" },
                        body: JSON.stringify({
                            lat: site.lat,
                            lon: site.lon
                        }),
                        signal: controller.signal
                    });
                    if (!response.ok) {
                        const errorBody = await response.json().catch(() => ({}));
                        throw new Error(errorBody.detail || `HTTP ${response.status}`);
                    }
                    const profile = await response.json();
                    if (sequence !== state.horizonSeq) return;
                    state.horizonProfile = profile;
                    const sampledElevation = Number(profile.site_elevation_m);
                    const activeSite = state.lastSite || site;
                    const exactSite = {
                        ...activeSite,
                        elevation: Number.isFinite(sampledElevation) ? sampledElevation : activeSite.elevation
                    };
                    state.lastSite = exactSite;
                    state.horizonSiteKey = siteCacheKey(exactSite);
                    try {
                        localStorage.setItem(
                            SELECTED_SITE_STORAGE_KEY,
                            JSON.stringify({ lat: exactSite.lat, lon: exactSite.lon, elevation: exactSite.elevation })
                        );
                    } catch {}
                    if (Number.isFinite(sampledElevation) && Math.abs(sampledElevation - Number(activeSite.elevation)) > 0.05) {
                        state.lastEphemeris = null;
                        const phi = (Number(exactSite.lat) * Math.PI) / 180;
                        const lambda = (Number(exactSite.lon) * Math.PI) / 180;
                        const rho = 2 * MOON_RADIUS_M * Math.tan(Math.PI / 4 + phi / 2);
                        endurationMarker((rho * Math.sin(lambda)) / 1000, (-rho * Math.cos(lambda)) / 1000, sampledElevation);
                        requestEphemeris(exactSite);
                    }
                    updateTerrainShadow(state.lastEphemeris && state.lastEphemeris.sun);
                    setBadge($("hud-psr-candidate"), "Pre-screen not run", "waiting");
                    if (psrButton) psrButton.disabled = false;
                    if (cycleButton) cycleButton.disabled = false;
                    if (horizonButton) horizonButton.disabled = false;
                    requestSunlightForecast(exactSite);
                } catch (error) {
                    if (error && error.name === "AbortError") return;
                    if (sequence !== state.horizonSeq) return;
                    console.warn("Lunaris: terrain horizon profile could not be calculated:", error);
                    setMetric("hud-horizon-angle", "—", "");
                    setMetric("hud-horizon-distance", "—", "");
                    setBadge($("hud-terrain-shadow"), "Data unavailable", "error");
                    setBadge($("hud-psr-candidate"), "Data unavailable", "error");
                    if (psrButton) psrButton.disabled = true;
                    if (cycleButton) cycleButton.disabled = true;
                    if (horizonButton) horizonButton.disabled = true;
                } finally {
                    if (state.horizonController === controller) state.horizonController = null;
                }
            };

            const logFileProtocolHint = (level) => {
                if (typeof window === "undefined" || window.location.protocol !== "file:") {
                    return;
                }
                const message =
                    "Lunaris: under file://, API/CORS requests may be " +
                    "blocked by the browser. Suggestion: " +
                    "run `python -m http.server 8080 --directory outputs` " +
                    "and open http://localhost:8080/south_pole_3d.html.";
                if (level === "info") {
                    console.info(message);
                } else {
                    console.warn(message);
                }
            };

            const polarStereographicToLatLon = (xM, yM) => {
                const rho = Math.hypot(xM, yM);
                if (rho <= 1e-12) {
                    return { lat: -90.0, lon: 0.0 };
                }
                const lonDeg = (Math.atan2(xM, -yM) * 180.0) / Math.PI;
                const latDeg =
                    -(180.0 / Math.PI) *
                    (Math.PI / 2.0 -
                        2.0 * Math.atan(rho / (2.0 * MOON_RADIUS_M * K0)));
                const lon = ((lonDeg % 360.0) + 360.0) % 360.0;
                const lat = Math.max(-90.0, Math.min(90.0, latDeg));
                return { lat, lon };
            };

            const nearestAxisIndex = (values, target) => {
                if (!values || values.length === 0) return -1;
                const first = Number(values[0]);
                const last = Number(values[values.length - 1]);
                if (!Number.isFinite(first) || !Number.isFinite(last)) return -1;

                const ascending = first <= last;
                let low = 0;
                let high = values.length - 1;

                while (low <= high) {
                    const middle = (low + high) >> 1;
                    const value = Number(values[middle]);
                    if (!Number.isFinite(value)) return -1;
                    if (value === target) return middle;
                    if (ascending ? value < target : value > target) {
                        low = middle + 1;
                    } else {
                        high = middle - 1;
                    }
                }

                if (low >= values.length) return values.length - 1;
                if (high < 0) return 0;

                const lowDistance = Math.abs(Number(values[low]) - target);
                const highDistance = Math.abs(Number(values[high]) - target);
                return lowDistance < highDistance ? low : high;
            };

            const lookupSurfaceElevation = (xKm, yKm) => {
                const mapDiv = $(MAP_ID);
                const trace = mapDiv && mapDiv.data ? mapDiv.data[0] : null;
                if (!trace || !trace.x || !trace.y || !trace.z) return null;

                const column = nearestAxisIndex(trace.x, xKm);
                const row = nearestAxisIndex(trace.y, yKm);
                if (column < 0 || row < 0) return null;

                const rowData = trace.z[row];
                let raw;
                if (rowData && typeof rowData === "object" && "length" in rowData) {
                    raw = rowData[column];
                } else {
                    raw = trace.z[row * trace.x.length + column];
                }

                const elevation = Number(raw);
                return Number.isFinite(elevation) ? elevation : null;
            };

            const resolveElevation = (point, xKm, yKm) => {
                const raw = point ? point.z : undefined;
                if (raw !== undefined && raw !== null && raw !== "") {
                    const direct = Number(raw);
                    if (Number.isFinite(direct)) return direct;
                }

                const fallback = lookupSurfaceElevation(xKm, yKm);
                if (Number.isFinite(fallback)) return fallback;

                return DEFAULT_ELEVATION_M;
            };

            const updateLocationAndFetch = (xM, yM, zM, xKm, yKm) => {
                const { lat, lon } = polarStereographicToLatLon(xM, yM);
                if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
                    console.warn("Lunaris: converted coordinates are invalid.");
                    setMessage("The selection could not be processed. Click a location on the DEM surface.");
                    return;
                }

                const elevation = Number.isFinite(zM) ? zM : DEFAULT_ELEVATION_M;
                const site = { lat, lon, elevation, timestamp: getTimestamp() };
                state.lastSite = site;
                const safetyButton = $("hud-safety-run");
                if (safetyButton) safetyButton.disabled = false;
                state.lastEphemeris = null;
                try {
                    localStorage.setItem(
                        SELECTED_SITE_STORAGE_KEY,
                        JSON.stringify({ lat, lon, elevation })
                    );
                } catch (error) {
                    console.info("Lunaris: selected site could not be stored for this session.", error);
                }
                clearTimeout(state.timeTimer);
                state.timeTimer = null;

                endurationMarker(xKm, yKm, elevation);
                requestEphemeris(site);
                requestHorizonProfile(site);
                requestEarthLos();
                requestLsiScore();
            };

            const computeLightPosition = (sun, observer) => {
                const azimuth = Number(sun.azimuth_deg);
                const elevation = Number(sun.elevation_deg);
                if (!Number.isFinite(azimuth) || !Number.isFinite(elevation)) {
                    return null;
                }

                const lonDeg = Number(observer.longitude_deg);
                const lonValue = Number.isFinite(lonDeg) ? lonDeg : 0.0;
                const lonRad = (lonValue * Math.PI) / 180.0;
                const azRad = (azimuth * Math.PI) / 180.0;
                const elRad = (elevation * Math.PI) / 180.0;

                const horizontal = Math.cos(elRad);
                const east = horizontal * Math.sin(azRad);
                const north = horizontal * Math.cos(azRad);
                const up = Math.sin(elRad);

                const x = east * Math.cos(lonRad) + north * Math.sin(lonRad);
                const y = east * Math.sin(lonRad) - north * Math.cos(lonRad);
                const scale = 100000.0;
                return {
                    x: x * scale,
                    y: y * scale,
                    z: up * scale
                };
            };

            const flushLightUpdate = () => {
                state.lightTimer = null;
                const position = state.pendingLight;
                state.pendingLight = null;
                if (!position) return;

                const mapDiv = $(MAP_ID);
                if (!mapDiv || typeof Plotly === "undefined") return;

                const previous = state.lastLightPosition;
                if (previous) {
                    const dx = position.x - previous.x;
                    const dy = position.y - previous.y;
                    const dz = position.z - previous.z;
                    if (Math.hypot(dx, dy, dz) < LIGHT_MIN_DELTA) return;
                }

                state.lastLightPosition = position;
                lockSceneClicks(SCENE_LOCK_MS);
                Plotly.restyle(
                    mapDiv,
                    { lightposition: [position] },
                    [0]
                );
            };

            // Throttle lighting updates: they are cosmetic and each one forces
            // the 3D scene to redraw, so never run them inside the click path.
            const updateSceneLighting = (sun, observer) => {
                const position = computeLightPosition(sun, observer);
                if (!position) return;
                state.pendingLight = position;
                if (state.lightTimer !== null) return;
                state.lightTimer = setTimeout(
                    flushLightUpdate,
                    LIGHT_UPDATE_DELAY_MS
                );
            };

            const renderHud = (payload) => {
                const data = payload || {};
                const request = data.request || {};
                const ephemeris = data.ephemeris || {};
                const observer = ephemeris.observer || {};
                const cartesian = data.cartesian || {};
                const sun = ephemeris.sun || {};
                const earth = ephemeris.earth || {};

                setMetric(
                    "hud-lat",
                    numberFormat(observer.latitude_deg ?? request.lat, 5),
                    "°"
                );
                setMetric(
                    "hud-lon",
                    numberFormat(observer.longitude_deg ?? request.lon, 5),
                    "°"
                );
                setMetric(
                    "hud-elevation",
                    numberFormat(observer.elevation_m ?? request.elevation, 0),
                    "m"
                );

                setMetric("hud-sun-elevation", numberFormat(sun.elevation_deg, 2), "°");
                setMetric("hud-sun-azimuth", numberFormat(sun.azimuth_deg, 2), "°");

                setMetric("hud-earth-elevation", numberFormat(earth.elevation_deg, 2), "°");
                setMetric("hud-earth-azimuth", numberFormat(earth.azimuth_deg, 2), "°");
                setMetric("hud-earth-distance", numberFormat(earth.distance_km, 1), "km");

                setMetric("hud-x", numberFormat(cartesian.x_m, 1), "m");
                setMetric("hud-y", numberFormat(cartesian.y_m, 1), "m");
                setMetric("hud-z", numberFormat(cartesian.z_m, 1), "m");
                setMetric("hud-frame", cartesian.frame || ephemeris.frame || "—");

                const sunlit = Number(sun.elevation_deg) > 0.0;
                setBadge(
                    $("hud-sun-status"),
                    sunlit ? "Sunlit" : "Shadow",
                    sunlit ? "sunlit" : "shadow"
                );

                const earthAboveGeometricHorizon = Number(earth.elevation_deg) > 0.0;
                setBadge(
                    $("hud-earth-status"),
                    earthAboveGeometricHorizon ? "Above geometric horizon" : "Below geometric horizon",
                    earthAboveGeometricHorizon ? "dte" : "dte-down"
                );

                if (ephemeris.timestamp_utc) {
                    const utc = $("hud-time-utc");
                    const utcText = formatUtc(ephemeris.timestamp_utc);
                    if (utc && utc.textContent !== utcText) {
                        utc.textContent = utcText;
                    }
                }

                updateSceneLighting(sun, observer);

                const stamp = ephemeris.timestamp_utc || request.timestamp;
                setMessage(
                    `Selected point updated${stamp ? ` · ${formatUtc(stamp)}` : ""}`
                );
            };

            let pendingHudPayload = null;
            let pendingHudFrame = null;

            const cancelPendingHudRender = () => {
                pendingHudPayload = null;
                if (pendingHudFrame !== null) {
                    cancelFrame(pendingHudFrame);
                    pendingHudFrame = null;
                }
            };

            const scheduleHudRender = (payload) => {
                pendingHudPayload = payload;
                if (pendingHudFrame !== null) return;
                pendingHudFrame = requestFrame(() => {
                    pendingHudFrame = null;
                    const data = pendingHudPayload;
                    pendingHudPayload = null;
                    if (data) renderHud(data);
                });
            };

            const handleError = (error) => {
                cancelPendingHudRender();

                const detail =
                    error instanceof Error ? error.message : String(error);
                const status = Number(error && error.status);
                const isNetworkError =
                    error instanceof TypeError ||
                    /failed to fetch|networkerror|load failed|network request failed/i.test(
                        detail
                    );

                if (isNetworkError) {
                    setApiStatus("API Offline", "offline");
                    setMessage(
                        "API unreachable. Start main.py server; " +
                            "if needed, serve the page via HTTP."
                    );
                    logFileProtocolHint();
                    return;
                }

                if (status === 422) {
                    console.warn("Lunaris API validation error (422):", detail);
                    setApiStatus("Invalid Request", "error");
                    setMessage(
                        "The selected coordinate or epoch could not be validated. " +
                            "Please click another point on the DEM surface."
                    );
                    return;
                }

                if (status === 503) {
                    console.warn("Lunaris SPICE engine unavailable (503):", detail);
                    setApiStatus("Engine Unavailable", "offline");
                    setMessage(
                        "SPICE engine is not responding right now. " +
                            "Try again in a few seconds."
                    );
                    return;
                }

                console.error("Lunaris request error:", error);
                setApiStatus("Request Error", "error");
                setMessage(`Calculation failed: ${detail}`);
            };

            const requestEphemeris = async (site) => {
                const sequence = ++state.requestSeq;
                if (state.activeController) state.activeController.abort();
                const controller = new AbortController();
                state.activeController = controller;
                cancelPendingHudRender();

                setApiStatus("Calculating...", "waiting");
                setMessage("SPICE kernels querying...");

                try {
                    const response = await fetch(`${API_BASE}/calculate`, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            Accept: "application/json"
                        },
                        body: JSON.stringify({
                            lat: site.lat,
                            lon: site.lon,
                            elevation: site.elevation,
                            timestamp: site.timestamp
                        }),
                        signal: controller.signal
                    });

                    if (sequence !== state.requestSeq) return;

                    if (!response.ok) {
                        let detail = `HTTP ${response.status}`;
                        try {
                            const errorBody = await response.json();
                            if (errorBody && errorBody.detail) {
                                detail =
                                    typeof errorBody.detail === "string"
                                        ? errorBody.detail
                                        : JSON.stringify(errorBody.detail);
                            }
                        } catch {
                            detail = `HTTP ${response.status}`;
                        }
                        const httpError = new Error(detail);
                        httpError.status = response.status;
                        throw httpError;
                    }

                    let payload;
                    try {
                        payload = await response.json();
                    } catch {
                        const parseError = new Error(
                            "The server response could not be read."
                        );
                        parseError.kind = "parse";
                        throw parseError;
                    }

                    if (sequence !== state.requestSeq) return;

                    state.lastEphemeris = payload.ephemeris || null;
                    updateTerrainShadow(state.lastEphemeris && state.lastEphemeris.sun);
                    scheduleHudRender(payload);
                    setApiStatus("Engine Ready", "dte");
                } catch (error) {
                    if (error && error.name === "AbortError") return;
                    if (sequence !== state.requestSeq) return;
                    handleError(error);
                } finally {
                    if (state.activeController === controller) {
                        state.activeController = null;
                    }
                }
            };

            const endurationMarker = (xKm, yKm, zM) => {
                const mapDiv = $(MAP_ID);
                if (!mapDiv || typeof Plotly === "undefined") return;

                const previous = state.lastMarker;
                if (
                    previous &&
                    previous.x === xKm &&
                    previous.y === yKm &&
                    previous.z === zM
                ) {
                    return;
                }

                let index = state.markerTraceIndex;
                if (index === null || index < 0) {
                    index = findMarkerTraceIndex();
                    if (index < 0) {
                        console.warn(
                            "Lunaris: selection marker trace was not found."
                        );
                        return;
                    }
                    state.markerTraceIndex = index;
                }

                state.pendingMarker = { index, x: xKm, y: yKm, z: zM };
                if (state.markerFrame !== null) return;

                state.markerFrame = requestFrame(() => {
                    state.markerFrame = null;
                    const pending = state.pendingMarker;
                    state.pendingMarker = null;
                    if (!pending) return;

                    state.lastMarker = {
                        x: pending.x,
                        y: pending.y,
                        z: pending.z
                    };
                    lockSceneClicks(SCENE_LOCK_MS);
                    Plotly.restyle(
                        mapDiv,
                        {
                            x: [[pending.x]],
                            y: [[pending.y]],
                            z: [[pending.z]],
                            visible: [true]
                        },
                        [pending.index]
                    );
                });
            };

            const applySelection = (selection) => {
                updateLocationAndFetch(
                    selection.xM,
                    selection.yM,
                    selection.elevation,
                    selection.xKm,
                    selection.yKm
                );
            };

            const queueSelection = (selection) => {
                state.pendingClick = selection;
                if (state.clickTimer !== null) return;
                state.clickTimer = setTimeout(() => {
                    state.clickTimer = null;
                    const pending = state.pendingClick;
                    state.pendingClick = null;
                    if (pending) applySelection(pending);
                }, CLICK_DEBOUNCE_MS);
            };

            const handleMapClick = (event) => {
                // Ignore the synthetic click events Plotly emits while a 3D
                // trace is being restyled; they previously caused a freeze.
                if (sceneClicksLocked()) return;

                if (
                    !event ||
                    !event.points ||
                    !Array.isArray(event.points) ||
                    event.points.length === 0
                ) {
                    console.warn("Lunaris: invalid or empty click detected.");
                    return;
                }

                const point = event.points[0];
                if (!point || point.curveNumber !== 0) {
                    return;
                }
                if (
                    point.x === undefined ||
                    point.x === null ||
                    point.y === undefined ||
                    point.y === null
                ) {
                    console.warn("Lunaris: Click coordinates missing.");
                    setMessage("The selection could not be processed. Click a location on the DEM surface.");
                    return;
                }

                const xKm = Number(point.x);
                const yKm = Number(point.y);
                if (!Number.isFinite(xKm) || !Number.isFinite(yKm)) {
                    console.warn("Lunaris: click coordinates are invalid.");
                    setMessage("The selection could not be processed. Click a location on the DEM surface.");
                    return;
                }

                const elevation = resolveElevation(point, xKm, yKm);
                queueSelection({
                    xKm,
                    yKm,
                    xM: xKm * 1000.0,
                    yM: yKm * 1000.0,
                    elevation
                });
            };

            const bindMap = () => {
                const mapDiv = $(MAP_ID);
                if (!mapDiv) return;
                state.markerTraceIndex = findMarkerTraceIndex();
                if (typeof mapDiv.on === "function") {
                    mapDiv.on("plotly_click", handleMapClick);
                } else {
                    mapDiv.addEventListener("plotly_click", handleMapClick);
                }
            };

            const bindTimeControls = () => {
                const slider = $("hud-time-slider");
                if (slider) {
                    slider.min = String(-HALF_RANGE_HOURS);
                    slider.max = String(HALF_RANGE_HOURS);
                    slider.value = "0";
                    slider.addEventListener("input", () => {
                        updateTimeDisplay();
                        scheduleSiteRefresh();
                    });
                    slider.addEventListener("change", () => {
                        updateTimeDisplay();
                        flushSiteRefresh();
                    });
                }

                const nowButton = $("hud-time-now");
                if (nowButton) nowButton.addEventListener("click", resetToNow);

                const playButton = $("hud-time-play");
                if (playButton) playButton.addEventListener("click", togglePlayback);

                const psrButton = $("hud-psr-run");
                if (psrButton) psrButton.addEventListener("click", requestPsrScreen);
                const cycleButton = $("hud-psr-cycle-run");
                if (cycleButton) cycleButton.addEventListener("click", requestNodalPsrScreen);

                const candidateButton = $("hud-candidate-run");
                if (candidateButton) {
                    candidateButton.addEventListener("click", requestCandidateComparison);
                }

                const safetyButton = $("hud-safety-run");
                if (safetyButton) safetyButton.addEventListener("click", requestLandingSafety);

                const horizonButton = $("hud-horizon-open");
                if (horizonButton) {
                    horizonButton.addEventListener("click", () => {
                        if (!state.lastSite || !state.horizonProfile) return;
                        const params = new URLSearchParams({
                            lat: String(state.lastSite.lat),
                            lon: String(state.lastSite.lon),
                            elevation: String(state.lastSite.elevation),
                            timestamp: state.lastSite.timestamp
                        });
                        const url = new URL(`horizon_analysis.html?${params}`, window.location.href);
                        window.open(url.toString(), "_blank", "noopener");
                    });
                }
            };

            const restoreSelectedSite = () => {
                let saved = null;
                const params = new URLSearchParams(window.location.search);
                if (params.has("lat") && params.has("lon") && params.has("elevation")) {
                    saved = {
                        lat: Number(params.get("lat")),
                        lon: Number(params.get("lon")),
                        elevation: Number(params.get("elevation"))
                    };
                } else {
                    try {
                        saved = JSON.parse(localStorage.getItem(SELECTED_SITE_STORAGE_KEY) || "null");
                    } catch {
                        saved = null;
                    }
                }
                if (!saved) return;

                const lat = Number(saved.lat);
                const lon = Number(saved.lon);
                const elevation = Number(saved.elevation);
                if (
                    !Number.isFinite(lat) || lat < -90 || lat > 0 ||
                    !Number.isFinite(lon) ||
                    !Number.isFinite(elevation) || Math.abs(elevation) > 20000
                ) return;

                const site = { lat, lon: ((lon % 360) + 360) % 360, elevation, timestamp: getTimestamp() };
                state.lastSite = site;
                const safetyButton = $("hud-safety-run");
                if (safetyButton) safetyButton.disabled = false;
                const phi = (lat * Math.PI) / 180;
                const lambda = (site.lon * Math.PI) / 180;
                const rho = 2 * MOON_RADIUS_M * Math.tan(Math.PI / 4 + phi / 2);
                endurationMarker((rho * Math.sin(lambda)) / 1000, (-rho * Math.cos(lambda)) / 1000, elevation);
                requestEphemeris(site);
                requestHorizonProfile(site);
                try {
                    localStorage.setItem(SELECTED_SITE_STORAGE_KEY, JSON.stringify({ lat, lon: site.lon, elevation }));
                } catch {}
            };

            const bindHudPanel = () => {
                const hud = $("lunaris-hud");
                const header = hud?.querySelector(".hud-header");
                const toggle = $("hud-toggle");
                if (!hud || !header || !toggle) return;

                toggle.addEventListener("click", () => {
                    const collapsed = hud.classList.toggle("hud-collapsed");
                    toggle.setAttribute("aria-expanded", String(!collapsed));
                    toggle.setAttribute("aria-label", collapsed ? "Expand panel" : "Collapse panel");
                    toggle.title = collapsed ? "Expand panel" : "Collapse panel";
                    toggle.textContent = collapsed ? "+" : "−";
                });

                let drag = null;
                header.addEventListener("pointerdown", (event) => {
                    if (event.target.closest("button, .badge")) return;
                    const rect = hud.getBoundingClientRect();
                    drag = {
                        pointerId: event.pointerId,
                        dx: event.clientX - rect.left,
                        dy: event.clientY - rect.top
                    };
                    hud.classList.add("dragging");
                    header.setPointerCapture(event.pointerId);
                    event.preventDefault();
                });
                header.addEventListener("pointermove", (event) => {
                    if (!drag || event.pointerId !== drag.pointerId) return;
                    const maxLeft = Math.max(0, window.innerWidth - hud.offsetWidth);
                    const maxTop = Math.max(0, window.innerHeight - 48);
                    const left = Math.min(maxLeft, Math.max(0, event.clientX - drag.dx));
                    const top = Math.min(maxTop, Math.max(0, event.clientY - drag.dy));
                    hud.style.left = `${left}px`;
                    hud.style.top = `${top}px`;
                    hud.style.right = "auto";
                    hud.style.bottom = "auto";
                });
                const stopDragging = (event) => {
                    if (!drag || event.pointerId !== drag.pointerId) return;
                    drag = null;
                    hud.classList.remove("dragging");
                };
                header.addEventListener("pointerup", stopDragging);
                header.addEventListener("pointercancel", stopDragging);
            };

            const checkHealth = async () => {
                try {
                    const response = await fetch(`${API_BASE}/health`, {
                        headers: { Accept: "application/json" }
                    });
                    if (!response.ok) {
                        const healthError = new Error(`HTTP ${response.status}`);
                        healthError.status = response.status;
                        throw healthError;
                    }

                    let payload;
                    try {
                        payload = await response.json();
                    } catch {
                        throw new Error("Health response could not be read.");
                    }

                    if (payload && payload.ready) {
                        setApiStatus("Engine ready", "dte");
                        if (!state.lastSite) {
                            setMessage(
                                "Select a point on the DEM surface by clicking."
                            );
                        }
                    } else {
                        setApiStatus("Engine unavailable", "error");
                        if (!state.lastSite) {
                            setMessage(
                                "The API is running, but the SPICE engine is not ready."
                            );
                        }
                    }
                } catch (error) {
                    const detail =
                        error instanceof Error ? error.message : String(error);
                    const status = Number(error && error.status);
                    const isNetworkError =
                        error instanceof TypeError ||
                        /failed to fetch|networkerror|load failed|network request failed/i.test(
                            detail
                        );

                    if (isNetworkError) {
                        console.warn("Lunaris: health check failed:", detail);
                        logFileProtocolHint();
                    } else if (status === 503) {
                        console.warn("Lunaris: engine unavailable (503):", detail);
                    } else {
                        console.warn("Lunaris: Health check error:", detail);
                    }

                    setApiStatus("API Offline", "offline");
                    if (!state.lastSite) {
                        setMessage(
                            "API unreachable. Start main.py server; " +
                                "if needed, serve the page via HTTP."
                        );
                    }
                }
            };

            const init = () => {
                logFileProtocolHint("info");
                bindTimeControls();
                bindHudPanel();
                updateTimeDisplay();
                bindMap();
                restoreSelectedSite();
                checkHealth();
            };

            if (document.readyState === "complete") {
                init();
            } else {
                window.addEventListener("load", init, { once: true });
            }
        })();
    </script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()

    try:
        dem, x_km, y_km = read_downsampled_dem(DEFAULT_DEM, args.stride)
    except Exception as exc:
        print(f"ERROR: could not read the DEM: {exc}", file=sys.stderr)
        return 1

    fig, z_min, z_max, z_mean = build_figure(
        dem, x_km, y_km, args.stride, args.colorscale
    )

    # Console summary.
    print()
    print(f"Downsampled shape : {dem.shape} (stride={args.stride})")
    print(f"Elevation minimum : {z_min:,.1f} m")
    print(f"Elevation maximum : {z_max:,.1f} m")
    print(f"Elevation mean    : {z_mean:,.1f} m")
    print(f"Displayed pixel   : {PIXEL_SIZE_KM * args.stride * 1000:.0f} m")
    print(f"Reference radius  : {REFERENCE_RADIUS_KM:.1f} km")
    print()

    plotly_fragment = fig.to_html(
        full_html=False,
        include_plotlyjs="inline",
        div_id="lunaris-map",
        config={"displayModeBar": True, "scrollZoom": True, "responsive": True},
    )
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    api_base = args.api_base.rstrip("/")
    html_document = (
        HTML_TEMPLATE.replace("__GENERATED_AT__", generated_at)
        .replace("__API_BASE__", json.dumps(api_base))
        .replace("__STRIDE__", str(args.stride))
        .replace("__DISPLAY_PIXEL_M__", f"{PIXEL_SIZE_KM * args.stride * 1000:.0f}")
        .replace("__PLOTLY_FRAGMENT__", plotly_fragment)
    )

    output_path = args.output
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_document, encoding="utf-8")
    print(f"Saved interactive HTML with HUD: {output_path.resolve()}")

    horizon_template_path = BASE_DIR / "horizon_analysis_view.html"
    horizon_template = horizon_template_path.read_text(encoding="utf-8")
    horizon_document = horizon_template.replace("__API_BASE__", json.dumps(api_base))
    horizon_output_path = output_path.with_name("horizon_analysis.html")
    horizon_output_path.write_text(horizon_document, encoding="utf-8")
    print(f"Saved selected-site horizon viewer: {horizon_output_path.resolve()}")

    if not args.no_show:
        try:
            webbrowser.open(output_path.resolve().as_uri())
        except (OSError, webbrowser.Error) as exc:
            print(
                f"Could not open the HTML viewer ({exc}). "
                f"Open the saved file manually: {output_path.resolve()}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
