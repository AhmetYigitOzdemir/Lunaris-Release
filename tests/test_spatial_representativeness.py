from __future__ import annotations

import math

import pytest

from horizon_analysis import neighborhood_coordinates, summarize_neighborhood_values


def test_neighborhood_coordinates_center_and_count() -> None:
    coords = neighborhood_coordinates(-89.9, 0.0, radius_m=500.0, step_m=500.0)
    # 3x3 grid (radius 500 / step 500 -> half=1)
    assert len(coords) == 9
    # center point should be closest to original site
    distances = [abs(lat + 89.9) + abs(lon) for lat, lon in coords]
    center = min(coords, key=lambda c: abs(c[0] + 89.9) + abs(c[1]))
    assert abs(center[0] + 89.9) < 0.5
    assert abs(center[1]) < 0.5 or abs(center[1] - 360.0) < 0.5


def test_neighborhood_coordinates_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        neighborhood_coordinates(10.0, 0.0)
    with pytest.raises(ValueError):
        neighborhood_coordinates(-89.9, 0.0, radius_m=0.0)
    with pytest.raises(ValueError):
        neighborhood_coordinates(-89.9, 0.0, step_m=-1.0)


def test_summarize_neighborhood_values_basic() -> None:
    result = summarize_neighborhood_values([1.0, 2.0, None, 4.0])
    assert result["sample_count"] == 4
    assert result["valid_count"] == 3
    assert result["mean"] == pytest.approx(7.0 / 3.0)
    assert result["min"] == 1.0
    assert result["max"] == 4.0
    assert result["range"] == 3.0


def test_summarize_neighborhood_values_all_invalid() -> None:
    result = summarize_neighborhood_values([None, float("nan")])
    assert result["valid_count"] == 0
    assert result["mean"] is None
    assert result["std"] is None
    assert result["range"] is None
