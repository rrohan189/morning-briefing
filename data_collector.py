"""
Data Collection for Morning Intelligence Pipeline.

Collects candidate articles from all sources with $0 LLM cost:
  - RSS feeds (14 configured in phase1_validator.py)
  - Google News RSS (free keyword search for gaps)
  - DuckDuckGo (From X handle sweep + edge cases)
  - Concurrent article fetching + date validation

Reuses validation logic from phase1_validator.py (dates, tiers, age gate).

Search API cost: $0 (Google News RSS + DuckDuckGo are both free, no API key).
Upgrade path: swap DuckDuckGoBackend for SerpAPIBackend ($50/month) if needed.
"""

import base64
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from phase1_validator import (
    RSS_FEEDS,
    FROM_X_HANDLES,
    FROM_X_SEARCH_BATCHES,
    FROM_X_BRAND_ACCOUNTS,
    MAX_AGE_HOURS,
    USER_AGENT,
    REQUEST_TIMEOUT,
    get_session,
    extract_publication_date,
    estimate_read_time,
    format_date,
    format_date_iso,
    build_from_x_batch_queries,
    build_from_x_reference_query,
    validate_status_id_delta,
    extract_status_id_from_url,
    compute_age_hours,
    deduplicate_candidates,
)

# Optional: trafilatura for better article text extraction
try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

# Optional: duckduckgo_search for web search (From X + edge cases)
try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False


# =============================================================================
# CONFIGURATION
# =============================================================================

GOOGLE_NEWS_RSS_BASE = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)

# Healthcare queries (supplement the 6 healthcare RSS feeds)
HEALTHCARE_SEARCH_QUERIES = [
    "healthcare revenue cycle management",
    "patient financing healthcare billing",
    "Medicare Advantage CMS payment policy",
    "health system financial operations",
    "healthcare affordability patient cost",
]

# Tech/AI queries (supplement the 4 tech RSS feeds)
TECH_SEARCH_QUERIES = [
    "Anthropic Claude AI",
    "AI coding agent tool launch",
    "enterprise AI adoption",
    "OpenAI update",
]

# GA broadening queries (world/national news — balanced US + international)
GA_SEARCH_QUERIES = [
    # US (2 queries)
    "US politics Congress government today",
    "US economy business news today",
    # International (4 queries — ensures enough non-US candidates)
    "Europe EU policy regulation news today",
    "Asia Pacific China India news today",
    "Middle East Africa news today",
    "global health policy WHO international",
]

# Local East Bay / Tri-Valley queries
LOCAL_SEARCH_QUERIES = [
    "Danville San Ramon Dublin Pleasanton news",
    "Tri-Valley California news today",
    "East Bay news today",
    "BART Bay Area service",
    "Bay Area air quality weather alert",
]

# Ticket watch queries
TICKET_WATCH_QUERIES = [
    '"Manchester United" USA tour 2026 tickets',
    '"Taylor Swift" tour 2026 Bay Area tickets',
    '"Coldplay" 2026 Bay Area tickets',
    '"Piano Guys" 2026 Bay Area',
    "Ticketmaster Bay Area onsale this week",
    "Chase Center upcoming events",
    "Levi's Stadium events 2026",
    "Shoreline Amphitheatre events 2026",
]

# Known paywall domains
PAYWALL_DOMAINS = {
    "statnews.com", "wsj.com", "nytimes.com", "ft.com",
    "modernhealthcare.com", "theinformation.com", "bloomberg.com",
    "barrons.com", "economist.com",
}

# Domain → source name mapping (for URL-based source inference)
DOMAIN_SOURCE_MAP = {
    "statnews.com": "STAT News",
    "healthcaredive.com": "Healthcare Dive",
    "fiercehealthcare.com": "Fierce Healthcare",
    "modernhealthcare.com": "Modern Healthcare",
    "beckershospitalreview.com": "Becker's Hospital Review",
    "kffhealthnews.org": "KFF Health News",
    "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge",
    "arstechnica.com": "Ars Technica",
    "technologyreview.com": "MIT Technology Review",
    "bbc.com": "BBC", "bbc.co.uk": "BBC",
    "reuters.com": "Reuters",
    "apnews.com": "AP News",
    "npr.org": "NPR",
    "aljazeera.com": "Al Jazeera", "aljazeera.net": "Al Jazeera",
    "france24.com": "France24",
    "dw.com": "DW News",
    "nytimes.com": "New York Times",
    "wsj.com": "Wall Street Journal",
    "cnbc.com": "CNBC",
    "bloomberg.com": "Bloomberg",
    "washingtonpost.com": "Washington Post",
    "politico.com": "Politico",
    "espn.com": "ESPN",
    "nbcnews.com": "NBC News",
    "cbsnews.com": "CBS News",
    "abcnews.go.com": "ABC News",
    "cnn.com": "CNN",
    "theguardian.com": "The Guardian",
    "ft.com": "Financial Times",
    "fortune.com": "Fortune",
    "wired.com": "Wired",
    "sfchronicle.com": "SF Chronicle",
    "eastbaytimes.com": "East Bay Times",
    "mercurynews.com": "Mercury News",
    "kqed.org": "KQED",
    "patch.com": "Patch",
    "pbs.org": "PBS",
}


def _log(msg: str):
    """Log progress to stderr with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)


# =============================================================================
# SEARCH BACKENDS (pluggable — swap for SerpAPI/Brave if DDG is unreliable)
# =============================================================================

class SearchResult:
    """A single search result."""
    __slots__ = ("title", "url", "snippet", "source", "date")

    def __init__(self, title="", url="", snippet="", source="", date=""):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source
        self.date = date


class GoogleNewsRSSBackend:
    """Free news search via Google News RSS. No API key, no rate limits."""

    def __init__(self, session: requests.Session):
        self.session = session

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        url = GOOGLE_NEWS_RSS_BASE.format(query=quote_plus(query))
        try:
            feed = feedparser.parse(url)
            results = []
            for entry in feed.entries[:max_results]:
                title = entry.get("title", "")
                source_name = ""
                # Google News titles: "Article Title - Source Name"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0]
                    source_name = parts[1] if len(parts) > 1 else ""

                # <source> element is more reliable
                source_el = entry.get("source", {})
                if hasattr(source_el, "get"):
                    source_name = source_el.get("title", source_name) or source_name

                results.append(SearchResult(
                    title=title,
                    url=entry.get("link", ""),
                    snippet=entry.get("summary", ""),
                    source=source_name,
                    date=entry.get("published", ""),
                ))
            return results
        except Exception as e:
            _log(f"    Google News RSS error for '{query[:40]}': {e}")
            return []


class DuckDuckGoBackend:
    """Free web search via DuckDuckGo. No API key. Good for site:x.com queries."""

    def __init__(self):
        if not HAS_DDGS:
            _log("  Warning: duckduckgo_search not installed (pip install duckduckgo_search)")

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if not HAS_DDGS:
            return []
        try:
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", r.get("link", "")),
                    snippet=r.get("body", ""),
                )
                for r in raw
            ]
        except Exception as e:
            _log(f"    DuckDuckGo error for '{query[:40]}': {e}")
            return []

    def news_search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if not HAS_DDGS:
            return []
        try:
            with DDGS() as ddgs:
                raw = list(ddgs.news(query, max_results=max_results))
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("body", ""),
                    source=r.get("source", ""),
                    date=r.get("date", ""),
                )
                for r in raw
            ]
        except Exception as e:
            _log(f"    DuckDuckGo news error for '{query[:40]}': {e}")
            return []


# =============================================================================
# ARTICLE PROCESSING HELPERS
# =============================================================================

def resolve_google_news_url(session: requests.Session, url: str) -> Optional[str]:
    """Resolve a Google News redirect URL to the actual article URL."""
    if "news.google.com" not in url:
        return url

    # Try 1: decode from the base64 protobuf in the URL path
    decoded = _decode_google_news_url(url)
    if decoded:
        return decoded

    # Try 2: follow HTTP redirects with Google-specific headers
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://news.google.com/",
        }
        resp = session.get(url, timeout=15, allow_redirects=True, headers=headers)
        final = resp.url
        if "news.google.com" not in final and "consent.google" not in final:
            return final

        # Try 3: extract from the Google redirect page HTML
        soup = BeautifulSoup(resp.text, "html.parser")
        # Check noscript fallback
        noscript = soup.find("noscript")
        if noscript:
            a = noscript.find("a", href=True)
            if a and "google.com" not in a["href"]:
                return a["href"]
        # Check data-url attributes
        for tag in soup.find_all(attrs={"data-url": True}):
            if "google.com" not in tag["data-url"]:
                return tag["data-url"]
        # Check og:url
        og = soup.find("meta", property="og:url")
        if og and og.get("content") and "google.com" not in og["content"]:
            return og["content"]
    except Exception:
        pass

    return None


def _decode_google_news_url(url: str) -> Optional[str]:
    """Decode real article URL from Google News RSS redirect URL.
    Google encodes article URLs in a protobuf-like base64 blob."""
    if "/articles/" not in url:
        return None
    try:
        encoded = url.split("/articles/")[1].split("?")[0]
        # Try multiple padding approaches
        for pad_extra in ["", "=", "==", "==="]:
            try:
                decoded = base64.urlsafe_b64decode(encoded + pad_extra)
                # Look for http(s):// in raw decoded bytes
                idx = decoded.find(b"http")
                if idx >= 0:
                    # Extract URL bytes until a non-URL character
                    url_bytes = bytearray()
                    for b in decoded[idx:]:
                        if 32 < b < 127 and chr(b) not in ' "<>{}|\\^`[]':
                            url_bytes.append(b)
                        else:
                            break
                    candidate = url_bytes.decode("ascii", errors="ignore")
                    if candidate.startswith("http") and "google.com" not in candidate:
                        # Basic URL validation
                        parsed = urlparse(candidate)
                        if parsed.netloc and "." in parsed.netloc:
                            return candidate
            except Exception:
                continue
    except Exception:
        pass
    return None


def extract_article_text(html: str) -> str:
    """Extract main article body text from HTML.
    Returns up to ~5000 chars (enough for LLM summarization)."""
    if HAS_TRAFILATURA:
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text:
            return text[:5000]

    # Fallback: BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                      "figure", "figcaption", "form", "button"]):
        tag.decompose()

    article = soup.find("article")
    container = article if article else soup
    paragraphs = container.find_all("p")
    text = "\n\n".join(
        p.get_text(strip=True) for p in paragraphs
        if len(p.get_text(strip=True)) > 40
    )
    return text[:5000]


def detect_paywall(url: str, html: str = "") -> bool:
    """Check if an article URL is behind a paywall."""
    domain = urlparse(url).netloc.lower()
    for pd in PAYWALL_DOMAINS:
        if pd in domain:
            return True
    if html:
        # Check common paywall indicators
        html_lower = html[:5000].lower()
        if any(indicator in html_lower for indicator in [
            "subscribe to read", "subscribers only", "paywall",
            "content_tier", "metered", "premium content",
        ]):
            return True
    return False


def infer_source_from_url(url: str) -> str:
    """Infer source name from URL domain."""
    domain = urlparse(url).netloc.lower().replace("www.", "")
    for d, name in DOMAIN_SOURCE_MAP.items():
        if d in domain:
            return name
    # Fallback: capitalize first part of domain
    parts = domain.split(".")
    return parts[0].title() if parts else "Unknown"


def _extract_date_method(html: str, url: str) -> str:
    """Determine which date extraction method succeeded."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("meta", property="article:published_time"):
        return "meta article:published_time"
    if soup.find("meta", property="og:published_time"):
        return "meta og:published_time"
    scripts = soup.find_all("script", type="application/ld+json")
    for s in scripts:
        if s.string and "datePublished" in (s.string or ""):
            return "JSON-LD datePublished"
    if soup.find("time", datetime=True):
        return "time tag"
    return "visible text / heuristic"


# =============================================================================
# MANDATORY SOURCE LISTS
# =============================================================================

MANDATORY_HEALTHCARE_SOURCES = [
    "Healthcare Dive",
    "STAT News",
    "Modern Healthcare",
    "Becker's Hospital Review",
    "Fierce Healthcare",
]


def build_healthcare_log(all_articles: list[dict]) -> list[dict]:
    """Build Healthcare Candidate Log showing all 5 mandatory sources."""
    log = []
    for source in MANDATORY_HEALTHCARE_SOURCES:
        matches = [
            a for a in all_articles
            if source.lower() in a.get("source", "").lower()
        ]
        if matches:
            # Prefer valid over stale/error
            valid = [m for m in matches if m.get("verdict") == "PASS"]
            best = valid[0] if valid else matches[0]
            log.append({
                "source": source,
                "headline": best.get("headline", ""),
                "verified_date": best.get("verified_date"),
                "age_hours": best.get("age_hours"),
                "verdict": best.get("verdict", "REJECT"),
                "reason": "Fresh article found" if best.get("verdict") == "PASS"
                    else best.get("rejection_reason", "No fresh articles"),
            })
        else:
            log.append({
                "source": source,
                "headline": "(no articles found)",
                "verified_date": None,
                "age_hours": None,
                "verdict": "No results",
                "reason": "No articles surfaced within search window",
            })
    return log


# =============================================================================
# DATA COLLECTOR
# =============================================================================

class DataCollector:
    """
    Collects candidate articles from all configured sources.

    Cost: $0 (RSS feeds + Google News RSS + DuckDuckGo = all free).
    Speed: ~2-4 minutes (concurrent article fetching).
    """

    def __init__(self, max_workers: int = 8):
        self.session = get_session()
        self.max_workers = max_workers
        self.delivery_time = datetime.now(timezone.utc)

        # Search backends
        self.gnews = GoogleNewsRSSBackend(self.session)
        self.ddg = DuckDuckGoBackend() if HAS_DDGS else None

        # Stats (keys match bucket names from _validate_concurrent)
        self.stats = {
            "rss_candidates": 0,
            "search_candidates": 0,
            "from_x_searches": 0,
            "local_candidates": 0,
            "total_validated": 0,
            "valid": 0,
            "stale": 0,
            "unverified": 0,
            "error": 0,
        }

    def collect_all(self) -> dict:
        """
        Run the full collection pipeline.

        Returns structured dict with all candidates and metadata,
        ready for Phase 1 JSON assembly by run_pipeline.py.
        """
        _log("=" * 60)
        _log("DATA COLLECTION PIPELINE")
        _log("=" * 60)

        # 1. RSS feeds
        _log("\n[1/5] RSS feeds...")
        rss = self._collect_rss()

        # 2. News search (healthcare gaps, tech, GA)
        _log("\n[2/5] News search (Google News RSS)...")
        search = self._collect_news_search()

        # 3. From X handle sweep
        _log("\n[3/5] From X handle sweep...")
        from_x = self._collect_from_x()

        # 4. Local news
        _log("\n[4/5] Local news...")
        local = self._collect_local()

        # 5. Ticket watch
        _log("\n[5/5] Ticket watch...")
        ticket_watch = self._collect_ticket_watch()

        # Merge and deduplicate article candidates
        all_raw = rss + search + local
        all_raw = deduplicate_candidates(all_raw)
        _log(f"\n  Total unique article candidates: {len(all_raw)}")

        # Validate all articles concurrently (fetch HTML, extract dates, age gate)
        _log("\nValidating articles (concurrent fetch)...")
        validated = self._validate_concurrent(all_raw)

        _log(f"\n{'=' * 60}")
        _log("COLLECTION COMPLETE")
        _log(f"{'=' * 60}")
        _log(f"  Valid:      {self.stats['valid']}")
        _log(f"  Stale:      {self.stats['stale']}")
        _log(f"  Unverified: {self.stats['unverified']}")
        _log(f"  Errors:     {self.stats['error']}")
        _log(f"  From X:     {len(from_x['candidates'])} candidates")

        return {
            "delivery_time": self.delivery_time.isoformat(),
            "valid_articles": validated["valid"],
            "stale_articles": validated["stale"],
            "unverified_articles": validated["unverified"],
            "error_articles": validated["error"],
            "from_x": from_x,
            "ticket_watch": ticket_watch,
            "stats": self.stats,
        }

    # ---- RSS FEEDS ----

    def _collect_rss(self) -> list[dict]:
        candidates = []
        for source_name, feed_url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(feed_url)
                count = 0
                for entry in feed.entries[:10]:
                    url = entry.get("link", "")
                    headline = entry.get("title", "")
                    if url and headline:
                        candidates.append({
                            "url": url,
                            "headline": headline,
                            "source": source_name,
                            "collection_method": "rss",
                        })
                        count += 1
                _log(f"  {source_name}: {count} items")
                self.stats["rss_candidates"] += count
            except Exception as e:
                _log(f"  {source_name}: ERROR — {e}")
        return candidates

    # ---- NEWS SEARCH ----

    def _collect_news_search(self) -> list[dict]:
        """Search for additional articles via DDG news (real URLs) or Google News RSS."""
        candidates = []

        query_groups = [
            ("Healthcare", HEALTHCARE_SEARCH_QUERIES),
            ("Tech/AI", TECH_SEARCH_QUERIES),
            ("GA", GA_SEARCH_QUERIES),
        ]

        for group_name, queries in query_groups:
            _log(f"  {group_name} queries...")
            group_count = 0
            for query in queries:
                results = []
                # Prefer DDG news search (returns real URLs, not Google redirects)
                if self.ddg and HAS_DDGS:
                    results = self.ddg.news_search(query, max_results=5)
                    time.sleep(0.8)  # DDG rate limit
                # Fallback to Google News RSS
                if not results:
                    results = self.gnews.search(query, max_results=5)
                    time.sleep(0.3)

                for r in results:
                    # Skip Google News redirect URLs (can't be resolved reliably)
                    if "news.google.com" in r.url:
                        continue
                    candidates.append({
                        "url": r.url,
                        "headline": r.title,
                        "source": r.source or "",
                        "collection_method": "ddg_news" if self.ddg else "google_news_rss",
                        "search_query": query,
                    })
                group_count += len(results)
            _log(f"    → {group_count} results")
            self.stats["search_candidates"] += group_count

        return candidates

    # ---- FROM X ----

    def _collect_from_x(self) -> dict:
        """Sweep From X handles using keyword-based search queries.

        DDG doesn't support site:x.com well, so we use two strategies:
          1. Per-handle keyword search: "handle_name x.com/status" (3-4 handles per query)
          2. Filter results for x.com/handle/status URLs
          3. Validate via status ID delta against reference post
        """
        result = {
            "candidates": [],
            "handle_sweep_report": {
                "handles_searched": [f"@{h}" for h in FROM_X_HANDLES],
                "handles_with_results": [],
                "handles_no_recent_results": [],
                "reference_post": None,
                "total_search_calls": 0,
            },
        }

        if not self.ddg and not HAS_DDGS:
            _log("  Warning: DuckDuckGo not available — From X sweep skipped")
            _log("    Install: pip install duckduckgo_search")
            result["handle_sweep_report"]["handles_no_recent_results"] = [
                f"@{h}" for h in FROM_X_HANDLES
            ]
            return result

        month_year = self.delivery_time.strftime("%B %Y")
        year_month_short = self.delivery_time.strftime("%Y")

        # Step 1: Find reference post (brand account for status ID baseline)
        _log("  Finding reference post...")
        ref_brands = list(FROM_X_BRAND_ACCOUNTS)[:3]
        ref_query = " OR ".join(f'"{b}" x.com status' for b in ref_brands)
        ref_query += f" {year_month_short}"
        ref_results = self.ddg.search(ref_query, max_results=10)
        result["handle_sweep_report"]["total_search_calls"] += 1
        self.stats["from_x_searches"] += 1
        time.sleep(1)

        reference_id = None
        reference_handle = None
        for r in ref_results:
            sid = extract_status_id_from_url(r.url)
            if sid:
                reference_id = sid
                match = re.search(r"x\.com/(\w+)/status", r.url)
                reference_handle = f"@{match.group(1)}" if match else "Unknown"
                result["handle_sweep_report"]["reference_post"] = {
                    "handle": reference_handle,
                    "status_id": reference_id,
                    "url": r.url,
                    "note": "Brand account — reference only",
                }
                _log(f"    Reference: {reference_handle} (ID: {reference_id})")
                break

        if not reference_id:
            _log("    Warning: No reference post found — status ID validation unavailable")

        # Step 2: Search for each handle individually (DDG doesn't batch site: well)
        # Group handles into small batches of 2 for OR queries
        handles_with_results = set()
        seen_status_ids = set()
        handle_list = list(FROM_X_HANDLES)

        # Build per-handle search queries (individual for better DDG results)
        batch_size = 2
        batches = []
        for i in range(0, len(handle_list), batch_size):
            batch_handles = handle_list[i:i + batch_size]
            batches.append(batch_handles)

        for batch_num, batch_handles in enumerate(batches, 1):
            handles_str = ", ".join(f"@{h}" for h in batch_handles)
            _log(f"  Batch {batch_num}/{len(batches)}: {handles_str}")

            # Strategy: search for handle names with "x.com" as keyword
            handle_clauses = " OR ".join(f'"{h}"' for h in batch_handles)
            query = f'({handle_clauses}) x.com/status {year_month_short}'

            search_results = self.ddg.search(query, max_results=10)
            result["handle_sweep_report"]["total_search_calls"] += 1
            self.stats["from_x_searches"] += 1
            time.sleep(1)  # Rate limit for DDG

            # Also try news search for these handles (may surface x.com links)
            if self.ddg:
                for h in batch_handles:
                    news_results = self.ddg.news_search(f"@{h} tweet", max_results=3)
                    # Filter for x.com URLs only
                    for r in news_results:
                        if "x.com" in r.url and "/status/" in r.url:
                            search_results.append(r)
                    time.sleep(0.5)
                    result["handle_sweep_report"]["total_search_calls"] += 1

            for r in search_results:
                # Only accept x.com/handle/status URLs
                if "x.com" not in r.url or "/status/" not in r.url:
                    continue

                sid = extract_status_id_from_url(r.url)
                if not sid or sid in seen_status_ids:
                    continue
                seen_status_ids.add(sid)

                # Extract handle from URL
                match = re.search(r"x\.com/(\w+)/status", r.url)
                if not match:
                    continue
                handle = match.group(1)

                # Skip brand accounts
                if handle in FROM_X_BRAND_ACCOUNTS:
                    continue

                # Validate status ID delta
                delta_result = None
                if reference_id:
                    delta_result = validate_status_id_delta(sid, reference_id)
                    if delta_result["verdict"] == "REJECT":
                        _log(f"    REJECT @{handle} — delta: {delta_result['delta_display']}")
                        continue

                handles_with_results.add(f"@{handle}")
                result["candidates"].append({
                    "handle": f"@{handle}",
                    "status_id": sid,
                    "url": r.url,
                    "topic": r.title or r.snippet,
                    "reference_id": reference_id,
                    "reference_source": reference_handle,
                    "delta_raw": delta_result["delta"] if delta_result else None,
                    "delta_display": delta_result["delta_display"] if delta_result else "N/A",
                    "verdict": delta_result["verdict"] if delta_result else "UNVERIFIED",
                })
                _log(f"    PASS @{handle}: {(r.title or r.snippet)[:60]}...")

        # Sweep report
        result["handle_sweep_report"]["handles_with_results"] = sorted(handles_with_results)
        result["handle_sweep_report"]["handles_no_recent_results"] = [
            f"@{h}" for h in FROM_X_HANDLES
            if f"@{h}" not in handles_with_results
        ]

        _log(f"  → {len(result['candidates'])} From X candidates")
        _log(f"  → Handles with results: {len(handles_with_results)}/{len(FROM_X_HANDLES)}")

        return result

    # ---- LOCAL NEWS ----

    def _collect_local(self) -> list[dict]:
        candidates = []
        for query in LOCAL_SEARCH_QUERIES:
            results = []
            # Prefer DDG news for real URLs
            if self.ddg and HAS_DDGS:
                results = self.ddg.news_search(query, max_results=5)
                time.sleep(0.8)
            if not results:
                results = self.gnews.search(query, max_results=5)
                time.sleep(0.3)

            for r in results:
                if "news.google.com" in r.url:
                    continue
                candidates.append({
                    "url": r.url,
                    "headline": r.title,
                    "source": r.source or "",
                    "collection_method": "ddg_news" if self.ddg else "google_news_rss",
                    "search_query": query,
                    "is_local": True,
                })
            self.stats["local_candidates"] += len(results)
        _log(f"  → {self.stats['local_candidates']} local candidates")
        return candidates

    # ---- TICKET WATCH ----

    def _collect_ticket_watch(self) -> dict:
        watch = {}
        for query in TICKET_WATCH_QUERIES:
            # Extract artist/venue name
            if '"' in query:
                key = query.split('"')[1]
            else:
                key = query[:30]

            results = []
            if self.ddg:
                results = self.ddg.search(query, max_results=3)
                time.sleep(0.5)

            if results:
                watch[key] = {
                    "found": True,
                    "results": [
                        {"title": r.title, "url": r.url, "snippet": r.snippet}
                        for r in results[:2]
                    ],
                }
                _log(f"  {key}: {len(results)} results")
            else:
                watch[key] = {"found": False, "note": "No results found"}
                _log(f"  {key}: no results")

        return watch

    # ---- CONCURRENT ARTICLE VALIDATION ----

    def _validate_concurrent(self, candidates: list[dict]) -> dict:
        """Fetch and validate all candidates concurrently."""
        buckets = {"valid": [], "stale": [], "unverified": [], "error": []}
        total = len(candidates)

        def validate_one(candidate: dict) -> tuple[str, dict]:
            url = candidate.get("url", "")
            source = candidate.get("source", "")
            headline = candidate.get("headline", "")
            is_local = candidate.get("is_local", False)

            # Resolve Google News redirect URLs
            if "news.google.com" in url:
                resolved = resolve_google_news_url(self.session, url)
                if resolved:
                    url = resolved
                else:
                    return "error", {
                        "headline": headline, "url": candidate["url"],
                        "source": source, "status": "error",
                        "verdict": "REJECT",
                        "error": "Could not resolve Google News redirect",
                    }

            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                resp.raise_for_status()
                html = resp.text
                final_url = resp.url

                # Extract publication date from HTML
                pub_date = extract_publication_date(html, final_url)

                # Extract headline if not provided
                if not headline:
                    soup = BeautifulSoup(html, "html.parser")
                    h1 = soup.find("h1")
                    if h1:
                        headline = h1.get_text(strip=True)
                    else:
                        og = soup.find("meta", property="og:title")
                        headline = og["content"] if og and og.get("content") else "Unknown"

                # Infer source from URL if empty
                if not source or source == "Unknown":
                    source = infer_source_from_url(final_url)

                # Build result
                result = {
                    "headline": headline,
                    "url": final_url,
                    "source": source,
                    "estimated_read_time_min": estimate_read_time(html),
                    "has_paywall": detect_paywall(final_url, html),
                    "article_text": extract_article_text(html),
                    "collection_method": candidate.get("collection_method", "unknown"),
                    "is_local": is_local,
                }

                if pub_date:
                    age = compute_age_hours(pub_date.isoformat(), self.delivery_time)
                    result["verified_date"] = format_date_iso(pub_date)
                    result["verified_date_display"] = format_date(pub_date)
                    result["age_hours"] = age
                    result["date_method"] = _extract_date_method(html, final_url)

                    if age is not None and age <= MAX_AGE_HOURS:
                        result["verdict"] = "PASS"
                        return "valid", result
                    else:
                        result["verdict"] = "REJECT"
                        result["rejection_reason"] = (
                            f"Article is {age} hours old (max {MAX_AGE_HOURS})"
                        )
                        return "stale", result
                else:
                    result["verified_date"] = None
                    result["age_hours"] = None
                    result["verdict"] = "REJECT"
                    result["rejection_reason"] = "Could not extract publication date"
                    return "unverified", result

            except requests.RequestException as e:
                return "error", {
                    "headline": headline, "url": url, "source": source,
                    "verdict": "REJECT", "error": str(e),
                }
            except Exception as e:
                return "error", {
                    "headline": headline, "url": url, "source": source,
                    "verdict": "REJECT", "error": str(e),
                }

        # Run with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(validate_one, c): c for c in candidates}
            done_count = 0

            for future in as_completed(futures):
                done_count += 1
                try:
                    category, result = future.result()
                    buckets[category].append(result)
                    self.stats[category] += 1
                    if category == "valid":
                        _log(
                            f"  [{done_count}/{total}] ✓ "
                            f"{result.get('source', '?')}: "
                            f"{result.get('headline', '?')[:50]}..."
                        )
                    elif category == "stale":
                        _log(
                            f"  [{done_count}/{total}] ✗ STALE "
                            f"{result.get('source', '?')}: "
                            f"{result.get('headline', '?')[:50]}..."
                        )
                    # Silently count errors and unverified to reduce noise
                except Exception as e:
                    _log(f"  [{done_count}/{total}] ✗ Validation exception: {e}")
                    self.stats["error"] += 1

        self.stats["total_validated"] = total

        # Summary of errors (avoid per-item spam)
        error_count = len(buckets["error"])
        if error_count > 0:
            google_errors = sum(
                1 for e in buckets["error"]
                if "Google News" in str(e.get("error", ""))
            )
            other_errors = error_count - google_errors
            if google_errors:
                _log(f"  ({google_errors} Google News URLs could not be resolved)")
            if other_errors:
                _log(f"  ({other_errors} articles had fetch errors)")

        return buckets


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    _log("Running data collector standalone test...\n")

    if not HAS_DDGS:
        _log("⚠ duckduckgo_search not installed — From X will be skipped")
        _log("  Install: pip install duckduckgo_search\n")
    if not HAS_TRAFILATURA:
        _log("⚠ trafilatura not installed — using BeautifulSoup for text extraction")
        _log("  Install: pip install trafilatura\n")

    collector = DataCollector()
    results = collector.collect_all()

    print(f"\n{'=' * 40}")
    print(f"RESULTS SUMMARY")
    print(f"{'=' * 40}")
    print(f"Valid articles:     {len(results['valid_articles'])}")
    print(f"Stale (rejected):   {len(results['stale_articles'])}")
    print(f"Unverified:         {len(results['unverified_articles'])}")
    print(f"Errors:             {len(results['error_articles'])}")
    print(f"From X candidates:  {len(results['from_x']['candidates'])}")
    print(f"Ticket watch items: {len(results['ticket_watch'])}")

    if results["valid_articles"]:
        print(f"\nTop 5 valid articles:")
        for a in results["valid_articles"][:5]:
            print(f"  [{a.get('age_hours', '?')}h] {a['source']}: {a['headline'][:60]}...")
