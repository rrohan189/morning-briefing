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

## Phase 1 Tools (phase1_validator.py)

The validator script provides code-based quality gates. Use these during Phase 1 instead of manual judgment:

### Tier Classification (prevents NBC Olympics-type bugs)
```bash
# Check a source's tier before including in GA
python phase1_validator.py tier "NBC Olympics"
python phase1_validator.py tier "Al Jazeera"
python phase1_validator.py tier "Source Name" --url "https://domain.com/article"
```
- Tier 1/2 → ga_eligible: true (OK for GA)
- Tier 3 → ga_eligible: false, FLAGGED (find Tier 1/2 coverage instead)
- Local → ga_eligible: false, BLOCKED (Local section only)
- Unknown → ga_eligible: false (classify manually before including)

### GA Source Tally Gate
```bash
# Run automated tally check on a JSON list of GA items
python phase1_validator.py tally ga_items.json
```
Checks: no source > 3, no Tier 3 in GA, flags all violations.

### Batched From X Searches (4 queries instead of 14)
```bash
# Generate the 4 batched search queries for the current month
python phase1_validator.py fromx "February 2026"
```
Use the output queries directly in WebSearch. This reduces From X handle sweep from ~14 individual searches to 4 batched queries + 1 reference query = **5 total searches**.

### Status ID Validation
```bash
# Validate a candidate post's status ID against reference
python phase1_validator.py statusid "https://x.com/handle/status/123" "https://x.com/OpenAI/status/456"
```

### From X Workflow (mandatory)
1. Run `python phase1_validator.py fromx "[current month year]"` to get batched queries
2. Run the reference query first to find a known-today brand post
3. Run each batch query (4 searches) via WebSearch
4. For each candidate found, run `statusid` to validate delta
5. Apply 48h age gate on top of status ID check
6. Report which handles returned no results (don't silently skip)

## Critical Rules
- All dates must come from Phase 1 code extraction — never fabricated
- Every story must have a real, fetchable URL — no hallucinated articles
- So Whats are written in **second person** ("you", "your team") — never "Rohan should"
- Not every story needs a PayZen angle — big tech/AI news and viral X posts earn inclusion on their own
- Quality over quantity — 4 strong stories beat 7 padded ones
- **GA tier gate is code-enforced** — run `phase1_validator.py tier` for every GA source. If ga_eligible=false, find Tier 1/2 alternative before including. Tier 3 exceptions require explicit justification in Phase 1 JSON.
- **Local section allowlist (code-enforced)** — Local items must match at least one valid category in `_LOCAL_INCLUDE_PATTERNS` (run_pipeline.py): transit/infrastructure, weather/air quality, local government, safety, community events, local healthcare, local economy impact (layoffs/closures/strikes). Real estate listings, opinion pieces, business promotions, sports scores, and advice columns are never valid Local content.
- **Press release filter (code-enforced)** — Articles where the subject company is also the announcer (e.g., "Company X deploys Product Y") are vendor marketing, not news. `_PRESS_RELEASE_SIGNALS` (phase2_generator.py) penalizes scoring when 2+ signals match (e.g., "completes deployment", "enterprise-wide", "launches new", "partners with"). These articles will not reach Tier 1.

## Pre-Flight Checklist (MUST complete before writing ANY HTML)

Do not begin Phase 2 until every box is checked. If a box cannot be checked, fix it first.

**Phase 1 gates:**
- [ ] **Age Verification Table produced** — every candidate (including Local items) has numeric `age_hours` (integer, no tildes or "about"). All with `age_hours > 48` are marked REJECT. Verdicts computed mechanically from the number, not by judgment. If date extraction failed, verdict = REJECT (no "unverified" middle state).
- [ ] **Local items included in Age Verification Table** — Local section is not exempt from freshness rules. Every Local item must have numeric age_hours computed and verified ≤ 48.
- [ ] **No REJECT items remain in candidate list** — all items proceeding to Phase 2 have `age_hours ≤ 48`.
- [ ] **GA Source Tally produced (code-enforced)** — run `python phase1_validator.py tally` on GA items JSON. Gate must return `passed: true`. If any Tier 3 or Local sources flagged, find Tier 1/2 alternatives. Exceptions require explicit justification. No single outlet exceeds 3 items. US count ≤ 4.
- [ ] **From X Status ID table produced** — use batched queries from `python phase1_validator.py fromx`. Every post has a delta computed via `statusid` subcommand. Delta > 500K = REJECT. Every post has a real `x.com/handle/status/[id]` URL. Brand accounts excluded from candidates (use only for reference).
- [ ] **From X handle sweep complete (batched)** — run all 4 batch queries + 1 reference query (5 total WebSearch calls). Report which handles returned no recent results.
- [ ] **URL Verification Log produced** — every URL in every section was fetched. All 404s and fabricated URLs removed.
- [ ] **Healthcare Candidate Log produced** — all 5 sources appear. If <3 pass, confirmed it's a quiet day (not silent drops).
- [ ] **Ticket Watch sweep complete** — searched priority artists (Manchester United, Taylor Swift, Coldplay, Piano Guys) + checked Ticketmaster/major venues for Bay Area onsales. Include 🎟️ item if tickets going on sale within 48 hours.
- [ ] **Phase 1 tables saved to disk** — write `output/phase1-YYYY-MM-DD.json` with all verification tables before proceeding to Phase 2.

**Phase 2 gates:**
- [ ] **Phase 1 output treated as immutable** — no new items added during Phase 2. No additional searching.
- [ ] **Phase 2 Cut Log produced** — every Phase 1 PASS not in the final briefing has a stated reason. Table format required even if 0 cuts.
- [ ] **Reconciliation count matches** — Phase 1 PASS count = final briefing items + Phase 2 Cut Log items.
- [ ] **Cross-reference check** — every URL in the final HTML appears in the Phase 1 URL Verification Log.
- [ ] **Deduplication check** — no story appears in more than one section. Same URL cannot appear twice.
- [ ] **GA pre-publish counts** — US ≤ 4, international ≥ 6, ≥ 4 regions, no source > 3, no Tier 3 or local papers.
- [ ] **Paywalls marked** — STAT News, Modern Healthcare, The Information, WSJ, NYT, FT all get 🔒.
- [ ] **From X not skipped** — if 1-4 posts passed validation, they're included. Only omit if 0 posts passed after full sweep.
- [ ] **Factual integrity** — no statistics, quotes, or specific claims in summaries that don't appear in the source article. When in doubt, use vaguer language.
- [ ] **Weekend acknowledgment** — if Saturday/Sunday and Tier 1 count < 5, add editorial note in header: "Lighter edition today — weekend news cycle."
