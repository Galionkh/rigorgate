from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class JsonFundamentalCache:
    """Small auditable cache for slow-changing provider bundles; never stores credentials."""

    SCHEMA_VERSION = 2

    def __init__(self, root: Path, ttl_days: int = 14) -> None:
        self.root = root
        self.ttl = timedelta(days=ttl_days)

    @classmethod
    def from_environment(cls) -> "JsonFundamentalCache":
        return cls(
            Path(os.getenv("GALION_CACHE_DIR", "data/cache/fundamentals")),
            ttl_days=int(os.getenv("GALION_CACHE_TTL_DAYS", "14")),
        )

    def _path(self, symbol: str) -> Path:
        normalized = "".join(char for char in symbol.upper() if char.isalnum() or char in {"-", "."})
        if not normalized:
            raise ValueError("invalid cache symbol")
        return self.root / f"{normalized}.json"

    def get(self, symbol: str, now: datetime | None = None) -> dict[str, Any] | None:
        path = self._path(symbol)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.SCHEMA_VERSION:
                return None
            fetched_at = datetime.fromisoformat(str(payload["fetched_at_utc"]))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        current = now or datetime.now(timezone.utc)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if current - fetched_at > self.ttl:
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    def set(self, symbol: str, data: dict[str, Any], now: datetime | None = None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(symbol)
        current = now or datetime.now(timezone.utc)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "symbol": symbol.upper(),
            "fetched_at_utc": current.isoformat(),
            "data": data,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def prune(self, max_age_days: int = 180, now: datetime | None = None) -> int:
        if not self.root.exists():
            return 0
        current = now or datetime.now(timezone.utc)
        removed = 0
        for path in self.root.glob("*.json"):
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if current - modified > timedelta(days=max_age_days):
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed
