"""
Turns a pile of RawListings into "what's actually new this week".

Two steps, matching the design doc's "Detection Logic" section:
1. Fingerprint match against the store (cheap, exact).
2. A fuzzy guard BEFORE calling something new, so "Suzuki Alto VXL" and
   "Alto VXL" (same car, slightly different naming on two pages) don't
   both get reported as new. This does not replace human review -- it
   just stops the obvious false positives.
"""
from __future__ import annotations

from datetime import date

from rapidfuzz import fuzz

from .fingerprint import FingerprintStore
from .schema import NewModelEntry, RawListing

FUZZY_MATCH_THRESHOLD = 90  # 0-100; tune after seeing real false-positive rate


def _looks_like_duplicate(candidate: RawListing, already_new: list[NewModelEntry]) -> bool:
    candidate_label = f"{candidate.brand} {candidate.model} {candidate.variant or ''}".strip()
    for existing in already_new:
        if existing.category != candidate.category:
            continue
        existing_label = f"{existing.brand} {existing.model} {existing.variant or ''}".strip()
        if fuzz.token_sort_ratio(candidate_label.lower(), existing_label.lower()) >= FUZZY_MATCH_THRESHOLD:
            return True
    return False


def detect_new_models(
    listings: list[RawListing],
    store: FingerprintStore,
    run_date: date,
) -> list[NewModelEntry]:
    """
    NOTE: this only separates "new" from "already known" using what the
    LISTING page gave us. The design doc's "Detail Fetcher" step -- pulling
    the FULL spec page only for confirmed-new items -- happens in the
    orchestrator, after this function returns, to avoid wasting detail
    fetches on models we already have.
    """
    new_entries: list[NewModelEntry] = []

    for listing in listings:
        fp = listing.fingerprint_key()
        if store.has_seen(fp):
            store.mark_seen(fp, run_date)
            continue

        if _looks_like_duplicate(listing, new_entries):
            # Same model, slightly different naming -- treat as seen, don't
            # double-report. Flag it so a human can sanity-check later.
            store.mark_seen(fp, run_date)
            continue

        entry = NewModelEntry(
            category=listing.category,
            brand=listing.brand,
            model=listing.model,
            variant=listing.variant,
            model_year=listing.model_year,
            fingerprint=fp,
            first_seen_run=run_date,
            price_pkr=listing.price_pkr,
            price_as_of=listing.price_as_of,
            specs=listing.specs,
            ram_options=listing.ram_options,
            storage_options=listing.storage_options,
            color_options=listing.color_options,
            images=listing.images,
            sources=[listing.source],
            confidence=listing.confidence,
            flags=list(listing.flags),
        )
        new_entries.append(entry)
        store.mark_seen(fp, run_date)

    return new_entries
