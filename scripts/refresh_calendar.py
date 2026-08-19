#!/usr/bin/env python3
"""refresh_calendar.py — weekly economic calendar (§2, refreshed Mondays).

Source: ForexFactory's public weekly JSON (verified 2026-08-19; FMP's
economics-calendar endpoint is plan-gated). USD events only, with impact
rating, consensus forecast, and previous print. Written to
data/calendar_cache.json.
"""

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull_data import _get  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "calendar_cache.json"
URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def main():
    events = json.loads(_get(URL).decode("utf-8", "replace"))
    us = [{"date": e["date"], "title": e["title"], "impact": e.get("impact"),
           "forecast": e.get("forecast") or None,
           "previous": e.get("previous") or None}
          for e in events if e.get("country") == "USD"]
    OUT.write_text(json.dumps(
        {"refreshed_at_utc": dt.datetime.utcnow().isoformat() + "Z",
         "source": URL, "events": us}, indent=1) + "\n")
    print(f"{len(us)} USD events -> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
