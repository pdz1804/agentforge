# agent-core

**Unified Agent Core** — a declarative, provider-agnostic runtime for building
LLM agents from YAML manifests. It's the shared core that powers
[AgentForge](https://github.com/pdz1804/agentforge) and, unmodified, the
naturalist assistant in [FloraLens](https://github.com/pdz1804/floralens) —
proving one runtime can serve very different products.

## Features

- **Declarative manifests** — define an agent (model, prompt, tools, limits,
  guardrails, io-schema) in YAML; load + validate fail-fast.
- **Pluggable registries** — register model providers, tools, prompts, memory
  backends, and guardrails; extend without editing the core.
- **LangGraph ReAct runtime** with **live token streaming** over an SSE-friendly
  trace bus.
- **Model providers** — OpenAI, Anthropic, and an offline Echo provider for
  deterministic tests.
- **Built-in tools** — web search, HTTP fetch, sandboxed code execution,
  embedding search; plus MCP auto-binding for external tool servers.
- **Multi-agent supervisor** — expose sub-agents to a supervisor as tools.
- **Guardrails & io-schema** enforced at runtime; **memory** (in-memory / mem0);
  opt-in durable **SQLite checkpointer** for multi-turn threads.
- **Evaluation harness** — dev/held-out suites, programmatic/rubric/LLM-judge
  scoring, and a regression gate.

## Install

```bash
pip install "pdz-agent-core[openai]"   # + OpenAI provider; imported as `agent_core`
# extras: [anthropic] [mem0] [mcp] [dev]
```

## Quickstart

```python
from agent_core import build_default_registries, compile_agent, load_manifest_dict

manifest = {
    "id": "echo_agent",
    "model": {"provider": "echo", "name": "test-model"},
    "prompt_ref": "prompts/echo_agent.md",
    "tools": [],
}
agent = compile_agent(load_manifest_dict(manifest), build_default_registries())

async for event in agent.astream("hello"):
    print(event.type, event.detail)
```

## Documentation

Full architecture, API, and the cross-product reuse write-up live in the
AgentForge repo under [`docs/`](https://github.com/pdz1804/agentforge/tree/main/docs).

## License

MIT © pdz1804
