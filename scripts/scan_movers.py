#!/usr/bin/env python3
"""scan_movers.py — mechanical movers selection (§5 Tier 2).

Rules (ratified; mechanical to prevent drift into stock-tipping):
  - S&P 500 constituents with |1D| >= 4%
  - top-50 mega-caps (data/megacap50.json) with |1D| >= 2.5%
  - any GICS sector ETF diverging >= 1.5pp from SPX on the day
Output is CANDIDATES sorted by |move|; the brief writer applies the cap
(3 names + 1 sector note) and the fact/reason/read-through format. Earnings/
guidance-driven moves take priority over drift at equal magnitude.

Scan source: Yahoo v8 spark batch endpoint over the constituents file
(verified 2026-08-19; FMP batch quotes are plan-gated). Every close used is
dated <= --row-date so a mid-session run never grades today's partial bar.

Usage: scan_movers.py --row-date 2026-08-18 [--out data/raw/movers_2026-08-18.json]
"""

import argparse
import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull_data import _get  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SP500_PATH = REPO / "data" / "sp500_constituents.json"
MEGA_PATH = REPO / "data" / "megacap50.json"

SECTOR_ETFS = {"XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
               "XLV": "Health Care", "XLI": "Industrials",
               "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
               "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate",
               "XLC": "Communication Services"}
SP500_THRESHOLD = 4.0
MEGACAP_THRESHOLD = 2.5
SECTOR_DIVERGENCE_PP = 1.5
CHUNK = 20


def spark_chunk(symbols, range_="5d"):
    """{symbol: {date: close}} for one spark batch call."""
    q = urllib.request.quote(",".join(symbols), safe=",")
    url = (f"https://query1.finance.yahoo.com/v8/finance/spark"
           f"?symbols={q}&range={range_}&interval=1d")
    data = json.loads(_get(url).decode("utf-8", "replace"))
    out = {}
    for sym, r in data.items():
        ts = r.get("timestamp") or []
        closes = r.get("close") or []
        series = {}
        for t, c in zip(ts, closes):
            if c is not None:
                series[dt.datetime.utcfromtimestamp(t - 4 * 3600)
                       .date().isoformat()] = float(c)
        out[sym] = series
    return out


def one_day_move(series, row_date):
    """(pct_change, close, prev_close) using the last two closes <= row_date."""
    dates = sorted(d for d in series if d <= row_date)
    if len(dates) < 2:
        return None
    last, prev = series[dates[-1]], series[dates[-2]]
    if not prev:
        return None
    return (round(100.0 * (last - prev) / prev, 3), last, prev,
            dates[-1], dates[-2])


def scan(symbols, row_date, label, threshold, sleep_s=0.35):
    hits, covered, missing = [], 0, []
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        try:
            data = spark_chunk(chunk)
        except RuntimeError:
            missing.extend(chunk)
            continue
        for sym in chunk:
            m = one_day_move(data.get(sym, {}), row_date)
            if m is None:
                missing.append(sym)
                continue
            covered += 1
            pct, last, prev, d_last, d_prev = m
            if abs(pct) >= threshold:
                hits.append({"symbol": sym, "pct_1d": pct, "close": last,
                             "prev_close": prev, "close_date": d_last,
                             "screen": label})
        time.sleep(sleep_s)
    return hits, covered, missing


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--row-date", required=True)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    row_date = args.row_date

    sp500 = json.loads(SP500_PATH.read_text())["tickers"]
    mega = [c["symbol"] for c in
            json.loads(MEGA_PATH.read_text())["constituents"]]

    hits, covered, missing = scan(sp500, row_date, "sp500_4pct",
                                  SP500_THRESHOLD)
    mega_set = set(mega)
    # megacap threshold applied from the same scan (megacaps ⊂ S&P universe)
    mega_hits, mcov, mmiss = scan(mega, row_date, "megacap_2.5pct",
                                  MEGACAP_THRESHOLD)
    seen = {h["symbol"] for h in hits}
    hits += [h for h in mega_hits if h["symbol"] not in seen]

    setf, scov, smiss = scan(list(SECTOR_ETFS) + ["SPY"], row_date,
                             "sector", 0.0)
    by_sym = {h["symbol"]: h for h in setf}
    spy = by_sym.get("SPY", {}).get("pct_1d")
    sectors = []
    if spy is not None:
        for etf, name in SECTOR_ETFS.items():
            h = by_sym.get(etf)
            if not h:
                continue
            div = round(h["pct_1d"] - spy, 3)
            if abs(div) >= SECTOR_DIVERGENCE_PP:
                sectors.append({"etf": etf, "sector": name,
                                "pct_1d": h["pct_1d"], "spy_pct_1d": spy,
                                "divergence_pp": div})
    hits.sort(key=lambda h: -abs(h["pct_1d"]))
    sectors.sort(key=lambda s: -abs(s["divergence_pp"]))

    result = {"row_date": row_date,
              "scanned_at_utc": dt.datetime.utcnow().isoformat() + "Z",
              "universe": {"sp500": len(sp500), "sp500_covered": covered,
                           "megacap": len(mega), "megacap_covered": mcov,
                           "missing": sorted(set(missing + mmiss))},
              "thresholds": {"sp500_pct": SP500_THRESHOLD,
                             "megacap_pct": MEGACAP_THRESHOLD,
                             "sector_divergence_pp": SECTOR_DIVERGENCE_PP},
              "name_candidates": hits, "sector_candidates": sectors}
    out = Path(args.out) if args.out else (
        REPO / "data" / "raw" / f"movers_{row_date}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")

    print(f"scan {row_date}: {covered}/{len(sp500)} S&P names covered, "
          f"{len(hits)} name candidates, {len(sectors)} sector divergences")
    for h in hits[:12]:
        print(f"  {h['symbol']:<6} {h['pct_1d']:+7.2f}%  [{h['screen']}]")
    for s in sectors:
        print(f"  {s['etf']} ({s['sector']}): {s['pct_1d']:+.2f}% vs SPY "
              f"{s['spy_pct_1d']:+.2f}% -> {s['divergence_pp']:+.2f}pp")
    if len(missing) > len(sp500) * 0.1:
        print(f"  WARNING: {len(missing)} symbols uncovered — state the gap "
              f"in the movers section (§4)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
