"""Sandbox security matrix — runs REAL Docker containers.

Skipped automatically when the docker CLI/daemon is unavailable. These are the
build-blocking isolation guarantees (PRD Section 14.4): each attack must be
contained. Slow (each test spins a throwaway container).
"""

import asyncio
import shutil
import subprocess

import pytest

from agent_core import DockerCodeExecutor
from agent_core.interfaces import RunContext


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, timeout=15
            ).returncode
            == 0
        )
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker not available")

_EXECUTOR = DockerCodeExecutor()


def _run(code: str, timeout: int = 20, net: bool = False):
    return asyncio.run(
        _EXECUTOR.run(code, RunContext(wall_clock_s=timeout, allow_network=net))
    )


def test_happy_path_executes():
    result = _run("print(2 + 2)")
    assert result.exit_code == 0
    assert result.stdout.strip() == "4"
    assert result.timed_out is False


def test_network_egress_is_blocked():
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except Exception:\n"
        "    print('BLOCKED')\n"
    )
    result = _run(code)
    assert "BLOCKED" in result.stdout
    assert "CONNECTED" not in result.stdout


def test_host_filesystem_write_is_denied():
    code = (
        "try:\n"
        "    open('/pwned', 'w').write('x')\n"
        "    print('WROTE')\n"
        "except Exception:\n"
        "    print('DENIED')\n"
    )
    result = _run(code)
    assert "DENIED" in result.stdout
    assert "WROTE" not in result.stdout


def test_non_allowlisted_import_fails():
    result = _run("import requests")
    assert result.exit_code != 0
    assert "ModuleNotFoundError" in result.stderr


def test_infinite_loop_is_killed_by_timeout():
    result = _run("while True:\n    pass\n", timeout=5)
    assert result.timed_out is True
    assert result.exit_code == 124


def test_stdout_is_capped():
    # A chatty program must not exhaust host memory; output is byte-capped.
    result = _run("print('A' * 50000)")
    assert len(result.stdout) <= 10_000
    assert "truncated" in result.stderr


def test_runs_as_non_root():
    result = _run("import os\nprint(os.getuid())")
    assert result.stdout.strip() == "65534"  # nobody, not root


def test_memory_bomb_is_killed():
    # 1 GiB against a 256m cap -> OOM-killed (nonzero) or MemoryError.
    result = _run("x = bytearray(1024 * 1024 * 1024)\nprint('OK')\n", timeout=20)
    assert not (result.exit_code == 0 and "OK" in result.stdout)
