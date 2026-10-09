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

- [x] **History as a section, not a guardrail.** The 10-08 layer was used
  only defensively. Today's first edition cited 120-day z-scores and one
  percentile, and missed findings that were already in `state.json`: the
  10Y at its highest since June 2007, a real yield matched only in the
  2008 crisis, and real rates this high alongside credit this tight with no
  precedent since 2003. Shipped the same day, re-issued as today's second
  edition. Shipped: "first time since" episodes with backdrop (fed funds,
  S&P next year), standing cross-series combinations, return-based context
  for S&P/Nasdaq/WTI/gold, and DXY long history (gap closed). Also: a
  mechanical "Today in history" section, a one-line email headline, a
  build-time refusal when the section is missing, and a generated markdown
  twin. Data-integrity catch along the way: unverifiable 2002-06 30Y values
  are excluded (README).
- [ ] **Monthly refresh now covers Yahoo files too.** Run
  `build_long_history.py --refresh` at review. Between refreshes, live
  closes from `macro_series.csv` fill the gap (see `compute_state.py`).
- [ ] **Candidate additional combinations** for review (keep the standing
  set small so each one stays meaningful): e.g. oil YTD strength plus
  breakevens, curve slope plus credit.
