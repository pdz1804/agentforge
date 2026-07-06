"""OpenAIModelProvider — chat completions with tool-use.

The message/tool translation and response parsing are split into pure functions
so they can be unit-tested with fake objects, with no network. Construction
never requires a key (lazy resolution), matching AnthropicModelProvider.
"""

import json
import os
from typing import Any

from ..errors import AgentCoreError
from ..interfaces import BaseTool, Message, ModelProvider, ModelResponse, ToolCall


def tools_to_openai(tools: list[BaseTool]) -> list[dict] | None:
    """Our tools -> OpenAI `tools` schema (function calling)."""
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.json_schema(),
            },
        }
        for t in tools
    ]


def messages_to_openai(messages: list[Message]) -> list[dict]:
    """Our neutral messages -> OpenAI chat messages (incl. tool calls/results)."""
    out: list[dict] = []
    for m in messages:
        if m.role == "tool":
            out.append(
                {"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content}
            )
        elif m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id or f"call_{i}",
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                        }
                        for i, tc in enumerate(m.tool_calls)
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def parse_openai_message(message: Any) -> tuple[str, list[ToolCall]]:
    """OpenAI response message -> (text, tool_calls)."""
    text = message.content or ""
    tool_calls: list[ToolCall] = []
    for tc in getattr(message, "tool_calls", None) or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(name=tc.function.name, args=args, id=tc.id))
    return text, tool_calls


class OpenAIModelProvider(ModelProvider):
    provider = "openai"

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None

    async def complete(
        self, messages: list[Message], tools: list[BaseTool] | None = None, **cfg: Any
    ) -> ModelResponse:
        api_key = self._api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise AgentCoreError("OPENAI_API_KEY is not set; cannot call the OpenAI API")
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - optional extra
            raise AgentCoreError(
                "the 'openai' package is not installed; "
                "install with: pip install 'agent-core[openai]'"
            ) from exc

        if self._client is None:
            self._client = AsyncOpenAI(api_key=api_key)
        kwargs: dict[str, Any] = {
            "model": cfg.get("model") or self.model,
            "messages": messages_to_openai(messages),
            "temperature": cfg.get("temperature", 0.2),
            "max_tokens": cfg.get("max_tokens", 1024),
        }
        oai_tools = tools_to_openai(tools or [])
        if oai_tools:
            kwargs["tools"] = oai_tools

        resp = await self._client.chat.completions.create(**kwargs)
        text, tool_calls = parse_openai_message(resp.choices[0].message)
        usage = {}
        if resp.usage:
            usage = {
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
            }
        return ModelResponse(text=text, tool_calls=tool_calls, usage=usage)
