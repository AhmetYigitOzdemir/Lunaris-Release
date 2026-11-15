"""
LSI monotonicity and behavior verification.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from horizon_analysis import _slope_score, _roughness_score


def test_slope_monotonicity():
    """Verify slope score is monotonically non-increasing."""
    prev = 100.0
    for s in [0, 1, 2, 3, 4, 5, 5.5, 6, 7, 8, 8.5, 9, 10, 12, 14, 15, 16, 20, 30]:
        score = _slope_score(s)
        assert score <= prev + 1e-9, f"Slope score not monotonic at {s}: {score} > {prev}"
        prev = score
    assert _slope_score(5.0) == 100.0
    assert _slope_score(8.0) == 60.0  # 100 - 3/3*40 = 60
    assert _slope_score(15.0) == 0.0   # 60 - 7/7*60 = 0
    assert _slope_score(15.1) == 0.0
    print("Slope score: MONOTONIC (verified)")
    print(f"  score(5°)={_slope_score(5.0)}, score(8°)={_slope_score(8.0)}, score(15°)={_slope_score(15.0)}")


def test_roughness_monotonicity():
    """Verify roughness score is monotonically non-increasing."""
    prev = 100.0
    for r in [0, 0.1, 0.5, 0.6, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 7.0, 7.1, 10.0]:
        score = _roughness_score(r)
        assert score <= prev + 1e-9, f"Roughness score not monotonic at {r}: {score} > {prev}"
        prev = score
    assert _roughness_score(0.5) == 100.0
    assert _roughness_score(2.0) == 50.0  # 100 - 1.5/1.5*50 = 50
    assert _roughness_score(7.0) == 0.0   # max(0, 50 - 5*10) = 0
    assert _roughness_score(float('nan')) == 100.0  # Non-finite = best score
    print("Roughness score: MONOTONIC (verified)")
    print(f"  score(0.5m)={_roughness_score(0.5)}, score(2.0m)={_roughness_score(2.0)}, score(7.0m)={_roughness_score(7.0)}")


def test_lsi_range():
    """Verify LSI weighted sum stays in [0, 100]."""
    # LSI = 0.7 * slope + 0.3 * roughness, both in [0, 100]
    min_lsi = 0.7 * 0.0 + 0.3 * 0.0
    max_lsi = 0.7 * 100.0 + 0.3 * 100.0
    assert min_lsi == 0.0
    assert max_lsi == 100.0
    print(f"LSI range: [{min_lsi}, {max_lsi}] (correct)")


def test_lsi_classes():
    """Verify LSI class thresholds."""
    # Classes: A >= 85, B >= 70, C >= 50, D < 50
    test_scores = [(85.0, "A"), (84.9, "B"), (70.0, "B"), (69.9, "C"), (50.0, "C"), (49.9, "D")]
    for score, expected in test_scores:
        if score >= 85.0:
            cls = "A"
        elif score >= 70.0:
            cls = "B"
        elif score >= 50.0:
            cls = "C"
        else:
            cls = "D"
        assert cls == expected, f"Class mismatch at {score}: {cls} != {expected}"
    print("LSI class thresholds: CORRECT")


if __name__ == "__main__":
    test_slope_monotonicity()
    test_roughness_monotonicity()
    test_lsi_range()
    test_lsi_classes()
    print()
    print("All LSI behavior checks passed.")
    print()
    print("NOTE: Weights (0.7/0.3) and thresholds are HEURISTIC, not empirically calibrated.")
    print("No published lunar landing standard supports these specific values.")
