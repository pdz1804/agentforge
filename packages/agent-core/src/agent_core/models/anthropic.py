"""AnthropicModelProvider — real inference via the Anthropic SDK, with tool-use.

Construction never requires a key (so it can be registered offline, e.g. in
tests); the key and the ``anthropic`` package are resolved lazily on the first
``complete`` call. Default model id is ``claude-sonnet-5`` per project stack.

Message/tool translation and response parsing are split into pure functions so
they can be unit-tested with fake objects, no network.
"""

import os
from typing import Any

from ..errors import AgentCoreError
from ..interfaces import BaseTool, Message, ModelProvider, ModelResponse, ToolCall


def tools_to_anthropic(tools: list[BaseTool]) -> list[dict] | None:
    """Our tools -> Anthropic `tools` schema."""
    if not tools:
        return None
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.args_schema.model_json_schema(),
        }
        for t in tools
    ]


def messages_to_anthropic(messages: list[Message]) -> tuple[str | None, list[dict]]:
    """Our neutral messages -> (system, anthropic messages).

    Assistant tool calls become ``tool_use`` blocks; ``role="tool"`` results
    become ``tool_result`` blocks merged into a user turn (Anthropic requires
    tool results in a user message immediately following the tool_use).
    """
    system_parts: list[str] = []
    conv: list[dict] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
        elif m.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.tool_call_id or "",
                "content": m.content,
            }
            if conv and conv[-1]["role"] == "user" and isinstance(conv[-1]["content"], list):
                conv[-1]["content"].append(block)
            else:
                conv.append({"role": "user", "content": [block]})
        elif m.role == "assistant" and m.tool_calls:
            blocks: list[dict] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                blocks.append(
                    {"type": "tool_use", "id": tc.id or "tu", "name": tc.name, "input": tc.args}
                )
            conv.append({"role": "assistant", "content": blocks})
        else:
            conv.append({"role": m.role, "content": m.content})
    return ("\n".join(system_parts) or None), conv


def parse_anthropic_content(content_blocks: list[Any]) -> tuple[str, list[ToolCall]]:
    """Anthropic response content blocks -> (text, tool_calls)."""
    text = ""
    tool_calls: list[ToolCall] = []
    for block in content_blocks:
        btype = getattr(block, "type", None)
        if btype == "text":
            text += block.text
        elif btype == "tool_use":
            tool_calls.append(ToolCall(name=block.name, args=dict(block.input), id=block.id))
    return text, tool_calls


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
            raise AgentCoreError("ANTHROPIC_API_KEY is not set; cannot call the Anthropic API")
        try:
            from anthropic import AsyncAnthropic  # imported lazily
        except ImportError as exc:  # pragma: no cover - optional extra
            raise AgentCoreError(
                "the 'anthropic' package is not installed; "
                "install with: pip install 'agent-core[anthropic]'"
            ) from exc

        system, conversation = messages_to_anthropic(messages)
        if self._client is None:
            self._client = AsyncAnthropic(api_key=api_key)

        # A manifest sets the exact model name; fall back to the instance default.
        kwargs: dict[str, Any] = {
            "model": cfg.get("model") or self.model,
            "max_tokens": cfg.get("max_tokens", 1024),
            "temperature": cfg.get("temperature", 0.2),
            "messages": conversation,
        }
        if system is not None:  # omit rather than send system=null
            kwargs["system"] = system
        anthropic_tools = tools_to_anthropic(tools or [])
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        resp = await self._client.messages.create(**kwargs)
        text, tool_calls = parse_anthropic_content(resp.content)
        return ModelResponse(
            text=text,
            tool_calls=tool_calls,
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        )
