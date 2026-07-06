"""Provider translation/parsing — pure functions tested offline with fakes.

These cover the robust multi-provider selection surface: our neutral messages
and tools translate to each provider's native format, and each provider's
response parses back into ModelResponse (text + tool_calls). No network.
"""

from types import SimpleNamespace

from agent_core import EchoTool, Message, ToolCall
from agent_core.models.anthropic import (
    messages_to_anthropic,
    parse_anthropic_content,
    tools_to_anthropic,
)
from agent_core.models.openai import (
    messages_to_openai,
    parse_openai_message,
    tools_to_openai,
)


def _conversation() -> list[Message]:
    return [
        Message(role="system", content="be helpful"),
        Message(role="user", content="weather?"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(name="web_search", args={"query": "weather"}, id="c1")],
        ),
        Message(role="tool", content="sunny", tool_call_id="c1", name="web_search"),
    ]


# --- OpenAI ---------------------------------------------------------------- #
def test_openai_tools_schema():
    schema = tools_to_openai([EchoTool()])
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "echo"
    assert "properties" in schema[0]["function"]["parameters"]
    assert tools_to_openai([]) is None


def test_openai_message_translation():
    msgs = messages_to_openai(_conversation())
    assert msgs[0] == {"role": "system", "content": "be helpful"}
    assistant = msgs[2]
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == "web_search"
    tool_msg = msgs[3]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1"


def test_openai_parse_response_with_tool_call():
    message = SimpleNamespace(
        content="thinking",
        tool_calls=[
            SimpleNamespace(
                id="c9",
                function=SimpleNamespace(name="echo", arguments='{"text": "hi"}'),
            )
        ],
    )
    text, calls = parse_openai_message(message)
    assert text == "thinking"
    assert calls[0].name == "echo"
    assert calls[0].args == {"text": "hi"}
    assert calls[0].id == "c9"


# --- Anthropic ------------------------------------------------------------- #
def test_anthropic_tools_schema():
    schema = tools_to_anthropic([EchoTool()])
    assert schema[0]["name"] == "echo"
    assert "input_schema" in schema[0]
    assert tools_to_anthropic([]) is None


def test_anthropic_message_translation_extracts_system_and_blocks():
    system, conv = messages_to_anthropic(_conversation())
    assert system == "be helpful"
    assistant = next(m for m in conv if m["role"] == "assistant")
    assert any(b["type"] == "tool_use" and b["name"] == "web_search" for b in assistant["content"])
    # tool result merged into a user turn as a tool_result block
    tool_turn = conv[-1]
    assert tool_turn["role"] == "user"
    assert tool_turn["content"][0]["type"] == "tool_result"
    assert tool_turn["content"][0]["tool_use_id"] == "c1"


def test_anthropic_parse_content_blocks():
    blocks = [
        SimpleNamespace(type="text", text="hello "),
        SimpleNamespace(type="tool_use", id="t1", name="echo", input={"text": "x"}),
    ]
    text, calls = parse_anthropic_content(blocks)
    assert text == "hello "
    assert calls[0].name == "echo"
    assert calls[0].args == {"text": "x"}
    assert calls[0].id == "t1"
