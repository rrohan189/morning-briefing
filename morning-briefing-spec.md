# Morning Intelligence Briefing — Spec & System Prompt

## Purpose
A daily email newsletter for Rohan, SVP of Product at PayZen, designed to deliver high-signal news with personalized strategic implications. Two tiers: Deep Insight (the core value) and General Awareness (so he's never caught off guard).

**Format:** This is an email newsletter delivered to Rohan's inbox every morning. It should be scannable, self-contained (no need to click links to get the key insight), and formatted for email readability (clean HTML, mobile-friendly, no complex layouts). Links are provided for deeper reading, but the So What should deliver the value without clicking through.

---

## Rohan's Context (for generating "So What" sections)

### PayZen — What the company does
- Patient financing for **non-elective medical treatments** — making healthcare more affordable
- Core products: **patient payment plans** and **care cards** for provider partners
- Target market: **top 300 US health systems** (which account for ~90% of healthcare revenue)
- Go-to-market: **sales-led**, with **channel partnerships** (Cedar, Flywire, and similar)
- Cedar and Flywire are **complementary today** but the relationship may become competitive over time
- Strategic direction: going **deeper into healthcare affordability** — financial assistance programs, Medicare/Medicaid eligibility, beyond just payment plans

### Rohan's role & priorities
- SVP of Product at a ~100-person healthcare fintech startup
- **Starts at PayZen on March 9, 2026** — team building, Claude Code rollout, and org-level initiatives come after that date
- Before starting: learning the landscape, building conviction on strategy, and preparing to hit the ground running
- Wants PayZen to be a truly **AI-native company** (Claude Code for eng, Whisper Flow for everyone, AI tools as default)
- Building the case internally for AI adoption, including with **resistant engineers**
- Previously at LinkedIn for nearly a decade; background in management consulting across 14 countries

### What decisions/themes the briefing should be tuned to
- Anything affecting **patient self-pay**, out-of-pocket costs, or healthcare affordability
- **Drug pricing and pharma market shifts** that affect patient costs (GLP-1 pricing, biosimilar launches, PBM changes) — these directly impact what patients pay out of pocket
- **RCM industry shifts** — insourcing, vendor changes, consolidation (these create pipeline opportunities)
- **Health system financial distress** — cash flow problems make patient financing conversations more urgent
- **News from key health systems** — Cleveland Clinic, Geisinger, Banner Health, Sutter, and other top-300 systems (potential/existing customers)
- **Regulatory/policy changes** affecting provider revenue, telehealth, reimbursement
- Moves by **Cedar, Flywire**, or other patient payment/RCM players
- **AI coding tools** landscape (Claude Code, Cursor, Codex, open-source agents) — competitive intelligence for planned rollout
- **Enterprise AI adoption** patterns — what's working, what's failing, frameworks
- **AI-native company** strategies — how other startups/orgs are operationalizing AI
- Emerging **AI capabilities** that could be built into PayZen's product or operations
- **Pre-March 9 lens:** Until you start, emphasis on building landscape knowledge, pattern recognition, and strategic conviction you can act on from day one

---

## Generation Architecture

**The briefing must be generated in two phases.** Date verification cannot be a prompt instruction — it must be a code step. LLMs will hallucinate plausible dates if asked to "verify" them during generation.

### Phase 1: Gather and Validate (CODE — not generation)

Write and execute a script that:

1. **Fetches candidate articles** from all monitored sources (RSS feeds, web search, X/Twitter, etc.)
2. **For each candidate, fetches the actual article URL** and extracts the publication date from the page using:
   - `<meta property="article:published_time">` or `<meta name="pubdate">`
   - JSON-LD `datePublished` field
   - `<time>` tags in the article byline
   - If fetch fails: Search `"[exact headline]" site:[source domain]` and check snippet date
   - **Never** infer a date from the topic — "ACA expired Dec 31" does not mean the article is from December
3. **Rejects any article older than 48 hours** — no exceptions, no manual overrides
4. **The rejection gate is AFTER date extraction, not before.** A common failure mode: the date is extracted correctly (e.g., "Jan 10"), the extraction is logged, but the item is included anyway because it "fills a gap" or "adds regional diversity." This is wrong. The sequence is: extract date → compare to now → if >48hrs, REJECT. A verified old date is still old. Regional diversity or topic coverage never overrides the 48-hour cutoff.
5. **If a date cannot be extracted from meta tags, JSON-LD, or search snippet, REJECT the candidate.** Do not include unverified articles. There is no "unverified" status — only PASS or REJECT.
6. **Extraordinary claims require verification.** If a story implies a major world event (a head of state removed, a country collapsing, a massive policy reversal), verify it against at least 2 Tier 1 news sources (BBC, Reuters, AP, NYT). If only niche or unverifiable sources carry the claim, do not include it.
7. **Outputs a validated candidate list** as structured data, e.g.:
   ```json
   {
     "headline": "ACA Premium Subsidies Expired...",
     "url": "https://www.pbs.org/...",
     "source": "PBS News",
     "verified_date": "2026-02-01",
     "today": "2026-02-04",
     "age_hours": 72,
     "verdict": "REJECT — exceeds 48 hours",
     "date_extraction_method": "article:published_time meta tag",
     "estimated_read_time_min": 6
   }
   ```
   The `age_hours` field MUST be computed numerically (`today - verified_date` in hours). If `age_hours` is not present, the candidate is not validated. `age_hours > 48` = automatic REJECT regardless of topic importance, regional diversity, or gap-filling.

### Phase 1 Output Checkpoint (MANDATORY)

Before generating ANY briefing content, present the validated candidate list. Show each candidate with: headline, URL, source, verified_date, and how the date was verified. Also show rejected candidates and rejection reasons. **Do not proceed to Phase 2 until the candidate list is reviewed.** When running automated (no user present), the checkpoint is self-review: scan the list for any article older than 48 hours and remove it before proceeding.

**Universal URL requirement:** Every item in every section (Tier 1, From X, GA) must have a verified URL at checkpoint time. Placeholder text like "(to be fetched)", "(verified earlier)", or "(need to verify)" means the item is not validated and cannot appear in the checkpoint. No URL = not validated = not included. This applies identically to all sections.

**Checkpoint continuity:** If multiple checkpoint rounds occur in one session, any story that appeared in a prior checkpoint must either (a) appear in the current checkpoint with a verified URL, or (b) have an explicit rejection reason in the Dropped section. Stories cannot silently disappear between checkpoints.

### Phase 1 Mandatory Verification Tables

Before proceeding to Phase 2, you MUST produce ALL of the following tables. If any table is missing, Phase 1 is incomplete and Phase 2 cannot begin.

**1. Age Verification Table (all sections)**
For every candidate in Tier 1, GA, and Local:
```
| # | Headline (truncated) | Source | verified_date | today | age_hours | Verdict |
|---|---------------------|--------|---------------|-------|-----------|---------|
| 1 | House Ends Shutdown | NPR | 2026-02-03 | 2026-02-04 | 24 | PASS |
| 2 | Pakistan cricket... | Al Jaz | 2026-02-01 | 2026-02-04 | 72 | REJECT |
```
Every candidate must have a numeric `age_hours`. No exceptions. `age_hours > 48` = REJECT.
**Verdicts must be computed mechanically, never written by judgment.** State the rule, state the number, apply the comparison. If `age_hours` is 49, the verdict is REJECT — do not override because the story "fills a gap" or "seems recent enough."

**No approximate values.** The `age_hours` field must be a computed integer. Tildes (~), "about", "borderline", or blank cells are invalid. If exact date unavailable, verdict = REJECT. There is no "unverified" middle state — either the date was extracted and age computed, or the candidate is REJECT.

**2. GA Source Tally**
```
| Source | Count | Tier | Status |
|--------|-------|------|--------|
| Al Jazeera | 2 | Tier 1 | OK |
| Reuters | 3 | Tier 1 | OK |
| AP | 2 | Tier 1 | OK |
| NPR | 1 | Tier 1 | OK |
| Bloomberg | 2 | Tier 2 | OK |
| East Bay Times | 1 | Local | ⚠️ SWAP — find Tier 1/2 source |
```
If any source exceeds 3, STOP. Swap items for the same story from a different outlet before proceeding.
If any source is local/Tier 3 for a national story, STOP. Find Tier 1/Tier 2 coverage instead.

**GA US Item Count:**
```
US items: ___ / 4 max
International items: ___ / 6 min
```
If US > 4, remove the weakest US item before proceeding.

**3. From X Status ID Comparison**
```
| Handle | Status ID | URL | Reference ID (known today) | Delta | Verdict |
|--------|-----------|-----|---------------------------|-------|---------|
| @karpathy | 2015883857489522876 | x.com/karpathy/status/2015883857489522876 | 2018500000000000000 | -2.6M | REJECT |
| @simonw | 2018413446166167919 | x.com/simonw/status/2018413446166167919 | 2018500000000000000 | -87K | PASS |
```
Reference post must be from a known-today source (@OpenAI, @AnthropicAI, or any post confirmed today).
Negative delta > 500K = REJECT. If no reference post can be found, note it and use date from post page instead.
**Same mechanical verdict rule: state the delta, apply the threshold, write the result. Delta 800K = REJECT, not "PASS (close enough)."**
**No URL = no item.** If you cannot produce a real `x.com/handle/status/[id]` URL, the post cannot appear in From X.
**Brand accounts excluded from From X:** @OpenAI, @AnthropicAI, @SpaceX, @BBCBreaking, @Reuters. These belong in Tier 1 stories, not From X.

**4. URL Verification Log**
For every URL in every section (Tier 1, From X, GA, Local):
```
| URL (truncated) | Section | Fetch Status | Verdict |
|----------------|---------|-------------|---------|
| pbs.org/newshour/... | Tier 1 | 200 OK | PASS |
| x.com/alexalbert__/status/... | From X | 404 | REJECT |
| statnews.com/... | Tier 1 | 403 (paywall) | PASS (confirmed via search) |
```
- 200 OK = PASS
- 404 or redirect to homepage = REJECT
- 403 (paywall) = PASS only if headline confirmed via search snippet
- If a URL was never fetched, it is NOT verified and cannot be included
- **Zero fabricated URLs.** If you cannot find a real URL for a candidate, drop the candidate. 4 verified items beats 5 with 1 fabricated.

**5. Healthcare Candidate Log**
```
| Source | Headline | verified_date | age_hours | Verdict | Rejection Reason |
|--------|----------|---------------|-----------|---------|------------------|
| Healthcare Dive | Story A | 2026-02-03 | 18 | PASS | — |
| STAT News | Story B | 2026-01-30 | 120 | REJECT | >48 hours |
| Modern Healthcare | (no results) | — | — | — | No recent articles |
| Becker's | Story C | 2026-02-02 | 40 | PASS | — |
| Fierce Healthcare | (no results) | — | — | — | No recent articles |
```
All 5 healthcare sources must appear in this table. If fewer than 3 stories PASS, that's fine — quiet news day. But the log must prove the sweep was done.

### Phase 1 Mandatory Source Sweep

Before presenting candidates, confirm you have searched all of the following. If any source returns 0 results, note it explicitly in Phase 1 output.

**Healthcare (must check all):**
- [ ] Healthcare Dive
- [ ] STAT News
- [ ] Modern Healthcare
- [ ] Becker's Hospital Review
- [ ] Fierce Healthcare

**Tech & AI (must check all):**
- [ ] TechCrunch AI
- [ ] The Verge AI
- [ ] Ars Technica
- [ ] Techmeme (aggregator catch-all)

**From X (must search handles individually):**
- [ ] Find a known-today post from @OpenAI or @AnthropicAI as status ID reference (these are for date comparison ONLY — they cannot be From X candidates)
- [ ] @karpathy
- [ ] @sama
- [ ] @simonw
- [ ] @emollick
- [ ] @alexalbert__ / Boris Cherny (@bcherny)
- [ ] @levelsio
- [ ] @DrJimFan
- [ ] @garrytan
- [ ] @paulg
- [ ] At least 2 others from: @saranormous, @EladGil, @benedictevans, @toaborai
- [ ] Compare all candidate status IDs to reference; reject if delta > 500K
- [ ] **Report which handles returned no recent results** — don't silently skip

**General Awareness (must check all Tier 1 sources):**
- [ ] BBC World (bbc.com/news/world)
- [ ] Reuters (reuters.com)
- [ ] AP News (apnews.com)
- [ ] NPR (npr.org)
- [ ] Al Jazeera (aljazeera.com)
- [ ] NYT or Politico (for US domestic — government, DOJ, Supreme Court, Congress)

**Local — East Bay / Tri-Valley (must check at least 3):**
- [ ] East Bay Times / Mercury News (eastbaytimes.com)
- [ ] Patch Danville / San Ramon (patch.com/california/danville, patch.com/california/sanramon)
- [ ] KQED (kqed.org)
- [ ] BART alerts (bart.gov/schedules/advisories)
- [ ] Bay Area Air Quality (baaqmd.gov)
- [ ] lu.ma / Eventbrite for Bay Area tech events

**Ticket Watch (check for priority artists + major Bay Area events):**
- [ ] Search "Manchester United tour 2026 tickets" / "Manchester United USA"
- [ ] Search "Taylor Swift tour 2026 tickets Bay Area"
- [ ] Search "Coldplay tour 2026 tickets Bay Area"
- [ ] Search "Piano Guys tour 2026 tickets Bay Area"
- [ ] Check Ticketmaster Bay Area new onsales (ticketmaster.com)
- [ ] Check Chase Center, Levi's Stadium, Shoreline Amphitheatre upcoming events

### Phase 1 Completeness Rule

The mandatory source sweep above IS the wide net. If after completing every checkbox you still have fewer than 5 Tier 1 candidates, 5 From X posts, or 10 GA items — that's okay as long as every checkbox was searched. A thin briefing from a thorough sweep means it was a quiet news day. A thin briefing because you only searched 3 sources means the sweep was incomplete. **Never pad with stale or low-quality stories to hit a number. But always complete the full sweep before concluding the pool is thin.**

The output of Phase 1 is a clean list of date-verified, recent articles with their real URLs, real dates, and real sources. The LLM never decides the date — the code hands it a fact.

### Phase 1 Persistence (mandatory)

All Phase 1 verification tables must be saved to `output/phase1-YYYY-MM-DD.json` containing:
- Age Verification Table (all candidates with numeric age_hours and verdict)
- GA Source Tally (with tier and count)
- From X Status ID Comparison (with URLs and deltas)
- URL Verification Log (all fetched URLs with status)
- Healthcare Candidate Log (all 5 sources with verdicts)

This file must be written before Phase 2 begins. It makes every briefing auditable after the fact — if a stale or fabricated item appears in the final briefing, the Phase 1 file will show whether it was validated or added later.

### Phase 2: Generate the Briefing (LLM generation)

**Phase 1 output is immutable.** After the Phase 1 checkpoint is complete, no new items can be added. Phase 2 draws ONLY from the validated candidate list. Do not search for additional stories during Phase 2. If you discover a story while writing that wasn't in Phase 1, it cannot be included — it missed the validation gates.

Using ONLY the validated candidate list from Phase 1:

1. **List the candidate pool** — at the start of Phase 2, write out only the headlines that PASSED Phase 1. This is your closed universe.
2. **Rank by signal strength** — score each candidate by relevance to PayZen, your active decisions, and strategic context
3. **Check for promotion candidates** — scan for stories big enough to promote from General Awareness to Tier 1
4. **Apply selection criteria and anti-patterns** (see below)
5. **Check source diversity** — no more than 3 from the same publication (2 is the default; 3 only if all are strong), at least 3 distinct sources
6. **Generate summaries and So Whats** for the top 5–10 stories
7. **Generate General Awareness items** from remaining validated candidates
8. **Generate "Today in 30 Seconds"** from the strongest So Whats
9. **Render as HTML email** using the reference template

**Phase 2 Cut Log (mandatory).** After selecting stories, produce a cut log for every Phase 1 PASS that didn't make the final briefing:
```
| Headline | Phase 1 Verdict | Phase 2 Decision | Reason |
|----------|----------------|-----------------|--------|
| Santé Investment | PASS | CUT | Lower signal than other healthcare stories |
| Hungary election | PASS | CUT | Would exceed 4 US items... wait, this is international — INCLUDE |
```
**Reconciliation count:** Phase 1 PASS count = items in final briefing + items in Phase 2 Cut Log. If these don't add up, something was silently dropped.

**Cross-reference check (mandatory).** Before finalizing HTML, verify that every URL in the final briefing appears in the Phase 1 URL Verification Log. If a URL is in the briefing but not in the log, it was added after Phase 1 and must be removed.

**Deduplication check (mandatory).** Before finalizing, list all headlines across all sections (Tier 1, From X, GA, Local). If the same story or event appears in more than one section, keep it in the most relevant section and remove it from the other. The same URL cannot appear twice in the briefing.

**GA pre-publish counts (mandatory):**
- US items: ___ / 4 max
- International items: ___ / 6 min
- Distinct regions: ___ / 4 min
- Source with highest count: ___ (___ items) / 3 max

If any count is out of range, fix before publishing.

**Critical rule:** The model must use the `verified_date` from Phase 1 in every meta line. It must NEVER generate, modify, or override a date. Every story in the briefing must have a verified date — there are no "unverified" stories.

**Source consistency rule:** Phase 2 must use the exact source and URL validated in Phase 1. If Phase 1 validated a story from Healthcare Dive, the briefing must cite Healthcare Dive — not swap to a different outlet's coverage of the same story. The two-phase architecture only works if Phase 2 output is traceable to Phase 1 validation.

**Factual integrity rule:** Phase 2 summaries and context lines must not introduce statistics, quotes, or specific claims not present in the source article. If a number appears in a briefing summary (e.g., "nearly one million visitors"), it must appear in the fetched article. The LLM may paraphrase and contextualize, but it must not fabricate specifics. When in doubt, use vaguer language ("tens of thousands" instead of a made-up precise number).

### Weekend Briefings (Saturday/Sunday)

Healthcare trade press (Healthcare Dive, STAT, Modern Healthcare, Becker's, Fierce Healthcare), business publications, and policy sources publish minimally on weekends. This is expected — not a failure.

**Weekend adjustments:**
- If the healthcare sweep returns fewer than 2 passing stories, that's fine for a weekend
- Lean more heavily on From X (AI Twitter doesn't sleep), GA (international news runs 24/7), and Local (events, weather, community news)
- Consider promoting strong GA stories to Tier 1 if they warrant deeper analysis (e.g., Super Bowl as both cultural and local story)
- When Tier 1 count is below 5, add a brief editorial note in the briefing header: "Lighter edition today — weekend news cycle." This sets expectations rather than silently delivering a thin product.

The 48-hour freshness rule, URL verification, and source tier requirements still apply on weekends — don't relax quality gates just because volume is lower.

---

## Briefing Format

### Output format
This briefing is rendered as an **HTML email**. Use the reference template (`morning-briefing-template.html`) for exact styling. The HTML should be self-contained (inline-ready CSS, no external dependencies except Google Fonts).

**Output filename:** `morning-intelligence-YYYY-MM-DD.html` (e.g., `morning-intelligence-2026-02-03.html`)

### Design principles
The design should feel like a premium editorial newsletter — think Monocle, The Economist Espresso, or Morning Brew's cleaner moments. Not a SaaS dashboard, not a corporate report.

- **Typography:** Playfair Display for headlines/mastheads (editorial weight), Source Sans 3 for body (clean readability), JetBrains Mono for labels/metadata (precision, modern). Never use generic system fonts.
- **Color palette:** Warm whites and creams (#f8f7f4, #fafaf8) for backgrounds. Near-black (#1a1a1a, #2c2c2c) for text. Muted gold (#b8860b) as the single accent color — used sparingly for labels, left-borders on So What blocks, and key emphasis. No blues, no gradients, no heavy color blocks.
- **Layout:** Clean single-column. Generous whitespace between stories. Story numbers in large, light serif type (decorative, not functional). Section labels in small monospace uppercase with a trailing rule line.
- **So What blocks:** Light background (#fafaf8) with a 3px gold left border and rounded right corners. Visually distinct from the summary — this is the most important part of each story.
- **General Awareness:** Compact rows with flag emoji, bold headline, context, and right-aligned source/time. Subtle bottom borders between items.
- **Mobile-friendly:** Padding reduces on small screens, source labels in General Awareness hide on mobile to save space.
- **No heavy header blocks.** The masthead is a single line of small-caps serif, not a giant colored banner.

### Header
```
Masthead: "The Morning Intelligence" (left) / "Digital Chief of Staff" (right)
Date line: [Day], [Date] · [X] deep reads · ~[Y] min total
```

### Today in 30 Seconds (appears right after header)
A quick-scan summary of the 3–4 most important takeaways from today's briefing. This is for the mornings when you have 30 seconds, not 35 minutes. Each item is **one short line** — bold key fact + brief implication. No multi-sentence bullets.

```
TODAY IN 30 SECONDS
• [Bold key fact] — [short implication, under 15 words]
• [Bold key fact] — [short implication, under 15 words]
• [Bold key fact] — [short implication, under 15 words]
```

Selection for this section: pick the 3–4 stories with the strongest So Whats. If a story's So What is "monitor this" or "early signal," it probably doesn't make the 30-second cut. Prioritize stories where the implication is concrete and immediate.

### Tier 1: Deep Insight (5–10 stories)

Organized by section. Sections should include:
- **🏥 Health Tech** — RCM, patient financing, provider operations, health system M&A, policy/regulation
- **⚡ Tech & AI** — AI tools, enterprise AI, coding agents, relevant product/tech trends
- **🐦 From X** — Up to 5 high-signal posts from AI leaders, builders, VCs, and the Claude Code team. This is a dedicated section, not an afterthought.
- **💰 Business & Strategy** (when warranted) — fintech, healthcare fintech, GTM patterns, fundraising signals

**Section quality bars:**
- **Health Tech** is the core of the briefing and should typically have the most stories. But don't force it — if the healthcare sweep (all 5 mandatory sources) only surfaces 1-2 stories that pass validation, that's fine. A thin healthcare section from a thorough sweep is better than padding with stale or marginal stories. The Healthcare Candidate Log (Phase 1) must show the sweep was done.
- **Tech & AI** must feature **concrete developments** — model releases, tool launches, specific adoption case studies, benchmark results, regulatory moves. Generic think pieces about "AI design principles" or "why AI matters for enterprise" are not stories. If Codex shipped an update, Claude Code added a feature, an open-source agent went viral, or a company published real adoption numbers — those are stories. Aim for 2–4 stories.
- **🐦 From X** should surface up to 5 high-signal posts — viral demos, benchmark drops, provocative threads, shipping announcements, or takes that are driving real discussion in AI/tech circles. These get a lighter format than full Tier 1 stories (see format below). This section should feel like "here's what AI Twitter is talking about today."
- **Business & Strategy** is optional — only include when there's a genuinely relevant story (fintech funding, GTM pattern, M&A).

**Numbering: Stories must be numbered sequentially across ALL sections** (1, 2, 3, 4, 5... not restarting per section, not skipping numbers). If there are 7 Tier 1 stories, they're numbered 1–7. If the output shows numbers out of order (e.g., 01, 02, 03, 05, 04), the generation is broken.

**Reading time:** Estimate based on article word count (~250 words/min). A typical news article is 3–6 min, a deep dive is 8–15 min. Never default to "1 min" — if you can't estimate accurately, omit the reading time. Reading times should vary across stories — if every story shows the same reading time, the estimation is broken.

**Source diversity:** No more than 2 Tier 1 stories from the same publication as a default. A third is acceptable if all three are genuinely strong and distinct stories — but never more than 3. Tier 1 should draw from **at least 3 distinct sources**.

Each story follows this format:
```
### 1. [Headline — rewritten to be specific and informative]
**[Source] · [Publication date, e.g. "Feb 2, 2026"] · [X] min read[ · 🔒 paywall]**

[2-3 sentence summary of the actual news]

**So What:** [1 paragraph — specific, opinionated, actionable. Written in **second person** ("you", "your team") — never refer to Rohan in third person.
Reference PayZen's business, your team, your decisions where relevant.
Not generic industry commentary — specific strategic implications.]
```

**Publication date is mandatory.** It must appear in the meta line for every Tier 1 story. Dates come from Phase 1 (code extraction) — the LLM must never generate a date. Articles without verified dates are rejected in Phase 1 and never reach the briefing.

#### Rules for "So What" sections:
- **Write in second person.** "You should..." / "Your team..." / "Worth flagging to your VP Eng..." — never "Rohan should..." or "PayZen should consider..."
- **Be specific.** Not "this is relevant to healthcare" but "flag this to your partnerships team because CommonSpirit insourcing RCM means a new buyer owns the self-pay problem"
- **Be actionable when possible.** "Worth testing whether..." / "Ask your VP Eng about..." / "Good ammunition for..."
- **Connect to active decisions.** Claude Code rollout, VP Eng onboarding, GTM strategy, product roadmap
- **Name the business implication.** Pipeline opportunity, competitive signal, regulatory risk, cost tailwind
- **Be honest about signal strength.** "Early signal, worth monitoring" vs. "This directly impacts your Q2 plans"
- **Not everything connects to PayZen.** Some stories matter because they're big news in AI, tech, or the world. A major AI model release or a viral Karpathy thread matters for your general knowledge and AI-native strategy — it doesn't need to be forced into a "PayZen's addressable market expands" frame. If the natural So What is "this is worth 10 minutes of your time because it'll change how you think about X," that's a valid So What.
- **Vary the tone and length.** If every So What is a 5-sentence paragraph ending with "PayZen should position itself as..." the briefing is broken. Some So Whats should be 2 sentences. Some should be a pointed question. Some should say "just interesting, no action needed." The variety signals that each story was actually analyzed, not stamped from a template.

---

#### Story selection process (Phase 2):

**Principle: Cast wide first, then filter.** Phase 1 already gathered and validated candidates. Now rank and select.

1. **Start from Phase 1 output** — all candidates are already date-verified, URL-validated, and have accurate reading times. Sources include traditional publications, X/Twitter, blogs, and social — a trending post is just as valid as a news article if the signal is strong.
2. **Rank by signal strength** — score each candidate by how directly it affects PayZen, your decisions, or your strategic context.
3. **Check for promotion candidates** — scan General Awareness candidates for stories big enough that your CEO would mention them in a meeting (e.g., Musk merging SpaceX with xAI). Promote these to Tier 1 with a So What, even if not directly PayZen-related.
4. **Apply selection criteria** — each story must meet at least one:
   1. Directly affects PayZen's market, customers, or competitive position
   2. Affects a decision you're actively making
   3. Significant AI/tech development relevant to your AI-native company strategy
   4. Major healthcare policy/regulatory change with business implications
   5. Competitive intelligence on Cedar, Flywire, or adjacent players
   6. **A story so significant that any tech/healthcare executive would be expected to know about it** — e.g., major mergers (xAI + SpaceX), breakthrough AI demos, viral industry moments. These don't need a PayZen angle to earn Tier 1 placement.
   7. **A high-signal X/Twitter post or thread** from a tracked account (Karpathy, Anthropic team, etc.) that's generating real discussion — viral demos, benchmark results, provocative takes on AI tooling. These are first-class Tier 1 candidates.
5. **Apply anti-patterns filter** — reject stories that match any anti-pattern below (but apply these with judgment, not as keyword matches)
6. **Check source diversity** — ensure no more than 3 stories from the same publication (2 is the default; 3 only if all are strong and distinct) and at least 3 distinct sources
7. **Take the top 5–10** — quality over quantity. Don’t artificially cap if there are more genuinely strong stories, but don’t pad to hit a number.

#### Story selection anti-patterns (reject these):
- **Stale news:** Handled by Phase 1. If a stale article somehow reaches Phase 2, reject it. The model must never generate, guess, or assume a publication date — dates come from Phase 1 as verified facts.
- **Duplicates:** Deduplicate before output. If the same story appears from multiple sources, pick the best source and include it once.
- **Heavy hedging required:** If the So What requires multiple hedges ("weak signal," "probably won't matter," "historically resolves quickly") to justify inclusion, the story doesn't belong in Tier 1. Either drop it or move it to General Awareness.
- **Self-contradicting So Whats:** Only cut if the So What's overall conclusion is that the story is not important (e.g., "this is political noise, not business intelligence"). Conditional framing is fine — "this matters if the shutdown extends beyond a week" is nuance, not contradiction.
- **Sponsored content / vendor marketing:** Filter only when the article's primary purpose is promoting a specific vendor's product or partnership — i.e., it reads like a case study or press release, not journalism. An article that *quotes* or *references* a vendor while making a broader industry point is fine. If a genuinely promotional piece is included, flag explicitly as "⚠️ Sponsored/vendor content."
- **Pay-to-publish market research:** Reports distributed via PRNewswire, Globe Newswire, or Business Wire from research firms (Astute Analytica, Grand View Research, etc.) are paid press releases, not journalism. These "market projected to reach $X by 20XX" stories are marketing material. Exclude them from Tier 1. An article in a real publication *citing* such a report is fine — but the press release itself is not a story.
- **Newsletter recaps with no original content:** Only filter if the article is exclusively a republished newsletter with no additional reporting or analysis. A mention of "this originally appeared in..." is NOT grounds for exclusion if the content itself is substantive.
- **Padding to hit the count:** 4 strong stories beat 7 padded ones. Never include filler just to reach 5. Quality over quantity.
- **Generic think pieces as news:** Articles about "why AI matters" or "design principles for enterprise AI" are not news stories. They're evergreen content that could have been published any week. Tier 1 stories should describe **something that happened** — a launch, a deal, a policy change, a data release, a competitive move. The only exception is genuinely groundbreaking research or analysis with specific new findings.
- **Hallucinated stories:** If Phase 1 cannot find a real article at a real URL, the story does not exist. Never fabricate a company, product, article, or source. If a story name sounds plausible but can't be verified against an actual URL, it must be dropped. This is a critical integrity rule — a single fabricated story destroys the entire briefing's credibility.

### 🐦 From X (up to 5 posts)

The best of AI/tech Twitter from the last 24 hours. This section surfaces high-signal posts that are driving discussion — not every tweet from every account, just the ones worth reading.

```
## 🐦 From X
*What AI Twitter is talking about today.*

**[@handle](link to specific post)** — [1-2 sentence summary of what they said/showed and why it matters]

**[@handle](link to specific post)** — [1-2 sentence summary]
```

#### Rules for From X:
- **Link directly to the specific post** — the handle must be a clickable link to the actual tweet/thread URL (e.g., `https://x.com/karpathy/status/1886847487281881424`). Not a link to their profile. In the HTML output, this means an `<a href="...">` tag wrapping the handle text.
- **Aim for 5 posts.** Fewer is fine if the day was quiet, but typically AI Twitter generates at least 5 noteworthy posts daily.
- **Posts must be from the last 48 hours.** This matches the article freshness rule. Search indexing lag makes 24 hours impractical — 48 hours is the real threshold. A great Karpathy thread from last week is not today's news. Web search results often surface old viral posts — verify via status ID delta.
- **Verification heuristic for X post dates:** X status IDs are roughly chronological. Compare the candidate post's status ID to known-recent posts. If @sama posted status/2018437537103269909 on Feb 2, 2026, then any post with a status ID significantly lower (e.g., 1968xxx, 2004xxx) is likely weeks or months old. When in doubt, search for `[handle] [topic] [today's month and date]` to find posts explicitly dated to that day.
- **Status ID comparison is mandatory.** In Phase 1 output, show each candidate tweet's status ID alongside a reference-today post's status ID. If the candidate's ID is more than ~500K lower than the reference, REJECT it.
- **Red flag for old posts:** If a search for "February 2026" returns a post about a prediction or trend for 2026, it's likely an old post *about* 2026, not *from* February 2026. Similarly, posts about a product launch that happened weeks ago are stale even if they're resurfacing in discussion.
- **Only include posts with real substance** — shipping announcements, benchmark results, viral demos, insightful threads, provocative takes that generated real discussion. Not casual comments or retweets.
- **Voices, not brands — explicit exclusion list.** These accounts are not for From X: @OpenAI, @AnthropicAI, @SpaceX, @BBCBreaking, @Reuters, @SawyerMerritt. Corporate announcements belong in Tier 1 stories, not From X. If a story is big enough for a brand account to post about it, cover it in Tier 1 and find individual reactions for From X.
- **Keep it tight** — 1-2 sentences per post. This is a pointer, not a deep dive.
- **No more than 2 posts from the same handle** — 5 posts should reflect at least 4 different people.
- **Diversity of voices required.** The section should reflect the breadth of AI Twitter, not just one company's launch day. **No more than 2 posts about the same topic or event — this is a hard cap enforced in Phase 1.** If 4 out of 5 candidate posts are about the Codex launch, keep the best 2 and search for 3 more on different topics. If OpenAI launched Codex today, include 1-2 reactions — but the other 3 slots must cover different topics, tools, or perspectives.
- **Search strategy:** Don't just search by topic (e.g., "Codex launch site:x.com"). Also search each tracked handle individually — `site:x.com/simonw/status [current month year]`, `site:x.com/karpathy/status [current month year]`, `site:x.com/alexalbert__/status [current month year]`, etc. This ensures you catch posts unrelated to the day's biggest headline. Search at least 8-10 handles individually before finalizing the From X list.
- **Search indexing lag:** Web search indexes X posts with a 12-24 hour delay for most accounts. If today's posts aren't findable, try searching for `[handle] [current month] [current year]` and verify recency via status ID delta. Accept posts within the last 48 hours. If the full handle sweep returns fewer than 5 usable posts, ship with 3-4 quality posts rather than padding with brand accounts or aggregators.
- **These don't get numbered** — they're separate from the Tier 1 story count
- **Never skip From X entirely.** If 1-4 posts pass validation, include them. Only omit the section if literally 0 posts pass after the full handle sweep. 2 quality posts > empty section.
- **Phase 1 must verify each post URL exists.** Same rule as articles — no hallucinated tweets.

### Tier 2: General Awareness (10 items)

```
## 🌍 General Awareness
*So you're never caught off guard.*

- **🇺🇸 [One-line headline (linked to source)]** — [One sentence of context]. — [Source] · [Date] · [X] min[ · 🔒]
- **🇬🇧 [One-line headline (linked to source)]** — [One sentence of context]. — [Source] · [Date] · [X] min[ · 🔒]
```

#### Rules for General Awareness:
- **Target 10 items.** Fewer is fine on genuinely quiet news days, but most days should hit 10.
- **No more than 4 US items.** The rest should be international. This is a global awareness section, not a US news recap.
- **But at least 1-2 US items.** Major US domestic news (government shutdowns, Supreme Court rulings, mass casualty events, DOJ actions like the Epstein files) must be included. A GA section with 0 US items means something was missed. Check AP, NPR, NYT, and Politico for top US stories before finalizing.
- **Headlines must be clickable links** to the source article. Links must resolve to the actual article — not a homepage, search page, or unrelated page. Phase 1 must verify each URL.
- **Publication dates are mandatory** — same rule as Tier 1: dates come from Phase 1 code extraction, never generated by the LLM
- **Reading times are mandatory** — estimate based on article length, same as Tier 1
- **Use specific country/region flag emojis** (🇺🇸 🇬🇧 🇮🇱 🇨🇳 🇮🇳 🇳🇬 etc.) — never use 🌐 as a generic fallback. If a story is truly global, pick the most relevant country.
- **Minimum geographic spread:** At least 4 distinct regions (e.g., US, Europe, Middle East, Asia, Africa, Latin America). If the day's news only surfaces items from 1–2 regions, the source list isn't broad enough — check BBC World, AP, Reuters, Al Jazeera for international coverage.
- **Source diversity:** Draw from at least 4 distinct sources. **No more than 3 items from the same outlet.** If Al Jazeera or BBC is producing most of the international coverage, swap 1-2 items for the same story from Reuters, AP, or Guardian.
- **Source quality tiers for GA:**
  - **Tier 1 (prefer):** BBC, Reuters, AP, Al Jazeera, NPR, NYT, WSJ, The Guardian
  - **Tier 2 (acceptable):** Bloomberg, CNBC, Financial Times, Politico, Washington Post, CNN, PBS, ABC News, CBS News, NBC News
  - **Tier 3 (avoid for GA):** Balkan Insight, Just Security, WORLD, Defense One, Yahoo Sports, UNHCR, Olympics.com, Ukr. Pravda, and similar niche publications, aggregators, or single-topic sources. Only use Tier 3 if they are the sole source for a significant story no major outlet has covered — then actively search for Tier 1/2 coverage before including.
  - **Local papers (NEVER for GA):** East Bay Times, Mercury News, Patch, Danville SanRamon, and similar local papers are for the Local section only. If a national story (e.g., WaPo layoffs, PayPal earnings) is found via a local paper, find the same story from a Tier 1/Tier 2 source instead.
- **Every GA item must have a verified URL.** "Search results" or "multiple sources confirm" is not a URL. If Phase 1 can't produce a real article URL for a GA item, the item is not validated and cannot be included.
- **Paywalls flagged with 🔒** — same as Tier 1, mark paywalled sources in the meta line
- **Known paywalled sources (always mark with 🔒):** STAT News, Modern Healthcare, The Information, WSJ, NYT, Financial Times. Bloomberg is sometimes paywalled — check the specific article.
- **Combine redundant stories** — if two items are the same trend (e.g., two measles outbreaks in different locations), merge into one item. Don't waste two GA slots on one story.
- One line each — just enough to not be caught off guard in conversation
- These are the biggest global/national stories of the day regardless of PayZen relevance
- Include major cultural moments (Grammys, Super Bowl, etc.) when they're in the news
- No niche industry items that aren't big enough to come up in general conversation
- No filler quotes (e.g., random inspirational quotes at the end)

### Tier 3: Local — East Bay / Tri-Valley (3-5 items)

```
## 📍 Local — East Bay
*What's happening around you.*

- **[One-line headline (linked to source)]** — [One sentence of context]. — [Source] · [Date]
- **[One-line headline (linked to source)]** — [One sentence of context]. — [Source] · [Date]
```

#### Rules for Local:
- **Location:** Danville, CA and surrounding East Bay / Tri-Valley area (San Ramon, Dublin, Pleasanton, Walnut Creek, Livermore, Oakland, broader Bay Area)
- **3-5 items.** Fewer is fine on quiet days. Skip the section entirely if nothing local is newsworthy.
- **What to include:**
  - Local news: city council decisions, major developments, school district news, crime/safety alerts
  - Transit/traffic: BART disruptions, 680/580 closures, VTA changes
  - Bay Area tech events: meetups, conferences, demo days happening today or this week (check lu.ma, Eventbrite, Meetup)
  - Weather: only if notable (heat wave, air quality advisory, storm, PG&E shutoffs)
  - Bay Area business: local company announcements, office openings/closures, layoffs that affect the area
- **What to exclude:** National news that happens to mention the Bay Area, routine crime blotter, real estate listings, opinion/editorial pieces, business promotions ("now open", "grand opening"), sports scores/rankings, advice columns, horoscopes, obituaries. The pipeline uses an **allowlist filter** (`_LOCAL_INCLUDE_PATTERNS` in `run_pipeline.py`) — only articles matching valid categories (transit, weather/air quality, local government, safety, community events, local healthcare, local economy impact) pass through. All others are dropped.
- **Sources:** East Bay Times, Mercury News, SF Chronicle, Danville SanRamon, Patch (Danville/San Ramon), KQED, Bay Area News Group, local government sites (danville.ca.gov, contracosta.ca.gov), lu.ma, Eventbrite
- **Same 48-hour rule applies** — no stale local news
- **Phase 1 must verify URLs** — same as all other sections

### Ticket Watch (end of Local section)

A single line at the end of Local when tickets go on sale for priority artists/events or major tours announce Bay Area dates.

**Priority watchlist (always include if tickets announced):**
- Manchester United (any US tour/friendly)
- Taylor Swift
- Coldplay
- Piano Guys

**Also include:** Major artists/events of broad renown announcing Bay Area shows or ticket sales — arena tours, stadium concerts, sports events (Warriors, 49ers playoffs, etc.). Use judgment: a huge act announcing Levi's Stadium or Chase Center dates is worth a line; a niche artist at a small venue is not.

**Format:**
```
🎟️ **Ticket Watch:** [Artist/Event] [Tour Name] — [Venue], [Date]. [On-sale info: date/time, presale codes if known]. [Link to tickets]
```

**Example:**
```
🎟️ **Ticket Watch:** Coldplay Music of the Spheres Tour — Levi's Stadium, Aug 15-16. General sale Friday 10am PT via Ticketmaster.
```

**Sources to check:** Ticketmaster new onsales, Live Nation announcements, venue sites (Chase Center, Levi's Stadium, Shoreline, Greek Theatre), artist official sites/social, Pollstar.

**Rules:**
- Only include when tickets are going on sale or just went on sale (within 48 hours of announcement)
- Skip if the event is sold out or presale-only with no public sale announced
- One line per event — keep it brief
- Link directly to ticket page when possible

### Footer
```
---
*Sources: [list]*
*🔒 = paywall*
```

---

## What NOT to include
- Stories that are interesting but have no clear "so what" for Tier 1 and aren't big enough for Tier 2
- Generic "Why It Matters" like "AI capabilities that could enhance operations" — if you can't be specific, it doesn't belong in Tier 1
- "Elsewhere in..." dump sections — every Tier 1 story earns its spot or it's out
- Duplicate stories — same news from different sources should be merged, not repeated
- Pieces whose primary purpose is vendor promotion (case studies, press releases disguised as articles) — articles that merely *reference* a vendor are fine
- Pure newsletter recaps with zero original content — articles that *mention* their newsletter origin but contain substantive content are fine
- Stories whose own So What concludes they aren't important — conditional framing ("matters if X happens") is fine
- Inspirational quotes, sign-off messages, or any padding that isn't news
- Generic 🌐 flag emojis in General Awareness — always use specific country flags
- More than 3 Tier 1 stories from the same publication (2 is the default max; 3 is acceptable if all are strong and distinct)

---

## Sources to monitor (Phase 1 inputs)

**Source freshness rule:** Prioritize original reporting and breaking news over republished content. When the same story is available from a primary source and a secondary aggregator, use the primary source.

**X/Twitter and social are first-class sources.** A trending thread, a viral demo, or a high-signal post from a tracked account is just as valid as a traditional article. If Karpathy posts a breakthrough benchmark, or the Claude Code team ships a new feature, or a startup demo goes viral — that's a story, not a second-class source.

Phase 1 should search/scrape the following:

- **Health Tech — Trade publications:** Healthcare Dive, Fierce Healthcare, Modern Healthcare, Becker's, STAT News, KFF Health News
- **Health Tech — Research & policy:** Health Affairs (journal — publishes high-signal studies), Advisory Board, AHA News, CMS.gov press releases and rulemaking, Politico Health/Pulse (healthcare policy and regulation)
- **Health Tech — Industry players:** Cedar/Flywire/competitor blogs and press rooms
- **Health System newsrooms:** Cleveland Clinic, Geisinger, Banner Health, Sutter Health, HCA, CommonSpirit, Ascension, and other top-300 systems. These often break news before trade press picks it up.
- **AI & Tech — Publications:** The Verge AI, TechCrunch AI, MIT Technology Review, Ars Technica, The Information (paywalled but high-signal), Semafor Tech, Wired
- **AI & Tech — Substacks & blogs:** Simon Willison (simonwillison.net), Ben Thompson/Stratechery, Ethan Mollick (One Useful Thing), Zvi Mowshowitz, Hugging Face blog (open-source model releases), Casey Newton/Platformer (tech policy), Nathan Benaich (State of AI)
- **X/Twitter — AI builders & leaders (primary feed for 🐦 From X section):**
  - **Anthropic / Claude Code:** @AnthropicAI, @alexalbert__ (Alex Albert, Claude product), Boris Cherny (Claude Code lead — search by name, handle may change). For other Anthropic/Claude Code team members, search by name + "site:x.com" — handles change.
  - **OpenAI:** @sama (Sam Altman), @gaborcselle (Gabor Cselle), @OpenAI
  - **AI researchers & builders:** @karpathy (Andrej Karpathy), @ylecun (Yann LeCun), @DrJimFan (Jim Fan / NVIDIA), @hardmaru (David Ha)
  - **AI tooling & dev experience:** @simonw (Simon Willison), @levelsio (Pieter Levels), @swyx (Swyx), @kentcdodds
  - **VCs & investors writing about AI:** @garrytan (Garry Tan / Y Combinator), @paulg (Paul Graham), @saranormous (Sarah Guo / Conviction), @EladGil (Elad Gil), @mattturck (Matt Turck / FirstMark), @wolfejosh (Josh Wolfe / Lux Capital), @VinodKhosla (Vinod Khosla), @naborsi (Nabeel Hyatt / Spark Capital — search by name if handle wrong)
  - **AI commentary & strategy:** @benedictevans (Benedict Evans), @emollick (Ethan Mollick)
  - **NOTE: Handles change and get deactivated. When searching for From X posts, search by person's full name + "site:x.com" if a handle doesn't resolve. Do not fabricate handles.**
  - **Search broadly** — don't limit to this list. If someone not on this list has a post going viral in AI circles, include it. The list is a starting point, not a constraint.
- **Business:** WSJ, Bloomberg, Reuters, Financial Times, Forbes
- **General:** BBC World, NYT, AP, NPR, Al Jazeera
- **Healthcare fintech & VC:** Rock Health (publishes quarterly digital health funding reports), CB Insights healthcare, Crunchbase News (catches funding rounds that trade press misses)
- **Company blogs:** Anthropic blog, OpenAI blog, Google DeepMind blog — these often break product news before press coverage
- **Aggregators & "did I miss anything" checks:** Techmeme, Google News top stories, Hacker News front page (news.ycombinator.com — surfaces real projects and discussions fast)

---

## Quality check before sending
- [ ] **All 5 verification tables produced** — Age table, GA Source Tally, From X Status ID table, URL Verification Log, Healthcare Candidate Log. If any is missing, Phase 1 was incomplete.
- [ ] **Pre-flight checklist in CLAUDE.md completed** — every box checked before Phase 2 began
- [ ] **Phase 1 checkpoint completed** — validated candidate list was presented with dates and verification methods before any content was generated
- [ ] **Phase 1 ran successfully** — all articles were fetched, dates extracted from meta tags/JSON-LD, and stale articles rejected by code. No articles with unverifiable dates were included.
- [ ] **All dates are from Phase 1, not generated** — every publication date was extracted from the actual article page by the validation script. The LLM did not produce any dates.
- [ ] **All stories are current** — every article published within the last 48 hours based on Phase 1 verified dates
- [ ] **No hallucinated stories** — every story has a real URL from Phase 1 that resolves to an actual article. No fabricated companies, products, or sources.
- [ ] **Numbering is sequential** — stories numbered 1, 2, 3... across all sections with no gaps or reordering
- [ ] **No duplicates** — every story appears exactly once
- [ ] **So Whats vary in tone and length** — not every So What follows the same "PayZen should position itself..." template. Some are 2 sentences, some are a question, some say "no action needed, just interesting"
- [ ] **Source diversity** — no more than 3 Tier 1 stories from the same publication (2 is default; 3 only if all are strong), at least 3 distinct sources in Tier 1 and in General Awareness
- [ ] Every Tier 1 story has a specific, opinionated So What (not generic)
- [ ] **No heavy hedging** — if the So What is mostly caveats, cut the story
- [ ] **No self-contradicting So Whats** — if the analysis concludes the story doesn't matter, cut it. Conditional framing ("matters if X") is fine.
- [ ] So What sections are in **second person** ("you", "your team") — never "Rohan should..."
- [ ] So Whats reference PayZen, your decisions, or your team where relevant — but not every So What needs a PayZen angle
- [ ] **Reading times are realistic and varied** — estimate from article length (a typical article is 3–6 min, not 1 min). If every story shows the same reading time, the estimation is broken. If actual reading time is unknown, omit rather than guess wrong.
- [ ] Paywalls flagged with 🔒 in both Tier 1 and General Awareness
- [ ] 5–10 Tier 1 stories (but 4 strong > 7 padded), **10 General Awareness items** (no more than 4 US)
- [ ] No filler — would you forward each Tier 1 story to your CEO or VP Eng with a note?
- [ ] **No sponsored content** — only filter pieces whose primary purpose is vendor promotion, not articles that reference vendors
- [ ] **No pure newsletter recaps** — only filter if the piece has zero original content beyond the republished newsletter
- [ ] **Wide net cast** — stories sourced from X/Twitter, blogs, and social are included alongside traditional publications
- [ ] **Big news included** — if there's a major story any tech/business executive would know about (major merger, viral AI demo, geopolitical event), it's in the briefing regardless of PayZen relevance
- [ ] **Not everything forced to PayZen** — some So Whats are about general knowledge, AI strategy, or "this is worth your time" without a PayZen business case
- [ ] General Awareness uses **specific country flag emojis**, never 🌐
- [ ] General Awareness covers **at least 4 distinct regions**, **1-4 US items** (0 US items means major domestic news was missed; check AP, NPR, NYT)
- [ ] General Awareness: **no more than 3 items from the same outlet** — if one source dominates, swap for same story from a different Tier 1 source
- [ ] General Awareness: **every item has a real, verified URL** — "search results" or "multiple sources confirm" or "verified earlier" is not a URL. Fetch the actual URL and verify the date. No URL = not validated = not included.
- [ ] **No silent drops between checkpoint rounds** — if a story was verified in a previous checkpoint pass (e.g., Costa Rica election, South Korea crash), it cannot disappear without an explicit rejection reason. Correcting one issue must not silently break something else.
- [ ] **Extraordinary claims verified** — if a story implies a major world event (head of state removed, country collapsing, mass prisoner release), confirmed against at least 2 Tier 1 sources (BBC, Reuters, AP, NYT)
- [ ] General Awareness includes **reading times** on every item
- [ ] **From X posts are from the last 48 hours** — no old viral posts resurfaced by search. Each post date verified via status ID comparison against a known-today reference post. Delta > 500K = REJECT.
- [ ] **From X has 5 different handles** — no duplicate people, no more than 2 posts about the same topic/event, at least 8 handles searched individually
- [ ] **From X reflects AI Twitter, not corporate PR** — prioritize builders, researchers, VCs, and commentators. Brand accounts (@OpenAI, @AnthropicAI, @SpaceX, @BBCBreaking, @Reuters) belong in Tier 1, not From X. Corporate announcements belong in Tier 1.
- [ ] **From X reports search coverage** — Phase 1 must list which handles were searched and returned no recent results. If @simonw, @karpathy, @emollick, Boris Cherny, and every VC all returned nothing, say so explicitly — don't silently skip them.
- [ ] **From X: every post has a real status URL** — `x.com/handle/status/[id]`. No generic references to brand accounts without specific post links.
- [ ] **General Awareness sources are Tier 1 or Tier 2** — no niche/partisan outlets unless they're the sole source for a major story. **Local papers (East Bay Times, Patch, etc.) are NEVER used for GA** — they belong in Local only.
- [ ] **No duplicate stories across sections** — same event cannot appear in both GA and Local, or both Tier 1 and GA.
- [ ] **Phase 2 Cut Log produced** — every Phase 1 PASS not in the final briefing has a stated cut reason. Reconciliation count matches.
- [ ] **Cross-reference check passed** — every URL in the final briefing appears in the Phase 1 URL Verification Log. No post-Phase-1 additions.
- [ ] **General Awareness sources are Tier 1 or Tier 2** — no niche/partisan outlets unless they're the sole source for a major story
- [ ] **Local section: 3-5 items** from Danville / East Bay / Tri-Valley / Bay Area. Skip the section if nothing local is newsworthy. Same 48-hour and URL verification rules apply.
- [ ] **No inspirational quotes** or padding at the end

---

## Automation & Email Delivery

### Schedule
- **6:00 AM Pacific, daily** via Windows Task Scheduler
- Run Claude Code with `--dangerously-skip-permissions` for unattended execution

### Task Scheduler setup
1. Open Task Scheduler (`taskschd.msc`)
2. Click "Create Basic Task"
3. Name: `Morning Intelligence Briefing`
4. Trigger: Daily, 6:00 AM
5. Action: Start a Program
   - Program: `C:\Users\rohan\Desktop\ClaudeCode\morning_briefing\run-briefing.bat`
   - Start in: `C:\Users\rohan\Desktop\ClaudeCode\morning_briefing`
6. In Properties after creation:
   - Check "Run whether user is logged on or not"
   - Check "Wake the computer to run this task" (if laptop sleeps overnight)
   - Under Conditions, uncheck "Start only if on AC power" (if laptop)

### Email delivery (Gmail SMTP)

**One-time setup:**
1. Go to https://myaccount.google.com/apppasswords
2. Generate an app password for "Mail" (requires 2FA enabled on the account)
3. Store credentials in a `.env` file in the project directory:
   ```
   GMAIL_ADDRESS=your-email@gmail.com
   GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
   BRIEFING_RECIPIENT=your-email@gmail.com
   ```
4. Add `.env` to `.gitignore`

**Send script:** See `send-briefing.py` in the project root. The script:
- Reads the HTML briefing file
- Inlines all CSS using `premailer` (required for Gmail desktop rendering — Gmail strips `<style>` tags)
- Sends via Gmail SMTP with the subject line "Morning Intelligence — [Day, Month Date]"

**Dependencies:** `pip install python-dotenv premailer`

### Claude Code workflow (automated)
When running unattended, Claude Code should:
1. Run Phase 1 with self-review checkpoint (scan for >48hr articles, apply all hard gates)
2. Run Phase 2 to generate the HTML briefing
3. Save the HTML to `output/briefing-YYYY-MM-DD.html`
4. Call `send-briefing.py` to email it
5. Log success/failure

### Reference files
- **`morning-briefing-template.html`** — The reference HTML template with exact styling. Use this as the base for generating each day's email. Match the typography, color palette, spacing, and component structure precisely.
