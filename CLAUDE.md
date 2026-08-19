# MORNING MACRO BRIEF — System Specification (v1.3)

**Owner:** Jacob Puckett
**Status:** Design ratified in conversation 2026-08-18; final ratification in the repo's first build session.
**Intended home:** New Claude Code repository (`morning-macro/`), separate from the NR repo and the Cowork finances folder.

**Ratified decisions (2026-08-18):**
- Audience: **the brief is for Jacob only.** Voice is personal; no client-distributable framing. The **system design** is shareable — see §12 Portability.
- Primary reading surface: **the full HTML page, on laptop, with morning coffee** — replacing an existing daily ChatGPT market-read habit. The habit is proven; this upgrades it.
- Hosting: GitHub Pages, public repo.
- Quiet-day protocol (§4A) adopted, amended: quiet macro days promote the movers section (§5 Tier 2) rather than thinning the read.
- Claims ledger (§4B) adopted.
- Company & sector movers section (§5 Tier 2) adopted as a daily section — ratified as high priority.
- Positioning vs. financial press: the brief is the **pre-read** — Jacob reads it before WSJ headlines so reporting lands in data context. Press front-page framing is an explicit input to narrative detection (§6.4).
- Political-neutrality protocol (§4D) adopted.
- Monday weekend coverage and event-day claims pattern (§4E) adopted.

---

## 1. Purpose and product definition

A weekday pre-market brief that is **analysis of data the system itself maintains**, not a synthesis of overnight headlines. The narrative is always downstream of a quantitative state file, but it engages the day's news directly — the news supplies the question, the data supplies the answer. The brief has four jobs, in priority order:

1. **Market awareness** — what happened yesterday and where things stand YTD, plus regime awareness: where rates, credit, and liquidity sit versus their own history and whether they confirm risk-asset prices.
2. **Advisor readiness** — Jacob is a practicing financial advisor. The brief should sharpen allocation judgment and prepare him for client conversations: what clients are hearing in the news, and how the data contextualizes it.
3. **AI capex & financing-cycle monitoring** — the macro layer of Jacob's core investing lens, tracked at the cycle level (never the position level — see §8).
4. **Education** — a deliberate CFP→CFA curriculum taught through live data (§7), with every concept translated into client-conversation language.

**Compliance boundary:** the brief is personal research for Jacob's own understanding. It is never client-distributable material; anything shared with clients goes through LPL's review process. The system must not produce content formatted or framed for client distribution.

What this is **not**: a news digest, a trade-idea generator, or an input channel to the NR system.

---

## 2. Architecture

```
morning-macro/
├── CLAUDE.md                  # This spec, adapted as the repo's operating file
├── data/
│   ├── macro_series.csv       # Append-only daily state file (the system of record)
│   ├── claims_ledger.csv      # Open conditional claims + resolution record (§4B)
│   └── calendar_cache.json    # This week's economic calendar, refreshed Mondays
├── briefs/
│   └── YYYY-MM-DD.md          # Every brief, archived (email is a copy, repo is the record)
├── curriculum/
│   ├── syllabus.md            # The 8-unit sequence (§7)
│   └── tracker.md             # What's been taught, when, and when last reinforced
├── templates/
│   └── brief.html             # The design template (see sample-morning-brief.html)
└── scripts/
    ├── compute_state.py       # Deltas, trends, z-scores from macro_series.csv
    └── render_charts.py       # Matplotlib chart generation (SVG/PNG)
```

**Execution:** Cloud scheduled task (claude.ai/code/scheduled), weekdays 6:30am ET.
Rationale: cloud tasks run regardless of machine state; desktop tasks require the app open. Confirm run-limit fit with current plan tier before enabling daily cadence.

**Delivery (two layers, laptop-primary):**
1. **Full brief** — a self-contained HTML file (`briefs/YYYY-MM-DD.html`, charts embedded as inline SVG/base64 PNG, zero external dependencies) built from `templates/brief.html`, committed, and published via GitHub Pages. **This is the product** — the coffee read.
2. **Email (notification layer)** — short: regime pill, regime line, recap strip, and the link. Subject: `Macro Brief — {date} — {regime tag}`. Fifteen-second scan that gets Jacob to the page; it does not attempt to be the brief.

---

## 3. Daily run order (strict)

1. **Pull data** (sources in §5). Every value must carry a timestamp.
2. **Validate:** every Tier 1 series present and dated within the last trading day. Any failure → §4 fail-closed path. No partial analysis.
3. **Append** the day's row to `macro_series.csv`. Never overwrite history.
4. **Compute state** via `compute_state.py`: 1-day delta, 5-day delta, 20-day trend direction, and z-score vs. trailing 120 trading days for every Tier 1 series. Flag any |z| ≥ 1.5.
5. **Reconcile the claims ledger (§4B):** read every open conditional claim; check each against today's computed state; mark resolved claims (confirmed/refuted/expired) and carry the reconciliation into the brief *before* any new narrative is written. Yesterday is answered before today is asserted.
6. **Check calendar:** today's scheduled releases and Fed-speak, with consensus where available.
7. **Render charts** (matplotlib → SVG/PNG): recap sparklines, dashboard sparklines, and the chart of the day per §6.5 selection rules. Weekly: liquidity panel.
8. **Write the brief** (§6), narrative strictly downstream of steps 4–5, into the HTML template (§9) plus a plain-markdown twin for greppability. Log any new conditional claims to the ledger.
9. **Teach** one curriculum unit segment (§7); update `curriculum/tracker.md`.
10. **Commit** with message `brief: YYYY-MM-DD [regime tag]`; GitHub Pages publishes on push.
11. **Email** the notification layer with link to the hosted page.

---

## 4. Fail-closed rules

- If any Tier 1 series is missing or stale: **do not write analysis.** Email a two-line notice — "Data pull incomplete ({series}); no brief generated" — and log the failure in the commit. A brief built on guessed numbers is worse than no brief.
- If Tier 2 or Tier 3 data is partial, the brief runs but states the gap explicitly in that section.
- **Seasoning rule:** until `macro_series.csv` holds 60 trading days, z-scores are labeled "thin history — directional only" and no z-based regime flags are asserted with confidence. The system earns its statistics; it does not fake them.
- No numeric claim appears in a brief unless it exists in the day's data pull or the CSV. If a number would require recall from training data, it is omitted and flagged.

---

## 4A. Quiet-day protocol (the boredom clause)

Genuine regime information arrives a handful of times per month; a system obligated to manufacture daily significance becomes the financial media it was built to escape. Therefore:

- **Every brief is a complete read** — regime line, recap strip, story section, dashboard, calendar, concept of the day all run daily. The coffee ritual is never shorted.
- **Significance claims are gated.** On days with no |z| ≥ 1.5 flag, no claims-ledger resolution, and no major calendar event, the story section states the circulating narrative and then says plainly: *the macro data shows nothing outside normal ranges* — with the ranges shown. That sentence is analysis, not a cop-out, and it is often the most client-useful output the system produces ("markets are calm, and here is the evidence").
- **Calm macro days change the lens, not the length.** The movers section (§5 Tier 2) is promoted to lead the story, and the chart of the day may be a single-stock or sector chart. Something is always moving at the company level; quiet macro mornings become micro mornings.
- The regime tag vocabulary includes a `calm` state. Quiet days are labeled as such in the subject line; over time, the rarity of loud days is what makes them credible.
- The brief may never escalate language to compensate for a quiet tape. "Notable," "significant," and "sharp" are earned by the computed state, not the prose.

## 4B. Claims ledger (continuity and accountability)

Each scheduled run is a fresh session; without a mechanism, the brief is 250 analysts a year thinking once each. The claims ledger makes it one analyst thinking across days.

- Every **conditional claim** in a brief ("if IG follows HY, the divergence thesis strengthens") is logged: date, claim, test condition, resolution deadline (default 5 trading days).
- Every morning's run **reconciles open claims first** (run order step 5). Resolutions appear in the brief: confirmed, refuted, or expired-unresolved. Refuted claims are stated as plainly as confirmed ones.
- Quarterly, the brief publishes a one-paragraph **track-record note**: how many claims resolved each way. This audits the system's interpretive quality — including the model's.

## 4C. Epistemics rules (numbers were constrained; causation is too)

- **Mechanical facts** ("the 10Y rose 6bp") are stated plainly.
- **Causal attributions** ("stocks fell on rate fears") are the archetypal unfalsifiable sentence in financial writing. The brief may offer causal readings only when explicitly marked as hypothesis *with a stated test* — which then enters the claims ledger. Untestable causal narration is prohibited.
- The author is an LLM: strong at computing, retrieving, structuring, and pattern-matching; incapable of forecasting; prone to prose that sounds more confident than its evidence. The brief is a disciplined junior analyst whose arithmetic is script-verified and whose narratives Jacob interrogates. The claims ledger is partly a check on the model itself.
- All tables and chart values are **script-generated from the data files**; the model writes prose only. Any number appearing in prose is cross-checked against computed state before send.

## 4D. Political-neutrality protocol

"Less biased than CNBC/WSJ" is a method, not a promise:

- **Data-first is the structural defense.** Most bias in financial media enters through narrative selection and causal attribution; both are already gated by §4C and the story-section test requirement. The state file has no politics.
- **Policy as mechanics only.** Fiscal, monetary, trade, and regulatory news is covered strictly as transmission — effects on rates, earnings, margins, sectors, credit — never as advocacy for or against the policy. Tariffs are a pass-through and margin question here, not a trade-philosophy debate.
- **Contested claims are labeled contested.** When a circulating narrative is politically live (e.g., deficit–yield attribution), the brief names it as contested, presents what data would discriminate between readings, logs a conditional claim where possible, and adopts no side.
- **Attribution over adoption.** Press framings are reported as framings ("the Journal is leading with X"), never absorbed into the brief's own voice untested.
- **The author's bias is acknowledged.** The model has training biases; no neutrality is claimed for it. The mitigation is structural: attributed, falsifiable, or flagged claims plus the ledger's resolution record. Jacob remains the arbiter.

## 4E. Calendar edges

- **Monday edition** covers "since Friday's close": weekend news flow, Sunday-evening futures, geopolitical developments, and any weekend policy announcements — tested against the state file like any narrative. Monday should be among the strongest editions, not the thinnest.
- **Event days (CPI, FOMC, payrolls, major earnings):** the 6:30am brief runs *before* the event. It does not predict; it frames — stating what to watch and what each plausible outcome would imply, each logged as a conditional claim (§4B). The next morning's reconciliation grades those claims against the actual print. Event eves set the test; event aftermaths answer it. No same-day supplemental editions in v1.
- **Market holidays:** no brief, or a one-line "markets closed" notice; decided at build.

---

## 5. Data tiers and sources

### Tier 1 — Rates / Credit / Liquidity (the daily spine)
| Series | Source | Cadence |
|---|---|---|
| UST 3m, 2y, 10y, 30y; 2s10s, 3m10y | FMP (treasury endpoint) | Daily |
| 10y TIPS real yield; 10y breakeven (derived) | FRED via web fetch (DFII10) | Daily |
| HY OAS, IG OAS | FRED via web fetch (BAMLH0A0HYM2, BAMLC0A0CM) | Daily (1-day lag; label as such) |
| DXY | FMP (forex) | Daily |
| Fed balance sheet, ON RRP, TGA | FRED / NY Fed via web fetch | Weekly (Thu H.4.1); carry-forward with date label |
| SOFR | NY Fed via web fetch | Daily |

### Tier 2 — Company & sector movers (daily) [PERSONAL-PRIORITY SECTION]
Micro as macro sensor: large single-name and sector moves are treated as leading evidence about the macro picture (consumer read-throughs from retail guidance, credit read-throughs from bank provisioning, capex read-throughs from semis orders), not as a stock-watching digest.

- **Selection rules (mechanical, to prevent drift into stock-tipping):** S&P 500 constituents with |1D| ≥ 4%; top-50 mega-caps with |1D| ≥ 2.5%; any GICS sector ETF diverging ≥ 1.5pp from SPX on the day. Earnings/guidance reactions prioritized over drift. **Cap: 3 names + 1 sector note.** Source: FMP (gainers/losers, sector performance); Bigdata.com for the reported reason.
- **Entry format (three parts, all mandatory):** (1) the fact — script-verified move; (2) the stated reason — attributed to reporting per §4C ("the company cited X"), never asserted as cause; (3) the **read-through** — what this implies for the macro picture, or an explicit "idiosyncratic — no read-through."
- **NR-held names:** factual moves and read-throughs are reported normally — omitting them would gut the section — but position-level commentary is prohibited (§8); NR-relevant read-throughs carry the routing flag.
- **Quiet-macro promotion:** on §4A calm days, this section leads the story, and the chart of the day may be a single-stock or sector chart (annotated with the read-through, not price targets).

### Tier 3 — AI capex & financing cycle (daily touch, weekly depth)
- Daily: SMH relative strength vs. SPY; any credit-market news on hyperscaler/neocloud issuance, vendor financing structures, datacenter debt (Bigdata.com search — this is its comparative advantage over generic web search).
- Weekly (Friday brief): a structured half-page on cycle health — issuance volume trend, spread behavior of AI-adjacent credits, capex guidance changes, financing-structure novelty (the Lucent-pattern watch). This section is **cycle-level only** (§8).

### Tier 4 — Cross-asset scan (compact table)
- Equal-weight vs. cap-weight SPX spread (breadth proxy); copper; EUR/USD, USD/JPY; anything in the recap strip crossing a flag threshold gets a line here. Source: FMP quotes. Five lines of commentary maximum.

---

## 6. Brief format (target: readable in 7 minutes)

1. **Regime line** (1 sentence): the single most decision-relevant fact of the morning.
2. **Recap strip** — fixed-position table: yesterday's move and YTD for S&P 500, Nasdaq, Russell 2000, UST 10Y, HY OAS, DXY, WTI, gold. Includes one permanent line: **S&P 500 distance from all-time high** (pure market data; its private significance to Jacob's standing triggers lives outside this repo). Reference material, same place every day, ten seconds.
3. **Claims reconciliation** — resolutions of prior conditional claims (§4B), stated plainly whichever way they resolved. Omitted only when no claims are open or due.
4. **The story** — what is driving markets right now. Narrative detection explicitly includes **what the major financial press is leading with this morning** (headlines via Bigdata.com — headline-level access is sufficient; the headline *is* the narrative). One or two paragraphs stating the prevailing narrative with attribution, then the pivot: does the state file confirm it, complicate it, or refute it? The design intent: Jacob reads this before opening the WSJ, so the Journal's framing lands in data context rather than setting it. On quiet days, §4A governs; politically live narratives follow §4D. The brief never repeats a narrative it hasn't tested.
5. **Tier 1 dashboard** — rates/credit/liquidity table with deltas and z-flags, then interpretation. Every number in the interpretation must exist in the table or the day's pull.
6. **Movers** (§5 Tier 2) — up to 3 names + 1 sector note, each with fact / stated reason / read-through. On calm macro days this section moves up and leads.
7. **Chart of the day** — one featured, annotated chart, editorially selected each morning by these rules, in order: (a) the series with the largest |z| move; (b) the mover with the strongest read-through; (c) the series behind the day's dominant news story; (d) the series most relevant to today's calendar event. Must map to `macro_series.csv` or a fetchable series logged that day. Rotation is the point — the chart follows the story. A short "why this chart today" line is mandatory.
8. **Tier 3** — AI capex/financing-cycle note; expanded Friday section.
9. **Today's calendar** — releases, consensus, why each matters *to the current regime*.
10. **Concept of the day** (§7) — ~200 words applied to a number in that morning's brief, ending with the **client translation**: one sentence expressing the concept as Jacob would say it across the table from a client.
11. **Client lens** — 2–3 items: topics clients are likely to raise this week given the news cycle — individual-stock questions ("did you see what happened to {name}") are expected staples here, answered from the movers read-throughs. Conversation prep for Jacob, not scripting, never client-distributable copy.
12. **Flags** — threshold crossings; any "route to NR commentary process" tag (§8).

Prose over bullets throughout the interpretive sections. Tables for data only.

---

## 7. Educational curriculum — CFP → CFA macro bridge

**Premise:** CFP training builds planning architecture, not market mechanics. The gap is the CFA fixed-income/economics layer: how prices form, what spreads mean, how liquidity transmits. Each unit is taught in ~200-word daily segments across roughly two weeks, always anchored to that morning's live data, and **every segment ends with a client translation** — the concept rendered in one sentence of plain client-conversation language. The endpoint of the whole curriculum is dual: read the market like an analyst, explain it like an advisor.

| Unit | Subject | Endpoint capability |
|---|---|---|
| 1 | Yield curve mechanics — duration, convexity, what curve shape prices (path of policy + term premium) | Read a curve move as an expectations statement |
| 2 | Real vs. nominal decomposition — TIPS, breakevens, term premium | Decompose any 10y move into growth/inflation/premium components |
| 3 | Credit spreads — OAS, default vs. liquidity premium, spreads as the risk barometer | Use HY OAS as a leading risk signal, know its false-positive modes |
| 4 | Liquidity plumbing — reserves, RRP, TGA, QT mechanics | Trace a Treasury refunding announcement to equity-market liquidity |
| 5 | The dollar cycle — carry, rate differentials, global transmission | Explain why DXY strength tightens conditions everywhere |
| 6 | Positioning & sentiment vs. fundamentals — flows, breadth, divergence | Distinguish "priced in" from "improving" |
| 7 | Financing cycles & reflexivity — Minsky sequence, vendor financing, the Lucent reference class | Locate the AI capex cycle on a financing-cycle map |
| 8 | Cross-asset confirmation — when bonds, credit, FX, and equities disagree, who to believe | Build a hierarchy-of-evidence habit |

**Reinforcement rule:** `tracker.md` logs each concept's last appearance. When the tape makes an old concept relevant (e.g., a 2σ HY OAS move after Unit 3 is complete), the brief reactivates it in the interpretation rather than teaching something new — application beats coverage.

Unit 7 is sequenced late deliberately: it lands after the reader has spread and liquidity mechanics, which is what separates a real financing-cycle judgment from pattern-matching to 1999.

---

## 8. Governance wall — the NR interface

Modeled on the NR system's own interface doc, with the direction reversed:

- The brief **never** makes recommendations about NR positions, sizing, membership, or kill criteria. Not implicitly, not "for context."
- The brief **never** reproduces NR analytics or references repo-internal state.
- When Tier 2 (movers) or Tier 3 monitoring surfaces something plausibly relevant to an NR thesis or kill criterion, the brief appends a single flag line: `→ Route to NR commentary process: {one-sentence description}`. Jacob decides whether it enters the NR repo through its prescribed channel. The brief's job ends at the flag.
- **NR-held names in the movers section:** factual moves, stated reasons, and macro read-throughs are reported the same as any other company — the section would be useless otherwise. What is prohibited is position-level commentary: nothing about weights, adds, trims, kill criteria, or whether the move is "good or bad for the position."
- Rationale: additive evidence enters the NR system only through its commentary directory. A daily email that editorializes about held names would erode the governance discipline that makes the NR system work. The wall is a feature.

The same wall applies to the household finance system: the brief does not comment on household allocation, the 401(k), or any account.

---

## 9. Presentation layer

- **Design system:** regime color as the signature element — one accent color per day (`confirming #2E7D5B`, `diverging #B07C1F`, `tightening #46586B`, `stress #A63D2F`) threads through the masthead band, flagged table rows, chart annotations, and the email subject-line tag. Over time the color communicates posture before the text does.
- **Typography:** serif display (Fraunces) for masthead and concept-card headlines only; quiet sans (Source Sans 3) for prose; monospace (IBM Plex Mono) for every numeric value so columns align. Email version falls back to Georgia / system sans / Menlo.
- **Charts:** two classes. (1) The **recap strip and dashboard sparklines** are fixed-position, every day — reference furniture. (2) The **chart of the day** rotates, selected by the editorial rules in §6.5 to follow the actual story — annotated, with a mandatory "why this chart today" line. Weekly liquidity panel on Fridays.
- **Email constraint is a design constraint:** inline CSS only, no JS, static images, ≤720px single column. The full HTML page inherits the same layout so the two renderings feel like one product.
- **Chart discipline:** no chart appears unless it maps to a series in `macro_series.csv` or a series fetched and logged that day. Decorative imagery is excluded; the aesthetic budget goes to typography, spacing, and the regime system.
- Template reference: `templates/brief.html` (built from the approved sample).

## 10. System governance (the meta-layer)

Jacob's self-identified discipline risk is building systems rather than running them. This system therefore governs itself:

- **Design freeze:** after v1 ships, no template, format, or structural changes for 30 days. Improvements are logged to a `backlog.md` and batched into a monthly review — never made daily.
- **Kill criteria for the system itself:** if the brief goes unread three days running in two consecutive weeks, or if at the 90-day review Jacob cannot name one client conversation or one allocation judgment it sharpened, the system is redesigned or retired at that review — not silently abandoned. (Base rate is favorable: the daily reading habit predates this system.) A softer 90-day success test: does the WSJ now read differently — headlines landing in context the brief already supplied?
- **Attribution & licensing:** footer credits FRED and data providers per their terms; the Pages site carries `noindex` to stay out of search. If provider terms ever conflict with public hosting, fallback is the HTML-attachment delivery.
- **Regime-tag vocabulary:** `calm`, `risk-on/confirming`, `risk-on/diverging`, `tightening`, `stress` — resolved; amendable only at monthly review.

## 12. Portability principle (shareable system, personal brief)

The brief is Jacob's; the **system design** is a shareable artifact for other advisors.

- **Separation of concerns:** personal couplings are confined to marked sections — the NR interface (§8), the S&P drawdown line's private significance, the curriculum position in `tracker.md`, and the client-lens tuning. Everything else (architecture, run order, fail-closed rules, quiet-day protocol, claims ledger, epistemics rules, movers selection rules, template, curriculum syllabus) is the generic engine.
- **Export command:** at any time, Claude Code can be asked to *"generate the shareable spec"* → produces `SHARE_SPEC.md`: this document with personal sections stripped and replaced by `[configure for your practice]` placeholders, plus the template and a setup guide. A receiving advisor builds their own repo, their own data file, their own curriculum position.
- **What is never shared:** the brief itself, the claims ledger, the data files, anything referencing Jacob's holdings, clients, household, or NR system.
- **Compliance note:** sharing methodology peer-to-peer differs from distributing content, but if the shared spec becomes firm training material or a Christian Planning asset, it goes through LPL review like any firm artifact.

## 13. Open items — resolved at the first build session (2026-08-19)

1. ~~Cadence~~ **Resolved:** weekdays 6:30am ET ratified by Jacob 2026-08-19. Plan-tier run-limit fit is verified when the scheduled task is actually created (deferred until a manual brief is approved).
2. ~~FMP treasury/forex coverage~~ **Resolved:** verified against live endpoints 2026-08-18/19 — see §14 source map. FMP treasury works but lags ~2 trading days; FRED substituted as primary. FMP forex (DXY) is plan-gated; Yahoo substituted.
3. ~~Gmail connector~~ **Resolved (design):** email layer stays in v1, ratified 2026-08-19. Connector authorization inside the scheduled-task context is verified at task-creation time; if unavailable, fail open to page-only delivery and say so.
4. ~~Koyfin~~ **Resolved:** no Koyfin subscription exists — the spec line was an error (Jacob, 2026-08-19). Full automation; no manual paste channel.
5. ~~Curriculum~~ **Resolved:** 8-unit sequence ratified as written 2026-08-19. Tracker starts at Unit 1, segment 1.
6. ~~Regime-tag vocabulary~~ **Resolved** — see §10.
7. ~~Hosting decision~~ **Resolved:** GitHub Pages, public repo — approved by Jacob 2026-08-18. Confirmed constraint: brief contains only market data and curriculum; no household, client, or NR-position content ever enters the repo.
8. ~~Template revision~~ **Resolved:** `sample-morning-brief.html` was not present in the project folder at build time, so `templates/brief.html` was built fresh from the §9 design system in the v1.3 §6 section order (flagged to Jacob 2026-08-19; reconstruction, not redesign).
9. ~~Movers endpoints & mega-cap universe~~ **Resolved:** verified 2026-08-18/19 — see §14. Mega-cap universe: static top-50 list (`data/megacap50.json`), refreshed quarterly by market cap; chosen because per-symbol market-cap ranking is plan-gated daily but fine quarterly. Amendable at monthly review.

---

## 14. Build record & verified source map (2026-08-19)

Every endpoint below was exercised live on 2026-08-18/19; nothing here is assumed.

### FMP (via MCP connector) — current plan tier
| Works | Endpoint | Use |
|---|---|---|
| ✅ | `economics: treasury-rates` | cross-check only (lags ~2 trading days behind FRED) |
| ✅ | `indexes: index-quote` (^GSPC, ^RUT, …) | intraday cross-check |
| ✅ | `quote: quote`, `quote-change` (single symbol) | mover detail: 1D/YTD per name |
| ✅ | `marketPerformance: biggest-gainers / biggest-losers / most-active / sector-performance-snapshot` | movers candidate screens + sector note |
| ✅ | `commodity: commodities-quote GCUSD` | gold cross-check (per-symbol gating: CLUSD/DXUSD denied) |
| ❌ | `forex` (all), `quote: batch-quote(-short)`, `indexes: sp-500` constituents, `economics: economics-calendar` | plan-gated — substitutes below |

### Substitutes (all script-fetched by `scripts/pull_data.py`, curl-based)
| Series | Source | Notes |
|---|---|---|
| UST 3m/2y/10y/30y | FRED DGS3MO/DGS2/DGS10/DGS30 | H.15; at 6:30am the freshest observation is one trading day behind the row date (labeled) |
| 10y TIPS real / breakeven | FRED DFII10; breakeven derived = DGS10 − DFII10 (T10YIE cross-check in raw file) | |
| HY / IG OAS | FRED BAMLH0A0HYM2 / BAMLC0A0CM | 1-day publication lag, labeled per §5 |
| SOFR | FRED SOFR (NY Fed markets API fallback) | published ~8am ET next day; lag ≤ 2 labeled |
| Fed BS / ON RRP / TGA | FRED WALCL / RRPONTSYD / WTREGEN | WALCL & WTREGEN weekly carry-forward, RRP daily |
| DXY | Yahoo `DX-Y.NYB` | FMP forex gated |
| WTI / gold / copper | Yahoo `CL=F` / `GC=F` / `HG=F` | FMP commodity per-symbol gated |
| SPX/NDX/RUT, SPY/RSP/SMH | Yahoo v8 chart | FMP index-quote as cross-check |
| S&P 500 constituents | Wikipedia list page (parsed, cached in `data/sp500_constituents.json`) | FMP constituents gated; refresh weekly |
| Broad movers scan | Yahoo v8 `spark` batch endpoint (chunks of ~20) over the constituents list | FMP batch quotes gated |
| Economic calendar | ForexFactory weekly JSON (`ff_calendar_thisweek.json`) with impact + consensus | FMP economics-calendar gated; refresh Mondays into `data/calendar_cache.json` |

Fetcher quirks (encoded in `pull_data.py`, do not "fix" without re-verifying): FRED serves curl's default UA and rejects spoofed browser UAs (HTTP/2 INTERNAL_ERROR) and stalls urllib; Yahoo requires a browser UA. WebFetch-class tools get 403 from FRED and NY Fed — scripts use curl.

### Operational notes
- **Seeded history:** `macro_series.csv` was seeded 2026-08-19 with genuine daily observations from 2025-12-01 (FRED/Yahoo history), so the 120-day z-window and YTD baselines are real from day one and the §4 seasoning rule is satisfied honestly (weekly series like WALCL/TGA remain "thin" until they accumulate 60 observations, and are so labeled). Rows are append-only from here.
- **Row semantics:** one row per market close date; each series' value sits on its observation date. Late-publishing series (OAS, SOFR) fill their empty cells on the next run — a fill, never an overwrite. Freshness contract per series lives in `TIER1_MAX_LAG`.
- **SPX ATH line:** closing-basis all-time high tracked in `data/spx_ath.json`, seeded from 10y of history.
- **Run pipeline:** `pull_data.py --daily` (fail-closed exit 2 stops everything) → `compute_state.py` → `render_charts.py sparklines` / `chart-of-day` (+ `liquidity` on Fridays) → brief written from `templates/brief.html` + markdown twin → commit. FMP/Bigdata content (movers reasons, headlines) is pulled by the session via MCP at brief-build time and recorded in `data/raw/`.
- **Calm-tag color** `#64707D` is provisional (the §9 palette defined only the four loud regimes) — in `backlog.md` for ratification at the 30-day review.

---

*Design principles inherited from the NR system: repo as system of record, fail-closed on missing data, narrative downstream of computed state, closed governance channels, and no statistic asserted before its history exists.*
