from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from callqa.client import BolnaClient


class FakeTransport:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, method, url, headers):
        self.calls.append((method, url, headers))
        return self.pages.pop(0) if self.pages else {"data": [], "has_more": False}


def test_requires_key(monkeypatch):
    monkeypatch.delenv("BOLNA_API_KEY", raising=False)
    with pytest.raises(ValueError):
        BolnaClient()


def test_debug_url_auth_and_include():
    t = FakeTransport([{"execution_id": "abc"}])
    BolnaClient("k", transport=t).get_debug("abc", include="execution,progression")
    method, url, headers = t.calls[0]
    assert method == "GET" and headers["Authorization"] == "Bearer k"
    assert urlparse(url).path == "/executions/abc/debug"
    assert parse_qs(urlparse(url).query)["include"] == ["execution,progression"]


def test_executions_paginate_and_split_into_7_day_windows():
    t = FakeTransport([{"data": [{"id": "1"}], "has_more": True}, {"data": [{"id": "2"}], "has_more": False},
                       {"data": [{"id": "3"}], "has_more": False}])
    c = BolnaClient("k", transport=t)
    start, end = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert [e["id"] for e in c.iter_executions("ag", start, end)] == ["1", "2", "3"]
    qs = [parse_qs(urlparse(u).query) for _, u, _ in t.calls]
    assert [q["page_number"] for q in qs] == [["1"], ["2"], ["1"]]
    assert qs[0]["from"] == ["2026-10-01T00:00:00.000Z"] and qs[0]["to"] == ["2026-10-08T00:00:00.000Z"]
    assert qs[2]["from"] == ["2026-10-08T00:00:00.000Z"] and qs[2]["to"] == ["2026-10-10T00:00:00.000Z"]
    assert all(q["status"] == ["completed"] for q in qs)
    assert urlparse(t.calls[0][1]).path == "/v2/agent/ag/executions"


def test_http_error_becomes_bolna_error(monkeypatch):
    import io
    import urllib.error

    from callqa import client

    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                     io.BytesIO(b'{"detail":"Unrecognized access token"}'))

    monkeypatch.setattr(client.urllib.request, "urlopen", boom)
    with pytest.raises(client.BolnaError) as e:
        BolnaClient("bad").get_debug("abc")
    assert e.value.status == 403 and "Unrecognized access token" in str(e.value)
