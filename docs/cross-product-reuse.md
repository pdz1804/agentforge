# Cross-product reuse: FloraLens runs on AgentForge's agent-core

This is the PRD's central thesis made real: the **Unified Agent Core**
(`packages/agent-core`) that powers AgentForge also powers a completely
different product — **FloraLens**, a botanical similarity-search app — with
**zero edits to the core**. FloraLens adds one domain tool and a few YAML
manifests; everything else (manifest schema, registries, LangGraph ReAct
runtime, model providers, memory, guardrails, token streaming, the eval
harness) is the *same code* AgentForge itself runs.

> FloraLens is the sibling repo at `../floralens`. Its own write-up of this
> integration lives in `floralens/docs/cross-product-reuse.md`.

## How FloraLens consumes the core

**1. Editable install** — FloraLens depends on `agent-core` directly, so it
tracks the exact same source AgentForge uses:

```bash
# from the floralens repo
pip install -e ../agentforge/packages/agent-core[openai]
```

**2. Import the public surface** — FloraLens imports from `agent_core`, never
from AgentForge's app layer:

```python
# floralens/apps/api/app/assistant_service.py
from agent_core import (
    AgentManifest, BaseTool, CompiledAgent, Registries, ToolResult,
    build_default_registries, compile_agent, load_manifest_file,
)
```

**3. Extend by registration, not modification** — FloraLens builds the default
registries (echo/openai/anthropic model providers, `web_search`,
`embedding_search`, …) and registers exactly **one** domain tool of its own:

```python
def build_floralens_registries() -> Registries:
    registries = build_default_registries(prompts_dir=_PROMPTS_DIR)
    registries.tools.register("gallery_facts", GalleryFactsTool())  # the only addition
    return registries
```

`GalleryFactsTool` looks a species up in FloraLens's own gallery (read-only) and
returns curated botanical facts. It subclasses the core's `BaseTool` and returns
a core `ToolResult` — no core file is touched.

**4. Compile + stream with the core runtime** — FloraLens loads its manifests
and calls the same `compile_agent` + `astream` AgentForge uses; the SSE trace
(including live token streaming) is surfaced at FloraLens's `POST /api/assistant`:

```python
def compile_naturalist(registries, checkpointer=None):
    manifests = load_naturalist_manifests()      # naturalist + 3 sub-agents
    return compile_agent(
        manifests["naturalist"], registries,
        agents={"identifier": ..., "researcher": ..., "care_advisor": ...},
        checkpointer=checkpointer,
    )
```

## The naturalist agent team (all YAML, no code)

FloraLens defines a four-role multi-agent team as manifests
(`floralens/agents/*.yaml`) — the core's supervisor pattern exposes each
sub-agent to the supervisor as an `ask_<id>` tool:

| Role | Manifest | Tools | Exposed to supervisor as |
|------|----------|-------|--------------------------|
| **Supervisor** | `naturalist.yaml` | `web_search` (fallback) | — |
| **Identifier** | `identifier.yaml` | `gallery_facts` | `ask_identifier` |
| **Researcher** | `researcher.yaml` | `web_search` (Tavily, cited) | `ask_researcher` |
| **Care-Advisor** | `care_advisor.yaml` | `gallery_facts` | `ask_care_advisor` |

## Enforced guardrails from the shared core

The supervisor manifest attaches guardrails from the core's `GuardrailRegistry`
— these are **enforced at runtime** on the final answer, not just prompt text:

```yaml
# floralens/agents/naturalist.yaml
guardrails: [no_medical_dosage, educational_disclaimer, no_secret_exfil]
```

`no_medical_dosage` replaces dosage answers with a refusal,
`educational_disclaimer` appends the not-professional-advice note, and
`no_secret_exfil` redacts leaked credentials — all from `agent_core`, unchanged.

## Memory

FloraLens uses the core's memory subsystem — the `in_memory` provider by default
(swap to `mem0` via `FLORALENS_MEMORY_PROVIDER=mem0`), scoped `user` /
namespace `floralens`, inspectable through FloraLens's `/api/memory` endpoint.
Same provider interface, same code.

## Why this proves the thesis

- **No core edits.** FloraLens registers one tool + provides YAML manifests and
  prompts. It never forks or patches `agent_core`. This is exactly the
  "extend without redesign" guarantee that `test_extension_conformance.py`
  checks (an extension must add capability with **zero diffs** to core files).
- **Radically different domains.** AgentForge is a general agent builder;
  FloraLens is a flower-similarity product. The same runtime, manifest schema,
  streaming, guardrails, and eval harness serve both.
- **One place to improve.** A fix or feature in `agent-core` (e.g. the token
  streaming or guardrails added recently) reaches both products at once.

## Where to look

- FloraLens integration: `floralens/apps/api/app/assistant_service.py`
- Naturalist manifests: `floralens/agents/{naturalist,identifier,researcher,care_advisor}.yaml`
- Prompts: `floralens/prompts/`
- The core they share: `agentforge/packages/agent-core/`
