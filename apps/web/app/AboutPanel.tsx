"use client";

import { motion, useReducedMotion } from "motion/react";
import {
  BoltIcon,
  CheckIcon,
  CoinIcon,
  CubeIcon,
  DocIcon,
  GraphIcon,
  LayersIcon,
  LogoMark,
  PlugIcon,
  TraceIcon,
} from "./icons";
import { cardHoverProps, heroProps, revealContainer, revealItem } from "./motion-presets";

// Shared scroll-reveal wiring for a grid/list section: gentle stagger, once
// per mount, triggered when a quarter of the block scrolls into view.
const REVEAL_VIEWPORT = { once: true, amount: 0.25 } as const;

const PILLARS = [
  {
    Icon: LayersIcon,
    title: "Multi-agent workbench",
    body: "Author, validate, run, and replay agents from one console — no boilerplate, no redeploys between iterations.",
  },
  {
    Icon: CubeIcon,
    title: "Unified Agent Core",
    body: "A single runtime contract for models, tools, memory, and control flow so every agent behaves consistently.",
  },
  {
    Icon: GraphIcon,
    title: "Sandboxed execution",
    body: "Runs stream inside an isolated Docker sandbox with live tracing and per-run cost accounting.",
  },
];

const FEATURES = [
  {
    Icon: DocIcon,
    title: "Declarative manifests",
    body: "Describe an agent in a compact YAML manifest — model, tools, memory, and limits. Validate before you run.",
  },
  {
    Icon: PlugIcon,
    title: "Pluggable everything",
    body: "Swap models, tools, memory backends, and MCP servers behind stable interfaces without touching agent logic.",
  },
  {
    Icon: TraceIcon,
    title: "LangGraph runtime",
    body: "A graph-based control loop drives the model→tool→answer cycle with deterministic, inspectable steps.",
  },
  {
    Icon: CubeIcon,
    title: "Docker sandbox",
    body: "Each run executes in a contained environment, keeping tool side-effects and untrusted output isolated.",
  },
  {
    Icon: BoltIcon,
    title: "Live trace stream",
    body: "Watch every step arrive over SSE — nodes, tool calls, token usage — and replay them on the 3D graph.",
  },
  {
    Icon: CoinIcon,
    title: "Cost accounting",
    body: "Token usage rolls up into a per-run USD cost so you can compare configurations at a glance.",
  },
];

const STEPS = [
  {
    title: "Pick a template",
    body: (
      <>
        Open the <b>Builder</b> tab and choose a starter from the <b>Template</b> menu — it seeds the manifest and a
        sample input.
      </>
    ),
  },
  {
    title: "Author the manifest",
    body: (
      <>
        Edit the YAML to set the model, tools, memory, and limits. Toggle <code>eval mode</code> for deterministic,
        graded runs.
      </>
    ),
  },
  {
    title: "Validate",
    body: (
      <>
        Click <b>Validate</b> to check the manifest against the core schema before spending a single token.
      </>
    ),
  },
  {
    title: "Run & observe",
    body: (
      <>
        Hit <b>Run agent</b> to stream the trace live, read the final answer, and inspect the reconstructed execution
        graph and cost.
      </>
    ),
  },
];

export default function AboutPanel() {
  const reduce = useReducedMotion() ?? false;
  const container = reduce ? undefined : revealContainer;
  const item = reduce ? undefined : revealItem;
  const reveal = reduce
    ? {}
    : ({ initial: "hidden", whileInView: "show", viewport: REVEAL_VIEWPORT } as const);
  return (
    <div className="about" data-testid="about-page">
      <motion.section className="about-hero" {...heroProps(reduce)}>
        <span className="about-eyebrow">
          <LogoMark />
          Unified Agent Core
        </span>
        <h2>
          Build, run, and replay agents on <span className="grad">AgentForge</span>.
        </h2>
        <p className="about-lede">
          AgentForge is a multi-agent workbench built on the Unified Agent Core: a declarative way to compose models,
          tools, memory, and MCP servers, execute them inside a Docker sandbox, and watch every step stream back with
          full trace and cost visibility.
        </p>
        <div className="about-cta">
          <span className="pill info">Declarative</span>
          <span className="pill info">Pluggable</span>
          <span className="pill info">Sandboxed</span>
          <span className="pill info">Observable</span>
        </div>
      </motion.section>

      <motion.div className="about-pillars" variants={container} {...reveal}>
        {PILLARS.map((p) => (
          <motion.article className="pillar" key={p.title} variants={item}>
            <span className="ico">
              <p.Icon />
            </span>
            <h3>{p.title}</h3>
            <p>{p.body}</p>
          </motion.article>
        ))}
      </motion.div>

      <div className="about-section-h">
        <h3>Key capabilities</h3>
        <span className="rule" />
      </div>
      <motion.div className="feature-grid" variants={container} {...reveal}>
        {FEATURES.map((f) => (
          <motion.article
            className="feature"
            key={f.title}
            variants={item}
            {...cardHoverProps(reduce)}
          >
            <div className="fhead">
              <span className="fico">
                <f.Icon />
              </span>
              <h4>{f.title}</h4>
            </div>
            <p>{f.body}</p>
          </motion.article>
        ))}
      </motion.div>

      <div className="about-section-h">
        <h3>How to use</h3>
        <span className="rule" />
      </div>
      <motion.div className="steps" variants={container} {...reveal}>
        {STEPS.map((s, i) => (
          <motion.div className="step-item" key={s.title} variants={item}>
            <span className="num">{i + 1}</span>
            <div className="stxt">
              <h4>{s.title}</h4>
              <p>{s.body}</p>
            </div>
          </motion.div>
        ))}
      </motion.div>

      <div className="about-foot">
        <CheckIcon aria-hidden="true" style={{ width: 14, height: 14, color: "var(--ok)" }} />
        Ready when you are — switch to the <b>&nbsp;Builder&nbsp;</b> tab to author your first agent.
      </div>
    </div>
  );
}
