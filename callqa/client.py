"""Minimal Bolna REST client (stdlib only) for the two endpoints callqa reads.

- GET /v2/agent/{agent_id}/executions   paginated, from/to required, <= 7 days
- GET /executions/{execution_id}/debug  execution + per-turn latency + transcript
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

BASE_URL = "https://api.bolna.ai"
MAX_WINDOW = timedelta(days=7)

# (method, url, headers) -> parsed JSON. Swappable so tests never hit the network.
Transport = Callable[[str, str, dict], dict]


def urllib_transport(method: str, url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https host)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BolnaError(e.code, e.read().decode("utf-8", "replace")[:300]) from None


class BolnaError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Bolna API returned {status}: {body}")
        self.status = status


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class BolnaClient:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL,
                 transport: Transport = urllib_transport):
        self.api_key = api_key or os.environ.get("BOLNA_API_KEY")
        if not self.api_key:
            raise ValueError("set BOLNA_API_KEY or pass api_key")
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    def _get(self, path: str, params: dict | None = None) -> dict:
        q = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{self.base_url}{path}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        return self.transport("GET", url, {"Authorization": f"Bearer {self.api_key}",
                                           "Accept": "application/json"})

    def get_debug(self, execution_id: str, include: str | None = None) -> dict:
        return self._get(f"/executions/{urllib.parse.quote(execution_id)}/debug", {"include": include})

    def iter_executions(self, agent_id: str, start: datetime, end: datetime,
                        status: str | None = "completed", page_size: int = 50) -> Iterator[dict]:
        """Yield executions in [start, end), splitting into the API's 7-day windows."""
        lo = start
        while lo < end:
            hi = min(lo + MAX_WINDOW, end)
            page = 1
            while True:
                body = self._get(f"/v2/agent/{urllib.parse.quote(agent_id)}/executions", {
                    "from": _iso(lo), "to": _iso(hi), "status": status,
                    "page_number": page, "page_size": page_size,
                })
                yield from body.get("data") or []
                if not body.get("has_more"):
                    break
                page += 1
            lo = hi
