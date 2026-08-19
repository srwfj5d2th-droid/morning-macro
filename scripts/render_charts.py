#!/usr/bin/env python3
"""render_charts.py — matplotlib chart generation (§3.7, §9).

Chart discipline (§9): every chart maps to a series in macro_series.csv (or a
derived curve computed from it). Two classes:
  sparklines     fixed reference furniture for the recap strip and dashboard
  chart-of-day   one rotating annotated chart, editorially selected (§6.7)
  liquidity      Friday panel: fed_bs / on_rrp / tga / sofr, 90 observations

All output is SVG (self-contained, inline-embeddable). The regime accent color
(§9) threads through the line work.

Usage:
  render_charts.py sparklines --regime calm [--days 30] [--out briefs/assets/DATE]
  render_charts.py chart-of-day --series hy_oas --days 120 --regime stress \
      --title "..." --why "..." [--annotate "2026-08-14:label"] [--unit pct]
  render_charts.py liquidity --regime calm [--out ...]
"""

import argparse
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data" / "macro_series.csv"

REGIME_COLORS = {
    "calm": "#64707D",             # provisional — log to backlog for ratification
    "risk-on/confirming": "#2E7D5B",
    "confirming": "#2E7D5B",
    "risk-on/diverging": "#B07C1F",
    "diverging": "#B07C1F",
    "tightening": "#46586B",
    "stress": "#A63D2F",
}
INK = "#1F2430"
FAINT = "#9AA3AF"

SPARK_SERIES = ["spx", "ndx", "rut", "ust_10y", "hy_oas", "dxy", "wti", "gold",
                "ust_2y", "ust_30y", "tips_10y_real", "bkeven_10y", "ig_oas",
                "sofr", "on_rrp", "tga", "fed_bs", "smh", "copper"]


def load_series(col, days=None):
    """[(date, value)] non-null ascending; optionally last `days` observations.
    Derived curves s2s10/s3m10y are computed on the fly (chart discipline: they
    map directly to CSV columns)."""
    with open(CSV_PATH, newline="") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: r["date"])

    def col_obs(c):
        return [(r["date"], float(r[c])) for r in rows if r.get(c) not in ("", None)]

    if col == "s2s10":
        a, b = dict(col_obs("ust_10y")), dict(col_obs("ust_2y"))
        obs = [(d, (a[d] - b[d]) * 100) for d in sorted(a) if d in b]
    elif col == "s3m10y":
        a, b = dict(col_obs("ust_10y")), dict(col_obs("ust_3m"))
        obs = [(d, (a[d] - b[d]) * 100) for d in sorted(a) if d in b]
    else:
        obs = col_obs(col)
    return obs[-days:] if days else obs


def sparkline(obs, out_path, color):
    vals = [v for _, v in obs]
    fig, ax = plt.subplots(figsize=(1.35, 0.32), dpi=100)
    ax.plot(range(len(vals)), vals, color=color, linewidth=1.1,
            solid_capstyle="round")
    ax.plot([len(vals) - 1], [vals[-1]], "o", color=color, markersize=2.4)
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or abs(hi) * 0.01 or 1
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-0.5, len(vals) - 0.5)
    ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(out_path, format="svg", transparent=True)
    plt.close(fig)


def cmd_sparklines(args):
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    color = REGIME_COLORS.get(args.regime, INK)
    made = []
    for col in SPARK_SERIES:
        obs = load_series(col, days=args.days)
        if len(obs) < 2:
            continue
        p = out_dir / f"spark_{col}.svg"
        sparkline(obs, p, color)
        made.append(p.name)
    print(f"{len(made)} sparklines -> {out_dir}")
    return 0


def cmd_chart_of_day(args):
    obs = load_series(args.series, days=args.days)
    if len(obs) < 2:
        print(f"not enough observations for {args.series}", file=sys.stderr)
        return 2
    color = REGIME_COLORS.get(args.regime, INK)
    dates = [d for d, _ in obs]
    vals = [v for _, v in obs]

    fig, ax = plt.subplots(figsize=(7.0, 3.1), dpi=100)
    ax.plot(range(len(vals)), vals, color=color, linewidth=1.8,
            solid_capstyle="round", zorder=3)
    ax.plot([len(vals) - 1], [vals[-1]], "o", color=color, markersize=5, zorder=4)
    ax.fill_between(range(len(vals)), vals, min(vals), color=color, alpha=0.06)

    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(FAINT)
    ax.tick_params(colors=FAINT, labelsize=8, length=0)
    ticks = list(range(0, len(dates), max(1, len(dates) // 6)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([dates[i][5:] for i in ticks])
    ax.grid(axis="y", color=FAINT, alpha=0.25, linewidth=0.6)

    fmt = "{:,.2f}" if args.unit != "bp" else "{:+,.0f}bp"
    ax.annotate(fmt.format(vals[-1]),
                xy=(len(vals) - 1, vals[-1]), xytext=(8, 0),
                textcoords="offset points", fontsize=10, fontweight="bold",
                color=color, va="center")
    for a in args.annotate or []:
        date, _, label = a.partition(":")
        if date in dates:
            i = dates.index(date)
            ax.axvline(i, color=FAINT, linewidth=0.8, linestyle=":")
            ax.annotate(label or date, xy=(i, max(vals)), fontsize=8,
                        color=INK, ha="center", va="bottom")
    if args.title:
        ax.set_title(args.title, loc="left", fontsize=11, color=INK,
                     fontweight="bold", pad=10)
    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="svg", transparent=True)
    plt.close(fig)
    print(f"chart-of-day ({args.series}) -> {out}")
    return 0


def cmd_liquidity(args):
    color = REGIME_COLORS.get(args.regime, INK)
    panels = [("fed_bs", "Fed balance sheet ($M)"), ("on_rrp", "ON RRP ($B)"),
              ("tga", "TGA ($M)"), ("sofr", "SOFR (%)")]
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 3.6), dpi=100)
    for ax, (col, label) in zip(axes.flat, panels):
        obs = load_series(col, days=90)
        vals = [v for _, v in obs]
        if len(vals) >= 2:
            ax.plot(range(len(vals)), vals, color=color, linewidth=1.4)
            ax.plot([len(vals) - 1], [vals[-1]], "o", color=color, markersize=3)
        ax.set_title(label, loc="left", fontsize=8.5, color=INK)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(colors=FAINT, labelsize=7, length=0)
        ax.set_xticks([])
        ax.grid(axis="y", color=FAINT, alpha=0.25, linewidth=0.5)
    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="svg", transparent=True)
    plt.close(fig)
    print(f"liquidity panel -> {out}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sparklines")
    sp.add_argument("--regime", default="calm")
    sp.add_argument("--days", type=int, default=30)
    sp.add_argument("--out", default=str(REPO / "briefs" / "assets"))

    cd = sub.add_parser("chart-of-day")
    cd.add_argument("--series", required=True)
    cd.add_argument("--days", type=int, default=120)
    cd.add_argument("--regime", default="calm")
    cd.add_argument("--title", default="")
    cd.add_argument("--why", default="")   # carried into the brief by the builder
    cd.add_argument("--unit", default="")
    cd.add_argument("--annotate", action="append")
    cd.add_argument("--out", default=str(REPO / "briefs" / "assets" / "chart_of_day.svg"))

    lq = sub.add_parser("liquidity")
    lq.add_argument("--regime", default="calm")
    lq.add_argument("--out", default=str(REPO / "briefs" / "assets" / "liquidity.svg"))

    args = ap.parse_args(argv)
    return {"sparklines": cmd_sparklines, "chart-of-day": cmd_chart_of_day,
            "liquidity": cmd_liquidity}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
