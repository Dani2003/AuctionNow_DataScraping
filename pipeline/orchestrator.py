from __future__ import annotations

from datetime import date
from importlib import import_module

import yaml

from .detector import detect_new_models
from .fingerprint import FingerprintStore
from .http_client import PoliteClient
from .output_writer import write_run_report
from .schema import RawListing, RunError, make_fingerprint

# Maps source id (config.yaml) -> "module_path:ClassName". Add one line here
# whenever a new adapter is written.
ADAPTER_REGISTRY = {
    "whatmobile": "adapters.mobiles.whatmobile:WhatMobileAdapter",
    "pakwheels_new_cars": "adapters.cars.pakwheels_new_cars:PakWheelsNewCarsAdapter",
}


def _load_adapter_class(dotted_path: str):
    module_path, class_name = dotted_path.split(":")
    module = import_module(module_path)
    return getattr(module, class_name)


def run(config_path: str = "config.yaml", only_source: str | None = None, limit: int | None = None):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    client = PoliteClient(
        user_agent=cfg["http"]["user_agent"],
        cache_dir=cfg["paths"]["cache_dir"],
        default_rate_limit_seconds=cfg["http"]["default_rate_limit_seconds"],
        cache_max_age_hours=cfg["http"]["cache_max_age_hours"],
        timeout_seconds=cfg["http"]["default_timeout_seconds"],
    )
    store = FingerprintStore(cfg["paths"]["fingerprint_store"])
    run_date = date.today()

    all_listings: list[RawListing] = []
    errors: list[RunError] = []
    sources_run = 0
    sources_failed = 0

    sources = cfg["sources"]
    if only_source:
        sources = [s for s in sources if s["id"] == only_source]

    for source in sources:
        if not source.get("enabled", False):
            print(f"-- skipping '{source['id']}' (enabled: false in config.yaml)")
            continue
        if source["id"] not in ADAPTER_REGISTRY:
            print(f"-- skipping '{source['id']}' (no adapter registered)")
            continue

        print(f"== running source: {source['id']}")
        try:
            adapter_cls = _load_adapter_class(ADAPTER_REGISTRY[source["id"]])
            adapter = adapter_cls(
                client=client,
                base_url=source["base_url"],
                rate_limit_seconds=source.get("rate_limit_seconds", cfg["http"]["default_rate_limit_seconds"]),
            )

            candidates = adapter.list_candidates()
            if limit:
                candidates = candidates[:limit]

            for candidate in candidates:
                fp = make_fingerprint(
                    category=adapter.category,
                    brand=candidate["brand"],
                    model=candidate["model"],
                    variant=candidate.get("variant"),
                )
                if store.has_seen(fp):
                    store.mark_seen(fp, run_date)
                    continue

                listing = adapter.fetch_detail(candidate)
                all_listings.append(listing)

            sources_run += 1

        except Exception as e:  # noqa: BLE001 -- one bad source must not kill the run
            print(f"   ! source '{source['id']}' failed: {e}")
            sources_failed += 1
            errors.append(RunError(source=source["id"], error=str(e)))

    run_date = date.today()
    new_models = detect_new_models(all_listings, store, run_date)

    # Only persist the new baseline if we got through without a hard crash --
    # a partial/failed run should not overwrite a good baseline.
    store.save()

    out_path = write_run_report(
        run_date=run_date,
        new_models=new_models,
        errors=errors,
        sources_run=sources_run,
        sources_failed=sources_failed,
        runs_dir=cfg["paths"]["runs_dir"],
    )
    print(f"\nWrote report: {out_path}")
    print(f"New models found: {len(new_models)} "
          f"(cars: {sum(1 for m in new_models if m.category == 'car')}, "
          f"mobiles: {sum(1 for m in new_models if m.category == 'mobile')})")
    return out_path
