#!/usr/bin/env python3
"""compute_state.py — the quantitative state the narrative is downstream of (§3.4).

Reads data/macro_series.csv, computes for every tracked series:
  d1      1-day delta (last vs. previous non-null observation)
  d5      5-day delta (last vs. 5 non-null observations back)
  trend20 direction of the 20-observation change: up / down / flat
          (flat when |change| < 0.25 sigma of the 20-obs daily diffs)
  z120    z-score of the latest level vs. the trailing 120 prior non-null
          observations (excluding the latest). Needs >= 60 prior observations
          (§4 seasoning rule); below that it is null and labeled thin.
  flag    |z120| >= 1.5 (§3.4)

Derived series computed here (not stored in the CSV): 2s10s and 3m10y curve
slopes (bp), SPX distance from all-time closing high, YTD changes for the
recap strip (vs. the last observation of the prior calendar year).

Output: data/state.json (machine), and a human-readable table on stdout.
No prose number may appear in a brief unless it exists here or in the day's
raw pull (§4C).
"""

import csv
import datetime as dt
import json
import math
import sys
from pathlib import Path

import history_context as hc

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "macro_series.csv"
ATH_PATH = REPO / "data" / "spx_ath.json"
STATE_PATH = REPO / "data" / "state.json"
HIST_DIR = REPO / "data" / "history"

# Tier 1 keys with real long-run history (§4F, added 2026-10-08 — Jacob: a
# "widest/highest this system has tracked" claim against ~10 months of data
# is true but misleading; this pairs every such series with where it sits
# against real history, computed from data/history/*.csv, never recalled.
# bp_to_pct: state.json stores these two curve series in bp; the long-history
# files are in percentage points, so divide by 100 before comparing.
LONG_HISTORY_KEYS = {
    "ust_3m": {}, "ust_2y": {}, "ust_10y": {}, "ust_30y": {},
    "tips_10y_real": {}, "bkeven_10y": {}, "sofr": {},
    "hy_oas": {}, "ig_oas": {},
    "s2s10": {"bp_to_pct": True}, "s3m10y": {"bp_to_pct": True},
    "dxy": {},
}

# History v2 (§4F amendment, 2026-10-09 -- Jacob: "I still didn't see a
# deeper connection to historical context"). Reference series quoted on
# their own latest observation (not Tier 1; never fail-closed).
REFERENCE_KEYS = ["real10_cleveland", "kw_tp10", "mortgage30"]
# rate series that get a "pace" view: YTD change ranked against every year,
# and the 12-month rate-shock track record measured from each shock's start
RATE_PACE_KEYS = ["ust_2y", "ust_10y", "ust_30y", "tips_10y_real"]
# price series: return-based context (a level percentile of a trending
# price is meaningless)
MARKET_HISTORY_KEYS = ["spx", "ndx", "wti", "gold"]
# Pre-registered cross-series pairs, fixed percentile bands. Small on
# purpose: every extra pair is another lottery ticket for a spurious
# "only other time". Change only at monthly review.
HISTORY_PAIRS = {
    "real_rates_vs_credit": ("tips_10y_real", "high", "baa_10y_spread", "low"),
}

SEASONING_MIN = 60      # §4: no z asserted below this many prior observations
Z_WINDOW = 120
FLAG_Z = 1.5

# how each series is quoted, for delta units in the brief
UNITS = {
    "ust_3m": "pct", "ust_2y": "pct", "ust_10y": "pct", "ust_30y": "pct",
    "tips_10y_real": "pct", "bkeven_10y": "pct", "hy_oas": "pct",
    "ig_oas": "pct", "sofr": "pct",
    "dxy": "level", "fed_bs": "musd", "on_rrp": "busd", "tga": "musd",
    "spx": "index", "ndx": "index", "rut": "index",
    "wti": "usd", "gold": "usd", "copper": "usd",
    "spy": "usd", "rsp": "usd", "smh": "usd",
}
TIER1 = ["ust_3m", "ust_2y", "ust_10y", "ust_30y", "tips_10y_real",
         "bkeven_10y", "hy_oas", "ig_oas", "dxy", "sofr", "fed_bs",
         "on_rrp", "tga"]


def series_obs(rows, col):
    """[(date, value)] of non-null observations, ascending by date."""
    out = []
    for r in rows:
        v = r.get(col, "")
        if v not in ("", None):
            out.append((r["date"], float(v)))
    return out


def mean(xs):
    return sum(xs) / len(xs)


def stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def compute_series(obs):
    """Stats for one series from its non-null observations."""
    if not obs:
        return None
    dates = [d for d, _ in obs]
    vals = [v for _, v in obs]
    last_date, last = dates[-1], vals[-1]
    out = {"last": last, "last_date": last_date, "n_obs": len(obs)}
    out["d1"] = round(last - vals[-2], 6) if len(vals) >= 2 else None
    out["d5"] = round(last - vals[-6], 6) if len(vals) >= 6 else None
    if len(vals) >= 21:
        window = vals[-21:]
        change = window[-1] - window[0]
        diffs = [window[i + 1] - window[i] for i in range(len(window) - 1)]
        eps = 0.25 * stdev(diffs)
        out["trend20"] = ("flat" if abs(change) <= eps
                          else "up" if change > 0 else "down")
    else:
        out["trend20"] = None
    prior = vals[-(Z_WINDOW + 1):-1]
    if len(prior) >= SEASONING_MIN:
        sd = stdev(prior)
        out["z120"] = round((last - mean(prior)) / sd, 3) if sd > 0 else 0.0
        out["z_thin"] = False
    else:
        out["z120"] = None
        out["z_thin"] = True
    out["flag"] = out["z120"] is not None and abs(out["z120"]) >= FLAG_Z
    return out


def ytd_change(obs, year):
    """(abs_change, pct_change) vs. last observation dated before `year`."""
    base = None
    for d, v in obs:
        if d < f"{year}-01-01":
            base = v
    if base is None:
        return None, None
    last = obs[-1][1]
    return round(last - base, 6), round(100.0 * (last - base) / base, 3)


def main():
    if not CSV_PATH.exists():
        print("no macro_series.csv — run pull_data.py first", file=sys.stderr)
        return 2
    with open(CSV_PATH, newline="") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: r["date"])
    cols = [c for c in rows[0].keys() if c != "date"]

    market_dates = [r["date"] for r in rows if r.get("spx") not in ("", None)]
    row_date = market_dates[-1] if market_dates else rows[-1]["date"]
    year = row_date[:4]

    state = {"computed_at_utc": dt.datetime.utcnow().isoformat() + "Z",
             "row_date": row_date,
             "trading_rows": len(market_dates),
             "seasoned": len(market_dates) >= SEASONING_MIN,
             "series": {}, "derived": {}, "flags": []}

    for col in cols:
        s = compute_series(series_obs(rows, col))
        if s is None:
            continue
        s["unit"] = UNITS.get(col, "level")
        a, p = ytd_change(series_obs(rows, col), year)
        s["ytd_abs"], s["ytd_pct"] = a, p
        state["series"][col] = s
        if s["flag"]:
            state["flags"].append(
                {"series": col, "z120": s["z120"], "last": s["last"],
                 "last_date": s["last_date"]})

    # derived curve slopes in bp, with their own history for z
    def derived_curve(name, a, b):
        obs_a = dict(series_obs(rows, a))
        obs_b = dict(series_obs(rows, b))
        obs = [(d, round((obs_a[d] - obs_b[d]) * 100, 2))
               for d in sorted(obs_a) if d in obs_b]
        s = compute_series(obs)
        if s:
            s["unit"] = "bp"
            state["derived"][name] = s
            if s["flag"]:
                state["flags"].append(
                    {"series": name, "z120": s["z120"], "last": s["last"],
                     "last_date": s["last_date"]})

    derived_curve("s2s10", "ust_10y", "ust_2y")
    derived_curve("s3m10y", "ust_10y", "ust_3m")

    if ATH_PATH.exists():
        ath = json.loads(ATH_PATH.read_text())
        spx = state["series"].get("spx")
        if spx and ath.get("value"):
            state["derived"]["spx_ath"] = {
                "ath": ath["value"], "ath_date": ath["date"],
                "basis": ath.get("basis", "close"),
                "dist_pct": round(100.0 * (spx["last"] - ath["value"])
                                  / ath["value"], 3)}

    # long-run historical context (§4F) — supplementary, not fail-closed: if
    # data/history/ is missing or broken, skip it (and say so) rather than
    # fail the run; never leave half the history keys behind
    if HIST_DIR.exists():
        attach_history_safe(state, rows, row_date)

    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")

    # human summary
    print(f"state for {row_date} | trading rows: {len(market_dates)} | "
          f"seasoned: {state['seasoned']}")
    hdr = f"{'series':<15}{'last':>10}{'d1':>9}{'d5':>9}{'trend20':>9}{'z120':>8}  flag"
    print(hdr); print("-" * len(hdr))
    for name in TIER1 + ["s2s10", "s3m10y"]:
        s = state["series"].get(name) or state["derived"].get(name)
        if not s:
            print(f"{name:<15}{'MISSING':>10}")
            continue
        z = "thin" if s["z_thin"] else f"{s['z120']:+.2f}"
        d1 = "" if s["d1"] is None else f"{s['d1']:+.3f}"
        d5 = "" if s["d5"] is None else f"{s['d5']:+.3f}"
        print(f"{name:<15}{s['last']:>10.3f}{d1:>9}{d5:>9}"
              f"{(s['trend20'] or ''):>9}{z:>8}  {'⚑' if s['flag'] else ''}")
    if "spx_ath" in state["derived"]:
        a = state["derived"]["spx_ath"]
        print(f"\nSPX vs ATH ({a['ath_date']}, close {a['ath']:.2f}): "
              f"{a['dist_pct']:+.2f}%")
    if state["flags"]:
        print("\nFLAGS (|z|>=1.5):")
        for fl in state["flags"]:
            print(f"  {fl['series']}: z={fl['z120']:+.2f} last={fl['last']}")
    else:
        print("\nno z-flags — nothing outside normal ranges")
    return 0


def _label(ctx, z, thin):
    return hc.lately_vs_history(z, thin, ctx["pct_rank_all_time"], ctx.get("pct_rank_modern"),
                                ctx["start_date"][:4], ctx["short_history"])


HISTORY_KEYS = ("long_history", "history_base_rates", "rate_pace", "history_pairs",
                "curve_cycles", "market_history", "cycle_map", "then_vs_now",
                "history_digest")


def attach_history_safe(state, rows, row_date):
    """attach_history, but a broken history file costs the history blocks,
    never the brief: all of them are dropped (no half-written state) and the
    error is recorded so the brief can say so."""
    try:
        attach_history(state, rows, row_date)
    except Exception as e:
        for k in HISTORY_KEYS:
            state.pop(k, None)
        state["history_error"] = f"{type(e).__name__}: {e}"
        print(f"WARNING: long-run history skipped ({state['history_error']})", file=sys.stderr)


def attach_history(state, rows, row_date):
    """§4F: where today sits against real history -- percentiles, the last
    time it was here, what came after (from the start, against the normal
    rate), pace, pairs, curve cycles, markets, then-vs-now, the financing-
    cycle map, and the digest the brief leads with. history_context.py does
    the math; this only wires live readings in."""
    import history_digest

    lh = state["long_history"] = {}
    for key, opts in LONG_HISTORY_KEYS.items():
        s = state["series"].get(key) or state["derived"].get(key)
        if s is None or key not in hc.SOURCES:
            continue
        value = s["last"] / 100.0 if opts.get("bp_to_pct") else s["last"]
        if opts.get("bp_to_pct"):
            a, b = {"s2s10": ("ust_10y", "ust_2y"), "s3m10y": ("ust_10y", "ust_3m")}[key]
            oa, ob = dict(series_obs(rows, a)), dict(series_obs(rows, b))
            live = [(d, oa[d] - ob[d]) for d in sorted(oa) if d in ob]
        else:
            live = series_obs(rows, key)
        try:
            ctx = hc.context_for(key, value, s["last_date"], direction="high",
                                 live_rows=live)
        except FileNotFoundError:
            continue
        if not ctx:
            continue
        ctx["latest_value"] = value
        ctx["latest_date"] = s["last_date"]
        ctx["label"] = _label(ctx, s.get("z120"), s.get("z_thin"))
        lh[key] = ctx
        if ctx.get("proxy_key") and ctx["proxy_key"] not in lh:
            try:
                prow, _ = hc._series_for(ctx["proxy_key"])
                prow = [x for x in prow if x[0] <= row_date]
                pdate, pval = prow[-1]
                pctx = hc.context_for(ctx["proxy_key"], pval, pdate, direction="high")
                pctx["latest_value"], pctx["latest_date"] = pval, pdate
                z, thin = hc.recent_z(prow, pdate)
                pctx["lately_z"] = z
                pctx["label"] = _label(pctx, z, thin)
                lh[ctx["proxy_key"]] = pctx
            except (FileNotFoundError, IndexError):
                pass
    for key in REFERENCE_KEYS:
        try:
            r, _ = hc._series_for(key)
        except FileNotFoundError:
            continue
        r = [x for x in r if x[0] <= row_date]
        if not r:
            continue
        d, v = r[-1]
        ctx = hc.context_for(key, v, d, direction="high")
        if ctx:
            ctx["latest_value"], ctx["latest_date"] = v, d
            ctx["reference_series"] = True
            z, thin = hc.recent_z(r, d)
            ctx["lately_z"] = z
            ctx["label"] = _label(ctx, z, thin)
            lh[key] = ctx
    # TIPS only reach back to 2003; flag when the Cleveland model's longer
    # record tells a different story, so prose cites both (§4F)
    if "tips_10y_real" in lh and "real10_cleveland" in lh:
        a = lh["tips_10y_real"]["pct_rank_all_time"]
        b = lh["real10_cleveland"]["pct_rank_all_time"]
        lh["tips_10y_real"]["tips_window_divergence"] = abs(a - b) >= hc.REGIME_DIVERGENCE_PTS
        lh["tips_10y_real"]["cleveland_pct_all_time"] = b
        lh["tips_10y_real"]["cleveland_pct_modern"] = lh["real10_cleveland"]["pct_rank_modern"]

    state["history_base_rates"] = hc.base_rates(row_date)

    pace = state["rate_pace"] = {}
    for key in RATE_PACE_KEYS:
        s = state["series"].get(key)
        if not s:
            continue
        hrows, _ = hc._series_for(key)
        entry = {"ytd": hc.ytd_rank(hrows, s["last"], s["last_date"], "bp"),
                 "shock": hc.rate_shock(key, s["last"], s["last_date"])}
        if key == "ust_10y":
            entry["daily_move"] = hc.daily_change_rank(hrows, s["d1"], s["last_date"])
        pace[key] = entry

    latest = {}
    for key in ("tips_10y_real", "ust_10y", "dxy"):
        s = state["series"].get(key)
        if s:
            latest[key] = (s["last_date"], s["last"])
    state["history_pairs"] = {}
    for name, (a, sa, b, sb) in HISTORY_PAIRS.items():
        try:
            ctx = hc.pair_bands(a, sa, b, sb, row_date,
                                latest={k: v for k, v in latest.items() if k in (a, b)})
        except FileNotFoundError:
            continue
        if ctx:
            state["history_pairs"][name] = ctx

    state["curve_cycles"] = {}
    for key in ("s2s10", "s3m10y"):
        try:
            state["curve_cycles"][key] = hc.inversion_cycles(key, row_date)
        except FileNotFoundError:
            pass

    live = {k: series_obs(rows, k) for k in MARKET_HISTORY_KEYS}
    state["market_history"] = {}
    for key in MARKET_HISTORY_KEYS:
        try:
            ctx = hc.market_context(key, row_date, live_rows=live.get(key))
        except FileNotFoundError:
            continue
        if ctx:
            state["market_history"][key] = ctx

    try:
        state["cycle_map"] = hc.cycle_map(row_date, live={k: live[k] for k in ("spx", "ndx")})
    except FileNotFoundError:
        pass

    digest = history_digest.build_digest(state)
    # then-vs-now panel for the lead "last time" fact, when it's 10+ years back
    lead = next((f for f in digest if f["id"].startswith("lookback:")
                 and (f.get("years_since") or 0) >= 10), None)
    if lead:
        now_vals = {}
        for key in ("ust_10y", "tips_10y_real", "bkeven_10y"):
            s = state["series"].get(key)
            if s:
                now_vals[key] = (s["last_date"], s["last"])
        sofr = state["series"].get("sofr")
        if sofr:
            now_vals["dff"] = (sofr["last_date"], sofr["last"])
        for key in ("s2s10", "s3m10y"):
            s = state["derived"].get(key)
            if s:
                now_vals[key] = (s["last_date"], s["last"] / 100.0)
        ath = state["derived"].get("spx_ath")
        if ath:
            now_vals["spx_dd"] = (state["series"]["spx"]["last_date"], ath["dist_pct"])
        state["then_vs_now"] = hc.then_vs_now(lead["anchor_date"], row_date, now_vals)
        state["then_vs_now"]["fact_id"] = lead["id"]
    state["history_digest"] = digest


if __name__ == "__main__":
    sys.exit(main())
