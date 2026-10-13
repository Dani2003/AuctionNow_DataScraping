"""
Fetch + parse robots.txt for every configured source BEFORE any adapter is
allowed to run. This is a hard gate per the design doc (Section 8), not a
one-time manual check.

Usage:
    python -m pipeline.robots_check
    python -m pipeline.robots_check --source whatmobile --path /Infinix_Note-50-vs-
"""
from __future__ import annotations

import argparse
import sys
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx
import yaml


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def fetch_robots(base_url: str, user_agent: str, timeout: int = 15) -> RobotFileParser:
    robots_url = urljoin(base_url.rstrip("/") + "/", "robots.txt")
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        resp = httpx.get(robots_url, headers={"User-Agent": user_agent}, timeout=timeout, follow_redirects=True)
        if resp.status_code == 200:
            parser.parse(resp.text.splitlines())
        else:
            # No robots.txt, or it errored -> treat as "no explicit rules found".
            # This is NOT the same as "allowed" -- still check the site's
            # Terms of Service by hand; robots.txt alone is not sufficient.
            parser.parse([])
    except httpx.HTTPError as e:
        print(f"  ! could not fetch {robots_url}: {e}", file=sys.stderr)
        parser.parse([])
    return parser


def check_source(source: dict, user_agent: str, test_path: str = "/") -> None:
    base_url = source["base_url"]
    name = source.get("name", source["id"])
    parser = fetch_robots(base_url, user_agent)

    allowed = parser.can_fetch(user_agent, urljoin(base_url, test_path))
    delay = parser.crawl_delay(user_agent)

    status = "ALLOWED" if allowed else "DISALLOWED"
    print(f"[{status}] {name} ({base_url}) — path '{test_path}'")
    if delay:
        print(f"    robots.txt requests a crawl-delay of {delay}s (config has "
              f"{source.get('rate_limit_seconds', '?')}s — make sure yours is >= this)")
    if not allowed:
        print("    -> DO NOT scrape this path. Reconsider the source or find another path/API.")
    print("    NOTE: robots.txt is necessary but not sufficient — also check the site's "
          "Terms of Service by hand before enabling this source in config.yaml.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="Check only this source id")
    ap.add_argument("--path", default="/", help="Path to test, default '/'")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    user_agent = cfg["http"]["user_agent"]
    sources = cfg["sources"]
    if args.source:
        sources = [s for s in sources if s["id"] == args.source]
        if not sources:
            print(f"No source with id '{args.source}' in {args.config}", file=sys.stderr)
            sys.exit(1)

    for source in sources:
        check_source(source, user_agent, args.path)
        print()


if __name__ == "__main__":
    main()
