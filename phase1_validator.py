"""
Phase 1: Article Validator for Morning Intelligence Briefing

This script fetches candidate articles from monitored sources, extracts and verifies
publication dates from actual HTML, and outputs a validated candidate list as JSON.

The LLM never decides dates — this code hands it facts.

Also provides:
- Source tier classification (Tier 1/2/3/Local) for GA source quality gates
- From X batched search query builder and status ID validation
- Age computation helpers for the age verification table
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

# Configuration
MAX_AGE_HOURS = 48
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# =============================================================================
# SOURCE TIER CLASSIFICATION
# =============================================================================
# Used by GA Source Tally gate. Hard-coded from spec to prevent misclassification.
# Key = lowercase normalized name or domain fragment. Value = tier number.

# Tier 1: Prefer for GA
TIER1_SOURCES = {
    "bbc", "bbc world", "bbc news", "bbc sport",
    "reuters", "reuters business",
    "ap", "ap news", "associated press",
    "al jazeera",
    "npr", "npr news",
    "nyt", "new york times", "the new york times",
    "wsj", "wall street journal", "the wall street journal",
    "the guardian", "guardian",
}

# Tier 2: Acceptable for GA
TIER2_SOURCES = {
    "bloomberg",
    "cnbc",
    "financial times", "ft",
    "politico",
    "washington post", "the washington post", "wapo",
    "cnn",
    "pbs", "pbs newshour",
    "abc news",
    "cbs news",
    "nbc news",
    "espn",
    "techcrunch", "techcrunch ai",
    "the verge", "the verge ai",
    "fortune",
    "wired",
    "time", "time magazine",
    "axios",
    "the atlantic",
    "the economist",
    "foreign affairs",
    "foreign policy",
}

# Tier 3: Avoid for GA — niche, single-topic, or aggregator sources
# These should only be used if they are the SOLE source for a significant story
# and no Tier 1/2 coverage exists after active search.
TIER3_SOURCES = {
    # Sports niche
    "olympics.com", "nbc olympics", "nbcolympics",
    "yahoo sports", "bleacher report",
    # Single-topic / niche publications
    "unhcr", "balkan insight", "just security", "world",
    "defense one", "ukr. pravda", "ukrainian pravda",
    "military times", "space.com", "the diplomat",
    # Aggregators / press releases
    "pr newswire", "prnewswire", "globenewswire", "business wire",
    "ramaonhealthcare",
    # Regional / niche international
    "times of israel",
    # Healthcare-specific (these are fine for Health Tech section, NOT for GA)
    "healthcare dive", "fierce healthcare", "modern healthcare",
    "becker's hospital review", "beckers hospital review",
    "stat news", "kff health news",
    # Tech-specific (fine for Tech & AI section, NOT for GA)
    "mit technology review", "ars technica", "the information",
    "techcrunch ai",
}

# Local papers: NEVER for GA, only for Local section
LOCAL_SOURCES = {
    "east bay times", "mercury news", "san jose mercury news",
    "patch", "danville sanramon", "danville san ramon",
    "sf standard", "san francisco standard",
    "sf chronicle", "san francisco chronicle", "sfchronicle",
    "abc7", "abc7 san francisco", "abc7 news",
    "kqed",
    "pleasanton weekly", "tri-valley herald",
    "oakland tribune",
    "bay area news group",
    "marin independent journal",
}

# Domain fragment -> source name mapping for URL-based classification
DOMAIN_TO_SOURCE = {
    "nbcolympics.com": "NBC Olympics",
    "olympics.com": "Olympics.com",
    "yahoosports": "Yahoo Sports",
    "sports.yahoo.com": "Yahoo Sports",
    "bleacherreport.com": "Bleacher Report",
    "prnewswire.com": "PR Newswire",
    "globenewswire.com": "GlobeNewsWire",
    "businesswire.com": "Business Wire",
    "timesofisrael.com": "Times of Israel",
    "ramaonhealthcare.com": "RamaOnHealthcare",
}


def _normalize_source_name(name: str) -> str:
    """Normalize a source name for tier lookup.
    Strips parenthetical suffixes like '(AFP)', whitespace, and 'The' prefix.
    """
    # Remove parenthetical suffixes: "Times of Israel (AFP)" -> "Times of Israel"
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    return name.strip().lower()


def classify_source_tier(source_name: str, url: str = "") -> dict:
    """
    Classify a source into Tier 1, 2, 3, or Local for GA source quality gate.

    Returns dict with:
        tier: int (1, 2, 3, or 99 for local)
        tier_label: str ("Tier 1", "Tier 2", "Tier 3", "Local")
        ga_eligible: bool (True if Tier 1 or 2)
        note: str (explanation if flagged)
    """
    name_lower = _normalize_source_name(source_name)

    # Check URL domain for additional classification
    url_lower = url.lower() if url else ""
    for domain_frag, mapped_source in DOMAIN_TO_SOURCE.items():
        if domain_frag in url_lower:
            name_lower = mapped_source.lower()
            break

    # Check each tier (try both normalized and original)
    names_to_check = {name_lower}
    # Also add the full original lowered name in case normalization over-stripped
    names_to_check.add(source_name.strip().lower())

    for name in names_to_check:
        if name in TIER1_SOURCES:
            return {"tier": 1, "tier_label": "Tier 1", "ga_eligible": True, "note": ""}

    for name in names_to_check:
        if name in TIER2_SOURCES:
            return {"tier": 2, "tier_label": "Tier 2", "ga_eligible": True, "note": ""}

    for name in names_to_check:
        if name in TIER3_SOURCES:
            return {
                "tier": 3,
                "tier_label": "Tier 3",
                "ga_eligible": False,
                "note": f"FLAGGED: '{source_name}' is Tier 3 (niche/single-topic). "
                        f"Find Tier 1/2 coverage for the same story before including in GA.",
            }

    for name in names_to_check:
        if name in LOCAL_SOURCES:
            return {
                "tier": 99,
                "tier_label": "Local",
                "ga_eligible": False,
                "note": f"BLOCKED: '{source_name}' is a local paper. NEVER use for GA.",
            }

    # Unknown source — flag for manual review
    return {
        "tier": 0,
        "tier_label": "Unknown",
        "ga_eligible": False,
        "note": f"UNKNOWN: '{source_name}' not in tier database. Classify manually. "
                f"Check spec Tier 1/2 lists before including in GA.",
    }


def validate_ga_source_tally(ga_items: list[dict]) -> dict:
    """
    Run the GA Source Tally gate on a list of GA items.
    Each item should have 'source' and optionally 'url' keys.

    Returns dict with:
        passed: bool
        source_counts: dict of source -> count
        tier_violations: list of flagged items
        us_count: int
        max_source_count: int
        issues: list of str (empty if passed)
    """
    source_counts = {}
    tier_violations = []
    issues = []

    for item in ga_items:
        source = item.get("source", "Unknown")
        url = item.get("url", "")

        # Count sources
        source_counts[source] = source_counts.get(source, 0) + 1

        # Classify tier
        tier_info = classify_source_tier(source, url)
        if not tier_info["ga_eligible"]:
            tier_violations.append({
                "source": source,
                "headline": item.get("headline", ""),
                **tier_info,
            })

    # Check max source count (no source > 3)
    max_source = max(source_counts.values()) if source_counts else 0
    max_source_name = max(source_counts, key=source_counts.get) if source_counts else ""
    if max_source > 3:
        issues.append(f"Source '{max_source_name}' appears {max_source} times (max 3)")

    # Report tier violations
    for v in tier_violations:
        issues.append(v["note"])

    return {
        "passed": len(issues) == 0,
        "source_counts": source_counts,
        "tier_violations": tier_violations,
        "max_source_count": max_source,
        "max_source_name": max_source_name,
        "issues": issues,
    }


# =============================================================================
# FROM X: BATCHED SEARCH AND STATUS ID VALIDATION
# =============================================================================

# Tracked handles grouped into search batches (3-4 per query)
# This reduces From X from ~14 individual web searches to 4 batched queries.
FROM_X_HANDLES = [
    "karpathy", "sama", "simonw", "emollick",
    "levelsio", "garrytan", "paulg", "bcherny",
    "DrJimFan", "saranormous", "EladGil", "benedictevans",
    "alexalbert__", "toaborai",
]

FROM_X_SEARCH_BATCHES = [
    ["karpathy", "sama", "simonw", "emollick"],
    ["levelsio", "garrytan", "paulg", "bcherny"],
    ["DrJimFan", "saranormous", "EladGil", "benedictevans"],
    ["alexalbert__", "toaborai"],
]

# Brand accounts excluded from From X (use only as reference posts)
FROM_X_BRAND_ACCOUNTS = {
    "OpenAI", "AnthropicAI", "SpaceX", "BBCBreaking",
    "Reuters", "SawyerMerritt",
}

# Status ID delta threshold
FROM_X_STATUS_ID_MAX_DELTA = 500_000


def build_from_x_batch_queries(month_year: str) -> list[dict]:
    """
    Build batched web search queries for From X handle sweep.

    Args:
        month_year: e.g. "February 2026"

    Returns list of dicts with:
        batch_number: int
        handles: list of str
        query: str (ready to paste into WebSearch)
    """
    queries = []
    for i, batch in enumerate(FROM_X_SEARCH_BATCHES, 1):
        # Build OR query: site:x.com/handle1/status OR site:x.com/handle2/status ...
        site_clauses = " OR ".join(f"site:x.com/{h}/status" for h in batch)
        query = f"({site_clauses}) {month_year}"
        queries.append({
            "batch_number": i,
            "handles": batch,
            "query": query,
        })
    return queries


def build_from_x_reference_query() -> str:
    """
    Build query to find a known-today reference post from a brand account.
    Used to establish the status ID baseline for delta comparison.
    """
    return "site:x.com/OpenAI/status OR site:x.com/AnthropicAI/status"


def validate_status_id_delta(candidate_id: int, reference_id: int) -> dict:
    """
    Compare a candidate X post's status ID against a known-today reference.

    Returns dict with:
        delta: int (candidate - reference)
        delta_display: str (human-readable)
        verdict: str ("PASS" or "REJECT")
        reason: str
    """
    delta = candidate_id - reference_id

    if delta < -FROM_X_STATUS_ID_MAX_DELTA:
        return {
            "delta": delta,
            "delta_display": f"{delta:+,}",
            "verdict": "REJECT",
            "reason": f"Status ID is {abs(delta):,} below reference (threshold: {FROM_X_STATUS_ID_MAX_DELTA:,})",
        }

    return {
        "delta": delta,
        "delta_display": f"{delta:+,}",
        "verdict": "PASS",
        "reason": "Within acceptable range of reference post",
    }


def extract_status_id_from_url(url: str) -> Optional[int]:
    """Extract the numeric status ID from an x.com/twitter.com URL."""
    match = re.search(r"(?:x\.com|twitter\.com)/\w+/status/(\d+)", url)
    if match:
        return int(match.group(1))
    return None


def compute_age_hours(verified_date: str, delivery_time: datetime) -> Optional[int]:
    """
    Compute age in hours between a verified date and the delivery time.
    Returns integer hours or None if date can't be parsed.
    """
    try:
        pub_date = date_parser.parse(verified_date)
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        if delivery_time.tzinfo is None:
            delivery_time = delivery_time.replace(tzinfo=timezone.utc)
        delta = delivery_time - pub_date
        return max(0, int(delta.total_seconds() / 3600))
    except Exception:
        return None

# RSS Feeds to monitor
RSS_FEEDS = {
    # Health Tech
    "Healthcare Dive": "https://www.healthcaredive.com/feeds/news/",
    "Fierce Healthcare": "https://www.fiercehealthcare.com/rss/xml",
    "Modern Healthcare": "https://www.modernhealthcare.com/section/rss",
    "Becker's Hospital Review": "https://www.beckershospitalreview.com/rss/berkshire-healthcare.rss",
    "STAT News": "https://www.statnews.com/feed/",
    "KFF Health News": "https://kffhealthnews.org/feed/",

    # AI & Tech
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "MIT Technology Review": "https://www.technologyreview.com/feed/",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",

    # Business
    "Reuters Business": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best",

    # General News
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "NPR News": "https://feeds.npr.org/1001/rss.xml",
    "AP News": "https://rsshub.app/apnews/topics/apf-topnews",
}

# Search queries for web search (used with news aggregators)
SEARCH_QUERIES = [
    "healthcare RCM revenue cycle management",
    "patient financing healthcare",
    "health system financial",
    "Cedar healthcare payments",
    "Flywire healthcare",
    "Claude Code AI coding",
    "OpenAI Codex",
    "enterprise AI adoption",
    "AI coding assistant",
    "healthcare affordability",
    "Medicare Medicaid policy",
    "telehealth regulation",
]


def get_session() -> requests.Session:
    """Create a requests session with proper headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return session


def extract_date_from_meta(soup: BeautifulSoup) -> Optional[datetime]:
    """Extract date from meta tags."""
    # Try article:published_time (Open Graph)
    meta = soup.find("meta", property="article:published_time")
    if meta and meta.get("content"):
        try:
            return date_parser.parse(meta["content"])
        except:
            pass

    # Try og:published_time
    meta = soup.find("meta", property="og:published_time")
    if meta and meta.get("content"):
        try:
            return date_parser.parse(meta["content"])
        except:
            pass

    # Try pubdate
    meta = soup.find("meta", attrs={"name": "pubdate"})
    if meta and meta.get("content"):
        try:
            return date_parser.parse(meta["content"])
        except:
            pass

    # Try date
    meta = soup.find("meta", attrs={"name": "date"})
    if meta and meta.get("content"):
        try:
            return date_parser.parse(meta["content"])
        except:
            pass

    # Try DC.date
    meta = soup.find("meta", attrs={"name": "DC.date"})
    if meta and meta.get("content"):
        try:
            return date_parser.parse(meta["content"])
        except:
            pass

    # Try sailthru.date
    meta = soup.find("meta", attrs={"name": "sailthru.date"})
    if meta and meta.get("content"):
        try:
            return date_parser.parse(meta["content"])
        except:
            pass

    return None


def extract_date_from_jsonld(soup: BeautifulSoup) -> Optional[datetime]:
    """Extract date from JSON-LD structured data."""
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        try:
            data = json.loads(script.string)
            # Handle array of objects
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        date_str = item.get("datePublished") or item.get("dateCreated")
                        if date_str:
                            return date_parser.parse(date_str)
            # Handle single object
            elif isinstance(data, dict):
                date_str = data.get("datePublished") or data.get("dateCreated")
                if date_str:
                    return date_parser.parse(date_str)
                # Check nested @graph
                if "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict):
                            date_str = item.get("datePublished") or item.get("dateCreated")
                            if date_str:
                                return date_parser.parse(date_str)
        except:
            continue
    return None


def extract_date_from_time_tag(soup: BeautifulSoup) -> Optional[datetime]:
    """Extract date from <time> tags."""
    # Look for time tags with datetime attribute
    time_tags = soup.find_all("time", datetime=True)
    for tag in time_tags:
        try:
            return date_parser.parse(tag["datetime"])
        except:
            continue

    # Look for time tags with pubdate attribute
    time_tags = soup.find_all("time", pubdate=True)
    for tag in time_tags:
        try:
            if tag.get("datetime"):
                return date_parser.parse(tag["datetime"])
            elif tag.string:
                return date_parser.parse(tag.string)
        except:
            continue

    return None


def extract_date_from_visible_text(soup: BeautifulSoup) -> Optional[datetime]:
    """Extract date from visible text patterns (last resort)."""
    # Common date container classes
    date_classes = [
        "date", "published", "post-date", "article-date", "timestamp",
        "byline-date", "publish-date", "entry-date", "meta-date",
        "article__date", "article-meta", "post-meta"
    ]

    for class_name in date_classes:
        elements = soup.find_all(class_=re.compile(class_name, re.I))
        for el in elements:
            text = el.get_text(strip=True)
            try:
                # Try to parse the text as a date
                parsed = date_parser.parse(text, fuzzy=True)
                # Sanity check: date should be within the last year
                if parsed.year >= datetime.now().year - 1:
                    return parsed
            except:
                continue

    return None


def extract_publication_date(html: str, url: str) -> Optional[datetime]:
    """
    Extract publication date from HTML using multiple strategies.
    Returns None if date cannot be determined.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Try strategies in order of reliability
    strategies = [
        ("meta tags", extract_date_from_meta),
        ("JSON-LD", extract_date_from_jsonld),
        ("time tags", extract_date_from_time_tag),
        ("visible text", extract_date_from_visible_text),
    ]

    for strategy_name, strategy_func in strategies:
        try:
            date = strategy_func(soup)
            if date:
                # Ensure timezone awareness for comparison
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                return date
        except Exception as e:
            continue

    return None


def estimate_read_time(html: str) -> int:
    """Estimate reading time in minutes based on word count."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script, style, nav elements
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Get text content
    text = soup.get_text(separator=" ", strip=True)
    word_count = len(text.split())

    # ~250 words per minute
    read_time = max(1, round(word_count / 250))

    # Cap at reasonable bounds
    return min(max(read_time, 2), 20)


def is_within_48_hours(pub_date: datetime) -> bool:
    """Check if publication date is within the last 48 hours."""
    now = datetime.now(timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=timezone.utc)

    age = now - pub_date
    return age <= timedelta(hours=MAX_AGE_HOURS)


def format_date(dt: datetime) -> str:
    """Format datetime as 'Feb 2, 2026'."""
    if not hasattr(dt, 'strftime'):
        return str(dt)
    # Windows uses %#d, Linux/Mac use %-d for day without leading zero
    try:
        return dt.strftime("%b %d, %Y").replace(" 0", " ")
    except:
        return dt.strftime("%b %d, %Y")


def format_date_iso(dt: datetime) -> str:
    """Format datetime as ISO date string."""
    return dt.strftime("%Y-%m-%d")


def fetch_and_validate_article(session: requests.Session, url: str, source: str, headline: str = None) -> Optional[dict]:
    """
    Fetch an article URL and extract/validate its publication date.
    Returns validated article dict or None if invalid/stale.
    """
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        html = response.text

        # Extract publication date
        pub_date = extract_publication_date(html, url)

        # Extract headline from page if not provided
        if not headline:
            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.find("h1")
            if h1:
                headline = h1.get_text(strip=True)
            else:
                og_title = soup.find("meta", property="og:title")
                if og_title and og_title.get("content"):
                    headline = og_title["content"]
                else:
                    title = soup.find("title")
                    headline = title.get_text(strip=True) if title else "Unknown"

        # Estimate read time
        read_time = estimate_read_time(html)

        # Build result
        result = {
            "headline": headline,
            "url": url,
            "source": source,
            "estimated_read_time_min": read_time,
        }

        if pub_date:
            if is_within_48_hours(pub_date):
                result["verified_date"] = format_date_iso(pub_date)
                result["verified_date_display"] = format_date(pub_date)
                result["status"] = "valid"
            else:
                result["verified_date"] = format_date_iso(pub_date)
                result["verified_date_display"] = format_date(pub_date)
                result["status"] = "stale"
                result["rejection_reason"] = f"Article is older than {MAX_AGE_HOURS} hours"
        else:
            result["verified_date"] = "UNVERIFIED"
            result["verified_date_display"] = "⚠️ date unverified"
            result["status"] = "unverified"

        return result

    except requests.RequestException as e:
        return {
            "headline": headline or "Unknown",
            "url": url,
            "source": source,
            "verified_date": "UNVERIFIED",
            "verified_date_display": "⚠️ date unverified",
            "status": "error",
            "error": str(e),
        }
    except Exception as e:
        return {
            "headline": headline or "Unknown",
            "url": url,
            "source": source,
            "verified_date": "UNVERIFIED",
            "verified_date_display": "⚠️ date unverified",
            "status": "error",
            "error": str(e),
        }


def fetch_rss_candidates(session: requests.Session) -> list[dict]:
    """Fetch candidate articles from RSS feeds."""
    candidates = []

    for source_name, feed_url in RSS_FEEDS.items():
        try:
            print(f"  Fetching RSS: {source_name}...", file=sys.stderr)
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:10]:  # Limit per feed
                url = entry.get("link", "")
                headline = entry.get("title", "")

                if url and headline:
                    candidates.append({
                        "url": url,
                        "headline": headline,
                        "source": source_name,
                        "from_rss": True,
                        # RSS dates are often unreliable, so we'll verify from the page
                        "rss_date": entry.get("published", entry.get("updated", "")),
                    })
        except Exception as e:
            print(f"  Error fetching {source_name}: {e}", file=sys.stderr)
            continue

    return candidates


def deduplicate_candidates(candidates: list[dict]) -> list[dict]:
    """Remove duplicate URLs."""
    seen_urls = set()
    unique = []

    for candidate in candidates:
        url = candidate.get("url", "").split("?")[0].rstrip("/")  # Normalize URL
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(candidate)

    return unique


def run_phase1(output_file: str = None) -> dict:
    """
    Run Phase 1: Gather and validate articles.

    Returns a dict with:
    - valid_candidates: Articles within 48 hours with verified dates
    - unverified_candidates: Articles where date couldn't be extracted
    - stale_candidates: Articles older than 48 hours (rejected)
    - errors: Articles that couldn't be fetched
    """
    print("=" * 60, file=sys.stderr)
    print("PHASE 1: Article Validation", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    session = get_session()

    # Step 1: Gather candidates from RSS feeds
    print("\n[1/3] Fetching RSS feeds...", file=sys.stderr)
    candidates = fetch_rss_candidates(session)
    print(f"  Found {len(candidates)} candidates from RSS", file=sys.stderr)

    # Step 2: Deduplicate
    print("\n[2/3] Deduplicating...", file=sys.stderr)
    candidates = deduplicate_candidates(candidates)
    print(f"  {len(candidates)} unique candidates", file=sys.stderr)

    # Step 3: Validate each candidate
    print("\n[3/3] Validating articles (fetching and extracting dates)...", file=sys.stderr)

    valid = []
    unverified = []
    stale = []
    errors = []

    for i, candidate in enumerate(candidates):
        print(f"  [{i+1}/{len(candidates)}] {candidate['source']}: {candidate['headline'][:50]}...", file=sys.stderr)

        result = fetch_and_validate_article(
            session,
            candidate["url"],
            candidate["source"],
            candidate["headline"]
        )

        if result:
            if result["status"] == "valid":
                valid.append(result)
            elif result["status"] == "unverified":
                unverified.append(result)
            elif result["status"] == "stale":
                stale.append(result)
            else:
                errors.append(result)

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_age_hours": MAX_AGE_HOURS,
        "summary": {
            "total_candidates": len(candidates),
            "valid": len(valid),
            "unverified": len(unverified),
            "stale_rejected": len(stale),
            "errors": len(errors),
        },
        "valid_candidates": valid,
        "unverified_candidates": unverified,
        "stale_candidates": stale,
        "errors": errors,
    }

    # Print summary
    print("\n" + "=" * 60, file=sys.stderr)
    print("PHASE 1 COMPLETE", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Valid (within {MAX_AGE_HOURS}h): {len(valid)}", file=sys.stderr)
    print(f"  Unverified (date unknown): {len(unverified)}", file=sys.stderr)
    print(f"  Stale (rejected): {len(stale)}", file=sys.stderr)
    print(f"  Errors: {len(errors)}", file=sys.stderr)

    # Output JSON
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\nOutput written to: {output_file}", file=sys.stderr)
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))

    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 1: Article Validation for Morning Briefing")
    subparsers = parser.add_subparsers(dest="command")

    # Default: run full Phase 1 RSS validation
    rss_parser = subparsers.add_parser("rss", help="Run full Phase 1 RSS validation")
    rss_parser.add_argument("-o", "--output", help="Output JSON file path")

    # Tier classification check
    tier_parser = subparsers.add_parser("tier", help="Check source tier classification")
    tier_parser.add_argument("source", help="Source name to classify")
    tier_parser.add_argument("--url", default="", help="Optional URL for domain-based classification")

    # GA source tally validation
    tally_parser = subparsers.add_parser("tally", help="Validate GA source tally from JSON file")
    tally_parser.add_argument("input", help="JSON file with GA items (list of {source, headline, url})")

    # From X batch query generator
    fromx_parser = subparsers.add_parser("fromx", help="Generate batched From X search queries")
    fromx_parser.add_argument("month_year", help="Month and year, e.g. 'February 2026'")

    # Status ID validator
    sid_parser = subparsers.add_parser("statusid", help="Validate X status ID delta")
    sid_parser.add_argument("candidate_url", help="Candidate post URL")
    sid_parser.add_argument("reference_url", help="Reference post URL (known-today)")

    args = parser.parse_args()

    if args.command == "tier":
        result = classify_source_tier(args.source, args.url)
        print(json.dumps(result, indent=2))

    elif args.command == "tally":
        with open(args.input, "r") as f:
            items = json.load(f)
        result = validate_ga_source_tally(items)
        print(json.dumps(result, indent=2))

    elif args.command == "fromx":
        queries = build_from_x_batch_queries(args.month_year)
        print(f"\nFrom X Batched Search Queries ({len(queries)} queries for {len(FROM_X_HANDLES)} handles):")
        print(f"Handles: {', '.join('@' + h for h in FROM_X_HANDLES)}")
        print(f"Brand accounts (reference only): {', '.join('@' + h for h in FROM_X_BRAND_ACCOUNTS)}")
        print(f"\nReference query (find known-today post):")
        print(f"  {build_from_x_reference_query()}\n")
        for q in queries:
            print(f"Batch {q['batch_number']} ({', '.join('@' + h for h in q['handles'])}):")
            print(f"  {q['query']}\n")

    elif args.command == "statusid":
        cand_id = extract_status_id_from_url(args.candidate_url)
        ref_id = extract_status_id_from_url(args.reference_url)
        if cand_id is None:
            print(f"Error: Could not extract status ID from {args.candidate_url}")
            sys.exit(1)
        if ref_id is None:
            print(f"Error: Could not extract status ID from {args.reference_url}")
            sys.exit(1)
        result = validate_status_id_delta(cand_id, ref_id)
        print(f"Candidate: {cand_id}")
        print(f"Reference: {ref_id}")
        print(json.dumps(result, indent=2))

    elif args.command == "rss" or args.command is None:
        output = getattr(args, 'output', None)
        run_phase1(output)
