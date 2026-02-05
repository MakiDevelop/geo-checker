"""CLI commands."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from src.fetcher.html_fetcher import fetch_html
from src.geo.geo_checker import check_geo
from src.parser.content_parser import parse_content
from src.report.formatter import OutputFormat, format_report
from src.seo.seo_checker import check_seo

app = typer.Typer(
    add_completion=False,
    help="GEO Checker - Analyze web pages for AI/LLM optimization",
)
console = Console()


@app.command()
def run(
    target: str = typer.Argument(..., help="URL to analyze"),
    output: str = typer.Option(
        "cli",
        "--output",
        "-o",
        help="Output format: cli, json, markdown",
    ),
    save: str | None = typer.Option(
        None,
        "--save",
        "-s",
        help="Save report to file",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed analysis information",
    ),
) -> None:
    """Analyze a URL for GEO (Generative Engine Optimization).

    Examples:
        geo-checker run https://example.com
        geo-checker run https://example.com -o json
        geo-checker run https://example.com -o markdown -s report.md
    """
    # Validate output format
    if output not in ("cli", "json", "markdown"):
        console.print(f"[red]Error:[/red] Invalid output format '{output}'. Use cli, json, or markdown.")
        raise typer.Exit(1)

    output_format: OutputFormat = output  # type: ignore

    console.print(Panel.fit(
        f"[bold cyan]GEO Checker[/bold cyan]\n[dim]Analyzing:[/dim] {target}",
        border_style="cyan",
    ))

    try:
        # Step 1: Fetch HTML
        with console.status("[bold blue]Fetching page...", spinner="dots"):
            html = fetch_html(target)

        if verbose:
            console.print(f"[dim]Fetched {len(html):,} bytes[/dim]")

        # Step 2: Parse content
        with console.status("[bold blue]Parsing content...", spinner="dots"):
            parsed = parse_content(html, target)

        if verbose:
            stats = parsed.get("stats", {})
            console.print(f"[dim]Parsed: {stats.get('word_count', 0)} words, {stats.get('heading_count', 0)} headings[/dim]")

        # Step 3: Run GEO checks
        with console.status("[bold blue]Running GEO analysis...", spinner="dots"):
            geo_results = check_geo(parsed, html, target)

        # Step 4: Run SEO checks (supplementary)
        with console.status("[bold blue]Running SEO checks...", spinner="dots"):
            seo_results = check_seo(parsed, html)

        # Combine results
        results = {
            **parsed,
            "url": target,
            "geo": geo_results,
            "seo": seo_results,
        }

        # Format output
        report = format_report(results, output_format)

        # Display or save
        if save:
            save_path = Path(save)
            save_path.write_text(report, encoding="utf-8")
            console.print(f"\n[green]Report saved to:[/green] {save_path}")
        else:
            console.print("")
            if output_format == "cli":
                # CLI format uses Rich markup
                console.print(report)
            else:
                # JSON/Markdown - print raw
                console.print(report, markup=False)

        # Exit with appropriate code based on grade
        grade = geo_results.get("geo_score", {}).get("grade", "F")
        if grade in ("D", "F"):
            raise typer.Exit(1)

    except ValueError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"\n[red]Runtime Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Unexpected error:[/red] {e}")
        if verbose:
            import traceback
            console.print(traceback.format_exc())
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    console.print("[bold]GEO Checker[/bold] v2.0.0")
    console.print("[dim]Generative Engine Optimization analyzer[/dim]")


@app.command()
def check(
    target: str = typer.Argument(..., help="URL to quick-check"),
) -> None:
    """Quick check - returns only the GEO score and grade.

    Example:
        geo-checker check https://example.com
    """
    try:
        with console.status("[bold blue]Analyzing...", spinner="dots"):
            html = fetch_html(target)
            parsed = parse_content(html, target)
            geo_results = check_geo(parsed, html, target)

        score = geo_results.get("geo_score", {})
        total = score.get("total", 0)
        grade = score.get("grade", "N/A")

        # Color based on grade
        grade_colors = {"A": "green", "B": "blue", "C": "yellow", "D": "red", "F": "red"}
        color = grade_colors.get(grade, "white")

        console.print(f"[{color}]{grade}[/{color}] ({total}/100) - {target}")

        if grade in ("D", "F"):
            raise typer.Exit(1)

    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
