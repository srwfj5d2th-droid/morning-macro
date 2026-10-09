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


# --- History v2 (2026-10-09): each test pins one bias the design review
# --- caught, so it can't creep back.

import datetime as _dt


def _days(start, values, step=1):
    d0 = _dt.date.fromisoformat(start)
    return [((d0 + _dt.timedelta(days=i * step)).isoformat(), float(v))
            for i, v in enumerate(values)]


def _fixture_world(tmp_path, monkeypatch, recessions=None, usrec_last="2026-09-01"):
    setup_fixture(tmp_path, monkeypatch)
    _write_episodes(tmp_path, recessions=recessions or [])
    _write_series(tmp_path, "usrec", [("1945-01-01", 0.0), (usrec_last, 0.0)])


def test_group_episodes_splits_on_gap_only():
    rows = [("2000-01-01", 5.0), ("2000-03-01", 1.0), ("2000-06-01", 5.0),
            ("2003-01-01", 5.0), ("2003-02-01", 6.0)]
    eps = hc.group_episodes(rows, 5.0, "high", gap_days=365)
    assert [(e["start"], e["end"]) for e in eps] == [
        ("2000-01-01", "2000-06-01"), ("2003-01-01", "2003-02-01")]
    assert eps[1]["extreme"] == 6.0


def test_group_episodes_low_side():
    rows = [("2000-01-01", 1.0), ("2000-02-01", 3.0), ("2002-01-01", 0.5)]
    eps = hc.group_episodes(rows, 1.0, "low", gap_days=365)
    assert len(eps) == 2 and eps[1]["extreme"] == 0.5


def test_lookback_tail_gate_suppresses_mid_range(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    rows = [("2000-01-01", 1.0), ("2010-01-01", 5.0), ("2020-01-01", 3.0)]
    lb = hc.lookback(rows, 3.0, "2026-10-08", p_all=50.0, p_30=60.0)
    assert lb["gated"] is False  # a mid-range reading earns no "last time" claim


def test_lookback_touch_vs_sustained_and_current_run(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    sustained = _days("1995-01-01", [6.0] * 40, step=7)      # long stretch
    touch = _days("2007-06-01", [5.3] * 3)                    # 3-day touch
    below = _days("2010-01-01", [3.0] * 5, step=200)
    run = _days("2026-09-28", [5.25, 5.31, 5.22])
    lb = hc.lookback(sustained + touch + below + run[:-1], 5.22, run[-1][0],
                     p_all=49.0, p_30=87.0)
    assert lb["gated"] and lb["side"] == "high"
    assert lb["current_run_start"] == "2026-09-28"
    assert lb["last_touch"]["end"] == "2007-06-03" and lb["last_touch"]["n_obs"] == 3
    assert lb["last_sustained"]["end"] == sustained[-1][0]
    # today (5.22) is below this run's own peak (5.31): never "highest since"
    assert lb["today_is_run_extreme"] is False and lb["run_extreme"] == 5.31
    assert lb["run_extreme_prior"]["end"] == sustained[-1][0]


def test_lookback_gap_sensitive_when_answer_depends_on_grouping(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    rows = (_days("2010-01-01", [5.0] * 30) + [("2018-01-01", 1.0), ("2025-03-01", 5.0),
                                               ("2025-06-01", 1.0)])
    lb = hc.lookback(rows, 5.0, "2026-01-01", p_all=90.0, p_30=90.0)
    # G=90/180 say "last time Mar 2025"; G=365 merges it into today's run
    assert lb["prior_end_by_gap_days"]["90"] == "2025-03-01"
    assert lb["prior_end_by_gap_days"]["365"] == rows[29][0]
    assert lb["gap_sensitive"] is True


def test_outcomes_are_measured_from_entry_not_end(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    # S&P rises 20% in the year after 2000-01-01, then crashes
    spx = _days("1999-01-01", [100.0] * 365) + _days("2000-01-01", [100 + 20 * i / 366 for i in range(367)]) \
        + _days("2001-01-03", [120 - 40 * i / 400 for i in range(401)])
    _write_series(tmp_path, "spx", [(d, round(v, 4)) for d, v in spx])
    # the condition held 2000-01-01 .. 2001-01-01 (12 readings, monthly)
    series = _days("1999-01-01", [1.0] * 12, step=30) + _days("2000-01-01", [5.0] * 13, step=30) \
        + _days("2001-03-01", [1.0] * 60, step=30)
    lb = hc.lookback(series, 5.0, "2026-10-08", p_all=95.0)
    t = lb["track"][0]
    assert t["entry"] == "2000-01-01"
    assert t["spx_12m"]["return_pct"] > 15     # from the start: a good year
    assert lb["track_summary"]["n"] == 1 and lb["track_summary"]["small_n"]


def test_recession_outcome_statuses(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch, recessions=[
        {"name": "R1", "start": "2008-01-01", "end": "2009-06-01"}], usrec_last="2026-09-01")
    assert hc.recession_outcome("2007-01-01")["status"] == "yes"
    assert hc.recession_outcome("2008-06-01")["status"] == "in_progress"
    assert hc.recession_outcome("2015-01-01")["status"] == "no"
    # window ends after NBER can judge (usrec last - 12m) -> pending, never "no"
    assert hc.recession_outcome("2024-06-01")["status"] == "pending"


def test_pair_bands_use_percentile_bands_not_exact_values(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    # 2005-06: a high and b low together, but neither as extreme as "today"
    a = _days("2003-01-01", [1.0] * 700) + _days("2005-01-01", [2.5] * 300) \
        + _days("2006-01-01", [1.0] * 3000)
    b = _days("2003-01-01", [3.0] * 700) + _days("2005-01-01", [1.6] * 300) \
        + _days("2006-01-01", [3.0] * 3000)
    _write_series(tmp_path, "dfii10", [(d, v) for d, v in a])
    _write_series(tmp_path, "dbaa", [(d, v + 4.0) for d, v in b])
    _write_series(tmp_path, "dgs10", [(d, 4.0) for d, _ in b])
    pr = hc.pair_bands("tips_10y_real", "high", "baa_10y_spread", "low", "2026-10-08",
                       latest={"tips_10y_real": ("2026-10-08", 2.9)})
    band = pr["bands"]["10"]
    assert band["today_in_band"]
    assert band["n_prior_stretches"] == 1          # 2005 counts at the band...
    assert pr["never_before_allowed"] is False     # ...so no "never before"


def test_inversion_cycles_merge_fragments_and_classify(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch, recessions=[
        {"name": "R90", "start": "1990-08-01", "end": "1991-03-01"},
        {"name": "R81", "start": "1981-08-01", "end": "1982-11-01"}], usrec_last="2026-09-01")
    pos = lambda start, n: _days(start, [0.5] * n)
    neg = lambda start, n, v=-0.3: _days(start, [v] * n)
    rows = (pos("1981-06-01", 30) + neg("1981-09-01", 20)          # began in recession
            + pos("1982-01-01", 400)
            + neg("1989-01-01", 15) + pos("1989-01-16", 60)        # fragment 1
            + neg("1989-03-17", 15) + pos("1989-04-01", 600)       # fragment 2, same cycle
            + neg("1998-06-01", 30, -0.05)                          # blip: too shallow
            + pos("1998-07-01", 9000)
            + neg("2024-01-01", 30) + pos("2024-01-31", 300))      # too recent to judge
    _write_series(tmp_path, "dgs10", [(d, 4.0 + v) for d, v in rows])
    _write_series(tmp_path, "dgs2", [(d, 4.0) for d, _ in rows])
    c = hc.inversion_cycles("s2s10", "2026-10-08")
    statuses = [x["status"] for x in c["cycles"]]
    assert statuses == ["began_in_recession", "followed", "pending"]
    assert c["cycles"][1]["fragments"] == 2       # 1989 counted once, not twice
    assert c["n_judged"] == 1 and c["n_followed"] == 1


def test_ytd_rank_bp_mode_keeps_negative_bases_and_skips_holes():
    rows = [("2011-12-30", -0.10), ("2012-10-08", 0.40),             # +50bp off a negative base
            ("2012-12-31", 0.20), ("2013-10-08", 0.30),              # +10bp
            ("2013-12-31", 0.30), ("2014-02-01", 0.90),              # data hole: no Oct obs
            ("2014-12-31", 0.50)]
    r = hc.ytd_rank(rows, 0.90, "2015-10-08", "bp")
    years = {y["year"] for y in r["years_more_extreme"]}
    assert r["change"] == 40 and r["rank"] == 2 and 2012 in years   # 2012 kept
    assert r["n_years"] == 3                                        # 2014 skipped


def test_rate_shock_counts_from_each_start(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    vals = [2.0] * 400 + [2.0 + 0.004 * i for i in range(300)] + [3.2] * 1200 \
        + [3.2 - 0.003 * i for i in range(400)] + [2.0 + 0.004 * i for i in range(300)]
    rows = _days("2000-01-01", vals)
    _write_series(tmp_path, "dgs10", rows[:-1])
    sh = hc.rate_shock("ust_10y", rows[-1][1], rows[-1][0])
    assert sh["change_12m_pp"] > 0.9
    assert sh["track_summary"]["n"] == 1
    assert sh["track"][0]["entry"] < "2002-01-01"


def test_market_context_v2_move_record_ytd_pullback_and_live_merge(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    rows, d, price = [], _dt.date(2020, 1, 1), 100.0
    while d <= _dt.date(2023, 3, 1):
        r = -0.05 if d.isoformat() == "2021-06-01" else 0.001
        price *= (1 + r)
        rows.append((d.isoformat(), round(price, 6)))
        d += _dt.timedelta(days=1)
    _write_series(tmp_path, "spx", rows + [("2023-03-04", 1.0)])  # partial future bar
    live = [("2023-03-02", round(price * 0.99, 6))]                # file is stale
    m = hc.market_context("spx", "2023-03-02", live_rows=live)
    assert m["as_of"] == "2023-03-02" and abs(m["move"]["pct"] + 1.0) < 1e-6
    assert m["move"]["last_at_least_this_big"]["date"] == "2021-06-01"
    assert m["record"]["record_date"] == "2023-03-01" and not m["record"]["stale"]
    assert m["ytd"]["n_years"] == 3
    assert m["pullback"]["this_year_worst_pct"] < 0


def test_then_vs_now_marks_similar_and_different(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    _write_series(tmp_path, "dgs10", _days("2000-01-01", list(range(1, 11)), step=365))
    _write_series(tmp_path, "dff", _days("2000-01-01", [5.0] * 5 + [1.0] * 5, step=365))
    tn = hc.then_vs_now("2003-12-31", "2010-12-31", {"ust_10y": ("2010-12-31", 5.0),
                                                      "dff": ("2010-12-31", 1.0)})
    by = {r["key"]: r for r in tn["rows"]}
    assert by["ust_10y"]["similar"] is True
    assert by["dff"]["similar"] is False


def test_lately_vs_history_labels():
    assert hc.lately_vs_history(2.3, False, 99.7, False) == "unusual lately and historically"
    assert hc.lately_vs_history(3.1, False, 55.0, False) == "unusual lately, ordinary historically"
    assert hc.lately_vs_history(None, True, 98.0, False) == "quiet lately, historically extreme"
    assert hc.lately_vs_history(3.1, False, 99.0, True) == "3-yr record only"


def test_context_for_ignores_rows_after_as_of(tmp_path, monkeypatch):
    _fixture_world(tmp_path, monkeypatch)
    _write_series(tmp_path, "dgs10", [("2000-01-01", 1.0), ("2000-01-02", 2.0),
                                      ("2000-01-03", 99.0)])  # future bar
    ctx = hc.context_for("ust_10y", 2.0, "2000-01-02")
    assert ctx["end_date"] == "2000-01-02" and ctx["pct_rank_all_time"] == 100.0


def test_add_months_clamps_month_end():
    assert hc._add_months("2007-01-31", 1) == "2007-02-28"
    assert hc._add_months("2008-01-31", 1) == "2008-02-29"
    assert hc._add_months("2007-06-14", 24) == "2009-06-14"


# --- the prose linter -------------------------------------------------------

import check_history_prose as lint  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _lint_state():
    return {"row_date": "2026-10-08",
            "long_history": {"ust_10y": {"pct_rank_all_time": 48.7, "pct_rank_modern": 86.7,
                                         "start_date": "1962-01-02"}},
            "history_digest": [{"id": "lookback:ust_10y", "tier": 1, "anchor_date": "2007-06-14",
                                "sentence": "x"}]}


def test_lint_fails_the_first_edition_that_skipped_history():
    """The regression test for Jacob's complaint: 2026-10-09's first edition
    carried no history section and never used the lead fact (10Y last here
    in 2007). The linter must refuse it."""
    content = json.loads((FIXTURES / "content_2026-10-09_first_edition.json").read_text())
    errors, _ = lint.lint(content, _lint_state())
    joined = " | ".join(errors)
    assert "history_html is empty" in joined
    assert "never mentions 2007" in joined


def test_lint_passes_grounded_prose_and_catches_overclaims():
    good = {"history_html": "<p>The 10-year was last here briefly in 2007. It sits at the "
                            "87th percentile of the last 30 years and the 49th since 1962.</p>",
            "regime_line": "A level last reached in 2007."}
    errors, _ = lint.lint(good, _lint_state())
    assert errors == []
    bad = {"history_html": "<p>Never before in 2007 terms. It is the 95th percentile. "
                           "The 1999 peak signals a recession. Stocks fell 25% over the next "
                           "year after 2007.</p>",
           "regime_line": "2007"}
    errors, _ = lint.lint(bad, _lint_state())
    joined = " | ".join(errors)
    assert "never before" in joined.lower()
    assert "95th percentile" in joined
    assert "1999" in joined
    assert "signals a" in joined
    assert "without a count" in joined
