# AuctionNow — PK Market Data Engine

Weekly discovery pipeline that detects **newly released car and mobile phone models** on Pakistani market sources, fetches complete specifications for confirmed-new models, and produces a reviewable JSON report (`runs/<date>/new_models.json`).

> **Core Principle**: This pipeline is strictly additive and human-in-the-loop. It generates reviewable reports and **NEVER** writes directly to production product/catalog databases.

---

## Architecture Overview

```
pk_market_engine/
├── config.yaml                     # Sources, rate limits, storage paths (strictly validated)
├── pipeline/
│   ├── config_schema.py            # Pydantic models validating config.yaml at startup
│   ├── logger.py                   # Structured logging (timestamps, levels, context)
│   ├── schema.py                   # JSON output contract (RawListing, NewModelEntry, RunReport)
│   ├── robots_check.py             # robots.txt compliance gate
│   ├── http_client.py              # Polite rate-limited fetcher with retries & on-disk cache
│   ├── fingerprint.py              # Incremental discovery store (storage/fingerprints.json)
│   ├── detector.py                 # Fuzzy diffing & naming variant deduplication
│   ├── output_writer.py            # Writes runs/<date>/new_models.json
│   └── orchestrator.py             # Wires execution, fault isolation & reports
├── adapters/
│   ├── base.py                     # Base adapter interface (list_candidates + fetch_detail)
│   ├── mobiles/
│   │   ├── whatmobile.py           # WhatMobile adapter (table specs, PKR prices, variants)
│   │   └── priceoye.py             # PriceOye adapter (Schema.org JSON-LD & DOM parser)
│   └── cars/
│       ├── pakwheels_new_cars.py   # PakWheels new car catalog adapter
│       └── toyota_indus.py         # Indus Motor Company (Toyota Pakistan) official specs
├── tests/
│   ├── fixtures/                   # Real offline HTML snapshots
│   ├── test_adapters.py            # Unit tests for all adapters
│   └── test_pipeline.py            # Unit tests for fingerprinting, detector, & resilience
├── scripts/run_weekly.py           # CLI entrypoint
├── storage/fingerprints.json       # Persisted baseline of known models
└── .github/workflows/
    ├── ci.yml                      # CI: runs lint (ruff) and offline test suite
    └── weekly_scrape.yml           # Weekly cron trigger and artifact publisher
```

---

## Active & Verified Sources

| Source ID | Category | Domain | Extraction Technique |
|-----------|----------|--------|----------------------|
| `whatmobile` | Mobile | `whatmobile.com.pk` | Structured spec tables, PKR price regex, color & RAM tokens |
| `priceoye` | Mobile | `priceoye.pk` | Schema.org Product JSON-LD, size/color swatch selectors |
| `pakwheels_new_cars` | Car | `pakwheels.com` | Automotive specs tables, CDN pictures, variant price matrix |
| `indus_motor_toyota` | Car | `toyota-indus.com` | Official manufacturer vehicle catalogs, dimension tables |

---

## Setup & Local Development

```bash
# 1. Clone repository
git clone https://github.com/Dani2003/AuctionNow_DataScraping.git
cd AuctionNow_DataScraping

# 2. Create and activate virtual environment
python3 -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running the Pipeline

```bash
# Run all enabled sources
python -m scripts.run_weekly

# Run a single source with limit (ideal for quick verification)
python -m scripts.run_weekly --adapter whatmobile --limit 5
python -m scripts.run_weekly --adapter priceoye --limit 5
python -m scripts.run_weekly --adapter pakwheels_new_cars --limit 5
python -m scripts.run_weekly --adapter indus_motor_toyota --limit 5
```

---

## Testing & Quality Gates

The test suite runs **100% offline** using saved HTML fixtures located in `tests/fixtures/`:

```bash
# Run offline test suite
pytest -v

# Run linter
ruff check .
```

---

## How to Add a New Source (Step-by-Step Guide)

Adding a new source is repeatable, testable, and gated by compliance checks:

### Step 1: Compliance & robots.txt Gate
Before writing any scraper code, check the robots.txt permissions:
```bash
python -m pipeline.robots_check --source <new_source_id> --path <target_path>
```
> [!IMPORTANT]
> If the path is disallowed in `robots.txt`, **DO NOT SCRAPE IT**. Find an alternative official path or API.

### Step 2: Capture HTML Fixtures
Save realistic sample pages under `tests/fixtures/` so tests never depend on the live web:
1. Save an index/listing page as `tests/fixtures/<source>_listing.html`.
2. Save a representative model/detail page as `tests/fixtures/<source>_detail.html`.

### Step 3: Implement Adapter Subclass
Create a new adapter file in `adapters/mobiles/<source>.py` or `adapters/cars/<source>.py` inheriting from `BaseAdapter`:

```python
from adapters.base import BaseAdapter
from pipeline.schema import RawListing, Category, SourceRef

class MyNewSourceAdapter(BaseAdapter):
    source_id = "my_source"
    category = "mobile"  # or "car"

    def list_candidates(self) -> list[dict]:
        html = self.client.get(self.base_url, rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_candidates_from_html(html)

    def parse_candidates_from_html(self, html: str) -> list[dict]:
        # Pure parsing logic for testability
        ...
        return [{"brand": brand, "model": model, "variant": variant, "url": url}]

    def fetch_detail(self, candidate: dict) -> RawListing:
        html = self.client.get(candidate["url"], rate_limit_seconds=self.rate_limit_seconds)
        return self.parse_detail_from_html(candidate, html)

    def parse_detail_from_html(self, candidate: dict, html: str) -> RawListing:
        # Extract specs, price_pkr, color_options, images
        ...
        return RawListing(...)
```

### Step 4: Register the Adapter
In `pipeline/orchestrator.py`, add your adapter to `ADAPTER_REGISTRY`:
```python
ADAPTER_REGISTRY = {
    ...
    "my_source": "adapters.mobiles.my_source:MyNewSourceAdapter",
}
```

### Step 5: Configure in `config.yaml`
Add the source definition to `config.yaml`:
```yaml
  - id: my_source
    category: mobile
    name: "My Source Name"
    base_url: "https://example.com"
    enabled: true
    rate_limit_seconds: 4
```

### Step 6: Write Offline Unit Tests
In `tests/test_adapters.py`, add fixture tests:
```python
def test_my_source_candidates_from_fixture(dummy_client):
    html = (FIXTURES_DIR / "my_source_listing.html").read_text(encoding="utf-8")
    adapter = MyNewSourceAdapter(dummy_client, "https://example.com", rate_limit_seconds=0)
    candidates = adapter.parse_candidates_from_html(html)
    assert len(candidates) > 0
```
Run `pytest -v` to ensure tests pass offline.

### Step 7: Verify Live End-to-End Execution
Run the new source with a small limit:
```bash
python -m scripts.run_weekly --adapter my_source --limit 5
```
- Verify `runs/<date>/new_models.json` contains valid models.
- Run a second time with the same command to confirm `new_models` returns **0** (proving fingerprint diffing works).
