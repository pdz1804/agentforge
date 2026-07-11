"""HttpFetchTool — offline via a monkeypatched httpx.AsyncClient (no real network)."""

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from agent_core import HttpFetchTool
from agent_core.interfaces import ToolResult


def test_http_fetch_requires_url():
    tool = HttpFetchTool()
    with pytest.raises(ValidationError):
        asyncio.run(tool.run())


def test_http_fetch_rejects_non_http_scheme():
    tool = HttpFetchTool()
    result = asyncio.run(tool.run(url="file:///etc/passwd"))
    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert "scheme" in result.error


def test_http_fetch_rejects_url_with_no_scheme():
    tool = HttpFetchTool()
    result = asyncio.run(tool.run(url="example.com/data"))
    assert result.ok is False
    assert "scheme" in result.error


class _FakeResponse:
    def __init__(self, status_code: int, text: str, url: str) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient; records the call and returns a canned response."""

    last_call: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def request(self, method, url, headers=None):
        _FakeAsyncClient.last_call = {"method": method, "url": url, "headers": headers}
        return _FakeResponse(200, "x" * 5000, url)


def test_http_fetch_success_returns_capped_body(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    tool = HttpFetchTool()
    result = asyncio.run(tool.run(url="https://example.com/data", headers={"X-Test": "1"}))

    assert result.ok is True
    assert len(result.output) == 4000  # capped from the 5000-char fake body
    assert result.meta["status_code"] == 200
    assert result.meta["truncated"] is True
    assert _FakeAsyncClient.last_call == {
        "method": "GET",
        "url": "https://example.com/data",
        "headers": {"X-Test": "1"},
    }


def test_http_fetch_short_body_is_not_marked_truncated(monkeypatch):
    class _ShortClient(_FakeAsyncClient):
        async def request(self, method, url, headers=None):
            return _FakeResponse(200, "short body", url)

    monkeypatch.setattr(httpx, "AsyncClient", _ShortClient)

    tool = HttpFetchTool()
    result = asyncio.run(tool.run(url="https://example.com/short"))

    assert result.ok is True
    assert result.output == "short body"
    assert result.meta["truncated"] is False


def test_http_fetch_network_error_is_non_ok_not_a_crash(monkeypatch):
    class _BoomClient(_FakeAsyncClient):
        async def request(self, method, url, headers=None):
            raise httpx.ConnectTimeout("connection timed out")

    monkeypatch.setattr(httpx, "AsyncClient", _BoomClient)

    tool = HttpFetchTool()
    result = asyncio.run(tool.run(url="https://example.com/data"))

    assert result.ok is False
    assert "http_fetch failed" in result.error
