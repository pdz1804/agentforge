// Starter manifests for the template gallery. YAML text so the editor is
// authored the same way manifests live on disk (YAML-first authoring).

export type Template = { key: string; label: string; yaml: string; input: string; eval_mode: boolean };

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
];
