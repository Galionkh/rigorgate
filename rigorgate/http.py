from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


class ProviderError(RuntimeError):
    """A provider returned an invalid, unauthorized, or exhausted response."""


@dataclass(frozen=True)
class HttpConfig:
    timeout_seconds: int = 45
    attempts: int = 3
    backoff_seconds: float = 1.5


def get_json(
    base_url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    config: HttpConfig | None = None,
) -> Any:
    cfg = config or HttpConfig()
    query = urllib.parse.urlencode(
        [(key, value) for key, value in (params or {}).items() if value is not None]
    )
    url = f"{base_url}?{query}" if query else base_url
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "RigorGate-Alpha-Scanner/0.2",
            **dict(headers or {}),
        },
    )
    last_error: Exception | None = None
    for attempt in range(cfg.attempts):
        try:
            with urllib.request.urlopen(request, timeout=cfg.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            content_type = (exc.headers.get("Content-Type", "") if exc.headers else "").lower()
            body = exc.read().decode("utf-8", errors="replace").strip()
            detail = ""
            if "html" not in content_type and body:
                detail = f": {body[:240]}"
            last_error = ProviderError(f"HTTP {exc.code} from {base_url}{detail}")
            if exc.code not in {429, 500, 502, 503, 504}:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt + 1 < cfg.attempts:
            time.sleep(cfg.backoff_seconds * (2**attempt))
    raise ProviderError(f"Request failed for {base_url}: {last_error}")
