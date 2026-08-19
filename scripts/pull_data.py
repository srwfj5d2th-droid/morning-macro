#!/usr/bin/env python3
"""pull_data.py — data layer for the morning macro brief.

Fetches every scriptable series (FRED, Yahoo, NY Fed), writes a provenance
file (data/raw/YYYY-MM-DD.json) in which every value carries its observation
date, fetch timestamp, and source URL, then appends the day's row to
data/macro_series.csv.

Append-only contract: an existing non-null cell is never changed. Late-arriving
observations (OAS, SOFR publish with a 1-day lag) may fill a previously empty
cell on a later run; that is a fill, not an overwrite.

FMP-sourced content (sector performance, movers screens, single quotes) enters
through the MCP connector at brief-build time and lives in the raw file /
brief, not in this CSV. Substitutions vs. the spec's source table (§5), all
verified 2026-08-18/19 against the live endpoints:
  - Treasury tenors: FRED DGS* (FMP treasury endpoint lags ~2 trading days)
  - DXY: Yahoo DX-Y.NYB (FMP forex endpoint is plan-gated)
  - WTI / gold / copper: Yahoo futures (FMP commodity quotes gated per-symbol)
  - SOFR: FRED, NY Fed markets API as fallback

Usage:
  pull_data.py --seed [--start 2025-12-01]   build history from scratch
  pull_data.py --daily                       fetch, validate (fail-closed), append
  pull_data.py --validate-only               freshness check, no writes
Exit codes: 0 ok; 2 fail-closed (Tier 1 missing/stale) — no brief may be written.
"""

import argparse
import csv
import datetime as dt
import io
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "macro_series.csv"
RAW_DIR = REPO / "data" / "raw"
ATH_PATH = REPO / "data" / "spx_ath.json"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# column -> (source, source_id)
FRED_SERIES = {
    "ust_3m": "DGS3MO",
    "ust_2y": "DGS2",
    "ust_10y": "DGS10",
    "ust_30y": "DGS30",
    "tips_10y_real": "DFII10",
    "bkeven_10y_fred": "T10YIE",  # cross-check; stored bkeven_10y is derived
    "hy_oas": "BAMLH0A0HYM2",
    "ig_oas": "BAMLC0A0CM",
    "sofr": "SOFR",
    "on_rrp": "RRPONTSYD",
    "tga": "WTREGEN",
    "fed_bs": "WALCL",
}
YAHOO_SERIES = {
    "spx": "^GSPC",
    "ndx": "^IXIC",
    "rut": "^RUT",
    "dxy": "DX-Y.NYB",
    "wti": "CL=F",
    "gold": "GC=F",
    "copper": "HG=F",
    "spy": "SPY",
    "rsp": "RSP",
    "smh": "SMH",
}
COLUMNS = ["date", "ust_3m", "ust_2y", "ust_10y", "ust_30y", "tips_10y_real",
           "bkeven_10y", "hy_oas", "ig_oas", "dxy", "sofr", "fed_bs", "on_rrp",
           "tga", "spx", "ndx", "rut", "wti", "gold", "copper", "spy", "rsp", "smh"]

# Tier 1 freshness contract: max staleness in TRADING days from the row date
# (row date = most recent market close). 0 = must be dated the row date itself.
# OAS and SOFR publish next-day and are labeled as lagged in the brief (§5).
TIER1_MAX_LAG = {
    "ust_3m": 1, "ust_2y": 1, "ust_10y": 1, "ust_30y": 1,
    "tips_10y_real": 1, "bkeven_10y": 1,
    "hy_oas": 2, "ig_oas": 2,
    "dxy": 1, "sofr": 2,
    "fed_bs": 10, "on_rrp": 3, "tga": 10,   # weekly H.4.1 / DTS carry-forward
}


def _get(url, retries=3, timeout=45):
    """Fetch bytes via curl, urllib as fallback where curl is unavailable.

    UA quirk, verified 2026-08-19: FRED serves curl's default UA in <1s but
    stalls/errors both urllib and a spoofed browser UA; Yahoo requires a
    browser UA. So the browser UA goes only to hosts that need it."""
    ua = ["-A", UA] if "yahoo.com" in url else []
    last = None
    for i in range(retries + 1):
        try:
            p = subprocess.run(
                ["curl", "-sS", "--fail", "--max-time", str(timeout), *ua, url],
                capture_output=True, check=True)
            return p.stdout
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            last = e
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            except Exception as e2:  # noqa: BLE001 — retry any transport error
                last = e2
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed after {retries + 1} tries: {url}: {last}")


def fetch_fred(series_id, start):
    url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
           f"&cosd={start}")
    text = _get(url).decode("utf-8", "replace")
    return parse_fred_csv(text), url


def parse_fred_csv(text):
    """FRED fredgraph CSV -> {date: float}. Missing values ('.') skipped."""
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 2 or row[0] in ("DATE", "observation_date"):
            continue
        try:
            out[row[0]] = float(row[1])
        except ValueError:
            continue
    return out


def fetch_yahoo(symbol, range_="1y"):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.request.quote(symbol)}?range={range_}&interval=1d")
    data = json.loads(_get(url).decode("utf-8", "replace"))
    return parse_yahoo_chart(data), url


def parse_yahoo_chart(data):
    """Yahoo v8 chart JSON -> {date: close}. Nulls and same-date partial bars
    collapse to the last non-null close per date (exchange-local date)."""
    res = data["chart"]["result"][0]
    meta = res["meta"]
    off = meta.get("gmtoffset", 0)
    ts = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0].get("close") or []
    out = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = (dt.datetime.utcfromtimestamp(t + off)).date().isoformat()
        out[d] = round(float(c), 6)
    return out


TREASURY_GOV_URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
                    "interest-rates/daily-treasury-rates.csv/{year}/all"
                    "?type=daily_treasury_yield_curve"
                    "&field_tdr_date_value={year}&_format=csv")
TREASURY_GOV_COLS = {"3 Mo": "ust_3m", "2 Yr": "ust_2y",
                     "10 Yr": "ust_10y", "30 Yr": "ust_30y"}


def fetch_treasury_gov(year):
    """{date: {col: val}} same-day par yields from treasury.gov (posted ~6pm ET,
    so at 6:30am the prior trading day IS present — FRED ingests a day later)."""
    url = TREASURY_GOV_URL.format(year=year)
    return parse_treasury_gov_csv(_get(url).decode("utf-8", "replace")), url


def parse_treasury_gov_csv(text):
    out = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            m, d, y = row["Date"].split("/")
            date = f"{y}-{m}-{d}"
        except (KeyError, ValueError):
            continue
        vals = {}
        for src, col in TREASURY_GOV_COLS.items():
            try:
                vals[col] = float(row[src])
            except (KeyError, TypeError, ValueError):
                continue
        if vals:
            out[date] = vals
    return out


def fetch_nyfed_sofr():
    url = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/10.json"
    data = json.loads(_get(url).decode("utf-8", "replace"))
    return {r["effectiveDate"]: float(r["percentRate"])
            for r in data.get("refRates", [])}, url


def trading_days_between(d1, d2):
    """Weekday count in (d1, d2], holiday-blind (documented approximation)."""
    if d1 >= d2:
        return 0
    n, d = 0, d1
    while d < d2:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def read_csv_rows():
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


def write_csv_rows(rows):
    rows.sort(key=lambda r: r["date"])
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


def merge(rows, incoming):
    """Merge {date: {col: val}} into rows. Never change a non-null cell."""
    by_date = {r["date"]: r for r in rows}
    filled, conflicts = 0, 0
    for date, vals in incoming.items():
        row = by_date.get(date)
        if row is None:
            row = {"date": date}
            by_date[date] = row
            rows.append(row)
        for col, val in vals.items():
            if val is None:
                continue
            existing = row.get(col, "")
            if existing in ("", None):
                row[col] = val
                filled += 1
            elif abs(float(existing) - float(val)) > 1e-9:
                conflicts += 1  # keep existing; report, never overwrite
    return filled, conflicts


def pull_all(start):
    """Fetch everything; return (incoming {date:{col:val}}, provenance dict)."""
    incoming, prov = {}, {"pulled_at_utc": dt.datetime.utcnow().isoformat() + "Z",
                          "sources": {}}
    # treasury.gov first: same-day par yields (FRED carries the same H.15
    # values a day later, so first-writer-wins keeps the two consistent)
    years = {start[:4], dt.date.today().strftime("%Y")}
    for y in sorted(years):
        try:
            tsy, url = fetch_treasury_gov(y)
            prov["sources"][f"treasury_gov_{y}"] = {
                "source": "treasury.gov par yield curve", "url": url,
                "latest_obs": max(tsy) if tsy else None}
            for d, vals in tsy.items():
                if d >= start:
                    incoming.setdefault(d, {}).update(vals)
        except RuntimeError as e:
            prov["sources"][f"treasury_gov_{y}"] = {"error": str(e)}

    fred_vals = {}
    for col, sid in FRED_SERIES.items():
        time.sleep(0.6)   # politeness: FRED throttles rapid-fire requests
        series, url = fetch_fred(sid, start)
        fred_vals[col] = series
        prov["sources"][col] = {"source": f"FRED {sid}", "url": url,
                                "latest_obs": max(series) if series else None,
                                "latest_val": series.get(max(series)) if series else None}
        if col == "bkeven_10y_fred":
            continue
        for d, v in series.items():
            # setdefault: treasury.gov already populated tenor cells for the
            # freshest day; FRED (same H.15 values, one day later) backfills
            incoming.setdefault(d, {}).setdefault(col, v)
    # derived 10y breakeven = nominal - real (§5: "derived"); T10YIE cross-check
    for d, nom in fred_vals.get("ust_10y", {}).items():
        real = fred_vals.get("tips_10y_real", {}).get(d)
        if real is not None:
            incoming.setdefault(d, {})["bkeven_10y"] = round(nom - real, 4)
    xchk = fred_vals.get("bkeven_10y_fred", {})
    prov["breakeven_crosscheck"] = {
        d: {"derived": incoming[d]["bkeven_10y"], "t10yie": xchk[d]}
        for d in list(xchk) if d in incoming and "bkeven_10y" in incoming[d]
        and abs(incoming[d]["bkeven_10y"] - xchk[d]) > 0.05}

    yr = "2y" if start < "2025-09-01" else "1y"
    for col, sym in YAHOO_SERIES.items():
        try:
            series, url = fetch_yahoo(sym, range_=yr)
        except RuntimeError as e:
            prov["sources"][col] = {"source": f"Yahoo {sym}", "error": str(e)}
            continue
        prov["sources"][col] = {"source": f"Yahoo {sym}", "url": url,
                                "latest_obs": max(series) if series else None,
                                "latest_val": series.get(max(series)) if series else None}
        for d, v in series.items():
            if d >= start:
                incoming.setdefault(d, {})[col] = v
    # SOFR fallback if FRED lags NY Fed
    try:
        ny, url = fetch_nyfed_sofr()
        prov["sources"]["sofr_nyfed"] = {"source": "NY Fed SOFR", "url": url,
                                         "latest_obs": max(ny) if ny else None}
        for d, v in ny.items():
            if d >= start:
                incoming.setdefault(d, {}).setdefault("sofr", v)
    except RuntimeError as e:
        prov["sources"]["sofr_nyfed"] = {"error": str(e)}
    return incoming, prov


def update_ath(rows):
    """Track SPX all-time high (closing basis) across runs."""
    ath = {"value": 0.0, "date": None, "basis": "close"}
    if ATH_PATH.exists():
        ath = json.loads(ATH_PATH.read_text())
    for r in rows:
        v = r.get("spx", "")
        if v not in ("", None) and float(v) > float(ath["value"]):
            ath = {"value": float(v), "date": r["date"], "basis": "close"}
    ATH_PATH.write_text(json.dumps(ath, indent=2) + "\n")
    return ath


def seed_ath():
    """One-time: max ^GSPC close over 10y so the ATH line is genuine."""
    series, _ = fetch_yahoo("^GSPC", range_="10y")
    if not series:
        return
    d = max(series, key=lambda k: series[k])
    ATH_PATH.write_text(json.dumps(
        {"value": series[d], "date": d, "basis": "close"}, indent=2) + "\n")


def validate(rows):
    """Fail-closed Tier 1 freshness check. Returns (ok, row_date, problems)."""
    dated = [r for r in rows if r.get("spx") not in ("", None)]
    if not dated:
        return False, None, ["no market rows at all"]
    row_date = dt.date.fromisoformat(max(r["date"] for r in dated))
    problems = []
    for col, max_lag in TIER1_MAX_LAG.items():
        obs = [r["date"] for r in rows if r.get(col) not in ("", None)]
        if not obs:
            problems.append(f"{col}: no observations")
            continue
        lag = trading_days_between(dt.date.fromisoformat(max(obs)), row_date)
        if lag > max_lag:
            problems.append(f"{col}: latest {max(obs)} is {lag} trading days "
                            f"stale (max {max_lag})")
    return not problems, row_date.isoformat(), problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--daily", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--start", default="2025-12-01")
    args = ap.parse_args(argv)

    rows = read_csv_rows()
    if args.validate_only:
        ok, row_date, problems = validate(rows)
        print(f"row_date={row_date} ok={ok}")
        for p in problems:
            print("  STALE:", p)
        return 0 if ok else 2

    if args.seed and rows:
        print(f"macro_series.csv already has {len(rows)} rows; seed refused "
              f"(append-only). Delete the file first if you mean it.")
        return 1

    start = args.start if args.seed else (
        max(r["date"] for r in rows) if rows else args.start)
    # re-fetch a trailing window so late-arriving lagged series fill in
    if not args.seed and rows:
        start = (dt.date.fromisoformat(start) - dt.timedelta(days=14)).isoformat()

    incoming, prov = pull_all(start)
    filled, conflicts = merge(rows, incoming)
    # drop weekend/holiday rows with no market close (FRED weekly obs dates)
    rows = [r for r in rows if any(r.get(c) not in ("", None)
                                   for c in ("spx", "ust_10y", "hy_oas",
                                             "fed_bs", "tga"))]
    write_csv_rows(rows)
    if args.seed:
        seed_ath()
    ath = update_ath(rows)

    ok, row_date, problems = validate(rows)
    run_date = dt.date.today().isoformat()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    prov.update({"row_date": row_date, "validation_ok": ok,
                 "validation_problems": problems, "cells_filled": filled,
                 "conflicts_kept_existing": conflicts, "spx_ath": ath})
    (RAW_DIR / f"{run_date}.json").write_text(json.dumps(prov, indent=2) + "\n")

    print(f"rows={len(rows)} filled={filled} conflicts={conflicts} "
          f"row_date={row_date} tier1_ok={ok}")
    for p in problems:
        print("  STALE:", p)
    if not ok:
        print("FAIL-CLOSED: Tier 1 incomplete — no brief may be written (§4).")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
