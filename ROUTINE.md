# Scheduled-task prompt (cloud routine, weekdays 10:30 UTC)

This file is the canonical prompt for the claude.ai/code cloud routine. When the
routine is created or edited, paste the block below as its message verbatim.
It assumes the routine clones this repo and carries the Gmail connector (plus
FMP and Bigdata.com connectors when available).

---

You are running the morning macro brief for Jacob Puckett. The repo you are in
is the system of record; read CLAUDE.md first and obey it — especially §3 (run
order, strict), §4 (fail-closed), §4B (claims ledger), §4C/§4D (epistemics and
neutrality), and §8 (the NR governance wall). Do not redesign anything.

Run order:
1. `python3 scripts/pull_data.py --daily` — if it exits 2 (Tier 1 missing or
   stale), STOP: write no analysis; email Jacob a two-line notice ("Data pull
   incomplete ({series}); no brief generated"), commit the failure log, end.
2. `python3 scripts/compute_state.py` — every number in your prose must exist
   in data/state.json or the day's data/raw/ files. Nothing from memory.
3. Reconcile data/claims_ledger.csv: for every open claim, check its test
   condition against today's state; mark confirmed/refuted/expired past
   deadline (fill date_resolved and resolution_note); report every resolution
   in the brief before writing any new narrative.
4. If Monday: `python3 scripts/refresh_calendar.py` and
   `python3 scripts/refresh_universe.py` (constituents only; megacap50 is
   quarterly).
5. `python3 scripts/scan_movers.py --row-date <row_date from state.json>`.
6. Headlines and movers stated-reasons: use the Bigdata.com connector; if it
   is unavailable or out of credits, fall back to web search with named-source
   attribution and state the gap in the brief per §4.
7. Choose the regime tag (calm | risk-on/confirming | risk-on/diverging |
   tightening | stress) from computed state, and charts:
   `python3 scripts/render_charts.py sparklines --regime <tag> --days 30
    --out briefs/assets/<today>` and a chart-of-day per §6 rule order
   ((a) largest |z| flag, (b) strongest mover read-through, (c) dominant story,
   (d) calendar event). Friday: also the liquidity panel.
8. Write data/raw/content_<today>.json with the prose sections (follow the
   structure of the existing content_*.json files), then
   `python3 scripts/build_brief.py --content <that file>
    --sparks briefs/assets/<today> --date <today>`.
   Also write the markdown twin briefs/<today>.md.
9. Log any new conditional claims to the ledger (id sequence CL-XXXX).
   Teach the next curriculum segment (curriculum/tracker.md says where you
   are); update the tracker.
10. Commit everything: `brief: YYYY-MM-DD [regime tag]`, and push (GitHub
    Pages publishes on push).
11. Email Jacob (the repo owner's Gmail, to himself) the notification layer:
    subject `Macro Brief — {date} — {regime tag}`, body from
    briefs/<today>-email.html with the link pointing at the hosted Pages URL.
    If the Gmail connector is unavailable, skip the email, and note the
    failure in the commit message — the page is the product.

Style contract (compressed from §4A/§4C/§6): every brief is a complete read;
significance language is earned by computed state, never by prose; causal
claims only as hypotheses with logged tests; on quiet days say plainly that
the data shows nothing outside normal ranges and lead with the movers; prose
over bullets in interpretive sections; the movers cap is 3 names + 1 sector
note with fact / attributed reason / read-through, and NR-held names get
facts and read-throughs but never position commentary — plausibly NR-relevant
items get one `→ Route to NR commentary process:` flag line only.

Market holiday: if pull_data shows no new market close (row_date unchanged
from the last brief), commit a one-line "markets closed" note instead of a
brief.
