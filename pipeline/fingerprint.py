"""
The "have we seen this model before" baseline. A flat JSON file is enough
at this scale (hundreds-to-low-thousands of models, not millions) -- no
database needed for v1.

Golden rule: the store is only updated after a FULLY successful run. A
crash mid-run must not corrupt next week's baseline (see orchestrator.py).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class FingerprintStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def has_seen(self, fingerprint: str) -> bool:
        return fingerprint in self._data

    def mark_seen(self, fingerprint: str, run_date: date) -> None:
        if fingerprint not in self._data:
            self._data[fingerprint] = {"first_seen": run_date.isoformat()}
        self._data[fingerprint]["last_seen"] = run_date.isoformat()

    def save(self) -> None:
        """Call this ONLY after a run completes without a fatal error."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)  # atomic on POSIX -- avoids a half-written store
