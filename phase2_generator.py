"""
Phase 2: Briefing Generator for Morning Intelligence Briefing

This script reads validated candidates from Phase 1 and generates the HTML briefing.
It uses Claude API for content generation (summaries, So Whats, rankings).

The script:
1. Reads validated_candidates.json from Phase 1
2. Ranks articles by signal strength for PayZen relevance
3. Selects top 5-8 for Tier 1, remainder for General Awareness
4. Generates summaries and "So What" sections via Claude API
5. Renders HTML email using the v4 template

CRITICAL: This script uses verified_date_display from Phase 1. It NEVER generates dates.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

# Check for optional Anthropic SDK
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    print("Warning: anthropic package not installed. Install with: pip install anthropic", file=sys.stderr)

# Configuration
MODEL = "claude-sonnet-4-20250514"
MAX_TIER1_STORIES = 10
MIN_TIER1_STORIES = 5
MAX_GA_ITEMS = 10
MIN_GA_ITEMS = 5

# Section targets (v8 spec)
HEALTH_TECH_TARGET = (3, 6)  # 3-6 stories
TECH_AI_TARGET = (2, 4)      # 2-4 stories, must be concrete developments
BUSINESS_TARGET = (0, 2)     # optional, 0-2 stories

# PayZen relevance keywords for scoring
PAYZEN_KEYWORDS = {
    "high": [
        # PayZen core business
        "patient financing", "payment plan", "patient payment", "self-pay",
        "out-of-pocket", "healthcare affordability", "medical debt", "revenue cycle",
        "rcm", "patient collections", "bad debt", "financial assistance",
        "medicaid eligibility", "cedar", "flywire", "payzen", "care card",
        "health system financial", "provider revenue", "telehealth reimbursement",
    ],
    "medium": [
        # AI companies & products (SVP Product must track these)
        "openai", "anthropic", "claude", "chatgpt", "gpt-4", "gpt-5",
        "gemini", "deepmind", "nvidia", "meta ai", "mistral",
        # AI industry signals
        "ai coding", "claude code", "codex", "cursor", "ai agent", "enterprise ai",
        "ai-native", "coding assistant", "developer tools", "ai adoption",
        # Healthcare systems
        "health system", "hospital", "cleveland clinic", "banner health",
        "geisinger", "sutter health", "optum", "unitedhealth", "cms",
        "medicare", "medicaid", "aca", "affordable care act",
    ],
    "low": [
        "healthcare", "fintech", "startup", "series", "funding",
        "artificial intelligence", "machine learning", "automation",
        "valuation", "billion", "investment",
    ],
    # Market impact signals — major financial events relevant to any executive
    "market": [
        "market crash", "stock crash", "market selloff", "sell-off",
        "recession", "bear market", "market correction", "downturn",
        "nasdaq plunge", "dow plunge", "s&p plunge", "market plunge",
        "fed rate", "rate hike", "rate cut", "interest rate",
        "unemployment spike", "job losses", "mass layoff",
        "bank failure", "banking crisis", "liquidity crisis",
        "tariff", "tariffs", "trade war", "economic shock",
        "ipo", "market cap", "trillion",
        "bubble", "overvalued", "market warning",
        "market decoupled", "economy decoupled",
        "analyst warns", "economist warns", "economist criticizes",
        # Broad business/finance terms (added 2026-02-26)
        "economy", "gdp", "inflation", "earnings", " layoffs",
        "stocks", "deficit", "government shutdown",
        "imf", "fed ", "trade deal", "trade policy",
        "trade strategy", "trade deficit", "trade talks", "job cuts",
        "jobs report", "labor market", "debt ceiling",
        "fiscal", "treasury", "central bank",
    ],
    # Geopolitical signals — international events an executive should track
    "geopolitical": [
        "sanctions", "nato", "opec",
        "g7 ", "g20 ", "united nations", "diplomacy", "embassy",
        "ceasefire", "peace deal", "arms deal", "nuclear talks",
        "nuclear deal", "territorial", "sovereignty",
    ],
}

# Country flag mapping for General Awareness
COUNTRY_FLAGS = {
    "us": "🇺🇸", "usa": "🇺🇸", "united states": "🇺🇸", "america": "🇺🇸",
    "uk": "🇬🇧", "britain": "🇬🇧", "england": "🇬🇧", "united kingdom": "🇬🇧",
    "china": "🇨🇳", "chinese": "🇨🇳", "beijing": "🇨🇳",
    "russia": "🇷🇺", "russian": "🇷🇺", "moscow": "🇷🇺", "putin": "🇷🇺",
    "ukraine": "🇺🇦", "ukrainian": "🇺🇦", "kyiv": "🇺🇦",
    "israel": "🇮🇱", "israeli": "🇮🇱", "gaza": "🇮🇱", "hamas": "🇮🇱",
    "palestine": "🇵🇸", "palestinian": "🇵🇸",
    "iran": "🇮🇷", "iranian": "🇮🇷", "tehran": "🇮🇷",
    "india": "🇮🇳", "indian": "🇮🇳", "delhi": "🇮🇳", "mumbai": "🇮🇳",
    "japan": "🇯🇵", "japanese": "🇯🇵", "tokyo": "🇯🇵",
    "korea": "🇰🇷", "korean": "🇰🇷", "seoul": "🇰🇷",
    "north korea": "🇰🇵", "pyongyang": "🇰🇵",
    "germany": "🇩🇪", "german": "🇩🇪", "berlin": "🇩🇪",
    "france": "🇫🇷", "french": "🇫🇷", "paris": "🇫🇷",
    "italy": "🇮🇹", "italian": "🇮🇹", "rome": "🇮🇹", "milan": "🇮🇹", "cortina": "🇮🇹",
    "spain": "🇪🇸", "spanish": "🇪🇸", "madrid": "🇪🇸",
    "brazil": "🇧🇷", "brazilian": "🇧🇷",
    "mexico": "🇲🇽", "mexican": "🇲🇽",
    "canada": "🇨🇦", "canadian": "🇨🇦", "ottawa": "🇨🇦", "toronto": "🇨🇦",
    "australia": "🇦🇺", "australian": "🇦🇺", "sydney": "🇦🇺",
    "saudi": "🇸🇦", "saudi arabia": "🇸🇦", "riyadh": "🇸🇦",
    "turkey": "🇹🇷", "turkish": "🇹🇷", "ankara": "🇹🇷", "erdogan": "🇹🇷",
    "pakistan": "🇵🇰", "pakistani": "🇵🇰",
    "afghanistan": "🇦🇫", "afghan": "🇦🇫", "kabul": "🇦🇫", "taliban": "🇦🇫",
    "syria": "🇸🇾", "syrian": "🇸🇾", "damascus": "🇸🇾",
    "iraq": "🇮🇶", "iraqi": "🇮🇶", "baghdad": "🇮🇶",
    "egypt": "🇪🇬", "egyptian": "🇪🇬", "cairo": "🇪🇬",
    "south africa": "🇿🇦",
    "nigeria": "🇳🇬", "nigerian": "🇳🇬", "lagos": "🇳🇬",
    "kenya": "🇰🇪", "kenyan": "🇰🇪", "nairobi": "🇰🇪",
    "ethiopia": "🇪🇹", "ethiopian": "🇪🇹",
    "zimbabwe": "🇿🇼", "harare": "🇿🇼",
    "somalia": "🇸🇴", "somali": "🇸🇴", "mogadishu": "🇸🇴",
    "lebanon": "🇱🇧", "lebanese": "🇱🇧", "beirut": "🇱🇧",
    "bangladesh": "🇧🇩", "bangladeshi": "🇧🇩", "dhaka": "🇧🇩",
    "myanmar": "🇲🇲", "burmese": "🇲🇲",
    "vietnam": "🇻🇳", "vietnamese": "🇻🇳", "hanoi": "🇻🇳",
    "indonesia": "🇮🇩", "indonesian": "🇮🇩", "jakarta": "🇮🇩",
    "philippines": "🇵🇭", "philippine": "🇵🇭", "manila": "🇵🇭",
    "thailand": "🇹🇭", "thai": "🇹🇭", "bangkok": "🇹🇭",
    "singapore": "🇸🇬",
    "malaysia": "🇲🇾", "malaysian": "🇲🇾", "kuala lumpur": "🇲🇾",
    "colombia": "🇨🇴", "colombian": "🇨🇴", "bogota": "🇨🇴",
    "argentina": "🇦🇷", "argentine": "🇦🇷", "buenos aires": "🇦🇷",
    "chile": "🇨🇱", "chilean": "🇨🇱", "santiago": "🇨🇱",
    "peru": "🇵🇪", "peruvian": "🇵🇪", "lima": "🇵🇪",
    "morocco": "🇲🇦", "moroccan": "🇲🇦",
    "tunisia": "🇹🇳", "tunisian": "🇹🇳",
    "algeria": "🇩🇿", "algerian": "🇩🇿",
    "ghana": "🇬🇭", "ghanaian": "🇬🇭",
    "tanzania": "🇹🇿", "tanzanian": "🇹🇿",
    "congo": "🇨🇩",
    "sudan": "🇸🇩", "sudanese": "🇸🇩", "khartoum": "🇸🇩",
    "libya": "🇱🇾", "libyan": "🇱🇾", "tripoli": "🇱🇾",
    "jordan": "🇯🇴", "jordanian": "🇯🇴", "amman": "🇯🇴",
    "qatar": "🇶🇦", "qatari": "🇶🇦", "doha": "🇶🇦",
    "kuwait": "🇰🇼", "kuwaiti": "🇰🇼",
    "oman": "🇴🇲", "omani": "🇴🇲",
    "bahrain": "🇧🇭", "bahraini": "🇧🇭",
    # Regional / supranational
    "europe": "🇪🇺", "european": "🇪🇺", "brussels": "🇪🇺",
    "macron": "🇫🇷", "zelensky": "🇺🇦", "modi": "🇮🇳",
    "uae": "🇦🇪", "dubai": "🇦🇪", "abu dhabi": "🇦🇪", "emirates": "🇦🇪",
    "poland": "🇵🇱", "polish": "🇵🇱", "warsaw": "🇵🇱",
    "netherlands": "🇳🇱", "dutch": "🇳🇱", "amsterdam": "🇳🇱",
    "belgium": "🇧🇪", "belgian": "🇧🇪", "brussels": "🇧🇪",
    "sweden": "🇸🇪", "swedish": "🇸🇪", "stockholm": "🇸🇪",
    "norway": "🇳🇴", "norwegian": "🇳🇴", "oslo": "🇳🇴",
    "finland": "🇫🇮", "finnish": "🇫🇮", "helsinki": "🇫🇮",
    "greece": "🇬🇷", "greek": "🇬🇷", "athens": "🇬🇷",
    "portugal": "🇵🇹", "portuguese": "🇵🇹", "lisbon": "🇵🇹",
    "switzerland": "🇨🇭", "swiss": "🇨🇭", "zurich": "🇨🇭",
    "austria": "🇦🇹", "austrian": "🇦🇹", "vienna": "🇦🇹",
    "argentina": "🇦🇷", "argentine": "🇦🇷", "buenos aires": "🇦🇷",
    "chile": "🇨🇱", "chilean": "🇨🇱", "santiago": "🇨🇱",
    "colombia": "🇨🇴", "colombian": "🇨🇴", "bogota": "🇨🇴",
    "venezuela": "🇻🇪", "venezuelan": "🇻🇪", "caracas": "🇻🇪",
    "taiwan": "🇹🇼", "taiwanese": "🇹🇼", "taipei": "🇹🇼",
    "singapore": "🇸🇬", "singaporean": "🇸🇬",
    "indonesia": "🇮🇩", "indonesian": "🇮🇩", "jakarta": "🇮🇩",
    "malaysia": "🇲🇾", "malaysian": "🇲🇾", "kuala lumpur": "🇲🇾",
    "thailand": "🇹🇭", "thai": "🇹🇭", "bangkok": "🇹🇭",
    "vietnam": "🇻🇳", "vietnamese": "🇻🇳", "hanoi": "🇻🇳",
    "philippines": "🇵🇭", "philippine": "🇵🇭", "manila": "🇵🇭",
    "myanmar": "🇲🇲", "burma": "🇲🇲", "burmese": "🇲🇲",
    "bangladesh": "🇧🇩", "bangladeshi": "🇧🇩", "dhaka": "🇧🇩",
    "sri lanka": "🇱🇰", "sri lankan": "🇱🇰", "colombo": "🇱🇰",
    "nepal": "🇳🇵", "nepalese": "🇳🇵", "kathmandu": "🇳🇵",
    "new zealand": "🇳🇿", "kiwi": "🇳🇿", "auckland": "🇳🇿",
    "ireland": "🇮🇪", "irish": "🇮🇪", "dublin": "🇮🇪",
    "scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "hong kong": "🇭🇰",
    # Olympics: don't map to a generic globe — let country detection find the
    # actual country (athlete nationality, host city, etc.) via other keywords.
    # "cortina" and "milan" map to Italy via existing entries.
    "un": "🇺🇳", "united nations": "🇺🇳",
    "eu": "🇪🇺", "european union": "🇪🇺", "europe": "🇪🇺",
    "nato": "🇪🇺",
    "belarus": "🇧🇾", "belarusian": "🇧🇾", "minsk": "🇧🇾",
    "lithuania": "🇱🇹", "lithuanian": "🇱🇹",
    "latvia": "🇱🇻", "latvian": "🇱🇻",
    "estonia": "🇪🇪", "estonian": "🇪🇪",
}


# Press release / vendor marketing signals — if 2+ match, penalize heavily
_PRESS_RELEASE_SIGNALS = [
    "completes deployment", "announces partnership", "launches new",
    "expands operations", "signs agreement", "selected by",
    "chosen to provide", "awards contract", "deploys",
    "enterprise-wide", "go-live", "rolls out", "now available",
    "partners with", "teams up with", "integrates with",
    "unveils new", "introduces new", "expands into",
    "achieves milestone", "reaches milestone", "surpasses",
    "named leader", "recognized as", "positioned as",
    "completes acquisition", "acquires", "enters partnership",
    "signs deal", "inks deal", "secures contract",
    "completes rollout", "completes migration",
]


# High-signal tech sources get a scoring boost — PayZen is a tech company,
# so top industry aggregator stories are always worth reviewing.
_HIGH_SIGNAL_SOURCES = {
    "techmeme": 5,
    "techcrunch": 3, "techcrunch ai": 3,
    "the verge": 3, "the verge ai": 3,
    "ars technica": 2,
    "wired": 2,
    "the information": 3,
    "mit technology review": 2,
}


def score_article(article: dict) -> int:
    """
    Score an article by PayZen relevance.
    Higher score = more relevant to PayZen/Rohan's priorities.
    Penalizes press releases / vendor marketing content.
    Boosts high-signal tech sources (Techmeme, TechCrunch, etc.).
    """
    text = f"{article.get('headline', '')} {article.get('source', '')}".lower()
    score = 0

    for keyword in PAYZEN_KEYWORDS["high"]:
        if keyword in text:
            score += 10

    for keyword in PAYZEN_KEYWORDS["medium"]:
        if keyword in text:
            score += 5

    for keyword in PAYZEN_KEYWORDS["low"]:
        if keyword in text:
            score += 1

    # Market impact: major financial events any executive should know about
    for keyword in PAYZEN_KEYWORDS["market"]:
        if keyword in text:
            score += 7
            break  # One match is enough — avoid double-counting "market crash" + "crash"

    # Geopolitical: international events an executive should track
    for keyword in PAYZEN_KEYWORDS["geopolitical"]:
        if keyword in text:
            score += 5
            break  # Single match sufficient

    # Source boost: high-signal tech aggregators
    source_lower = article.get("source", "").lower()
    for src, boost in _HIGH_SIGNAL_SOURCES.items():
        if src in source_lower:
            score += boost
            break

    # Press release penalty: if 2+ signals match, this is vendor marketing
    pr_hits = sum(1 for sig in _PRESS_RELEASE_SIGNALS if sig in text)
    if pr_hits >= 2:
        score -= 25
    elif pr_hits == 1:
        score -= 5

    return score


def detect_country_flag(text: str) -> str:
    """Detect the most relevant country flag for a headline.

    Uses word-boundary matching for all keywords to avoid false matches
    like 'oman' in 'woman', 'un' in 'Runway', or 'eu' in 'neural'.
    """
    import re
    text_lower = text.lower()

    for keyword, flag in COUNTRY_FLAGS.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            return flag

    # Default to US if no match (most common for business news)
    return "🇺🇸"


def categorize_article(article: dict) -> str:
    """Categorize article into a section.

    Source-based overrides take priority over headline keywords —
    a STAT News story about Congress is still health news.
    """
    source = article.get("source", "").lower()

    # Source-based overrides: strongest signal for category
    _HEALTH_SOURCES = [
        "stat news", "stat", "becker", "healthcare dive", "kff health",
        "fierce healthcare", "modern healthcare", "healthleaders",
        "health affairs", "medpage", "advisory board",
    ]
    _BUSINESS_SOURCES = [
        "financial times", "bloomberg", "wall street journal", "wsj",
        "reuters business", "cnbc", "fortune", "barron", "economist",
        "business insider", "insider", "marketwatch",
    ]

    for src in _HEALTH_SOURCES:
        if src in source:
            return "health"
    for src in _BUSINESS_SOURCES:
        if src in source:
            return "business"

    # Headline keyword fallback
    text = f"{article.get('headline', '')} {source}".lower()

    health_keywords = [
        "health", "hospital", "patient", "medical", "medicare", "medicaid",
        "cms", "healthcare", "telehealth", "clinic", "physician", "doctor",
        "rcm", "revenue cycle", "payment plan", "self-pay", "aca",
        "cedar", "flywire", "optum", "unitedhealth", "anthem", "cigna",
    ]

    ai_keywords = [
        "ai", "artificial intelligence", "machine learning", "claude", "gpt",
        "openai", "anthropic", "codex", "cursor", "coding", "developer",
        "agent", "automation", "model", "llm", "enterprise ai",
    ]

    for kw in health_keywords:
        if kw in text:
            return "health"

    for kw in ai_keywords:
        if kw in text:
            return "tech"

    return "business"


def load_validated_candidates(input_file: str) -> dict:
    """Load validated candidates from Phase 1 output."""
    with open(input_file, "r", encoding="utf-8") as f:
        return json.load(f)


def select_tier1_candidates(candidates: list[dict]) -> list[dict]:
    """
    Select and rank candidates for Tier 1 (Deep Insight).
    Returns top 5-8 articles sorted by relevance score.
    """
    # Score all candidates
    for article in candidates:
        article["_score"] = score_article(article)
        article["_category"] = categorize_article(article)

    # Sort by score descending
    sorted_candidates = sorted(candidates, key=lambda x: x["_score"], reverse=True)

    # Apply source diversity: max 2 from same source
    selected = []
    source_counts = {}

    for article in sorted_candidates:
        source = article.get("source", "Unknown")
        if source_counts.get(source, 0) < 2:
            selected.append(article)
            source_counts[source] = source_counts.get(source, 0) + 1

        if len(selected) >= MAX_TIER1_STORIES:
            break

    return selected


def select_ga_candidates(all_candidates: list[dict], tier1_urls: set) -> list[dict]:
    """
    Select candidates for General Awareness.
    Excludes Tier 1 articles, prioritizes geographic diversity.
    """
    # Filter out Tier 1 articles
    remaining = [a for a in all_candidates if a.get("url") not in tier1_urls]

    # Add flag detection
    for article in remaining:
        article["_flag"] = detect_country_flag(article.get("headline", ""))

    # Prioritize diversity of flags
    selected = []
    seen_flags = set()

    # First pass: one per region
    for article in remaining:
        flag = article["_flag"]
        if flag not in seen_flags and len(selected) < MAX_GA_ITEMS:
            selected.append(article)
            seen_flags.add(flag)

    # Second pass: fill remaining slots
    for article in remaining:
        if article not in selected and len(selected) < MAX_GA_ITEMS:
            selected.append(article)

    return selected[:MAX_GA_ITEMS]


def get_day_of_week(date_str: str) -> str:
    """Get day of week from ISO date string."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A")
    except:
        return datetime.now().strftime("%A")


def format_date_header(date_str: str = None) -> str:
    """Format date for the header (e.g., 'Monday, February 2, 2026')."""
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            dt = datetime.now()
    else:
        dt = datetime.now()

    # Format: "Monday, February 2, 2026"
    return dt.strftime("%A, %B %d, %Y").replace(" 0", " ")


def build_generation_prompt(tier1: list[dict], ga: list[dict], date_str: str) -> str:
    """
    Build the prompt for Claude to generate the briefing content.
    """
    prompt = f"""You are generating a Morning Intelligence Briefing for Rohan, SVP of Product at PayZen.

## Context about Rohan and PayZen:
- PayZen does patient financing for non-elective medical treatments
- Target market: top 300 US health systems
- Partners/competitors: Cedar, Flywire
- Rohan starts March 9, 2026 — currently building landscape knowledge
- He wants PayZen to be an AI-native company (Claude Code rollout planned)
- Key themes: patient self-pay, RCM shifts, health system financial distress, AI coding tools

## Your Task:
Generate content for the briefing using ONLY the validated articles below. You must:

1. For each Tier 1 story, generate:
   - A rewritten headline (specific, informative)
   - A 2-3 sentence summary of the actual news
   - A "So What" section (1 paragraph, specific to PayZen/Rohan, actionable)
   - Note if it has a paywall

2. For General Awareness items, generate:
   - A one-line headline
   - One sentence of context

3. Generate "Today in 30 Seconds" (3-4 bullet points from strongest So Whats)

## SECTION QUALITY BARS (v8 spec):
- **Health Tech** should have the MOST stories (3-6). This is the core of the briefing.
- **Tech & AI** must feature CONCRETE DEVELOPMENTS only (2-4 stories):
  - YES: Model releases, tool launches, specific adoption case studies, benchmark results, regulatory moves
  - NO: Generic think pieces about "AI design principles" or "why AI matters for enterprise"
  - If it doesn't describe SOMETHING THAT HAPPENED, it's not a Tech & AI story
- **Business & Strategy** is optional — only include when genuinely relevant (0-2 stories)

## ANTI-PATTERNS TO REJECT:
- Generic think pieces as news — "why AI matters" or "design principles for enterprise AI" are NOT news
- Tier 1 stories should describe SOMETHING THAT HAPPENED — a launch, a deal, a policy change, a data release
- If the So What requires heavy hedging ("weak signal," "probably won't matter"), drop it

## CRITICAL RULES:
- Use EXACTLY the verified_date_display from each article. NEVER generate a date.
- If verified_date_display shows "⚠️ date unverified", display it exactly as-is.
- The dates have been verified by code extraction — do not modify them.
- NUMBER STORIES SEQUENTIALLY (1, 2, 3, 4...) across ALL sections — no gaps, no restarts per section.

## Date for header: {date_str}

## Tier 1 Candidates (generate Deep Insight stories):
"""

    for i, article in enumerate(tier1, 1):
        prompt += f"""
### Candidate {i}
- Headline: {article.get('headline', 'Unknown')}
- URL: {article.get('url', '')}
- Source: {article.get('source', 'Unknown')}
- Verified Date: {article.get('verified_date_display', '⚠️ date unverified')}
- Read Time: {article.get('estimated_read_time_min', 5)} min
- Category: {article.get('_category', 'general')}
"""

    prompt += """

## General Awareness Candidates:
"""

    for i, article in enumerate(ga, 1):
        prompt += f"""
### GA Candidate {i}
- Headline: {article.get('headline', 'Unknown')}
- URL: {article.get('url', '')}
- Source: {article.get('source', 'Unknown')}
- Verified Date: {article.get('verified_date_display', '⚠️ date unverified')}
- Read Time: {article.get('estimated_read_time_min', 3)} min
- Flag: {article.get('_flag', '🇺🇸')}
"""

    prompt += """

## Output Format:
Return a JSON object with this structure:
```json
{
  "today_in_30_seconds": [
    {"bold_fact": "...", "implication": "..."},
    ...
  ],
  "tier1_stories": [
    {
      "number": 1,
      "headline": "Rewritten headline",
      "url": "original URL",
      "source": "Source Name",
      "date_display": "EXACTLY as provided in verified_date_display",
      "read_time_min": 5,
      "has_paywall": false,
      "category": "health|tech|business",
      "summary": "2-3 sentence summary...",
      "so_what": "1 paragraph So What..."
    },
    ...
  ],
  "general_awareness": [
    {
      "flag": "🇺🇸",
      "headline": "One-line headline",
      "url": "original URL",
      "context": "One sentence context",
      "source": "Source",
      "date_display": "EXACTLY as provided in verified_date_display",
      "read_time_min": 3
    },
    ...
  ],
  "sources_list": ["Source 1", "Source 2", ...]
}
```

IMPORTANT:
- Copy dates EXACTLY from verified_date_display. Never generate dates.
- Number stories 1, 2, 3, 4... SEQUENTIALLY across all sections.
- Health Tech stories come first, then Tech & AI, then Business (if any).
- Reject generic think pieces — only include stories about THINGS THAT HAPPENED.
"""

    return prompt


def generate_with_claude(prompt: str) -> Optional[dict]:
    """Call Claude API to generate the briefing content."""
    if not HAS_ANTHROPIC:
        print("Error: anthropic package not installed", file=sys.stderr)
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        return None

    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Extract JSON from response
        response_text = message.content[0].text

        # Find JSON in response
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1

        if json_start >= 0 and json_end > json_start:
            json_str = response_text[json_start:json_end]
            return json.loads(json_str)
        else:
            print("Error: Could not find JSON in response", file=sys.stderr)
            return None

    except Exception as e:
        print(f"Error calling Claude API: {e}", file=sys.stderr)
        return None


def render_html(content: dict, date_str: str) -> str:
    """Render the briefing as HTML using the v4 template structure."""

    # Calculate totals
    total_stories = len(content.get("tier1_stories", []))
    total_time = sum(s.get("read_time_min", 5) for s in content.get("tier1_stories", []))

    date_header = format_date_header(date_str)

    # Build Today in 30 Seconds
    topline_items = ""
    for item in content.get("today_in_30_seconds", []):
        topline_items += f'      <li><strong>{item.get("bold_fact", "")}</strong> — {item.get("implication", "")}</li>\n'

    # Group Tier 1 by category (health first, then tech, then business per v8 spec)
    health_stories = [s for s in content.get("tier1_stories", []) if s.get("category") == "health"]
    tech_stories = [s for s in content.get("tier1_stories", []) if s.get("category") == "tech"]
    business_stories = [s for s in content.get("tier1_stories", []) if s.get("category") == "business"]

    # Assign sequential numbers across all sections (v8 spec requirement)
    story_number = 1
    for story in health_stories + tech_stories + business_stories:
        story["_seq_number"] = story_number
        story_number += 1

    def render_story(story: dict, global_idx: int) -> str:
        alt_class = " story-alt" if global_idx % 2 == 0 else ""
        paywall_badge = '<span class="divider">·</span>\n      <span class="paywall-badge">🔒 paywall</span>' if story.get("has_paywall") else ""

        return f'''
  <div class="story{alt_class}">
    <div class="story-headline-row">
      <div class="story-number">{story.get("_seq_number", global_idx):02d}</div>
      <div class="story-headline"><a href="{story.get("url", "#")}">{story.get("headline", "")}</a></div>
    </div>
    <div class="story-meta">
      <span class="source">{story.get("source", "")}</span>
      <span class="divider">·</span>
      {story.get("date_display", "⚠️ date unverified")}
      <span class="divider">·</span>
      {story.get("read_time_min", 5)} min read
      {paywall_badge}
    </div>
    <div class="story-summary">
      {story.get("summary", "")}
    </div>
    <div class="so-what">
      <div class="so-what-label">So What</div>
      <p>{story.get("so_what", "")}</p>
    </div>
  </div>
'''

    # Render sections with global sequential numbering
    stories_html = ""
    global_idx = 0

    # Health Tech section (comes first per v8 spec)
    if health_stories:
        stories_html += '''
  <div class="section-header">
    <div class="section-label">🏥 Health Tech</div>
  </div>
'''
        for story in health_stories:
            stories_html += render_story(story, global_idx)
            global_idx += 1

    # Tech & AI section
    if tech_stories:
        stories_html += '''
  <div class="section-header">
    <div class="section-label">⚡ Tech & AI</div>
  </div>
'''
        for story in tech_stories:
            stories_html += render_story(story, global_idx)
            global_idx += 1

    # Business section (optional per v8 spec)
    if business_stories:
        stories_html += '''
  <div class="section-header">
    <div class="section-label">💰 Business & Strategy</div>
  </div>
'''
        for story in business_stories:
            stories_html += render_story(story, global_idx)
            global_idx += 1

    # Render General Awareness
    ga_items = ""
    for item in content.get("general_awareness", []):
        ga_items += f'''
    <div class="ga-item">
      <div class="ga-flag">{item.get("flag", "🇺🇸")}</div>
      <div class="ga-content">
        <a href="{item.get("url", "#")}" class="ga-headline">{item.get("headline", "")}</a> —
        <span class="ga-context">{item.get("context", "")}</span>
      </div>
      <div class="ga-source">{item.get("source", "")} · {item.get("date_display", "")} · {item.get("read_time_min", 3)}m</div>
    </div>
'''

    # Sources list
    sources = " · ".join(content.get("sources_list", []))

    # Full HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Morning Intelligence</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=Source+Sans+3:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: 'Source Sans 3', -apple-system, sans-serif;
    background: #f8f7f4;
    color: #1a1a1a;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }}

  .email-wrapper {{
    max-width: 680px;
    margin: 0 auto;
    background: #ffffff;
  }}

  .header {{
    padding: 32px 40px 24px;
    border-bottom: 1px solid #e8e6e1;
  }}

  .header-top {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 6px;
  }}

  .masthead {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #2c2c2c;
  }}

  .edition-label {{
    font-size: 12px;
    font-weight: 500;
    color: #999;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }}

  .date-line {{
    font-size: 13px;
    color: #888;
    font-weight: 400;
  }}

  .date-line span {{
    color: #b8860b;
    font-weight: 500;
  }}

  .topline {{
    padding: 28px 40px;
    background: #fafaf8;
    border-bottom: 1px solid #e8e6e1;
  }}

  .topline-title {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #b8860b;
    margin-bottom: 14px;
  }}

  .topline-items {{
    list-style: none;
    padding: 0;
  }}

  .topline-items li {{
    font-size: 14px;
    line-height: 1.55;
    color: #3a3a3a;
    padding: 5px 0;
    padding-left: 16px;
    position: relative;
  }}

  .topline-items li::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 12px;
    width: 5px;
    height: 5px;
    background: #b8860b;
    border-radius: 50%;
  }}

  .topline-items li strong {{
    font-weight: 600;
    color: #1a1a1a;
  }}

  .section-header {{
    padding: 36px 40px 0;
  }}

  .section-label {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #888;
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  .section-label::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: #e8e6e1;
  }}

  .story {{
    padding: 26px 40px 30px;
    border-bottom: 1px solid #f0eeeb;
  }}

  .story:last-of-type {{
    border-bottom: 1px solid #e8e6e1;
  }}

  .story-alt {{
    background: #fdfcfa;
  }}

  .story-headline-row {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 6px;
  }}

  .story-number {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 16px;
    font-weight: 700;
    color: #b8860b;
    flex-shrink: 0;
    min-width: 22px;
  }}

  .story-headline {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 20px;
    font-weight: 600;
    line-height: 1.3;
    color: #1a1a1a;
  }}

  .story-headline a {{
    color: #1a1a1a;
    text-decoration: none;
    border-bottom: 1px solid #d4d0c8;
    transition: border-color 0.2s, color 0.2s;
  }}

  .story-headline a:hover {{
    border-bottom-color: #b8860b;
    color: #333;
  }}

  .story-meta {{
    font-size: 12px;
    color: #aaa;
    font-weight: 400;
    margin-bottom: 14px;
    margin-left: 34px;
    display: flex;
    align-items: center;
    gap: 6px;
  }}

  .story-meta .source {{
    font-weight: 500;
    color: #888;
  }}

  .story-meta .divider {{
    color: #ddd;
  }}

  .paywall-badge {{
    font-size: 10px;
    background: #fff3cd;
    color: #856404;
    padding: 1px 6px;
    border-radius: 3px;
    font-weight: 500;
  }}

  .story-summary {{
    font-size: 15px;
    line-height: 1.65;
    color: #444;
    margin-bottom: 18px;
    margin-left: 34px;
  }}

  .so-what {{
    background: #f9f8f5;
    border-left: 3px solid #b8860b;
    padding: 16px 20px;
    border-radius: 0 6px 6px 0;
    margin-left: 34px;
  }}

  .so-what-label {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #b8860b;
    margin-bottom: 8px;
  }}

  .so-what p {{
    font-size: 14px;
    line-height: 1.65;
    color: #555;
  }}

  .so-what strong {{
    color: #333;
    font-weight: 600;
  }}

  .general-awareness {{
    padding: 32px 40px;
    background: #fafaf8;
    border-top: 1px solid #e8e6e1;
  }}

  .ga-title {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 4px;
  }}

  .ga-subtitle {{
    font-size: 12px;
    color: #aaa;
    font-style: italic;
    margin-bottom: 18px;
  }}

  .ga-item {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 9px 0;
    border-bottom: 1px solid #eeedea;
    font-size: 14px;
  }}

  .ga-item:last-child {{
    border-bottom: none;
  }}

  .ga-flag {{
    font-size: 16px;
    flex-shrink: 0;
    width: 24px;
    text-align: center;
  }}

  .ga-content {{
    flex: 1;
  }}

  .ga-headline {{
    font-weight: 600;
    color: #2c2c2c;
    text-decoration: none;
    border-bottom: 1px solid #d4d0c8;
    transition: border-color 0.2s, color 0.2s;
  }}

  .ga-headline:hover {{
    border-bottom-color: #b8860b;
    color: #333;
  }}

  .ga-context {{
    color: #777;
    font-weight: 400;
  }}

  .ga-source {{
    font-size: 11px;
    color: #aaa;
    flex-shrink: 0;
    text-align: right;
    white-space: nowrap;
  }}

  .footer {{
    padding: 24px 40px;
    border-top: 1px solid #e8e6e1;
    text-align: center;
  }}

  .footer-sources {{
    font-size: 11px;
    color: #bbb;
    line-height: 1.6;
    margin-bottom: 8px;
  }}

  .footer-note {{
    font-size: 11px;
    color: #ccc;
  }}

  .footer-note span {{
    color: #b8860b;
  }}

  @media (max-width: 600px) {{
    .header, .topline, .section-header, .story, .general-awareness, .footer {{
      padding-left: 24px;
      padding-right: 24px;
    }}

    .story-headline {{
      font-size: 18px;
    }}

    .story-meta, .story-summary, .so-what {{
      margin-left: 0;
    }}

    .story-headline-row {{
      gap: 8px;
    }}

    .ga-item {{
      font-size: 13px;
    }}

    .ga-source {{
      display: none;
    }}
  }}
</style>
</head>
<body>

<div class="email-wrapper">

  <!-- HEADER -->
  <div class="header">
    <div class="header-top">
      <div class="masthead">The Morning Intelligence</div>
      <div class="edition-label">Digital Chief of Staff</div>
    </div>
    <div class="date-line">{date_header} · <span>{total_stories} deep reads</span> · ~{total_time} min total</div>
  </div>

  <!-- TOP LINE -->
  <div class="topline">
    <div class="topline-title">Today in 30 Seconds</div>
    <ul class="topline-items">
{topline_items}    </ul>
  </div>

{stories_html}

  <!-- GENERAL AWARENESS -->
  <div class="general-awareness">
    <div class="ga-title">🌍 General Awareness</div>
    <div class="ga-subtitle">So you're never caught off guard.</div>
{ga_items}
  </div>

  <!-- FOOTER -->
  <div class="footer">
    <div class="footer-sources">
      Sources: {sources}
    </div>
    <div class="footer-note"><span>🔒</span> = paywall · Built with <span>♠</span> by Digital Chief of Staff</div>
  </div>

</div>

</body>
</html>
'''

    return html


def run_phase2(input_file: str, output_file: str = None, date_str: str = None) -> str:
    """
    Run Phase 2: Generate the briefing from validated candidates.

    Args:
        input_file: Path to validated_candidates.json from Phase 1
        output_file: Path for output HTML file (optional)
        date_str: Date string for the briefing (optional, defaults to today)

    Returns:
        Path to the generated HTML file
    """
    print("=" * 60, file=sys.stderr)
    print("PHASE 2: Briefing Generation", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Load candidates
    print("\n[1/5] Loading validated candidates...", file=sys.stderr)
    data = load_validated_candidates(input_file)

    valid_candidates = data.get("valid_candidates", [])
    unverified_candidates = data.get("unverified_candidates", [])

    print(f"  Loaded {len(valid_candidates)} valid + {len(unverified_candidates)} unverified candidates", file=sys.stderr)

    # Combine valid and unverified (valid prioritized)
    all_candidates = valid_candidates + unverified_candidates

    # Select Tier 1
    print("\n[2/5] Selecting Tier 1 stories...", file=sys.stderr)
    tier1 = select_tier1_candidates(all_candidates)
    print(f"  Selected {len(tier1)} stories for Tier 1", file=sys.stderr)

    # Select General Awareness
    print("\n[3/5] Selecting General Awareness items...", file=sys.stderr)
    tier1_urls = {a.get("url") for a in tier1}
    ga = select_ga_candidates(all_candidates, tier1_urls)
    print(f"  Selected {len(ga)} items for General Awareness", file=sys.stderr)

    # Determine date
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # Generate content via Claude API
    print("\n[4/5] Generating briefing content via Claude API...", file=sys.stderr)

    prompt = build_generation_prompt(tier1, ga, date_str)

    if HAS_ANTHROPIC and os.environ.get("ANTHROPIC_API_KEY"):
        content = generate_with_claude(prompt)
        if not content:
            print("  API generation failed, creating skeleton briefing...", file=sys.stderr)
            content = create_skeleton_content(tier1, ga)
    else:
        print("  No API key available, creating skeleton briefing...", file=sys.stderr)
        print("  Set ANTHROPIC_API_KEY and install anthropic package for full generation", file=sys.stderr)
        content = create_skeleton_content(tier1, ga)

    # Render HTML
    print("\n[5/5] Rendering HTML...", file=sys.stderr)
    html = render_html(content, date_str)

    # Output
    if not output_file:
        output_file = f"morning-briefing-{date_str}.html"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    print("\n" + "=" * 60, file=sys.stderr)
    print("PHASE 2 COMPLETE", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Output written to: {output_file}", file=sys.stderr)

    return output_file


def create_skeleton_content(tier1: list[dict], ga: list[dict]) -> dict:
    """
    Create skeleton content when API is not available.
    Uses article headlines and metadata directly.
    """
    # Today in 30 seconds - pick top 4
    today_30 = []
    for i, article in enumerate(tier1[:4]):
        today_30.append({
            "bold_fact": article.get("headline", "")[:60],
            "implication": "[Generate with Claude API for full content]"
        })

    # Tier 1 stories
    tier1_stories = []
    for i, article in enumerate(tier1, 1):
        tier1_stories.append({
            "number": i,
            "headline": article.get("headline", ""),
            "url": article.get("url", "#"),
            "source": article.get("source", "Unknown"),
            "date_display": article.get("verified_date_display", "⚠️ date unverified"),
            "read_time_min": article.get("estimated_read_time_min", 5),
            "has_paywall": False,
            "category": article.get("_category", "health"),
            "summary": "[Set ANTHROPIC_API_KEY to generate summary]",
            "so_what": "[Set ANTHROPIC_API_KEY to generate So What section]"
        })

    # General Awareness
    ga_items = []
    for article in ga:
        ga_items.append({
            "flag": article.get("_flag", "🇺🇸"),
            "headline": article.get("headline", ""),
            "url": article.get("url", "#"),
            "context": "[Set ANTHROPIC_API_KEY to generate context]",
            "source": article.get("source", "Unknown"),
            "date_display": article.get("verified_date_display", "⚠️ date unverified"),
            "read_time_min": article.get("estimated_read_time_min", 3)
        })

    # Sources list
    sources = list(set(a.get("source", "Unknown") for a in tier1 + ga))

    return {
        "today_in_30_seconds": today_30,
        "tier1_stories": tier1_stories,
        "general_awareness": ga_items,
        "sources_list": sources
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 2: Briefing Generator for Morning Intelligence")
    parser.add_argument("-i", "--input", default="validated_candidates.json",
                        help="Input JSON file from Phase 1 (default: validated_candidates.json)")
    parser.add_argument("-o", "--output", help="Output HTML file path")
    parser.add_argument("-d", "--date", help="Date for the briefing (YYYY-MM-DD format)")
    args = parser.parse_args()

    run_phase2(args.input, args.output, args.date)
