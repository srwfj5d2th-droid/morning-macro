# Long-run historical reference data (§4F)

Added 2026-10-08. Jacob's ask: "the highest reading this system has tracked"
is meaningless when the system is 10 months old. He needs to know what a
reading means against real market history — and whether moves like it have
preceded recessions, pullbacks, or nothing at all.

**Not part of the daily pipeline.** This is slow-changing reference data,
refreshed periodically via `scripts/build_long_history.py --refresh` (at
monthly review, or sooner if a gap matters), not every morning. `compute_state.py`
reads whatever is currently on disk here; it does not re-fetch it.

## What's in here, and the honest limits of each

| File | FRED series | Real coverage | Notes |
|---|---|---|---|
| `dgs3mo.csv` | DGS3MO | 1981-09-01+ | 3-month Treasury |
| `dgs2.csv` | DGS2 | 1976-06-01+ | 2-year Treasury |
| `dgs10.csv` | DGS10 | 1962-01-02+ | 10-year Treasury |
| `dgs30.csv` | DGS30 | 1977-02-15+ | 30-year Treasury. Treasury suspended the 30Y bond 2002-02-18 to 2006-02-09 and the official series has no readings then — but this environment's file carries ~1,000 values in that window (found 2026-10-09). Provenance unverifiable, so `history_context.py` excludes 2002-02-19..2006-02-08 from every calculation (`exclude` in `SOURCES`). |
| `dfii10.csv` | DFII10 | 2003-01-02+ | 10Y TIPS real yield — TIPS didn't exist before this |
| `t10yie.csv` | T10YIE | 2003-01-02+ | 10Y breakeven inflation — same constraint |
| `dff.csv` | DFF | 1954-07-01+ | Effective fed funds rate — **SOFR's long-run proxy**; SOFR itself only exists from 2018 |
| `dbaa.csv` | DBAA | 1986-01-02+ | Moody's Baa (lowest investment-grade rung) corporate bond yield, daily |
| `daaa.csv` | DAAA | 1983-01-03+ | Moody's Aaa corporate bond yield, daily |
| `usrec.csv` | USREC | 1945-01-01+ | NBER recession indicator, monthly 0/1 — recession date ranges in `episodes.json` are derived from this, not hand-typed |
| `baml_hy_oas.csv` | BAMLH0A0HYM2 | **2023-10-09+ only** | See constraint below |
| `baml_ig_oas.csv` | BAMLC0A0CM | **2023-10-09+ only** | Same constraint |
| `wti_spot.csv` | DCOILWTICO | 1986-01-02+ | WTI spot (Cushing) — deeper than the futures file, but spot ≠ front-month (they can differ by several dollars in a tight market), so it's a labeled proxy only; not currently consumed |

Added 2026-10-09 from Yahoo's v8 chart endpoint (true daily bars via an
explicit `period1/period2` window — `range=max` silently downsamples to
monthly). Same symbols the daily pull quotes, so history and live series are
one instrument (cross-checked: 10-05 through 10-08 closes match
`macro_series.csv` exactly):

| File | Yahoo symbol | Real coverage | Notes |
|---|---|---|---|
| `spx.csv` | ^GSPC | 1927-12-30+ | S&P 500 |
| `ixic.csv` | ^IXIC | 1971-02-05+ | Nasdaq Composite (this system's `ndx` key) |
| `dxy.csv` | DX-Y.NYB | 1971-01-04+ | ICE U.S. Dollar Index — **closes the DXY gap below** |
| `wti_fut.csv` | CL=F | 2000-08-23+ | WTI front-month futures (the live series) |
| `gold_fut.csv` | GC=F | 2000-08-30+ | Gold front-month futures (the live series) |

Yahoo files carry a partial bar for the current session when fetched
intraday; every consumer clips to the brief's as-of date, so it never
leaks into a comparison.

### The HY/IG OAS constraint — read this before trusting a credit-spread percentile

Real-world FRED carries BAMLH0A0HYM2 and BAMLC0A0CM back to 1996-12-31. In
*this* environment, the fredgraph chart API itself reports `min_date:
"2023-10-09"` for both series regardless of the `cosd` requested — verified
live 2026-10-08, not assumed. That is a constraint of this sandbox's FRED
mirror, not a request-tuning problem. `scripts/build_long_history.py` has
tried every requested-range value worth trying; if a future session finds a
way to get the real 1996+ history, update this file and re-run the refresh.

Until then: `hy_oas` and `ig_oas` get an honest ~3-year percentile only
(`short_history: true` in `history_context.py`'s output — never silently
upgraded to look like a decades-long claim). For a genuine multi-decade
credit-risk-premium read, `ig_oas` carries a `proxy_key` pointing at
`baa_10y_spread` (Moody's Baa yield minus the 10Y Treasury, real history
back to 1986). **`hy_oas` deliberately has no numeric proxy** — Baa is
investment-grade, a full tier or more above the junk-rated universe HY OAS
actually measures, and its magnitude runs structurally far tighter (2008
peak ~6.2pp vs. HY OAS's own ~21.8% peak, per this system's own earlier
published citation). Using it as a magnitude stand-in for HY OAS would trade
one overclaim for a different one. It's fair to use for *episode timing*
(did credit broadly tighten/widen, and when) — never for *magnitude*.

### What has no long-run source at all (and isn't getting one yet)

Fed balance sheet, TGA, and ON RRP are structurally modern-only instruments
(ON RRP facility created 2014; TGA/WALCL as currently reported are a QE-era
construct) — there's no pre-2008-ish "normal" to compare against, so no
history file is built for them. (DXY was listed here until 2026-10-09; it
now has daily history to 1971 via Yahoo, above.)

## `episodes.json`

Two lists. `recessions` are NBER-dated windows, computed directly from
`usrec.csv` by inspecting the 0/1 series for its own transitions — re-derive
after any refresh rather than hand-editing. `named_episodes` are
hand-curated date ranges for well-known market/credit stress windows that
aren't all NBER recessions (1987 crash, 1994 bond selloff, 1998 LTCM, 2011
eurozone/debt-ceiling, 2015-16 energy bust, 2018 Q4 selloff, 2013 taper
tantrum, 2022-23 hiking cycle). The *date ranges* are well-established
historical facts. Every min/max/median *value* a brief states for a series
during one of these windows is computed live from the CSVs above by
`scripts/history_context.py` — never typed into this file or recalled from
training data (§4C).

## Consumption

`scripts/history_context.py` is the only code that reads these files.
`scripts/compute_state.py` calls it and attaches a `long_history` block
(percentile rank, percentile breakpoints, most recent comparable reading
and whether a recession followed within 12 months, matching named episodes)
to `data/state.json` for every Tier 1 series listed in its
`LONG_HISTORY_KEYS`, plus a `curve_inversions` summary for 2s10s and 3m10y
(material inversion episodes and their historical lag to the next
recession, capped at 36 months). The dashboard table's "%ile all/30y" column
and any brief prose citing long-run context must come from this block —
never from memory.

### All-time percentile vs. trailing-30-year percentile

Added same day, Jacob's follow-up: percentile rank already isn't the
mean-skew trap (it's an order statistic — checked directly against this
system's own pulled data, the 10Y's 64-year mean is 5.80% but its median is
5.39%, and the percentile machinery uses the median-style order statistic,
not the mean). But pooling 60+ years into one number still pools genuinely
different monetary regimes — Volcker-era double-digit rates, the Great
Moderation, the ZIRP era, now. A reading can look unremarkable against the
full pool while running hot against the last 30 years, or the reverse.

Every `long_history` entry (where there's enough history to make the
comparison meaningful — see below) therefore carries both `pct_rank_all_time`
and `pct_rank_modern` (`MODERN_WINDOW_YEARS = 30`, trailing from the as-of
date), plus `regime_divergence` (true when they differ by
`REGIME_DIVERGENCE_PTS = 20` or more) and `regime_divergence_pts`. Live
example, found immediately on running this against 2026-10-07's data: the
10-year Treasury was at the **49th** percentile all-time but the **87th**
percentile of the last 30 years — a 38-point divergence. The full-history
number was being pulled down by decades (1970s-80s) with yields regularly
higher than today's; the last 30 years, which is what "normal" actually
feels like to someone who's been investing or paying a mortgage during
that span, has spent most of its time well below today's level. Both
numbers are true; citing only the all-time one would have been the exact
mistake this file exists to prevent.

Series with no real second regime to pool against — `hy_oas`/`ig_oas`
(`short_history`, ~3yr total) and any series whose full history is itself
under roughly 35 years (TIPS real yield and breakeven, 2003+) — get
`pct_rank_modern: null` and `regime_divergence: false` by construction:
there isn't a distinct older era available to disagree with the recent one.

## History v2: "last time", what came next, pace, pairs, cycles (2026-10-09)

Jacob, again, 2026-10-09: the brief still didn't connect today to real
history. A same-day first draft added "first time since" lookups, but an
independent three-lens review (advisor, statistician, historian) found biases
in it. The shipped version, in `history_context.py`, is built around those
findings. Its thresholds are pinned constants at the top of the v2 block and
change only at monthly review:

- **`lookback`** (in each `long_history[key]`). This is the last stretch
  *before* the current run at least this high or low.
  - It is only `gated` for a tail reading: top or bottom fifth on either the
    all-time or the 30-year view.
  - It is flagged `gap_sensitive` when the answer changes across 90-, 180-
    and 365-day grouping gaps. Prose may not use it then.
  - `last_touch` and `last_sustained` (20+ sessions) are reported
    separately. Thresholds are in sessions: `cadence` is inferred from the
    file, and a weekly reading counts as 5 sessions, a monthly one as 21
    (`last_touch.brief`).
  - The current run's own extreme is checked, so a reading below this run's
    peak is never called "the highest since". `record` requires today to be
    the run's extreme; otherwise `run_is_record` says the run's peak is.
  - The current run is gap-grouped, so `current_run_total_sessions`,
    `current_streak_start` and `current_run_unbroken` say whether "since X"
    is literally true.
  - The `track` measures outcomes from each past stretch's **start**. Blips
    (<10 sessions) and regimes (>5 years) are excluded.
  - `most_recent_comparable` is kept for audit only. It lands inside the
    current run ("days ago") and must not be cited.
- **`outcomes_from` / `base_rates`.** These give the S&P 500's next-12-month
  price return and deepest drop, and whether a recession began within 24
  months: `yes`, `no`, `in_progress`, or `pending` when the window ends
  after NBER can date it (USREC's last month minus 12). Each comes with the
  **normal rate** over every month since 1948, 1962 or 1983, leaving out
  months already inside a recession (tracks leave those cases out too), plus
  the S&P's median deepest drop over any 12 months.
- **`rate_shock` / `ytd_rank`** (`state.rate_pace`).
  - `rate_shock` covers 12-month moves at least this big: every past
    episode, measured from its start, against the normal rate. This is the
    honest track record for a rate move, where a level's own track is
    usually 1–2 cases. It reports how many shorter (<10-session) episodes it
    left out, and flags a recession already counted for an earlier shock
    (`same_recession_as_earlier`). The underlying 12-month changes skip any
    date whose base reading falls more than 10 days early (a data hole).
  - `ytd_rank` ranks this year's change through today's date against every
    prior year. It works in bp mode for rates (negative bases kept) and %
    mode for prices. Years with data holes are skipped, and early-January
    years that hadn't traded yet count as unchanged.
- **`pair_bands`** (`state.history_pairs`). This checks pre-registered pairs
  on fixed percentile bands, never today's exact values. It reports the
  joint share against the share expected if the series were unrelated, and
  whether the prior stretch is stable across bands. `never_before_allowed`
  is almost never true, by design.
- **`inversion_cycles`** (`state.curve_cycles`). Runs within 365 days merge
  into one cycle. A cycle is material at 10+ sessions *and* a trough of
  −10bp or deeper. Cycles are classified `followed`, `not_followed`,
  `pending`, `began_in_recession`, or `start_unknown` (already inverted when
  the data begins), against the 36-month normal rate over the series' own
  years. This
  replaces the fragment counts of `summarize_inversions`, which is kept but
  no longer used.
- **`market_context`** covers S&P 500, Nasdaq, WTI and gold. It is
  return-based: move frequency with a tail gate, the last bigger move,
  count this year, distance from record (flagged `stale` when the record is
  over 10 years old), and YTD rank. For the S&P it adds this year's worst
  pullback vs. every full year. The live series overrides the file wherever
  both have a date.
- **`then_vs_now`** is a fixed panel for the lead fact's date vs. today. It
  marks each row similar or different (within 15 percentile points of that
  measure's own history on both the all-time and 30-year views) and shows
  the gap in the measure's own units.
- **`cycle_map`** is Unit 7's aggregate gauges vs. the 2000 and 2007 peaks,
  cycle level only (§8).
- **`lately_vs_history`** is the script-written label, two parts. Lately:
  "unusual lately", "quiet lately", or "no 6-month read" (proxy and
  reference series get a z from their own file via `recent_z`; a monthly
  series can't). History, each lens tested on its own: "historically
  extreme" (both), "high vs. last 30 yrs (87th), about average since 1962
  (49th)" (one), "ordinary historically", or "3-yr record only". A record
  under 30 years (TIPS, breakeven: no separate 30-year view by
  construction) reads "extreme since 2003 (short record)" instead of
  "historically"; TIPS also carries the Cleveland model's reading.
- **`by_decade`** (series with 35+ years) gives each decade's range and the
  share of its readings at or above today's. It is the only source for a
  decade framing in prose.

`scripts/history_digest.py` picks at most four facts a day and writes their
sentences. `scripts/check_history_prose.py` lints the model's prose against
all of the above.

Honesty rules for every block:
- Each "what came next" is a count against a normal rate, measured from the
  start.
- Small counts are called anecdotes.
- Proxies are always named: DFF for SOFR, Baa−10Y for IG OAS, the Cleveland
  model next to TIPS, futures (not spot) for WTI.
