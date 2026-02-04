# Morning Intelligence Briefing

This project generates a daily email newsletter called "The Morning Intelligence."

## Permissions
- You have blanket permission to search the web and fetch any URL during briefing generation. Do not ask for confirmation before searching or fetching — just do it.
- You may fetch from any news source, blog, X/Twitter, RSS feed, press room, or aggregator listed in the spec's source list (or any other relevant source you discover).
- If a fetch fails (paywall, 403, timeout), skip that article and move on. Do not stop to ask.

## Key Files
- `morning-briefing-spec.md` — Complete spec including context, format, selection process, anti-patterns, source list, and quality checklist. **Read this first.**
- `morning-briefing-template.html` — Reference HTML template with exact styling. Match the typography, color palette, spacing, and component structure precisely.

## How to Generate

The briefing must be generated in **two phases** (see spec for full details):

### Phase 1: Gather & Validate (code, not generation)
Write and run a script that:
1. Searches monitored sources for candidate articles (web search, X/Twitter, RSS, Techmeme, etc.)
2. Fetches each article URL and extracts the **real publication date** from HTML meta tags or JSON-LD
3. Rejects anything older than 48 hours — no exceptions
4. Rejects anything where the date cannot be verified — no "unverified" status, only PASS or REJECT
5. Outputs a validated JSON list with verified dates, URLs, sources, and reading times

**MANDATORY CHECKPOINT:** Present the validated candidate list (with dates and verification methods) before proceeding to Phase 2. Do not generate any briefing content until this step is complete.

**The LLM must never generate or guess a publication date.** Dates come from Phase 1 only.

### Phase 2: Generate the Briefing (LLM generation)
Using only validated candidates from Phase 1:
1. Rank by signal strength and select top stories
2. Generate summaries, So Whats, From X, General Awareness, and Today in 30 Seconds
3. Render as HTML email using the reference template
4. Use `verified_date` from Phase 1 in every meta line — never override

## Quick Command
To generate today's briefing: `generate today's morning briefing`

## Automated Daily Run (6 AM Pacific)
When running unattended via Task Scheduler (`--dangerously-skip-permissions`):
1. Run Phase 1 with self-review checkpoint (no human present — scan for >48hr articles, apply all hard gates yourself)
2. Run Phase 2 to generate the HTML briefing
3. Save to `output/briefing-YYYY-MM-DD.html`
4. Run `python send-briefing.py output/briefing-YYYY-MM-DD.html` to email it (this auto-inlines CSS for Gmail desktop rendering)
5. Log success or failure

Gmail credentials are in `.env` — never commit this file.
Dependencies: `pip install python-dotenv premailer`

## Critical Rules
- All dates must come from Phase 1 code extraction — never fabricated
- Every story must have a real, fetchable URL — no hallucinated articles
- So Whats are written in **second person** ("you", "your team") — never "Rohan should"
- Not every story needs a PayZen angle — big tech/AI news and viral X posts earn inclusion on their own
- Quality over quantity — 4 strong stories beat 7 padded ones

## Pre-Flight Checklist (MUST complete before writing ANY HTML)

Do not begin Phase 2 until every box is checked. If a box cannot be checked, fix it first.

**Phase 1 gates:**
- [ ] **Age Verification Table produced** — every candidate has numeric `age_hours` (integer, no tildes or "about"). All with `age_hours > 48` are marked REJECT. Verdicts computed mechanically from the number, not by judgment. If date extraction failed, verdict = REJECT (no "unverified" middle state).
- [ ] **No REJECT items remain in candidate list** — all items proceeding to Phase 2 have `age_hours ≤ 48`.
- [ ] **GA Source Tally produced** — no single outlet exceeds 3 items. Tier check included — no Tier 3 (Balkan Insight, Just Security, etc.) or local papers for national stories. US count ≤ 4.
- [ ] **From X Status ID table produced** — every post has a delta computed against a known-today reference. Delta > 500K = REJECT. Every post has a real `x.com/handle/status/[id]` URL. Brand accounts excluded from candidates (use only for reference).
- [ ] **From X handle sweep complete** — all 10+ handles searched, report which returned no recent results.
- [ ] **URL Verification Log produced** — every URL in every section was fetched. All 404s and fabricated URLs removed.
- [ ] **Healthcare Candidate Log produced** — all 5 sources appear. If <3 pass, confirmed it's a quiet day (not silent drops).

**Phase 2 gates:**
- [ ] **Phase 1 output treated as immutable** — no new items added during Phase 2. No additional searching.
- [ ] **Phase 2 Cut Log produced** — every Phase 1 PASS not in the final briefing has a stated reason. Table format required even if 0 cuts.
- [ ] **Reconciliation count matches** — Phase 1 PASS count = final briefing items + Phase 2 Cut Log items.
- [ ] **Cross-reference check** — every URL in the final HTML appears in the Phase 1 URL Verification Log.
- [ ] **Deduplication check** — no story appears in more than one section. Same URL cannot appear twice.
- [ ] **GA pre-publish counts** — US ≤ 4, international ≥ 6, ≥ 4 regions, no source > 3, no Tier 3 or local papers.
- [ ] **Paywalls marked** — STAT News, Modern Healthcare, The Information, WSJ, NYT, FT all get 🔒.
- [ ] **From X not skipped** — if 1-4 posts passed validation, they're included. Only omit if 0 posts passed after full sweep.
