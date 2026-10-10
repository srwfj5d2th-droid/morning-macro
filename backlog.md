# Backlog — batched to monthly review (§10: no daily design changes)

Opened at build, 2026-08-19:

- [ ] **Calm regime color**: `#64707D` chosen provisionally (§9 palette defines
  only the four loud regimes). Ratify or replace at 30-day review.
- [ ] **Market-holiday protocol** (§4E left "decided at build"): current default
  is a one-line "markets closed" notice, no brief. Ratify.
- [ ] **Weekly-series z-windows**: WALCL/WTREGEN accumulate ~52 observations a
  year, so the 60-observation seasoning floor keeps them "thin" for ~14 months.
  Consider a weekly-cadence z-window at review.
- [ ] **FMP plan tier**: forex, batch quotes, constituents, screener, economic
  calendar, news, and ETF holdings are all gated on the current tier, and
  single quotes intermittently rate-limit under parallel bursts. Everything is
  substituted with free sources (see CLAUDE.md §14). Standing constraint
  (Jacob, 2026-08-21): **no paid services** — if a substitute source breaks,
  find another free one; paid upgrades (FMP tiers, Bigdata credits) are off
  the table unless Jacob reverses that decision at a review.
- [ ] **Yahoo dependence**: DXY, WTI, gold, copper, index closes, and the
  movers scan all ride Yahoo's unofficial v8/spark endpoints. Stable for years,
  but unofficial. Document a fallback order at review (stooq is currently dead;
  FRED DTWEXBGS can stand in for DXY at a 1-day lag).
- [ ] **Scheduled-task run-limit check** (§13.1) and **Gmail-connector check in
  the task context** (§13.3) — perform when the task is created, after manual
  brief approval.

Opened 2026-10-05 (Jacob flagged live, same morning as the 2026-10-05 brief):

- [x] **"Widest/largest this system has recorded" needs historical context by
  default.** Shipped 2026-10-08, same day Jacob asked for it directly in
  conversation (not held for the monthly batch — a direct build request
  isn't a daily design whim, §10's freeze is about unprompted changes).
  Built per §4F: `scripts/build_long_history.py` pulls real FRED history
  (Treasury yields to 1962, effective fed funds to 1954, NBER recessions to
  1945, Moody's Baa/Aaa corporate yields to 1983-86); `scripts/history_context.py`
  computes all-time percentile rank, most-recent-comparable reading (+
  whether a recession followed within 12mo), matching named episodes, and
  curve-inversion-vs-recession lag for 2s10s/3m10y; `compute_state.py`
  attaches it all to `data/state.json`; the dashboard table gained a "Hist.
  %ile" column. Known limitation, disclosed rather than papered over: this
  environment's FRED mirror only carries ~3 years of the literal ICE BofA
  HY/IG OAS series regardless of requested range (real FRED has 1996+) —
  `ig_oas` gets a genuine 40-year Baa-Treasury-spread proxy for direction/
  timing only (never magnitude; Baa is investment-grade and runs
  structurally tighter than junk spreads), `hy_oas` gets no numeric proxy
  at all, just its own honest short window. DXY has no long-run source
  built yet either — real gap, not yet closed. First live finding from
  running it against 2026-10-06's data: nearly every Tier 1 series the
  120-day z-score had been flagging as "elevated" (3m/2y/10y/30y yields,
  2s10s, 3m10y, SOFR, HY OAS, IG OAS) actually sits at or near its
  *historical median* (38th-59th percentile over 40-72 years) — one
  conspicuous exception, the 10Y real yield (TIPS), which genuinely is at
  the 100th percentile of its ~23-year history. The system had been
  overstating significance across the board; this is the correction.

  **Same-day follow-up (Jacob):** sharp catch — pointed out that an average
  over 40 years can itself mislead (e.g. a 40-year average mortgage rate
  near 7% looks "normal" today, even though rates spent most of those
  years well below it) and asked whether the percentile math was making
  the same mistake. Checked: no, percentile rank is an order statistic
  (count below/above), not a mean, so it was never vulnerable to that
  specific trap — confirmed against the system's own data (10Y Treasury's
  64yr mean 5.80% vs. median 5.39%, and the code uses the latter). But the
  real, sharper version of the concern — does pooling 60+ years hide a
  genuine regime shift — did apply. Fixed same day: every `long_history`
  entry now carries a second reading, the trailing-30-year percentile
  (`pct_rank_modern`), plus a `regime_divergence` flag when it disagrees
  with the all-time one by 20+ points. First real catch: the 10-year
  Treasury's 49th all-time percentile and 87th trailing-30-year percentile
  diverge by 38 points — unremarkable since the 1960s, genuinely elevated
  against the last 30 years. UST 2Y, 30Y, and the fed-funds/SOFR proxy
  diverge the same way; the curve spreads and credit proxies don't. The
  dashboard column is now "%ile all/30y" (`49/87†`), and §4F requires
  citing both when they diverge rather than picking the more convenient one.

Opened 2026-10-09 (Jacob, live: "I still didn't see in the morning macro a deeper connection to historical context like I've been asking for"):

- [x] **History as a section, not a guardrail.** Shipped the same day as a
  re-issue of the 2026-10-09 brief.
  - *What the first edition missed.* It cited 120-day z-scores and one
    defensive percentile. It missed the 10Y at a level last reached (briefly)
    in June 2007, this run's 5.31% peak last matched in May 2002, and this
    year's 9th-fastest 10Y rise since 1963.
  - *What the first draft got wrong.* It was rushed and overclaimed. An
    independent advisor/statistician/historian design review and a separate
    verification pass both caught the same biases:
    - outcomes measured from the end of past episodes
    - "never before" produced by exact-value thresholds
    - "highest since 2007" for a reading below its own run's peak
    - a TIPS-only real-yield record
    - curve inversions counted by fragment (18/14 instead of 5 cycles/4)
    - an untested term-premium attribution
  - *What shipped.* History v2 (see CLAUDE.md §4F amendment and
    `data/history/README.md`), with a digest, a prose linter, and a
    regression test that the first edition fails it.
  - *Data-integrity catches along the way:*
    - unverifiable 2002–06 30Y values (excluded)
    - Yahoo partial intraday bars (no longer stored)
    - Yahoo gold-futures history revised after a roll (the live series now
      overrides it)
    - SVG metadata leaking into the markdown twin
- [x] **Second verification pass (v2.1), same day.** About 40 independent
  checks found that v2's numbers reproduced, but some wording didn't match
  them. All of the following were fixed before the re-issue merged, each
  with a regression test:
  - "quiet lately" printed for series never measured (mortgage rates had
    jumped a point);
  - one-lens percentiles where the two diverge (Cleveland real rate, the
    '80s client line);
  - "has been here since" for a run with dips;
  - a pair's "twice before" that held only at one cutoff;
  - "briefly" for 9 monthly readings;
  - a record flag that ignored the run's own peak;
  - normal rates that included months already in recession, and a curve
    base rate from the wrong years;
  - an email line that dropped its qualifier;
  - causal links in Story/Movers/Tier 3 that the reporting doesn't make;
  - an incomplete corrections note.
- [x] **Third verification pass (v2.1, round 2), same day.** 8 independent
  checks (numbers, code, rules, reader) confirmed 41 findings, all fixed
  with tests before merge. The weightiest:
  - the brief used the 10-07 high-yield print to say credit "didn't confirm"
    the 10-08 selloff;
  - the regime line called 5.22% "a level last reached in June 2007" on the
    run's ninth session;
  - TIPS's 23-year record was labeled "historically extreme";
  - the email's history line carried a "highest since 2002" with no
    percentiles;
  - oil and energy causes were stated in the brief's own voice;
  - the NR routing flag was missing;
  - three claim-grading closes had no source file (now
    `data/raw/claims_check_2026-10-09.json`);
  - a crash on the first sessions of a year;
  - linter gaps (a since-year the data never found, decade shares
    accepted as percentiles, the history-outage path skipping every
    rule).
- [ ] **Movers scan: ex-dividend days overstate declines** (found 2026-10-10).
  `scan_movers.py` measures the 1-day move against the raw prior close. On an
  ex-dividend date that counts the dividend as a price drop: Verizon
  -10.14% raw vs. -8.75% adjusted, AT&T -10.82% vs. -9.81% (both went ex on
  2026-10-09; `data/raw/dividends_2026-10-09.json`). The exchange-reported
  move adjusts the prior close. Consider fetching Yahoo `events=div` in the
  scan and reporting the adjusted move (it can also change which names clear
  the 4% screen). Until then, the brief states the basis when it matters.
- [ ] **Then-vs-now similarity in native units.** The pinned rule (within 15
  percentile points on both views) calls the 30Y mortgage rate +0.66 points
  "similar" (14.6 points apart on the 30-year view). The gap is now shown
  in the cell, but consider a per-row unit tolerance at review.
- [ ] **Monthly refresh now covers the Yahoo files and the new FRED reference
  series.** Run `build_long_history.py --refresh` at review. Between
  refreshes the live series fills recent days.
- [ ] **Ratify the pinned history thresholds** (the `history_context.py` v2
  constants): the 80/20 tail gate, 365-day stretch gap, 20-reading
  "sustained", 10-reading minimum, 5-year regime cap, 10/20/25 pair bands,
  and 15-point then-vs-now similarity.
- [ ] **Deferred from the design review, computed but not shipped.** Each
  needs ratification so the system doesn't add analogs ad hoc.
  - *Bond-holder pain rank.* Modeled 10Y constant-maturity total return
    YTD: about −4.7%, 9th-worst of 64 years.
  - *Nearest-neighbour era finder.* It points to the late 1990s; outcomes
    split from −10% to +38%. Pre-register its features first.
  - *Inflation-adjusted oil level.* Needs CPIAUCSL: WTI spot was the 92nd
    percentile nominal vs. the 74th real.
  - *Long-run mini-chart* for the chart of the day.
  - *Analog-overlay chart.*
  - *Mortgage rate in the digest's rates family* (the mortgage row is only
    in the table today).
  - *Further pre-registered pairs.*
