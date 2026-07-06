"""DockerCodeExecutor — run untrusted Python in a locked-down throwaway container.

Isolation (deny-by-default, PRD Section 15):
- No host mounts, so the host filesystem is unreachable; no env is forwarded.
- ``--network none`` by default (opt-in via RunContext.allow_network).
- Read-only rootfs; tmpfs /tmp mounted noexec,nosuid,nodev.
- Runs as an unprivileged uid, all capabilities dropped, no-new-privileges.
- CPU / memory / pids limits; memory-swap pinned to memory (no swap escape).
- Only the base image's stdlib is present, so a non-allowlisted third-party
  import fails naturally (nothing extra is installed).

The code is fed over stdin to ``python -`` — no host file is written or mounted,
and no shell is involved (args go straight to ``docker`` via exec). stdout/stderr
are read with a byte cap so a chatty program cannot exhaust host memory.

Requires the ``docker`` CLI where this runs; E2B/Firecracker can later implement
the same ``CodeExecutor`` interface without touching callers.
"""

import asyncio
import uuid

from ..interfaces import CodeExecutor, ExecResult, RunContext

_OUTPUT_CAP = 10_000  # bytes of stdout/stderr retained (host-memory bound)
_MIN_WALL_CLOCK_S = 1


class DockerCodeExecutor(CodeExecutor):
    def __init__(
        self,
        image: str = "python:3.11-slim",
        memory: str = "256m",
        cpus: str = "1.0",
        pids_limit: int = 128,
        run_as_uid: str = "65534:65534",  # nobody:nogroup
    ) -> None:
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.run_as_uid = run_as_uid

    def _docker_args(self, name: str, ctx: RunContext) -> list[str]:
        args = [
            "docker", "run", "--rm", "-i", "--name", name,
            "--user", self.run_as_uid,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--memory", self.memory, "--memory-swap", self.memory,
            "--cpus", str(self.cpus), "--pids-limit", str(self.pids_limit),
            "--read-only", "--tmpfs", "/tmp:size=16m,noexec,nosuid,nodev",
        ]
        if not ctx.allow_network:
            args += ["--network", "none"]
        args += [self.image, "python", "-"]
        return args

    async def run(self, code: str, ctx: RunContext) -> ExecResult:
        wall_clock = max(ctx.wall_clock_s, _MIN_WALL_CLOCK_S)
        name = f"afsbx-{uuid.uuid4().hex[:12]}"
        proc = await asyncio.create_subprocess_exec(
            *self._docker_args(name, ctx),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            return await asyncio.wait_for(
                self._drive(proc, code), timeout=wall_clock
            )
        except TimeoutError:
            await _docker_remove(name)
            _kill(proc)
            return ExecResult(
                stderr=f"timed out after {wall_clock}s", exit_code=124, timed_out=True
            )

    async def _drive(self, proc: asyncio.subprocess.Process, code: str) -> ExecResult:
        proc.stdin.write(code.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        (out, out_over), (err, err_over) = await asyncio.gather(
            _read_capped(proc.stdout, _OUTPUT_CAP),
            _read_capped(proc.stderr, _OUTPUT_CAP),
        )
        await proc.wait()
        stderr = err.decode("utf-8", "replace")
        if out_over or err_over:
            stderr = (stderr + "\n[output truncated]").strip()
        return ExecResult(
            stdout=out.decode("utf-8", "replace"),
            stderr=stderr,
            exit_code=proc.returncode if proc.returncode is not None else 0,
        )


async def _read_capped(stream: asyncio.StreamReader, cap: int) -> tuple[bytes, bool]:
    """Read up to ``cap`` bytes; stop early if the stream exceeds it."""
    chunks: list[bytes] = []
    total = 0
    while total <= cap:
        chunk = await stream.read(8192)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)[:cap], total > cap


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass


async def _docker_remove(name: str) -> None:
    """Force-remove the container (kills it if running). Best-effort, retried."""
    for _ in range(2):
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if await proc.wait() == 0:
                return
        except Exception:
            return
