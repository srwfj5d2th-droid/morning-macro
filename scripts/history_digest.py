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

from history_context import level_word, ordinal, pct_ordinal, reading_units

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


def _mon_d(d, as_of=None):
    """'Oct 5' within the as-of year, 'Dec 30, 2025' otherwise."""
    x = dt.date.fromisoformat(d)
    s = f"{x.strftime('%b')} {x.day}"
    return s if as_of and d[:4] == as_of[:4] else f"{s}, {x.year}"


def _span(start, end):
    a, b = _mon_yr(start), _mon_yr(end)
    return a if a == b else f"{a} and {b}"


_ordinal = ordinal  # kept for callers that import it from here


def _fmt(key, v):
    u = UNITS.get(key, "%")
    if u == "pp":
        return f"{v:.2f} points"
    if u == "":
        return f"{v:.2f}"
    return f"{v:.2f}%"


def _bin(p):
    return level_word(p)


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
                f"but {_bin(p_all)} ({pct_ordinal(p_all)} percentile) since {start}")
    return f"{word} than on {n_of_100(p_all)} of every 100 days since {start}"


def _cleveland_clause(ctx):
    """TIPS start in 2003; the Cleveland Fed's model real rate reaches back
    to 1982. Worded from its two percentiles, whichever way they point."""
    c_all, c_30 = ctx.get("cleveland_pct_all_time"), ctx.get("cleveland_pct_modern")
    if c_all is None:
        return ""
    if c_30 is None:
        return (f" But TIPS only exist since 2003: the Cleveland Fed's model real rate, "
                f"back to 1982, puts real rates at the {pct_ordinal(c_all)} percentile since 1982 "
                f"({level_word(c_all)}).")
    tail = (f"{level_word(c_30)} on both views" if level_word(c_30) == level_word(c_all) else
            f"{level_word(c_30)} against the last 30 years, {level_word(c_all)} since 1982")
    return (f" But TIPS only exist since 2003: the Cleveland Fed's model real rate, back to "
            f"1982, puts real rates at the {pct_ordinal(c_30)} percentile of the last 30 years "
            f"and the {pct_ordinal(c_all)} since 1982 — {tail}.")


def _lookback_parts(key, ctx, value, as_of):
    """[headline sentence, run-extreme sentence or '', two-lens sentence,
    caveat or ''] -- the email keeps the first two."""
    lb = ctx["lookback"]
    lt, ls = lb.get("last_touch"), lb.get("last_sustained")
    side_word = "at or above" if lb["side"] == "high" else "at or below"
    hi = lb["side"] == "high"
    label = LABELS.get(key, key)
    cad = lb.get("cadence", "daily")
    if lb["record"]:
        head = (f"The {label} ({_fmt(key, value)}) is {'above' if hi else 'below'} "
                f"every earlier reading since records begin in {lb['history_start'][:4]}.")
    elif lb.get("run_is_record"):
        head = (f"The {label} is in a record run: this run's {'high' if hi else 'low'} of "
                f"{_fmt(key, lb['run_extreme'])} on {_mon_d(lb['run_extreme_date'], as_of)} is "
                f"{'above' if hi else 'below'} every earlier reading since records begin in "
                f"{lb['history_start'][:4]}; today's {_fmt(key, value)} is below that high.")
    else:
        start = _mon_d(lb["current_run_start"], as_of)
        if lb.get("current_run_unbroken", True):
            here = f"has been {side_word} this level since {start}"
        else:
            here = (f"first reached this level on {start} and has been there on "
                    f"{lb['current_run_sessions']} of the "
                    f"{reading_units(lb['current_run_total_sessions'], cad)} since")
        brief = lt.get("brief", lt["n_obs"] < 20)
        head = (f"The {label} ({_fmt(key, value)}) {here}; before this run, the last time was "
                f"{_mon_yr(lt['end'])}"
                + (f", and only briefly ({reading_units(lt['n_obs'], cad)} between "
                   f"{_span(lt['start'], lt['end'])})" if brief and _mon_yr(lt['start']) != _mon_yr(lt['end'])
                   else f", and only briefly ({reading_units(lt['n_obs'], cad)})" if brief else "")
                + (f"; it was last there routinely until {_mon_yr(ls['end'])}"
                   if ls and brief and ls["end"] != lt["end"] else "")
                + ".")
    runx = ""
    if not lb.get("today_is_run_extreme", True) and not lb.get("run_is_record"):
        rp = lb.get("run_extreme_prior")
        runx = (f"This run's {'high' if hi else 'low'} was "
                f"{_fmt(key, lb['run_extreme'])} on {_mon_d(lb['run_extreme_date'], as_of)}"
                + (f", last matched in {_mon_yr(rp['end'])}" if rp else "") + ".")
    lens = f"Today's reading is {two_lens(ctx)}."
    cav = _cleveland_clause(ctx).strip() if (key == "tips_10y_real"
                                              and ctx.get("tips_window_divergence")) else ""
    return [head, runx, lens, cav or _era_clause(key, ctx, value)]


def _era_clause(key, ctx, value):
    """When the two lenses diverge, name the whole decades that sat entirely
    beyond today's reading -- the data behind 'if you remember the '80s'."""
    dec = ctx.get("by_decade") or {}
    if not ctx.get("regime_divergence") or not dec:
        return ""
    hi = ctx["lookback"]["side"] == "high"
    beyond = [k for k, d in dec.items() if d["complete"]
              and d["share_at_or_above_pct"] == (100.0 if hi else 0.0)]
    if not beyond:
        return ""
    names = " and ".join(beyond) if len(beyond) <= 2 else ", ".join(beyond[:-1]) + f" and {beyond[-1]}"
    return (f"Every reading in the {names} was {'at or above' if hi else 'below'} "
            f"today's {_fmt(key, value)}.")


def _lookback_sentence(key, ctx, value, as_of=None):
    return " ".join(p for p in _lookback_parts(key, ctx, value, as_of) if p)


def _pair_parts(p, as_of):
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
    start = _mon_d(b["current_run_start"], as_of)
    if b.get("streak_start") and b["streak_start"] != b["current_run_start"]:
        when = (f"true on {b['run_n_obs']} of the {b['run_total_sessions']} sessions since "
                f"{start} (unbroken since {_mon_d(b['streak_start'], as_of)})")
    else:
        when = f"true since {start}"
    head = ("10-year real yields in their top tenth while the Baa credit spread sits in its "
            f"bottom tenth (both measured since {p['shared_history_start'][:4]}, when TIPS data begins): "
            f"{when}; it happened "
            + {1: "once", 2: "twice"}.get(n, f"{n} times") + " before — " + "; ".join(stretches) + ".")
    label = ({1: "One case is an anecdote, not a pattern.",
              2: "Two cases are an anecdote, not a pattern."}.get(
        n, f"{n} cases are too few to call a pattern." if n < 5 else ""))
    wider = p["bands"]["20"].get("current_run_start")
    extra = (f"At a looser top-fifth/bottom-fifth cut, the current stretch starts in {_mon_yr(wider)}."
             if wider and wider != b["current_run_start"] else "")
    return [head, label, extra]


def _pair_sentence(p, as_of=None):
    return " ".join(x for x in _pair_parts(p, as_of) if x)


def _pace_parts(key, yr, shock, base):
    label = LABELS.get(key, key)
    top = ", ".join(f"{y['year']} {y['change']:+.0f}bp" for y in yr["years_more_extreme"][:3])
    head = (f"The {label} is {'up' if yr['change'] >= 0 else 'down'} {abs(yr['change']):.0f}bp this year — "
            f"the {ordinal(yr['rank'])}-{'largest rise' if yr['change'] >= 0 else 'largest fall'} "
            f"through this date in {yr['n_years']} years" + (f" (bigger: {top}" + (", …" if len(yr['years_more_extreme']) > 3 else "") + ")" if top else "") + ".")
    rest = ""
    if shock and shock["track_summary"]["n"] >= 5:
        t = shock["track_summary"]
        r24 = base["recession_starts_within"].get("24m_since_1962")
        spx = base["spx_12m"].get("since_1962", {})
        judged = t["n_recession_yes"] + t["n_recession_no"]
        rise = "rise" if shock["change_12m_pp"] >= 0 else "fall"
        n_brief = shock.get("n_briefer_excluded") or 0
        dup = t["n_recession_yes"] - t.get("n_distinct_recessions", t["n_recession_yes"])
        rest = (f"Over the last 12 months it is {'up' if shock['change_12m_pp'] >= 0 else 'down'} "
                f"{abs(shock['change_12m_pp']):.2f} points; a 12-month {rise} at least that big has "
                f"started {t['n']} times since {shock['history_start'][:4]}"
                + (f" (not counting {n_brief} that lasted under 10 sessions)" if n_brief else "")
                + f". Measured from each start, the S&P 500 (price only) was lower a year later in "
                f"{t['n_spx_negative']} of {t['n_spx_known']} (any 12-month stretch since 1962: "
                f"{spx.get('share_negative_pct')}%), and a recession began within two years in "
                f"{t['n_recession_yes']} of {judged}"
                + (f", covering {t['n_distinct_recessions']} different recessions" if dup > 0 else "")
                + f" (any two-year stretch since 1962 outside a recession: {r24}%"
                + (f"; {t['n_recession_in_progress']} more began mid-recession"
                   if t['n_recession_in_progress'] else "")
                + ").")
    return [head, rest]


def _pace_sentence(key, yr, shock, base):
    return " ".join(x for x in _pace_parts(key, yr, shock, base) if x)


def _move_sentence(mk, as_of=None):
    mv = mk["move"]
    lb = mv.get("last_at_least_this_big")
    word = "drop" if mv["direction"] == "down" else "gain"
    return (f"The {mk['label']}'s {mv['pct']:+.2f}% is a {word} of a size that comes about "
            f"{mv['per_year_recent']:.0f} days a year (last {mv['recent_window_years']:.0f} years); "
            f"it's the {ordinal(mv['count_this_year_incl_today'])} this year"
            + (f", and the last bigger one was {_mon_d(lb['date'], as_of)}" if lb else "") + ".")


def build_digest(state):
    lh = state.get("long_history", {})
    as_of = state.get("row_date")
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
            record = lb["record"] or lb.get("run_is_record")
            yrs = lb["last_touch"]["years_since"] if lb.get("last_touch") else None
            if not record and (yrs is None or yrs < 5):
                continue
            value = ctx.get("latest_value", live_value(key))
            tier = 1 if (record or yrs >= 10) else 4
            parts = _lookback_parts(key, ctx, value, as_of)
            facts.append({"id": f"lookback:{key}", "family": fam, "tier": tier,
                          "years_since": yrs, "series": key,
                          "sentence": " ".join(x for x in parts if x),
                          # the email keeps the headline and any run-high
                          # correction, never the headline alone
                          "email": " ".join(x for x in parts[:2] if x),
                          "anchor_date": lb["last_touch"]["end"] if lb.get("last_touch") else None})
            break  # one per family: the first qualifying member

    # 2: pre-registered pair, in band today with a stable prior (the count
    # of past cases must not depend on which percentile cut is used)
    for name, p in (state.get("history_pairs") or {}).items():
        b = p["bands"]["10"]
        if b["today_in_band"] and p["track"] and p.get("stable_prior"):
            parts = _pair_parts(p, as_of)
            facts.append({"id": f"pair:{name}", "family": "pair", "tier": 2,
                          "sentence": " ".join(x for x in parts if x),
                          "email": " ".join(x for x in parts[:2] if x),
                          "anchor_date": p["track"][0]["entry"]})

    # 3: pace of this year's rate move
    pace = state.get("rate_pace", {})
    base = state.get("history_base_rates", {})
    for key in ("ust_10y", "ust_2y", "ust_30y"):
        yr = (pace.get(key) or {}).get("ytd")
        if yr and yr["rank"] <= 10:
            parts = _pace_parts(key, yr, pace[key].get("shock"), base)
            facts.append({"id": f"pace:{key}", "family": "pace", "tier": 3,
                          "sentence": " ".join(x for x in parts if x),
                          "email": parts[0]})
            break

    # 5: a stock-index move in its tail
    for key in ("spx", "ndx"):
        mk = (state.get("market_history") or {}).get(key)
        if mk and mk["move"]["in_tail"]:
            s_ = _move_sentence(mk, as_of)
            facts.append({"id": f"move:{key}", "family": "move", "tier": 5,
                          "sentence": s_, "email": s_})
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
