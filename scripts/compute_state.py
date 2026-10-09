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

# Price series: return-based long-run context (a level percentile of an
# equity index or nominal oil price is meaningless). §4F, 2026-10-09.
MARKET_HISTORY_KEYS = ["spx", "ndx", "wti", "gold"]

# Standing cross-series configurations (§4F, 2026-10-09): "when were these
# last true at the same time?" Each is a tension the brief has been
# narrating day to day; history says whether it is ordinary or rare.
JOINT_CONFIGS = {
    "real_rates_high_credit_tight": {
        "label": "10Y real yield this high AND investment-grade credit "
                 "spread proxy (Baa minus 10Y) this tight",
        "conditions": [("tips_10y_real", "high"), ("baa_10y_spread", "low")]},
    "long_rates_high_stocks_near_record": {
        "label": "10Y Treasury yield this high AND the S&P 500 this close "
                 "to its record close",
        "conditions": [("ust_10y", "high"), ("spx_dd", "high")]},
    "long_rates_high_dollar_strong": {
        "label": "10Y Treasury yield this high AND the dollar (DXY) this strong",
        "conditions": [("ust_10y", "high"), ("dxy", "high")]},
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

    # long-run historical context (§4F) — supplementary, not fail-closed:
    # if data/history/ hasn't been built/refreshed yet, skip quietly rather
    # than failing the whole run over reference data.
    if HIST_DIR.exists():
        state["long_history"] = {}
        for key, opts in LONG_HISTORY_KEYS.items():
            s = state["series"].get(key) or state["derived"].get(key)
            if s is None or key not in hc.SOURCES:
                continue
            value = s["last"] / 100.0 if opts.get("bp_to_pct") else s["last"]
            try:
                ctx = hc.context_for(key, value, s["last_date"], direction="high")
            except FileNotFoundError:
                continue
            if ctx:
                state["long_history"][key] = ctx
                if ctx.get("proxy_key"):
                    prow = state["series"].get(key) or {}
                    try:
                        proxy_rows, _ = hc._series_for(ctx["proxy_key"])
                        pdate, pval = proxy_rows[-1]
                        state["long_history"][ctx["proxy_key"]] = hc.context_for(
                            ctx["proxy_key"], pval, pdate, direction="high")
                    except (FileNotFoundError, IndexError):
                        pass
        try:
            state["curve_inversions"] = {
                "s2s10": hc.summarize_inversions("s2s10"),
                "s3m10y": hc.summarize_inversions("s3m10y"),
            }
        except FileNotFoundError:
            pass

        state["market_history"] = {}
        for key in MARKET_HISTORY_KEYS:
            try:
                ctx = hc.market_context(key, row_date)
            except FileNotFoundError:
                continue
            if ctx:
                state["market_history"][key] = ctx

        # live readings the brief quotes, so a joint config describes today,
        # not the last date every history file happens to share
        latest = {}
        for key in ("ust_10y", "tips_10y_real", "dxy"):
            s = state["series"].get(key)
            if s:
                latest[key] = (s["last_date"], s["last"])
        spx = state["series"].get("spx")
        if spx and ATH_PATH.exists():
            ath_val = json.loads(ATH_PATH.read_text()).get("value")
            if ath_val:
                latest["spx_dd"] = (spx["last_date"],
                                    round(100.0 * (spx["last"] / ath_val - 1.0), 4))
        state["joint_history"] = {}
        for name, cfg in JOINT_CONFIGS.items():
            try:
                ctx = hc.joint_context(cfg["conditions"], row_date,
                                       latest={k: v for k, v in latest.items()
                                               if k in dict(cfg["conditions"])})
            except FileNotFoundError:
                continue
            if ctx:
                ctx["label"] = cfg["label"]
                state["joint_history"][name] = ctx

    if ATH_PATH.exists():
        ath = json.loads(ATH_PATH.read_text())
        spx = state["series"].get("spx")
        if spx and ath.get("value"):
            state["derived"]["spx_ath"] = {
                "ath": ath["value"], "ath_date": ath["date"],
                "basis": ath.get("basis", "close"),
                "dist_pct": round(100.0 * (spx["last"] - ath["value"])
                                  / ath["value"], 3)}

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


if __name__ == "__main__":
    sys.exit(main())
