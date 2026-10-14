"""
The JSON output contract. Every adapter must produce `RawListing` objects;
everything downstream (fingerprinting, detection, output) is built against
these models, not against any one site's HTML.

Keep this in sync with the "Data Schema" section of the design doc.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Category(str, Enum):
    car = "car"
    mobile = "mobile"
    laptop = "laptop"
    bike = "bike"


class SourceRef(BaseModel):
    site: str
    url: str
    fetched_at: datetime


def make_fingerprint(category: str | Category, brand: str, model: str, variant: str | None = None) -> str:
    """
    Stable identity for "have we seen this before". Lowercase,
    hyphenated, no punctuation noise.
    """
    cat_val = category.value if isinstance(category, Category) else str(category)
    parts = [cat_val, brand, model, variant or ""]
    cleaned = [
        "".join(ch.lower() if ch.isalnum() else "-" for ch in p).strip("-")
        for p in parts
    ]
    return ":".join(p for p in cleaned if p)


class RawListing(BaseModel):
    """
    What an adapter hands back for ONE model/variant found on a source,
    BEFORE we know whether it's new. One of these per variant, not per
    brand/model — e.g. "Alto VXL" and "Alto VXL AGS" are separate listings.
    """
    category: Category
    brand: str
    model: str
    variant: str | None = None
    model_year: int | None = None

    price_pkr: float | None = None
    price_as_of: date | None = None

    specs: dict = Field(default_factory=dict)
    # RAM/storage/color should be lists even if only one value is known yet —
    # matches the "*_options" pattern used for the AuctionNow laptop catalog.
    ram_options: list[str] = Field(default_factory=list)
    storage_options: list[str] = Field(default_factory=list)
    color_options: list[str] = Field(default_factory=list)

    images: list[str] = Field(default_factory=list)
    source: SourceRef

    confidence: str = "high"   # "high" | "medium" | "low"
    flags: list[str] = Field(default_factory=list)

    def fingerprint_key(self) -> str:
        return make_fingerprint(self.category, self.brand, self.model, self.variant)


class NewModelEntry(BaseModel):
    """One entry in the weekly new_models.json output."""
    category: Category
    brand: str
    model: str
    variant: str | None = None
    model_year: int | None = None
    fingerprint: str
    first_seen_run: date

    price_pkr: float | None = None
    price_as_of: date | None = None

    specs: dict = Field(default_factory=dict)
    ram_options: list[str] = Field(default_factory=list)
    storage_options: list[str] = Field(default_factory=list)
    color_options: list[str] = Field(default_factory=list)

    images: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)

    confidence: str = "high"
    flags: list[str] = Field(default_factory=list)


class RunError(BaseModel):
    source: str
    error: str
    url: str | None = None


class RunSummary(BaseModel):
    sources_run: int
    sources_failed: int
    new_cars: int = 0
    new_mobiles: int = 0
    new_laptops: int = 0
    new_bikes: int = 0


class RunReport(BaseModel):
    run_id: str
    run_date: date
    summary: RunSummary
    new_models: list[NewModelEntry] = Field(default_factory=list)
    errors: list[RunError] = Field(default_factory=list)
