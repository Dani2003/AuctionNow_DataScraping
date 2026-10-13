from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from .schema import Category, NewModelEntry, RunError, RunReport, RunSummary


def write_run_report(
    run_date: date,
    new_models: list[NewModelEntry],
    errors: list[RunError],
    sources_run: int,
    sources_failed: int,
    runs_dir: str,
) -> Path:
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
    out_path = out_dir / "new_models.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return out_path
