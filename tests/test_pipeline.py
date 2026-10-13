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
