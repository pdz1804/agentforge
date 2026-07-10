"""Load KEY=VALUE pairs from .env file(s) into the process environment.

No python-dotenv dependency — a tiny parser so a locally-run `uvicorn` picks up
API keys (and DATABASE_URL etc.) from .env the same way docker-compose or a
sourced shell would, instead of silently starting with none of them set (which
otherwise surfaces only later as "OPENAI_API_KEY is not set" on the first run).

Only variables NOT already present are set, so an explicitly-exported variable
always wins over the file. Files are read in order; the first file to define a
key wins. Values are never returned or logged.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env_files(*paths: str | Path) -> dict[str, str]:
    """Set missing env vars from the given .env files.

    Returns ``{key: source_path}`` for the vars this call actually set (for
    optional non-secret logging of *which* keys loaded — never their values).
    """
    loaded: dict[str, str] = {}
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip('"').strip("'")
            loaded[key] = str(p)
    return loaded
