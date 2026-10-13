# AuctionNow — PK Market Data Engine

Weekly engine that detects **new car and mobile phone models** on Pakistani
sources and produces a reviewable JSON report. See
`AuctionNow_PK_Scraper_Engine_Design.md` for the full design doc — this repo
is Phase 0/1 of that plan.

## What's here

```
pk_market_engine/
├── config.yaml              # sources, rate limits, paths
├── pipeline/
│   ├── schema.py             # Pydantic models = the JSON output contract
│   ├── robots_check.py       # fetch + parse robots.txt BEFORE scraping
│   ├── http_client.py        # rate-limited, cached, polite fetcher
│   ├── fingerprint.py        # "have we seen this model before?" store
│   ├── detector.py           # diffs this run vs last run -> new models
│   ├── output_writer.py      # writes runs/<date>/new_models.json
│   └── orchestrator.py       # wires it all together, runs every adapter
├── adapters/
│   ├── base.py                # interface every source adapter implements
│   ├── cars/pakwheels_new_cars.py
│   └── mobiles/whatmobile.py
├── scripts/run_weekly.py      # entrypoint (what the scheduler calls)
├── storage/fingerprints.json  # the "last run" baseline (starts empty)
└── .github/workflows/weekly_scrape.yml   # weekly cron trigger
```

## Status: scaffold, not finished

The **framework is real and working**: config loading, the robots.txt gate,
rate-limited HTTP client with on-disk caching, the fingerprint/diff logic,
and the JSON writer. Run it now and it will execute end-to-end and produce
a (mostly empty) report — that's by design, see below.

The **two adapters are skeletons**. `fetch_listing()` and `parse_detail()`
have `# TODO` markers instead of real CSS selectors, because I have not
fetched the live pages from inside this chat — selectors must be written
against the actual current HTML, by someone looking at the real page
(view-source or browser devtools), not guessed. That's step 1 below.

## Setup

```bash
cd pk_market_engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Step 1 — before writing any adapter code

```bash
python -m pipeline.robots_check
```

This fetches and parses `robots.txt` for every source in `config.yaml` and
prints what's allowed/disallowed. **Do this for every new source before
writing its adapter.** If a path you need is disallowed, don't scrape it —
flag it in the design doc and find another source or an official API.

## Step 2 — fill in one adapter

Open `adapters/mobiles/whatmobile.py` (simplest site to start with — plain
HTML tables, no JS rendering needed). Steps:

1. Open a real listing page in your browser, view source.
2. Replace the `# TODO` selectors in `fetch_listing()` and `parse_detail()`
   with the real ones.
3. Run just that adapter:
   ```bash
   python -m scripts.run_weekly --adapter whatmobile --limit 5
   ```
4. Check `runs/<today>/new_models.json` — every model should show up as
   "new" on the very first run (empty fingerprint store), which is how you
   confirm parsing worked before testing the diff logic itself.
5. Run it again unchanged — this time `new_models` should be **empty**,
   proving the fingerprint/diff logic works.

Repeat for `adapters/cars/pakwheels_new_cars.py`.

## Step 3 — schedule it

`.github/workflows/weekly_scrape.yml` is ready — it runs every Monday at
02:00 UTC and uploads the run's JSON as a workflow artifact. Turn it on
once both adapters work locally. Add a Slack webhook (see the commented-out
block in the workflow file) once you want weekly notifications.

## Design rules this scaffold already enforces

- **robots.txt is checked before every run**, not just once by hand.
- **Rate-limited per domain** (`config.yaml` → `rate_limit_seconds`),
  default 3s between requests to the same host.
- **Raw HTML is cached** under `.cache/` for a few days, so re-running
  while debugging a parser doesn't hammer the live site.
- **Fingerprint store only updates on a fully successful run** — a crash
  mid-run can't corrupt next week's baseline.
- **Output is additive JSON, never a direct write into AuctionNow's DB.**
  A human reviews `runs/<date>/new_models.json` before anything gets added
  to the product catalog.
