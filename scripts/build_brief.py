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

from history_context import ordinal, pct_ordinal, reading_units

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
    series with no long-history source (Fed balance sheet, TGA, ON RRP);
    '*' flags the two series with only ~3 years available; a plain single
    number is a record under ~35 years (TIPS, breakeven), too short for a
    separate 30-year view."""
    ctx = state.get("long_history", {}).get(key)
    if ctx is None:
        return '<span style="color:#B9BEC7;">&mdash;</span>'
    if ctx.get("short_history"):
        return f'{_pct(ctx["pct_rank_all_time"])}*'
    modern = ctx.get("pct_rank_modern")
    if modern is None:
        return _pct(ctx["pct_rank_all_time"])
    cell = f'{_pct(ctx["pct_rank_all_time"])}/{_pct(modern)}'
    if ctx.get("regime_divergence"):
        return f'<span style="font-weight:600;">{cell}&dagger;</span>'
    return cell


def _pct(p):
    """A percentile cell: whole numbers, but one decimal near the edges so
    99.7 never reads as a record ('100')."""
    return f"{p:.1f}" if (p >= 99 or p <= 1) else f"{p:.0f}"


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


WEEKLY_KEYS = ("fed_bs", "tga")


def _wk(key, span):
    """Weekly series: the 1D/5D columns hold one- and five-week changes."""
    return (f' <span style="color:#8A8F99; font-size:10px;">{span}</span>'
            if key in WEEKLY_KEYS else "")


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
            f'{fdelta(s, s["d1"], kind)}{_wk(key, "1w")}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">'
            f'{fdelta(s, s["d5"], kind)}{_wk(key, "5w")}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO} '
            f'{"font-weight:600; color:" + color + ";" if flagged else ""}">'
            f'{z_cell(s)}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">'
            f'{pctile_cell(state, key)}</td>\n'
            f'        <td style="padding:2px 0 2px 8px;">{spark(spark_dir, key)}</td>\n'
            f'      </tr>')
    return "\n".join(rows)


# ---- §4F "Today in history" (v2, 2026-10-09) ----------------------------
# Every cell and every History-check sentence below is read from state.json
# (history_digest / long_history / then_vs_now / rate_pace / curve_cycles /
# history_pairs / market_history / cycle_map, built by history_context.py and
# history_digest.py). The model writes only the interpretation (history_html).

MUTED = "color:#8A8F99;"
HIST_REF = [("UST 2Y", "ust_2y", "yld"), ("UST 10Y", "ust_10y", "yld"),
            ("UST 30Y", "ust_30y", "yld"), ("10Y real (TIPS)", "tips_10y_real", "yld"),
            ("10Y real (Cleveland model, monthly)", "real10_cleveland", "yld"),
            ("10Y breakeven", "bkeven_10y", "yld"),
            ("Term premium (Kim-Wright model)", "kw_tp10", "yld"),
            ("SOFR (vs. fed funds history)", "sofr", "yld"),
            ("2s10s", "s2s10", "bp"), ("3m10y", "s3m10y", "bp"),
            ("HY OAS", "hy_oas", "sprd"), ("IG OAS", "ig_oas", "sprd"),
            ("IG proxy: Baa − 10Y", "baa_10y_spread", "pp"),
            ("DXY", "dxy", "lvl"), ("30Y mortgage (weekly)", "mortgage30", "yld")]


def _mon_yr(d):
    import datetime as _dt
    return _dt.date.fromisoformat(d).strftime("%b %Y")


def _mon_d_yr(d):
    import datetime as _dt
    x = _dt.date.fromisoformat(d)
    return f"{x.strftime('%b')} {x.day}, {x.year}"


def _mon_d_rel(d, as_of):
    """'Oct 5' in the as-of year, 'Dec 30, 2025' otherwise."""
    full = _mon_d_yr(d)
    return full[:-6] if d[:4] == as_of[:4] else full


def _signed(v, nd=1, unit="%"):
    return f"{'−' if v < 0 else '+'}{abs(v):.{nd}f}{unit}"


def _ref_value(ctx, kind):
    v = ctx.get("latest_value")
    if v is None:
        return "&mdash;"
    if kind == "bp":
        return f"{v * 100:+.0f}bp"
    if kind == "pp":
        return f"{v:.2f}pp"
    if kind == "lvl":
        return f"{v:.2f}"
    return f"{v:.2f}%"


def _last_time_cell(ctx, as_of):
    lb = ctx.get("lookback") or {}
    if ctx.get("short_history"):
        return f'<span style="{MUTED}">only ~{ctx["years"]:.0f} yrs of data here*</span>'
    if not lb.get("gated"):
        return f'<span style="{MUTED}">mid-range &mdash; no &ldquo;last time&rdquo; claim</span>'
    if lb.get("gap_sensitive"):
        return (f'<span style="{MUTED}">answer depends on how stretches are grouped '
                f'&mdash; not claimed</span>')
    hi = lb["side"] == "high"
    if lb.get("record"):
        return f'<strong>beyond every reading since {lb["history_start"][:4]}</strong>'
    if lb.get("run_is_record"):
        return (f'<strong>this run set a record</strong> <span style="{MUTED}">('
                f'{"high" if hi else "low"} {lb["run_extreme"]:.2f}, {_mon_d_rel(lb["run_extreme_date"], as_of)}; '
                f'today is {"below" if hi else "above"} it)</span>')
    lt, ls = lb.get("last_touch"), lb.get("last_sustained")
    sym = "&ge;" if hi else "&le;"
    if not lt:
        return f'<span style="{MUTED}">not before (data since {lb["history_start"][:4]})</span>'
    cad = lb.get("cadence", "daily")
    cell = f'{sym} {_mon_yr(lt["end"])}'
    if lt.get("brief", lt["n_obs"] < 20):
        cell += f' <span style="{MUTED}">(briefly, {reading_units(lt["n_obs"], cad)})</span>'
        if ls and ls["end"] != lt["end"]:
            cell += f'<br><span style="{MUTED} font-size:11px;">routinely until {_mon_yr(ls["end"])}</span>'
    if (lb.get("current_run_years") or 0) >= 1:
        cell += f'<br><span style="{MUTED} font-size:11px;">this run began {_mon_yr(lb["current_run_start"])}</span>'
    if not lb.get("today_is_run_extreme", True) and lb.get("run_extreme_prior"):
        cell += (f'<br><span style="{MUTED} font-size:11px;">run {"high" if hi else "low"} '
                 f'{lb["run_extreme"]:.2f} ({_mon_d_rel(lb["run_extreme_date"], as_of)}) last matched '
                 f'{_mon_yr(lb["run_extreme_prior"]["end"])}</span>')
    if ctx.get("exclude_note"):
        cell += f'<br><span style="{MUTED} font-size:11px;">2002&ndash;06 excluded (30Y bond suspended)</span>'
    return cell


def history_check_html(state):
    if state.get("history_error"):
        return ('    <p style="font-size:14px; margin:0 0 10px 0; color:#39404E;">History check: '
                'the long-run history files failed to load today, so this brief makes no '
                'historical comparisons (&sect;4). Logged: '
                f'{html.escape(state["history_error"])}.</p>')
    facts = state.get("history_digest") or []
    if not facts:
        gated = [k for k, c in (state.get("long_history") or {}).items()
                 if (c.get("lookback") or {}).get("gated")]
        msg = ("no long-run fact cleared this box's bar today: the readings in a historical tail "
               "were last this far out within the past five years, or the answer depends on how "
               "readings are grouped (see the table below)." if gated else
               "nothing in today's data sits in a historical tail &mdash; every tracked series is "
               "mid-range against its own long-run record.")
        return ('    <p style="font-size:14px; margin:0 0 10px 0; color:#39404E;">History check: '
                f'{msg}</p>')
    items = "\n".join(f'        <li style="margin-bottom:7px;">{html.escape(f["sentence"])}</li>'
                      for f in facts)
    return ('    <div style="background:#F7F5F1; border-left:3px solid #46586B; padding:10px 14px 4px 14px; margin:0 0 14px 0;">\n'
            '      <div style="font-family:\'IBM Plex Mono\', Menlo, monospace; font-size:10.5px; '
            'letter-spacing:0.14em; text-transform:uppercase; color:#6B7280; margin-bottom:6px;">'
            'History check &middot; script-written from the data</div>\n'
            f'      <ul style="font-size:14px; margin:0; padding-left:18px; color:#1F2430;">\n{items}\n      </ul>\n'
            '    </div>')


def then_now_html(state):
    tn = state.get("then_vs_now")
    if not tn or not tn.get("rows"):
        return ""
    rows = []
    for r in tn["rows"]:
        def f(x):
            if x is None:
                return "&mdash;"
            v = x["value"]
            if r["unit"] == "bp":
                return f"{v * 100:+.0f}bp"
            if r["unit"] == "pp":
                return f"{v:.2f}pp"
            if r["unit"] == "pctpt":
                return _signed(v)
            return f"{v:.2f}%"
        gap = ""
        if r.get("gap") is not None and r.get("then"):
            # from the values as displayed, so the bracket always reconciles
            nd = 1 if r["unit"] == "pctpt" else 2
            g = round(r["now"]["value"], nd) - round(r["then"]["value"], nd)
            gap = {"bp": f"{g * 100:+.0f}bp", "pctpt": f"{g:+.1f} pts"}.get(r["unit"], f"{g:+.2f} pt")
            gap = f' <span style="{MUTED}">({gap.replace("-", "&minus;")})</span>'
        call = ("&mdash;" if r["similar"] is None else
                ("similar" if r["similar"] else '<strong>different</strong>')) + gap
        now_lag = (f' <span style="{MUTED} font-size:10px;">({r["now"]["date"][5:]})</span>'
                   if r["now"]["date"] != state["row_date"] else "")
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF;">\n'
            f'        <td style="padding:5px 0;">{html.escape(r["label"])}</td>\n'
            f'        <td style="padding:5px 6px; text-align:right; {MONO}">{f(r["then"])}</td>\n'
            f'        <td style="padding:5px 6px; text-align:right; {MONO}">{f(r["now"])}{now_lag}</td>\n'
            f'        <td style="padding:5px 0 5px 6px; text-align:right; font-size:12px;">{call}</td>\n'
            f'      </tr>')
    return (f'    <p style="font-size:13px; font-weight:600; margin:16px 0 4px 0;">Then vs. now &mdash; '
            f'{_mon_d_yr(tn["then_date"])} (the last time before this run) vs. today</p>\n'
            '    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%; border-collapse:collapse; font-size:12.5px;">\n'
            '      <tr style="border-bottom:1.5px solid #1F2430;">'
            '<td style="padding:4px 0; font-size:11px; font-weight:600; text-transform:uppercase;">Measure</td>'
            f'<td style="padding:4px 6px; text-align:right; font-size:11px; font-weight:600; text-transform:uppercase;">{_mon_yr(tn["then_date"])}</td>'
            '<td style="padding:4px 6px; text-align:right; font-size:11px; font-weight:600; text-transform:uppercase;">Now</td>'
            '<td style="padding:4px 0 4px 6px; text-align:right; font-size:11px; font-weight:600; text-transform:uppercase;">Call</td></tr>\n'
            + "\n".join(rows) + '\n    </table>\n'
            f'    <p style="font-size:11.5px; {MUTED} margin:4px 0 0 0;">&ldquo;Similar&rdquo; = within '
            '15 percentile points of each other on that measure\'s own history, both all-time and over '
            'the last 30 years; the gap in brackets is now minus then. Term premium is a '
            'Fed Board model estimate (Kim-Wright); fed funds then vs. SOFR now.</p>')


def history_ref_rows(state, row_date):
    lh = state.get("long_history", {})
    out = []
    for label, key, kind in HIST_REF:
        ctx = lh.get(key)
        if not ctx:
            continue
        lag = (f' <span style="{MUTED} font-size:10px;">({ctx["latest_date"][5:]})</span>'
               if ctx.get("latest_date") and ctx["latest_date"] != row_date else "")
        out.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF; vertical-align:top;">\n'
            f'        <td style="padding:6px 0;">{label}{lag}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO} white-space:nowrap;">{_ref_value(ctx, kind)}</td>\n'
            f'        <td style="padding:6px 6px; font-size:12px;">{html.escape(ctx.get("label", ""))}</td>\n'
            f'        <td style="padding:6px 0 6px 6px; font-size:12px;">{_last_time_cell(ctx, row_date)}</td>\n'
            f'      </tr>')
    return "\n".join(out)


def history_lines(state):
    lines = []
    for key, name in (("s2s10", "2s10s"), ("s3m10y", "3m10y")):
        c = (state.get("curve_cycles") or {}).get(key)
        if not c:
            continue
        miss = [x for x in c["cycles"] if x["status"] == "not_followed"]
        pend = [x for x in c["cycles"] if x["status"] == "pending"]
        txt = (f"<strong>{name} inversions since {c['history_start'][:4]}:</strong> "
               f"{c['n_followed']} of {c['n_judged']} inversion cycles were followed by a recession "
               f"within three years of starting (any three-year stretch since "
               f"{c.get('base_rate_since', c['history_start'][:4])}, outside a recession: "
               f"{c['base_rate_36m_pct']}%).")
        if miss:
            m = miss[-1]
            txt += (f" The miss: {_mon_yr(m['start'])}&ndash;{_mon_yr(m['end'])}, "
                    f"{m['trough_bp']}bp at its deepest.")
        if pend:
            m = pend[-1]
            txt += (f" Still too recent to judge: {_mon_yr(m['start'])}&ndash;{_mon_yr(m['end'])} "
                    f"({m['trough_bp']}bp at its deepest).")
        covid = [x for x in c["cycles"] if x["status"] == "followed"
                 and "COVID" in (x.get("recession") or "")]
        if covid:
            txt += (f" One hit ({_mon_yr(covid[0]['start'])}) counts the COVID recession, which began "
                    f"{covid[0]['months_from_start']} months after that inversion started.")
        if c.get("n_began_in_recession"):
            txt += f" ({c['n_began_in_recession']} began inside a recession and isn't counted.)"
        if c.get("n_start_unknown"):
            txt += (f" ({c['n_start_unknown']} was already inverted when the data begins, so its "
                    "start is unknown and it isn't counted.)")
        hits = [x for x in c["cycles"] if x["status"] == "followed"
                and not x.get("same_recession_as_earlier_cycle")]
        after = [x["months_from_uninversion"] for x in hits if x["months_from_uninversion"] > 0]
        same = sum(1 for x in hits if x["months_from_uninversion"] == 0)
        rest = len(hits) - len(after) - same
        if c.get("months_since_latest_cycle_end") is not None:
            txt += f" The latest inversion ended {c['months_since_latest_cycle_end']} months ago."
            if after:
                txt += (f" In {len(after)} of the {len(hits)} hits, the recession began "
                        + (f"{min(after)}&ndash;{max(after)} months" if min(after) != max(after)
                           else f"{after[0]} months")
                        + " after the curve stopped being inverted"
                        + (f"; in {same}, the same month it stopped" if same else "")
                        + (f"; in {rest}, while it was still inverted" if rest else "")
                        + ".")
        lines.append(txt)
    digest_ids = {f["id"] for f in state.get("history_digest") or []}
    for name, pr in (state.get("history_pairs") or {}).items():
        if f"pair:{name}" in digest_ids:
            continue
        b, b20 = pr["bands"]["10"], pr["bands"]["20"]
        txt = (f"<strong>High real yields with tight credit</strong> (both since "
               f"{pr['shared_history_start'][:4]}): in its extreme band today: "
               f"{'yes' if b['today_in_band'] else 'no'}. ")
        if pr.get("stable_prior"):
            txt += f"Prior stretches: {b['n_prior_stretches']}."
        else:
            txt += (f"Prior stretches: {b['n_prior_stretches']} at the strict top/bottom-tenth cut, "
                    f"{b20['n_prior_stretches']} at a top/bottom-fifth cut"
                    + (f" (where today's stretch reaches back to {_mon_yr(b20['current_run_start'])})"
                       if b20.get("current_run_start") else "")
                    + ". The count depends on the cut, so no track record is claimed.")
        lines.append(txt)
    return "\n".join(f'    <p style="font-size:13px; margin:8px 0 0 0; color:#39404E;">{t}</p>'
                     for t in lines)


def shock_track_html(state):
    sh = ((state.get("rate_pace") or {}).get("ust_10y") or {}).get("shock")
    if not sh or not sh.get("track"):
        return ""
    base = state.get("history_base_rates", {})
    rows = []
    for t in sh["track"]:
        spx = t.get("spx_12m")
        rec = t["recession_24m"]
        rec_txt = {"yes": f"yes ({rec.get('months_after')} mo"
                          + (", same as above" if rec.get("same_recession_as_earlier") else "") + ")",
                   "no": "no", "pending": "too recent",
                   "in_progress": "began mid-recession"}[rec["status"]]
        rows.append(
            f'        <tr style="border-bottom:1px solid #EAE6DF;">'
            f'<td style="padding:4px 0;">{_mon_yr(t["entry"])}</td>'
            f'<td style="padding:4px 6px; text-align:right; {MONO}">{t["level_at_entry"]:.2f}%</td>'
            f'<td style="padding:4px 6px; text-align:right; {MONO}">{(_signed(spx["return_pct"]) if spx else "&mdash;")}</td>'
            f'<td style="padding:4px 6px; text-align:right; {MONO}">{(_signed(spx["worst_drawdown_pct"]) if spx else "&mdash;")}</td>'
            f'<td style="padding:4px 0 4px 6px; text-align:right;">{rec_txt}</td></tr>')
    sm = sh["track_summary"]
    spx_b = base.get("spx_12m", {}).get("since_1962", {})
    dd = spx_b.get("median_worst_drawdown_pct")
    rows.append(
        f'        <tr style="border-top:1.5px solid #1F2430;"><td style="padding:4px 0; font-weight:600;">Normal (any month since 1962)</td>'
        f'<td></td><td style="padding:4px 6px; text-align:right; {MONO}">{_signed(spx_b.get("median_pct", 0))} median'
        f'<br><span style="{MUTED}">{spx_b.get("share_negative_pct")}% of 12-mo spans negative</span></td>'
        f'<td style="padding:4px 6px; text-align:right; {MONO}">{(_signed(dd) + " median") if dd is not None else "&mdash;"}</td>'
        f'<td style="padding:4px 0 4px 6px; text-align:right;">{base.get("recession_starts_within", {}).get("24m_since_1962")}% yes'
        f'<br><span style="{MUTED}">outside recessions</span></td></tr>')
    move = "rise" if sh["side"] == "high" else "fall"
    n_brief = sh.get("n_briefer_excluded") or 0
    title = (f'Every time before: the {sm["n"]} past 12-month {move}{"" if sm["n"] == 1 else "s"} in the 10Y '
             f'of {abs(sh["change_12m_pp"]):.2f} points or more (since {sh["history_start"][:4]}'
             + (f"; {n_brief} that lasted under 10 sessions not shown" if n_brief else "") + ")")
    return (f'    <details style="margin:12px 0 0 0;"><summary style="font-size:13px; font-weight:600; cursor:pointer;">'
            f'{title}</summary>\n'
            '      <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%; border-collapse:collapse; font-size:12px; margin-top:6px;">\n'
            '        <tr style="border-bottom:1.5px solid #1F2430;"><td style="padding:4px 0; font-size:10.5px; font-weight:600; text-transform:uppercase;">Started</td>'
            '<td style="padding:4px 6px; text-align:right; font-size:10.5px; font-weight:600; text-transform:uppercase;">10Y then</td>'
            '<td style="padding:4px 6px; text-align:right; font-size:10.5px; font-weight:600; text-transform:uppercase;">S&amp;P next 12 mo</td>'
            '<td style="padding:4px 6px; text-align:right; font-size:10.5px; font-weight:600; text-transform:uppercase;">Deepest drop in that year</td>'
            '<td style="padding:4px 0 4px 6px; text-align:right; font-size:10.5px; font-weight:600; text-transform:uppercase;">Recession &le;2 yrs</td></tr>\n'
            + "\n".join(rows) + '\n      </table>\n'
            f'      <p style="font-size:11.5px; {MUTED} margin:4px 0 0 0;">Measured from the day each {move} first '
            'reached this size (the real-time twin of today), never from when it ended. S&amp;P 500 price '
            'only, no dividends. Overlapping windows aren\'t independent: counts, not odds.</p>\n'
            '    </details>')


def market_rows(state):
    as_of = state["row_date"]
    rows = []
    for key, ctx in (state.get("market_history") or {}).items():
        mv, rec, ytd = ctx["move"], ctx["record"], ctx.get("ytd")
        word = "drop" if mv["direction"] == "down" else "gain"
        lb = mv.get("last_at_least_this_big")
        py, n_r = mv.get("per_year_recent"), mv.get("n_recent")
        often = ("&mdash;" if py is None else
                 f'{word}s this size: ~{py:.0f} days/yr' if py >= 1 else
                 f'{word}s this size: {n_r} in {mv["recent_window_years"]:.0f} yrs')
        often += (f'<br><span style="{MUTED} font-size:11px;">{"since " + ctx["history_start"][:4] if mv["recent_window_years"] < 30 else "last 30 yrs"}'
                  + (f'; last bigger {word} {_mon_d_rel(lb["date"], as_of)}' if lb else "") + '</span>')
        if ytd:
            ytd_txt = (f'{_signed(ytd["change"])} <span style="{MUTED}">· {"#" + str(ytd["rank"])} '
                       f'{"best" if ytd["direction"] == "up" else "worst"} of {ytd["n_years"]} '
                       f'(median {_signed(ytd["median_prior"])})</span>')
        else:
            ytd_txt = "&mdash;"
        rec_txt = (f'<span style="{MUTED}">record is {rec["record_date"][:4]}: too old to compare</span>'
                   if rec["stale"] else
                   ("at record" if rec["pct_below_record"] > -0.05 else
                    f'{_signed(rec["pct_below_record"])} <span style="{MUTED}">({_mon_yr(rec["record_date"])})</span>'))
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF; vertical-align:top;">\n'
            f'        <td style="padding:6px 0;">{html.escape(ctx["label"])}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">{_signed(mv["pct"], 2)}</td>\n'
            f'        <td style="padding:6px 6px;">{often}</td>\n'
            f'        <td style="padding:6px 6px; text-align:right; {MONO}">{ytd_txt}</td>\n'
            f'        <td style="padding:6px 0 6px 6px; text-align:right; {MONO}">{rec_txt}</td>\n'
            f'      </tr>')
    return "\n".join(rows)


def pullback_line(state):
    pb = ((state.get("market_history") or {}).get("spx") or {}).get("pullback")
    if not pb or pb.get("this_year_worst_pct") is None:
        return ""
    a, b = pb["since_1929"], pb["since_1950"]
    as_of = state["row_date"]
    cmp_ = ("milder than" if pb["this_year_worst_pct"] > a["median_pct"] else "deeper than")
    # early in a year the index may not have closed below its running high yet
    span = ("no close below its running high yet" if pb.get("peak_date") is None else
            f'{_mon_d_rel(pb["peak_date"], as_of)} to {_mon_d_rel(pb["trough_date"], as_of)}')
    return ('    <p style="font-size:13px; margin:8px 0 0 0; color:#39404E;"><strong>S&amp;P 500 pullbacks:</strong> '
            f'this year\'s worst drop so far is {_signed(pb["this_year_worst_pct"])} '
            f'({span}), '
            f'{cmp_} a typical year: since 1929 the median year\'s worst drop was '
            f'{_signed(a["median_pct"])}, and {a["n_10pct_or_worse"]} of {a["n_years"]} years saw a '
            f'drop of 10% or more ({a["n_20pct_or_worse"]} saw 20% or more). Since 1950 the median '
            f'is {_signed(b["median_pct"])}. Price only.</p>')


def cycle_map_html(state):
    cm = state.get("cycle_map")
    if not cm or not cm.get("gauges"):
        return ""
    rows = []
    for g in cm["gauges"]:
        now = f'{g["value"]:.1f}%' + (" <strong>record</strong>" if g["is_record"] else
                                     f' <span style="{MUTED}">({pct_ordinal(g["pct_rank_all_time"])} %ile)</span>')
        p00, p07 = g.get("peak_1997_2001"), g.get("peak_2005_2008")
        c00 = f'{p00["value"]:.1f}%' if p00 else "&mdash;"
        c07 = f'{p07["value"]:.1f}%' if p07 else "&mdash;"
        qtr = f'{g["latest_quarter"][:4]} Q{(int(g["latest_quarter"][5:7]) - 1) // 3 + 1}'
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF;"><td style="padding:5px 0;">{html.escape(g["label"])}'
            f' <span style="{MUTED} font-size:10px;">({qtr})</span></td>'
            f'<td style="padding:5px 6px; text-align:right; {MONO}">{now}</td>'
            f'<td style="padding:5px 6px; text-align:right; {MONO}">{c00}</td>'
            f'<td style="padding:5px 0 5px 6px; text-align:right; {MONO}">{c07}</td></tr>')
    for r in cm.get("returns_3y", []):
        pk = r.get("peak_1997_2000")
        rows.append(
            f'      <tr style="border-bottom:1px solid #EAE6DF;"><td style="padding:5px 0;">{html.escape(r["label"])} 3-year price return</td>'
            f'<td style="padding:5px 6px; text-align:right; {MONO}">{_signed(r["three_year_return_pct"])} '
            f'<span style="{MUTED}">({pct_ordinal(r["pct_rank_all_time"])} %ile)</span></td>'
            f'<td style="padding:5px 6px; text-align:right; {MONO}">{(_signed(pk["value"]) + " peak") if pk else "&mdash;"}</td>'
            f'<td style="padding:5px 0 5px 6px; text-align:right;">&mdash;</td></tr>')
    return ('    <p style="font-size:13px; font-weight:600; margin:14px 0 4px 0;">Financing-cycle map (Unit 7) &mdash; '
            'today vs. the 2000 and 2007 peaks</p>\n'
            '    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%; border-collapse:collapse; font-size:12.5px;">\n'
            '      <tr style="border-bottom:1.5px solid #1F2430;"><td style="padding:4px 0; font-size:11px; font-weight:600; text-transform:uppercase;">Gauge</td>'
            '<td style="padding:4px 6px; text-align:right; font-size:11px; font-weight:600; text-transform:uppercase;">Now</td>'
            '<td style="padding:4px 6px; text-align:right; font-size:11px; font-weight:600; text-transform:uppercase;">1997&ndash;2001 high</td>'
            '<td style="padding:4px 0 4px 6px; text-align:right; font-size:11px; font-weight:600; text-transform:uppercase;">2005&ndash;08 high</td></tr>\n'
            + "\n".join(rows) + '\n    </table>\n'
            f'    <p style="font-size:11.5px; {MUTED} margin:4px 0 0 0;">Aggregates only (cycle level, &sect;8). Quarterly '
            'BEA/Fed data arrive about a quarter late and get revised; IT investment is nominal; '
            'corporate debt is one aggregate of all nonfinancial corporate bonds and loans and doesn\'t '
            'isolate data-center financing. Equity/GDP has drifted up structurally &mdash; a map, not a timing signal.</p>')


HISTORY_NOTE = (
    "How to read: <strong>Lately vs. history</strong> puts two questions side by side. "
    "&ldquo;Lately&rdquo; compares today with the past six months (&ldquo;unusual&rdquo; = a 120-day "
    "z-score of 1.5 or more; &ldquo;no 6-month read&rdquo; = too few recent readings to say). "
    "&ldquo;History&rdquo; checks the all-time and last-30-years percentiles separately: "
    "&ldquo;historically extreme&rdquo; means top or bottom fifth on both; when only one view is "
    "extreme, both numbers are shown. <strong>Last time</strong> appears only for readings in the "
    "top or bottom fifth, and only when short dips in between don't change the answer: it is the "
    "last stretch <em>before</em> this one at least this high (&ge;) or low (&le;), with "
    "&ldquo;briefly&rdquo; when that stretch added up to under 20 trading days. Any &ldquo;what came "
    "next&rdquo; is measured from the day a past stretch began, against the normal rate, and "
    "recessions too recent for NBER to date are &ldquo;too recent to judge.&rdquo; Sources: FRED "
    "(Treasuries: 10-year 1962+, 2-year 1976+, 30-year 1977+ with 2002&ndash;06 excluded, 3-month "
    "1981+; TIPS/breakeven 2003+, fed funds 1954+, Moody's Baa 1986+, Cleveland Fed real rate "
    "1982+, Kim-Wright term premium 1990+, Freddie Mac mortgage 1971+, NBER recessions), Yahoo "
    "(S&amp;P 500 1928+, Nasdaq 1971+, DXY 1971+, WTI and gold futures 2000+). *HY/IG OAS: only "
    "~3 years reachable here; the Baa&minus;10Y row is the long-run investment-grade proxy "
    "(direction and timing only, never magnitude).")


def history_markdown(state, row_date, prose_md=""):
    """The same history blocks as markdown, for the twin (briefs/<date>.md),
    in the page's order: History check, prose, then the reference blocks."""
    parts = []
    if state.get("history_error"):
        parts.append(_html_to_md(history_check_html(state)))
        if prose_md:
            parts.append(prose_md)
        return "\n\n".join(parts)
    facts = state.get("history_digest") or []
    if facts:
        parts.append("**History check** (script-written from the data):\n\n"
                     + "\n".join(f"- {f['sentence']}" for f in facts))
    if prose_md:
        parts.append(prose_md)
    tn = then_now_html(state)
    if tn:
        parts.append(f"**Then vs. now — {_mon_d_yr(state['then_vs_now']['then_date'])} vs. today**\n\n"
                     + _md_table(["Measure", "Then", "Now", "Call"], tn)
                     + "\n\n" + _footnote_md(tn))
    parts.append(_md_table(["Series", "Today", "Lately vs. history", "Last time"],
                           history_ref_rows(state, row_date)))
    lines = history_lines(state)
    if lines:
        parts.append(_html_to_md(lines))
    st = shock_track_html(state)
    if st:
        summary = re.search(r"<summary[^>]*>(.*?)</summary>", st, re.S).group(1)
        parts.append(f"**{html.unescape(re.sub(r'<[^>]+>', '', summary))}**\n\n"
                     + _md_table(["Started", "10Y then", "S&P next 12 mo", "Deepest drop in that year", "Recession ≤2 yrs"], st)
                     + "\n\n" + _footnote_md(st))
    parts.append(_md_table(["Market", "Today", "How often", "This year vs. past years", "From record"],
                           market_rows(state)))
    pb = pullback_line(state)
    if pb:
        parts.append(_html_to_md(pb))
    parts.append(_html_to_md(HISTORY_NOTE))
    return "\n\n".join(parts)


def _footnote_md(block_html):
    """The caveat paragraph that follows a block's table, as markdown -- the
    twin must carry the same caveats as the page."""
    tail = block_html.rsplit("</table>", 1)[-1]
    return _html_to_md(re.sub(r"</?details[^>]*>", "", tail))


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
        if "text-transform:uppercase" in row:
            continue  # the HTML table's own header row; the md header is above
        cells = [html.unescape(strip.sub("", re.sub(r"<br\s*/?>", " · ", c)))
                 .replace("|", "/").strip()
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
    if state.get("long_history") or state.get("history_error"):
        parts += ["## Today in history",
                  history_markdown(state, row_date, _html_to_md(content.get("history_html", "")))]
    parts += [
        "## Movers", _html_to_md(content["movers_html"]),
        "## Chart of the day",
        f"Why this chart today — {_html_to_md(content['chart_of_day_why'])}",
        "## AI capex & financing cycle",
        _html_to_md(content["tier3_html"]
                    .replace("[[LIQUIDITY_SVG]]", "<p>(Liquidity panel: chart on the web page.)</p>")
                    .replace("[[CYCLE_MAP]]", "<p>[[CYCLE_MAP_MD]]</p>"))
        .replace("[[CYCLE_MAP_MD]]",
                 "**Financing-cycle map (Unit 7) — today vs. the 2000 and 2007 peaks**\n\n"
                 + _md_table(["Gauge", "Now", "1997–2001 high", "2005–08 high"],
                             cycle_map_html(state))
                 + "\n\n" + _footnote_md(cycle_map_html(state)) if state.get("cycle_map") else ""),
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
    # the twin needs the prose before chart/table slots are filled with HTML
    tier3_source = content["tier3_html"]
    spark_dir = Path(args.sparks)
    template = (REPO / "templates" / "brief.html").read_text()
    color = content["regime_color"]
    row_date = state["row_date"]

    # §4F (2026-10-09): the historical-context section is fixed furniture.
    # A brief built while long-run history is available must carry its prose
    # and its one-line email headline -- refuse to build otherwise, so a
    # scheduled run can't quietly ship without it again.
    if state.get("long_history"):
        if not str(content.get("history_html", "")).strip():
            raise SystemExit(
                "build_brief: content is missing history_html -- every brief carries a "
                "'Today in history' section (CLAUDE.md §4F, ROUTINE.md step 8). Write it "
                "from state.json history_digest / then_vs_now / rate_pace / curve_cycles, "
                "then run scripts/check_history_prose.py.")
    # Friday Tier 3: the Unit 7 financing-cycle map, where the content marks
    # a [[CYCLE_MAP]] slot
    content["tier3_html"] = content["tier3_html"].replace("[[CYCLE_MAP]]", cycle_map_html(state))

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
        "{{HISTORY_CHECK}}": history_check_html(state),
        "{{HISTORY_HTML}}": content.get("history_html", ""),
        "{{THEN_NOW}}": then_now_html(state),
        "{{HISTORY_REF_ROWS}}": history_ref_rows(state, row_date),
        "{{HISTORY_LINES}}": history_lines(state),
        "{{SHOCK_TRACK}}": shock_track_html(state),
        "{{MARKET_ROWS}}": market_rows(state),
        "{{PULLBACK_LINE}}": pullback_line(state),
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
    # one history line under the regime line: the first sentence of the top
    # digest fact, script-written (never typed by the model)
    digest = state.get("history_digest") or []
    top = (digest[0].get("email") or digest[0]["sentence"]) if digest else ""
    history_email = (
        f'<p style="font-size:14px; line-height:1.5; margin:0 0 14px 0; '
        f'border-left:3px solid {color}; padding-left:10px;"><span style="font-family:Menlo,'
        f'monospace; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; '
        f'color:#6B7280;">In history</span><br>{html.escape(top)}</p>' if top else "")
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
    md_out.write_text(markdown_twin(dict(content, tier3_html=tier3_source), state,
                                    spark_dir, row_date, ath_line, todays))
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
