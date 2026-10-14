"""
Historical run metrics tracking.

Appends execution statistics to a persistent CSV log (runs/metrics.csv)
enabling performance and discovery trend analysis across weekly runs.
"""
from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from pathlib import Path

from pipeline.logger import get_logger

logger = get_logger("pipeline.metrics")

CSV_HEADER = [
    "run_id",
    "run_date",
    "timestamp",
    "sources_run",
    "sources_failed",
    "new_cars",
    "new_mobiles",
    "new_laptops",
    "new_bikes",
    "total_new_models",
    "errors_count",
    "runtime_seconds",
]


def record_run_metrics(
    metrics_path: str | Path,
    run_id: str,
    run_date: date,
    sources_run: int,
    sources_failed: int,
    new_cars: int,
    new_mobiles: int,
    errors_count: int,
    runtime_seconds: float,
    new_laptops: int = 0,
    new_bikes: int = 0,
) -> Path:
    """
    Append run metrics to CSV file.
    Creates the file and writes header if it does not exist.
    """
    path = Path(metrics_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    file_exists = path.exists() and path.stat().st_size > 0

    total_new = new_cars + new_mobiles + new_laptops + new_bikes
    row = [
        run_id,
        run_date.isoformat(),
        datetime.now(UTC).isoformat(),
        sources_run,
        sources_failed,
        new_cars,
        new_mobiles,
        new_laptops,
        new_bikes,
        total_new,
        errors_count,
        round(runtime_seconds, 2),
    ]

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(CSV_HEADER)
        writer.writerow(row)

    logger.info("Recorded historical run metrics in %s", path)
    return path
