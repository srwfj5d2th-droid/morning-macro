#!/usr/bin/env python3
"""build_long_history.py — reference data for long-run historical context.

Fixes the failure mode flagged by Jacob 2026-10-05 and again 2026-10-08: a
brief calling a reading "the widest/highest this system has tracked" when the
system's own macro_series.csv only spans ~10 months is true but misleading —
it invites the reader to hear "historically extreme" when the data only
supports "extreme within a short lookback." This script pulls real long-run
history (decades, where the source actually has it) so compute_state.py can
report where today's reading actually sits against history, and whether
comparable past readings preceded a recession — not vibes, not training-data
recall, a cited file.

This is NOT part of the daily pipeline (§3). It is slow-changing reference
data, refreshed periodically (monthly review, or on demand) via:
  build_long_history.py --refresh

Series and their REAL available history, verified live 2026-10-08 against
this environment's FRED mirror (not assumed — the two ICE BofA OAS series
below have a genuine environment constraint, documented rather than papered
over):
  DGS3MO   1981-09-01+   3-month Treasury
  DGS2     1976-06-01+   2-year Treasury
  DGS10    1962-01-02+   10-year Treasury
  DGS30    1977-02-15+   30-year Treasury (gap 2002-02 to 2006-02: Treasury
                         stopped issuing 30Y bonds over that window)
  DFII10   2003-01-02+   10Y TIPS real yield
  T10YIE   2003-01-02+   10Y breakeven inflation
  DFF      1954-07-01+   Effective fed funds rate — SOFR's long-run proxy;
                         SOFR itself only exists from 2018
  DBAA     1986-01-02+   Moody's Baa corporate bond yield, daily — used to
                         build a long-run credit-risk-premium PROXY
                         (DBAA - DGS10), never conflated with the literal
                         ICE BofA HY OAS series this system quotes daily
  USREC    1950-01-01+   NBER recession indicator (monthly, 0/1)
  BAMLH0A0HYM2  2023-10-09+ only, in THIS environment  (real-world FRED has
                         this back to 1996-12-31; this sandbox's mirror
                         reports min_date=2023-10-09 for both ICE BofA OAS
                         series regardless of the cosd requested — verified
                         via the fredgraph chart-api's own min_date field,
                         not a guess). Treated honestly as a ~3-year window.
  BAMLC0A0CM    2023-10-09+ only, same constraint as above (IG OAS)

Output: data/history/<key>.csv (date,value), plus data/history/episodes.json
(hand-curated date ranges for named historical episodes — well-established
historical facts, not market-data claims; the actual min/max/median *within*
each window is computed from the pulled series, never hand-typed).
"""

import argparse
import csv
import io
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HIST_DIR = REPO / "data" / "history"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# key -> FRED series id
SERIES = {
    "dgs3mo": "DGS3MO",
    "dgs2": "DGS2",
    "dgs10": "DGS10",
    "dgs30": "DGS30",
    "dfii10": "DFII10",
    "t10yie": "T10YIE",
    "dff": "DFF",
    "dbaa": "DBAA",
    "daaa": "DAAA",
    "usrec": "USREC",
    "baml_hy_oas": "BAMLH0A0HYM2",
    "baml_ig_oas": "BAMLC0A0CM",
}

# earliest cosd worth asking for each — real series start dates (where known)
# or a safely-early date; the fetch just gets whatever the source actually has
COSD = {
    "dgs3mo": "1950-01-01", "dgs2": "1950-01-01", "dgs10": "1950-01-01",
    "dgs30": "1950-01-01", "dfii10": "1950-01-01", "t10yie": "1950-01-01",
    "dff": "1950-01-01", "dbaa": "1919-01-01", "daaa": "1919-01-01",
    "usrec": "1945-01-01",
    "baml_hy_oas": "1990-01-01", "baml_ig_oas": "1990-01-01",
}


def _get(url, retries=3, timeout=45):
    """Same UA quirk as pull_data.py: FRED wants curl's default UA."""
    last = None
    for i in range(retries + 1):
        try:
            p = subprocess.run(
                ["curl", "-sS", "--fail", "--max-time", str(timeout), url],
                capture_output=True, check=True)
            return p.stdout
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            last = e
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            except Exception as e2:  # noqa: BLE001
                last = e2
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed after {retries + 1} tries: {url}: {last}")


def fetch_series(series_id, cosd):
    url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
           f"&cosd={cosd}")
    text = _get(url).decode("utf-8", "replace")
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 2 or row[0] in ("DATE", "observation_date"):
            continue
        date, val = row
        if val.strip() in ("", "."):
            continue
        rows.append((date, val))
    return rows, url


def refresh():
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    report = []
    for key, series_id in SERIES.items():
        rows, url = fetch_series(series_id, COSD[key])
        out = HIST_DIR / f"{key}.csv"
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "value"])
            w.writerows(rows)
        first = rows[0][0] if rows else None
        last = rows[-1][0] if rows else None
        report.append((key, series_id, len(rows), first, last))
        time.sleep(0.6)  # politeness, same as pull_data.py
    print(f"{'key':<14}{'fred_id':<16}{'n_obs':>8}  {'first':<12}{'last':<12}")
    for key, series_id, n, first, last in report:
        print(f"{key:<14}{series_id:<16}{n:>8}  {first or '-':<12}{last or '-':<12}")
    # sanity flag: anything with suspiciously short history that *should* be
    # long, so a future human (or Claude) notices if the environment changes
    for key, series_id, n, first, last in report:
        if key not in ("baml_hy_oas", "baml_ig_oas", "usrec") and n < 1000:
            print(f"WARNING: {key} ({series_id}) returned only {n} rows — "
                  f"expected deep history. Re-check before trusting its "
                  f"long_history output.", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    if not args.refresh:
        ap.error("pass --refresh (this is reference data, not a daily pull)")
    refresh()


if __name__ == "__main__":
    main()
