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
| `dgs30.csv` | DGS30 | 1977-02-15+ | 30-year Treasury (gap 2002-02 to 2006-02: Treasury stopped issuing 30Y bonds over that window) |
| `dfii10.csv` | DFII10 | 2003-01-02+ | 10Y TIPS real yield — TIPS didn't exist before this |
| `t10yie.csv` | T10YIE | 2003-01-02+ | 10Y breakeven inflation — same constraint |
| `dff.csv` | DFF | 1954-07-01+ | Effective fed funds rate — **SOFR's long-run proxy**; SOFR itself only exists from 2018 |
| `dbaa.csv` | DBAA | 1986-01-02+ | Moody's Baa (lowest investment-grade rung) corporate bond yield, daily |
| `daaa.csv` | DAAA | 1983-01-03+ | Moody's Aaa corporate bond yield, daily |
| `usrec.csv` | USREC | 1945-01-01+ | NBER recession indicator, monthly 0/1 — recession date ranges in `episodes.json` are derived from this, not hand-typed |
| `baml_hy_oas.csv` | BAMLH0A0HYM2 | **2023-10-09+ only** | See constraint below |
| `baml_ig_oas.csv` | BAMLC0A0CM | **2023-10-09+ only** | Same constraint |

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
history file is built for them. DXY isn't covered yet either (no clean
decades-long daily series confirmed reachable from this sandbox); flagged
as a gap, not silently faked.

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
recession, capped at 36 months). The dashboard table's "Hist. %ile" column
and any brief prose citing long-run context must come from this block —
never from memory.
