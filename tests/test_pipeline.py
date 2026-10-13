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
