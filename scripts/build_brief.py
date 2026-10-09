#!/usr/bin/env python3
"""build_brief.py — assemble the day's brief from template + state + content.

Inputs:
  templates/brief.html      layout with {{TOKENS}} (§9)
  data/state.json           computed state (compute_state.py) — sole source of
                            every number this script renders (§4C)
  content JSON (arg)        the morning session's prose: regime call, story,
                            movers, tier-3, concept, client lens, flags, claims
  sparkline dir (arg)       SVGs from render_charts.py, inlined

Output: briefs/<date>.html (self-contained) and briefs/<date>-email.html
(notification layer: regime pill + regime line + recap + link).

The model writes prose; this script renders every table cell from state.json
so no numeric claim can drift from the computed state.
"""

import argparse
import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

RECAP = [("S&P 500", "spx", "idx"), ("Nasdaq", "ndx", "idx"),
         ("Russell 2000", "rut", "idx"), ("UST 10Y", "ust_10y", "yld"),
         ("HY OAS", "hy_oas", "sprd"), ("DXY", "dxy", "lvl"),
         ("WTI", "wti", "usd"), ("Gold", "gold", "usd")]
DASH = [("UST 3M", "ust_3m", "yld"), ("UST 2Y", "ust_2y", "yld"),
        ("UST 10Y", "ust_10y", "yld"), ("UST 30Y", "ust_30y", "yld"),
        ("2s10s", "s2s10", "bp"), ("3m10s", "s3m10y", "bp"),
        ("10Y real (TIPS)", "tips_10y_real", "yld"),
        ("10Y breakeven", "bkeven_10y", "yld"), ("HY OAS", "hy_oas", "sprd"),
        ("IG OAS", "ig_oas", "sprd"), ("DXY", "dxy", "lvl"),
        ("SOFR", "sofr", "yld"), ("Fed bal. sheet $M", "fed_bs", "big"),
        ("ON RRP $B", "on_rrp", "bn"), ("TGA $M", "tga", "big")]
MONO = "font-family:'IBM Plex Mono', Menlo, monospace;"


def get(state, key):
    return state["series"].get(key) or state["derived"].get(key)


def fnum(v, kind):
    if v is None:
        return "—"
    if kind in ("yld", "sprd"):
        return f"{v:.2f}%"
    if kind == "bp":
        return f"{v:+.0f}bp" if v < 0 or v > 0 else "0bp"
    if kind == "big":
        return f"{v:,.0f}"
    if kind == "usd":
        return f"{v:,.2f}"
    return f"{v:,.2f}"


def fdelta(s, d, kind):
    if d is None:
        return "—"
    if kind in ("yld", "sprd"):
        return f"{d * 100:+.0f}bp"
    if kind == "bp":
        return f"{d:+.0f}bp"
    if kind == "big":
        return f"{d:+,.0f}"
    if kind == "bn":
        return f"{d:+,.2f}"
    prev = s["last"] - d
    return f"{100 * d / prev:+.2f}%" if prev else "—"


def fytd(s, kind):
    if kind in ("yld", "sprd"):
        return f"{s['ytd_abs'] * 100:+.0f}bp" if s["ytd_abs"] is not None else "—"
    if kind == "bp":
        return f"{s['ytd_abs']:+.0f}bp" if s["ytd_abs"] is not None else "—"
    return f"{s['ytd_pct']:+.2f}%" if s["ytd_pct"] is not None else "—"


def spark(spark_dir, key):
    p = spark_dir / f"spark_{key}.svg"
    if not p.exists():
        return ""
    svg = p.read_text()
    svg = svg[svg.find("<svg"):]
    return re.sub(r'(<svg[^>]*?)\s(width|height)="[^"]*"',
                  r"\1", svg, count=2)


def z_cell(s):
    if s.get("z_thin"):
        return '<span style="color:#8A8F99;">thin</span>'
    z = s["z120"]
    mark = " ⚑" if s["flag"] else ""
    return f"{z:+.2f}{mark}"


def pctile_cell(state, key):
    """§4F: where today's level ranks against real long-run history, not
    just the 120-day window. Shows all-time/trailing-30y side by side since
    pooling 60+ years of history can itself mask a regime shift (Jacob,
    2026-10-08) -- a reading can look unremarkable against the full pool
    while running hot against the last 30 years, or vice versa. '—' for
    series with no long-history source (Fed balance sheet, TGA, ON RRP,
    DXY); '*' flags the two series with only ~3 years available (no
    separate modern window to show, so a single number)."""
    ctx = state.get("long_history", {}).get(key)
    if ctx is None:
        return '<span style="color:#B9BEC7;">&mdash;</span>'
    if ctx.get("short_history"):
        return f'{ctx["pct_rank_all_time"]:.0f}*'
    modern = ctx.get("pct_rank_modern")
    if modern is None:
        return f'{ctx["pct_rank_all_time"]:.0f}'
    cell = f'{ctx["pct_rank_all_time"]:.0f}/{modern:.0f}'
    if ctx.get("regime_divergence"):
        return f'<span style="font-weight:600;">{cell}&dagger;</span>'
    return cell


def recap_rows(state, spark_dir, color, row_date):
    rows = []
    for label, key, kind in RECAP:
        s = get(state, key)
        lag = (f' <span style="color:#8A8F99; font-size:10.5px;">'
               f'({s["last_date"][5:]})</span>'
               if s["last_date"] != row_date else "")
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF;">\n'
            f'        <td style="padding:7px 0; font-weight:600;">{label}{lag}</td>\n'
            f'        <td style="padding:7px 8px; text-align:right; {MONO}">'
            f'{fnum(s["last"], kind)}</td>\n'
            f'        <td style="padding:7px 8px; text-align:right; {MONO}">'
            f'{fdelta(s, s["d1"], kind)}</td>\n'
            f'        <td style="padding:7px 8px; text-align:right; {MONO}">'
            f'{fytd(s, kind)}</td>\n'
            f'        <td style="padding:2px 0 2px 8px;">{spark(spark_dir, key)}</td>\n'
            f'      </tr>')
    return "\n".join(rows)


def dash_rows(state, spark_dir, color, row_date):
    rows = []
    for label, key, kind in DASH:
        s = get(state, key)
        if s is None:
            continue
        flagged = s.get("flag")
        bg = f' background:{color}14;' if flagged else ""
        lag = (f' <span style="color:#8A8F99; font-size:10px;">'
               f'({s["last_date"][5:]})</span>'
               if s["last_date"] != row_date else "")
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF;{bg}">\n'
            f'        <td style="padding:6px 0 6px 4px;">{label}{lag}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">'
            f'{fnum(s["last"], kind)}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">'
            f'{fdelta(s, s["d1"], kind)}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">'
            f'{fdelta(s, s["d5"], kind)}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO} '
            f'{"font-weight:600; color:" + color + ";" if flagged else ""}">'
            f'{z_cell(s)}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">'
            f'{pctile_cell(state, key)}</td>\n'
            f'        <td style="padding:2px 0 2px 8px;">{spark(spark_dir, key)}</td>\n'
            f'      </tr>')
    return "\n".join(rows)


# ---- §4F "Today in history" tables (2026-10-09) -------------------------
# Every cell below is read from state.json's long_history / joint_history /
# market_history blocks (scripts/history_context.py). The model writes the
# prose around them, never the cells.

HIST_SERIES = [("UST 3M", "ust_3m", "yld"), ("UST 2Y", "ust_2y", "yld"),
               ("UST 10Y", "ust_10y", "yld"), ("UST 30Y", "ust_30y", "yld"),
               ("2s10s", "s2s10", "bp"), ("3m10s", "s3m10y", "bp"),
               ("10Y real (TIPS)", "tips_10y_real", "yld"),
               ("10Y breakeven", "bkeven_10y", "yld"),
               ("SOFR (fed funds pre-2018)", "sofr", "yld"),
               ("HY OAS", "hy_oas", "sprd"), ("IG OAS", "ig_oas", "sprd"),
               ("IG proxy: Baa − 10Y", "baa_10y_spread", "pp"),
               ("DXY", "dxy", "lvl")]
JOINT_SHORT = {"tips_10y_real": ("10Y real", "%"), "baa_10y_spread": ("Baa−10Y", "pp"),
               "ust_10y": ("10Y", "%"), "dxy": ("DXY", ""),
               "spx_dd": ("S&P from record", "%")}
MUTED = "color:#8A8F99;"


def _mon_yr(d):
    import datetime as _dt
    return _dt.date.fromisoformat(d).strftime("%b %Y")


def _mon_d_yr(d):
    import datetime as _dt
    x = _dt.date.fromisoformat(d)
    return f"{x.strftime('%b')} {x.day}, {x.year}"


def _ago(years):
    return f"{years:.0f} yrs ago" if years >= 1.95 else f"{years:.1f} yr ago"


def _signed(v, nd=1, unit="%"):
    return f"{'−' if v < 0 else '+'}{abs(v):.{nd}f}{unit}"


def _backdrop_text(p):
    bits = [o["name"] for o in p.get("overlapping", [])][:2]
    recs = p.get("recessions_began_during_or_within_24m_after") or []
    for r in recs:
        if r not in bits:
            bits.append(f"recession began within 2 yrs ({r})")
    b = p.get("backdrop_at_end") or {}
    if "fed_funds" in b:
        bits.append(f"fed funds {b['fed_funds']:.2f}% "
                    f"({_signed(b['fed_funds_change_prior_12m'], 2, 'pt')} over prior yr)")
    if "spx_return_next_12m_pct" in b:
        bits.append(f"S&amp;P next 12 mo {_signed(b['spx_return_next_12m_pct'])} "
                    f"(worst point {_signed(b['spx_worst_drawdown_next_12m_pct'])})")
    return "; ".join(bits) if bits else '<span style="' + MUTED + '">no named episode</span>'


def history_rows(state, row_date):
    lh = state.get("long_history", {})
    rows = []
    for label, key, kind in HIST_SERIES:
        ctx = lh.get(key)
        if not ctx:
            continue
        pe = ctx.get("prior_episode") or {}
        s = get(state, key) if key != "baa_10y_spread" else None
        if s:
            today = fnum(s["last"], kind if kind != "pp" else "sprd")
            if kind == "bp":
                today = fnum(s["last"], "bp")
            lag_d = s["last_date"]
        else:
            today = f"{pe.get('level', 0):.2f}pp"
            lag_d = ctx["end_date"]
        lag = (f' <span style="{MUTED} font-size:10px;">({lag_d[5:]})</span>'
               if lag_d != row_date else "")
        sym = "≥" if pe.get("side") == "high" else "≤"
        if ctx.get("short_history"):
            last = (f'<span style="{MUTED}">only ~{ctx["years"]:.0f} yrs of data '
                    f'here &mdash; no long-run comparison*</span>')
            then = f'<span style="{MUTED}">&mdash;</span>'
        elif pe.get("prior") is None:
            last = (f'<strong>{sym} never before</strong> '
                    f'<span style="{MUTED}">(data since {pe["history_start"][:4]})</span>')
            then = f'<span style="{MUTED}">no precedent in this series</span>'
        else:
            p = pe["prior"]
            last = f'{sym} {_mon_yr(p["end"])} <span style="{MUTED}">· {_ago(p["years_before_as_of"])}</span>'
            if pe.get("current_run_years", 0) >= 1:
                last += (f'<br><span style="{MUTED} font-size:11px;">here on and off '
                         f'since {_mon_yr(pe["current_run_start"])}</span>')
            if ctx.get("exclude_note"):
                last += (f'<br><span style="{MUTED} font-size:11px;">'
                         f'{html.escape(ctx["exclude_note"])}</span>')
            then = _backdrop_text(p)
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF; vertical-align:top;">\n'
            f'        <td style="padding:6px 0;">{label}{lag}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO} white-space:nowrap;">{today}</td>\n'
            f'        <td style="padding:6px 6px;">{last}</td>\n'
            f'        <td style="padding:6px 0 6px 6px; font-size:12px; color:#39404E;">{then}</td>\n'
            f'      </tr>')
    return "\n".join(rows)


def _joint_label(ctx):
    parts = []
    for c in ctx["conditions"]:
        name, unit = JOINT_SHORT.get(c["key"], (c["key"], ""))
        sym = "≥" if c["side"] == "high" else "≤"
        if c["key"] == "spx_dd":
            parts.append(f"S&amp;P within {abs(c['value']):.1f}% of record")
        elif unit == "pp":
            parts.append(f"{name} {sym} {c['value']:.2f}pp")
        elif unit == "%":
            parts.append(f"{name} {sym} {c['value']:.2f}%")
        else:
            parts.append(f"{name} {sym} {c['value']:.2f}")
    return " &amp; ".join(parts)


def joint_rows(state):
    rows = []
    for name, ctx in state.get("joint_history", {}).items():
        if ctx.get("prior") is None:
            last = (f'<strong>never before</strong> <span style="{MUTED}">(shared data since '
                    f'{ctx["shared_history_start"][:4]}; {ctx["share_of_days_pct"]:.2f}% of days, '
                    f'all in the current run)</span>')
            then = f'<span style="{MUTED}">no precedent</span>'
        else:
            p = ctx["prior"]
            last = (f'{_mon_yr(p["end"])} <span style="{MUTED}">· {_ago(p["years_before_as_of"])}; '
                    f'{ctx["share_of_days_pct"]:.1f}% of days since {ctx["shared_history_start"][:4]}</span>')
            then = _backdrop_text(p)
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF; vertical-align:top;">\n'
            f'        <td style="padding:6px 0;">{_joint_label(ctx)}</td>\n'
            f'        <td style="padding:6px 6px;">{last}</td>\n'
            f'        <td style="padding:6px 0 6px 6px; font-size:12px; color:#39404E;">{then}</td>\n'
            f'      </tr>')
    return "\n".join(rows)


def market_rows(state):
    rows = []
    for key, ctx in state.get("market_history", {}).items():
        mv, dd, ytd = ctx["move"], ctx["drawdown"], ctx.get("ytd")
        freq = (f'~{mv["per_year_recent"]:.0f}'
                f'<span style="{MUTED}"> ({"30 yrs" if mv["per_year_window_years"] >= 30 else "since " + ctx["history_start"][:4]})</span>'
                if mv.get("per_year_recent") is not None else "&mdash;")
        lb = mv.get("last_at_least_this_big")
        word = "drop" if mv["direction"] == "down" else "gain"
        last = (f'{_mon_d_yr(lb["date"])} <span style="{MUTED}">({_signed(lb["pct"], 2)}, '
                f'{lb["trading_days_ago"]} sessions ago)</span>'
                if lb else f'<strong>biggest {word} on record</strong>')
        ytd_txt = (f'{_signed(ytd["pct"])} <span style="{MUTED}">· #{ytd["rank_among_years"]} '
                   f'of {ytd["n_years"]} (median {_signed(ytd["median_prior_years_pct"])})</span>'
                   if ytd else "&mdash;")
        rec = ("at record" if dd["pct_below_record"] > -0.05 else
               f'{_signed(dd["pct_below_record"])} <span style="{MUTED}">({_mon_yr(dd["record_date"])})</span>')
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF; vertical-align:top;">\n'
            f'        <td style="padding:6px 0;">{html.escape(ctx["label"])}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">{_signed(mv["pct"], 2)}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">{freq}</td>\n'
            f'        <td style="padding:6px 6px;">{last}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">{ytd_txt}</td>\n'
            f'        <td style="padding:6px 0 6px 6px; text-align:right; {MONO}">{rec}</td>\n'
            f'      </tr>')
    return "\n".join(rows)


HISTORY_NOTE = (
    "How to read: <strong>Last time</strong> = the most recent stretch <em>before</em> the "
    "current one when the series was at least this high (&ge;) or this low (&le;); readings "
    "less than a year apart count as one stretch, so this is the last genuinely separate era, "
    "not last month. Side is set by where today sits against the last 30 years. "
    "<strong>Back then</strong> = named episodes overlapping that stretch, whether a recession "
    "began during it or within 2 years after, the fed funds rate when it ended, and the "
    "S&amp;P 500 over the following 12 months &mdash; one past instance each, not a forecast. "
    "<strong>Days/yr this big</strong> = average days per year with a same-direction move at "
    "least as large. <strong>YTD vs. past years</strong> = this year's gain through today's "
    "date ranked against every prior year through the same date. Sources: FRED (Treasuries "
    "1962+, TIPS/breakeven 2003+, fed funds 1954+, Moody's Baa 1986+, NBER recessions), Yahoo "
    "(S&amp;P 500 1928+, Nasdaq 1971+, DXY 1971+, WTI and gold futures 2000+). "
    "*HY/IG OAS: only ~3 years reachable here; the Baa&minus;10Y row is the long-run "
    "investment-grade proxy (direction and timing only, never magnitude).")


def history_markdown(state, row_date):
    """Same three tables as markdown, for the twin (briefs/<date>.md)."""
    strip = re.compile(r"<[^>]+>")

    def md(cell):
        return (html.unescape(strip.sub("", cell.replace("<br>", " — ")))
                .replace("|", "/").strip())

    def table(header, html_rows):
        out = ["| " + " | ".join(header) + " |",
               "|" + "|".join("---" for _ in header) + "|"]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_rows, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            out.append("| " + " | ".join(md(c) for c in cells) + " |")
        return "\n".join(out)

    return "\n\n".join([
        table(["Series", "Today", "Last time", "Back then"],
              history_rows(state, row_date)),
        table(["Together", "Last time", "Back then"], joint_rows(state)),
        table(["Market", "Today", "Days/yr this big", "Last move this big",
               "YTD vs. past years", "From record"], market_rows(state)),
        md(HISTORY_NOTE)])


def _html_to_md(fragment):
    """The content files' prose is simple inline-styled HTML; render it as
    markdown for the twin (briefs/<date>.md) so the twin can't drift."""
    s = fragment
    s = re.sub(r"<h[23][^>]*>(.*?)</h[23]>", r"\n## \1\n", s, flags=re.S)
    s = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: "- " + m.group(1).strip() + "\n", s, flags=re.S)
    s = re.sub(r"<(strong|b)>(.*?)</\1>", r"**\2**", s, flags=re.S)
    s = re.sub(r"<(em|i)>(.*?)</\1>", r"*\2*", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", " ", s)
    s = re.sub(r"</p>|</div>|</ul>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _md_table(header, html_rows):
    strip = re.compile(r"<[^>]+>")
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" if i == 0 else "---:" for i in range(len(header))) + "|"]
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_rows, re.S):
        cells = [html.unescape(strip.sub("", c)).replace("|", "/").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        out.append("| " + " | ".join(c for c in cells[:len(header)]) + " |")
    return "\n".join(out)


def markdown_twin(content, state, spark_dir, row_date, ath_line, todays_events):
    color = content["regime_color"]
    parts = [
        f"# Morning Macro Brief — {content['date_long']} — [{content['regime_tag']}]",
        f"**Regime line:** {_html_to_md(content['regime_line'])}",
        f"## Recap ({row_date} close)",
        _md_table(["Series", "Close", "1D", "YTD"],
                  recap_rows(state, spark_dir, color, row_date)),
        f"{ath_line.split(':')[0]}: **{ath_line.split(':', 1)[1].strip()}**",
        _html_to_md(content.get("claims_section_html", "")),
        "## The story", _html_to_md(content["story_html"]),
        "## Rates · credit · liquidity (obs dates labeled where lagged)",
        _md_table(["Series", "Level", "1D", "5D", "z(120d)", "%ile all/30y"],
                  dash_rows(state, spark_dir, color, row_date)),
        _html_to_md(content["dashboard_lag_note"]),
        _html_to_md(content["dashboard_interp_html"]),
    ]
    if state.get("long_history"):
        parts += ["## Today in history", _html_to_md(content.get("history_html", "")),
                  history_markdown(state, row_date)]
    parts += [
        "## Movers", _html_to_md(content["movers_html"]),
        "## Chart of the day",
        f"Why this chart today — {_html_to_md(content['chart_of_day_why'])}",
        "## AI capex & financing cycle",
        _html_to_md(content["tier3_html"].replace("[[LIQUIDITY_SVG]]", "")),
        "## Today's calendar",
        "\n".join(f"- {e['date'][11:16]} ET — {e['title']}"
                  + (f" · cons {e['forecast']}" if e.get("forecast") else "")
                  + (f" · prev {e['previous']}" if e.get("previous") else "")
                  for e in todays_events) or "- (no scheduled releases)",
        _html_to_md(content.get("calendar_note_html", "")),
        f"## Concept of the day — {content['concept_unit']}",
        f"**{content['concept_title']}.** {_html_to_md(content['concept_html'])}",
        f"**Client translation:** \"{content['client_translation']}\"",
        "## Client lens", _html_to_md(content["client_lens_html"]),
        "## Flags", _html_to_md(content["flags_html"]),
    ]
    return "\n\n".join(p for p in parts if p.strip()) + "\n"


def calendar_rows(events, row_date_next):
    out = []
    for e in events:
        imp = (e.get("impact") or "").lower()
        dot = {"high": "#A63D2F", "medium": "#B07C1F"}.get(imp, "#B9BEC7")
        fc = f' · cons {html.escape(str(e["forecast"]))}' if e.get("forecast") else ""
        pv = f' · prev {html.escape(str(e["previous"]))}' if e.get("previous") else ""
        t = e["date"][11:16] if len(e.get("date", "")) > 11 else ""
        out.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF;">\n'
            f'        <td style="padding:6px 8px 6px 0; white-space:nowrap; {MONO} '
            f'font-size:12.5px;">{t} ET</td>\n'
            f'        <td style="padding:6px 0;"><span style="display:inline-block; '
            f'width:8px; height:8px; border-radius:50%; background:{dot}; '
            f'margin-right:8px;"></span>{html.escape(e["title"])}'
            f'<span style="color:#6B7280; font-size:12px;">{fc}{pv}</span></td>\n'
            f'      </tr>')
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--sparks", required=True)
    ap.add_argument("--date", required=True)
    args = ap.parse_args()

    state = json.loads((REPO / "data" / "state.json").read_text())
    content = json.loads(Path(args.content).read_text())
    spark_dir = Path(args.sparks)
    template = (REPO / "templates" / "brief.html").read_text()
    color = content["regime_color"]
    row_date = state["row_date"]

    # §4F (2026-10-09): the historical-context section is fixed furniture.
    # A brief built while long-run history is available must carry its prose
    # and its one-line email headline -- refuse to build otherwise, so a
    # scheduled run can't quietly ship without it again.
    if state.get("long_history"):
        missing = [k for k in ("history_html", "history_headline")
                   if not str(content.get(k, "")).strip()]
        if missing:
            raise SystemExit(
                f"build_brief: content is missing {missing} -- every brief carries "
                f"a 'Today in history' section (CLAUDE.md §4F, ROUTINE.md step 8). "
                f"Write it from state.json long_history/joint_history/market_history.")

    cod = Path(content["chart_of_day_svg"]).read_text()
    cod = cod[cod.find("<svg"):]

    # Friday liquidity panel (§9): inline into the Tier 3 section where the
    # content marks a [[LIQUIDITY_SVG]] slot
    if content.get("liquidity_svg_path"):
        liq = Path(content["liquidity_svg_path"]).read_text()
        content["tier3_html"] = content["tier3_html"].replace(
            "[[LIQUIDITY_SVG]]", liq[liq.find("<svg"):])

    ath = state["derived"]["spx_ath"]
    ath_line = (f"S&P 500 distance from all-time closing high "
                f"({ath['ath_date']}, {ath['ath']:,.2f}): {ath['dist_pct']:+.2f}%")

    claims_html = content.get("claims_section_html", "")

    cal = json.loads((REPO / "data" / "calendar_cache.json").read_text())
    todays = [e for e in cal["events"]
              if e.get("date", "").startswith(content["brief_date"])]

    filled = template
    for token, value in {
        "{{DATE_ISO}}": content["brief_date"],
        "{{DATE_LONG}}": content["date_long"],
        "{{MASTHEAD_TITLE}}": content["masthead_title"],
        "{{REGIME_TAG}}": content["regime_tag"],
        "{{REGIME_COLOR}}": color,
        "{{REGIME_LINE}}": content["regime_line"],
        "{{RECAP_ROWS}}": recap_rows(state, spark_dir, color, row_date),
        "{{ATH_LINE}}": ath_line,
        "{{CLAIMS_SECTION}}": claims_html,
        "{{STORY_HTML}}": content["story_html"],
        "{{DASHBOARD_ROWS}}": dash_rows(state, spark_dir, color, row_date),
        "{{DASHBOARD_LAG_NOTE}}": content["dashboard_lag_note"],
        "{{DASHBOARD_INTERP}}": content["dashboard_interp_html"],
        "{{HISTORY_HTML}}": content.get("history_html", ""),
        "{{HISTORY_ROWS}}": history_rows(state, row_date),
        "{{JOINT_ROWS}}": joint_rows(state),
        "{{MARKET_ROWS}}": market_rows(state),
        "{{HISTORY_NOTE}}": HISTORY_NOTE,
        "{{MOVERS_HTML}}": content["movers_html"],
        "{{COD_SVG}}": cod,
        "{{COD_WHY}}": content["chart_of_day_why"],
        "{{TIER3_HTML}}": content["tier3_html"],
        "{{CALENDAR_ROWS}}": calendar_rows(todays, content["brief_date"]),
        "{{CALENDAR_NOTE}}": content.get("calendar_note_html", ""),
        "{{CONCEPT_UNIT}}": content["concept_unit"],
        "{{CONCEPT_TITLE}}": content["concept_title"],
        "{{CONCEPT_HTML}}": content["concept_html"],
        "{{CLIENT_TRANSLATION}}": content["client_translation"],
        "{{CLIENT_LENS_HTML}}": content["client_lens_html"],
        "{{FLAGS_HTML}}": content["flags_html"],
        "{{PULL_STAMP}}": content["pull_stamp"],
        "{{PROVENANCE_NOTE}}": content.get("provenance_note", ""),
    }.items():
        filled = filled.replace(token, value)

    out = REPO / "briefs" / f"{content['brief_date']}.html"
    out.write_text(filled)

    # ---- email notification layer (§2): pill, regime line, recap, link ----
    email_rows = []
    for label, key, kind in RECAP:
        s = get(state, key)
        email_rows.append(
            f'<tr><td style="padding:3px 12px 3px 0;">{label}</td>'
            f'<td style="padding:3px 8px; text-align:right; font-family:Menlo,'
            f'monospace;">{fnum(s["last"], kind)}</td>'
            f'<td style="padding:3px 0; text-align:right; font-family:Menlo,'
            f'monospace;">{fdelta(s, s["d1"], kind)}</td></tr>')
    history_email = (
        f'<p style="font-size:14px; line-height:1.5; margin:0 0 14px 0; '
        f'border-left:3px solid {color}; padding-left:10px;"><span style="font-family:Menlo,'
        f'monospace; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; '
        f'color:#6B7280;">In history</span><br>{content["history_headline"]}</p>'
        if content.get("history_headline") else "")
    email = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Macro Brief — {content['brief_date']} — {content['regime_tag']}</title></head>
<body style="margin:0; background:#F4F2EE; font-family:-apple-system,'Segoe UI',sans-serif; color:#1F2430;">
<div style="max-width:560px; margin:0 auto; padding:24px 20px;">
<div style="display:inline-block; background:{color}; color:#FCFBF9; border-radius:2px; padding:3px 12px; font-family:Menlo,monospace; font-size:12px; text-transform:uppercase; letter-spacing:0.08em;">{content['regime_tag']} · {content['brief_date']}</div>
<p style="font-size:16px; font-weight:600; line-height:1.5; margin:14px 0;">{content['regime_line']}</p>
{history_email}<table cellpadding="0" cellspacing="0" style="font-size:13px; border-collapse:collapse;">{''.join(email_rows)}</table>
<p style="font-size:13px; margin:16px 0 4px 0;"><a href="{content['page_url']}" style="color:{color}; font-weight:600;">Read the full brief →</a></p>
<p style="font-size:11px; color:#8A8F99;">{ath_line}</p>
</div></body></html>
"""
    email_out = REPO / "briefs" / f"{content['brief_date']}-email.html"
    email_out.write_text(email)

    # markdown twin (§3 step 8), generated from the same content + state as
    # the page so the two can't drift (2026-10-09; previously hand-written)
    md_out = REPO / "briefs" / f"{content['brief_date']}.md"
    md_out.write_text(markdown_twin(content, state, spark_dir, row_date,
                                    ath_line, todays))
    print(f"markdown twin -> {md_out}")

    # ---- site index: redirect to the latest brief, list the archive ----
    dates = sorted((p.stem for p in (REPO / "briefs").glob("????-??-??.html")),
                   reverse=True)
    links = "\n".join(
        f'<li><a href="briefs/{d}.html" style="color:#46586B;">{d}</a></li>'
        for d in dates)
    (REPO / "index.html").write_text(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="robots" content="noindex, nofollow">
<meta http-equiv="refresh" content="0; url=briefs/{dates[0]}.html">
<title>Morning Macro Brief</title></head>
<body style="font-family:Georgia,serif; max-width:640px; margin:40px auto;">
<p>Redirecting to the latest brief: <a href="briefs/{dates[0]}.html">{dates[0]}</a></p>
<p>Archive:</p><ul>{links}</ul>
</body></html>
""")
    print(f"brief -> {out}\nemail -> {email_out}\nindex -> latest {dates[0]}\n"
          f"size: {out.stat().st_size/1024:.0f}KB")


if __name__ == "__main__":
    main()
