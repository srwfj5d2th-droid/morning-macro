"""Tests for pull_data.py parsing, merge discipline, and fail-closed logic.
No network calls — everything runs on canned fixtures."""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pull_data import (TIER1_MAX_LAG, merge, parse_fred_csv,  # noqa: E402
                       parse_yahoo_chart, trading_days_between, validate)


def test_parse_fred_csv_skips_missing_values():
    text = "DATE,DGS10\n2026-08-14,4.68\n2026-08-15,.\n2026-08-17,4.72\n"
    assert parse_fred_csv(text) == {"2026-08-14": 4.68, "2026-08-17": 4.72}


def test_parse_fred_csv_observation_date_header():
    text = "observation_date,WALCL\n2026-08-12,6759955\n"
    assert parse_fred_csv(text) == {"2026-08-12": 6759955.0}


def test_parse_yahoo_chart_collapses_nulls_and_partial_bars():
    data = {"chart": {"result": [{
        "meta": {"gmtoffset": -14400},
        "timestamp": [1786973400, 1787059800, 1787100000, 1787103600],
        "indicators": {"quote": [{"close": [305.59, None, 309.0, 310.03]}]},
    }]}}
    out = parse_yahoo_chart(data)
    # bar 2 is null (dropped); bars 3+4 share a date -> last close wins
    assert list(out) == ["2026-08-17", "2026-08-18"]
    assert out["2026-08-18"] == 310.03


def test_merge_never_overwrites_existing_cell():
    rows = [{"date": "2026-08-18", "spx": "7693.26"}]
    filled, conflicts = merge(rows, {"2026-08-18": {"spx": 9999.0, "dxy": 99.63}})
    assert rows[0]["spx"] == "7693.26"     # kept, not clobbered
    assert rows[0]["dxy"] == 99.63         # empty cell filled
    assert conflicts == 1 and filled == 1


def test_merge_adds_new_dates():
    rows = []
    filled, _ = merge(rows, {"2026-08-18": {"spx": 7693.26}})
    assert filled == 1 and rows[0]["date"] == "2026-08-18"


def test_trading_days_between_skips_weekends():
    fri, mon = dt.date(2026, 8, 14), dt.date(2026, 8, 17)
    assert trading_days_between(fri, mon) == 1
    assert trading_days_between(fri, dt.date(2026, 8, 21)) == 5
    assert trading_days_between(mon, mon) == 0


def _rows_fresh():
    """A minimal fully-fresh Tier 1 row set dated 2026-08-18."""
    row = {"date": "2026-08-18", "spx": "7693.26"}
    for col in TIER1_MAX_LAG:
        row[col] = "1.0"
    return [row]


def test_validate_passes_when_fresh():
    ok, row_date, problems = validate(_rows_fresh())
    assert ok is True and row_date == "2026-08-18" and problems == []


def test_validate_fails_closed_on_missing_series():
    rows = _rows_fresh()
    del rows[0]["hy_oas"]
    ok, _, problems = validate(rows)
    assert ok is False
    assert any("hy_oas" in p for p in problems)


def test_validate_fails_closed_on_stale_series():
    # treasury dated 5 trading days before the market row -> stale (max 1)
    rows = [{"date": "2026-08-11", "ust_10y": "4.70"},
            {"date": "2026-08-18", "spx": "7693.26"}]
    for col in TIER1_MAX_LAG:
        if col != "ust_10y":
            rows[1][col] = "1.0"
    ok, _, problems = validate(rows)
    assert ok is False
    assert any("ust_10y" in p for p in problems)


def test_validate_allows_weekly_carry_forward():
    # fed_bs a week old is fine (max lag 10 trading days)
    rows = [{"date": "2026-08-12", "fed_bs": "6759955"},
            {"date": "2026-08-18", "spx": "7693.26"}]
    for col in TIER1_MAX_LAG:
        if col not in ("fed_bs",):
            rows[1][col] = "1.0"
    ok, _, problems = validate(rows)
    assert ok is True, problems
