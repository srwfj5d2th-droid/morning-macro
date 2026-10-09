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
import statistics
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
    # Reference series (not Tier 1; added 2026-10-09). Each is quoted on its
    # own latest observation and labeled as what it is.
    "real10_cleveland": {"kind": "direct", "file": "real10_cleveland",
                         "proxy_note": "Cleveland Fed model estimate of the "
                                       "10-year real rate, monthly, 1982+ -- a "
                                       "long-run cross-check on the TIPS yield "
                                       "(2003+). Built differently from TIPS; "
                                       "never spliced into it."},
    "kw_tp10": {"kind": "direct", "file": "kw_tp10",
                "proxy_note": "Kim-Wright 10-year term premium, a Federal "
                              "Reserve Board model estimate (1990+). Use for "
                              "direction and decomposition; other models "
                              "differ."},
    "mortgage30": {"kind": "direct", "file": "mortgage30",
                   "proxy_note": "Freddie Mac 30-year fixed mortgage rate, "
                                 "weekly survey (1971+)."},
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

    # "last time it was here" (v2, 2026-10-09). most_recent_comparable above
    # nearly always lands inside the current run ("days ago") -- kept only
    # for audit; never cite it. lookback() answers the real question, and
    # only for a tail reading whose answer survives different groupings.
    out["lookback"] = lookback(rows, today_value, today_date,
                               out["pct_rank_all_time"], out["pct_rank_modern"],
                               short=out["short_history"])

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
# History v2 -- 2026-10-09. Jacob, live: "I still didn't see in the morning
# macro a deeper connection to historical context like I've been asking for."
# Built after an independent three-lens design review (advisor, statistician,
# historian) of a first attempt the same morning. That review caught biases
# this code is now built to avoid; each is pinned below and changes only at
# monthly review (fixed thresholds stop the model from shopping for a story):
#   * "What came next" is measured from the START of a past stretch (the
#     day it first looked like today), never its END -- an end is only known
#     in hindsight and is often the day a crisis began, which manufactures
#     "last time, stocks fell" (S&P near a record: median next-12m +14% from
#     the start vs -16% from the end).
#   * Every outcome is shown against the normal (base) rate, and windows
#     too recent to judge are "pending", never "no recession followed".
#   * "Last time" is only claimed for readings in a tail (TAIL_GATE) and only
#     when the answer survives different episode-grouping gaps.
#   * Cross-series pairs use fixed percentile bands, not today's exact
#     values -- exact thresholds make "never before" happen by construction.
#   * Inversion track records count cycles, not fragments.
# Every number is computed from data/history/*.csv; nothing is recalled (§4C).
# ---------------------------------------------------------------------------

GAP_SENSITIVITY_DAYS = (90, 180, 365)
TAIL_GATE = 80                 # ext = max(|p_all-50|, |p_30-50|) + 50
SUSTAINED_MIN_OBS = 20         # a "sustained" stretch, vs a brief touch
TRACK_MIN_OBS = 10             # shorter stretches are blips, not events
TRACK_MAX_YEARS = 5            # longer stretches are regimes, not events
NBER_LAG_MONTHS = 12           # NBER dates recessions months after the fact
RECESSION_WINDOW_MONTHS = 24
INVERSION_MERGE_DAYS = 365
INVERSION_MIN_SESSIONS = 10
INVERSION_MIN_TROUGH_PP = 0.10
INVERSION_WINDOW_MONTHS = 36
PAIR_BANDS = (10, 20, 25)      # 10 is primary; 20/25 are robustness checks
SIMILAR_PCT_PTS = 15
SMALL_N = 5


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
    seen, uniq = set(), []
    for e in out:  # the GFC appears in both lists; keep one
        if e["name"] in seen:
            continue
        seen.add(e["name"])
        uniq.append(e)
    return uniq


def _add_months(date_str, months):
    d = dt.date.fromisoformat(date_str)
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day).isoformat()


def _months_between(a, b):
    da, db = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return (db.year - da.year) * 12 + (db.month - da.month)


def _value_on_or_after(rows, date_str):
    for d, v in rows:
        if d >= date_str:
            return d, v
    return None


def _value_on_or_before(rows, date_str):
    best = None
    for d, v in rows:
        if d > date_str:
            break
        best = (d, v)
    return best


def _years_between(a, b):
    return round((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
                 / 365.25, 1)


def _returns(rows):
    return [(rows[i][0], rows[i][1] / rows[i - 1][1] - 1.0)
            for i in range(1, len(rows)) if rows[i - 1][1] > 0 and rows[i][1] > 0]


def _quantile(sorted_vals, p):
    idx = min(len(sorted_vals) - 1, max(0, round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


# ---- outcomes, always against the normal rate ----------------------------

def _usrec_last():
    return _load_raw("usrec")[-1][0]


def _judgeable_through():
    """Last date a recession outcome can be called (NBER's announcement lag)."""
    return _add_months(_usrec_last(), -NBER_LAG_MONTHS)


def _in_recession(date_str):
    for r in _load_episodes()["recessions"]:
        if r["start"] <= date_str < _add_months(r["end"], 1):
            return r
    return None


def _recession_starting_in(lo, hi, inclusive_lo=False):
    for r in sorted(_load_episodes()["recessions"], key=lambda r: r["start"]):
        if (lo <= r["start"] if inclusive_lo else lo < r["start"]) and r["start"] <= hi:
            return r
    return None


def recession_outcome(entry, window_months=RECESSION_WINDOW_MONTHS):
    """'in_progress' | 'yes' | 'pending' | 'no' for an entry date."""
    cur = _in_recession(entry)
    if cur:
        return {"status": "in_progress", "recession": cur["name"]}
    r = _recession_starting_in(entry, _add_months(entry, window_months))
    if r:
        return {"status": "yes", "recession": r["name"],
                "months_after": _months_between(entry, r["start"])}
    if _add_months(entry, window_months) > _judgeable_through():
        return {"status": "pending"}
    return {"status": "no"}


def _spx_rows(as_of, live_rows=None):
    rows = [r for r in _load_raw(MARKET_SOURCES["spx"]["file"]) if r[0] <= as_of]
    return _merge_live(rows, live_rows, as_of)


def _merge_live(rows, live_rows, as_of):
    """History files are refreshed monthly. Where the live daily series
    (macro_series.csv -- the numbers the brief quotes) covers a date, it
    wins: that fills days after the file ends, and it replaces any file row
    the live series disagrees with (a partial intraday bar, or a futures
    history Yahoo revised after a contract roll), so "this year" in the
    history tables always matches the recap strip."""
    if not live_rows:
        return rows
    live = {d: v for d, v in live_rows if d <= as_of}
    merged = {d: v for d, v in rows}
    merged.update(live)
    return sorted(merged.items())


def spx_forward(entry, as_of, months=12, live_rows=None):
    """S&P 500 price return and worst drawdown over `months` from entry.
    None while the window is still open."""
    try:
        rows = _spx_rows(as_of, live_rows)
    except FileNotFoundError:
        return None  # optional context: a missing S&P file must not sink the lookback
    start = _value_on_or_after(rows, entry)
    end_d = _add_months(entry, months)
    if not start or end_d > as_of:
        return None
    end = _value_on_or_after(rows, end_d)
    if not end:
        return None
    peak, worst = start[1], 0.0
    for d, v in rows:
        if start[0] <= d <= end[0]:
            peak = max(peak, v)
            worst = min(worst, v / peak - 1.0)
    return {"return_pct": round(100.0 * (end[1] / start[1] - 1.0), 1),
            "worst_drawdown_pct": round(100.0 * worst, 1)}


def outcomes_from(entry, as_of):
    out = {"entry": entry,
           "spx_12m": spx_forward(entry, as_of),
           "recession_24m": recession_outcome(entry)}
    try:
        ff = _load_raw("dff")
        f0 = _value_on_or_before(ff, entry)
        f1 = _value_on_or_before(ff, _add_months(entry, 12))
        if f0:
            out["fed_funds_at_entry"] = round(f0[1], 2)
        if f0 and f1 and _add_months(entry, 12) <= as_of:
            out["fed_funds_change_next_12m"] = round(f1[1] - f0[1], 2)
    except FileNotFoundError:
        pass
    return out


def summarize_track(track):
    n = len(track)
    spx = [t["spx_12m"]["return_pct"] for t in track if t.get("spx_12m")]
    rec = [t["recession_24m"]["status"] for t in track]
    s = {"n": n, "small_n": n < SMALL_N,
         "n_spx_known": len(spx),
         "n_spx_negative": sum(1 for r in spx if r < 0),
         "n_recession_yes": rec.count("yes"), "n_recession_no": rec.count("no"),
         "n_recession_pending": rec.count("pending"),
         "n_recession_in_progress": rec.count("in_progress")}
    if spx and n >= SMALL_N:
        s["spx_12m_median_pct"] = round(statistics.median(spx), 1)
    return s


def base_rates(as_of):
    """Normal rates to set every track record against: the share of months
    in which a recession began within W months, and the S&P 500's ordinary
    12-month price return from a month-end."""
    key = ("_base_rates", as_of)
    if key in _cache:
        return _cache[key]
    cut = _judgeable_through()
    out = {"recession_starts_within": {}, "spx_12m": {},
           "judgeable_through": cut}
    for since in (1948, 1962, 1983):
        for w in (12, 24, 36):
            hits = n = 0
            t = f"{since}-01-01"
            while _add_months(t, w) <= cut:
                n += 1
                if _recession_starting_in(t, _add_months(t, w), inclusive_lo=True):
                    hits += 1
                t = _add_months(t, 1)
            out["recession_starts_within"][f"{w}m_since_{since}"] = (
                round(100.0 * hits / n, 1) if n else None)
    try:
        rows = _spx_rows(as_of)
        month_end = {}
        for d, v in rows:
            month_end[d[:7]] = (d, v)
        ends = sorted(month_end.values())
        for since in (1928, 1962):
            rets = []
            for d, v in ends:
                if int(d[:4]) < since or _add_months(d, 12) > as_of:
                    continue
                fwd = _value_on_or_after(rows, _add_months(d, 12))
                if fwd:
                    rets.append(fwd[1] / v - 1.0)
            if rets:
                out["spx_12m"][f"since_{since}"] = {
                    "median_pct": round(100.0 * statistics.median(rets), 1),
                    "share_negative_pct": round(100.0 * sum(1 for r in rets if r < 0) / len(rets), 1),
                    "n_months": len(rets)}
    except FileNotFoundError:
        pass
    _cache[key] = out
    return out


# ---- "last time it was here" ---------------------------------------------

def lookback(rows, value, as_of, p_all, p_30=None, short=False):
    """The last time before the current run the series was at least this
    high (or low) -- tail-gated, gap-robust, touch vs. sustained, with the
    current run's own extreme checked so "highest since" is never claimed
    for a reading below this run's peak."""
    ext_all = abs(p_all - 50)
    ext_30 = abs(p_30 - 50) if p_30 is not None else -1
    p_x = p_all if ext_all >= ext_30 else p_30
    side = "high" if p_x >= 50 else "low"
    ext = round(max(ext_all, ext_30) + 50, 1)
    rows = [r for r in rows if r[0] < as_of] + [(as_of, value)]
    out = {"ext": ext, "side": side, "gated": ext >= TAIL_GATE and not short,
           "short_history": short, "history_start": rows[0][0],
           "history_years": _years_between(rows[0][0], as_of)}

    ends = {}
    for g in GAP_SENSITIVITY_DAYS:
        eps_g = group_episodes(rows, value, side, g)
        ends[g] = eps_g[-2]["end"] if len(eps_g) >= 2 else None
    present = [e for e in ends.values() if e]
    if not present:
        sensitive = False
    elif len(present) < len(ends):
        sensitive = True
    else:
        sensitive = (dt.date.fromisoformat(max(present))
                     - dt.date.fromisoformat(min(present))).days > 365
    out["gap_sensitive"] = sensitive
    out["prior_end_by_gap_days"] = {str(g): ends[g] for g in GAP_SENSITIVITY_DAYS}

    eps = group_episodes(rows, value, side, EPISODE_GAP_DAYS)
    cur, priors = eps[-1], eps[:-1]
    in_run = [(d, v) for d, v in rows if d >= cur["start"]]
    pick = max if side == "high" else min
    rx_d, rx_v = pick(in_run, key=lambda r: r[1])
    out["current_run_start"] = cur["start"]
    out["current_run_sessions"] = cur["n_obs"]
    out["run_extreme"] = round(rx_v, 4)
    out["run_extreme_date"] = rx_d
    out["today_is_run_extreme"] = (value >= rx_v - 1e-9) if side == "high" \
        else (value <= rx_v + 1e-9)
    if not out["today_is_run_extreme"]:
        eps_x = group_episodes(rows, rx_v, side, EPISODE_GAP_DAYS)
        px = eps_x[-2] if len(eps_x) >= 2 else None
        out["run_extreme_prior"] = ({"end": px["end"], "n_obs": px["n_obs"],
                                     "years_since": _years_between(px["end"], as_of)}
                                    if px else None)

    if priors:
        p = priors[-1]
        out["last_touch"] = {
            "start": p["start"], "end": p["end"], "n_obs": p["n_obs"],
            "extreme": round(p["extreme"], 4), "extreme_date": p["extreme_date"],
            "years_since": _years_between(p["end"], as_of),
            "overlapping": [o["name"] for o in _overlapping_named(
                max(p["start"], _add_months(p["end"], -12)), p["end"])]}
        sus = next((e for e in reversed(priors)
                    if e["n_obs"] >= SUSTAINED_MIN_OBS), None)
        out["last_sustained"] = ({"start": sus["start"], "end": sus["end"],
                                  "n_obs": sus["n_obs"],
                                  "years_since": _years_between(sus["end"], as_of)}
                                 if sus else None)
    else:
        out["last_touch"] = out["last_sustained"] = None
    out["record"] = (not priors and not short and out["history_years"] >= 20)

    track, n_blips, n_regimes = [], 0, 0
    for e in priors:
        if e["n_obs"] < TRACK_MIN_OBS:
            n_blips += 1
            continue
        if _years_between(e["start"], e["end"]) > TRACK_MAX_YEARS:
            n_regimes += 1
            continue
        t = outcomes_from(e["start"], as_of)
        t.update({"end": e["end"], "n_obs": e["n_obs"],
                  "overlapping": [o["name"] for o in _overlapping_named(e["start"], e["end"])]})
        track.append(t)
    out["track"] = track
    out["track_summary"] = summarize_track(track)
    out["track_excluded"] = {"blips_under_min_obs": n_blips,
                             "regimes_over_max_years": n_regimes}
    return out


# ---- the speed of a move: rate shocks and year-to-date pace ---------------

def _change_series(rows, days=365):
    """[(date, value - value at the last obs on or before date - days)]."""
    out, j = [], 0
    dates = [d for d, _ in rows]
    for i, (d, v) in enumerate(rows):
        target = (dt.date.fromisoformat(d) - dt.timedelta(days=days)).isoformat()
        while j + 1 < len(rows) and dates[j + 1] <= target:
            j += 1
        if dates[j] <= target:
            out.append((d, v - rows[j][1]))
    return out


def rate_shock(key, live_value, as_of):
    """How big is the 12-month rise (or fall), how often has a move this size
    happened, and -- measured from each past shock's first day -- what came
    after, against the normal rate. n is usually 10+, so this is the honest
    track record for a rate move (a level's own track is often 1-2 cases)."""
    rows, _ = _series_for(key)
    rows = [r for r in rows if r[0] < as_of] + [(as_of, live_value)]
    ch = _change_series(rows)
    if not ch:
        return None
    c_today = ch[-1][1]
    side = "high" if c_today >= 0 else "low"
    hist = ch[:-1]
    share = 100.0 * sum(1 for _, c in hist if _qualifies(c, c_today, side)) / len(hist)
    eps = group_episodes(ch, c_today, side, EPISODE_GAP_DAYS)
    cur, priors = eps[-1], [e for e in eps[:-1] if e["n_obs"] >= TRACK_MIN_OBS]
    track = []
    for e in priors:
        t = outcomes_from(e["start"], as_of)
        lvl = _value_on_or_before(rows, e["start"])
        t.update({"end": e["end"], "n_obs": e["n_obs"],
                  "change_at_extreme_pp": round(e["extreme"], 2),
                  "level_at_entry": round(lvl[1], 2) if lvl else None,
                  "overlapping": [o["name"] for o in _overlapping_named(e["start"], e["end"])]})
        track.append(t)
    return {"change_12m_pp": round(c_today, 2), "side": side,
            "share_of_days_pct": round(share, 1),
            "history_start": ch[0][0], "current_run_start": cur["start"],
            "track": track, "track_summary": summarize_track(track)}


def ytd_rank(rows, live_value, as_of, mode):
    """This year's change through today's calendar date, ranked against every
    prior year through the same date. mode 'bp' (rates: keeps negative
    bases, e.g. sub-zero real yields) or 'pct' (prices: skips bases <= 0)."""
    rows = [r for r in rows if r[0] < as_of] + [(as_of, live_value)]
    md = as_of[5:]
    year_last, upto = {}, {}
    for d, v in rows:
        y = int(d[:4])
        year_last[y] = (d, v)
        if d[5:] <= md:
            upto[y] = (d, v)
    first_year = int(rows[0][0][:4])
    # a year that hadn't traded yet by an early-January date counts as
    # unchanged (0% / 0bp) -- dropping it would quietly shrink the sample
    if md <= "01-10":
        for y in {int(d[:4]) for d, _ in rows}:
            if y not in upto and y - 1 in year_last:
                upto[y] = (f"{y}-{md}", year_last[y - 1][1])
    changes = {}
    for y, (d, v) in upto.items():
        if y == first_year or y - 1 not in year_last:
            continue
        # the year's last obs on/before the date must be close to the date
        # (guards years with a data hole, e.g. the excluded 30Y window)
        target = dt.date.fromisoformat(f"{y}-{md}") if md != "02-29" else dt.date(y, 2, 28)
        if (target - dt.date.fromisoformat(d)).days > 10:
            continue
        base_d, base = year_last[y - 1]
        if (dt.date.fromisoformat(f"{y}-01-01") - dt.date.fromisoformat(base_d)).days > 10:
            continue  # prior year's data ends early (hole) -> no clean base
        if mode == "pct":
            if base <= 0:
                continue
            changes[y] = 100.0 * (v / base - 1.0)
        else:
            changes[y] = 100.0 * (v - base)  # basis points
    this_y = int(as_of[:4])
    if this_y not in changes:
        return None
    today = changes[this_y]
    prior = {y: c for y, c in changes.items() if y < this_y}
    up = today >= 0
    beyond = sorted(((y, c) for y, c in prior.items() if (c > today if up else c < today)),
                    key=lambda x: -x[1] if up else x[1])
    return {"mode": mode, "change": round(today, 2 if mode == "pct" else 0),
            "direction": "up" if up else "down",
            "rank": 1 + len(beyond), "n_years": len(prior) + 1,
            "first_year": min(changes),
            "median_prior": round(statistics.median(prior.values()), 2) if prior else None,
            "years_more_extreme": [{"year": y, "change": round(c, 2 if mode == "pct" else 0)}
                                   for y, c in beyond[:8]]}


def daily_change_rank(rows, live_change, as_of, scale=100.0):
    """How often has a one-day move at least this large happened (absolute,
    consecutive observations no more than 5 calendar days apart)?"""
    rows = [r for r in rows if r[0] < as_of]
    moves = []
    for i in range(1, len(rows)):
        if (dt.date.fromisoformat(rows[i][0]) - dt.date.fromisoformat(rows[i - 1][0])).days > 5:
            continue
        moves.append((rows[i][0], scale * (rows[i][1] - rows[i - 1][1])))
    if not moves:
        return None
    t = abs(scale * live_change)
    share = sum(1 for _, m in moves if abs(m) >= t - 1e-9) / len(moves)
    start_30 = (dt.date.fromisoformat(as_of)
                - dt.timedelta(days=round(MODERN_WINDOW_YEARS * 365.25))).isoformat()
    m30 = [m for d, m in moves if d >= start_30]
    share_30 = sum(1 for m in m30 if abs(m) >= t - 1e-9) / len(m30) if m30 else None
    return {"move": round(scale * live_change, 1),
            "share_at_least_this_big_pct": round(100.0 * share, 1),
            "share_at_least_this_big_30y_pct": round(100.0 * share_30, 1) if share_30 is not None else None,
            "one_in_n_days": round(1.0 / share) if share > 0 else None,
            "history_start": moves[0][0]}


# ---- cross-series pairs on fixed percentile bands -------------------------

def _derived_rows(key, as_of=None):
    """Rows for a pair/then-vs-now key: any SOURCES key, plus spx_dd (S&P 500
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


def pair_bands(a, side_a, b, side_b, as_of, latest=None):
    """Were both series in the same extreme bands at once, and when last?
    Bands are fixed percentiles of each series over the shared sample (10/90
    primary; 20/80 and 25/75 as robustness checks) -- never today's exact
    values. Reports the joint share against the share expected if the two
    were unrelated, so a pair only reads as rare when the combination is."""
    latest = latest or {}
    sa, sb = dict(_derived_rows(a, as_of)), dict(_derived_rows(b, as_of))
    if not sa or not sb:
        return None
    ta = latest.get(a) or (max(sa), sa[max(sa)])
    tb = latest.get(b) or (max(sb), sb[max(sb)])
    hist = sorted(d for d in set(sa) & set(sb) if d < as_of)
    if not hist:
        return None
    dates = hist + [as_of]
    sa[as_of], sb[as_of] = ta[1], tb[1]
    va, vb = sorted(sa[d] for d in dates), sorted(sb[d] for d in dates)
    starts = {a: min(_derived_rows(a, as_of))[0], b: min(_derived_rows(b, as_of))[0]}
    out = {"a": a, "side_a": side_a, "b": b, "side_b": side_b,
           "today": {a: {"obs_date": ta[0], "value": round(ta[1], 4)},
                     b: {"obs_date": tb[0], "value": round(tb[1], 4)}},
           "shared_history_start": dates[0], "n_days": len(dates),
           "window_limited_by": max(starts, key=starts.get), "bands": {}}
    for band in PAIR_BANDS:
        thr_a = _quantile(va, 100 - band if side_a == "high" else band)
        thr_b = _quantile(vb, 100 - band if side_b == "high" else band)
        qa = {d for d in dates if _qualifies(sa[d], thr_a, side_a)}
        qb = {d for d in dates if _qualifies(sb[d], thr_b, side_b)}
        q = sorted(qa & qb)
        eps = group_episodes([(d, 1.0) for d in q], 1.0, "high", EPISODE_GAP_DAYS)
        cur = eps[-1] if eps and eps[-1]["end"] == as_of else None
        priors = [e for e in eps if e is not cur and e["n_obs"] >= SUSTAINED_MIN_OBS]
        share = len(q) / len(dates)
        exp = (len(qa) / len(dates)) * (len(qb) / len(dates))
        out["bands"][str(band)] = {
            "threshold_a": round(thr_a, 4), "threshold_b": round(thr_b, 4),
            "share_pct": round(100.0 * share, 2),
            "expected_if_unrelated_pct": round(100.0 * exp, 2),
            "ratio_vs_unrelated": round(share / exp, 2) if exp else None,
            "today_in_band": as_of in q,
            "current_run_start": cur["start"] if cur else None,
            "n_prior_stretches": len(priors),
            "prior": ({"start": priors[-1]["start"], "end": priors[-1]["end"],
                       "n_obs": priors[-1]["n_obs"],
                       "years_since": _years_between(priors[-1]["end"], as_of)}
                      if priors else None),
            "_priors": priors,
        }
    p_ends = [out["bands"][str(b_)]["prior"]["end"] if out["bands"][str(b_)]["prior"] else None
              for b_ in PAIR_BANDS]
    if all(p_ends):
        out["stable_prior"] = (dt.date.fromisoformat(max(p_ends))
                               - dt.date.fromisoformat(min(p_ends))).days <= 365
    else:
        out["stable_prior"] = not any(p_ends)
    primary = out["bands"][str(PAIR_BANDS[0])]
    track = []
    for e in primary["_priors"]:
        if _years_between(e["start"], e["end"]) > TRACK_MAX_YEARS:
            continue
        t = outcomes_from(e["start"], as_of)
        t.update({"end": e["end"], "n_obs": e["n_obs"],
                  "overlapping": [o["name"] for o in _overlapping_named(e["start"], e["end"])]})
        track.append(t)
    for b_ in out["bands"].values():
        b_.pop("_priors")
    out["track"] = track
    out["track_summary"] = summarize_track(track)
    out["never_before_allowed"] = (all(out["bands"][str(b_)]["n_prior_stretches"] == 0
                                       for b_ in PAIR_BANDS)
                                   and _years_between(dates[0], as_of) >= 30)
    return out


# ---- curve inversions as cycles, not fragments ----------------------------

def inversion_cycles(key, as_of):
    rows = [r for r in _series_for(key)[0] if r[0] <= as_of]
    runs, cur = [], None
    for d, v in rows:
        if v < 0:
            if cur is None:
                cur = {"start": d, "end": d, "sessions": 0, "trough": v, "trough_date": d}
                runs.append(cur)
            cur["end"] = d
            cur["sessions"] += 1
            if v < cur["trough"]:
                cur["trough"], cur["trough_date"] = v, d
        else:
            cur = None
    cycles = []
    for r in runs:
        if cycles and (dt.date.fromisoformat(r["start"])
                       - dt.date.fromisoformat(cycles[-1]["end"])).days <= INVERSION_MERGE_DAYS:
            c = cycles[-1]
            c["end"] = r["end"]
            c["sessions"] += r["sessions"]
            c["fragments"] += 1
            if r["trough"] < c["trough"]:
                c["trough"], c["trough_date"] = r["trough"], r["trough_date"]
        else:
            cycles.append(dict(r, fragments=1))
    cut = _judgeable_through()
    used = set()
    out = []
    for c in cycles:
        if c["sessions"] < INVERSION_MIN_SESSIONS or c["trough"] > -INVERSION_MIN_TROUGH_PP:
            continue
        s = c["start"]
        rec_now = _in_recession(s)
        rec = _recession_starting_in(s, _add_months(s, INVERSION_WINDOW_MONTHS))
        if rec_now:
            status = "began_in_recession"
        elif rec:
            status = "followed"
        elif _add_months(s, INVERSION_WINDOW_MONTHS) > cut:
            status = "pending"
        else:
            status = "not_followed"
        rec_d = {}
        if status == "followed":
            rec_d = {"recession": rec["name"],
                     "months_from_start": _months_between(s, rec["start"]),
                     "months_from_uninversion": _months_between(c["end"], rec["start"]),
                     "same_recession_as_earlier_cycle": rec["name"] in used}
            used.add(rec["name"])
        out.append({"start": s, "end": c["end"], "sessions": c["sessions"],
                    "fragments": c["fragments"],
                    "trough_bp": round(c["trough"] * 100), "trough_date": c["trough_date"],
                    "ongoing": c["end"] == rows[-1][0], "status": status, **rec_d})
    counted = [c for c in out if c["status"] in ("followed", "not_followed")]
    latest = out[-1] if out else None
    return {
        "history_start": rows[0][0], "cycles": out,
        "n_judged": len(counted),
        "n_followed": sum(1 for c in counted if c["status"] == "followed"),
        "n_not_followed": sum(1 for c in counted if c["status"] == "not_followed"),
        "n_pending": sum(1 for c in out if c["status"] == "pending"),
        "n_began_in_recession": sum(1 for c in out if c["status"] == "began_in_recession"),
        "base_rate_36m_pct": base_rates(as_of)["recession_starts_within"]["36m_since_1948"],
        "latest_cycle_end": latest["end"] if latest else None,
        "months_since_latest_cycle_end": (_months_between(latest["end"], as_of)
                                          if latest and not latest["ongoing"] else None),
    }


# ---- price series: return-based context -----------------------------------

def market_context(key, as_of, live_rows=None):
    """How unusual today's move is, the last bigger one, how this year
    compares with every prior year through the same date, and (S&P) the
    worst pullback so far this year vs. a typical year. A level percentile
    is never given for a trending price."""
    if key not in MARKET_SOURCES:
        return None
    src = MARKET_SOURCES[key]
    rows = [r for r in _load_raw(src["file"]) if r[0] <= as_of]
    rows = _merge_live(rows, live_rows, as_of)
    if len(rows) < 260 or rows[-1][0] != as_of:
        return None
    rets = []
    for i in range(1, len(rows)):
        if rows[i - 1][1] <= 0 or rows[i][1] <= 0:
            continue
        if (dt.date.fromisoformat(rows[i][0]) - dt.date.fromisoformat(rows[i - 1][0])).days > 5:
            continue
        rets.append((rows[i][0], rows[i][1] / rows[i - 1][1] - 1.0))
    if not rets or rets[-1][0] != as_of:
        return None
    today_ret, hist = rets[-1][1], rets[:-1]
    down = today_ret < 0

    def big(r):
        return r <= today_ret if down else r >= today_ret

    start_30 = (dt.date.fromisoformat(as_of)
                - dt.timedelta(days=round(MODERN_WINDOW_YEARS * 365.25))).isoformat()
    hist_30 = [(d, r) for d, r in hist if d >= start_30]
    years = _years_covered(rows)
    win = min(MODERN_WINDOW_YEARS, years)
    n_30 = sum(1 for _, r in hist_30 if big(r))
    share_30 = 100.0 * n_30 / len(hist_30) if hist_30 else None
    last_big = next(((i, d, r) for i, (d, r) in reversed(list(enumerate(hist))) if big(r)), None)
    ytd_count = sum(1 for d, r in rets if d[:4] == as_of[:4] and big(r))

    peak = peak_date = None
    for d, v in rows:
        if peak is None or v >= peak:
            peak, peak_date = v, d
    dd_today = 100.0 * (rows[-1][1] / peak - 1.0)

    out = {
        "label": src["label"], "as_of": as_of, "history_start": rows[0][0],
        "years": years,
        "move": {
            "pct": round(100.0 * today_ret, 3),
            "direction": "down" if down else "up",
            "share_days_at_least_this_big_all_pct": round(100.0 * sum(1 for _, r in hist if big(r)) / len(hist), 2),
            "share_days_at_least_this_big_recent_pct": round(share_30, 2) if share_30 is not None else None,
            "per_year_recent": round(n_30 / win, 1) if hist_30 else None,
            "recent_window_years": win,
            # gate: only a move in the most extreme ~15% of same-direction
            # days over the recent window earns a sentence in prose
            "in_tail": share_30 is not None and share_30 <= 15.0,
            "count_this_year_incl_today": ytd_count,
            "last_at_least_this_big": ({"date": last_big[1], "pct": round(100.0 * last_big[2], 3),
                                        "sessions_ago": len(hist) - last_big[0]}
                                       if last_big else None),
        },
        "record": {"pct_below_record": round(dd_today, 3), "record_close": round(peak, 4),
                   "record_date": peak_date,
                   # a record more than 10 years old isn't a useful yardstick
                   "stale": _years_between(peak_date, as_of) > 10},
        "ytd": ytd_rank(rows[:-1], rows[-1][1], as_of, "pct"),
    }
    if key == "spx":
        out["pullback"] = _intra_year_pullback(rows, as_of)
    return out


def _intra_year_pullback(rows, as_of):
    """Worst peak-to-trough decline so far this calendar year (the running
    peak starts at the prior year-end close), vs. every full year."""
    by_year = {}
    for d, v in rows:
        by_year.setdefault(int(d[:4]), []).append((d, v))
    years = sorted(by_year)

    def worst(y):
        if y - 1 not in by_year:
            return None
        peak_d, peak = by_year[y - 1][-1]
        w, wp, wt = 0.0, None, None
        for d, v in by_year[y]:
            if v > peak:
                peak, peak_d = v, d
            dd = v / peak - 1.0
            if dd < w:
                w, wp, wt = dd, peak_d, d
        return w, wp, wt

    this_y = int(as_of[:4])
    cur = worst(this_y)
    full = {y: worst(y)[0] for y in years if y < this_y and worst(y)}

    def stats(since):
        ws = sorted(v for y, v in full.items() if y >= since)
        if not ws:
            return None
        return {"n_years": len(ws), "median_pct": round(100.0 * statistics.median(ws), 1),
                "n_10pct_or_worse": sum(1 for v in ws if v <= -0.10),
                "n_20pct_or_worse": sum(1 for v in ws if v <= -0.20)}
    return {"this_year_worst_pct": round(100.0 * cur[0], 2) if cur else None,
            "peak_date": cur[1] if cur else None, "trough_date": cur[2] if cur else None,
            "since_1929": stats(1929), "since_1950": stats(1950)}


# ---- then vs. now ---------------------------------------------------------

THEN_NOW_ROWS = [
    ("ust_10y", "10Y Treasury", "pct"), ("dff", "Fed funds (now: SOFR)", "pct"),
    ("s2s10", "2s10s curve", "bp"), ("s3m10y", "3m10y curve", "bp"),
    ("tips_10y_real", "10Y real yield (TIPS)", "pct"),
    ("bkeven_10y", "10Y breakeven", "pct"),
    ("kw_tp10", "Term premium (Kim-Wright model)", "pct"),
    ("baa_10y_spread", "Baa − 10Y (IG credit proxy)", "pp"),
    ("spx_dd", "S&P 500 from record", "pctpt"),
    ("mortgage30", "30Y mortgage rate", "pct"),
]


def then_vs_now(then_date, as_of, now_values):
    """Fixed panel: each row's reading on then_date (nearest obs on or before,
    within 45 days) vs. now, with each reading's own-history percentile and
    a mechanical similar/different call."""
    out = []
    for key, label, unit in THEN_NOW_ROWS:
        try:
            rows = (_load_raw("dff") if key == "dff" else _derived_rows(key, as_of))
        except (FileNotFoundError, KeyError):
            continue
        rows = [r for r in rows if r[0] <= as_of]
        if not rows:
            continue
        then = _value_on_or_before(rows, then_date)
        if then and (dt.date.fromisoformat(then_date) - dt.date.fromisoformat(then[0])).days > 45:
            then = None
        now = now_values.get(key) or (rows[-1][0], rows[-1][1])
        pct_then = _percentile_rank(rows, then[1]) if then else None
        pct_now = _percentile_rank(rows, now[1])
        out.append({"key": key, "label": label, "unit": unit,
                    "then": ({"date": then[0], "value": round(then[1], 4)} if then else None),
                    "now": {"date": now[0], "value": round(now[1], 4)},
                    "pct_then": pct_then, "pct_now": pct_now,
                    "similar": (abs(pct_then - pct_now) <= SIMILAR_PCT_PTS
                                if pct_then is not None else None)})
    return {"then_date": then_date, "rows": out}


# ---- Unit 7: the financing-cycle map --------------------------------------

def _ratio_rows(num_key, den_key, scale):
    num, den = dict(_load_raw(num_key)), dict(_load_raw(den_key))
    return [(d, scale * num[d] / den[d]) for d in sorted(set(num) & set(den)) if den[d]]


def _three_year_returns(rows):
    out, j = [], 0
    for i, (d, v) in enumerate(rows):
        target = (dt.date.fromisoformat(d) - dt.timedelta(days=round(3 * 365.25))).isoformat()
        while j + 1 < len(rows) and rows[j + 1][0] <= target:
            j += 1
        if rows[j][0] <= target and rows[j][1] > 0:
            out.append((d, 100.0 * (v / rows[j][1] - 1.0)))
    return out


def _window_peak(rows, lo, hi):
    w = [(d, v) for d, v in rows if lo <= d <= hi]
    return max(w, key=lambda r: r[1]) if w else None


def cycle_map(as_of, live=None):
    """Aggregate gauges for locating the AI capex cycle against the 2000 and
    2007 peaks -- cycle level only (§8). Quarterly series arrive about a
    quarter late and are revised; nonfinancial corporate debt misses private
    credit and off-balance-sheet structures, where much data-center
    financing sits."""
    live = live or {}
    out = {"gauges": [], "returns_3y": []}
    specs = [("it_capex_share_gdp", "IT equipment + software investment, % of GDP",
              "it_invest", "gdp", 100.0),
             ("nfc_equity_gdp", "Nonfinancial corporate equities, % of GDP",
              "nfc_equity", "gdp", 0.1),
             ("nfc_debt_gdp", "Nonfinancial corporate debt, % of GDP",
              "nfc_debt", "gdp", 0.1)]
    for gid, label, num, den, scale in specs:
        try:
            rows = [r for r in _ratio_rows(num, den, scale) if r[0] <= as_of]
        except FileNotFoundError:
            continue
        if not rows:
            continue
        d, v = rows[-1]
        prior = rows[:-1]
        pk00 = _window_peak(rows, "1997-01-01", "2001-12-31")
        pk07 = _window_peak(rows, "2005-01-01", "2008-12-31")
        lb = group_episodes(rows, v, "high", 400)
        out["gauges"].append({
            "id": gid, "label": label, "latest_quarter": d, "value": round(v, 2),
            "pct_rank_all_time": _percentile_rank(rows, v),
            "history_start": rows[0][0],
            "is_record": bool(prior) and v >= max(p for _, p in prior),
            "max_before": round(max(p for _, p in prior), 2) if prior else None,
            "max_before_date": max(prior, key=lambda r: r[1])[0] if prior else None,
            "peak_1997_2001": {"date": pk00[0], "value": round(pk00[1], 2)} if pk00 else None,
            "peak_2005_2008": {"date": pk07[0], "value": round(pk07[1], 2)} if pk07 else None,
            "last_this_high_before_run": lb[-2]["end"] if len(lb) >= 2 else None,
        })
    for key in ("spx", "ndx"):
        try:
            rows = [r for r in _load_raw(MARKET_SOURCES[key]["file"]) if r[0] <= as_of]
        except FileNotFoundError:
            continue
        rows = _merge_live(rows, live.get(key), as_of)
        r3 = _three_year_returns(rows)
        if not r3 or r3[-1][0] != as_of:
            continue
        d, v = r3[-1]
        pk = _window_peak(r3, "1997-01-01", "2000-12-31")
        out["returns_3y"].append({
            "key": key, "label": MARKET_SOURCES[key]["label"], "as_of": d,
            "three_year_return_pct": round(v, 1),
            "pct_rank_all_time": _percentile_rank(r3, v),
            "history_start": r3[0][0],
            "peak_1997_2000": {"date": pk[0], "value": round(pk[1], 1)} if pk else None})
    return out


# ---- one-glance label ------------------------------------------------------

def lately_vs_history(z120, z_thin, ext, short):
    """Script words for 'is this flag this year's noise or a decades-level
    reading?' -- never typed by the model."""
    if short:
        return "3-yr record only"
    loud = (z120 is not None) and (not z_thin) and abs(z120) >= 1.5
    tail = ext is not None and ext >= TAIL_GATE
    if loud and tail:
        return "unusual lately and historically"
    if loud:
        return "unusual lately, ordinary historically"
    if tail:
        return "quiet lately, historically extreme"
    return "ordinary"
