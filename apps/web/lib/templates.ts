// Starter manifests for the template gallery. YAML text so the editor is
// authored the same way manifests live on disk (YAML-first authoring).

export type Template = {
  key: string;
  label: string;
  yaml: string;
  input: string;
  eval_mode: boolean;
  // Child sub-agent manifest YAMLs for a supervisor template. Sent to the run
  // endpoint as `agents: [...]` (parsed to dicts) alongside `manifest`, per
  // POST /api/runs' RunRequest.agents contract — see apps/api/app/main.py.
  agents?: string[];
};

export const TEMPLATES: Template[] = [
  {
    key: "echo",
    label: "Echo (offline, deterministic)",
    input: "hello agentforge",
    eval_mode: true,
    yaml: `id: echo_agent
version: 1
model:
  provider: echo
  name: echo
  temperature: 0.2
prompt_ref: prompts/echo_agent.md
tools:
  - echo
`,
  },
  {
    key: "assistant",
    label: "Web-search assistant (OpenAI + Tavily)",
    input: "Use web_search to find who won the 2022 FIFA World Cup, then answer in one sentence.",
    eval_mode: false,
    yaml: `id: assistant
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
tools:
  - web_search
limits:
  max_steps: 12
`,
  },
  {
    key: "coder",
    label: "Code-runner (sandboxed Python)",
    input: "Compute the 15th Fibonacci number by running Python in the sandbox.",
    eval_mode: false,
    yaml: `id: coder
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
tools:
  - code_executor
limits:
  max_steps: 12
`,
  },
  {
    key: "supervisor",
    label: "Multi-agent supervisor",
    input:
      "Ask the planner sub-agent to outline 3 steps for building a to-do list app, " +
      "then ask the coder sub-agent to write the code for step 1. Combine both " +
      "sub-agent answers into your final answer.",
    eval_mode: false,
    // The supervisor delegates via `sub_agents: [<child id>, ...]`; each id must
    // match a child manifest's own `id` and be listed in `agents` below. The
    // runtime exposes each child as an `ask_<id>` tool (agents-as-tools),
    // modeled on packages/agent-core/tests/test_multi_agent.py.
    yaml: `id: supervisor
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
sub_agents:
  - planner
  - coder
limits:
  max_steps: 12
`,
    agents: [
      `id: planner
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
limits:
  max_steps: 6
`,
      `id: coder
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
tools:
  - code_executor
limits:
  max_steps: 6
`,
    ],
  },
  {
    key: "mcp",
    label: "MCP tools (public server)",
    input: "Use the echo tool to echo the exact text: MCP is working.",
    eval_mode: false,
    yaml: `id: mcp_demo
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
tools: []
mcp_servers:
  - everything
limits:
  max_steps: 8
`,
  },
  {
    key: "embedding_search",
    label: "Semantic search over indexed docs",
    input:
      "Use embedding_search to find documents about AgentForge, then summarize the most relevant result.",
    eval_mode: false,
    yaml: `id: embedding_search_demo
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
tools:
  - embedding_search
limits:
  max_steps: 8
`,
  },
  {
    key: "http_fetch",
    label: "HTTP fetch",
    input: "Fetch https://example.com and tell me the page title.",
    eval_mode: false,
    yaml: `id: http_fetch_demo
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
tools:
  - http_fetch
limits:
  max_steps: 8
`,
  },
  {
    key: "guardrails",
    label: "Guardrails (educational disclaimer)",
    // Elicit a plain-text answer with NO disclaimer, so educational_disclaimer
    // visibly appends one to the final answer — the guardrail is demonstrated
    // mutating output. (Kept separate from io_schema: a text-mutating guardrail
    // and strict JSON validation conflict, since io_schema runs after guardrails.)
    input: "In one sentence, how often should I water a small succulent on a sunny windowsill?",
    eval_mode: false,
    yaml: `id: guardrails_demo
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
guardrails:
  - educational_disclaimer
limits:
  max_steps: 6
`,
  },
  {
    key: "io_schema",
    label: "io_schema (JSON output)",
    // Strict output shape: the run fails validation unless the answer parses as
    // a JSON object. The prompt is explicit about raw JSON (no code fences) so
    // the happy path is demonstrated; io_schema still guards malformed output.
    input:
      'Reply with ONLY a raw JSON object — no markdown, no code fences, no prose, ' +
      'starting with { and ending with }. Use keys "plant" and "tip", filled with ' +
      "a short houseplant watering tip.",
    eval_mode: false,
    yaml: `id: io_schema_demo
version: 1
model:
  provider: openai
  name: gpt-4o-mini
  temperature: 0.2
prompt_ref: prompts/assistant.md
io_schema:
  output: json_object
limits:
  max_steps: 6
`,
  },
];
