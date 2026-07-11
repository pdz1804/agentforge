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
        "access, stdlib only) and return its stdout, or the error on failure. Only "
        "stdout is captured, so you MUST print() any value you want back — e.g. "
        "print(result); a script that computes a value but never prints returns nothing."
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
            # A successful run with no stdout almost always means the script
            # computed a value but never printed it. Return an explicit hint
            # instead of an empty string so the model prints next time rather
            # than silently retrying the same output-less code.
            output = result.stdout
            if not output.strip():
                output = (
                    "(the script ran successfully but produced no stdout — "
                    "print() the value you want returned, e.g. print(result))"
                )
            return ToolResult(ok=True, output=output, meta=meta)
        detail = result.stderr or f"exit code {result.exit_code}"
        return ToolResult(ok=False, output=result.stdout, error=detail, meta=meta)
