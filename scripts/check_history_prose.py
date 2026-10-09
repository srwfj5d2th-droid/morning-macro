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
CHECKED_FIELDS = ["masthead_title", "regime_line", "story_html", "history_html",
                  "dashboard_interp_html", "client_lens_html", "concept_html",
                  "chart_of_day_why", "client_translation"]
BANNED = [r"\bnever before\b", r"\bever recorded\b", r"\bsince records began\b",
          # forecast verbs only ("signals a recession"); "a signal" as a noun is fine
          r"\bsignals (?:a|an|that|the|recession|trouble|more|further)\b",
          r"\bpredicts?\b", r"\balways precedes?\b",
          r"\bwill likely\b", r"\bis likely to\b", r"\bhistory says\b",
          r"\bno precedent\b", r"\bunprecedented\b"]
COUNT_RE = re.compile(r"\b\d+ of \d+\b|\bone case\b|\btwo cases\b|\bonce\b|\btwice\b|"
                      r"\banecdote\b|\bone (?:past )?(?:episode|instance|stretch)\b", re.I)
BASE_RE = re.compile(r"\bnormal(?:ly)?\b|\bbase rate\b|\bany (?:\d+-month|12-month|one-year|"
                     r"two-year|three-year) stretch\b|\btypical\b", re.I)
OUTCOME_RE = re.compile(r"\bfollowed\b|\ba year later\b|\bnext (?:12 months|year)\b|"
                        r"\bover the following year\b|\bwhat came (?:next|after)\b", re.I)
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


def lint(content, state):
    errors, notes = [], []
    as_of_year = int(state["row_date"][:4])
    blocks = {k: state.get(k) for k in HISTORY_BLOCKS if state.get(k) is not None}
    if not blocks:
        notes.append("no history blocks in state.json (data/history missing?) — "
                      "history rules skipped")
        return errors, notes
    corpus = json.dumps(blocks)
    pct_values = _numbers_under_pct_keys(blocks, [])

    fields = {f: _text(content.get(f, "")) for f in CHECKED_FIELDS}
    hist = fields["history_html"]

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
        # 3. every "Nth percentile" must match a stored percentile
        for m in re.finditer(r"(\d{1,3}(?:\.\d)?)(?:st|nd|rd|th) percentile", text):
            v = float(m.group(1))
            if not any(abs(v - p) <= 0.6 for p in pct_values):
                errors.append(f"{field}: '{m.group(0)}' doesn't match a stored percentile")
        # 4. banned overclaims and forecast verbs
        for pat in BANNED:
            for m in re.finditer(pat, text, re.I):
                errors.append(f"{field}: banned phrase '{m.group(0)}' (§4C/§4F)")
        # 5. any 'what came next' sentence carries its count and the normal rate
        for sent in _sentences(text):
            if OUTCOME_RE.search(sent) and re.search(r"\b(19\d\d|20\d\d)\b", sent):
                if not COUNT_RE.search(sent):
                    errors.append(f"{field}: outcome sentence without a count/anecdote label: "
                                  f"“{sent[:120]}…”")
                if not BASE_RE.search(sent) and not re.search(r"anecdote|one case|once", sent, re.I):
                    errors.append(f"{field}: outcome sentence without the normal rate: "
                                  f"“{sent[:120]}…”")
        # 6. HY/IG OAS percentiles are only ever 'of ~3 years'
        for sent in _sentences(text):
            if re.search(r"\b(HY|IG) OAS\b|high-yield spread", sent) and "percentile" in sent \
                    and not re.search(r"\b(3|three)[- ]years?\b|~3", sent):
                errors.append(f"{field}: HY/IG OAS percentile without the ~3-year label: "
                              f"“{sent[:120]}…”")

    # 7. the lead 'last time' fact must be used, not skipped
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

    # 8. TIPS-window caveat when the Cleveland record disagrees
    tips = (state.get("long_history") or {}).get("tips_10y_real") or {}
    if tips.get("tips_window_divergence") and re.search(r"real yield|TIPS", hist) \
            and re.search(r"\b2008\b|\b2003\b|percentile", hist) \
            and not re.search(r"Cleveland|1982", hist):
        errors.append("history_html cites the TIPS record without the Cleveland/1982 "
                      "cross-check (tips_window_divergence is true)")
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
