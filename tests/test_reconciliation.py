"""
Unit tests for AuctionNow Backend Catalog Reconciliation Engine.
"""
from datetime import UTC, date, datetime
from pathlib import Path

from pipeline.reconciliation import (
    BackendCatalog,
    normalize_brand,
    reconcile_with_backend,
    save_reconciliation_report,
    slugify,
)
from pipeline.schema import Category, RawListing, SourceRef

BACKEND_DIR = Path(__file__).parent.parent / "auctionnow_backend_json"


def test_slugify_and_normalize_brand():
    assert slugify("MacBook Air 13 M3") == "macbook-air-13-m3"
    assert slugify("  iPhone 16 Pro Max!!  ") == "iphone-16-pro-max"
    assert normalize_brand("Apple") == "apple"
    assert normalize_brand("Hewlett-Packard") == "hp"
    assert normalize_brand("Techno") == "tecno"


def test_backend_catalog_loading():
    catalog = BackendCatalog(BACKEND_DIR)
    catalog.load()

    assert len(catalog.catalog["mobile"]) > 0
    assert "apple" in catalog.catalog["mobile"]
    assert "samsung" in catalog.catalog["mobile"]

    assert len(catalog.catalog["laptop"]) > 0
    assert "apple" in catalog.catalog["laptop"]

    assert len(catalog.catalog["bike"]) > 0
    assert "benelli" in catalog.catalog["bike"]


def test_backend_catalog_find_match():
    catalog = BackendCatalog(BACKEND_DIR)
    catalog.load()

    # Model that exists in mobile backend: iPhone 18 Pro Max
    found, slug, _entry = catalog.find_match(Category.mobile, "Apple", "iPhone 18 Pro Max")
    assert found is True
    assert "iphone-18-pro-max" in slug

    # Model that does NOT exist in backend
    found_missing, _, _ = catalog.find_match(Category.mobile, "Apple", "iPhone 99 Ultra Titanium")
    assert found_missing is False

    # Laptop model that exists: macbook-air-13-m5
    found_laptop, slug_laptop, _ = catalog.find_match(Category.laptop, "Apple", "MacBook Air 13 M5")
    assert found_laptop is True
    assert "macbook-air-13-m5" in slug_laptop

    # Completely unknown brand
    found_brand, _, _ = catalog.find_match(Category.laptop, "NonExistentBrand123", "SuperLaptop")
    assert found_brand is False


def test_reconcile_with_backend_detects_missing_and_attributes(tmp_path):
    source = SourceRef(site="test.pk", url="https://test.pk/p1", fetched_at=datetime.now(UTC))

    # 1. An existing model in backend (iPhone 18 Pro Max) with newly discovered color
    listing_existing = RawListing(
        category=Category.mobile,
        brand="Apple",
        model="iPhone 18 Pro Max",
        price_pkr=450000.0,
        color_options=["Cosmic Orange", "Titanium Blue"],
        source=source,
    )

    # 2. A brand-new missing model not present in AuctionNow backend
    listing_missing = RawListing(
        category=Category.laptop,
        brand="Apple",
        model="MacBook Neo 14 M7",
        variant="1TB",
        price_pkr=550000.0,
        ram_options=["32GB"],
        storage_options=["1TB"],
        color_options=["Space Black"],
        specs={"processor": "M7", "display": "14.2 inches"},
        source=source,
    )

    models = [listing_existing, listing_missing]
    report = reconcile_with_backend(models, BACKEND_DIR, run_date=date(2026, 10, 14))

    assert "summary" in report
    assert report["summary"]["total_models_evaluated"] == 2
    assert report["summary"]["total_missing_models"] >= 1
    assert report["summary"]["missing_by_category"]["laptop"] == 1

    # Check missing model ingestion payload
    missing_entry = next(m for m in report["missing_models"] if "MacBook Neo 14 M7" in m["model"])
    assert missing_entry["category"] == "laptop"
    assert missing_entry["brand"] == "Apple"
    assert missing_entry["suggested_slug"] == "apple-macbook-neo-14-m7"
    assert missing_entry["price_pkr"] == 550000.0
    assert "32GB" in missing_entry["ram_options"]
    assert "1TB" in missing_entry["storage_options"]
    assert "auctionnow_catalog_payload" in missing_entry

    payload = missing_entry["auctionnow_catalog_payload"]
    assert payload["slug"] == "apple-macbook-neo-14-m7"
    assert payload["metadata"]["initial_price_pkr"] == 550000.0
    assert payload["metadata"]["brand"] == "apple"

    # Test saving report to file
    out_file = save_reconciliation_report(report, tmp_path / "runs", date(2026, 10, 14))
    assert out_file.exists()
    assert out_file.name == "models_to_add_to_auctionnow.json"
