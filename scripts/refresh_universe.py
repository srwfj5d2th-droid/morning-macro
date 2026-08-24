#!/usr/bin/env python3
"""refresh_universe.py — movers-universe maintenance (§5 Tier 2, §13.9).

Single source (since 2026-08-24): State Street's official daily holdings file
for SPY — the S&P 500 ETF's actual holdings, published by the fund manager
itself. One authoritative file supplies both outputs:

  data/sp500_constituents.json   S&P 500 membership — refresh weekly (Mondays)
  data/megacap50.json            top-50 constituents by index weight
                                 (float-adjusted market cap) — quarterly

History: v1 used Wikipedia (membership) + the Nasdaq screener (caps). Replaced
at Jacob's request 2026-08-24 — he doesn't trust Wikipedia as a source, and
the fund's own holdings file is strictly more authoritative anyway. FMP's
constituents/screener endpoints remain plan-gated (no-paid-services rule).

The xlsx is parsed with the stdlib only (zip + regex over the sheet XML) so
the pipeline gains no new dependency.
"""

import datetime as dt
import io
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull_data import _get  # noqa: E402 — shared curl fetcher

REPO = Path(__file__).resolve().parent.parent
SP500_PATH = REPO / "data" / "sp500_constituents.json"
MEGA_PATH = REPO / "data" / "megacap50.json"

SSGA_URL = ("https://www.ssga.com/us/en/intermediary/library-content/"
            "products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx")

# dual-listed share classes: collapse to one company for the megacap list
ALIASES = {"GOOG": "GOOGL", "FOXA": "FOX", "NWSA": "NWS", "BF-A": "BF-B",
           "BRK-A": "BRK-B", "UHAL-B": "UHAL", "LEN-B": "LEN"}


def fetch_spy_holdings():
    """[(ticker, weight)] descending by weight, from the SSGA daily file.
    The URL 301-redirects; _get uses curl -sS which does not follow, so
    fetch with an explicit -L via the retry helper's urllib fallback path
    being unsuitable, we shell curl -L directly here."""
    import subprocess
    p = subprocess.run(
        ["curl", "-sSL", "--fail", "--max-time", "60",
         "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
         SSGA_URL],
        capture_output=True, check=True)
    return parse_spy_xlsx(p.stdout)


def parse_spy_xlsx(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    sis = re.findall(r"<si>(.*?)</si>",
                     z.read("xl/sharedStrings.xml").decode("utf-8", "replace"),
                     re.S)
    shared = ["".join(re.findall(r"<t[^>]*>([^<]*)</t>", si)) for si in sis]
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8", "replace")
    rows = re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S)

    def cells(row_xml):
        out = {}
        for ref, t, v in re.findall(
                r'<c r="([A-Z]+)\d+"(?: t="(\w+)")?[^>]*>(?:<v>([^<]*)</v>)?',
                row_xml):
            if v == "":
                continue
            out[ref] = shared[int(v)] if t == "s" and v.isdigit() else v
        return out

    hdr = None
    for i, r in enumerate(rows):
        c = cells(r)
        if "Ticker" in c.values() and "Weight" in c.values():
            hdr, hdr_i = c, i
            break
    if hdr is None:
        raise RuntimeError("SSGA holdings file: header row not found — "
                           "format changed?")
    tcol = next(k for k, v in hdr.items() if v == "Ticker")
    wcol = next(k for k, v in hdr.items() if v == "Weight")

    out = []
    for r in rows[hdr_i + 1:]:
        c = cells(r)
        tk, w = c.get(tcol), c.get(wcol)
        if not tk or not w:
            continue
        tk = tk.strip().replace(".", "-").replace(" ", "-")
        try:
            w = float(w)
        except ValueError:
            continue
        # ticker-shaped and positively weighted (drops cash/derivative rows)
        if re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", tk) and w > 0:
            out.append((tk, w))
    out.sort(key=lambda x: -x[1])
    if len(out) < 480:
        raise RuntimeError(f"only {len(out)} holdings parsed — file changed?")
    return out


def main():
    today = dt.date.today().isoformat()
    holdings = fetch_spy_holdings()

    SP500_PATH.write_text(json.dumps(
        {"as_of": today, "source": SSGA_URL, "count": len(holdings),
         "tickers": [t for t, _ in holdings]}, indent=1) + "\n")
    print(f"S&P 500 constituents: {len(holdings)} -> {SP500_PATH.name}")

    mega, seen = [], set()
    for sym, w in holdings:
        base = ALIASES.get(sym, sym)
        if base in seen:
            continue
        seen.add(base)
        mega.append({"symbol": sym, "index_weight_pct": w})
        if len(mega) == 50:
            break
    MEGA_PATH.write_text(json.dumps(
        {"as_of": today, "refresh": "quarterly", "source": SSGA_URL,
         "rule": ("top-50 S&P 500 constituents by index weight "
                  "(float-adjusted market cap), share classes deduped"),
         "constituents": mega}, indent=1) + "\n")
    print(f"megacap50: {len(mega)} names, #1 {mega[0]['symbol']} "
          f"{mega[0]['index_weight_pct']:.2f}%, "
          f"#50 {mega[-1]['symbol']} {mega[-1]['index_weight_pct']:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
