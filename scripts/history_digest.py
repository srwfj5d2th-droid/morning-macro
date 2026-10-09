#!/usr/bin/env python3
"""history_digest.py — picks the day's few history facts and words them.

The data layer (history_context.py) can produce ~30 history facts a day.
Two opposite failures followed from that on 2026-10-09: the first edition
skipped history entirely, and a rushed second draft drowned the reader in
it. The digest is the middle path: a deterministic, ranked, family-deduped
list of at most MAX_FACTS facts, each with a script-written sentence. The
brief renders these sentences verbatim (and the email carries the top one);
the model writes interpretation around them, never the numbers (§4C).

Selection order (pinned; change at monthly review):
  1. "last time it was here" >= 10 years ago (or a record), tail-gated and
     gap-robust -- one per family
  2. a pre-registered pair that is in band today with a stable prior
  3. the pace of this year's rate move, when it ranks in the top 10
  4. "last time" 5-10 years ago
  5. a stock-index move in its tail
"""

import datetime as dt

MAX_FACTS = 4

# family -> series, anchor first. One fact per family.
FAMILIES = {
    "rates": ["ust_10y", "ust_30y", "ust_2y"],
    "real": ["tips_10y_real"],
    "credit": ["baa_10y_spread"],
    "dollar": ["dxy"],
    "mortgage": ["mortgage30"],
}
LABELS = {
    "ust_10y": "10-year Treasury yield", "ust_30y": "30-year Treasury yield",
    "ust_2y": "2-year Treasury yield", "tips_10y_real": "10-year TIPS real yield",
    "baa_10y_spread": "investment-grade credit spread proxy (Moody's Baa minus the 10-year)",
    "dxy": "dollar index (DXY)", "mortgage30": "30-year mortgage rate",
}
UNITS = {"baa_10y_spread": "pp", "dxy": ""}


def _mon_yr(d):
    return dt.date.fromisoformat(d).strftime("%b %Y")


def _mon_d(d):
    x = dt.date.fromisoformat(d)
    return f"{x.strftime('%b')} {x.day}"


def _ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _fmt(key, v):
    u = UNITS.get(key, "%")
    if u == "pp":
        return f"{v:.2f} points"
    if u == "":
        return f"{v:.2f}"
    return f"{v:.2f}%"


def _bin(p):
    if p >= 95:
        return "near the top of its range"
    if p >= 80:
        return "high"
    if p >= 61:
        return "above average"
    if p >= 40:
        return "about average"
    if p >= 21:
        return "below average"
    return "low"


def two_lens(ctx):
    """'higher than on 87 of every 100 days of the last 30 years; about
    average (49th percentile) since 1962' -- both numbers whenever they
    diverge (§4F), one otherwise."""
    p_all, p_30 = ctx["pct_rank_all_time"], ctx.get("pct_rank_modern")
    start = ctx["start_date"][:4]
    side_hi = ctx["lookback"]["side"] == "high"
    word = "higher" if side_hi else "lower"

    def n_of_100(p):
        x = p if side_hi else 100 - p
        # near the edges, rounding to a whole number would erase the point
        # ("100 of every 100 days" when it's 99.7)
        return f"{x:.1f}" if (x >= 99 or x <= 1) else f"{round(x)}"
    if ctx.get("short_history"):
        return f"{word} than on {n_of_100(p_all)} of every 100 days of the ~{ctx['years']:.0f} years available"
    if p_30 is not None and ctx.get("regime_divergence"):
        return (f"{word} than on {n_of_100(p_30)} of every 100 days of the last 30 years, "
                f"but {_bin(p_all)} ({_ordinal(round(p_all))} percentile) since {start}")
    return f"{word} than on {n_of_100(p_all)} of every 100 days since {start}"


def _lookback_sentence(key, ctx, value):
    lb = ctx["lookback"]
    lt, ls = lb.get("last_touch"), lb.get("last_sustained")
    side_word = "at or above" if lb["side"] == "high" else "at or below"
    label = LABELS.get(key, key)
    if lb["record"]:
        s = (f"The {label} ({_fmt(key, value)}) is {'above' if lb['side'] == 'high' else 'below'} "
             f"every earlier reading since records begin in {lb['history_start'][:4]}.")
    else:
        brief = (lt["n_obs"] < 20)
        s = (f"The {label} ({_fmt(key, value)}) has been {side_word} this level since "
             f"{_mon_d(lb['current_run_start'])}; before this run, the last time was "
             f"{_mon_yr(lt['end'])}"
             + (f", and only briefly ({lt['n_obs']} readings)" if brief else "")
             + (f"; it was last there routinely until {_mon_yr(ls['end'])}"
                if ls and brief and ls["end"] != lt["end"] else "")
             + ".")
    if not lb.get("today_is_run_extreme", True):
        rp = lb.get("run_extreme_prior")
        s += (f" This run's {'high' if lb['side'] == 'high' else 'low'} was "
              f"{_fmt(key, lb['run_extreme'])} on {_mon_d(lb['run_extreme_date'])}"
              + (f", last matched in {_mon_yr(rp['end'])}" if rp else "") + ".")
    s += f" Today's reading is {two_lens(ctx)}."
    if key == "tips_10y_real" and ctx.get("tips_window_divergence"):
        s += (f" But TIPS only exist since 2003: the Cleveland Fed's model real rate, "
              f"which reaches back to 1982, puts real rates at the "
              f"{_ordinal(round(ctx['cleveland_pct_all_time']))} percentile since 1982 "
              f"({_ordinal(round(ctx['cleveland_pct_modern']))} over the last 30 years) — "
              f"high against the last two decades, not against the 1980s and '90s.")
    return s


def _pair_sentence(p):
    b = p["bands"]["10"]
    stretches = []
    for t in p["track"]:
        rec = t["recession_24m"]
        rec_txt = {"yes": f"recession began {rec.get('months_after')} months after it started",
                   "no": "no recession within two years",
                   "pending": "too recent to judge",
                   "in_progress": "began during a recession"}[rec["status"]]
        spx = t.get("spx_12m")
        stretches.append(f"{_mon_yr(t['entry'])}–{_mon_yr(t['end'])} ({rec_txt}"
                         + (f"; S&P 500 {spx['return_pct']:+.1f}% over the next 12 months"
                            if spx else "") + ")")
    n = len(stretches)
    s = ("10-year real yields in their top tenth while the Baa credit spread sits in its "
         f"bottom tenth (both measured since {p['shared_history_start'][:4]}, when TIPS data begins): "
         f"true since {_mon_d(b['current_run_start'])}; it happened "
         + {1: "once", 2: "twice"}.get(n, f"{n} times") + " before — " + "; ".join(stretches) + ".")
    s += ({1: " One case is an anecdote, not a pattern.",
           2: " Two cases are an anecdote, not a pattern."}.get(n, f" {n} cases are too few to call a pattern." if n < 5 else ""))
    wider = p["bands"]["20"].get("current_run_start")
    if wider and wider != b["current_run_start"]:
        s += (f" At a looser top-fifth/bottom-fifth cut, today's stretch reaches back to "
              f"{_mon_yr(wider)}.")
    return s


def _pace_sentence(key, yr, shock, base):
    label = LABELS.get(key, key)
    top = ", ".join(f"{y['year']} {y['change']:+.0f}bp" for y in yr["years_more_extreme"][:3])
    s = (f"The {label} is {'up' if yr['change'] >= 0 else 'down'} {abs(yr['change']):.0f}bp this year — "
         f"the {_ordinal(yr['rank'])}-{'largest rise' if yr['change'] >= 0 else 'largest fall'} "
         f"through this date in {yr['n_years']} years" + (f" (bigger: {top}" + (", …" if len(yr['years_more_extreme']) > 3 else "") + ")" if top else "") + ".")
    if shock and shock["track_summary"]["n"] >= 5:
        t = shock["track_summary"]
        r24 = base["recession_starts_within"].get("24m_since_1962")
        spx = base["spx_12m"].get("since_1962", {})
        judged = t["n_recession_yes"] + t["n_recession_no"]
        s += (f" A 12-month {'rise' if shock['change_12m_pp'] >= 0 else 'fall'} this big "
              f"({shock['change_12m_pp']:+.2f} points) has started {t['n']} times since "
              f"{shock['history_start'][:4]}. Measured from each start, the S&P 500 (price only) "
              f"was lower a year later in {t['n_spx_negative']} of {t['n_spx_known']} "
              f"(any 12-month stretch since 1962: {spx.get('share_negative_pct')}%), and a recession "
              f"began within two years in {t['n_recession_yes']} of {judged}"
              + f" (any two-year stretch since 1962: {r24}%"
              + (f"; {t['n_recession_in_progress']} more began mid-recession"
                 if t['n_recession_in_progress'] else "")
              + ").")
    return s


def _move_sentence(mk):
    mv = mk["move"]
    lb = mv.get("last_at_least_this_big")
    word = "drop" if mv["direction"] == "down" else "gain"
    return (f"The {mk['label']}'s {mv['pct']:+.2f}% is a {word} that comes about "
            f"{mv['per_year_recent']:.0f} days a year (last {mv['recent_window_years']:.0f} years); "
            f"it's the {_ordinal(mv['count_this_year_incl_today'])} this year"
            + (f", and the last bigger one was {_mon_d(lb['date'])}" if lb else "") + ".")


def build_digest(state):
    lh = state.get("long_history", {})
    facts = []

    def live_value(key):
        s = state["series"].get(key) or state["derived"].get(key)
        if key in ("s2s10", "s3m10y") and s:
            return s["last"] / 100.0
        if s:
            return s["last"]
        ctx = lh.get(key)
        return ctx["lookback"]["run_extreme"] if ctx and ctx["lookback"].get("today_is_run_extreme") else (
            ctx.get("latest_value") if ctx else None)

    # 1 & 4: "last time it was here", one per family
    for fam, keys in FAMILIES.items():
        for key in keys:
            ctx = lh.get(key)
            if not ctx or "lookback" not in ctx:
                continue
            lb = ctx["lookback"]
            if not lb["gated"] or lb["gap_sensitive"]:
                continue
            yrs = lb["last_touch"]["years_since"] if lb.get("last_touch") else None
            if not lb["record"] and (yrs is None or yrs < 5):
                continue
            value = ctx.get("latest_value", live_value(key))
            tier = 1 if (lb["record"] or yrs >= 10) else 4
            facts.append({"id": f"lookback:{key}", "family": fam, "tier": tier,
                          "years_since": yrs, "series": key,
                          "sentence": _lookback_sentence(key, ctx, value),
                          "anchor_date": lb["last_touch"]["end"] if lb.get("last_touch") else None})
            break  # one per family: the first qualifying member

    # 2: pre-registered pair, in band today with a stable prior
    for name, p in (state.get("history_pairs") or {}).items():
        b = p["bands"]["10"]
        if b["today_in_band"] and p["track"]:
            facts.append({"id": f"pair:{name}", "family": "pair", "tier": 2,
                          "sentence": _pair_sentence(p),
                          "anchor_date": p["track"][0]["entry"]})

    # 3: pace of this year's rate move
    pace = state.get("rate_pace", {})
    base = state.get("history_base_rates", {})
    for key in ("ust_10y", "ust_2y", "ust_30y"):
        yr = (pace.get(key) or {}).get("ytd")
        if yr and yr["rank"] <= 10:
            facts.append({"id": f"pace:{key}", "family": "pace", "tier": 3,
                          "sentence": _pace_sentence(key, yr, pace[key].get("shock"), base)})
            break

    # 5: a stock-index move in its tail
    for key in ("spx", "ndx"):
        mk = (state.get("market_history") or {}).get(key)
        if mk and mk["move"]["in_tail"]:
            facts.append({"id": f"move:{key}", "family": "move", "tier": 5,
                          "sentence": _move_sentence(mk)})
            break

    facts.sort(key=lambda f: (f["tier"], -(f.get("years_since") or 0)))
    seen, out = set(), []
    for f in facts:
        if f["family"] in seen:
            continue
        seen.add(f["family"])
        out.append(f)
        if len(out) >= MAX_FACTS:
            break
    return out
