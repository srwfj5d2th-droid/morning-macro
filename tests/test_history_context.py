"""Tests for history_context.py — long-run percentile/episode lookups (§4F).

Added 2026-10-08 (Jacob: "widest this system has tracked" needs real
historical context, not just an 8-10 month lookback). Uses synthetic data
in a temp dir so these tests never depend on network access or the live
data/history/*.csv files.
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import history_context as hc  # noqa: E402


def _write_series(hist_dir, name, rows):
    path = hist_dir / f"{name}.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "value"])
        w.writerows(rows)


def _write_episodes(hist_dir, recessions=None, named=None):
    data = {"recessions": recessions or [], "named_episodes": named or []}
    (hist_dir / "episodes.json").write_text(json.dumps(data))


def setup_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HIST_DIR", tmp_path)
    hc._cache.clear()
    return tmp_path


def test_percentile_rank_basic(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [(f"2000-01-{i:02d}", float(i)) for i in range(1, 11)]  # 1..10
    _write_series(tmp_path, "x", rows)
    _write_episodes(tmp_path)
    series_rows = hc._load_raw("x")
    # value 5 >= 5 of the 10 obs (1..5) -> 50th percentile
    assert hc._percentile_rank(series_rows, 5.0) == 50.0
    # value above everything -> 100th percentile
    assert hc._percentile_rank(series_rows, 100.0) == 100.0
    # value below everything -> 0th percentile
    assert hc._percentile_rank(series_rows, -1.0) == 0.0


def test_percentiles_breakpoints(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [(f"2000-01-{i:02d}", float(i)) for i in range(1, 11)]
    _write_series(tmp_path, "x", rows)
    _write_episodes(tmp_path)
    p = hc._percentiles(hc._load_raw("x"))
    assert p["min"] == 1.0
    assert p["max"] == 10.0
    assert 5.0 <= p["median"] <= 6.0


def test_most_recent_at_least_and_at_most(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [("2000-01-01", 5.0), ("2000-01-02", 2.0), ("2000-01-03", 8.0),
            ("2000-01-04", 1.0)]
    _write_series(tmp_path, "x", rows)
    _write_episodes(tmp_path)
    series_rows = hc._load_raw("x")
    # looking back from 2000-01-05 (excludes nothing), most recent >= 4.0
    # should be 2000-01-03 (8.0), the most recent qualifying obs scanning
    # backward even though 2000-01-01 (5.0) also qualifies
    d, v = hc._most_recent_at_least(series_rows, 4.0, "2000-01-05")
    assert (d, v) == ("2000-01-03", 8.0)
    # before_date excludes same-or-later dates
    d, v = hc._most_recent_at_least(series_rows, 4.0, "2000-01-03")
    assert (d, v) == ("2000-01-01", 5.0)
    # nothing qualifies
    assert hc._most_recent_at_least(series_rows, 100.0, "2000-01-05") is None
    d, v = hc._most_recent_at_most(series_rows, 1.5, "2000-01-05")
    assert (d, v) == ("2000-01-04", 1.0)


def test_years_covered(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [("2000-01-01", 1.0), ("2010-01-01", 2.0)]
    assert abs(hc._years_covered(rows) - 10.0) < 0.1


def test_recession_near_window(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path, recessions=[
        {"name": "fake recession", "start": "2008-01-01", "end": "2009-06-01"},
    ])
    # 6 months before the recession start -> within the 12mo window
    hits = hc._recession_near("2007-07-01", months_after=12)
    assert len(hits) == 1 and hits[0]["name"] == "fake recession"
    # 24 months before -> outside a 12mo window
    assert hc._recession_near("2006-01-01", months_after=12) == []
    # after the recession started -> not counted (delta would be negative)
    assert hc._recession_near("2008-06-01", months_after=12) == []


def test_episodes_matching_direction(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [("2008-01-01", 1.0), ("2008-06-01", 10.0), ("2008-12-01", 2.0)]
    _write_episodes(tmp_path, recessions=[
        {"name": "fake GFC", "start": "2008-01-01", "end": "2008-12-31"},
    ])
    matches = hc._episodes_matching(rows, 9.0, "high")
    assert len(matches) == 1
    assert matches[0]["window_extreme"] == 10.0
    # a value higher than anything in the window shouldn't match
    assert hc._episodes_matching(rows, 11.0, "high") == []


def test_context_for_short_history_flag(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [(f"2024-01-{i:02d}", float(i)) for i in range(1, 11)]
    _write_series(tmp_path, "short_src", rows)
    _write_episodes(tmp_path)
    monkeypatch.setitem(hc.SOURCES, "fake_short",
                         {"kind": "short_direct", "file": "short_src"})
    ctx = hc.context_for("fake_short", 10.0, "2024-01-15", direction="high")
    assert ctx["short_history"] is True
    assert ctx["n_obs"] == 10


def test_context_for_long_history_not_flagged_short(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [(f"2024-01-{i:02d}", float(i)) for i in range(1, 11)]
    _write_series(tmp_path, "long_src", rows)
    _write_episodes(tmp_path)
    monkeypatch.setitem(hc.SOURCES, "fake_long",
                         {"kind": "direct", "file": "long_src"})
    ctx = hc.context_for("fake_long", 10.0, "2024-01-15", direction="high")
    assert ctx["short_history"] is False


def test_diff_series_aligns_on_shared_dates(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_series(tmp_path, "a", [("2024-01-01", 5.0), ("2024-01-02", 6.0),
                                   ("2024-01-03", 7.0)])
    _write_series(tmp_path, "b", [("2024-01-01", 2.0), ("2024-01-02", 2.0)])
    diff = hc._diff_series("a", "b")
    # only the shared date 2024-01-01/02 should appear, not 01-03
    assert diff == [("2024-01-01", 3.0), ("2024-01-02", 4.0)]


def test_curve_inversion_detects_episode_and_recession_lag(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_series(tmp_path, "a", [
        ("2000-01-01", 1.0), ("2000-02-01", -0.5), ("2000-03-01", -1.0),
        ("2000-04-01", 0.5),
    ])
    _write_series(tmp_path, "b", [
        ("2000-01-01", 0.0), ("2000-02-01", 0.0), ("2000-03-01", 0.0),
        ("2000-04-01", 0.0),
    ])
    _write_episodes(tmp_path, recessions=[
        {"name": "fake recession", "start": "2001-01-01", "end": "2001-06-01"},
    ])
    monkeypatch.setitem(hc.SOURCES, "fake_spread",
                         {"kind": "diff", "a": "a", "b": "b"})
    inv = hc.curve_inversions("fake_spread")
    assert len(inv) == 1
    ep = inv[0]
    assert ep["start"] == "2000-02-01" and ep["end"] == "2000-04-01"
    assert ep["trough_value_bp"] == -100.0
    assert ep["next_recession_start"] == "2001-01-01"
    assert ep["lag_months_to_recession"] == 11


def test_curve_inversion_no_recession_within_36_months(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_series(tmp_path, "a", [("2000-01-01", -1.0), ("2000-02-01", 0.5)])
    _write_series(tmp_path, "b", [("2000-01-01", 0.0), ("2000-02-01", 0.0)])
    _write_episodes(tmp_path, recessions=[
        {"name": "too far out", "start": "2010-01-01", "end": "2010-06-01"},
    ])
    monkeypatch.setitem(hc.SOURCES, "fake_spread2",
                         {"kind": "diff", "a": "a", "b": "b"})
    inv = hc.curve_inversions("fake_spread2")
    assert inv[0]["next_recession_start"] is None
    assert inv[0]["lag_months_to_recession"] is None


def test_summarize_inversions_filters_noise_blips(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    # a 1-day, 2bp blip (noise) and a 20-day, 50bp real episode
    _write_series(tmp_path, "a", [
        ("2000-01-01", 0.0), ("2000-01-02", -0.02), ("2000-01-03", 0.0),
        ("2000-06-01", -0.5), ("2000-06-21", 0.1),
    ])
    _write_series(tmp_path, "b", [
        ("2000-01-01", 0.0), ("2000-01-02", 0.0), ("2000-01-03", 0.0),
        ("2000-06-01", 0.0), ("2000-06-21", 0.0),
    ])
    _write_episodes(tmp_path)
    monkeypatch.setitem(hc.SOURCES, "fake_spread3",
                         {"kind": "diff", "a": "a", "b": "b"})
    summary = hc.summarize_inversions("fake_spread3", min_days=10,
                                      min_trough_bp=10)
    assert summary["n_material_episodes"] == 1
    assert summary["episodes"][0]["trough_value_bp"] == -50.0


# --- trailing-window percentile / regime-divergence (Jacob, 2026-10-08 follow-up) ---

def test_window_rows_filters_to_trailing_years():
    rows = [("2000-01-01", 1.0), ("2010-01-01", 2.0), ("2019-06-01", 3.0),
            ("2020-01-01", 4.0)]
    windowed = hc._window_rows(rows, "2020-01-01", 5)
    # only 2019-06-01 and 2020-01-01 fall within 5 years of 2020-01-01
    assert windowed == [("2019-06-01", 3.0), ("2020-01-01", 4.0)]


def test_context_for_flags_regime_divergence(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    # Mirrors the real ust_10y finding: an old, HIGH-value regime (1970-95,
    # like the Volcker-era double-digit years) followed by a LOW-value
    # modern regime (1996-2024, like the post-2008 near-zero years), then
    # today's reading of 5.0 -- squarely in the middle of the full pool
    # (high-regime 8s balance out low-regime 1s) but near the TOP of just
    # the trailing-30y window, which is dominated by the low-regime 1s.
    rows = [(f"{1970+y}-01-01", 8.0) for y in range(26)]           # 1970-95
    rows += [(f"{1996+y}-01-01", 1.0) for y in range(29)]          # 1996-2024
    rows += [("2025-01-01", 5.0)]                                  # today
    _write_series(tmp_path, "regime_src", rows)
    _write_episodes(tmp_path)
    monkeypatch.setitem(hc.SOURCES, "fake_regime",
                         {"kind": "direct", "file": "regime_src"})
    ctx = hc.context_for("fake_regime", 5.0, "2025-01-01", direction="high")
    # full 56yr pool: 26 eights (above 5) + 29 ones + the 5 itself -> ~54th
    assert 40 < ctx["pct_rank_all_time"] < 60
    # trailing 30y window (~1995-2025): dominated by the low-regime ones,
    # so today's 5.0 sits at or near the very top of that window
    assert ctx["pct_rank_modern"] >= 95.0
    assert ctx["regime_divergence"] is True
    assert ctx["regime_divergence_pts"] >= hc.REGIME_DIVERGENCE_PTS


def test_context_for_no_divergence_when_windows_agree(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [(f"{1970+y}-01-01", 5.0) for y in range(50)]
    _write_series(tmp_path, "flat_src", rows)
    _write_episodes(tmp_path)
    monkeypatch.setitem(hc.SOURCES, "fake_flat",
                         {"kind": "direct", "file": "flat_src"})
    ctx = hc.context_for("fake_flat", 5.0, "2019-01-01", direction="high")
    assert ctx["regime_divergence"] is False
    assert ctx["regime_divergence_pts"] < hc.REGIME_DIVERGENCE_PTS


def test_context_for_short_history_has_no_modern_window(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    rows = [(f"2024-01-{i:02d}", float(i)) for i in range(1, 11)]
    _write_series(tmp_path, "short_src2", rows)
    _write_episodes(tmp_path)
    monkeypatch.setitem(hc.SOURCES, "fake_short2",
                         {"kind": "short_direct", "file": "short_src2"})
    ctx = hc.context_for("fake_short2", 10.0, "2024-01-15", direction="high")
    assert ctx["pct_rank_modern"] is None
    assert ctx["regime_divergence"] is False


# --- 2026-10-09: "first time since" episodes, joint configs, market context ---

def _daily(start, values):
    """Consecutive calendar-day rows from `start` (fine for these tests)."""
    import datetime as _dt
    d0 = _dt.date.fromisoformat(start)
    return [((d0 + _dt.timedelta(days=i)).isoformat(), float(v))
            for i, v in enumerate(values)]


def test_group_episodes_splits_on_gap_only():
    rows = [("2000-01-01", 5.0), ("2000-03-01", 1.0), ("2000-06-01", 5.0),
            ("2003-01-01", 5.0), ("2003-02-01", 6.0)]
    eps = hc.group_episodes(rows, 5.0, "high", gap_days=365)
    # a 5-month dip stays inside one episode; a 2.5-year gap starts a new one
    assert [(e["start"], e["end"]) for e in eps] == [
        ("2000-01-01", "2000-06-01"), ("2003-01-01", "2003-02-01")]
    assert eps[1]["extreme"] == 6.0 and eps[1]["extreme_date"] == "2003-02-01"


def test_group_episodes_low_side():
    rows = [("2000-01-01", 1.0), ("2000-02-01", 3.0), ("2002-01-01", 0.5)]
    eps = hc.group_episodes(rows, 1.0, "low", gap_days=365)
    assert len(eps) == 2 and eps[1]["extreme"] == 0.5


def test_prior_episode_skips_current_run(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path, recessions=[
        {"name": "R1", "start": "2008-01-01", "end": "2009-06-01"}])
    rows = [("2007-06-01", 5.3), ("2007-07-01", 5.0), ("2010-01-01", 3.0),
            ("2026-09-28", 5.25), ("2026-10-06", 5.27)]
    pe = hc.prior_episode(rows, 5.22, "2026-10-08", "high")
    # current run anchors on the as-of print even though the file stops 10-06
    assert pe["current_run_start"] == "2026-09-28"
    assert pe["prior"]["start"] == pe["prior"]["end"] == "2007-06-01"
    assert pe["prior"]["recessions_began_during_or_within_24m_after"] == ["R1"]
    assert pe["n_prior_episodes"] == 1


def test_prior_episode_none_when_unprecedented(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path)
    rows = [("2003-01-01", 1.0), ("2010-01-01", 2.0)]
    pe = hc.prior_episode(rows, 3.0, "2026-10-08", "high")
    assert pe["prior"] is None and pe["n_prior_episodes"] == 0
    assert pe["history_start"] == "2003-01-01"


def test_prior_episode_today_value_overrides_stale_file_row(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path)
    # file's as-of row (5.10) is below today's live print (5.22); the run
    # must still be anchored on today, not treated as "not at this level"
    rows = [("2007-06-01", 5.3), ("2026-10-08", 5.10)]
    pe = hc.prior_episode(rows, 5.22, "2026-10-08", "high")
    assert pe["current_run_start"] == "2026-10-08"
    assert pe["prior"]["start"] == "2007-06-01"


def test_context_for_ignores_rows_after_as_of(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path)
    _write_series(tmp_path, "dgs10", [("2000-01-01", 1.0), ("2000-01-02", 2.0),
                                      ("2000-01-03", 99.0)])  # future bar
    ctx = hc.context_for("ust_10y", 2.0, "2000-01-02")
    assert ctx["end_date"] == "2000-01-02"
    assert ctx["pct_rank_all_time"] == 100.0


def test_joint_context_requires_all_conditions_and_uses_latest(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path)
    # a high on 1998-01-01 and b high on 1999-01-01 -- never together until now
    _write_series(tmp_path, "dgs10", [("1998-01-01", 6.0), ("1999-01-01", 1.0),
                                      ("2026-10-06", 5.0)])
    _write_series(tmp_path, "dxy", [("1998-01-01", 80.0), ("1999-01-01", 110.0),
                                    ("2026-10-06", 100.0)])
    j = hc.joint_context([("ust_10y", "high"), ("dxy", "high")], "2026-10-08",
                         latest={"ust_10y": ("2026-10-08", 5.2),
                                 "dxy": ("2026-10-08", 102.0)})
    assert j["prior"] is None and j["n_prior_episodes"] == 0
    assert [c["obs_date"] for c in j["conditions"]] == ["2026-10-08", "2026-10-08"]
    # now make 1998 qualify on both
    _write_series(tmp_path, "dxy", [("1998-01-01", 105.0), ("1999-01-01", 110.0),
                                    ("2026-10-06", 100.0)])
    hc._cache.clear()
    j = hc.joint_context([("ust_10y", "high"), ("dxy", "high")], "2026-10-08",
                         latest={"ust_10y": ("2026-10-08", 5.2),
                                 "dxy": ("2026-10-08", 102.0)})
    assert j["prior"]["start"] == j["prior"]["end"] == "1998-01-01"


def test_market_context_move_drawdown_and_ytd(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path)
    import datetime as _dt
    rows = []
    d = _dt.date(2020, 1, 1)
    price = 100.0
    # three full years of +0.1%/day, with one -3% day in 2021
    while d <= _dt.date(2023, 3, 1):
        r = 0.001
        if d.isoformat() == "2021-06-01":
            r = -0.03
        price *= (1 + r)
        rows.append((d.isoformat(), round(price, 6)))
        d += _dt.timedelta(days=1)
    # as-of day: a -1% move; then a partial "future" bar that must be ignored
    rows.append(("2023-03-02", round(price * 0.99, 6)))
    rows.append(("2023-03-03", round(price * 0.5, 6)))
    _write_series(tmp_path, "spx", rows)
    m = hc.market_context("spx", "2023-03-02")
    assert m["as_of"] == "2023-03-02"
    assert abs(m["move"]["pct"] - (-1.0)) < 1e-6
    # the only earlier move at least as big is the -3% day
    assert m["move"]["last_at_least_this_big"]["date"] == "2021-06-01"
    assert abs(m["drawdown"]["pct_below_record"] - (-1.0)) < 1e-6
    assert m["drawdown"]["record_date"] == "2023-03-01"
    # YTD through Mar 2: 2021 (2 full years of data before it? 2020 is the
    # first year so it has no prior-year close) -> years 2021, 2022, 2023
    assert m["ytd"]["n_years"] == 3 and m["ytd"]["first_year"] == 2021


def test_market_context_none_without_as_of_bar(tmp_path, monkeypatch):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path)
    rows = _daily("2020-01-01", [100 + i for i in range(400)])
    _write_series(tmp_path, "spx", rows)
    assert hc.market_context("spx", "2030-01-01") is None


def test_add_months_clamps_month_end():
    assert hc._add_months("2007-01-31", 1) == "2007-02-28"
    assert hc._add_months("2008-01-31", 1) == "2008-02-29"
    assert hc._add_months("2007-06-14", 24) == "2009-06-14"
