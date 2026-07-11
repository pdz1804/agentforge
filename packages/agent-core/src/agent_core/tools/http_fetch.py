"""HttpFetchTool — fetch a URL over HTTP(S) and return its status + a capped body.

Only ``http``/``https`` schemes are allowed; anything else (``file://``,
``ftp://``, a bare/missing scheme, ...) is rejected up front as a non-ok
``ToolResult`` — the request is never attempted. Uses ``httpx`` (already a core
dependency, see ``web_search.py``); network errors/timeouts become a non-ok
``ToolResult`` too, mirroring ``web_search``/``code_executor``: never a crash.
"""

from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from ..interfaces import BaseTool, ToolResult

_ALLOWED_SCHEMES = {"http", "https"}
# Keeps a single fetch from flooding the model's context with an entire page;
# generous enough for API responses and article text.
_MAX_BODY_CHARS = 4000
_DEFAULT_TIMEOUT_S = 20.0


class HttpFetchArgs(BaseModel):
    url: str
    method: str = "GET"
    headers: dict[str, str] | None = None


class HttpFetchTool(BaseTool):
    name = "http_fetch"
    description = (
        "Fetch a URL over HTTP or HTTPS and return its status code and response "
        "body (capped to the first ~4000 characters). Only http/https URLs are "
        "allowed; any other scheme is rejected."
    )
    args_schema = HttpFetchArgs

    def __init__(self, timeout_s: float = _DEFAULT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    async def run(self, **kwargs: Any) -> ToolResult:
        args = self.validate_args(**kwargs)
        scheme = urlparse(args.url).scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            return ToolResult(
                ok=False,
                error=(
                    f"unsupported URL scheme '{scheme or '(none)'}'; "
                    f"only http/https are allowed"
                ),
            )

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.request(
                    args.method.upper(), args.url, headers=args.headers
                )
        except Exception as exc:  # timeouts/connection errors -> tool failure, not a crash
            return ToolResult(ok=False, error=f"http_fetch failed: {exc}")

        body = resp.text
        truncated = len(body) > _MAX_BODY_CHARS
        return ToolResult(
            ok=True,
            output=body[:_MAX_BODY_CHARS],
            meta={
                "status_code": resp.status_code,
                "url": str(resp.url),
                "truncated": truncated,
            },
        )
