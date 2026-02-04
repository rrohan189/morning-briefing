"""
Phase 1: Article Validator for Morning Intelligence Briefing

This script fetches candidate articles from monitored sources, extracts and verifies
publication dates from actual HTML, and outputs a validated candidate list as JSON.

The LLM never decides dates — this code hands it facts.
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
    parser.add_argument("-o", "--output", help="Output JSON file path")
    args = parser.parse_args()

    run_phase1(args.output)
