# AuctionNow — PK Market Scraper Engine Design

## 1. Executive Summary & Objective
The AuctionNow PK Market Data Engine is a production-grade weekly pipeline designed to identify newly released vehicle (cars) and mobile phone models across Pakistani market sources. The pipeline produces an audited, reviewable JSON output report (`runs/<date>/new_models.json`) accompanied by human-readable summaries for product operations and catalog managers.

**Crucial System Principle:** This engine is **strictly additive and human-in-the-loop**. It NEVER writes directly to live product or catalog databases. Human review must precede any catalog ingestion.

---

## 2. High-Level Architecture
The engine operates on a weekly scheduled cadence with an intelligent two-stage discovery model to minimize bandwidth, eliminate redundant detail page scrapes, and respect host capacity:

```
[Weekly Scheduler (Cron/CLI)]
            │
            ▼
[Configuration & Startup Validation (Pydantic / config.yaml)]
            │
            ▼
[Robots.txt & Compliance Gate (urllib.robotparser)]
            │ (Halt or skip source if disallowed)
            ▼
[Candidate Discovery (Stage 1: list_candidates())]
  - Fetches index / catalog listing pages
  - Extracts basic identifiers: {brand, model, variant, url}
            │
            ▼
[Diff & Fingerprint Detection (pipeline/detector.py & fingerprint.py)]
  - Evaluates candidate fingerprint against `storage/fingerprints.json`
  - Applies fuzzy similarity guards (rapidfuzz) to collapse naming variants
            │
            ▼
[Detail Fetching (Stage 2: fetch_detail()) — ONLY FOR CONFIRMED NEW MODELS]
  - Polite, rate-limited HTTP fetch with persistent caching
  - Parses structured specifications, colors, variants, pricing in PKR
            │
            ▼
[Report Generation & Human Review Artifacts (pipeline/output_writer.py)]
  - Writes `runs/<date>/new_models.json`
  - Generates markdown summary for Slack / notification distribution
  - Updates run metrics log
            │
            ▼
[Atomic Fingerprint Persistence]
  - Atomically saves updated fingerprints only on un-corrupted run
```

---

## 3. Data Schema & Contract
All source adapters normalize extracted data into standard Pydantic models defined in `pipeline/schema.py`:
- `RawListing`: Intermediate representation of a candidate variant scraped from a source.
- `NewModelEntry`: Canonical report entry containing first-seen dates, pricing, specs, images, source provenance, confidence rating, and review flags.
- `RunReport`: Aggregated weekly payload containing metadata, execution summary counts, errors, and identified models.

### Key Fields & Options
- `ram_options`, `storage_options`, `color_options`: Always represented as lists to match catalog conventions.
- `fingerprint`: Deterministic lowercase, alphanumeric normalized key (`category:brand:model:variant`).
- `flags`: Explicit diagnostic labels (e.g. `price_not_found`, `spec_mismatch`, `color_not_found`, `low_confidence`) to alert human reviewers.

---

## 4. Crawling Policy & Technical Constraints
1. **Robots.txt Compliance:** Every target path must be tested against robots.txt. Disallowed paths must not be requested.
2. **Per-Domain Rate Limiting:** Enforce a minimum delay (e.g. 3–5 seconds) per host domain.
3. **HTTP Caching:** Raw HTML responses are cached under `.cache/` (default 72 hours max age) to protect remote origins and enable fast, reproducible local testing.
4. **Transient Error Handling:** Retries with exponential backoff for transient issues (5xx, timeouts), while hard 403, 429, or robots disallowance fail fast and loud.
5. **Fault Isolation:** An exception or failure in one source adapter must never abort other sources.

---

## 5. Legal, Terms of Service, and Compliance Review
- Target sources are public product catalog / price indexing directories.
- User-Agent explicitly identifies the crawler and contact address.
- Used-car classifieds, user-generated listings, and personal contact info are strictly out of scope.
- Fingerprints are maintained to ensure minimal crawling volume (incremental delta scraping rather than full-catalog weekly re-crawling).
