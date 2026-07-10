"""OpenAIModelProvider.astream_complete reconstructs text, tool-calls (streamed
as fragments), and usage from a mocked SSE chunk stream — no network."""
import asyncio
import types

from agent_core.models.openai import OpenAIModelProvider


def _chunk(content=None, tool_calls=None, usage=None):
    has_choice = content is not None or tool_calls is not None
    delta = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = types.SimpleNamespace(delta=delta)
    return types.SimpleNamespace(choices=[choice] if has_choice else [], usage=usage)


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()


class _FakeClient:
    def __init__(self, chunks):
        async def create(**kwargs):
            assert kwargs.get("stream") is True
            assert kwargs.get("stream_options") == {"include_usage": True}
            return _FakeStream(chunks)

        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))


def test_astream_reconstructs_text_tool_calls_and_usage():
    # A tool call streams as fragments: name + first arg-slice, then the rest.
    frag1 = types.SimpleNamespace(
        index=0, id="call_1",
        function=types.SimpleNamespace(name="web_search", arguments='{"q":'),
    )
    frag2 = types.SimpleNamespace(
        index=0, id=None,
        function=types.SimpleNamespace(name=None, arguments='"cats"}'),
    )
    chunks = [
        _chunk(content="Hel"),
        _chunk(content="lo"),
        _chunk(tool_calls=[frag1]),
        _chunk(tool_calls=[frag2]),
        _chunk(usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=7)),
    ]
    provider = OpenAIModelProvider(model="gpt-4o-mini", api_key="test-key")
    provider._client = _FakeClient(chunks)  # skip real client construction

    tokens: list[str] = []
    resp = asyncio.run(provider.astream_complete([], on_token=tokens.append))

    assert tokens == ["Hel", "lo"]  # deltas delivered live, in order
    assert resp.text == "Hello"
    assert resp.usage == {"input_tokens": 5, "output_tokens": 7}
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.name == "web_search"
    assert tc.args == {"q": "cats"}  # fragments joined then JSON-parsed
    assert tc.id == "call_1"
