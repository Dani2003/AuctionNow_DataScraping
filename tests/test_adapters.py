from pathlib import Path

import pytest

from adapters.cars.pakwheels_new_cars import PakWheelsNewCarsAdapter
from adapters.mobiles.whatmobile import WhatMobileAdapter
from pipeline.http_client import PoliteClient
from pipeline.schema import Category

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def dummy_client(tmp_path):
    return PoliteClient(
        user_agent="TestBot/1.0",
        cache_dir=str(tmp_path / ".cache"),
    )


def test_whatmobile_candidates_from_fixture(dummy_client):
    html = (FIXTURES_DIR / "whatmobile_listing.html").read_text(encoding="utf-8")
    adapter = WhatMobileAdapter(dummy_client, "https://www.whatmobile.com.pk", rate_limit_seconds=0)

    candidates = adapter.parse_candidates_from_html(html)
    assert len(candidates) > 0

    first = candidates[0]
    assert "brand" in first
    assert "model" in first
    assert "url" in first
    assert first["url"].startswith("https://www.whatmobile.com.pk")

    # Check for known model in the fixture
    model_names = [c["model"] for c in candidates]
    assert any("V80 Lite" in m for m in model_names)


def test_whatmobile_detail_from_fixture(dummy_client):
    html = (FIXTURES_DIR / "whatmobile_detail.html").read_text(encoding="utf-8")
    adapter = WhatMobileAdapter(dummy_client, "https://www.whatmobile.com.pk", rate_limit_seconds=0)

    candidate = {
        "brand": "Vivo",
        "model": "V80 Lite",
        "variant": None,
        "url": "https://www.whatmobile.com.pk/Vivo_V80-Lite",
    }
    listing = adapter.parse_detail_from_html(candidate, html)

    assert listing.category == Category.mobile
    assert listing.brand == "Vivo"
    assert listing.model == "V80 Lite"
    assert listing.price_pkr == 124999.0
    assert "Sapphire Blue" in listing.color_options
    assert "Silk White" in listing.color_options
    assert "8GB" in listing.ram_options
    assert "128GB" in listing.storage_options
    assert listing.model_year == 2026
    assert listing.fingerprint_key() == "mobile:vivo:v80-lite"
    assert listing.confidence == "high"
    assert listing.flags == []


def test_pakwheels_candidates_from_fixture(dummy_client):
    html = (FIXTURES_DIR / "pakwheels_listing.html").read_text(encoding="utf-8")
    adapter = PakWheelsNewCarsAdapter(dummy_client, "https://www.pakwheels.com", rate_limit_seconds=0)

    candidates = adapter.parse_candidates_from_html(html)
    assert len(candidates) > 0

    first = candidates[0]
    assert "brand" in first
    assert "model" in first
    assert "url" in first
    assert first["url"].startswith("https://www.pakwheels.com/new-cars/")

    brands = [c["brand"] for c in candidates]
    assert "Kia" in brands or "Arcfox" in brands


def test_pakwheels_detail_from_fixture(dummy_client):
    html = (FIXTURES_DIR / "pakwheels_detail.html").read_text(encoding="utf-8")
    adapter = PakWheelsNewCarsAdapter(dummy_client, "https://www.pakwheels.com", rate_limit_seconds=0)

    candidate = {
        "brand": "Kia",
        "model": "Stonic",
        "variant": None,
        "url": "https://www.pakwheels.com/new-cars/kia/stonic/",
    }
    listing = adapter.parse_detail_from_html(candidate, html)

    assert listing.category == Category.car
    assert listing.brand == "Kia"
    assert listing.model == "Stonic"
    assert listing.price_pkr == 5499000.0
    assert len(listing.color_options) > 0
    assert "Clear White" in listing.color_options
    assert "Displacement" in listing.specs
    assert listing.specs["Displacement"] == "998 cc"
    assert listing.specs["Transmission"] == "Automatic"
    assert len(listing.images) > 0
    assert listing.fingerprint_key().startswith("car:kia:stonic")
    assert listing.confidence == "high"
    assert listing.flags == []


def test_priceoye_candidates_from_fixture(dummy_client):
    from adapters.mobiles.priceoye import PriceOyeAdapter

    html = (FIXTURES_DIR / "priceoye_listing.html").read_text(encoding="utf-8")
    adapter = PriceOyeAdapter(dummy_client, "https://priceoye.pk", rate_limit_seconds=0)

    candidates = adapter.parse_candidates_from_html(html)
    assert len(candidates) > 0

    first = candidates[0]
    assert "brand" in first
    assert "model" in first
    assert "url" in first
    assert first["url"].startswith("https://priceoye.pk/mobiles/")


def test_priceoye_detail_from_fixture(dummy_client):
    from adapters.mobiles.priceoye import PriceOyeAdapter

    html = (FIXTURES_DIR / "priceoye_detail.html").read_text(encoding="utf-8")
    adapter = PriceOyeAdapter(dummy_client, "https://priceoye.pk", rate_limit_seconds=0)

    candidate = {
        "brand": "Infinix",
        "model": "Smart 20",
        "variant": None,
        "url": "https://priceoye.pk/mobiles/infinix/infinix-smart-20",
    }
    listing = adapter.parse_detail_from_html(candidate, html)

    assert listing.category == Category.mobile
    assert listing.brand == "Infinix"
    assert "Smart 20" in listing.model
    assert listing.price_pkr == 39499.0
    assert len(listing.color_options) > 0
    assert "Shadow Black" in listing.color_options
    assert len(listing.storage_options) > 0
    assert len(listing.images) > 0
    assert listing.fingerprint_key() == "mobile:infinix:smart-20"
    assert listing.confidence == "high"


def test_toyota_indus_candidates_from_fixture(dummy_client):
    from adapters.cars.toyota_indus import ToyotaIndusAdapter

    html = (FIXTURES_DIR / "toyota_listing.html").read_text(encoding="utf-8")
    adapter = ToyotaIndusAdapter(dummy_client, "https://toyota-indus.com", rate_limit_seconds=0)

    candidates = adapter.parse_candidates_from_html(html)
    assert len(candidates) > 0

    models = [c["model"] for c in candidates]
    assert "Yaris" in models or "Corolla" in models


def test_toyota_indus_detail_from_fixture(dummy_client):
    from adapters.cars.toyota_indus import ToyotaIndusAdapter

    html = (FIXTURES_DIR / "toyota_detail.html").read_text(encoding="utf-8")
    adapter = ToyotaIndusAdapter(dummy_client, "https://toyota-indus.com", rate_limit_seconds=0)

    candidate = {
        "brand": "Toyota",
        "model": "Yaris",
        "variant": None,
        "url": "https://toyota-indus.com/yaris/",
    }
    listing = adapter.parse_detail_from_html(candidate, html)

    assert listing.category == Category.car
    assert listing.brand == "Toyota"
    assert listing.model == "Yaris"
    assert "Exterior L x W x H" in listing.specs
    assert len(listing.images) > 0
    assert listing.fingerprint_key() == "car:toyota:yaris"
