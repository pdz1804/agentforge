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
    supports_token_streaming = True

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None

    async def _prepare(
        self, messages: list[Message], tools: list[BaseTool] | None, cfg: dict[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        """Resolve the key/client (lazily) and build the request kwargs shared
        by the blocking and streaming code paths."""
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
        return self._client, kwargs

    async def complete(
        self, messages: list[Message], tools: list[BaseTool] | None = None, **cfg: Any
    ) -> ModelResponse:
        client, kwargs = await self._prepare(messages, tools, cfg)
        resp = await client.chat.completions.create(**kwargs)
        text, tool_calls = parse_openai_message(resp.choices[0].message)
        usage = {}
        if resp.usage:
            usage = {
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
            }
        return ModelResponse(text=text, tool_calls=tool_calls, usage=usage)

    async def astream_complete(
        self,
        messages: list[Message],
        tools: list[BaseTool] | None = None,
        *,
        on_token: Any = None,
        **cfg: Any,
    ) -> ModelResponse:
        """Server-sent streaming: emit each text delta via ``on_token`` as it
        arrives, reassembling the same ``ModelResponse`` ``complete`` returns.

        Tool-call fragments stream in pieces (a name in the first fragment, the
        JSON arguments across later ones), keyed by ``index`` — they're
        accumulated per index and parsed once the stream closes. Usage arrives
        in a trailing chunk via ``stream_options.include_usage``.
        """
        client, kwargs = await self._prepare(messages, tools, cfg)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        text_parts: list[str] = []
        tc_acc: dict[int, dict[str, Any]] = {}
        usage: dict[str, int] = {}
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = {
                    "input_tokens": chunk.usage.prompt_tokens,
                    "output_tokens": chunk.usage.completion_tokens,
                }
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                text_parts.append(delta.content)
                if on_token is not None:
                    on_token(delta.content)
            for tcd in getattr(delta, "tool_calls", None) or []:
                slot = tc_acc.setdefault(tcd.index, {"id": None, "name": "", "args": ""})
                if getattr(tcd, "id", None):
                    slot["id"] = tcd.id
                fn = getattr(tcd, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments

        tool_calls: list[ToolCall] = []
        for idx in sorted(tc_acc):
            slot = tc_acc[idx]
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(name=slot["name"] or "", args=args, id=slot["id"]))
        return ModelResponse(text="".join(text_parts), tool_calls=tool_calls, usage=usage)
