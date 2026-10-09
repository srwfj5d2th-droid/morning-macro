#!/usr/bin/env python3
"""check_history_prose.py — lint the day's prose against its history data.

Run after build_brief.py, before committing (ROUTINE.md step 8). Exit 1
blocks the commit: fix the prose and re-run. A failure caused by missing
data (not by prose) is reported as a note instead.

Why it exists (2026-10-09): the first edition that day skipped history
entirely, and the rushed second draft overclaimed it ("highest since 2007"
for a reading below that run's own peak; "never before" from exact-value
thresholds; outcomes measured from the end of past episodes). Each rule
below blocks one of those failure modes mechanically.

Usage: check_history_prose.py --content data/raw/content_<date>.json
       [--state data/state.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

HISTORY_BLOCKS = ["long_history", "history_digest", "then_vs_now", "rate_pace",
                  "curve_cycles", "history_pairs", "market_history", "cycle_map",
                  "history_base_rates"]
# fields where a historical year or percentile has to be backed by the data
# flags_html is left out on purpose: its system notes quote the phrases
# a correction withdrew
CHECKED_FIELDS = ["masthead_title", "regime_line", "story_html", "history_html",
                  "dashboard_interp_html", "client_lens_html", "concept_html",
                  "chart_of_day_why", "client_translation", "tier3_html", "movers_html"]
BANNED = [r"\bnever before\b", r"\bever recorded\b", r"\bsince records began\b",
          # forecast verbs only ("signals a recession"); "a signal" as a noun is fine
          r"\bsignals (?:a|an|that|the|recession|trouble|more|further)\b",
          r"\bpredicts?\b", r"\balways precedes?\b",
          r"\bwill likely\b", r"\bis likely to\b", r"\bhistory says\b",
          r"\bno precedent\b", r"\bunprecedented\b",
          r"\bwill (?:follow|come|happen|hit|cause|lead)\b",
          # an unattributed press framing set up to be knocked down (§4D)
          r"\bthe press will\b"]
# series names, for tying a percentile or superlative to the series it's about.
# The 10-year pattern skips the 10-year real yield / TIPS / breakeven.
SERIES_PATS = {
    "ust_10y": r"\b10-year(?![- ](?:real|TIPS|breakeven|inflation))\b|\b10Y(?! real| breakeven)\b",
    "ust_30y": r"\b30-year (?:Treasury|yield|bond)\b|\bthe 30-year\b|\b30Y\b",
    "ust_2y": r"\b2-year\b|\b2Y\b", "ust_3m": r"\b3-month\b|\b3M\b",
    "tips_10y_real": r"\b[Rr]eal yields?\b|\bTIPS\b",
    "real10_cleveland": r"\bCleveland\b",
    "bkeven_10y": r"\bbreakeven\b",
    "dxy": r"\b[Dd]ollar\b|\bDXY\b", "mortgage30": r"\b[Mm]ortgage rates?\b",
    "baa_10y_spread": r"\bBaa\b", "hy_oas": r"\bHY OAS\b|\bhigh-yield spreads?\b",
    "ig_oas": r"\bIG OAS\b", "sofr": r"\bSOFR\b", "kw_tp10": r"\bterm premium\b",
}
ORD_RE = re.compile(r"\b(\d{1,2}(?:\.\d)?)(?:st|nd|rd|th)\b(?![- ](?:largest|biggest|best|worst|highest|lowest|time))")
SOFT_LABEL_RE = re.compile(r"middle-of-the-pack|mid-range|mid-pack|unremarkable|nothing unusual", re.I)
COUNT_RE = re.compile(r"\b\d+ of \d+\b|\bone case\b|\btwo cases\b|\bonce\b|\btwice\b|"
                      r"\banecdote\b|\bone (?:past )?(?:episode|instance|stretch)\b", re.I)
BASE_RE = re.compile(r"\bnormal(?:ly)?\b|\bbase rate\b|\bany (?:\d+-month|12-month|one-year|"
                     r"two-year|three-year) stretch\b|\btypical\b", re.I)
OUTCOME_RE = re.compile(r"\bfollowed\b|\ba year later\b|\bnext (?:12 months|year)\b|"
                        r"\bover the following year\b|\bwhat came (?:next|after)\b|"
                        r"\b\d+ months after (?:it|each|that|the (?:stretch|inversion|shock|start)) (?:started|began)\b|"
                        r"\b(?:recession|S&P 500|stocks)\b[^.]{0,60}\b\d+ months (?:later|after)\b|"
                        r"\bbegan within\b|\brecessions?\b[^.]{0,40}\bwithin (?:one|two|three|\d+) years?\b", re.I)
MAX_HISTORY_WORDS = 300


def _text(html_fragment):
    t = re.sub(r"<[^>]+>", " ", html_fragment or "")
    t = (t.replace("&mdash;", "—").replace("&ndash;", "–").replace("&amp;", "&")
         .replace("&rsquo;", "'").replace("&ldquo;", '"').replace("&rdquo;", '"'))
    t = re.sub(r"&[a-z]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"(])|(?<=[.!?]\))\s+(?=[A-Z“\"(])", text)
    return [s.strip() for s in parts if s and s.strip()]


def _numbers_under_pct_keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "pct" in k and isinstance(v, (int, float)):
                out.append(float(v))
            _numbers_under_pct_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _numbers_under_pct_keys(v, out)
    return out


def _paragraphs(html_fragment):
    return [_text(p) for p in re.split(r"</p>|</li>", html_fragment or "") if _text(p)]


def _named(text, lh):
    return [k for k, pat in SERIES_PATS.items() if k in lh and re.search(pat, text)]


LEAD_PCT_KEYS = ("pct_rank_all_time", "pct_rank_modern",
                 "cleveland_pct_all_time", "cleveland_pct_modern")
# a sentence that names one series is checked against that series' own
# percentile ranks only (not every number under a "pct" key -- decade shares
# and returns would let invented percentiles through)
OUTAGE_RE = re.compile(r"fail|unavailable|no historical comparison", re.I)
# the series' names for superlative / since / record rules
NAMES = {"ust_10y": SERIES_PATS["ust_10y"], "ust_30y": r"30-year|30Y", "ust_2y": r"2-year|2Y",
         "tips_10y_real": r"[Rr]eal yield|TIPS", "dxy": r"[Dd]ollar|DXY",
         "mortgage30": r"[Mm]ortgage", "baa_10y_spread": r"Baa|[Cc]redit spread"}


def _sup_for(lb):
    """Superlatives on the series' own side: "highest since" for a high-side
    reading, "lowest since" for a low-side one."""
    hi = lb.get("side", "high") == "high"
    w, lvl, ab = ("highest|widest", "high", "above") if hi else ("lowest|tightest", "low", "below")
    return re.compile(rf"\b(?:{w})\s+(?:level\s+)?(?:since|in \d+ years)\b|\bat its (?:{w})\b|"
                      rf"\b\d+-year {lvl}\b|\b{ab} (?:every|all|any)\b(?:[^.;]|\.\d){{0,80}}?\bsince\b",
                      re.I)


def _clauses(sent):
    return re.split(r";|,\s+(?:yet|but|while|though|and today)\b", sent)


def lint(content, state):
    errors, notes = [], []
    as_of_year = int(state["row_date"][:4])
    fields = {f: _text(content.get(f, "")) for f in CHECKED_FIELDS}
    hist = fields["history_html"]

    # 4. banned overclaims and forecast verbs -- these need no history data
    for field, text in fields.items():
        for pat in BANNED:
            for m in re.finditer(pat, text, re.I):
                errors.append(f"{field}: banned phrase '{m.group(0)}' (§4C/§4F)")

    blocks = {k: state.get(k) for k in HISTORY_BLOCKS if state.get(k) is not None}
    if not blocks:
        if state.get("history_error"):
            # the history files failed to load: no long-run number can be checked,
            # so none may appear, and the section must say why it's thin
            for field, text in fields.items():
                for m in re.finditer(r"\d{1,3}(?:\.\d)?(?:st|nd|rd|th) percentile|"
                                     r"\d{1,3}(?:\.\d)? of every 100 days", text):
                    errors.append(f"{field}: '{m.group(0)}' cites long-run history on a day it "
                                  f"failed to load ({state['history_error']})")
            if hist and not OUTAGE_RE.search(hist):
                errors.append("history_html must say the long-run history failed to load today")
        else:
            notes.append("no history blocks in state.json (data/history missing?) — "
                         "history rules skipped")
        return errors, notes
    corpus = json.dumps(blocks)
    pct_values = _numbers_under_pct_keys(blocks, [])
    lh = state.get("long_history") or {}
    tvn = {r["key"]: r for r in (state.get("then_vs_now") or {}).get("rows", [])}

    # 1. the section exists and stays short
    if not hist:
        errors.append("history_html is empty — every brief carries 'Today in history'")
    n_words = len(hist.split())
    if n_words > MAX_HISTORY_WORDS:
        errors.append(f"history_html is {n_words} words (max {MAX_HISTORY_WORDS}) — "
                      "deeper, not longer; the History check box already carries the facts")

    for field, text in fields.items():
        # 2. every past year must exist somewhere in the history data
        for y in sorted(set(re.findall(r"\b(19\d\d|20\d\d)\b", text))):
            if int(y) >= as_of_year:
                continue
            if y not in corpus:
                errors.append(f"{field}: year {y} isn't in any state.json history block "
                              "(recalled, not computed? §4C)")
        # 3. every "Nth percentile" / "N of every 100 days" must match a stored
        #    percentile -- of the series the sentence names, when it names one
        for sent in _sentences(text):
            named = _named(sent, lh)
            if named:
                allowed = ([float(lh[k][f]) for k in named for f in LEAD_PCT_KEYS
                            if isinstance(lh[k].get(f), (int, float))]
                           + [float(tvn[k][f]) for k in named if k in tvn
                              for f in ("pct_then", "pct_now", "pct30_then", "pct30_now")
                              if isinstance(tvn[k].get(f), (int, float))])
            else:
                allowed = pct_values
            for m in re.finditer(r"(\d{1,3}(?:\.\d)?)(?:st|nd|rd|th) percentile", sent):
                v = float(m.group(1))
                if not any(abs(v - p) <= 0.6 for p in allowed):
                    errors.append(f"{field}: '{m.group(0)}' doesn't match a stored percentile"
                                  + (f" for {', '.join(named)}" if named else ""))
            for m in re.finditer(r"(\d{1,3}(?:\.\d)?) of every 100 days", sent):
                v = float(m.group(1))
                if not any(abs(v - p) <= 0.6 or abs(v - (100 - p)) <= 0.6 for p in allowed):
                    errors.append(f"{field}: '{m.group(0)}' doesn't match a stored percentile")
        # 5. any 'what came next' sentence carries its count and the normal rate
        sents = _sentences(text)
        for i, sent in enumerate(sents):
            has_year = re.search(r"\b(19\d\d|20\d\d)\b", sent)
            if OUTCOME_RE.search(sent) and (has_year or re.search(r"\b\d+ of \d+\b", sent)):
                if has_year and not COUNT_RE.search(sent):
                    errors.append(f"{field}: outcome sentence without a count/anecdote label: "
                                  f"“{sent[:120]}…”")
                nxt = sents[i + 1] if i + 1 < len(sents) else ""
                if not (BASE_RE.search(sent) or BASE_RE.search(nxt)) and not re.search(
                        r"anecdote|one case|once", sent, re.I):
                    errors.append(f"{field}: outcome sentence without the normal rate: "
                                  f"“{sent[:120]}…”")
        # 6. HY/IG OAS percentiles are only ever 'of ~3 years'
        for sent in _sentences(text):
            if re.search(r"\b(HY|IG) OAS\b|high-yield spread", sent) and "percentile" in sent \
                    and not re.search(r"\b(3|three)[- ]years?\b|~3", sent):
                errors.append(f"{field}: HY/IG OAS percentile without the ~3-year label: "
                              f"“{sent[:120]}…”")

    # 7. superlatives on the series' own side:
    #    (a) never "highest since" for a reading below its own run's peak
    #        (5.22% on a day the run had peaked at 5.31% is not "the highest
    #        since 2007") -- unless that clause is about the peak itself;
    #    (b) a year after "since" must be one the lookback actually found
    for key, pat in NAMES.items():
        lb = (lh.get(key) or {}).get("lookback") or {}
        if not lb:
            continue
        sup = _sup_for(lb)
        peak_ref = re.compile(rf"{lb.get('run_extreme', 0):.2f}|\bthis run'?s? (?:high|low|peak)|"
                              r"\bthis run peaked\b|\brun (?:high|low|peak)\b", re.I)
        ok_years = {(lb.get(x) or {}).get("end", "")[:4]
                    for x in ("last_touch", "last_sustained", "run_extreme_prior")} - {""}
        for field, text in fields.items():
            for sent in _sentences(text):
                if not re.search(pat, sent):
                    continue
                if not lb.get("today_is_run_extreme", True) and any(
                        sup.search(c) and not peak_ref.search(c) for c in _clauses(sent)):
                    errors.append(f"{field}: “highest/lowest since” for {key}, but today isn't "
                                  f"this run's extreme ({lb.get('run_extreme')} on "
                                  f"{lb.get('run_extreme_date')}): “{sent[:120]}…”")
                for c in _clauses(sent):
                    m = sup.search(c)
                    y = re.search(r"\bsince (?:\w+ )?((?:19|20)\d\d)\b", c[m.start():]) if m else None
                    if y and ok_years and y.group(1) not in ok_years:
                        errors.append(f"{field}: “… since {y.group(1)}” for {key}, but the "
                                      f"lookback found {', '.join(sorted(ok_years))}: “{sent[:120]}…”")

    # 8. the lead 'last time' fact must be used, not skipped
    for f in state.get("history_digest") or []:
        if f.get("tier") == 1 and f["id"].startswith("lookback:") and f.get("anchor_date"):
            y = f["anchor_date"][:4]
            if y not in hist:
                errors.append(f"history_html never mentions {y}, the lead fact "
                              f"({f['id']}) — interpret the History check, don't skip it")
            if not any(y in fields[k] for k in ("regime_line", "story_html", "masthead_title")):
                errors.append(f"the lead history fact ({f['id']}, {y}) appears in neither the "
                              "regime line, the story, nor the masthead")
            break

    # 9. TIPS-window caveat when the Cleveland record disagrees
    tips = lh.get("tips_10y_real") or {}
    if tips.get("tips_window_divergence") and re.search(r"real yield|TIPS", hist) \
            and re.search(r"\b2008\b|\b2003\b|percentile", hist) \
            and not re.search(r"Cleveland|1982", hist):
        errors.append("history_html cites the TIPS record without the Cleveland/1982 "
                      "cross-check (tips_window_divergence is true)")

    # 10. when a series' two percentiles diverge, a paragraph that cites one
    #     (or calls it 'middle-of-the-pack') must cite both (§4F). The
    #     script's own "N of every 100 days" wording counts as a citation.
    for field in CHECKED_FIELDS:
        for para in _paragraphs(content.get(field, "")):
            ords = [float(x) for x in ORD_RE.findall(para)]
            for x in re.findall(r"(\d{1,3}(?:\.\d)?) of every 100 days", para):
                ords += [float(x), 100.0 - float(x)]
            for key in _named(para, lh):
                e = lh[key]
                if not e.get("regime_divergence") or e.get("pct_rank_modern") is None:
                    continue
                a, m = e["pct_rank_all_time"], e["pct_rank_modern"]
                has_a = any(abs(o - a) <= 0.6 for o in ords)
                has_m = any(abs(o - m) <= 0.6 for o in ords)
                # a soft label counts only right after the series' name
                soft = any(0 <= sl.start() - nm.start() <= 100
                           for nm in re.finditer(SERIES_PATS[key], para)
                           for sl in SOFT_LABEL_RE.finditer(para))
                if has_a != has_m or (soft and not (has_a and has_m)):
                    errors.append(f"{field}: {key} cited on one lens only — its percentiles "
                                  f"diverge ({a:.0f} all-time vs {m:.0f} over 30 years); show both "
                                  f"(§4F): “{para[:120]}…”")

    # 11. "has been above <today's level> since <date>" only for an unbroken
    #     run (a lower level, or the digest's "there on N of the M", is fine)
    since_re = re.compile(r"\b(?:has|have) (?:been|stayed|held|remained) (?:at or )?"
                          r"(?:above|below|over|under|there|here)\b(?:[^.;]|\.\d){0,60}\bsince\b", re.I)
    for key, pat in NAMES.items():
        e = lh.get(key) or {}
        lb = e.get("lookback") or {}
        if lb.get("current_run_unbroken", True):
            continue
        today = e.get("latest_value")
        for field, text in fields.items():
            for sent in _sentences(text):
                m_ = since_re.search(sent)
                if not m_ or not re.search(pat, sent) or re.search(r"\bthere on \d+ of the \d+\b", sent):
                    continue
                lvls = [float(x) for x in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)", m_.group(0))]
                if not lvls or today is None or any(abs(x - today) <= 0.05 for x in lvls):
                    errors.append(f"{field}: “has been … since” for {key}, but its current run has "
                                  f"dips ({lb.get('current_run_sessions')} of "
                                  f"{lb.get('current_run_total_sessions')} sessions): “{sent[:120]}…”")

    # 12. "record" for a Tier 1 series only when the data says so
    rec_re = re.compile(r"\b(?:a|an|new|fresh) record\b|\ball-time (?:high|low)\b|\brecord (?:high|low)\b", re.I)
    for key, pat in NAMES.items():
        lb = (lh.get(key) or {}).get("lookback") or {}
        if not lb or lb.get("record"):
            continue
        run_ref = re.compile(rf"{lb.get('run_extreme', 0):.2f}|\bthis run\b|\brecord run\b", re.I)
        for field, text in fields.items():
            for sent in _sentences(text):
                if re.search(r"\bnot a record\b|\bno record\b", sent, re.I):
                    continue
                if lb.get("run_is_record") and run_ref.search(sent):
                    continue  # the run's peak is the record, and the sentence says so
                for m in rec_re.finditer(sent):
                    # the series has to be the record's subject: named just
                    # before it, in the same clause
                    pre = sent[:m.start()].split(",")[-1]
                    if re.search(pat, pre[-40:]):
                        errors.append(f"{field}: “record” for {key}, but it isn't one: "
                                      f"“{sent[:120]}…”")
                        break

    # 13. "last reached in <year>" for a series already in a multi-session run
    #     must say "before this run" (on 10-09 the 10-year had been at or above
    #     5.22% for eight sessions; "a level last reached in June 2007" read
    #     as if today were the first time back)
    last_re = re.compile(r"\blast (?:reached|touched|seen|hit|there|at)\b[^.;]{0,40}?\b(?:19|20)\d\d\b", re.I)
    for key, pat in NAMES.items():
        lb = (lh.get(key) or {}).get("lookback") or {}
        if (lb.get("current_run_total_sessions") or 1) <= 1:
            continue
        for field, text in fields.items():
            for sent in _sentences(text):
                if re.search(pat, sent) and any(
                        last_re.search(c) and not re.search(r"before this run|\bthis run'?s? (?:high|low|peak)\b|"
                                                             r"\bthis run peaked\b|\brun (?:high|low|peak)\b", c, re.I)
                        for c in _clauses(sent)):
                    errors.append(f"{field}: “last reached in …” for {key} without “before this "
                                  f"run” (it has been there since {lb.get('current_run_start')}): "
                                  f"“{sent[:120]}…”")
    return errors, notes


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True)
    ap.add_argument("--state", default=str(REPO / "data" / "state.json"))
    a = ap.parse_args(argv)
    content = json.loads(Path(a.content).read_text())
    state = json.loads(Path(a.state).read_text())
    errors, notes = lint(content, state)
    for n in notes:
        print(f"note: {n}")
    for e in errors:
        print(f"FAIL: {e}")
    if errors:
        print(f"{len(errors)} history-prose problem(s) — fix the prose and re-run; "
              "do not commit a failing brief.")
        return 1
    print("history prose OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
