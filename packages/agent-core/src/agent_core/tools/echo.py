"""EchoTool — the minimal tool that proves the wiring end to end."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..interfaces import BaseTool, ToolResult


class EchoArgs(BaseModel):
    text: str


class EchoTool(BaseTool):
    name = "echo"
    description = "Return the input text unchanged. Proves tool registration and invocation."
    args_schema = EchoArgs

    async def run(self, **kwargs: Any) -> ToolResult:
        args = self.validate_args(**kwargs)
        return ToolResult(ok=True, output=args.text)
