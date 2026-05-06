"""Bounded idempotency cache for observation writes."""

from __future__ import annotations

import hashlib
from collections import OrderedDict


class ObservationDeduper:
    """LRU of observation keys keyed by thread/profile/kind/normalized text."""

    def __init__(self, max_size: int = 512) -> None:
        self.max_size = max(1, int(max_size))
        self._seen: OrderedDict[str, None] = OrderedDict()

    def __len__(self) -> int:
        return len(self._seen)

    def should_write(self, thread: str, profile: str, kind: str, text: str) -> bool:
        key = self._key(thread, profile, kind, text)
        if key in self._seen:
            self._seen.move_to_end(key)
            return False
        self._seen[key] = None
        while len(self._seen) > self.max_size:
            self._seen.popitem(last=False)
        return True

    @staticmethod
    def _key(thread: str, profile: str, kind: str, text: str) -> str:
        normalized = " ".join((text or "").split()).casefold()
        raw = "\0".join([thread or "", profile or "", kind or "", normalized])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
