#!/usr/bin/env python3
"""refresh_universe.py — movers-universe maintenance (§5 Tier 2, §13.9).

Builds two files:
  data/sp500_constituents.json   S&P 500 membership (Wikipedia list page)
                                 — refresh weekly (Mondays with the calendar)
  data/megacap50.json            top-50 S&P names by market cap
                                 (Nasdaq screener API caps ∩ S&P membership,
                                 share classes deduped) — refresh quarterly

Verified sources 2026-08-19: FMP constituents/screener/batch endpoints are
plan-gated; Wikipedia and the Nasdaq screener API are not. Caps cross-checked
against FMP single quotes at build (NVDA 5,318B vs 5,322B; AAPL 4,525B vs
4,553B — intraday timing accounts for the gap).
"""

import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull_data import _get  # noqa: E402 — shared curl fetcher

REPO = Path(__file__).resolve().parent.parent
SP500_PATH = REPO / "data" / "sp500_constituents.json"
MEGA_PATH = REPO / "data" / "megacap50.json"

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ_URL = ("https://api.nasdaq.com/api/screener/stocks"
              "?limit=120&marketcap=mega&download=true")


def fetch_sp500():
    """Parse tickers from the Wikipedia constituents table."""
    html = _get(WIKI_URL).decode("utf-8", "replace")
    # constituents table only (the changes table further down repeats tickers)
    table = html.split('id="constituents"', 1)[-1]
    end = table.find("Selected changes")
    if end > 0:
        table = table[:end]
    # each row's first cell links to the exchange quote page for the ticker:
    #   nyse.com/quote/XNYS:MMM   |   nasdaq.com/market-activity/stocks/aapl
    nyse = re.findall(r'quote/[A-Z]+:([A-Z0-9.\-]+)"', table)
    nasdaq = re.findall(r'nasdaq\.com/market-activity/stocks/([a-z0-9.\-]+)"',
                        table)
    tickers = nyse + [t.upper() for t in nasdaq]
    seen, out = set(), []
    for t in tickers:
        t = t.replace(".", "-")          # BRK.B -> BRK-B (Yahoo/FMP style)
        if t not in seen:
            seen.add(t)
            out.append(t)
    if len(out) < 480:
        raise RuntimeError(f"only parsed {len(out)} S&P tickers — page changed?")
    return out


def fetch_megacaps():
    """[(symbol, cap)] from the Nasdaq screener, descending by cap."""
    data = json.loads(_get_nasdaq().decode("utf-8", "replace"))
    rows = (data.get("data") or {}).get("rows") or []
    out = []
    for r in rows:
        cap = r.get("marketCap")
        if not cap:
            continue
        sym = r["symbol"].strip().replace("/", "-")   # BRK/B -> BRK-B
        out.append((sym, float(cap)))
    out.sort(key=lambda x: -x[1])
    return out


def _get_nasdaq():
    # Nasdaq API wants browser-ish headers; _get sends a browser UA to yahoo
    # only, so fetch with explicit curl args here.
    import subprocess
    p = subprocess.run(
        ["curl", "-sS", "--fail", "--max-time", "30",
         "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
         "-H", "Accept: application/json", NASDAQ_URL],
        capture_output=True, check=True)
    return p.stdout


def main():
    today = dt.date.today().isoformat()
    sp500 = fetch_sp500()
    SP500_PATH.write_text(json.dumps(
        {"as_of": today, "source": WIKI_URL, "count": len(sp500),
         "tickers": sp500}, indent=1) + "\n")
    print(f"S&P 500 constituents: {len(sp500)} -> {SP500_PATH.name}")

    membership = set(sp500)
    caps = fetch_megacaps()
    # dual-listed share classes in the index: collapse to one company
    aliases = {"GOOG": "GOOGL", "FOXA": "FOX", "NWSA": "NWS", "BF-A": "BF-B",
               "BRK-A": "BRK-B", "UHAL-B": "UHAL", "LEN-B": "LEN"}
    mega, seen_names = [], set()
    for sym, cap in caps:
        if sym not in membership:
            continue                      # drops ADRs / non-S&P listings
        base = aliases.get(sym, sym)
        if base in seen_names:
            continue
        seen_names.add(base)
        mega.append({"symbol": sym, "market_cap": cap})
        if len(mega) == 50:
            break
    if len(mega) < 50:
        raise RuntimeError(f"only {len(mega)} megacaps after filtering")
    MEGA_PATH.write_text(json.dumps(
        {"as_of": today, "refresh": "quarterly", "source": NASDAQ_URL,
         "rule": "top-50 S&P 500 constituents by market cap, share classes deduped",
         "constituents": mega}, indent=1) + "\n")
    print(f"megacap50: {len(mega)} names, "
          f"#1 {mega[0]['symbol']} {mega[0]['market_cap']/1e12:.2f}T, "
          f"#50 {mega[-1]['symbol']} {mega[-1]['market_cap']/1e9:.0f}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
