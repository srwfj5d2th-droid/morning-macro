#!/usr/bin/env python3
"""history_context.py — long-run percentile/episode lookups for compute_state.py.

Answers the question Jacob asked 2026-10-08: when a Tier 1 series prints an
extreme reading, what does that mean against real history, not just this
system's ~10-month lookback -- and has a reading like it preceded a
recession, a pullback, or nothing at all before?

Every number this module returns is computed from data/history/*.csv
(fetched by build_long_history.py) and data/history/episodes.json. Nothing
here is recalled from training data or hand-typed at call time (§4C).

Two series (hy_oas, ig_oas) have only ~3 years of real history available to
this system's environment (see build_long_history.py's docstring) -- this
module reports that honestly via `short_history: true` rather than silently
producing a percentile that implies decades of support. Their long-run proxy
(a Baa/Aaa-minus-10Y corporate credit spread, real history back to 1983-86)
is exposed separately and must never be captioned as if it were the literal
OAS series.
"""

import csv
import datetime as dt
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HIST_DIR = REPO / "data" / "history"

# Tier 1 series key -> long-history source. "proxy" series are derived
# (difference of two fetched series), computed here, not fetched directly.
SOURCES = {
    "ust_3m": {"kind": "direct", "file": "dgs3mo"},
    "ust_2y": {"kind": "direct", "file": "dgs2"},
    "ust_10y": {"kind": "direct", "file": "dgs10"},
    "ust_30y": {"kind": "direct", "file": "dgs30"},
    "tips_10y_real": {"kind": "direct", "file": "dfii10"},
    "bkeven_10y": {"kind": "direct", "file": "t10yie"},
    "sofr": {"kind": "proxy_direct", "file": "dff",
             "proxy_note": "SOFR itself only exists from 2018; this uses the "
                            "effective fed funds rate, its long-run "
                            "predecessor as the economy's overnight rate."},
    "s2s10": {"kind": "diff", "a": "dgs10", "b": "dgs2"},
    "s3m10y": {"kind": "diff", "a": "dgs10", "b": "dgs3mo"},
    # No numeric proxy_key for hy_oas: Baa is the LOWEST investment-grade
    # rung, a full tier or more above the junk-rated universe ICE BofA HY
    # OAS actually covers. Baa-Treasury spreads run structurally far
    # tighter (2008 peak ~6.2pp vs HY OAS's own ~21.8% peak, per this
    # system's earlier published regime-line citation) -- quoting Baa as a
    # magnitude stand-in for HY OAS would just trade one overclaim for a
    # new, opposite-direction one. hy_oas gets only its own honest
    # short_history percentile; ig_oas's proxy below is the legitimate one
    # (both investment-grade) and its *episode timing* (did broad credit
    # stress coincide with X recession) is a fair directional cross-check
    # for hy_oas too, just never a magnitude comparison.
    "hy_oas": {"kind": "short_direct", "file": "baml_hy_oas"},
    "ig_oas": {"kind": "short_direct", "file": "baml_ig_oas",
               "proxy_key": "baa_10y_spread"},
    "baa_10y_spread": {"kind": "diff", "a": "dbaa", "b": "dgs10",
                        "proxy_note": "Moody's Baa corporate bond yield "
                                       "minus the 10Y Treasury -- a long-run "
                                       "investment-grade credit-risk-premium "
                                       "PROXY, not the literal ICE BofA IG "
                                       "OAS series this system quotes daily. "
                                       "Real history back to 1986. Useful "
                                       "for direction and episode timing "
                                       "(did credit broadly tighten/widen, "
                                       "and when); its magnitude runs "
                                       "tighter than IG OAS and far tighter "
                                       "than HY OAS, so never quote its "
                                       "level as if it were either."},
    "aaa_10y_spread": {"kind": "diff", "a": "daaa", "b": "dgs10",
                        "proxy_note": "Moody's Aaa corporate bond yield "
                                       "minus the 10Y Treasury -- the "
                                       "highest-grade long-run reference "
                                       "point, same caveat as the Baa one."},
}

_cache = {}


def _load_raw(file_key):
    if file_key in _cache:
        return _cache[file_key]
    path = HIST_DIR / f"{file_key}.csv"
    rows = []
    with open(path) as f:
        for d, v in csv.reader(f):
            if d == "date" or not v.strip():
                continue
            rows.append((d, float(v)))
    rows.sort(key=lambda r: r[0])
    _cache[file_key] = rows
    return rows


def _load_episodes():
    if "_episodes" in _cache:
        return _cache["_episodes"]
    with open(HIST_DIR / "episodes.json") as f:
        data = json.load(f)
    _cache["_episodes"] = data
    return data


def _diff_series(a_key, b_key):
    cache_key = f"_diff_{a_key}_{b_key}"
    if cache_key in _cache:
        return _cache[cache_key]
    a = dict(_load_raw(a_key))
    b = dict(_load_raw(b_key))
    dates = sorted(set(a) & set(b))
    rows = [(d, a[d] - b[d]) for d in dates]
    _cache[cache_key] = rows
    return rows


def _series_for(key):
    """Return (rows, meta) for a Tier 1 key, resolving diffs/proxies."""
    src = SOURCES[key]
    if src["kind"] in ("direct", "proxy_direct", "short_direct"):
        return _load_raw(src["file"]), src
    if src["kind"] == "diff":
        return _diff_series(src["a"], src["b"]), src
    raise ValueError(key)


def _percentile_rank(rows, value):
    vals = [v for _, v in rows]
    n = len(vals)
    if n == 0:
        return None
    n_leq = sum(1 for v in vals if v <= value)
    return round(100 * n_leq / n, 1)


def _percentiles(rows):
    vals = sorted(v for _, v in rows)
    n = len(vals)
    if n == 0:
        return {}

    def pct(p):
        idx = min(n - 1, max(0, round(p / 100 * (n - 1))))
        return vals[idx]

    return {"min": vals[0], "p10": pct(10), "p25": pct(25), "median": pct(50),
            "p75": pct(75), "p90": pct(90), "max": vals[-1]}


def _most_recent_at_least(rows, value, before_date):
    for d, v in reversed(rows):
        if d >= before_date:
            continue
        if v >= value:
            return d, v
    return None


def _most_recent_at_most(rows, value, before_date):
    for d, v in reversed(rows):
        if d >= before_date:
            continue
        if v <= value:
            return d, v
    return None


def _years_covered(rows):
    if not rows:
        return 0.0
    start = dt.date.fromisoformat(rows[0][0])
    end = dt.date.fromisoformat(rows[-1][0])
    return round((end - start).days / 365.25, 1)


def _recession_near(date_str, months_after=12):
    """Did an NBER recession start within `months_after` months of date_str?"""
    episodes = _load_episodes()
    d = dt.date.fromisoformat(date_str)
    hits = []
    for rec in episodes["recessions"]:
        start = dt.date.fromisoformat(rec["start"])
        delta_months = (start.year - d.year) * 12 + (start.month - d.month)
        if 0 <= delta_months <= months_after:
            hits.append({"name": rec["name"], "start": rec["start"],
                         "months_after": delta_months})
    return hits


def _episodes_matching(rows, value, direction):
    """Named episodes (incl. recessions) where the series reached a value
    at least as extreme as `value` within the episode's window."""
    episodes = _load_episodes()
    all_eps = episodes["recessions"] + episodes["named_episodes"]
    rows_by_date = rows
    out = []
    for ep in all_eps:
        window = [(d, v) for d, v in rows_by_date
                  if ep["start"] <= d <= ep["end"]]
        if not window:
            continue
        vals = [v for _, v in window]
        extreme = max(vals) if direction == "high" else min(vals)
        reached = extreme >= value if direction == "high" else extreme <= value
        if reached:
            out.append({"name": ep["name"], "window_extreme": extreme,
                        "start": ep["start"], "end": ep["end"]})
    return out


def context_for(key, today_value, today_date, direction="high"):
    """Build the long_history block for one Tier 1 series.

    direction: "high" if an elevated reading is the stress/extreme side
    worth comparing against history (true for all current Tier 1 series --
    yields, spreads, OAS). Percentile rank is reported regardless of
    direction; episode-matching and most-recent-comparable use it.
    """
    if key not in SOURCES:
        return None
    src = SOURCES[key]
    rows, _ = _series_for(key)
    if not rows:
        return None

    out = {
        "start_date": rows[0][0],
        "end_date": rows[-1][0],
        "years": _years_covered(rows),
        "n_obs": len(rows),
        "pct_rank_all_time": _percentile_rank(rows, today_value),
        "percentiles": _percentiles(rows),
        "short_history": src["kind"] == "short_direct",
    }

    cmp_fn = _most_recent_at_least if direction == "high" else _most_recent_at_most
    prior = cmp_fn(rows, today_value, today_date)
    if prior:
        pdate, pval = prior
        years_ago = round(
            (dt.date.fromisoformat(today_date) - dt.date.fromisoformat(pdate)).days
            / 365.25, 1)
        out["most_recent_comparable"] = {
            "date": pdate, "value": pval, "years_ago": years_ago,
            "recession_within_12m": _recession_near(pdate, 12),
        }
    else:
        out["most_recent_comparable"] = None  # today IS the historical extreme

    out["episodes_matching_or_exceeding"] = _episodes_matching(
        rows, today_value, direction)

    if "proxy_note" in src:
        out["proxy_note"] = src["proxy_note"]
    if "proxy_key" in src:
        out["proxy_key"] = src["proxy_key"]

    return out


def curve_inversions(key="s2s10"):
    """Contiguous negative-spread episodes for a curve series, with how long
    until the next recession started (None if none followed within 36mo)."""
    rows, _ = _series_for(key)
    episodes = _load_episodes()
    rec_starts = [dt.date.fromisoformat(r["start"])
                  for r in episodes["recessions"]]

    out = []
    in_inv = False
    start = trough_date = None
    trough_val = None
    for d, v in rows:
        if v < 0 and not in_inv:
            in_inv = True
            start, trough_date, trough_val = d, d, v
        elif v < 0 and in_inv:
            if v < trough_val:
                trough_date, trough_val = d, v
        elif v >= 0 and in_inv:
            in_inv = False
            out.append(_inversion_record(start, d, trough_date, trough_val,
                                          rec_starts))
    if in_inv:
        out.append(_inversion_record(start, rows[-1][0], trough_date,
                                      trough_val, rec_starts, ongoing=True))
    return out


def summarize_inversions(key="s2s10", min_days=10, min_trough_bp=10):
    """Material inversions only (filters out 1-2 day noise blips) -- the
    standing curve-inversion-vs-recession track record for prose."""
    all_inv = curve_inversions(key)
    material = [i for i in all_inv
                if i["days"] >= min_days or abs(i["trough_value_bp"]) >= min_trough_bp]
    with_lag = [i for i in material if i["lag_months_to_recession"] is not None]
    no_lag = [i for i in material
              if i["lag_months_to_recession"] is None and not i["ongoing"]]
    return {
        "n_material_episodes": len(material),
        "n_followed_by_recession_within_36mo": len(with_lag),
        "n_not_followed_within_36mo": len(no_lag),
        "episodes": material,
    }


def _inversion_record(start, end, trough_date, trough_val, rec_starts,
                       ongoing=False):
    s = dt.date.fromisoformat(start)
    next_rec = min((r for r in rec_starts if r >= s), default=None)
    lag_months = None
    if next_rec:
        lag_months = (next_rec.year - s.year) * 12 + (next_rec.month - s.month)
        if lag_months > 36:
            next_rec, lag_months = None, None
    return {
        "start": start, "end": end, "ongoing": ongoing,
        "trough_date": trough_date, "trough_value_bp": round(trough_val * 100, 0),
        "days": (dt.date.fromisoformat(end) - s).days,
        "next_recession_start": next_rec.isoformat() if next_rec else None,
        "lag_months_to_recession": lag_months,
    }
