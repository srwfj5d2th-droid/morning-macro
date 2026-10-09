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

Added 2026-10-08 (same day, Jacob's follow-up): percentile rank already
avoids the mean-skew trap (order statistics, not an average) -- but pooling
60+ years into one percentile still pools genuinely different monetary
regimes (Volcker-era double-digit rates vs. the Great Moderation vs. ZIRP
vs. now). A reading can look unremarkable against the full pool while being
unusual against the last few decades, or vice versa, if those regimes
differ enough. Every long_history block therefore carries a second,
trailing-MODERN_WINDOW_YEARS-year percentile alongside the all-time one, and
a `regime_divergence` flag when they disagree by REGIME_DIVERGENCE_PTS or
more -- so a brief can show both instead of picking one silently.
"""

import csv
import datetime as dt
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HIST_DIR = REPO / "data" / "history"

MODERN_WINDOW_YEARS = 30
REGIME_DIVERGENCE_PTS = 20

# Tier 1 series key -> long-history source. "proxy" series are derived
# (difference of two fetched series), computed here, not fetched directly.
SOURCES = {
    "ust_3m": {"kind": "direct", "file": "dgs3mo"},
    "ust_2y": {"kind": "direct", "file": "dgs2"},
    "ust_10y": {"kind": "direct", "file": "dgs10"},
    # Treasury suspended the 30-year bond 2002-02-18 .. 2006-02-09 and the
    # official 30Y constant-maturity series has no readings in that window,
    # yet this environment's FRED file carries ~1,000 values there (found
    # 2026-10-09 when a "first time since" landed on May 2004). Their
    # provenance can't be verified, so they're excluded from every
    # calculation rather than allowed to anchor a historical claim.
    "ust_30y": {"kind": "direct", "file": "dgs30",
                "exclude": [("2002-02-19", "2006-02-08")],
                "exclude_note": "30Y readings from 2002-02-19 to 2006-02-08 "
                                "excluded: Treasury had suspended the 30-year "
                                "bond, so values in that window are not "
                                "genuine 30Y constant-maturity prints."},
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
    # ICE U.S. Dollar Index, daily from Yahoo DX-Y.NYB (same instrument the
    # daily pull quotes) -- closes the "DXY has no long-run source" gap.
    "dxy": {"kind": "direct", "file": "dxy"},
}

# Price series whose LEVEL percentile is meaningless (equity indexes trend up
# for a century; nominal oil/gold are not inflation-adjusted). These get
# return-based context instead (market_context below): how unusual today's
# one-day move is, the last time a bigger one happened, distance from the
# running record high, and how this year-to-date compares with every prior
# year through the same calendar date.
MARKET_SOURCES = {
    "spx": {"file": "spx", "label": "S&P 500"},
    "ndx": {"file": "ixic", "label": "Nasdaq Composite"},
    "wti": {"file": "wti_fut", "label": "WTI crude (front-month futures)"},
    "gold": {"file": "gold_fut", "label": "Gold (front-month futures)"},
}

# Two qualifying readings more than this many days apart belong to separate
# episodes. A year is long enough that "the last time" means a genuinely
# earlier era, not a dip-and-recover inside the current run.
EPISODE_GAP_DAYS = 365

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
        rows = _load_raw(src["file"])
        for lo, hi in src.get("exclude", []):
            rows = [r for r in rows if not (lo <= r[0] <= hi)]
        return rows, src
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


def _window_rows(rows, end_date, years):
    """Rows within the trailing `years` years ending at (and including)
    end_date. Uses a day-count approximation (365.25/yr) rather than
    date.replace(year=...) to sidestep the Feb-29 edge case."""
    end = dt.date.fromisoformat(end_date)
    start = end - dt.timedelta(days=round(years * 365.25))
    return [(d, v) for d, v in rows if start.isoformat() <= d <= end_date]


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
    # never let a bar dated after the as-of date into the comparison (Yahoo
    # files carry a partial bar for the current session)
    rows = [r for r in rows if r[0] <= today_date]
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

    # trailing-window percentile (regime-pooling check, Jacob 2026-10-08):
    # the all-time number alone can look unremarkable while pooling eras
    # that aren't really comparable (Volcker-era vs. now). None of the
    # three short-history/direct-proxy series need this -- either the
    # window is the whole series already (hy_oas/ig_oas, ~3yr) or there's
    # no deep pool to pool incomparable regimes from in the first place.
    window_rows = _window_rows(rows, today_date, MODERN_WINDOW_YEARS)
    if window_rows and not out["short_history"]:
        modern_pct = _percentile_rank(window_rows, today_value)
        out["modern_window_years_requested"] = MODERN_WINDOW_YEARS
        out["modern_years"] = _years_covered(window_rows)
        out["modern_start_date"] = window_rows[0][0]
        out["pct_rank_modern"] = modern_pct
        out["percentiles_modern"] = _percentiles(window_rows)
        divergence_pts = round(abs(out["pct_rank_all_time"] - modern_pct), 1)
        out["regime_divergence_pts"] = divergence_pts
        out["regime_divergence"] = divergence_pts >= REGIME_DIVERGENCE_PTS
    else:
        out["pct_rank_modern"] = None
        out["regime_divergence"] = False
        out["regime_divergence_pts"] = None

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

    # "first time since" (added 2026-10-09, Jacob: still no deeper link to
    # history). most_recent_comparable above almost always lands inside the
    # current run (days ago), so it can't answer "when was the last time
    # before now?" -- prior_episode can. Side is picked from where the
    # reading sits: the trailing-30y percentile when it exists (the regime
    # a reader actually remembers), else the full-history one.
    ref_pct = out["pct_rank_modern"] if out["pct_rank_modern"] is not None \
        else out["pct_rank_all_time"]
    side = "high" if ref_pct >= 50 else "low"
    out["prior_episode"] = prior_episode(rows, today_value, today_date, side)

    if "exclude_note" in src:
        out["exclude_note"] = src["exclude_note"]
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


# ---------------------------------------------------------------------------
# "First time since" episodes, cross-series configurations, and return-based
# context for price series. Added 2026-10-09 after Jacob, again: the brief
# still didn't connect today to real history. The 10-08 layer could say
# where a reading ranks; it couldn't say WHEN it was last like this, what
# was going on then, or what came after. These can -- every value computed
# from data/history/*.csv, nothing recalled (§4C).
# ---------------------------------------------------------------------------

def _qualifies(v, value, side):
    return v >= value if side == "high" else v <= value


def group_episodes(rows, value, side, gap_days=EPISODE_GAP_DAYS):
    """Split the dates where the series was at/beyond `value` into episodes.
    A qualifying reading more than `gap_days` after the previous qualifying
    reading starts a new episode; shorter dips stay inside one episode."""
    eps = []
    cur = last = None
    for d, v in rows:
        if not _qualifies(v, value, side):
            continue
        day = dt.date.fromisoformat(d)
        if cur is None or (day - last).days > gap_days:
            cur = {"start": d, "end": d, "n_obs": 0,
                   "extreme": v, "extreme_date": d}
            eps.append(cur)
        cur["end"] = d
        cur["n_obs"] += 1
        if (v > cur["extreme"]) if side == "high" else (v < cur["extreme"]):
            cur["extreme"], cur["extreme_date"] = v, d
        last = day
    return eps


def _overlapping_named(start, end):
    """Named episodes and recessions whose window intersects [start, end]."""
    eps = _load_episodes()
    out = []
    for kind, lst in (("recession", eps["recessions"]),
                      ("episode", eps["named_episodes"])):
        for e in lst:
            if e["start"] <= end and e["end"] >= start:
                out.append({"name": e["name"], "kind": kind,
                            "start": e["start"], "end": e["end"]})
    # the GFC appears in both lists with slightly different windows; keep one
    seen, uniq = set(), []
    for e in out:
        if e["name"] in seen:
            continue
        seen.add(e["name"])
        uniq.append(e)
    return uniq


def _recessions_starting_between(start, end):
    return [r for r in _load_episodes()["recessions"]
            if start <= r["start"] <= end]


def _add_months(date_str, months):
    d = dt.date.fromisoformat(date_str)
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day).isoformat()


def _value_on_or_after(rows, date_str):
    for d, v in rows:
        if d >= date_str:
            return d, v
    return None


def _years_between(a, b):
    return round((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
                 / 365.25, 1)


def _backdrop(date_str, as_of):
    """What the Fed and the stock market were doing around date_str -- all
    read from data/history (dff.csv, spx.csv), never recalled. Returns only
    the pieces whose data exists."""
    out = {}
    try:
        ff = _load_raw("dff")
        now = _value_on_or_after(ff, date_str)
        then = _value_on_or_after(ff, _add_months(date_str, -12))
        if now and then and now[0] <= as_of:
            out["fed_funds"] = round(now[1], 2)
            out["fed_funds_change_prior_12m"] = round(now[1] - then[1], 2)
    except FileNotFoundError:
        pass
    try:
        spx = [r for r in _load_raw(MARKET_SOURCES["spx"]["file"]) if r[0] <= as_of]
        start = _value_on_or_after(spx, date_str)
        end_d = _add_months(date_str, 12)
        if start and end_d <= as_of:
            window = [v for d, v in spx if start[0] <= d <= end_d]
            end = _value_on_or_after(spx, end_d)
            if end and window:
                out["spx_return_next_12m_pct"] = round(
                    100.0 * (end[1] / start[1] - 1.0), 1)
                peak, worst = window[0], 0.0
                for v in window:
                    peak = max(peak, v)
                    worst = min(worst, v / peak - 1.0)
                out["spx_worst_drawdown_next_12m_pct"] = round(100.0 * worst, 1)
    except FileNotFoundError:
        pass
    return out


def _final_year_start(ep):
    return max(ep["start"], _add_months(ep["end"], -12))


def _describe_episode(rows, ep, as_of):
    end_plus_12 = _add_months(ep["end"], 12)
    end_plus_24 = _add_months(ep["end"], 24)
    after = _value_on_or_after(rows, end_plus_12) if end_plus_12 <= as_of else None
    return {
        # backdrop measured at the episode's END -- the last day the series
        # was at this level before now -- and the year that followed it
        "backdrop_at_end": _backdrop(ep["end"], as_of),
        "start": ep["start"], "end": ep["end"], "n_obs": ep["n_obs"],
        "extreme": round(ep["extreme"], 4), "extreme_date": ep["extreme_date"],
        "years_before_as_of": _years_between(ep["end"], as_of),
        # "back then" means around the LAST time -- the final year of the
        # stretch -- not its whole span: a 1977-2001 stretch would otherwise
        # describe Dec 2001 with the Volcker recessions
        "overlapping": _overlapping_named(_final_year_start(ep), ep["end"]),
        # a recession that began in that final year or in the two years
        # after -- reported as what happened, never as what the level
        # "predicts"
        "recessions_began_during_or_within_24m_after": [
            r["name"] for r in _recessions_starting_between(
                _final_year_start(ep), end_plus_24)],
        "value_12m_after_end": ({"date": after[0], "value": round(after[1], 4)}
                                if after else None),
    }


def prior_episode(rows, value, as_of, side, gap_days=EPISODE_GAP_DAYS,
                  max_track=8):
    """When was the series last at/beyond today's level BEFORE the current
    run, and what was going on then?

    rows: (date, value) history; today's (as_of, value) replaces any row on
    or after as_of so the current run is anchored on today's actual print
    (history files can trail the live series by a day or two).

    Returns None only if rows is empty. `prior` is None when no earlier
    episode exists in the series' history -- the brief may then say "not
    since records begin in <history_start>", and nothing stronger.
    """
    rows = [r for r in rows if r[0] < as_of] + [(as_of, value)]
    if not rows:
        return None
    eps = group_episodes(rows, value, side, gap_days)
    current = eps[-1]
    priors = eps[:-1]
    out = {
        "level": round(value, 4), "side": side, "gap_days": gap_days,
        "history_start": rows[0][0],
        "current_run_start": current["start"],
        "current_run_years": _years_between(current["start"], as_of),
        "n_prior_episodes": len(priors),
        "prior": _describe_episode(rows, priors[-1], as_of) if priors else None,
        "track": [
            {"start": e["start"], "end": e["end"],
             "extreme": round(e["extreme"], 4),
             "overlapping": [o["name"] for o in
                             _overlapping_named(e["start"], e["end"])]}
            for e in priors[-max_track:]],
    }
    return out


def _derived_rows(key, as_of=None):
    """Rows for a joint-config key: any SOURCES key, plus spx_dd (S&P 500
    percent below its running closing high)."""
    if key == "spx_dd":
        raw = [r for r in _load_raw(MARKET_SOURCES["spx"]["file"])
               if as_of is None or r[0] <= as_of]
        out, peak = [], None
        for d, v in raw:
            peak = v if peak is None else max(peak, v)
            out.append((d, round(100.0 * (v / peak - 1.0), 4)))
        return out
    rows, _ = _series_for(key)
    return [r for r in rows if as_of is None or r[0] <= as_of]


def joint_context(conditions, as_of, latest=None, gap_days=EPISODE_GAP_DAYS):
    """When were several series last simultaneously at/beyond their current
    readings?  conditions: [(key, side), ...].

    History: dates every series shares, strictly before as_of. Today: the
    as_of row uses `latest` ({key: (obs_date, value)}, the live readings the
    brief quotes) where given, else each series' last history value on or
    before as_of -- the usual "latest available" convention for series that
    publish a day or two behind. Component dates are reported so a lagged
    reading is never passed off as same-day.
    """
    latest = latest or {}
    series = {k: dict(_derived_rows(k, as_of)) for k, _ in conditions}
    today, today_dates = {}, {}
    for k, _ in conditions:
        if k in latest:
            today_dates[k], today[k] = latest[k]
        elif series[k]:
            d = max(series[k])
            today_dates[k], today[k] = d, series[k][d]
        else:
            return None
    hist = sorted(d for d in set.intersection(*(set(s) for s in series.values()))
                  if d < as_of)
    if not hist:
        return None
    ref = as_of
    dates = hist + [ref]
    for k in series:
        series[k][ref] = today[k]
    qual = [(d, 1.0) for d in dates
            if all(_qualifies(series[k][d], today[k], side)
                   for k, side in conditions)]
    eps = group_episodes(qual, 1.0, "high", gap_days)
    current, priors = eps[-1], eps[:-1]
    return {
        "as_of": ref,
        "conditions": [{"key": k, "side": side, "value": round(today[k], 4),
                        "obs_date": today_dates[k]}
                       for k, side in conditions],
        "shared_history_start": dates[0],
        "share_of_days_pct": round(100.0 * len(qual) / len(dates), 2),
        "current_run_start": current["start"],
        "n_prior_episodes": len(priors),
        "prior": ({"start": priors[-1]["start"], "end": priors[-1]["end"],
                   "years_before_as_of": _years_between(priors[-1]["end"], ref),
                   "backdrop_at_end": _backdrop(priors[-1]["end"], ref),
                   "overlapping": _overlapping_named(
                       _final_year_start(priors[-1]), priors[-1]["end"]),
                   "recessions_began_during_or_within_24m_after": [
                       r["name"] for r in _recessions_starting_between(
                           _final_year_start(priors[-1]),
                           _add_months(priors[-1]["end"], 24))]}
                  if priors else None),
        "track": [{"start": e["start"], "end": e["end"],
                   "overlapping": [o["name"] for o in
                                   _overlapping_named(e["start"], e["end"])]}
                  for e in priors[-8:]],
    }


def _returns(rows):
    return [(rows[i][0], rows[i][1] / rows[i - 1][1] - 1.0)
            for i in range(1, len(rows)) if rows[i - 1][1] > 0]


def _ytd_by_year(rows, month, day):
    """{year: return from prior year's last close to the last close on or
    before <year>-<month>-<day>} for every year with a prior-year close."""
    last_close = {}
    for d, v in rows:
        last_close[int(d[:4])] = v  # rows sorted -> ends on year's last close
    upto = {}
    for d, v in rows:
        y = int(d[:4])
        if (int(d[5:7]), int(d[8:10])) <= (month, day):
            upto[y] = v
    out = {}
    for y, v in upto.items():
        if y - 1 in last_close and int(rows[0][0][:4]) < y:
            out[y] = v / last_close[y - 1] - 1.0
    return out


def market_context(key, as_of):
    """Return-based long-run context for a price series (equity index, oil,
    gold) as of `as_of`. None if the series has no bar on as_of."""
    if key not in MARKET_SOURCES:
        return None
    src = MARKET_SOURCES[key]
    rows = [r for r in _load_raw(src["file"]) if r[0] <= as_of]
    if len(rows) < 260 or rows[-1][0] != as_of:
        return None
    rets = _returns(rows)
    today_ret = rets[-1][1]
    hist = rets[:-1]
    down = today_ret < 0

    def at_least_as_big(r):
        return r <= today_ret if down else r >= today_ret

    modern_start = (dt.date.fromisoformat(as_of)
                    - dt.timedelta(days=round(MODERN_WINDOW_YEARS * 365.25))
                    ).isoformat()
    hist_30 = [(d, r) for d, r in hist if d >= modern_start]
    n_big_all = sum(1 for _, r in hist if at_least_as_big(r))
    n_big_30 = sum(1 for _, r in hist_30 if at_least_as_big(r))
    bigger_since = next(((d, r) for d, r in reversed(hist) if at_least_as_big(r)),
                        None)

    # distance from the running closing record
    peak = peak_date = None
    dds = []
    for d, v in rows:
        if peak is None or v >= peak:
            peak, peak_date = v, d
        dds.append((d, 100.0 * (v / peak - 1.0)))
    dd_today = dds[-1][1]
    dds_30 = [x for x in dds if x[0] >= modern_start]

    m, dday = int(as_of[5:7]), int(as_of[8:10])
    ytd = _ytd_by_year(rows, m, dday)
    this_year = int(as_of[:4])
    ytd_today = ytd.get(this_year)
    prior_years = {y: r for y, r in ytd.items() if y < this_year}
    rank = (1 + sum(1 for r in prior_years.values() if r > ytd_today)
            if ytd_today is not None else None)

    return {
        "label": src["label"], "as_of": as_of,
        "history_start": rows[0][0],
        "years": _years_covered(rows),
        "move": {
            "pct": round(100.0 * today_ret, 3),
            "direction": "down" if down else "up",
            # share of all prior trading days with a move at least this
            # large in the same direction
            "pct_days_at_least_this_big_all": round(100.0 * n_big_all / len(hist), 2),
            "pct_days_at_least_this_big_30y": (round(100.0 * n_big_30 / len(hist_30), 2)
                                                if hist_30 else None),
            # average number of such days per year over the trailing 30y
            # (or the whole history when it is shorter than 30y)
            "per_year_recent": round(n_big_30 / min(MODERN_WINDOW_YEARS,
                                                    _years_covered(rows)), 1)
                               if hist_30 else None,
            "per_year_window_years": min(MODERN_WINDOW_YEARS, _years_covered(rows)),
            "last_at_least_this_big": ({"date": bigger_since[0],
                                         "pct": round(100.0 * bigger_since[1], 3),
                                         "trading_days_ago": len(hist) - next(
                                             i for i, (d, _) in enumerate(hist)
                                             if d == bigger_since[0])}
                                        if bigger_since else None),
        },
        "drawdown": {
            "pct_below_record": round(dd_today, 3),
            "record_close": round(peak, 4), "record_date": peak_date,
            # how often the series has been at least this close to its own
            # running record
            "pct_days_this_close_or_closer_all": round(
                100.0 * sum(1 for _, x in dds if x >= dd_today) / len(dds), 1),
            "pct_days_this_close_or_closer_30y": round(
                100.0 * sum(1 for _, x in dds_30 if x >= dd_today) / len(dds_30), 1)
                if dds_30 else None,
        },
        "ytd": ({
            "pct": round(100.0 * ytd_today, 2),
            "rank_among_years": rank,          # 1 = best year-to-date
            "n_years": len(prior_years) + 1,
            "first_year": min(ytd),
            "median_prior_years_pct": round(100.0 * sorted(prior_years.values())[
                len(prior_years) // 2], 2) if prior_years else None,
        } if ytd_today is not None else None),
    }
