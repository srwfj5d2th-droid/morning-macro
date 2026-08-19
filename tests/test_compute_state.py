"""Tests for compute_state.py — the arithmetic the brief's prose depends on."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from compute_state import (SEASONING_MIN, compute_series, series_obs,  # noqa: E402
                           stdev, ytd_change)


def obs(vals, start_day=1):
    """[(date, value)] over consecutive fake dates."""
    return [(f"2026-01-{d:02d}" if d <= 31 else f"2026-02-{d-31:02d}", v)
            for d, v in enumerate(vals, start=start_day)]


def test_d1_d5_deltas():
    s = compute_series(obs([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.5]))
    assert s["d1"] == 1.5          # 7.5 - 6.0
    assert s["d5"] == 5.5          # 7.5 - 2.0 (5 observations back)
    assert s["last"] == 7.5


def test_d5_requires_six_observations():
    s = compute_series(obs([1.0, 2.0, 3.0]))
    assert s["d1"] == 1.0
    assert s["d5"] is None


def test_seasoning_rule_thin_below_60_prior_obs():
    s = compute_series(obs([1.0] * SEASONING_MIN))   # 59 prior + last
    assert s["z_thin"] is True and s["z120"] is None and s["flag"] is False


def test_z_score_math():
    # 60 prior obs alternating 1/-1 (mean 0), last = 2
    prior = [1.0, -1.0] * 30
    s = compute_series(obs(prior + [2.0]))
    assert s["z_thin"] is False
    expected = 2.0 / stdev(prior)
    assert math.isclose(s["z120"], round(expected, 3), abs_tol=1e-9)


def test_flag_at_threshold():
    prior = [1.0, -1.0] * 30                    # sd ≈ 1.0084
    hot = compute_series(obs(prior + [10.0]))   # z far above 1.5
    calm = compute_series(obs(prior + [0.5]))   # z ≈ 0.5 — inside normal range
    assert hot["flag"] is True
    assert calm["flag"] is False


def test_z_window_excludes_latest_observation():
    # If the latest were included in its own window the z would shrink;
    # a constant history with one jump must give sd=0 -> z uses prior only.
    prior = [5.0] * 80
    s = compute_series(obs(prior + [9.0]))
    assert s["z120"] == 0.0 or s["z120"] is None or abs(s["z120"]) > 3
    # sd of constant prior is 0 -> implementation returns 0.0 by contract
    assert s["z120"] == 0.0


def test_trend20_directions():
    up = compute_series(obs([float(i) for i in range(1, 26)]))
    down = compute_series(obs([float(30 - i) for i in range(1, 26)]))
    assert up["trend20"] == "up"
    assert down["trend20"] == "down"


def test_trend20_flat_on_noise():
    vals = [10.0 + (0.01 if i % 2 else -0.01) for i in range(25)]
    s = compute_series(obs(vals))
    assert s["trend20"] == "flat"


def test_series_obs_skips_nulls():
    rows = [{"date": "2026-01-01", "x": "1.0"},
            {"date": "2026-01-02", "x": ""},
            {"date": "2026-01-03", "x": "3.0"}]
    assert series_obs(rows, "x") == [("2026-01-01", 1.0), ("2026-01-03", 3.0)]


def test_ytd_change_uses_last_obs_of_prior_year():
    o = [("2025-12-30", 100.0), ("2025-12-31", 110.0),
         ("2026-01-05", 121.0), ("2026-08-18", 132.0)]
    abs_chg, pct = ytd_change(o, "2026")
    assert abs_chg == 22.0
    assert pct == 20.0


def test_ytd_none_without_prior_year_base():
    abs_chg, pct = ytd_change([("2026-05-01", 1.0)], "2026")
    assert abs_chg is None and pct is None
