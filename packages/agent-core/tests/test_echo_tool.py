"""EchoTool + EchoModelProvider — proves tool/model invocation offline."""

import asyncio

import pytest
from pydantic import ValidationError

from agent_core import EchoModelProvider, EchoTool, Message, ToolResult


def test_echo_tool_returns_input():
    tool = EchoTool()
    result = asyncio.run(tool.run(text="hello world"))
    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert result.output == "hello world"


def test_echo_tool_validates_args():
    tool = EchoTool()
    with pytest.raises(ValidationError):  # missing required 'text'
        asyncio.run(tool.run(wrong="x"))


def test_echo_model_provider_echoes_last_user_message():
    provider = EchoModelProvider()
    messages = [
        Message(role="system", content="ignored"),
        Message(role="user", content="first"),
        Message(role="user", content="second"),
    ]
    resp = asyncio.run(provider.complete(messages))
    assert resp.text == "second"
