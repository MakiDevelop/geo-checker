"""Report formatting utilities."""
from __future__ import annotations

import json
from typing import Literal

OutputFormat = Literal["cli", "json", "markdown"]

# Issue key to human-readable message mapping
_ISSUE_MESSAGES = {
    "crawlers_blocked": "AI crawlers are blocked by robots.txt",
    "noindex_set": "Page has noindex directive - AI cannot index",
    "no_schema": "No Schema.org structured data found",
    "weak_entry": "Weak narrative entry (missing H1/H2 or meta description)",
    "no_facts": "No enumerable facts (lists/tables) found",
    "low_readability": "Content readability is low",
    "has_faq_schema": "FAQPage schema detected",
    "has_article_schema": "Article schema detected",
    "good_lists": "Good use of lists for content organization",
    "good_definitions": "Good definition density",
    "quotable_content": "Contains quotable sentences (facts, statistics)",
}

# Fix action to human-readable message mapping
_FIX_MESSAGES = {
    "update_robots_txt": "Update robots.txt to allow AI crawlers (GPTBot, ClaudeBot, etc.)",
    "remove_noindex": "Remove noindex directive from meta robots or X-Robots-Tag",
    "add_schema": "Add Schema.org structured data (Article, FAQPage, HowTo, etc.)",
    "add_h_framing": "Add clear H1/H2 headings and meta description",
    "add_fact_list": "Add lists or tables with enumerable facts",
    "improve_readability": "Simplify sentences and improve readability score",
}


def format_report(results: dict, output: OutputFormat = "cli") -> str:
    """Format analysis results for output.

    Args:
        results: Analysis results dict containing geo, parsed content, etc.
        output: Output format - 'cli', 'json', or 'markdown'

    Returns:
        Formatted string representation of results
    """
    if output == "json":
        return _format_json(results)
    elif output == "markdown":
        return _format_markdown(results)
    else:
        return _format_cli(results)


def _format_json(results: dict) -> str:
    """Format results as JSON."""
    return json.dumps(results, ensure_ascii=False, indent=2)


def _format_cli(results: dict) -> str:
    """Format results for terminal display with Rich-compatible markup."""
    lines = []
    geo = results.get("geo", {})
    score = geo.get("geo_score", {})
    meta = results.get("meta", {})

    # Header
    title = meta.get("title", "Unknown Page")
    if len(title) > 60:
        title = title[:57] + "..."
    lines.append("[bold cyan]GEO Analysis Report[/bold cyan]")
    lines.append(f"[dim]Page:[/dim] {title}")
    lines.append("")

    # Score display
    total = score.get("total", 0)
    grade = score.get("grade", "N/A")
    grade_label = score.get("grade_label", "")

    # Color based on grade
    grade_colors = {"A": "green", "B": "blue", "C": "yellow", "D": "red", "F": "red bold"}
    grade_color = grade_colors.get(grade, "white")

    lines.append(f"[bold]GEO Score:[/bold] [{grade_color}]{total}/100 ({grade} - {grade_label})[/{grade_color}]")
    lines.append("")

    # Score breakdown
    breakdown = score.get("breakdown", {})
    lines.append("[bold]Score Breakdown:[/bold]")

    for dimension, data in breakdown.items():
        dim_score = data.get("score", 0)
        dim_max = data.get("max", 0)
        percentage = data.get("percentage", 0)

        # Progress bar
        bar_width = 20
        filled = int(bar_width * percentage / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Color based on percentage
        if percentage >= 75:
            bar_color = "green"
        elif percentage >= 50:
            bar_color = "yellow"
        else:
            bar_color = "red"

        lines.append(f"  {dimension.capitalize():15} [{bar_color}]{bar}[/{bar_color}] {dim_score}/{dim_max} ({percentage}%)")

    lines.append("")

    # AI Crawler Access
    ai_access = geo.get("ai_crawler_access", {})
    lines.append("[bold]AI Crawler Access:[/bold]")

    crawlers = [
        ("GPTBot", ai_access.get("gptbot", "unknown")),
        ("ClaudeBot", ai_access.get("claudebot", "unknown")),
        ("PerplexityBot", ai_access.get("perplexitybot", "unknown")),
        ("Google-Extended", ai_access.get("google_extended", "unknown")),
    ]

    for name, status in crawlers:
        if status == "allow":
            status_display = "[green]✓ allowed[/green]"
        elif status == "disallow":
            status_display = "[red]✗ blocked[/red]"
        else:
            status_display = "[yellow]? unspecified[/yellow]"
        lines.append(f"  {name:18} {status_display}")

    lines.append("")

    # Issues summary
    summary = geo.get("summary", {})
    issues = summary.get("issues", {})

    critical = issues.get("critical", [])
    if critical:
        lines.append("[bold red]Critical Issues:[/bold red]")
        for issue in critical:
            key = issue.get("key", "unknown")
            msg = _ISSUE_MESSAGES.get(key, key)
            if key == "crawlers_blocked":
                crawlers_list = ", ".join(issue.get("crawlers", []))
                msg = f"{msg}: {crawlers_list}"
            lines.append(f"  [red]✗[/red] {msg}")
        lines.append("")

    warnings = issues.get("warning", [])
    if warnings:
        lines.append("[bold yellow]Warnings:[/bold yellow]")
        for issue in warnings:
            key = issue.get("key", "unknown")
            msg = _ISSUE_MESSAGES.get(key, key)
            lines.append(f"  [yellow]![/yellow] {msg}")
        lines.append("")

    good = issues.get("good", [])
    if good:
        lines.append("[bold green]Good Practices:[/bold green]")
        for issue in good:
            key = issue.get("key", "unknown")
            msg = _ISSUE_MESSAGES.get(key, key)
            lines.append(f"  [green]✓[/green] {msg}")
        lines.append("")

    # Priority fixes
    fixes = summary.get("priority_fixes", [])
    if fixes:
        lines.append("[bold]Recommended Fixes:[/bold]")
        for i, fix in enumerate(fixes, 1):
            action = fix.get("action", "unknown")
            priority = fix.get("priority", "suggested")
            impact = fix.get("impact", "low")
            msg = _FIX_MESSAGES.get(action, action)

            priority_color = {"critical": "red", "recommended": "yellow", "suggested": "blue"}.get(priority, "white")
            lines.append(f"  {i}. [{priority_color}][{priority}][/{priority_color}] {msg} (impact: {impact})")
        lines.append("")

    # Interpretation type
    interpretation = geo.get("ai_usage_interpretation", {})
    interp_type = interpretation.get("type", "Unknown")
    lines.append(f"[bold]AI Interpretation Type:[/bold] {interp_type}")

    return "\n".join(lines)


def _format_markdown(results: dict) -> str:
    """Format results as Markdown."""
    lines = []
    geo = results.get("geo", {})
    score = geo.get("geo_score", {})
    meta = results.get("meta", {})

    # Header
    title = meta.get("title", "Unknown Page")
    url = results.get("url", "")
    lines.append("# GEO Analysis Report")
    lines.append("")
    lines.append(f"**Page:** {title}")
    if url:
        lines.append(f"**URL:** {url}")
    lines.append("")

    # Score
    total = score.get("total", 0)
    grade = score.get("grade", "N/A")
    grade_label = score.get("grade_label", "")
    lines.append("## GEO Score")
    lines.append("")
    lines.append(f"**{total}/100** ({grade} - {grade_label})")
    lines.append("")

    # Score breakdown table
    lines.append("### Score Breakdown")
    lines.append("")
    lines.append("| Dimension | Score | Max | Percentage |")
    lines.append("|-----------|-------|-----|------------|")

    breakdown = score.get("breakdown", {})
    for dimension, data in breakdown.items():
        dim_score = data.get("score", 0)
        dim_max = data.get("max", 0)
        percentage = data.get("percentage", 0)
        lines.append(f"| {dimension.capitalize()} | {dim_score} | {dim_max} | {percentage}% |")

    lines.append("")

    # AI Crawler Access
    lines.append("## AI Crawler Access")
    lines.append("")
    ai_access = geo.get("ai_crawler_access", {})

    lines.append("| Crawler | Status |")
    lines.append("|---------|--------|")

    crawlers = [
        ("GPTBot", ai_access.get("gptbot", "unknown")),
        ("ClaudeBot", ai_access.get("claudebot", "unknown")),
        ("PerplexityBot", ai_access.get("perplexitybot", "unknown")),
        ("Google-Extended", ai_access.get("google_extended", "unknown")),
    ]

    for name, status in crawlers:
        emoji = "✅" if status == "allow" else "❌" if status == "disallow" else "❓"
        lines.append(f"| {name} | {emoji} {status} |")

    lines.append("")

    # Issues
    summary = geo.get("summary", {})
    issues = summary.get("issues", {})

    critical = issues.get("critical", [])
    warnings = issues.get("warning", [])
    good = issues.get("good", [])

    if critical or warnings or good:
        lines.append("## Issues & Findings")
        lines.append("")

    if critical:
        lines.append("### Critical Issues")
        lines.append("")
        for issue in critical:
            key = issue.get("key", "unknown")
            msg = _ISSUE_MESSAGES.get(key, key)
            if key == "crawlers_blocked":
                crawlers_list = ", ".join(issue.get("crawlers", []))
                msg = f"{msg}: {crawlers_list}"
            lines.append(f"- ❌ {msg}")
        lines.append("")

    if warnings:
        lines.append("### Warnings")
        lines.append("")
        for issue in warnings:
            key = issue.get("key", "unknown")
            msg = _ISSUE_MESSAGES.get(key, key)
            lines.append(f"- ⚠️ {msg}")
        lines.append("")

    if good:
        lines.append("### Good Practices")
        lines.append("")
        for issue in good:
            key = issue.get("key", "unknown")
            msg = _ISSUE_MESSAGES.get(key, key)
            lines.append(f"- ✅ {msg}")
        lines.append("")

    # Priority fixes
    fixes = summary.get("priority_fixes", [])
    if fixes:
        lines.append("## Recommended Fixes")
        lines.append("")
        for i, fix in enumerate(fixes, 1):
            action = fix.get("action", "unknown")
            priority = fix.get("priority", "suggested")
            impact = fix.get("impact", "low")
            msg = _FIX_MESSAGES.get(action, action)
            lines.append(f"{i}. **[{priority.upper()}]** {msg} _(impact: {impact})_")
        lines.append("")

    # Interpretation type
    interpretation = geo.get("ai_usage_interpretation", {})
    interp_type = interpretation.get("type", "Unknown")
    lines.append("## AI Interpretation")
    lines.append("")
    lines.append(f"This page is classified as **{interp_type}**.")
    lines.append("")

    signals = interpretation.get("signals", {})
    if signals:
        lines.append("| Signal | Value |")
        lines.append("|--------|-------|")
        for key, value in signals.items():
            lines.append(f"| {key.replace('_', ' ').title()} | {value} |")

    return "\n".join(lines)
