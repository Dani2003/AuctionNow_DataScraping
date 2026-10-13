"""
Pipeline Orchestrator.

Coordinates configuration validation, adapter execution, fingerprint diffing,
and output generation with structured logging and fault isolation.
"""
import time
from datetime import date
from importlib import import_module
from pathlib import Path

from .config_schema import AppConfig, load_and_validate_config
from .detector import detect_new_models
from .fingerprint import FingerprintStore
from .http_client import PoliteClient
from .logger import get_logger, setup_logging
from .metrics import record_run_metrics
from .notifications import send_slack_notification
from .output_writer import generate_slack_summary, write_run_report
from .schema import RawListing, RunError, RunReport, RunSummary, make_fingerprint

logger = get_logger("pipeline.orchestrator")

# Maps source id (config.yaml) -> "module_path:ClassName".
ADAPTER_REGISTRY = {
    "whatmobile": "adapters.mobiles.whatmobile:WhatMobileAdapter",
    "priceoye": "adapters.mobiles.priceoye:PriceOyeAdapter",
    "pakwheels_new_cars": "adapters.cars.pakwheels_new_cars:PakWheelsNewCarsAdapter",
    "indus_motor_toyota": "adapters.cars.toyota_indus:ToyotaIndusAdapter",
}


def _load_adapter_class(dotted_path: str):
    module_path, class_name = dotted_path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)


def run(config_path: str = "config.yaml", only_source: str | None = None, limit: int | None = None) -> Path:
    """
    Execute the market discovery pipeline.
    Validates configuration, runs configured adapters with fault isolation,
    detects newly released models, updates the fingerprint store, and writes reports.
    """
    setup_logging()
    start_time = time.monotonic()
    logger.info("Initializing PK Market Data Engine run using config: %s", config_path)

    # 1. Startup configuration validation (fails fast and loud if invalid)
    config: AppConfig = load_and_validate_config(config_path)

    client = PoliteClient(
        user_agent=config.http.user_agent,
        cache_dir=config.paths.cache_dir,
        default_rate_limit_seconds=config.http.default_rate_limit_seconds,
        cache_max_age_hours=config.http.cache_max_age_hours,
        timeout_seconds=config.http.default_timeout_seconds,
    )
    store = FingerprintStore(config.paths.fingerprint_store)
    run_date = date.today()

    all_listings: list[RawListing] = []
    errors: list[RunError] = []
    sources_run = 0
    sources_failed = 0

    sources = config.sources
    if only_source:
        sources = [s for s in sources if s.id == only_source]
        if not sources:
            logger.warning("No configured source matched filter '%s'", only_source)

    for source in sources:
        if not source.enabled:
            logger.info("Skipping source '%s' (enabled: false)", source.id)
            continue

        if source.id not in ADAPTER_REGISTRY:
            logger.warning("Skipping source '%s' (no adapter registered in ADAPTER_REGISTRY)", source.id)
            continue

        logger.info("Starting source: %s (%s)", source.name, source.id)
        try:
            adapter_cls = _load_adapter_class(ADAPTER_REGISTRY[source.id])
            adapter = adapter_cls(
                client=client,
                base_url=source.base_url,
                rate_limit_seconds=source.rate_limit_seconds,
            )

            candidates = adapter.list_candidates()
            logger.info("Source '%s': discovered %d candidates", source.id, len(candidates))

            if limit:
                candidates = candidates[:limit]
                logger.info("Source '%s': limited to %d candidates for testing", source.id, len(candidates))

            source_listings_count = 0
            for candidate in candidates:
                fp = make_fingerprint(
                    category=adapter.category,
                    brand=candidate["brand"],
                    model=candidate["model"],
                    variant=candidate.get("variant"),
                )

                if store.has_seen(fp):
                    store.mark_seen(fp, run_date)
                    logger.debug("Candidate already known: %s (skipped detail fetch)", fp)
                    continue

                # Isolate individual candidate detail failures so 1 bad page doesn't drop the batch
                try:
                    logger.info("Fetching details for candidate: %s [%s]", fp, candidate.get("url"))
                    listing = adapter.fetch_detail(candidate)
                    all_listings.append(listing)
                    source_listings_count += 1
                except Exception as cand_err:  # noqa: BLE001
                    logger.warning("Failed fetching detail for '%s' (%s): %s", fp, candidate.get("url"), cand_err)
                    errors.append(RunError(source=source.id, error=str(cand_err), url=candidate.get("url")))

            logger.info("Source '%s' completed: %d new listings fetched", source.id, source_listings_count)
            sources_run += 1

        except Exception as source_err:
            logger.exception("Source '%s' encountered fatal error", source.id)
            sources_failed += 1
            errors.append(RunError(source=source.id, error=str(source_err), url=source.base_url))

    # 2. Diff against baseline & fuzzy deduplication
    logger.info("Executing detection & deduplication across %d fetched listings...", len(all_listings))
    new_models = detect_new_models(all_listings, store, run_date)

    # 3. Only save updated fingerprints after uncorrupted execution
    store.save()
    logger.info("Atomically updated baseline fingerprints in %s", config.paths.fingerprint_store)

    runtime_seconds = time.monotonic() - start_time

    # 4. Generate JSON and Markdown reports
    json_path, md_path = write_run_report(
        run_date=run_date,
        new_models=new_models,
        errors=errors,
        sources_run=sources_run,
        sources_failed=sources_failed,
        runs_dir=config.paths.runs_dir,
        runtime_seconds=runtime_seconds,
    )

    car_count = sum(1 for m in new_models if m.category.value == "car")
    mobile_count = sum(1 for m in new_models if m.category.value == "mobile")

    # 5. Append historical metrics
    metrics_path = Path(config.paths.runs_dir) / "metrics.csv"
    record_run_metrics(
        metrics_path=metrics_path,
        run_id=json_path.parent.name,
        run_date=run_date,
        sources_run=sources_run,
        sources_failed=sources_failed,
        new_cars=car_count,
        new_mobiles=mobile_count,
        errors_count=len(errors),
        runtime_seconds=runtime_seconds,
    )

    # 6. Dispatch Slack notification (if webhook configured)
    summary_obj = RunSummary(
        sources_run=sources_run,
        sources_failed=sources_failed,
        new_cars=car_count,
        new_mobiles=mobile_count,
    )
    report_obj = RunReport(
        run_id=json_path.parent.name,
        run_date=run_date,
        summary=summary_obj,
        new_models=new_models,
        errors=errors,
    )
    slack_text = generate_slack_summary(report_obj, runtime_seconds=runtime_seconds)
    send_slack_notification(config.notifications.slack_webhook_url, slack_text)

    logger.info("Run finished successfully in %.2fs.", runtime_seconds)
    logger.info("JSON report: %s", json_path)
    logger.info("Markdown summary: %s", md_path)
    logger.info(
        "Run summary: sources_run=%d, sources_failed=%d, new_cars=%d, new_mobiles=%d, total_new=%d, errors=%d",
        sources_run,
        sources_failed,
        car_count,
        mobile_count,
        len(new_models),
        len(errors),
    )

    return json_path
