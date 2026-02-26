"""
LLM Call Wrappers for Morning Intelligence Pipeline.

Session 2 deliverable: targeted LLM calls replacing Opus-as-orchestrator.

Cost model:
  - Haiku 4.5:  $0.80/1M input, $4/1M output  (bulk work)
  - Sonnet 4.5: $3/1M input, $15/1M output     (quality-critical)
  - Total estimated: $0.50-1.50 per briefing

Architecture:
  - Python orchestrator calls individual LLM functions
  - Each function has a focused prompt, structured JSON output
  - No multi-turn conversations — single-shot calls only
  - Token/cost tracking for every call

Haiku tasks: relevance scoring, article summaries, GA one-liners, Noteworthy X summaries
Sonnet tasks: So Whats, Today in 30 Seconds, quality review
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# Model IDs
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-5-20250929"

# Cost per 1M tokens (USD)
HAIKU_INPUT_COST = 0.80
HAIKU_OUTPUT_COST = 4.00
SONNET_INPUT_COST = 3.00
SONNET_OUTPUT_COST = 15.00


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)


# =============================================================================
# ROHAN CONTEXT (extracted from morning-briefing-spec.md)
# Included in every So What prompt so the LLM has full context.
# =============================================================================

ROHAN_CONTEXT = """## Rohan's Context

### PayZen — What the company does
- Patient financing for non-elective medical treatments — making healthcare more affordable
- Core products: patient payment plans and care cards for provider partners
- Target market: top 300 US health systems (which account for ~90% of healthcare revenue)
- Go-to-market: sales-led, with channel partnerships (Cedar, Flywire, and similar)
- Cedar and Flywire are complementary today but the relationship may become competitive
- Strategic direction: going deeper into healthcare affordability — financial assistance programs, Medicare/Medicaid eligibility, beyond just payment plans

### Rohan's role & priorities
- SVP of Product at a ~100-person healthcare fintech startup
- Starts at PayZen on March 9, 2026 — currently building landscape knowledge
- Wants PayZen to be a truly AI-native company (Claude Code for eng, AI tools as default)
- Building the case internally for AI adoption, including with resistant engineers
- Previously at LinkedIn for nearly a decade; background in management consulting across 14 countries

### Decision themes to tune toward
- Patient self-pay, out-of-pocket costs, healthcare affordability
- Drug pricing / pharma shifts affecting patient costs (GLP-1 pricing, biosimilars, PBM changes)
- RCM industry shifts — insourcing, vendor changes, consolidation (pipeline opportunities)
- Health system financial distress — cash flow problems make patient financing conversations urgent
- News from key health systems (Cleveland Clinic, Geisinger, Banner, Sutter — potential customers)
- Regulatory/policy changes affecting provider revenue, telehealth, reimbursement
- Moves by Cedar, Flywire, or other patient payment/RCM players
- AI coding tools landscape (Claude Code, Cursor, Codex) — competitive intelligence for rollout
- Enterprise AI adoption patterns — what's working, what's failing
- AI-native company strategies — how other orgs are operationalizing AI"""


# =============================================================================
# SO WHAT EXAMPLES (from Feb 9-10, 2026 briefings — proven quality)
# =============================================================================

SO_WHAT_EXAMPLES = """## Example So Whats (calibrate your tone and specificity to these)

### Example 1 — Healthcare-specific, actionable (MA Payment Policy)
"This is the most significant MA payment policy change in years, and the downstream effects matter for PayZen. When MA plans get squeezed on reimbursement, providers absorb some of that pressure through lower payments — which accelerates the shift of costs to patients. Health systems already struggling with MA margin compression will face even more urgent conversations about patient self-pay solutions. **Worth tracking which of your target health systems have heavy MA patient populations** — they'll be the most receptive to financing conversations in Q3-Q4."

### Example 2 — Industry signal, second-order connection (Kaiser Strike)
"Kaiser is the largest integrated health system in your backyard. A strike of this scale creates operational chaos — delayed labs, pharmacy closures, diverted patients. For PayZen, the signal is less about Kaiser specifically (they're integrated payer-provider) and more about what it says about healthcare labor costs industry-wide. If 25% raises become the new baseline, every health system's margins get thinner, and the appetite for solutions that improve collections without adding headcount grows. Just worth knowing about — this will come up in Bay Area conversations."

### Example 3 — AI strategy, company-building angle (Anthropic $350B Round)
"**The company behind your primary AI tool just became one of the most valuable private companies in the world.** A $350B valuation with $9B revenue says the market believes Claude's enterprise moat is real. For your AI-native strategy, this is reassuring — you're betting on a platform with staying power, not a feature that gets acqui-hired. The Nvidia and Microsoft co-investment is also interesting: it suggests Anthropic is building the kind of infrastructure partnerships that make switching costs higher for everyone in their ecosystem."

### Example 4 — Pure awareness, no PayZen angle needed (Japan Election)
"This is a 'you should know about this' story — any executive would be expected to have seen the headline. Japan is the world's fourth-largest economy, and a supermajority this large hasn't happened since the post-war era. The defense and China implications are geopolitically significant; the economic reform agenda could shift Japan's healthcare market too, though that's second-order. No action needed, just awareness."

### Example 5 — Positioning/narrative alignment (Hims Super Bowl Ad)
"The 'wealth-health gap' is now a mainstream talking point, and that's the exact narrative PayZen is built to address from the provider side. Hims is attacking it from the consumer/telehealth angle; PayZen attacks it at the point of care when patients face bills they can't pay. **Worth noting for positioning conversations:** when 130 million people just watched an ad saying the healthcare system is 'broken' for regular people, health system CFOs will be thinking about affordability solutions more than usual this week."
"""


# =============================================================================
# LLM CLIENT
# =============================================================================

class LLMClient:
    """Wrapper for Anthropic API calls with cost tracking."""

    def __init__(self, api_key: str = None):
        if not HAS_ANTHROPIC:
            raise RuntimeError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Export it or pass api_key="
            )
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.call_count = 0

    def _call(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """Make a single API call and return the text response."""
        msg = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Track tokens
        input_tokens = msg.usage.input_tokens
        output_tokens = msg.usage.output_tokens
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.call_count += 1

        # Calculate cost
        if model == HAIKU_MODEL:
            cost = (
                input_tokens / 1_000_000 * HAIKU_INPUT_COST
                + output_tokens / 1_000_000 * HAIKU_OUTPUT_COST
            )
        else:
            cost = (
                input_tokens / 1_000_000 * SONNET_INPUT_COST
                + output_tokens / 1_000_000 * SONNET_OUTPUT_COST
            )
        self.total_cost += cost

        return msg.content[0].text

    def _call_json(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict:
        """Make an API call and parse the JSON response."""
        text = self._call(model, system, user, max_tokens, temperature)
        # Extract JSON from response (handle markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            # Remove ```json and closing ```
            lines = text.split("\n")
            start = 1 if lines[0].startswith("```") else 0
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[start:end])
        # Find JSON object or array
        json_start = text.find("{")
        json_arr_start = text.find("[")
        if json_arr_start >= 0 and (json_start < 0 or json_arr_start < json_start):
            json_start = json_arr_start
            json_end = text.rfind("]") + 1
        else:
            json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(text[json_start:json_end])
        raise ValueError(f"No JSON found in response: {text[:200]}")

    def get_cost_summary(self) -> dict:
        return {
            "total_calls": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost, 4),
        }


# =============================================================================
# HAIKU TASKS (cheap, fast — bulk work)
# =============================================================================

def rank_candidates(client: LLMClient, candidates: list[dict]) -> list[dict]:
    """
    Rank ~30 candidates by relevance. Returns scored list with assignments.

    Uses Haiku — this is a bulk scoring task, not quality-critical.
    Each candidate gets a relevance_score (0-100) and section assignment.
    """
    _log("  [Haiku] Ranking candidates...")

    # Build compact candidate list for the prompt
    candidate_lines = []
    for i, c in enumerate(candidates):
        line = (
            f"{i}: [{c.get('source', '?')}] "
            f"{c.get('headline', '?')[:80]} "
            f"(age:{c.get('age_hours', '?')}h, "
            f"cat:{c.get('_category', '?')})"
        )
        candidate_lines.append(line)

    system = (
        "You are a news relevance scorer for a healthcare fintech executive. "
        "Score each candidate 0-100 based on relevance to: patient financing, "
        "healthcare affordability, RCM, health system operations, AI coding tools, "
        "enterprise AI, and major world events an executive should know. "
        "Also assign each to: tier1, ga, or skip. "
        "Return JSON array of objects with: idx, score, section, reason (5 words max)."
    )

    user = (
        f"Score these {len(candidates)} article candidates.\n"
        f"Select the best 4-6 for tier1 (deep read with So What).\n"
        f"Select 8-10 for ga (general awareness one-liners).\n"
        f"Skip the rest.\n\n"
        + "\n".join(candidate_lines)
    )

    try:
        results = client._call_json(HAIKU_MODEL, system, user, max_tokens=3000)
        # Apply scores back to candidates
        score_map = {}
        if isinstance(results, list):
            for r in results:
                score_map[r.get("idx", -1)] = r
        elif isinstance(results, dict) and "candidates" in results:
            for r in results["candidates"]:
                score_map[r.get("idx", -1)] = r

        for i, c in enumerate(candidates):
            if i in score_map:
                c["_llm_score"] = score_map[i].get("score", 0)
                c["_llm_section"] = score_map[i].get("section", "skip")
                c["_llm_reason"] = score_map[i].get("reason", "")
            else:
                c["_llm_score"] = 0
                c["_llm_section"] = "skip"

        _log(f"    Scored {len(candidates)} candidates")
        return candidates

    except Exception as e:
        _log(f"    Ranking failed: {e} — falling back to code-based scoring")
        return candidates


def summarize_article(client: LLMClient, article: dict) -> str:
    """
    Generate a 2-3 sentence summary of an article for Tier 1.

    Uses Haiku — summaries are factual extraction, not creative.
    """
    headline = article.get("headline", "")
    source = article.get("source", "")
    text = article.get("article_text", "")[:3000]

    if not text:
        return f"{headline} ({source}). [Article text not available for summarization.]"

    system = (
        "You are a news summarizer for a busy executive. "
        "Write a 2-3 sentence summary of the actual news — what happened, "
        "key numbers, and who's involved. Be factual and specific. "
        "Do NOT include opinions, implications, or 'So What' analysis. "
        "Do NOT introduce statistics or quotes not present in the text. "
        "Return only the summary text, no JSON."
    )

    user = (
        f"Headline: {headline}\n"
        f"Source: {source}\n\n"
        f"Article text:\n{text}"
    )

    try:
        return client._call(HAIKU_MODEL, system, user, max_tokens=300)
    except Exception as e:
        _log(f"    Summary failed for '{headline[:40]}': {e}")
        return f"{headline}. ({source})"


def generate_ga_oneliner(client: LLMClient, article: dict) -> dict:
    """
    Generate a GA one-liner: rewritten headline + one sentence of context.

    Uses Haiku — these are compact factual summaries.
    """
    headline = article.get("headline", "")
    source = article.get("source", "")
    text = article.get("article_text", "")[:1500]

    system = (
        "You are writing General Awareness items for an executive newsletter. "
        "Return JSON with: headline (rewritten, concise, informative, max 12 words), "
        "context (one sentence of factual context — a key number, name, or concrete detail "
        "from the article, max 20 words). "
        "Write like a wire service, not a consultant. No marketing language, no jargon like "
        "'stakeholder audiences', 'humanize', 'leverage', or 'competitive excellence'. "
        "If the story is about a person, state what happened. If it involves numbers, include them."
    )

    user = (
        f"Original headline: {headline}\n"
        f"Source: {source}\n\n"
        f"Article excerpt:\n{text[:800]}"
    )

    try:
        result = client._call_json(HAIKU_MODEL, system, user, max_tokens=200)
        ga_headline = result.get("headline", headline)
        ga_context = result.get("context", "")
        # Quality gate: if headline is meta-commentary, use original
        if _is_llm_refusal(ga_headline):
            _log(f"    GA headline unusable, using original: {headline[:40]}")
            ga_headline = headline
        if _is_llm_refusal(ga_context):
            ga_context = ""
        return {
            "headline": ga_headline,
            "context": ga_context,
        }
    except Exception as e:
        _log(f"    GA oneliner failed for '{headline[:40]}': {e}")
        return {"headline": headline, "context": ""}


# Patterns that indicate the LLM refused or hedged instead of summarizing
_LLM_REFUSAL_PATTERNS = [
    "i don't have access",
    "i cannot access",
    "i can't access",
    "i can't see",
    "i cannot see",
    "could you share",
    "could you provide",
    "i'm unable to",
    "i am unable to",
    "the article does not contain",
    "the article doesn't contain",
    "not addressed in the provided",
    "not available for summarization",
    "i don't have enough information",
    "i cannot determine",
    "i cannot provide",
    "i cannot write",
    "i cannot summarize",
    "i can't provide",
    "i can't write",
    "i can't summarize",
    "the text provided does not contain",
    "the article text is missing",
    "article text itself is missing",
    "no actual news content",
    "no actual content",
    "without the full article",
    "without the actual article",
    "if you can provide the actual",
    # Headline-specific: LLM meta-commentary instead of actual headline
    "i notice this",
    "this appears to be",
    "this seems to be",
    "rather than a",
    "here is a rewritten",
    "here's a rewritten",
    "here is the rewritten",
    "here's the rewritten",
    "rewritten headline:",
    "note:",
]


def _is_llm_refusal(text: str) -> bool:
    """Check if LLM output is a refusal/hedge rather than real content."""
    text_lower = text.lower()
    return any(p in text_lower for p in _LLM_REFUSAL_PATTERNS)


def summarize_x_post(client: LLMClient, post: dict) -> str | None:
    """
    Generate a 1-2 sentence summary for a Noteworthy X post.

    Uses Haiku — these are short factual summaries.
    Returns None if the LLM refuses or produces a bad summary.
    """
    handle = post.get("handle", "")
    topic = post.get("topic", "")

    system = (
        "You are summarizing an X/Twitter post for an AI-focused executive newsletter. "
        "The post title/snippet is all you have — summarize ONLY what it says. "
        "Write 1-2 sentences: what they said/showed and why it matters to the "
        "AI/tech community. Keep it tight. Return only the summary text. "
        "If the title is too vague to summarize, return exactly: SKIP"
    )

    user = f"Post by {handle}:\n{topic}"

    try:
        result = client._call(HAIKU_MODEL, system, user, max_tokens=150)
        if not result or result.strip() == "SKIP" or _is_llm_refusal(result):
            _log(f"    X post summary unusable for {handle} — skipping")
            return None
        return result
    except Exception as e:
        _log(f"    X post summary failed for {handle}: {e}")
        return None


def rewrite_headline(client: LLMClient, article: dict) -> str:
    """
    Rewrite a headline to be more specific and informative.

    Uses Haiku — this is a quick rewrite task.
    Falls back to the original headline if the LLM produces meta-commentary.
    """
    headline = article.get("headline", "")
    source = article.get("source", "")
    text = article.get("article_text", "")[:1000]

    system = (
        "Rewrite this news headline to be more specific and informative. "
        "Include key details (company names, numbers, actions). "
        "Max 15 words. Return ONLY the rewritten headline text — no commentary, "
        "no explanation, no notes, no quotes around it, no JSON."
    )

    user = (
        f"Original: {headline}\n"
        f"Source: {source}\n"
        f"Article excerpt: {text[:500]}"
    )

    try:
        result = client._call(HAIKU_MODEL, system, user, max_tokens=60)
        # Clean up — remove quotes if wrapped
        result = result.strip().strip('"').strip("'")
        # Quality gate: if LLM produced meta-commentary instead of a headline, use original
        if _is_llm_refusal(result) or len(result) > 120:
            _log(f"    Headline rewrite unusable, using original: {headline[:50]}")
            return headline
        return result
    except Exception as e:
        return headline


# =============================================================================
# SONNET TASKS (quality-critical)
# =============================================================================

def generate_so_what(client: LLMClient, article: dict, summary: str) -> str:
    """
    Generate a So What section for a Tier 1 story.

    Uses Sonnet — this is the quality-critical piece of the briefing.
    The prompt includes Rohan's full context and calibration examples.
    """
    headline = article.get("headline", "")
    source = article.get("source", "")
    text = article.get("article_text", "")[:3000]
    category = article.get("_category", "general")

    system = (
        "You are writing the 'So What' section for a premium executive newsletter. "
        "This is the most valuable part of each story — it translates news into "
        "strategic implications for the reader.\n\n"
        + ROHAN_CONTEXT + "\n\n"
        + SO_WHAT_EXAMPLES + "\n\n"
        "## Rules for So Whats:\n"
        "- Write in SECOND PERSON: 'you', 'your team', 'your eng partner' — NEVER 'Rohan should'\n"
        "- Be SPECIFIC: name the business implication (pipeline opportunity, competitive signal, "
        "regulatory risk, cost tailwind)\n"
        "- Be HONEST about signal strength: 'early signal, worth monitoring' vs "
        "'this directly impacts your Q2 plans'\n"
        "- NOT everything connects to PayZen. A major AI story or geopolitical event "
        "can simply be 'you should know about this' with no forced PayZen angle.\n"
        "- VARY tone and length: some 2 sentences, some 4-5, some a pointed question. "
        "Never use the same 'PayZen should position itself...' template.\n"
        "- Use **bold** for the single most important takeaway (1 per So What, max).\n"
        "- Do NOT introduce facts not in the article.\n"
        "- Return only the So What paragraph text. No labels, no JSON."
    )

    user = (
        f"Story: {headline}\n"
        f"Source: {source}\n"
        f"Category: {category}\n\n"
        f"Summary: {summary}\n\n"
        f"Full article text:\n{text}"
    )

    try:
        return client._call(SONNET_MODEL, system, user, max_tokens=400, temperature=0.4)
    except Exception as e:
        _log(f"    So What failed for '{headline[:40]}': {e}")
        return "[So What generation failed — review manually]"


def generate_today_30_seconds(
    client: LLMClient,
    stories: list[dict],
) -> list[dict]:
    """
    Generate "Today in 30 Seconds" — 3-4 bullet points from strongest stories.

    Uses Sonnet — this is the first thing the reader sees.
    """
    _log("  [Sonnet] Generating Today in 30 Seconds...")

    story_summaries = []
    for s in stories[:6]:
        story_summaries.append(
            f"- {s.get('headline', '')}: {s.get('summary', '')[:150]}"
        )

    system = (
        "You are writing 'Today in 30 Seconds' for a premium executive newsletter. "
        "Pick the 3-4 stories with the strongest, most concrete implications. "
        "Each bullet: **Bold key fact** — short implication (under 15 words). "
        "Prioritize stories where the implication is concrete and immediate. "
        "Skip stories whose main takeaway is 'monitor this'. "
        "Return JSON array of objects with: bold_fact, implication."
    )

    user = "Today's top stories:\n" + "\n".join(story_summaries)

    try:
        result = client._call_json(SONNET_MODEL, system, user, max_tokens=500)
        if isinstance(result, list):
            return result[:4]
        return result.get("items", result.get("bullets", []))[:4]
    except Exception as e:
        _log(f"    Today in 30 Seconds failed: {e}")
        # Fallback: use headlines
        return [
            {"bold_fact": s.get("headline", "")[:60], "implication": "See details below"}
            for s in stories[:3]
        ]


def quality_review(client: LLMClient, briefing: dict) -> dict:
    """
    Final quality review pass on the complete briefing.

    Uses Sonnet — catches issues the individual calls might miss.
    Returns a dict with: passed (bool), issues (list of strings), fixes (list of dicts).
    """
    _log("  [Sonnet] Running quality review...")

    # Build compact briefing summary for review
    review_text = "BRIEFING REVIEW:\n\n"
    for s in briefing.get("tier1_stories", []):
        review_text += (
            f"TIER 1: {s.get('headline', '')}\n"
            f"  Summary: {s.get('summary', '')[:100]}...\n"
            f"  So What: {s.get('so_what', '')[:150]}...\n\n"
        )
    for g in briefing.get("general_awareness", []):
        review_text += (
            f"GA: {g.get('flag', '')} {g.get('headline', '')} — "
            f"{g.get('context', '')}\n"
        )

    system = (
        "You are quality-reviewing a morning intelligence briefing for an "
        "SVP of Product at a healthcare fintech. Check for:\n"
        "1. Any So What that says 'Rohan should' instead of 'you should' (FAIL)\n"
        "2. Any So What that is generic filler ('this is relevant to healthcare') (FLAG)\n"
        "3. Duplicate stories across sections (FAIL)\n"
        "4. More than 3 items from the same source (FLAG)\n"
        "5. GA items without geographic diversity (FLAG)\n"
        "6. So Whats that all sound the same (FLAG)\n"
        "Return JSON: {passed: bool, issues: [strings], suggestions: [strings]}"
    )

    try:
        result = client._call_json(SONNET_MODEL, system, review_text, max_tokens=800)
        return result
    except Exception as e:
        _log(f"    Quality review failed: {e}")
        return {"passed": True, "issues": [], "suggestions": []}


# =============================================================================
# ORCHESTRATOR — runs all LLM tasks in sequence
# =============================================================================

def run_phase2_llm(
    tier1_articles: list[dict],
    ga_articles: list[dict],
    noteworthy_x_posts: list[dict] = None,
    local_articles: list[dict] = None,
    briefing_date: str = "",
    api_key: str = None,
    backfill_candidates: list[dict] = None,
) -> dict:
    """
    Run all Phase 2 LLM tasks and return structured JSON for template rendering.

    This is the main entry point called by run_pipeline.py.

    Args:
        tier1_articles: Top articles selected for deep reads (with article_text)
        ga_articles: Articles selected for General Awareness (with article_text)
        noteworthy_x_posts: Noteworthy X post candidates (with topic/handle)
        local_articles: Local news articles
        briefing_date: YYYY-MM-DD string
        api_key: Anthropic API key (or from env)
        backfill_candidates: Additional scored candidates to try if Tier 1
            stories are rejected during summarization (content mismatch, etc.)

    Returns:
        Structured dict ready for Jinja2 template rendering.
    """
    if noteworthy_x_posts is None:
        noteworthy_x_posts = []
    if local_articles is None:
        local_articles = []
    if backfill_candidates is None:
        backfill_candidates = []
    _log("\n" + "=" * 60)
    _log("PHASE 2: LLM Content Generation")
    _log("=" * 60)

    client = LLMClient(api_key=api_key)

    # ---- Step 1: Tier 1 — summaries + headlines (Haiku, parallel-ready) ----
    _log("\n[1/5] Generating Tier 1 summaries (Haiku)...")
    tier1_stories = []
    TIER1_TARGET = 6
    tried_urls = {a.get("url") for a in tier1_articles}

    def _try_summarize(article: dict, story_num: int) -> dict | None:
        """Attempt to summarize an article. Returns story dict or None if rejected."""
        _log(f"  Story {story_num}: {article.get('headline', '?')[:50]}...")
        new_headline = rewrite_headline(client, article)
        summary = summarize_article(client, article)
        if _is_llm_refusal(summary):
            _log(f"    REJECT story {story_num}: summary indicates content mismatch — skipping")
            return None
        return {
            "number": story_num,
            "section": article.get("_category", "health"),
            "headline": new_headline,
            "original_headline": article.get("headline", ""),
            "url": article.get("url", ""),
            "source": article.get("source", "Unknown"),
            "date_display": article.get("verified_date_display", article.get("verified_date", "")),
            "read_time_min": article.get("estimated_read_time_min", 5),
            "has_paywall": article.get("has_paywall", False),
            "summary": summary,
            "so_what": "",  # Filled in step 2
            "article_text": article.get("article_text", ""),
            "_category": article.get("_category", "general"),
        }

    # Process initial Tier 1 candidates
    story_num = 0
    for article in tier1_articles[:TIER1_TARGET]:
        story_num += 1
        result = _try_summarize(article, story_num)
        if result:
            tier1_stories.append(result)
        time.sleep(0.2)

    # Backfill: if we have fewer than target, try additional candidates
    backfill_idx = 0
    while len(tier1_stories) < TIER1_TARGET and backfill_idx < len(backfill_candidates):
        candidate = backfill_candidates[backfill_idx]
        backfill_idx += 1
        if candidate.get("url") in tried_urls:
            continue
        tried_urls.add(candidate.get("url"))
        story_num += 1
        _log(f"  [Backfill] Trying: {candidate.get('headline', '?')[:50]}...")
        result = _try_summarize(candidate, story_num)
        if result:
            tier1_stories.append(result)
        time.sleep(0.2)

    # ---- Step 2: So Whats (Sonnet — quality-critical) ----
    _log("\n[2/7] Generating So Whats (Sonnet)...")
    stories_to_remove = []
    for story in tier1_stories:
        _log(f"  So What for: {story['headline'][:50]}...")
        so_what = generate_so_what(
            client,
            {
                "headline": story["headline"],
                "source": story["source"],
                "article_text": story.get("article_text", ""),
                "_category": story.get("_category", "general"),
            },
            story["summary"],
        )

        # Quality gate: if So What failed, retry once
        if so_what.startswith("[So What generation failed"):
            _log(f"    Retrying So What for: {story['headline'][:50]}...")
            time.sleep(1)
            so_what = generate_so_what(
                client,
                {
                    "headline": story["headline"],
                    "source": story["source"],
                    "article_text": story.get("article_text", ""),
                    "_category": story.get("_category", "general"),
                },
                story["summary"],
            )

        # If still failed or is a refusal, mark for removal
        if so_what.startswith("[So What generation failed") or _is_llm_refusal(so_what):
            _log(f"    DROPPING story: So What unusable after retry — {story['headline'][:50]}")
            stories_to_remove.append(story)
        else:
            story["so_what"] = so_what
        time.sleep(0.3)

    # Remove stories with failed So Whats
    for story in stories_to_remove:
        tier1_stories.remove(story)

    # Renumber remaining stories
    for i, story in enumerate(tier1_stories, 1):
        story["number"] = i

    # Strip article_text from output (large, not needed for template)
    for story in tier1_stories:
        story.pop("article_text", None)
        story.pop("_category", None)

    # ---- Step 3: GA one-liners (Haiku) ----
    _log("\n[3/5] Generating GA one-liners (Haiku)...")
    ga_items = []
    for article in ga_articles[:10]:
        oneliner = generate_ga_oneliner(client, article)
        ga_items.append({
            "flag": article.get("_flag", "🇺🇸"),
            "headline": oneliner["headline"],
            "url": article.get("url", ""),
            "context": oneliner["context"],
            "source": article.get("source", "Unknown"),
            "date_display": article.get("verified_date_display", article.get("verified_date", "")),
            "read_time_min": article.get("estimated_read_time_min", 3),
            "has_paywall": article.get("has_paywall", False),
        })
        time.sleep(0.2)
    _log(f"    Generated {len(ga_items)} GA items")

    # ---- Step 4: Noteworthy X post summaries (Haiku) ----
    _log("\n[4/7] Generating Noteworthy X summaries (Haiku)...")
    x_post_items = []
    for post in noteworthy_x_posts[:4]:
        summary = summarize_x_post(client, post)
        if summary is None:
            continue  # Skip posts where summary was unusable
        x_post_items.append({
            "handle": post.get("handle", ""),
            "url": post.get("url", ""),
            "summary": summary,
            "age_hours": post.get("age_hours"),
            "post_time": post.get("post_time", ""),
        })
        time.sleep(0.2)
    _log(f"    Generated {len(x_post_items)} X post summaries")

    # ---- Step 5: Today in 30 Seconds (Sonnet) ----
    today_30 = generate_today_30_seconds(client, tier1_stories)

    # ---- Step 6: Local items (no LLM needed — pass through) ----
    local_items = []
    for article in local_articles[:5]:
        local_items.append({
            "headline": article.get("headline", ""),
            "url": article.get("url", ""),
            "context": "",  # Could add Haiku summary if needed
            "source": article.get("source", "Unknown"),
            "date_display": article.get("verified_date_display", article.get("verified_date", "")),
        })

    # ---- Step 7: Quality review (Sonnet) ----
    draft_briefing = {
        "tier1_stories": tier1_stories,
        "general_awareness": ga_items,
    }
    review = quality_review(client, draft_briefing)
    if not review.get("passed", True):
        _log("    Quality issues found:")
        for issue in review.get("issues", []):
            _log(f"      - {issue}")

    # ---- Build final output ----
    # Compute header stats — reading time is for the BRIEFING, not original articles
    total_reads = len(tier1_stories)
    # Estimate briefing read time: ~2 min per Tier 1 (summary + So What),
    # ~0.5 min per GA item, ~1 min for Today 30s, ~0.5 min per local item
    total_minutes = (
        len(tier1_stories) * 2
        + len(ga_items) * 0.5
        + 1  # Today in 30 Seconds
        + len(local_items) * 0.5
    )
    total_minutes = round(total_minutes)

    # Build sources list (deduplicated)
    all_sources = set()
    for s in tier1_stories:
        all_sources.add(s["source"])
    for g in ga_items:
        all_sources.add(g["source"])
    for x in x_post_items:
        handle = x.get("handle", "").lstrip("@")
        if handle:
            all_sources.add(f"X/@{handle}")

    # Format date for header
    try:
        dt = datetime.strptime(briefing_date, "%Y-%m-%d")
        date_display = dt.strftime("%A, %B %d, %Y").replace(" 0", " ")
    except ValueError:
        date_display = briefing_date

    output = {
        "header": {
            "date_display": date_display,
            "briefing_date": briefing_date,
            "deep_reads": total_reads,
            "total_minutes": total_minutes,
        },
        "today_30_seconds": today_30,
        "tier1_stories": tier1_stories,
        "noteworthy_x": x_post_items,
        "general_awareness": ga_items,
        "local": local_items,
        "ticket_watch": None,  # Populated from Phase 1 data if relevant
        "sources_list": sorted(all_sources),
        "quality_review": review,
        "cost": client.get_cost_summary(),
    }

    # Print cost summary
    cost = client.get_cost_summary()
    _log(f"\n{'=' * 60}")
    _log("PHASE 2 COMPLETE")
    _log(f"{'=' * 60}")
    _log(f"  LLM calls:    {cost['total_calls']}")
    _log(f"  Input tokens:  {cost['total_input_tokens']:,}")
    _log(f"  Output tokens: {cost['total_output_tokens']:,}")
    _log(f"  Total cost:    ${cost['total_cost_usd']:.4f}")

    return output


# =============================================================================
# CLI — for testing individual functions
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM Call Wrappers — test individual functions")
    parser.add_argument("command", choices=["so_what_prompt", "test_summary", "test_so_what", "test_ga", "cost_estimate"],
                        help="Which function to test")
    parser.add_argument("--phase1", default="output/phase1-2026-02-10.json",
                        help="Phase 1 JSON file for test data")
    args = parser.parse_args()

    if args.command == "so_what_prompt":
        # Print the full So What system prompt for review
        print("=" * 70)
        print("SO WHAT SYSTEM PROMPT")
        print("=" * 70)
        print()
        system = (
            "You are writing the 'So What' section for a premium executive newsletter. "
            "This is the most valuable part of each story — it translates news into "
            "strategic implications for the reader.\n\n"
            + ROHAN_CONTEXT + "\n\n"
            + SO_WHAT_EXAMPLES + "\n\n"
            "## Rules for So Whats:\n"
            "- Write in SECOND PERSON: 'you', 'your team', 'your eng partner' — NEVER 'Rohan should'\n"
            "- Be SPECIFIC: name the business implication (pipeline opportunity, competitive signal, "
            "regulatory risk, cost tailwind)\n"
            "- Be HONEST about signal strength: 'early signal, worth monitoring' vs "
            "'this directly impacts your Q2 plans'\n"
            "- NOT everything connects to PayZen. A major AI story or geopolitical event "
            "can simply be 'you should know about this' with no forced PayZen angle.\n"
            "- VARY tone and length: some 2 sentences, some 4-5, some a pointed question. "
            "Never use the same 'PayZen should position itself...' template.\n"
            "- Use **bold** for the single most important takeaway (1 per So What, max).\n"
            "- Do NOT introduce facts not in the article.\n"
            "- Return only the So What paragraph text. No labels, no JSON."
        )
        print(system)
        print()
        print("=" * 70)
        print(f"Prompt length: ~{len(system)} chars, ~{len(system) // 4} tokens")
        print("=" * 70)

    elif args.command == "cost_estimate":
        # Estimate cost for a typical briefing
        print("=" * 50)
        print("PHASE 2 COST ESTIMATE (typical briefing)")
        print("=" * 50)
        print()
        # Typical counts
        tier1 = 5
        ga = 10
        print(f"  Tier 1 stories: {tier1}")
        print(f"  GA items: {ga}")
        print()

        # Haiku calls
        haiku_calls = 1 + tier1 * 2 + ga  # rank + (summary + headline) * tier1 + ga
        haiku_input = (
            3000  # ranking
            + tier1 * 3500  # summaries (3000 article + 500 prompt)
            + tier1 * 1500  # headline rewrites
            + ga * 2000  # GA one-liners
        )
        haiku_output = (
            2000  # ranking
            + tier1 * 300  # summaries
            + tier1 * 60  # headlines
            + ga * 200  # GA
        )

        # Sonnet calls
        sonnet_calls = tier1 + 1 + 1  # So Whats + Today 30s + quality review
        sonnet_input = (
            tier1 * 5000  # So Whats (article + context + examples)
            + 3000  # Today in 30 Seconds
            + 4000  # Quality review
        )
        sonnet_output = (
            tier1 * 300  # So Whats
            + 400  # Today 30s
            + 500  # Quality review
        )

        haiku_cost = (
            haiku_input / 1_000_000 * HAIKU_INPUT_COST
            + haiku_output / 1_000_000 * HAIKU_OUTPUT_COST
        )
        sonnet_cost = (
            sonnet_input / 1_000_000 * SONNET_INPUT_COST
            + sonnet_output / 1_000_000 * SONNET_OUTPUT_COST
        )

        print(f"  Haiku:  {haiku_calls} calls, ~{haiku_input:,} in / ~{haiku_output:,} out = ${haiku_cost:.4f}")
        print(f"  Sonnet: {sonnet_calls} calls, ~{sonnet_input:,} in / ~{sonnet_output:,} out = ${sonnet_cost:.4f}")
        print(f"  Total:  ${haiku_cost + sonnet_cost:.4f}")
        print()
        print(f"  Phase 1 (Python): $0.00")
        print(f"  Phase 2 (LLM):    ${haiku_cost + sonnet_cost:.4f}")
        print(f"  -" * 20)
        print(f"  Total per briefing: ~${haiku_cost + sonnet_cost:.2f}")
        print(f"  Current system:     ~$77.00")
        print(f"  Savings:            ~{(1 - (haiku_cost + sonnet_cost) / 77) * 100:.0f}%")

    else:
        print(f"Command '{args.command}' requires API key and Phase 1 data.")
        print("Set ANTHROPIC_API_KEY and provide --phase1 path.")
