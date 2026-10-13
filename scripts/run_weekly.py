"""
Entrypoint. This is what the scheduler (GitHub Actions cron, or you running
it by hand) calls.

Usage:
    python -m scripts.run_weekly                       # run all enabled sources
    python -m scripts.run_weekly --adapter whatmobile   # just one, for testing
    python -m scripts.run_weekly --adapter whatmobile --limit 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# allow running as `python -m scripts.run_weekly` from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.orchestrator import run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", help="Run only this source id (e.g. whatmobile)")
    ap.add_argument("--limit", type=int, help="Only process the first N candidates (for testing)")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    run(config_path=args.config, only_source=args.adapter, limit=args.limit)


if __name__ == "__main__":
    main()
