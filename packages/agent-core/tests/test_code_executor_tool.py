"""CodeExecutorTool — offline via a fake executor (no Docker)."""

import asyncio

import pytest
from pydantic import ValidationError

from agent_core import CodeExecutorTool
from agent_core.interfaces import CodeExecutor, ExecResult, RunContext


class FakeExecutor(CodeExecutor):
    def __init__(self, result: ExecResult) -> None:
        self._result = result
        self.seen_ctx: RunContext | None = None

    async def run(self, code: str, ctx: RunContext) -> ExecResult:
        self.seen_ctx = ctx
        return self._result


def test_ok_result_returns_stdout():
    tool = CodeExecutorTool(FakeExecutor(ExecResult(stdout="4\n", exit_code=0)))
    result = asyncio.run(tool.run(code="print(2+2)"))
    assert result.ok is True
    assert result.output.strip() == "4"
    assert result.meta["exit_code"] == 0


def test_nonzero_exit_is_not_ok():
    tool = CodeExecutorTool(FakeExecutor(ExecResult(stderr="boom", exit_code=1)))
    result = asyncio.run(tool.run(code="raise SystemExit(1)"))
    assert result.ok is False
    assert "boom" in result.error


def test_timeout_is_not_ok():
    tool = CodeExecutorTool(FakeExecutor(ExecResult(exit_code=124, timed_out=True)))
    result = asyncio.run(tool.run(code="while True: pass"))
    assert result.ok is False
    assert result.meta["timed_out"] is True


def test_network_is_disabled_by_the_tool():
    fake = FakeExecutor(ExecResult(exit_code=0))
    tool = CodeExecutorTool(fake)
    asyncio.run(tool.run(code="pass", timeout_s=5))
    assert fake.seen_ctx is not None
    assert fake.seen_ctx.allow_network is False
    assert fake.seen_ctx.wall_clock_s == 5


def test_timeout_bounds_validated():
    tool = CodeExecutorTool(FakeExecutor(ExecResult()))
    with pytest.raises(ValidationError):
        asyncio.run(tool.run(code="pass", timeout_s=999))
