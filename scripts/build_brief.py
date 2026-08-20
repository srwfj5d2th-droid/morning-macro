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
        ("ON RRP $B", "on_rrp", "lvl"), ("TGA $M", "tga", "big")]
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
            f'        <td style="padding:2px 0 2px 8px;">{spark(spark_dir, key)}</td>\n'
            f'      </tr>')
    return "\n".join(rows)


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

    cod = Path(content["chart_of_day_svg"]).read_text()
    cod = cod[cod.find("<svg"):]

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
    email = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Macro Brief — {content['brief_date']} — {content['regime_tag']}</title></head>
<body style="margin:0; background:#F4F2EE; font-family:-apple-system,'Segoe UI',sans-serif; color:#1F2430;">
<div style="max-width:560px; margin:0 auto; padding:24px 20px;">
<div style="display:inline-block; background:{color}; color:#FCFBF9; border-radius:2px; padding:3px 12px; font-family:Menlo,monospace; font-size:12px; text-transform:uppercase; letter-spacing:0.08em;">{content['regime_tag']} · {content['brief_date']}</div>
<p style="font-size:16px; font-weight:600; line-height:1.5; margin:14px 0;">{content['regime_line']}</p>
<table cellpadding="0" cellspacing="0" style="font-size:13px; border-collapse:collapse;">{''.join(email_rows)}</table>
<p style="font-size:13px; margin:16px 0 4px 0;"><a href="{content['page_url']}" style="color:{color}; font-weight:600;">Read the full brief →</a></p>
<p style="font-size:11px; color:#8A8F99;">{ath_line}</p>
</div></body></html>
"""
    email_out = REPO / "briefs" / f"{content['brief_date']}-email.html"
    email_out.write_text(email)

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
