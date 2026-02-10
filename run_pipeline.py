"""
Morning Intelligence Pipeline Orchestrator.

Replaces Claude Code (Opus) as orchestrator. Python coordinates, LLMs are specialists.

Pipeline:
  1. COLLECT  — data_collector.py gathers candidates       ($0 LLM)
  2. VALIDATE — build Phase 1 verification tables           ($0 LLM)
  3. GENERATE — llm_calls.py creates summaries/So Whats     (Session 2)
  4. ASSEMBLE — Jinja2 renders HTML from template            (Session 3)
  5. DELIVER  — send-briefing.py emails the result           ($0 LLM)

Cost: Steps 1-2 = $0 LLM, ~2-4 minutes.
      Steps 3-5 = ~$0.50-1.50 LLM (Haiku + Sonnet), ~30 seconds.

Usage:
    python run_pipeline.py                    # Run for today
    python run_pipeline.py --date 2026-02-10  # Specific date
    python run_pipeline.py --collect-only     # Phase 1 only (validate data_collector)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from data_collector import DataCollector, build_healthcare_log, _log
from phase1_validator import (
    MAX_AGE_HOURS,
    classify_source_tier,
    validate_ga_source_tally,
)
from phase2_generator import (
    score_article,
    categorize_article,
    detect_country_flag,
)
from llm_calls import run_phase2_llm
from render_briefing import render_html

# Output directory
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


# =============================================================================
# ARTICLE CATEGORIZATION
# =============================================================================

# =============================================================================
# DEDUPLICATION & LANGUAGE DETECTION
# =============================================================================

# Stop words excluded from topic similarity comparison
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "can", "with", "from", "by", "as", "its", "it", "this", "that", "than",
    "not", "no", "so", "up", "out", "if", "about", "into", "over", "after",
    "new", "more", "also", "how", "what", "when", "who", "why", "all", "just",
    "says", "said", "report", "reports", "according", "per", "via",
    "your", "their", "our", "his", "her", "its", "you", "they", "them",
}

# Common Spanish words for language detection
_SPANISH_MARKERS = {
    "el", "la", "los", "las", "de", "del", "en", "que", "por", "para",
    "con", "una", "como", "pero", "sobre", "entre", "hasta", "desde",
    "más", "según", "también", "después", "durante", "antes",
    "impacto", "costos", "inscripciones", "conocerá", "varios", "meses",
    "trabajadores", "renuncian", "salud", "pública", "consulta", "médico",
    "atención", "primaria", "registra", "inesperadamente", "altas", "pese",
    "reducción", "subsidios", "retención", "incierta", "aumento",
}


# Local section ALLOWLIST — only these categories are valid Local content.
# If a headline matches zero patterns, it gets dropped.
_LOCAL_INCLUDE_PATTERNS = [
    # Transit / infrastructure
    "bart", "caltrain", "muni", "vta", "highway", "traffic", "road closure",
    "bridge", "transit", "commute", "680", "580", "880", "101",
    "freeway", "interchange", "rail", "amtrak",
    # Weather / air quality / natural hazards
    "spare the air", "air quality", "heat advisory", "flood warning",
    "storm", "wildfire", "evacuation", "fire warning", "pg&e", "pge",
    "power outage", "weather warning", "red flag", "wind advisory",
    "earthquake", "mudslide", "drought",
    # Local government / civic
    "city council", "board of supervisors", "school board", "school district",
    "ballot measure", "zoning", "planning commission", "town hall",
    "mayor", "supervisor", "county", "ordinance", "municipal",
    "public hearing", "budget", "tax measure",
    # Safety / public safety
    "police", "fire department", "accident", "crime", "shooting",
    "missing person", "amber alert", "arrest", "investigation",
    "highway patrol", "chp", "sheriff",
    # Community events
    "festival", "parade", "farmers market", "community meeting",
    "town meeting", "marathon", "fun run", "block party",
    # Healthcare / public health (local)
    "hospital", "kaiser", "clinic", "health department",
    "vaccination", "covid", "public health",
    # Local economy impact (layoffs, closures affecting the area)
    "layoff", "closure", "shutdown", "strike",
]

# Digest / newsletter URL patterns — multi-topic bundles that can't be summarized as one story
_DIGEST_URL_PATTERNS = [
    "up-first", "newsletter", "daily-briefing", "morning-rundown",
    "news-roundup", "5-things", "five-things", "the-daily-digest",
    "morning-edition-highlights", "evening-briefing", "daily-recap",
    "week-in-review", "news-wrap", "headlines-today",
]


# Company/brand aliases — map alternate names to canonical form
_BRAND_ALIASES = {
    "facebook": "meta", "instagram": "meta", "whatsapp": "meta",
    "google": "alphabet", "youtube": "alphabet", "deepmind": "alphabet",
    "chatgpt": "openai", "gpt": "openai", "dall-e": "openai", "dalle": "openai",
    "claude": "anthropic",
    "bing": "microsoft", "github": "microsoft", "copilot": "microsoft",
    "alexa": "amazon", "aws": "amazon",
}


def _normalize_words(headline: str) -> set[str]:
    """Extract significant words from a headline for comparison.

    Applies: lowercasing, stop word removal, simple plural stripping,
    and brand alias normalization.
    """
    words = re.findall(r'[a-z0-9]+', headline.lower())
    normalized = set()
    for w in words:
        if w in _STOP_WORDS or len(w) <= 2:
            continue
        # Verb form / suffix stripping (order matters — most specific first)
        if w.endswith("ated") and len(w) > 5:
            w = w[:-1]  # "animated" → "animate"
        elif w.endswith("ied") and len(w) > 4:
            w = w[:-3] + "y"  # "applied" → "apply"
        elif w.endswith("ing") and len(w) > 5:
            w = w[:-3]  # "funding" → "fund"
        elif w.endswith("ed") and len(w) > 4:
            w = w[:-2]  # "launched" → "launch"
        elif w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("es") and len(w) > 4:
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        # Brand alias normalization
        w = _BRAND_ALIASES.get(w, w)
        normalized.add(w)
    return normalized


def _is_duplicate_topic(headline_a: str, headline_b: str) -> bool:
    """Check if two headlines are about the same topic using word overlap.

    Uses two complementary checks:
    1. Jaccard similarity >= 0.40 (overall word overlap)
    2. Coverage check: >= 55% of the shorter headline's words appear in the
       longer one AND at least 3 shared words (catches differently-phrased
       headlines about the same story, e.g. "OpenAI introduces ads in ChatGPT"
       vs "OpenAI tests ChatGPT ads for free users")
    """
    words_a = _normalize_words(headline_a)
    words_b = _normalize_words(headline_b)
    if not words_a or not words_b:
        return False
    intersection = words_a & words_b
    union = words_a | words_b

    # Check 1: Jaccard similarity
    if len(intersection) / len(union) >= 0.40:
        return True

    # Check 2: Coverage of shorter headline
    shorter = min(len(words_a), len(words_b))
    if len(intersection) >= 3 and len(intersection) / shorter >= 0.55:
        return True

    return False


def _is_non_english(article: dict) -> bool:
    """Detect if an article is in a non-English language.

    Uses headline word analysis — if >30% of words match Spanish markers
    or the URL path contains known non-English segments.
    """
    headline = article.get("headline", "")
    url = article.get("url", "")

    # URL-based detection
    if any(seg in url for seg in ["/es/", "/spanish/", "/espanol/"]):
        return True

    # Headline word analysis
    words = re.findall(r'[a-záéíóúñü]+', headline.lower())
    if len(words) < 3:
        return False
    spanish_count = sum(1 for w in words if w in _SPANISH_MARKERS)
    return spanish_count / len(words) > 0.30


def _deduplicate_articles(articles: list[dict]) -> list[dict]:
    """Remove duplicate-topic articles, keeping the first (highest-scored) one."""
    kept = []
    for article in articles:
        headline = article.get("headline", "")
        is_dup = False
        for existing in kept:
            if _is_duplicate_topic(headline, existing.get("headline", "")):
                is_dup = True
                break
        if not is_dup:
            kept.append(article)
    return kept


def categorize_validated_articles(valid_articles: list[dict]) -> dict:
    """
    Categorize valid articles into sections for the briefing.

    Uses code-based scoring from phase2_generator.py:
    - PayZen relevance score → Tier 1 candidates (top N)
    - Section category (health/tech/business) → section assignment
    - Source tier → GA eligibility
    - Country flag detection → GA flag

    Enforces:
    - Topic deduplication (same story from different sources → keep highest-tier)
    - Section diversity (at least 1 tech story if available)
    - Language filter (skip non-English articles)
    - Source diversity (max 2 per source in Tier 1, max 3 in GA)

    Returns dict with tier1_candidates, ga_candidates, local_candidates.
    """
    tier1_candidates = []
    ga_candidates = []
    local_candidates = []

    for article in valid_articles:
        # Skip articles with no headline
        if not article.get("headline"):
            continue

        # Skip newsletter digests (multi-topic URLs that can't be cleanly summarized)
        url_path = article.get("url", "").lower()
        if any(pat in url_path for pat in _DIGEST_URL_PATTERNS):
            continue

        # Local articles go to Local section (allowlist filter)
        if article.get("is_local", False):
            headline_lower = article.get("headline", "").lower()
            if any(pat in headline_lower for pat in _LOCAL_INCLUDE_PATTERNS):
                local_candidates.append(article)
            # If no allowlist pattern matches, article is silently dropped
            continue

        # Skip non-English articles
        if _is_non_english(article):
            continue

        # Score and categorize
        article["_score"] = score_article(article)
        article["_category"] = categorize_article(article)
        # Check headline + source for country detection (source helps for BBC World, Al Jazeera, etc.)
        flag_text = article.get("headline", "") + " " + article.get("source", "")
        article["_flag"] = detect_country_flag(flag_text)

        # Classify source tier for GA eligibility
        tier_info = classify_source_tier(
            article.get("source", "Unknown"),
            article.get("url", ""),
        )
        article["_tier"] = tier_info["tier"]
        article["_ga_eligible"] = tier_info["ga_eligible"]

    # Separate local articles, then sort remainder by score
    non_local = [a for a in valid_articles
                 if not a.get("is_local", False)
                 and a.get("headline")
                 and not _is_non_english(a)]
    non_local.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # Deduplicate by topic (keep highest-scored version)
    non_local = _deduplicate_articles(non_local)

    # ---- Tier 1 selection with section diversity ----
    # First pass: collect top candidates with source diversity (max 2 per source)
    initial_tier1 = []
    source_counts = {}
    for article in non_local:
        source = article.get("source", "Unknown")
        if source_counts.get(source, 0) < 2:
            initial_tier1.append(article)
            source_counts[source] = source_counts.get(source, 0) + 1
            if len(initial_tier1) >= 12:  # Collect a few extra for diversity swap
                break

    # Second pass: enforce section diversity — at least 1 tech and 1 business if available
    health_picks = [a for a in initial_tier1 if a.get("_category") == "health"]
    tech_picks = [a for a in initial_tier1 if a.get("_category") == "tech"]
    biz_picks = [a for a in initial_tier1 if a.get("_category") == "business"]

    # If no tech in top picks, find the best tech article in the full pool
    if not tech_picks:
        for article in non_local:
            if article.get("_category") == "tech" and article not in initial_tier1:
                tech_picks.append(article)
                break
        # Also check if any tech articles are already in initial_tier1 but miscategorized
        # If we found one, add it and we'll trim later
        if tech_picks:
            initial_tier1.append(tech_picks[0])

    if not biz_picks:
        for article in non_local:
            if article.get("_category") == "business" and article not in initial_tier1:
                biz_picks.append(article)
                break
        if biz_picks:
            initial_tier1.append(biz_picks[0])

    # Trim to 6 Tier 1 slots, prioritizing diversity:
    # Reserve 1 slot each for tech and business (if available), fill rest by score
    tier1_candidates = []
    used_urls = set()
    # Add best tech pick first (guaranteed slot)
    if tech_picks:
        best_tech = tech_picks[0]
        tier1_candidates.append(best_tech)
        used_urls.add(best_tech.get("url"))

    # Add best business pick (guaranteed slot)
    if biz_picks:
        best_biz = biz_picks[0]
        if best_biz.get("url") not in used_urls:
            tier1_candidates.append(best_biz)
            used_urls.add(best_biz.get("url"))

    # Fill remaining slots from initial_tier1 by score
    for article in initial_tier1:
        if len(tier1_candidates) >= 6:
            break
        if article.get("url") not in used_urls:
            tier1_candidates.append(article)
            used_urls.add(article.get("url"))

    # Sort final Tier 1 by category order: health → tech → business
    cat_order = {"health": 0, "tech": 1, "business": 2}
    tier1_candidates.sort(key=lambda a: (cat_order.get(a.get("_category", "business"), 2), -a.get("_score", 0)))

    # ---- GA candidates (remaining articles, GA-eligible, deduplicated) ----
    tier1_urls = {a["url"] for a in tier1_candidates}
    ga_source_counts = {}
    ga_pool = []
    for article in non_local:
        if article["url"] not in tier1_urls:
            if article.get("_ga_eligible", False):
                source = article.get("source", "Unknown")
                if ga_source_counts.get(source, 0) < 3:
                    ga_pool.append(article)
                    ga_source_counts[source] = ga_source_counts.get(source, 0) + 1

    # Deduplicate GA against each other AND against Tier 1 headlines
    ga_deduped = []
    for article in ga_pool:
        headline = article.get("headline", "")
        is_dup = False
        # Check against Tier 1
        for t1 in tier1_candidates:
            if _is_duplicate_topic(headline, t1.get("headline", "")):
                is_dup = True
                break
        # Check against already-selected GA
        if not is_dup:
            for existing in ga_deduped:
                if _is_duplicate_topic(headline, existing.get("headline", "")):
                    is_dup = True
                    break
        if not is_dup:
            ga_deduped.append(article)

    # Enforce geographic diversity: US ≤ 4 (spec requirement)
    # Strategy: pick top 10 by score, then swap out lowest US if US > 4
    US_FLAG = "🇺🇸"
    GA_US_CAP = 4
    GA_TARGET = 10

    # Start with top candidates by score
    ga_top = ga_deduped[:GA_TARGET]
    us_in_top = [a for a in ga_top if a.get("_flag", US_FLAG) == US_FLAG]
    intl_in_top = [a for a in ga_top if a.get("_flag", US_FLAG) != US_FLAG]

    if len(us_in_top) > GA_US_CAP:
        # Too many US — find international replacements from the remaining pool
        intl_remaining = [
            a for a in ga_deduped[GA_TARGET:]
            if a.get("_flag", US_FLAG) != US_FLAG
        ]
        # Keep top GA_US_CAP US items (by score, they're already sorted)
        us_keep = us_in_top[:GA_US_CAP]
        us_drop = us_in_top[GA_US_CAP:]
        # Replace dropped US with international if available
        replacements = intl_remaining[:len(us_drop)]
        ga_candidates = intl_in_top + us_keep + replacements
    else:
        ga_candidates = ga_top

    # Final sort by score
    ga_candidates.sort(key=lambda x: x.get("_score", 0), reverse=True)

    return {
        "tier1_candidates": tier1_candidates,
        "ga_candidates": ga_candidates,
        "local_candidates": local_candidates,
    }


# =============================================================================
# PHASE 1 JSON BUILDER
# =============================================================================

def build_phase1_json(
    categorized: dict,
    raw_results: dict,
    briefing_date: str,
) -> dict:
    """
    Build the Phase 1 JSON output with all 5 mandatory verification tables.

    This matches the format of existing phase1-YYYY-MM-DD.json files.
    """
    delivery_time = raw_results["delivery_time"]
    all_valid = raw_results["valid_articles"]
    all_stale = raw_results["stale_articles"]
    all_unverified = raw_results["unverified_articles"]
    all_error = raw_results["error_articles"]
    all_articles = all_valid + all_stale + all_unverified + all_error

    # ---- Table 1: Age Verification Table ----
    age_table = []
    for idx, article in enumerate(all_articles, 1):
        section = _determine_section(article, categorized)
        age_table.append({
            "id": idx,
            "headline": article.get("headline", "Unknown"),
            "source": article.get("source", "Unknown"),
            "url": article.get("url", ""),
            "verified_date": article.get("verified_date"),
            "today": briefing_date,
            "age_hours": article.get("age_hours"),
            "verdict": article.get("verdict", "REJECT"),
            "section": section,
            "date_method": article.get("date_method", "unknown"),
            "read_time_min": article.get("estimated_read_time_min"),
        })

    # ---- Table 2: From X Status ID Table ----
    from_x_table = raw_results["from_x"]["candidates"]

    # ---- Table 3: From X Handle Sweep Report ----
    from_x_sweep = raw_results["from_x"]["handle_sweep_report"]

    # ---- Table 4: GA Source Tally ----
    ga_candidates = categorized["ga_candidates"]
    ga_items_for_tally = [
        {"source": a.get("source", "Unknown"), "url": a.get("url", "")}
        for a in ga_candidates[:10]  # Top 10 GA candidates
    ]
    ga_tally = _build_ga_tally(ga_items_for_tally)

    # ---- Table 5: Healthcare Candidate Log ----
    healthcare_log = build_healthcare_log(all_articles)

    # ---- URL Verification Log ----
    url_log = _build_url_verification_log(all_articles, from_x_table)

    # ---- Ticket Watch ----
    ticket_watch = raw_results["ticket_watch"]

    return {
        "generated_at": delivery_time,
        "briefing_date": briefing_date,
        "max_age_hours": MAX_AGE_HOURS,
        "delivery_time": delivery_time,
        "summary": {
            "total_candidates": len(all_articles),
            "valid": len(all_valid),
            "stale_rejected": len(all_stale),
            "unverified_rejected": len(all_unverified),
            "error": len(all_error),
            "from_x_candidates": len(from_x_table),
            "tier1_candidates": len(categorized["tier1_candidates"]),
            "ga_candidates": len(ga_candidates),
            "local_candidates": len(categorized["local_candidates"]),
        },
        "age_verification_table": age_table,
        "from_x_status_id_table": from_x_table,
        "from_x_handle_sweep_report": from_x_sweep,
        "ga_source_tally": ga_tally,
        "healthcare_candidate_log": healthcare_log,
        "url_verification_log": url_log,
        "ticket_watch": ticket_watch,
    }


def _determine_section(article: dict, categorized: dict) -> str:
    """Determine which section an article belongs to."""
    url = article.get("url", "")
    if article.get("is_local", False):
        return "Local"
    for a in categorized.get("tier1_candidates", []):
        if a.get("url") == url:
            return "Tier 1"
    for a in categorized.get("ga_candidates", []):
        if a.get("url") == url:
            return "GA"
    # Default based on verdict
    if article.get("verdict") == "REJECT":
        return f"{article.get('_category', 'unknown')} candidate (rejected)"
    return "Uncategorized"


def _build_ga_tally(ga_items: list[dict]) -> dict:
    """Build GA source tally using phase1_validator."""
    if not ga_items:
        return {"passed": True, "sources": {}, "note": "No GA items yet"}

    # Run the validator
    tally_result = validate_ga_source_tally(ga_items)

    # Enrich with tier info
    sources_with_tier = {}
    for item in ga_items:
        source = item.get("source", "Unknown")
        if source not in sources_with_tier:
            tier_info = classify_source_tier(source, item.get("url", ""))
            sources_with_tier[source] = {
                "count": 0,
                "tier": tier_info["tier"],
                "tier_label": tier_info["tier_label"],
                "ga_eligible": tier_info["ga_eligible"],
            }
        sources_with_tier[source]["count"] += 1

    return {
        "passed": tally_result["passed"],
        "sources": sources_with_tier,
        "max_source_count": tally_result["max_source_count"],
        "max_source_name": tally_result.get("max_source_name", ""),
        "issues": tally_result["issues"],
    }


def _build_url_verification_log(articles: list[dict], from_x: list[dict]) -> list[dict]:
    """Build URL verification log for all URLs."""
    log = []
    seen = set()

    for article in articles:
        url = article.get("url", "")
        if url and url not in seen:
            seen.add(url)
            verdict = article.get("verdict", "REJECT")
            has_error = "error" in article
            log.append({
                "url": url[:80],
                "section": "Article",
                "fetch_status": "error" if has_error else "200 OK",
                "verdict": verdict,
            })

    for post in from_x:
        url = post.get("url", "")
        if url and url not in seen:
            seen.add(url)
            log.append({
                "url": url[:80],
                "section": "From X",
                "fetch_status": "200 OK (search result)",
                "verdict": post.get("verdict", "PASS"),
            })

    return log


# =============================================================================
# PIPELINE RUNNER
# =============================================================================

def run_pipeline(
    briefing_date: str = None,
    output_dir: str = OUTPUT_DIR,
    collect_only: bool = False,
    max_workers: int = 8,
) -> dict:
    """
    Run the full Morning Intelligence pipeline.

    Args:
        briefing_date: Date string (YYYY-MM-DD). Defaults to today.
        output_dir: Where to save phase1 JSON and briefing HTML.
        collect_only: If True, stop after Phase 1 (data validation).
        max_workers: Concurrent article fetch threads.

    Returns:
        Dict with phase1_json and (eventually) briefing_html path.
    """
    if not briefing_date:
        briefing_date = datetime.now().strftime("%Y-%m-%d")

    _log(f"\n{'=' * 60}")
    _log(f"MORNING INTELLIGENCE PIPELINE — {briefing_date}")
    _log(f"{'=' * 60}\n")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # ---- Phase 1: COLLECT + VALIDATE ----
    _log("PHASE 1: Collect and Validate")
    _log("-" * 40)

    collector = DataCollector(max_workers=max_workers)
    raw_results = collector.collect_all()

    # Categorize articles
    _log("\nCategorizing articles...")
    categorized = categorize_validated_articles(raw_results["valid_articles"])
    _log(f"  Tier 1 candidates: {len(categorized['tier1_candidates'])}")
    _log(f"  GA candidates:     {len(categorized['ga_candidates'])}")
    _log(f"  Local candidates:  {len(categorized['local_candidates'])}")

    # Build Phase 1 JSON
    _log("\nBuilding Phase 1 verification tables...")
    phase1 = build_phase1_json(categorized, raw_results, briefing_date)

    # Check GA tally gate
    ga_tally = phase1["ga_source_tally"]
    if ga_tally.get("passed"):
        _log("  GA Source Tally: PASSED ✓")
    else:
        _log("  GA Source Tally: FAILED ✗")
        for issue in ga_tally.get("issues", []):
            _log(f"    - {issue}")

    # Check healthcare sweep
    healthcare_log = phase1["healthcare_candidate_log"]
    hc_pass = sum(1 for h in healthcare_log if h.get("verdict") == "PASS")
    _log(f"  Healthcare sweep: {hc_pass}/{len(healthcare_log)} sources with fresh articles")

    # Save Phase 1 JSON (without article_text to keep file small)
    phase1_path = os.path.join(output_dir, f"phase1-{briefing_date}.json")
    phase1_clean = _strip_article_text(phase1)
    with open(phase1_path, "w", encoding="utf-8") as f:
        json.dump(phase1_clean, f, indent=2, ensure_ascii=False, default=str)
    _log(f"\n  Phase 1 JSON saved: {phase1_path}")

    # Print Phase 1 summary
    _log(f"\n{'=' * 60}")
    _log("PHASE 1 COMPLETE")
    _log(f"{'=' * 60}")
    summary = phase1["summary"]
    _log(f"  Total candidates:    {summary['total_candidates']}")
    _log(f"  Valid (≤{MAX_AGE_HOURS}h):       {summary['valid']}")
    _log(f"  Stale (rejected):    {summary['stale_rejected']}")
    _log(f"  Unverified (rejected): {summary['unverified_rejected']}")
    _log(f"  Errors:              {summary['error']}")
    _log(f"  From X candidates:   {summary['from_x_candidates']}")
    _log(f"  Tier 1 candidates:   {summary['tier1_candidates']}")
    _log(f"  GA candidates:       {summary['ga_candidates']}")
    _log(f"  Local candidates:    {summary['local_candidates']}")

    if collect_only:
        _log("\n  --collect-only: stopping after Phase 1.")
        return {"phase1_json": phase1_path, "phase1_data": phase1}

    # ---- Phase 2: GENERATE (llm_calls.py) ----
    tier1 = categorized["tier1_candidates"]
    ga = categorized["ga_candidates"][:10]
    local = categorized["local_candidates"]
    from_x = raw_results["from_x"]["candidates"]

    briefing_data = run_phase2_llm(
        tier1_articles=tier1,
        ga_articles=ga,
        from_x_posts=from_x,
        local_articles=local,
        briefing_date=briefing_date,
    )

    # Inject ticket watch from Phase 1
    briefing_data["ticket_watch"] = raw_results.get("ticket_watch")

    # ---- Phase 3: ASSEMBLE (render_briefing.py) ----
    _log(f"\n{'=' * 60}")
    _log("PHASE 3: Assemble HTML")
    _log(f"{'=' * 60}")

    html_output = render_html(briefing_data)
    briefing_path = os.path.join(output_dir, f"briefing-{briefing_date}.html")
    with open(briefing_path, "w", encoding="utf-8") as f:
        f.write(html_output)
    _log(f"  Briefing HTML saved: {briefing_path}")
    _log(f"  File size: {len(html_output):,} bytes")

    # Save Phase 2 JSON output (for debugging / auditing)
    phase2_path = os.path.join(output_dir, f"phase2-{briefing_date}.json")
    phase2_clean = {k: v for k, v in briefing_data.items() if k != "quality_review"}
    with open(phase2_path, "w", encoding="utf-8") as f:
        json.dump(phase2_clean, f, indent=2, ensure_ascii=False, default=str)
    _log(f"  Phase 2 JSON saved: {phase2_path}")

    # ---- Final summary ----
    cost = briefing_data.get("cost", {})
    _log(f"\n{'=' * 60}")
    _log("PIPELINE COMPLETE")
    _log(f"{'=' * 60}")
    _log(f"  Phase 1 JSON: {phase1_path}")
    _log(f"  Phase 2 JSON: {phase2_path}")
    _log(f"  Briefing HTML: {briefing_path}")
    _log(f"  LLM cost: ${cost.get('total_cost_usd', 0):.4f}")
    _log(f"  LLM calls: {cost.get('total_calls', 0)}")

    return {
        "phase1_json": phase1_path,
        "phase2_json": phase2_path,
        "briefing_html": briefing_path,
        "phase1_data": phase1,
        "briefing_data": briefing_data,
    }


def _strip_article_text(phase1: dict) -> dict:
    """Remove article_text from Phase 1 JSON to keep file size small.
    Article text is kept in memory for Phase 2 but not persisted."""
    # Deep copy the age verification table without article_text
    clean = {**phase1}
    if "age_verification_table" in clean:
        clean["age_verification_table"] = [
            {k: v for k, v in entry.items() if k != "article_text"}
            for entry in clean["age_verification_table"]
        ]
    return clean


# =============================================================================
# COST ESTIMATOR
# =============================================================================

def estimate_phase2_cost(articles_for_llm: dict) -> dict:
    """
    Estimate the LLM cost for Phase 2 content generation.

    This is informational — helps validate the $2-3 target.
    """
    tier1_count = len(articles_for_llm.get("tier1", []))
    ga_count = len(articles_for_llm.get("ga", []))
    from_x_count = len(articles_for_llm.get("from_x", []))

    # Haiku 4.5 pricing: $0.80/1M input, $4/1M output
    # Sonnet 4.5 pricing: $3/1M input, $15/1M output
    haiku_input_per_m = 0.80
    haiku_output_per_m = 4.00
    sonnet_input_per_m = 3.00
    sonnet_output_per_m = 15.00

    # Estimate tokens per task
    estimates = {
        "relevance_scoring": {
            "model": "haiku",
            "input_tokens": tier1_count * 500 + ga_count * 300,
            "output_tokens": (tier1_count + ga_count) * 50,
        },
        "tier1_summaries": {
            "model": "haiku",
            "input_tokens": tier1_count * 3000,  # article text
            "output_tokens": tier1_count * 200,
        },
        "ga_one_liners": {
            "model": "haiku",
            "input_tokens": ga_count * 500,
            "output_tokens": ga_count * 50,
        },
        "from_x_summaries": {
            "model": "haiku",
            "input_tokens": from_x_count * 300,
            "output_tokens": from_x_count * 80,
        },
        "so_whats": {
            "model": "sonnet",
            "input_tokens": tier1_count * 4000,  # article + PayZen context + examples
            "output_tokens": tier1_count * 300,
        },
        "today_30_seconds": {
            "model": "sonnet",
            "input_tokens": 3000,
            "output_tokens": 300,
        },
        "quality_review": {
            "model": "sonnet",
            "input_tokens": 5000,
            "output_tokens": 500,
        },
    }

    total_cost = 0
    for task, est in estimates.items():
        if est["model"] == "haiku":
            cost = (
                est["input_tokens"] / 1_000_000 * haiku_input_per_m
                + est["output_tokens"] / 1_000_000 * haiku_output_per_m
            )
        else:
            cost = (
                est["input_tokens"] / 1_000_000 * sonnet_input_per_m
                + est["output_tokens"] / 1_000_000 * sonnet_output_per_m
            )
        estimates[task]["estimated_cost"] = round(cost, 4)
        total_cost += cost

    return {
        "total_estimated_cost": round(total_cost, 2),
        "breakdown": estimates,
        "note": "Actual cost depends on prompt length and response quality.",
    }


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Morning Intelligence Pipeline — Python orchestrator"
    )
    parser.add_argument(
        "-d", "--date",
        help="Briefing date (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Run Phase 1 only (collect + validate). Skip Phase 2/3.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent article fetch threads (default: 8)",
    )
    parser.add_argument(
        "--estimate-cost",
        action="store_true",
        help="Print estimated Phase 2 LLM cost after Phase 1.",
    )

    args = parser.parse_args()

    result = run_pipeline(
        briefing_date=args.date,
        output_dir=args.output_dir,
        collect_only=args.collect_only,
        max_workers=args.workers,
    )

    # Print cost estimate if requested (collect-only mode)
    if args.estimate_cost and "phase1_data" in result:
        categorized_for_est = categorize_validated_articles(
            result["phase1_data"].get("age_verification_table", [])
        ) if "articles_for_llm" not in result else None
        # Use simple estimate
        articles_for_llm = {
            "tier1": [{}] * result["phase1_data"]["summary"]["tier1_candidates"],
            "ga": [{}] * result["phase1_data"]["summary"]["ga_candidates"],
            "from_x": [{}] * result["phase1_data"]["summary"]["from_x_candidates"],
        }
        cost = estimate_phase2_cost(articles_for_llm)
        print(f"\n{'=' * 60}")
        print("ESTIMATED PHASE 2 COST")
        print(f"{'=' * 60}")
        print(f"  Total: ${cost['total_estimated_cost']}")
        for task, est in cost["breakdown"].items():
            print(f"  {task}: ${est['estimated_cost']} ({est['model']})")
        print(f"\n  Current system: ~$77")
        print(f"  Target: $2-3 (Phase 1: $0 + Phase 2: ${cost['total_estimated_cost']})")
