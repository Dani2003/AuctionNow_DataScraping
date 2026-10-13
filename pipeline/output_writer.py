"""
Generates structured JSON reports and human-readable Markdown summaries.

Outputs:
- runs/<date>/new_models.json: Machine-readable payload for downstream catalog ingestion review.
- runs/<date>/summary.md: Human-readable markdown summary for PMs and operations review.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from .schema import Category, NewModelEntry, RunError, RunReport, RunSummary

FLAG_DESCRIPTIONS = {
    "price_not_found": "Price was not found on source page. Reviewer should verify if model is unpriced/upcoming.",
    "color_not_found": "Color options missing or unparsed. Check product gallery or manufacturer brochure.",
    "specs_empty": "Technical specifications table was empty. Manual entry required.",
    "low_confidence": "Extracted with potential ambiguities or missing critical fields.",
}


def generate_slack_summary(report: RunReport, runtime_seconds: float | None = None) -> str:
    """Generate a clean, compact text snippet suitable for Slack webhook delivery."""
    summary = report.summary
    duration_str = f" in {runtime_seconds:.1f}s" if runtime_seconds is not None else ""
    status_emoji = "✅" if summary.sources_failed == 0 and len(report.errors) == 0 else "⚠️"

    lines = [
        f"{status_emoji} *AuctionNow PK Market Engine Run — {report.run_date}*{duration_str}",
        f"• *New Models Found:* {len(report.new_models)} (Cars: {summary.new_cars}, Mobiles: {summary.new_mobiles})",
        f"• *Sources Processed:* {summary.sources_run} successful, {summary.sources_failed} failed",
    ]

    if report.new_models:
        lines.append("\n*Top Highlights:*")
        for m in report.new_models[:5]:
            cat_icon = "🚗" if m.category == Category.car else "📱"
            price_str = f"PKR {m.price_pkr:,.0f}" if m.price_pkr else "Price TBD"
            lines.append(f"  {cat_icon} *{m.brand} {m.model}* ({price_str})")
        if len(report.new_models) > 5:
            lines.append(f"  _...and {len(report.new_models) - 5} more in report_")

    if report.errors:
        lines.append(f"\n*⚠️ Attention:* {len(report.errors)} source/page errors occurred during this run.")

    return "\n".join(lines)


def generate_markdown_summary(
    report: RunReport,
    runtime_seconds: float | None = None,
) -> str:
    """Generate a rich human-readable Markdown summary report."""
    summary = report.summary
    status = "CLEAN RUN" if summary.sources_failed == 0 and len(report.errors) == 0 else "COMPLETED WITH WARNINGS"

    cars = [m for m in report.new_models if m.category == Category.car]
    mobiles = [m for m in report.new_models if m.category == Category.mobile]

    md = [
        f"# AuctionNow PK Market Engine — Weekly Run Summary ({report.run_date})",
        "",
        f"**Run ID:** `{report.run_id}` | **Status:** {status} | **Generated At:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "---",
        "",
        "## Executive Overview",
        "",
        "| Metric | Count |",
        "| :--- | :--- |",
        f"| **New Cars Detected** | {summary.new_cars} |",
        f"| **New Mobiles Detected** | {summary.new_mobiles} |",
        f"| **Total New Models** | {len(report.new_models)} |",
        f"| **Sources Succeeded** | {summary.sources_run} |",
        f"| **Sources Failed** | {summary.sources_failed} |",
        f"| **Errors Encountered** | {len(report.errors)} |",
    ]

    if runtime_seconds is not None:
        md.append(f"| **Runtime Duration** | {runtime_seconds:.2f}s |")

    md.extend(["", "---", "", "## Newly Discovered Models", ""])

    # Cars table
    md.append("### 🚗 Vehicles (Cars)")
    if cars:
        md.append("| Brand | Model | Variant | Year | Price (PKR) | Confidence | Flags | Sources |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for c in cars:
            var = c.variant or "—"
            yr = str(c.model_year) if c.model_year else "—"
            price = f"PKR {c.price_pkr:,.0f}" if c.price_pkr else "**Price TBD**"
            flags = ", ".join(f"`{f}`" for f in c.flags) if c.flags else "Clean"
            src_links = ", ".join(f"[{s.site}]({s.url})" for s in c.sources)
            md.append(f"| **{c.brand}** | {c.model} | {var} | {yr} | {price} | `{c.confidence}` | {flags} | {src_links} |")
    else:
        md.append("_No new car models detected this run._")

    md.extend(["", "### 📱 Mobile Phones"])
    if mobiles:
        md.append("| Brand | Model | Variant | RAM / Storage | Price (PKR) | Confidence | Flags | Sources |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for m in mobiles:
            var = m.variant or "—"
            options = []
            if m.ram_options:
                options.append(f"RAM: {', '.join(m.ram_options)}")
            if m.storage_options:
                options.append(f"Storage: {', '.join(m.storage_options)}")
            opt_str = " / ".join(options) if options else "—"
            price = f"PKR {m.price_pkr:,.0f}" if m.price_pkr else "**Price TBD**"
            flags = ", ".join(f"`{f}`" for f in m.flags) if m.flags else "Clean"
            src_links = ", ".join(f"[{s.site}]({s.url})" for s in m.sources)
            md.append(f"| **{m.brand}** | {m.model} | {var} | {opt_str} | {price} | `{m.confidence}` | {flags} | {src_links} |")
    else:
        md.append("_No new mobile models detected this run._")

    # Reviewer Flags Guide
    md.extend([
        "",
        "---",
        "",
        "## Reviewer Flags & Diagnostic Guide",
        "",
        "All models marked with flags in the tables above require manual verification before catalog promotion:",
        "",
    ])

    all_flags_seen = set()
    for m in report.new_models:
        all_flags_seen.update(m.flags)

    if all_flags_seen:
        for fl in sorted(all_flags_seen):
            desc = FLAG_DESCRIPTIONS.get(fl, "Diagnostic warning generated during page extraction.")
            md.append(f"- **`{fl}`**: {desc}")
    else:
        md.append("- _No diagnostic flags raised in this run — all extracted entries meet confidence criteria._")

    # Errors section
    md.extend(["", "---", "", "## Errors & System Warnings", ""])
    if report.errors:
        md.append("| Source | Target URL | Error Message |")
        md.append("| :--- | :--- | :--- |")
        for e in report.errors:
            url_str = f"[{e.url}]({e.url})" if e.url else "—"
            md.append(f"| **{e.source}** | {url_str} | `{e.error}` |")
    else:
        md.append("✅ _Zero source or network errors occurred during execution._")

    md.extend([
        "",
        "---",
        "",
        "## Slack Notification Snippet",
        "```text",
        generate_slack_summary(report, runtime_seconds),
        "```",
        "",
    ])

    return "\n".join(md)


def write_run_report(
    run_date: date,
    new_models: list[NewModelEntry],
    errors: list[RunError],
    sources_run: int,
    sources_failed: int,
    runs_dir: str,
    runtime_seconds: float | None = None,
) -> tuple[Path, Path]:
    """
    Write both the machine-readable JSON report and human-readable Markdown summary.
    Returns (json_path, markdown_path).
    """
    run_id = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    summary = RunSummary(
        sources_run=sources_run,
        sources_failed=sources_failed,
        new_cars=sum(1 for m in new_models if m.category == Category.car),
        new_mobiles=sum(1 for m in new_models if m.category == Category.mobile),
    )
    report = RunReport(
        run_id=run_id,
        run_date=run_date,
        summary=summary,
        new_models=new_models,
        errors=errors,
    )

    out_dir = Path(runs_dir) / run_date.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "new_models.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    md_content = generate_markdown_summary(report, runtime_seconds=runtime_seconds)
    md_path = out_dir / "summary.md"
    md_path.write_text(md_content, encoding="utf-8")

    return json_path, md_path
