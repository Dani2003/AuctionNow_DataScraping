"""
Shared fetcher for every adapter. Two things live here on purpose, in one
place, so no adapter can accidentally skip them: per-domain rate limiting,
and on-disk caching of raw HTML.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: str = ".cache",
        default_rate_limit_seconds: float = 3.0,
        cache_max_age_hours: float = 72.0,
        timeout_seconds: float = 15.0,
    ):
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_rate_limit_seconds = default_rate_limit_seconds
        self.cache_max_age_seconds = cache_max_age_hours * 3600
        self.timeout_seconds = timeout_seconds
        self._last_request_time: dict[str, float] = {}

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / f"{digest}.html"

    def _wait_for_rate_limit(self, domain: str, rate_limit_seconds: float) -> None:
        last = self._last_request_time.get(domain)
        if last is not None:
            elapsed = time.monotonic() - last
            wait = rate_limit_seconds - elapsed
            if wait > 0:
                time.sleep(wait)
        self._last_request_time[domain] = time.monotonic()

    def get(self, url: str, rate_limit_seconds: float | None = None) -> str:
        """
        Fetch a URL as text, respecting per-domain rate limiting and the
        on-disk cache. Raises httpx.HTTPStatusError on non-2xx responses.
        """
        cache_path = self._cache_path(url)
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < self.cache_max_age_seconds:
                return cache_path.read_text(encoding="utf-8")

        domain = urlparse(url).netloc
        self._wait_for_rate_limit(domain, rate_limit_seconds or self.default_rate_limit_seconds)

        resp = httpx.get(
            url,
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )
        resp.raise_for_status()
        cache_path.write_text(resp.text, encoding="utf-8")
        return resp.text
