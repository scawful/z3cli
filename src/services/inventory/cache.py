"""Small TTL cache for inventory snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any


@dataclass
class InventoryCacheEntry:
    snapshot: dict[str, Any]
    observed_monotonic_s: float


@dataclass
class InventoryCache:
    ttl_ms: int = 5000
    generation: int = 0
    _entries: dict[str, InventoryCacheEntry] = field(default_factory=dict)

    def get(self, source: str, *, allow_stale: bool = False) -> dict[str, Any] | None:
        entry = self._entries.get(str(source or "active"))
        if entry is None:
            return None
        if allow_stale or not self.is_stale(source):
            return dict(entry.snapshot)
        return None

    def put(self, source: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        self.generation += 1
        key = str(source or "active")
        stored = dict(snapshot)
        stored["generation"] = self.generation
        stored.setdefault("ttlMs", self.ttl_ms)
        self._entries[key] = InventoryCacheEntry(
            snapshot=stored,
            observed_monotonic_s=time.monotonic(),
        )
        return dict(stored)

    def is_stale(self, source: str) -> bool:
        entry = self._entries.get(str(source or "active"))
        if entry is None:
            return True
        ttl_ms = int(entry.snapshot.get("ttlMs") or self.ttl_ms)
        if ttl_ms <= 0:
            return False
        age_ms = int((time.monotonic() - entry.observed_monotonic_s) * 1000)
        return age_ms > ttl_ms

    def clear(self) -> None:
        self._entries.clear()
