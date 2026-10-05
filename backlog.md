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

- [ ] **"Widest/largest this system has recorded" needs historical context by
  default.** The 2026-10-05 brief originally called HY OAS's print "the widest
  reading this system has ever recorded" with no caveat — technically true,
  but this system only has ~8 months of data, so "ever" implied far more than
  it could support. Corrected same-day with real historical comparisons (HY
  OAS's long-run median since 1996, and its peaks in 2008/2020/2015-16/2022),
  sourced to FRED/TradingEconomics. Proposed standing fix for the monthly
  review: any time a brief calls a reading a record *within this system's own
  data*, it must pair that claim with where the series has actually traded
  historically (a small reference table of known peaks/median per Tier 1
  series, hand-maintained or scripted), not rely on the model remembering to
  add context after the fact. Candidate implementation: a
  `data/historical_context.json` reference file (median + major-episode peaks
  per series, sourced once, cited going forward) that `compute_state.py` or
  the model consults before any "record"/"widest"/"largest" claim.
