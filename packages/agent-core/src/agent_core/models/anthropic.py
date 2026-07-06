"""AnthropicModelProvider — real inference via the Anthropic SDK.

Construction never requires a key (so it can be registered offline, e.g. in
tests); the key and the ``anthropic`` package are resolved lazily on the first
``complete`` call. Default model id is ``claude-sonnet-5`` per project stack.
"""

from __future__ import annotations

import os
from typing import Any

from ..errors import AgentCoreError
from ..interfaces import BaseTool, Message, ModelProvider, ModelResponse


class AnthropicModelProvider(ModelProvider):
    provider = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5", api_key: str | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None  # lazily created, then reused across calls

    async def complete(
        self,
        messages: list[Message],
        tools: list[BaseTool] | None = None,
        **cfg: Any,
    ) -> ModelResponse:
        api_key = self._api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AgentCoreError(
                "ANTHROPIC_API_KEY is not set; cannot call the Anthropic API"
            )
        try:
            from anthropic import AsyncAnthropic  # imported lazily
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise AgentCoreError(
                "the 'anthropic' package is not installed; "
                "install with: pip install 'agent-core[anthropic]'"
            ) from exc

        system = "\n".join(m.content for m in messages if m.role == "system") or None
        conversation = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        if self._client is None:
            self._client = AsyncAnthropic(api_key=api_key)
        # A manifest sets the exact model name; fall back to the instance default.
        # NOTE: tool-use (tool_calls) parsing lands in Phase 3 with real tools;
        # this provider currently returns text only.
        resp = await self._client.messages.create(
            model=cfg.get("model") or self.model,
            max_tokens=cfg.get("max_tokens", 1024),
            temperature=cfg.get("temperature", 0.2),
            system=system,
            messages=conversation,
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return ModelResponse(
            text=text,
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        )
