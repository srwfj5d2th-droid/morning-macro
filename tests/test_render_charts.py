"""Tests for render_charts.py — charts must render valid SVG from the CSV."""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import render_charts  # noqa: E402


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Point the module at a temp CSV with 130 synthetic trading days."""
    csv_path = tmp_path / "macro_series.csv"
    cols = ["date", "spx", "ust_10y", "ust_2y", "ust_3m", "hy_oas",
            "fed_bs", "on_rrp", "tga", "sofr"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i in range(130):
            w.writerow({"date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                        "spx": 7000 + i, "ust_10y": 4.5 + i * 0.001,
                        "ust_2y": 4.1, "ust_3m": 3.9, "hy_oas": 2.7,
                        "fed_bs": 6.7e6, "on_rrp": 0.3, "tga": 9.0e5,
                        "sofr": 3.65})
    monkeypatch.setattr(render_charts, "CSV_PATH", csv_path)
    return tmp_path


def test_sparklines_render(fake_repo):
    out = fake_repo / "assets"
    rc = render_charts.main(["sparklines", "--regime", "calm",
                             "--out", str(out)])
    assert rc == 0
    made = list(out.glob("spark_*.svg"))
    assert made, "no sparklines produced"
    assert b"<svg" in made[0].read_bytes()


def test_chart_of_day_renders_with_annotation(fake_repo):
    out = fake_repo / "cod.svg"
    rc = render_charts.main(["chart-of-day", "--series", "ust_10y",
                             "--days", "60", "--regime", "stress",
                             "--title", "UST 10Y", "--unit", "pct",
                             "--annotate", "2026-02-01:CPI",
                             "--out", str(out)])
    assert rc == 0
    body = out.read_bytes()
    assert b"<svg" in body


def test_chart_of_day_derived_curve(fake_repo):
    out = fake_repo / "curve.svg"
    rc = render_charts.main(["chart-of-day", "--series", "s2s10",
                             "--days", "60", "--out", str(out)])
    assert rc == 0 and out.exists()


def test_chart_of_day_fails_on_unknown_series(fake_repo):
    rc = render_charts.main(["chart-of-day", "--series", "nope",
                             "--out", str(fake_repo / "x.svg")])
    assert rc == 2
    assert not (fake_repo / "x.svg").exists()


def test_liquidity_panel(fake_repo):
    out = fake_repo / "liq.svg"
    rc = render_charts.main(["liquidity", "--out", str(out)])
    assert rc == 0
    assert b"<svg" in out.read_bytes()


def test_regime_palette_matches_spec():
    assert render_charts.REGIME_COLORS["confirming"] == "#2E7D5B"
    assert render_charts.REGIME_COLORS["diverging"] == "#B07C1F"
    assert render_charts.REGIME_COLORS["tightening"] == "#46586B"
    assert render_charts.REGIME_COLORS["stress"] == "#A63D2F"
