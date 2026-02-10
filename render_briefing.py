"""
HTML Renderer for Morning Intelligence Pipeline.

Session 3 deliverable: renders LLM output JSON into HTML matching
the reference template (morning-briefing-template.html).

Uses Python string formatting (no Jinja2 dependency needed).
CSS is copied verbatim from the reference template for pixel-perfect match.
"""

import html
import re
from datetime import datetime


def render_html(briefing_data: dict) -> str:
    """
    Render the complete briefing HTML from structured LLM output.

    Args:
        briefing_data: Output from llm_calls.run_phase2_llm(), containing:
            header, today_30_seconds, tier1_stories, from_x,
            general_awareness, local, ticket_watch, sources_list

    Returns:
        Complete HTML string ready for email delivery.
    """
    header = briefing_data.get("header", {})
    date_display = header.get("date_display", "")
    deep_reads = header.get("deep_reads", 0)
    total_minutes = header.get("total_minutes", 0)

    # ---- Today in 30 Seconds ----
    topline_items = ""
    for item in briefing_data.get("today_30_seconds", []):
        bold = _esc(item.get("bold_fact", ""))
        impl = _esc(item.get("implication", ""))
        topline_items += (
            f'      <li><strong>{bold}</strong> &mdash; {impl}</li>\n'
        )

    # ---- Tier 1 Stories (grouped by section) ----
    stories = briefing_data.get("tier1_stories", [])
    health_stories = [s for s in stories if s.get("section") == "health"]
    tech_stories = [s for s in stories if s.get("section") == "tech"]
    biz_stories = [s for s in stories if s.get("section") == "business"]

    stories_html = ""
    story_num = 1

    if health_stories:
        stories_html += _section_header("\U0001f3e5 Health Tech")
        for s in health_stories:
            stories_html += _render_story(s, story_num)
            story_num += 1

    if tech_stories:
        stories_html += _section_header("\u26a1 Tech &amp; AI")
        for s in tech_stories:
            stories_html += _render_story(s, story_num)
            story_num += 1

    if biz_stories:
        stories_html += _section_header("\U0001f4b0 Business &amp; Strategy")
        for s in biz_stories:
            stories_html += _render_story(s, story_num)
            story_num += 1

    # ---- From X ----
    from_x_html = ""
    from_x_posts = briefing_data.get("from_x", [])
    if from_x_posts:
        posts_html = ""
        for post in from_x_posts:
            handle = _esc(post.get("handle", ""))
            url = _esc(post.get("url", "#"))
            summary = _esc(post.get("summary", ""))
            posts_html += (
                f'    <div class="from-x-post">\n'
                f'      <a href="{url}" class="from-x-handle">{handle}</a> &mdash;\n'
                f'      <span class="from-x-context">{summary}</span>\n'
                f'    </div>\n\n'
            )

        from_x_html = (
            f'  <!-- FROM X -->\n'
            f'  <div class="from-x">\n'
            f'    <div class="from-x-title">\U0001f426 From X</div>\n'
            f'    <div class="from-x-subtitle">What AI Twitter is talking about today.</div>\n\n'
            f'{posts_html}'
            f'  </div>\n'
        )

    # ---- General Awareness ----
    ga_items_html = ""
    for item in briefing_data.get("general_awareness", []):
        flag = item.get("flag", "\U0001f1fa\U0001f1f8")
        headline = _esc(item.get("headline", ""))
        url = _esc(item.get("url", "#"))
        context = _esc(item.get("context", ""))
        source = _esc(item.get("source", ""))
        date = _esc(item.get("date_display", ""))
        read_time = item.get("read_time_min", 3)
        paywall = " &middot; \U0001f512" if item.get("has_paywall") else ""

        ga_items_html += (
            f'    <div class="ga-item">\n'
            f'      <div class="ga-flag">{flag}</div>\n'
            f'      <div class="ga-content">\n'
            f'        <a href="{url}" class="ga-headline">{headline}</a> &mdash;\n'
            f'        <span class="ga-context">{context}</span>\n'
            f'      </div>\n'
            f'      <div class="ga-source">{source} &middot; {date} &middot; {read_time}m{paywall}</div>\n'
            f'    </div>\n\n'
        )

    # ---- Local ----
    local_html = ""
    local_items = briefing_data.get("local", [])
    ticket_watch = briefing_data.get("ticket_watch")
    if local_items or ticket_watch:
        local_items_html = ""
        for item in local_items:
            headline = _esc(item.get("headline", ""))
            url = _esc(item.get("url", "#"))
            context = _esc(item.get("context", ""))
            source = _esc(item.get("source", ""))
            date = _esc(item.get("date_display", ""))

            local_items_html += (
                f'    <div class="local-item">\n'
                f'      <div class="local-pin">\U0001f4cd</div>\n'
                f'      <div class="local-content">\n'
                f'        <a href="{url}" class="local-headline">{headline}</a> &mdash;\n'
                f'        <span class="local-context">{context}</span>\n'
                f'        <div class="local-source">{source} &middot; {date}</div>\n'
                f'      </div>\n'
                f'    </div>\n\n'
            )

        local_html = (
            f'  <!-- LOCAL -->\n'
            f'  <div class="local-section">\n'
            f'    <div class="local-title">\U0001f4cd Local &mdash; East Bay</div>\n'
            f'    <div class="local-subtitle">What\'s happening around you.</div>\n\n'
            f'{local_items_html}'
            f'  </div>\n'
        )

    # ---- Sources list ----
    sources = " &middot; ".join(_esc(s) for s in briefing_data.get("sources_list", []))

    # ---- Assemble full HTML ----
    return TEMPLATE.format(
        date_display=_esc(date_display),
        deep_reads=deep_reads,
        total_minutes=total_minutes,
        topline_items=topline_items,
        stories_html=stories_html,
        from_x_html=from_x_html,
        ga_items_html=ga_items_html,
        local_html=local_html,
        sources=sources,
    )


def _esc(text: str) -> str:
    """HTML-escape text but preserve markdown bold (**text**)."""
    if not text:
        return ""
    escaped = html.escape(str(text))
    # Convert **bold** to <strong>bold</strong>
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    return escaped


def _section_header(label: str) -> str:
    return (
        f'\n  <div class="section-header">\n'
        f'    <div class="section-label">{label}</div>\n'
        f'  </div>\n'
    )


def _render_story(story: dict, num: int) -> str:
    alt_class = " story-alt" if num % 2 == 0 else ""
    headline = _esc(story.get("headline", ""))
    url = _esc(story.get("url", "#"))
    source = _esc(story.get("source", ""))
    date = _esc(story.get("date_display", ""))
    read_time = story.get("read_time_min", 5)
    summary = _esc(story.get("summary", ""))
    so_what = _esc(story.get("so_what", ""))

    paywall_html = ""
    if story.get("has_paywall"):
        paywall_html = (
            '      <span class="divider">&middot;</span>\n'
            '      <span class="paywall-badge">\U0001f512 paywall</span>\n'
        )

    return (
        f'\n  <div class="story{alt_class}">\n'
        f'    <div class="story-headline-row">\n'
        f'      <div class="story-number">{num:02d}</div>\n'
        f'      <div class="story-headline"><a href="{url}">{headline}</a></div>\n'
        f'    </div>\n'
        f'    <div class="story-meta">\n'
        f'      <span class="source">{source}</span>\n'
        f'      <span class="divider">&middot;</span>\n'
        f'      {date}\n'
        f'      <span class="divider">&middot;</span>\n'
        f'      {read_time} min read\n'
        f'{paywall_html}'
        f'    </div>\n'
        f'    <div class="story-summary">\n'
        f'      {summary}\n'
        f'    </div>\n'
        f'    <div class="so-what">\n'
        f'      <div class="so-what-label">So What</div>\n'
        f'      <p>{so_what}</p>\n'
        f'    </div>\n'
        f'  </div>\n'
    )


# =============================================================================
# FULL HTML TEMPLATE (CSS from morning-briefing-template.html)
# =============================================================================

TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Morning Intelligence</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=Source+Sans+3:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
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
    margin-bottom: 6px;
  }}

  .masthead {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #2c2c2c;
    display: inline;
  }}

  .edition-label {{
    font-size: 12px;
    font-weight: 500;
    color: #999;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-left: 12px;
    display: inline;
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

  .from-x {{
    padding: 28px 40px;
    border-top: 1px solid #e8e6e1;
    border-bottom: 1px solid #e8e6e1;
  }}

  .from-x-title {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #888;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
  }}

  .from-x-title::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: #e8e6e1;
  }}

  .from-x-subtitle {{
    font-size: 12px;
    color: #aaa;
    font-style: italic;
    margin-bottom: 18px;
  }}

  .from-x-post {{
    padding: 10px 0;
    border-bottom: 1px solid #f0eeeb;
    font-size: 14px;
    line-height: 1.6;
  }}

  .from-x-post:last-child {{
    border-bottom: none;
  }}

  .from-x-handle {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 500;
    color: #b8860b;
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color 0.2s;
  }}

  .from-x-handle:hover {{
    border-bottom-color: #b8860b;
  }}

  .from-x-context {{
    color: #555;
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

  .local-section {{
    padding: 32px 40px;
    background: #f7f9f7;
    border-top: 1px solid #e8e6e1;
  }}

  .local-title {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 4px;
  }}

  .local-subtitle {{
    font-size: 12px;
    color: #aaa;
    font-style: italic;
    margin-bottom: 18px;
  }}

  .local-item {{
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 9px 0;
    border-bottom: 1px solid #f0eeea;
  }}

  .local-item:last-child {{
    border-bottom: none;
  }}

  .local-pin {{
    font-size: 14px;
    flex-shrink: 0;
  }}

  .local-content {{
    font-size: 14px;
    line-height: 1.5;
    color: #1a1a1a;
  }}

  .local-headline {{
    color: #1a1a1a;
    font-weight: 600;
    text-decoration: none;
  }}

  .local-headline:hover {{
    text-decoration: underline;
  }}

  .local-context {{
    color: #555;
  }}

  .local-source {{
    font-size: 11px;
    color: #999;
    margin-top: 2px;
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
    .header, .topline, .section-header, .story, .from-x, .general-awareness, .local-section, .footer {{
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
    <div class="date-line">{date_display} &middot; <span>{deep_reads} deep reads</span> &middot; ~{total_minutes} min total</div>
  </div>

  <!-- TODAY IN 30 SECONDS -->
  <div class="topline">
    <div class="topline-title">Today in 30 Seconds</div>
    <ul class="topline-items">
{topline_items}    </ul>
  </div>

{stories_html}

{from_x_html}

  <!-- GENERAL AWARENESS -->
  <div class="general-awareness">
    <div class="ga-title">\U0001f30d General Awareness</div>
    <div class="ga-subtitle">So you're never caught off guard.</div>

{ga_items_html}
  </div>

{local_html}

  <!-- FOOTER -->
  <div class="footer">
    <div class="footer-sources">
      Sources: {sources}
    </div>
    <div class="footer-note"><span>\U0001f512</span> = paywall &middot; Built with <span>\u2660</span> by Digital Chief of Staff</div>
  </div>

</div>

</body>
</html>
'''
