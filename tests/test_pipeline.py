from datetime import UTC, date, datetime

from pipeline.detector import detect_new_models
from pipeline.fingerprint import FingerprintStore
from pipeline.schema import Category, RawListing, SourceRef, make_fingerprint


def test_fingerprint_generation():
    fp = make_fingerprint(Category.mobile, "Samsung", "Galaxy S24", "256GB")
    assert fp == "mobile:samsung:galaxy-s24:256gb"

    fp_no_var = make_fingerprint(Category.car, "Suzuki", "Alto VXL", None)
    assert fp_no_var == "car:suzuki:alto-vxl"


def test_fingerprint_store(tmp_path):
    store_file = tmp_path / "fp.json"
    store = FingerprintStore(str(store_file))

    assert not store.has_seen("mobile:vivo:v80")
    store.mark_seen("mobile:vivo:v80", date(2026, 10, 13))
    assert store.has_seen("mobile:vivo:v80")

    store.save()
    assert store_file.exists()

    # Reload in a new store instance
    reloaded = FingerprintStore(str(store_file))
    assert reloaded.has_seen("mobile:vivo:v80")


def test_detector_detects_new_and_handles_duplicates(tmp_path):
    store_file = tmp_path / "fp.json"
    store = FingerprintStore(str(store_file))
    run_date = date(2026, 10, 13)

    source = SourceRef(site="test.example", url="https://test.example/phone", fetched_at=datetime.now(UTC))
    listing1 = RawListing(
        category=Category.mobile,
        brand="Samsung",
        model="Galaxy S25",
        variant="256GB",
        price_pkr=200000.0,
        source=source,
    )
    listing2 = RawListing(
        category=Category.mobile,
        brand="Samsung",
        model="Galaxy S25",
        variant="256GB",
        price_pkr=200000.0,
        source=source,
    )
    # Similar fuzzy duplicate in the same run
    listing_fuzzy = RawListing(
        category=Category.mobile,
        brand="Samsung",
        model="Galaxy S25 256GB",
        variant=None,
        price_pkr=200000.0,
        source=source,
    )

    new_models = detect_new_models([listing1, listing2, listing_fuzzy], store, run_date)

    # Exactly 1 model should be detected as new
    assert len(new_models) == 1
    assert new_models[0].brand == "Samsung"
    assert new_models[0].model == "Galaxy S25"

    # Subsequent run with same listing returns zero new models
    store.save()
    new_models_run2 = detect_new_models([listing1], store, run_date)
    assert len(new_models_run2) == 0


def test_config_validation_success():
    from pipeline.config_schema import load_and_validate_config

    config = load_and_validate_config("config.yaml")
    assert config.http.user_agent.startswith("AuctionNow")
    assert len(config.sources) >= 4


def test_config_validation_missing_file(tmp_path):
    import pytest

    from pipeline.config_schema import load_and_validate_config

    with pytest.raises(FileNotFoundError):
        load_and_validate_config(tmp_path / "non_existent_config.yaml")


def test_config_validation_invalid_schema(tmp_path):
    import pytest
    from pydantic import ValidationError

    from pipeline.config_schema import load_and_validate_config

    bad_config = tmp_path / "bad_config.yaml"
    # Invalid: missing required http.user_agent, invalid category
    bad_config.write_text(
        """
paths:
  runs_dir: runs
http:
  default_timeout_seconds: -5
sources:
  - id: test
    category: invalid_category
    name: Test
    base_url: not_a_url
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as exc:
        load_and_validate_config(bad_config)
    errors = str(exc.value)
    assert "user_agent" in errors or "invalid_category" in errors


def test_http_client_403_fails_fast(monkeypatch, tmp_path):
    import httpx
    import pytest

    from pipeline.http_client import PoliteClient

    client = PoliteClient(user_agent="TestBot/1.0", cache_dir=str(tmp_path / ".cache"), max_retries=3)

    call_count = 0

    def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        req = httpx.Request("GET", args[0])
        return httpx.Response(status_code=403, request=req)

    monkeypatch.setattr(httpx, "get", mock_get)

    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://forbidden.example/page", rate_limit_seconds=0)

    # 403 must fail immediately without retrying
    assert call_count == 1


def test_output_writer_markdown_and_slack(tmp_path):
    from pipeline.output_writer import write_run_report
    from pipeline.schema import NewModelEntry, RunError

    entry = NewModelEntry(
        category=Category.mobile,
        brand="Xiaomi",
        model="14T Pro",
        fingerprint="mobile:xiaomi:14t-pro",
        first_seen_run=date(2026, 10, 13),
        price_pkr=180000.0,
        flags=["price_not_found"],
        sources=[SourceRef(site="test.example", url="https://test.example/14t", fetched_at=datetime.now(UTC))],
    )
    err = RunError(source="broken_source", error="Connection reset", url="https://broken.example")

    json_path, md_path = write_run_report(
        run_date=date(2026, 10, 13),
        new_models=[entry],
        errors=[err],
        sources_run=1,
        sources_failed=1,
        runs_dir=str(tmp_path / "runs"),
        runtime_seconds=5.2,
    )

    assert json_path.exists()
    assert md_path.exists()

    md_text = md_path.read_text(encoding="utf-8")
    assert "AuctionNow PK Market Engine — Weekly Run Summary" in md_text
    assert "Xiaomi" in md_text
    assert "14T Pro" in md_text
    assert "price_not_found" in md_text
    assert "Reviewer Flags & Diagnostic Guide" in md_text
    assert "Errors & System Warnings" in md_text
    assert "broken_source" in md_text


def test_metrics_tracking(tmp_path):
    from pipeline.metrics import record_run_metrics

    metrics_csv = tmp_path / "metrics.csv"
    record_run_metrics(
        metrics_path=metrics_csv,
        run_id="run-1",
        run_date=date(2026, 10, 13),
        sources_run=2,
        sources_failed=0,
        new_cars=1,
        new_mobiles=2,
        errors_count=0,
        runtime_seconds=12.4,
    )

    content = metrics_csv.read_text(encoding="utf-8")
    assert "run_id,run_date,timestamp" in content
    assert "run-1,2026-10-13" in content

    # Append second run
    record_run_metrics(
        metrics_path=metrics_csv,
        run_id="run-2",
        run_date=date(2026, 10, 20),
        sources_run=2,
        sources_failed=0,
        new_cars=0,
        new_mobiles=0,
        errors_count=0,
        runtime_seconds=3.1,
    )

    lines = metrics_csv.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # Header + 2 data rows


def test_slack_notification_skipped_when_empty():
    from pipeline.notifications import send_slack_notification

    # Should gracefully return False without exceptions
    assert not send_slack_notification("", "Test message")
    assert not send_slack_notification(None, "Test message")


def test_orchestrator_reconciliation_integration(tmp_path, monkeypatch):
    import yaml
    from adapters.base import BaseAdapter
    from pipeline import orchestrator

    class MockLaptopAdapter(BaseAdapter):
        source_id = "mock_laptop_src"
        category = "laptop"

        def list_candidates(self):
            return [{
                "brand": "Apple",
                "model": "MacBook Air 13 M3",
                "variant": "256GB",
                "url": "https://priceoye.pk/laptops/apple/macbook-air-13-m3",
            }]

        def fetch_detail(self, candidate):
            return RawListing(
                category=Category.laptop,
                brand="Apple",
                model="MacBook Air 13 M3",
                variant="256GB",
                price_pkr=349999.0,
                ram_options=["8GB", "16GB"],
                storage_options=["256GB", "512GB"],
                color_options=["Midnight", "Starlight"],
                source=SourceRef(site="mock.pk", url=candidate["url"], fetched_at=datetime.now(UTC)),
            )

    monkeypatch.setitem(orchestrator.ADAPTER_REGISTRY, "mock_laptop_src", "mock:MockLaptopAdapter")
    monkeypatch.setattr(orchestrator, "_load_adapter_class", lambda _path: MockLaptopAdapter)

    config_data = {
        "paths": {
            "fingerprint_store": str(tmp_path / "fp.json"),
            "runs_dir": str(tmp_path / "runs"),
            "cache_dir": str(tmp_path / ".cache"),
            "backend_catalog_dir": str(Path(__file__).parent.parent / "auctionnow_backend_json"),
        },
        "http": {
            "user_agent": "TestBot/1.0",
            "default_timeout_seconds": 10,
            "default_rate_limit_seconds": 0,
            "cache_max_age_hours": 24,
        },
        "sources": [
            {
                "id": "mock_laptop_src",
                "category": "laptop",
                "name": "Mock Laptop Source",
                "base_url": "https://priceoye.pk",
                "enabled": True,
                "rate_limit_seconds": 0,
            }
        ],
        "notifications": {
            "slack_webhook_url": "",
        },
    }

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(config_data), encoding="utf-8")

    out_json = orchestrator.run(config_path=str(cfg_file))
    assert out_json.exists()

    run_dir = out_json.parent
    md_file = run_dir / "summary.md"
    assert md_file.exists()
    md_text = md_file.read_text(encoding="utf-8")
    assert "AuctionNow App Catalog Reconciliation" in md_text

    rec_json = run_dir / "models_to_add_to_auctionnow.json"
    assert rec_json.exists()
    rec_text = rec_json.read_text(encoding="utf-8")
    assert "missing_models" in rec_text
    assert "catalog_sources_reconciled" in rec_text

