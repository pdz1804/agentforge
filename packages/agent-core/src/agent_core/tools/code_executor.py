"""CodeExecutorTool — lets an agent run Python in the sandbox.

Wraps any ``CodeExecutor`` (Docker today, E2B later) so a "coder" agent can
compute things by running code. A nonzero exit / timeout becomes a non-ok
ToolResult the model can react to, never a crash.
"""

from typing import Any

from pydantic import BaseModel, Field

from ..interfaces import BaseTool, CodeExecutor, RunContext, ToolResult


class CodeExecArgs(BaseModel):
    code: str
    timeout_s: int = Field(default=15, ge=1, le=60)


class CodeExecutorTool(BaseTool):
    name = "code_executor"
    description = (
        "Execute a short Python script in an isolated sandbox (no network, no host "
        "access, stdlib only) and return its stdout, or the error on failure."
    )
    args_schema = CodeExecArgs

    def __init__(self, executor: CodeExecutor) -> None:
        self._executor = executor

    async def run(self, **kwargs: Any) -> ToolResult:
        args = self.validate_args(**kwargs)
        ctx = RunContext(wall_clock_s=args.timeout_s, allow_network=False)
        try:
            result = await self._executor.run(args.code, ctx)
        except Exception as exc:
            return ToolResult(ok=False, error=f"sandbox failed: {exc}")

        ok = result.exit_code == 0 and not result.timed_out
        meta = {"exit_code": result.exit_code, "timed_out": result.timed_out}
        if ok:
            return ToolResult(ok=True, output=result.stdout, meta=meta)
        detail = result.stderr or f"exit code {result.exit_code}"
        return ToolResult(ok=False, output=result.stdout, error=detail, meta=meta)
