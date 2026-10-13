"""
Every source adapter implements this interface. Keep adapters dumb and
isolated: one broken site must never take down the others (see orchestrator
.py, which catches per-adapter exceptions).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pipeline.http_client import PoliteClient
from pipeline.schema import RawListing


class BaseAdapter(ABC):
    source_id: str       # must match an id in config.yaml -> sources
    category: str         # "car" | "mobile"

    def __init__(self, client: PoliteClient, base_url: str, rate_limit_seconds: float):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.rate_limit_seconds = rate_limit_seconds

    @abstractmethod
    def list_candidates(self) -> list[dict]:
        """
        Cheap step: return a list of {"brand", "model", "variant", "url"}
        dicts from a listing/index page -- NOT full specs yet. This is what
        gets fingerprinted to decide what's new, before any detail fetch.
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_detail(self, candidate: dict) -> RawListing:
        """
        Expensive step: fetch the full detail page for ONE candidate and
        return a complete RawListing. Only called for candidates the
        detector has confirmed are new.
        """
        raise NotImplementedError
