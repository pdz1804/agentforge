"""Embedding functions. An embed fn is async ``(text) -> list[float]``.

``openai_embed`` is the live default (lazy key/SDK). Tests inject a deterministic
fake, so nothing here needs a network call to be exercised.
"""

import os

from .errors import AgentCoreError


async def openai_embed(
    text: str, model: str = "text-embedding-3-small", api_key: str | None = None
) -> list[float]:
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise AgentCoreError("OPENAI_API_KEY is not set; cannot embed")
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - optional extra
        raise AgentCoreError(
            "the 'openai' package is not installed; install with: pip install 'agent-core[openai]'"
        ) from exc
    # Construct per call so a per-request key is never masked by a cached client;
    # the SDK pools connections internally.
    client = AsyncOpenAI(api_key=key)
    resp = await client.embeddings.create(model=model, input=text)
    return resp.data[0].embedding
