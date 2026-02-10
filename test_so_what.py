"""
Test script: Compare current system So Whats with Sonnet-generated So Whats.

Fetches the same 4 articles from today's briefing, runs them through
the new Sonnet prompt, and prints side-by-side results.
"""

import sys
import os
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add parent dir to path
sys.path.insert(0, os.path.dirname(__file__))

# Load .env for ANTHROPIC_API_KEY
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from data_collector import extract_article_text, _log
from phase1_validator import get_session, extract_publication_date
from llm_calls import LLMClient, generate_so_what, summarize_article, SONNET_MODEL

# The 4 Tier 1 stories from today's (Feb 10) briefing
TEST_ARTICLES = [
    {
        "headline": "CMS Targets Medicare Advantage Upcoding with Updated Risk Score Data",
        "url": "https://www.statnews.com/2026/02/09/medicare-advantage-new-cms-risk-scores-target-insurer-upcoding/",
        "source": "STAT News",
        "_category": "health",
        "has_paywall": True,
    },
    {
        "headline": "Kaiser Strike Grows to 34,000 Workers as Pharmacy and Lab Techs Walk Out",
        "url": "https://www.mercurynews.com/2026/02/09/kaiser-strike-expands-with-3000-pharmacy-lab-workers-joining-nurses/",
        "source": "Mercury News",
        "_category": "health",
        "has_paywall": False,
    },
    {
        "headline": "Anthropic Closing $20B Round at $350B Valuation, Nearly Doubling in Five Months",
        "url": "https://techcrunch.com/2026/02/09/anthropic-closes-in-on-20b-round/",
        "source": "TechCrunch",
        "_category": "tech",
        "has_paywall": False,
    },
    {
        "headline": "Japan's Takaichi Wins Record Supermajority, Enabling Constitutional Overhaul",
        "url": "https://www.aljazeera.com/news/2026/2/8/pm-sanae-takaichis-party-set-for-majority-in-japan-parliamentary-elections",
        "source": "Al Jazeera",
        "_category": "business",
        "has_paywall": False,
    },
]

# Current system's So Whats (from today's briefing HTML)
CURRENT_SO_WHATS = [
    # Story 1: CMS / MA Payment Policy
    (
        "This is the most significant MA payment policy change in years, and the downstream "
        "effects matter for PayZen. When MA plans get squeezed on reimbursement, providers "
        "absorb some of that pressure through lower payments -- which accelerates the shift "
        "of costs to patients. Health systems already struggling with MA margin compression "
        "will face even more urgent conversations about patient self-pay solutions. "
        "**Worth tracking which of your target health systems have heavy MA patient populations** "
        "-- they'll be the most receptive to financing conversations in Q3-Q4."
    ),

    # Story 2: Kaiser Strike
    (
        "Kaiser is the largest integrated health system in your backyard. A strike of this scale "
        "creates operational chaos -- delayed labs, pharmacy closures, diverted patients. For "
        "PayZen, the signal is less about Kaiser specifically (they're integrated payer-provider) "
        "and more about what it says about healthcare labor costs industry-wide. If 25% raises "
        "become the new baseline, every health system's margins get thinner, and the appetite "
        "for solutions that improve collections without adding headcount grows. Just worth "
        "knowing about -- this will come up in Bay Area conversations."
    ),

    # Story 3: Anthropic $350B
    (
        "**The company behind your primary AI tool just became one of the most valuable private "
        "companies in the world.** A $350B valuation with $9B revenue says the market believes "
        "Claude's enterprise moat is real. For your AI-native strategy, this is reassuring -- "
        "you're betting on a platform with staying power, not a feature that gets acqui-hired. "
        "The Nvidia and Microsoft co-investment is also interesting: it suggests Anthropic is "
        "building the kind of infrastructure partnerships that make switching costs higher for "
        "everyone in their ecosystem."
    ),

    # Story 4: Japan Election
    (
        "This is a \"you should know about this\" story -- any executive would be expected to "
        "have seen the headline. Japan is the world's fourth-largest economy, and a supermajority "
        "this large hasn't happened since the post-war era. The defense and China implications "
        "are geopolitically significant; the economic reform agenda could shift Japan's healthcare "
        "market too, though that's second-order. No action needed, just awareness."
    ),
]


def main():
    _log("=" * 60)
    _log("SO WHAT COMPARISON TEST")
    _log("=" * 60)

    # Check API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: Set ANTHROPIC_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

    client = LLMClient()
    session = get_session()

    # Fetch article text for each story
    _log("\nFetching article text...")
    for article in TEST_ARTICLES:
        url = article["url"]
        _log(f"  Fetching: {article['source']}...")
        try:
            resp = session.get(url, timeout=15, allow_redirects=True)
            html = resp.text
            article["article_text"] = extract_article_text(html)
            text_len = len(article["article_text"])
            _log(f"    Got {text_len} chars of article text")
        except Exception as e:
            _log(f"    FETCH FAILED: {e}")
            article["article_text"] = ""

    # Generate Haiku summaries first (needed as input for So What)
    _log("\nGenerating summaries (Haiku)...")
    summaries = []
    for article in TEST_ARTICLES:
        summary = summarize_article(client, article)
        summaries.append(summary)
        _log(f"  {article['source']}: {summary[:80]}...")

    # Generate So Whats (Sonnet)
    _log("\nGenerating So Whats (Sonnet)...")
    new_so_whats = []
    for article, summary in zip(TEST_ARTICLES, summaries):
        _log(f"  Generating for: {article['headline'][:50]}...")
        so_what = generate_so_what(client, article, summary)
        new_so_whats.append(so_what)

    # Print side-by-side comparison
    print("\n" + "=" * 70)
    print("SO WHAT COMPARISON: Current System (Opus) vs New Pipeline (Sonnet)")
    print("=" * 70)

    for i, (article, current, new) in enumerate(
        zip(TEST_ARTICLES, CURRENT_SO_WHATS, new_so_whats), 1
    ):
        print(f"\n{'-' * 70}")
        print(f"STORY {i}: {article['headline']}")
        print(f"Source: {article['source']} | Category: {article['_category']}")
        print(f"{'-' * 70}")

        print(f"\n  CURRENT SYSTEM (Opus, ~$77/briefing):")
        print(f"  {'-' * 40}")
        # Word wrap at ~80 chars
        words = current.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 78:
                print(line)
                line = "  " + word
            else:
                line += " " + word if line.strip() else "  " + word
        if line.strip():
            print(line)

        print(f"\n  NEW PIPELINE (Sonnet, ~$0.70/briefing):")
        print(f"  {'-' * 40}")
        words = new.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 78:
                print(line)
                line = "  " + word
            else:
                line += " " + word if line.strip() else "  " + word
        if line.strip():
            print(line)

    # Cost summary
    cost = client.get_cost_summary()
    print(f"\n{'=' * 70}")
    print("COST SUMMARY")
    print(f"{'=' * 70}")
    print(f"  API calls:     {cost['total_calls']}")
    print(f"  Input tokens:  {cost['total_input_tokens']:,}")
    print(f"  Output tokens: {cost['total_output_tokens']:,}")
    print(f"  Total cost:    ${cost['total_cost_usd']:.4f}")
    print(f"  Per So What:   ${cost['total_cost_usd'] / 4:.4f}")


if __name__ == "__main__":
    main()
