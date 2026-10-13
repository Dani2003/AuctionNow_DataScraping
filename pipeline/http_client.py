"""
Shared fetcher for every adapter. Two things live here on purpose, in one
place, so no adapter can accidentally skip them: per-domain rate limiting,
and on-disk caching of raw HTML.

Production hardening:
- Automatic retry with exponential backoff for transient errors (timeouts, 5xx, network drops).
- Fast and loud failures on 403 (Forbidden), 429 (Rate Limited), and 404 (Not Found).
- Structured logging on retries and cache hits.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from pipeline.logger import get_logger

logger = get_logger("pipeline.http_client")

TRANSIENT_STATUS_CODES = {500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 405, 429}


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: str = ".cache",
        default_rate_limit_seconds: float = 3.0,
        cache_max_age_hours: float = 72.0,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ):
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_rate_limit_seconds = default_rate_limit_seconds
        self.cache_max_age_seconds = cache_max_age_hours * 3600
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
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
                logger.debug("Rate limiting [%s]: sleeping for %.2fs", domain, wait)
                time.sleep(wait)
        self._last_request_time[domain] = time.monotonic()

    def get(self, url: str, rate_limit_seconds: float | None = None, force_refresh: bool = False) -> str:
        """
        Fetch a URL as text, respecting per-domain rate limiting and the
        on-disk cache. Retries on transient errors with backoff.
        Raises httpx.HTTPStatusError on permanent non-2xx responses.
        """
        cache_path = self._cache_path(url)
        if not force_refresh and cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < self.cache_max_age_seconds:
                logger.debug("Cache hit for URL: %s", url)
                return cache_path.read_text(encoding="utf-8")

        domain = urlparse(url).netloc
        attempt = 0

        while True:
            attempt += 1
            self._wait_for_rate_limit(domain, rate_limit_seconds or self.default_rate_limit_seconds)

            try:
                logger.debug("HTTP GET [%s] (attempt %d/%d)", url, attempt, self.max_retries)
                resp = httpx.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                )

                if resp.status_code in NON_RETRYABLE_STATUS_CODES:
                    logger.error("HTTP %d for URL: %s (non-retryable, failing fast)", resp.status_code, url)
                    resp.raise_for_status()

                if resp.status_code in TRANSIENT_STATUS_CODES:
                    if attempt < self.max_retries:
                        delay = self.backoff_factor * (2 ** (attempt - 1))
                        logger.warning(
                            "HTTP %d from %s; retrying in %.2fs (attempt %d/%d)",
                            resp.status_code,
                            url,
                            delay,
                            attempt,
                            self.max_retries,
                        )
                        time.sleep(delay)
                        continue
                    resp.raise_for_status()

                resp.raise_for_status()
                text = resp.text
                cache_path.write_text(text, encoding="utf-8")
                return text

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt < self.max_retries:
                    delay = self.backoff_factor * (2 ** (attempt - 1))
                    logger.warning(
                        "Network/Timeout error fetching %s: %s; retrying in %.2fs (attempt %d/%d)",
                        url,
                        e,
                        delay,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(delay)
                    continue
                logger.error("Max retries exceeded for URL %s: %s", url, e)
                raise
