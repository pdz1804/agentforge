"""EchoModelProvider — an offline, deterministic model used for local dev and
tests. It echoes the last user message, so the harness can run end-to-end
without any API key. Real inference uses AnthropicModelProvider.
"""

from __future__ import annotations

from typing import Any

from ..interfaces import BaseTool, Message, ModelProvider, ModelResponse


class EchoModelProvider(ModelProvider):
    provider = "echo"

    async def complete(
        self,
        messages: list[Message],
        tools: list[BaseTool] | None = None,
        **cfg: Any,
    ) -> ModelResponse:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        return ModelResponse(text=last_user, usage={"input_tokens": 0, "output_tokens": 0})
