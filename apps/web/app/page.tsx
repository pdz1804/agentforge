"use client";

import { motion, useReducedMotion } from "motion/react";
import ThemeToggle from "./ThemeToggle";
import {
  BoltIcon,
  CheckIcon,
  CoinIcon,
  CubeIcon,
  DocIcon,
  GaugeIcon,
  GraphIcon,
  LogoMark,
  PlayIcon,
  PlugIcon,
  TraceIcon,
} from "./icons";
import { EASE, cardHoverProps, revealContainer, revealItem } from "./motion-presets";
import styles from "./landing.module.css";

// External destinations. The console lives in-app at /app; the repo + docs are
// the public project links surfaced in the nav-less footer.
const CONSOLE_HREF = "/app";
const REPO_HREF = "https://github.com/pdz1804/agentforge";
const DOCS_HREF = "https://github.com/pdz1804/agentforge/tree/main/docs";

const REVEAL_VIEWPORT = { once: true, amount: 0.25 } as const;

const FLOW = [
  { Icon: DocIcon, title: "Author", body: "Pick a template or write a manifest, then set the input to run against." },
  { Icon: CheckIcon, title: "Validate", body: "Check the manifest against the core schema before you spend a token." },
  { Icon: PlayIcon, title: "Run", body: "Execute inside the Docker sandbox and stream the trace as it happens." },
  { Icon: GraphIcon, title: "Observe", body: "Read the answer, replay the execution graph, and check the run cost." },
];

const STRENGTHS = [
  {
    Icon: GaugeIcon,
    title: "Deterministic evaluation",
    body: "Eval runs use temperature zero and isolated memory, so pass and fail stay stable across repeated attempts.",
  },
  {
    Icon: CoinIcon,
    title: "Per-run cost accounting",
    body: "Token usage rolls up into a USD figure for each run, so you can compare configurations side by side.",
  },
  {
    Icon: CubeIcon,
    title: "Sandbox isolation",
    body: "Generated code runs deny-by-default: no network or host filesystem access until you explicitly grant it.",
  },
];

export default function LandingPage() {
  const reduce = useReducedMotion() ?? false;
  const container = reduce ? undefined : revealContainer;
  const item = reduce ? undefined : revealItem;
  const reveal = reduce
    ? {}
    : ({ initial: "hidden", whileInView: "show", viewport: REVEAL_VIEWPORT } as const);
  const heroIn = (delay: number) =>
    reduce
      ? {}
      : ({
          initial: { opacity: 0, y: 18 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.55, ease: EASE, delay },
        } as const);

  return (
    <div className={styles.page}>
      {/* ---- Navigation ---- */}
      <header className={styles.nav}>
        <nav className={styles.navInner} aria-label="Primary">
          <a className={styles.brand} href={CONSOLE_HREF}>
            <span className={styles.brandMark} aria-hidden="true">
              <LogoMark />
            </span>
            AgentForge
          </a>
          <span className={styles.navSpacer} />
          <div className={styles.navRight}>
            <ThemeToggle />
            <a className={`${styles.cta} ${styles.ctaPrimary}`} href={CONSOLE_HREF}>
              Open the console
            </a>
          </div>
        </nav>
      </header>

      {/* ---- Hero: asymmetric split, copy left, real manifest right ---- */}
      <section className={styles.hero}>
        <div className={styles.heroBg} aria-hidden="true" />
        <div className={styles.heroGrid}>
          <motion.div className={styles.heroCopy} {...heroIn(0)}>
            <h1 className={styles.heroTitle}>
              Build agents in YAML. <span className={styles.accent}>See every step they take.</span>
            </h1>
            <p className={styles.heroLede}>
              A workbench for composing models, tools, and memory, then running each agent in a sandbox with a live
              trace.
            </p>
            <div className={styles.heroActions}>
              <a className={`${styles.cta} ${styles.ctaPrimary} ${styles.ctaLg}`} href={CONSOLE_HREF}>
                <PlayIcon />
                Open the console
              </a>
              <a className={`${styles.cta} ${styles.ctaGhost} ${styles.ctaLg}`} href={DOCS_HREF}>
                <DocIcon />
                Docs
              </a>
            </div>
          </motion.div>

          <motion.div className={styles.artifact} {...heroIn(0.12)}>
            <div className={styles.artifactHead}>
              <span className={styles.artifactFile}>assistant.yaml</span>
              <span className={styles.artifactTag}>manifest</span>
            </div>
            <pre className={styles.code}>
              <code>
                <span className={styles.ln}><span className={styles.yKey}>id</span><span className={styles.yPunc}>:</span> <span className={styles.yStr}>assistant</span></span>
                <span className={styles.ln}><span className={styles.yKey}>version</span><span className={styles.yPunc}>:</span> <span className={styles.yNum}>1</span></span>
                <span className={styles.ln}><span className={styles.yKey}>model</span><span className={styles.yPunc}>:</span></span>
                <span className={styles.ln}>{"  "}<span className={styles.yKey}>provider</span><span className={styles.yPunc}>:</span> <span className={styles.yStr}>openai</span></span>
                <span className={styles.ln}>{"  "}<span className={styles.yKey}>name</span><span className={styles.yPunc}>:</span> <span className={styles.yStr}>gpt-4o-mini</span></span>
                <span className={styles.ln}>{"  "}<span className={styles.yKey}>temperature</span><span className={styles.yPunc}>:</span> <span className={styles.yNum}>0.2</span></span>
                <span className={styles.ln}><span className={styles.yKey}>prompt_ref</span><span className={styles.yPunc}>:</span> <span className={styles.yStr}>prompts/assistant.md</span></span>
                <span className={styles.ln}><span className={styles.yKey}>tools</span><span className={styles.yPunc}>:</span></span>
                <span className={styles.ln}>{"  "}<span className={styles.yDash}>-</span> <span className={styles.yStr}>web_search</span></span>
                <span className={styles.ln}><span className={styles.yKey}>limits</span><span className={styles.yPunc}>:</span></span>
                <span className={styles.ln}>{"  "}<span className={styles.yKey}>max_steps</span><span className={styles.yPunc}>:</span> <span className={styles.yNum}>12</span></span>
              </code>
            </pre>
            {/* Node/edge motif - echoes the run's model -> tool -> answer graph. */}
            <div className={styles.motif}>
              <svg
                className={styles.motifSvg}
                viewBox="0 0 320 56"
                preserveAspectRatio="xMidYMid meet"
                aria-hidden="true"
              >
                <path className={styles.motifEdge} d="M40 28 H120" />
                <path className={styles.motifEdge} d="M140 28 H200" />
                <path className={styles.motifEdge} d="M220 28 H280" />
                <circle className={`${styles.motifNode} ${styles.pulse0}`} cx="28" cy="28" r="11" />
                <circle className={`${styles.motifNode} ${styles.pulse1}`} cx="130" cy="28" r="11" />
                <circle className={`${styles.motifNode} ${styles.pulse2}`} cx="210" cy="28" r="11" />
                <circle className={`${styles.motifNode} ${styles.pulse3}`} cx="292" cy="28" r="11" />
                <text className={styles.motifLabel} x="28" y="52" textAnchor="middle">start</text>
                <text className={styles.motifLabel} x="130" y="52" textAnchor="middle">model</text>
                <text className={styles.motifLabel} x="210" y="52" textAnchor="middle">tool</text>
                <text className={styles.motifLabel} x="292" y="52" textAnchor="middle">answer</text>
              </svg>
            </div>
          </motion.div>
        </div>
      </section>

      {/* ---- Capability bento ---- */}
      <section className={styles.section}>
        <div className={styles.shell}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>From manifest to trace, in one console</h2>
            <p className={styles.sectionSub}>
              The pieces you compose, and the parts that watch them run. Every capability below ships in the builder.
            </p>
          </div>

          <motion.div className={styles.bento} variants={container} {...reveal}>
            {/* Cell 1 - declarative manifests, with a real snippet */}
            <motion.article
              className={`${styles.cell} ${styles.cellWide}`}
              variants={item}
              {...cardHoverProps(reduce)}
            >
              <span className={styles.cellIco}><DocIcon /></span>
              <h3 className={styles.cellTitle}>Declarative manifests</h3>
              <p className={styles.cellBody}>
                Describe an agent in one YAML file: model, tools, memory, and limits. Validate it against the schema
                before anything runs.
              </p>
              <div className={styles.snippet}>
                <code>
                  <span className={styles.ln}><span className={styles.yKey}>tools</span><span className={styles.yPunc}>:</span></span>
                  <span className={styles.ln}>{"  "}<span className={styles.yDash}>-</span> <span className={styles.yStr}>web_search</span></span>
                  <span className={styles.ln}>{"  "}<span className={styles.yDash}>-</span> <span className={styles.yStr}>code_executor</span></span>
                  <span className={styles.ln}><span className={styles.yKey}>memory</span><span className={styles.yPunc}>:</span> <span className={styles.yStr}>semantic</span></span>
                </code>
              </div>
            </motion.article>

            {/* Cell 2 - LangGraph runtime, with the node motif */}
            <motion.article
              className={`${styles.cell} ${styles.cellWide}`}
              variants={item}
              {...cardHoverProps(reduce)}
            >
              <span className={styles.cellIco}><TraceIcon /></span>
              <h3 className={styles.cellTitle}>LangGraph runtime</h3>
              <p className={styles.cellBody}>
                A graph-based control loop drives the model, tool, and answer cycle in deterministic, inspectable steps.
              </p>
              <div className={styles.cellMotif}>
                <svg className={styles.cellMotifSvg} viewBox="0 0 300 48" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
                  <path className={styles.motifEdge} d="M28 24 H120" />
                  <path className={styles.motifEdge} d="M138 24 H206" />
                  <path className={styles.motifEdge} d="M138 24 C170 24 170 8 138 8 C120 8 120 24 138 24" />
                  <path className={styles.motifEdge} d="M224 24 H278" />
                  <circle className={`${styles.motifNode} ${styles.pulse0}`} cx="24" cy="24" r="9" />
                  <circle className={`${styles.motifNode} ${styles.pulse1}`} cx="130" cy="24" r="9" />
                  <circle className={`${styles.motifNode} ${styles.pulse2}`} cx="214" cy="24" r="9" />
                  <circle className={`${styles.motifNode} ${styles.pulse3}`} cx="286" cy="24" r="9" />
                </svg>
              </div>
            </motion.article>

            {/* Cell 3 - Docker sandbox */}
            <motion.article className={`${styles.cell} ${styles.cellThird}`} variants={item} {...cardHoverProps(reduce)}>
              <span className={styles.cellIco}><CubeIcon /></span>
              <h3 className={styles.cellTitle}>Docker sandbox</h3>
              <p className={styles.cellBody}>
                Generated code runs in an isolated container. No host filesystem or network unless you allow it.
              </p>
            </motion.article>

            {/* Cell 4 - Live trace + cost, tinted panel */}
            <motion.article
              className={`${styles.cell} ${styles.cellThird} ${styles.cellTinted}`}
              variants={item}
              {...cardHoverProps(reduce)}
            >
              <span className={styles.cellIco}><BoltIcon /></span>
              <h3 className={styles.cellTitle}>Live trace and cost</h3>
              <p className={styles.cellBody}>
                Every step streams over SSE with token usage, then rolls up into a per-run cost.
              </p>
              <div className={styles.costStrip}>
                <div className={styles.costRow}>
                  <span className={`${styles.costTag} ${styles.model}`}>model</span>
                  <span className={`${styles.costTag} ${styles.tool}`}>tool</span>
                  <span className={`${styles.costTag} ${styles.answer}`}>answer</span>
                </div>
                <div className={styles.costRow}>
                  <span className={styles.k}>cost:</span> rolled up per run in USD
                </div>
              </div>
            </motion.article>

            {/* Cell 5 - Eval harness */}
            <motion.article className={`${styles.cell} ${styles.cellThird}`} variants={item} {...cardHoverProps(reduce)}>
              <span className={styles.cellIco}><GaugeIcon /></span>
              <h3 className={styles.cellTitle}>Eval harness</h3>
              <p className={styles.cellBody}>
                Grade runs on a dev and held-out split. A regression gate blocks promotion when the held-out pass rate
                drops.
              </p>
            </motion.article>

            {/* Cell 6 - MCP tools */}
            <motion.article className={`${styles.cell} ${styles.cellThird}`} variants={item} {...cardHoverProps(reduce)}>
              <span className={styles.cellIco}><PlugIcon /></span>
              <h3 className={styles.cellTitle}>MCP tools</h3>
              <p className={styles.cellBody}>
                Connect MCP servers and expose their tools to an agent through the same manifest, behind stable
                interfaces.
              </p>
            </motion.article>
          </motion.div>
        </div>
      </section>

      {/* ---- How a run works: verb-led flow ---- */}
      <section className={styles.section}>
        <div className={styles.shell}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>How a run works</h2>
          </div>
          <motion.div className={styles.flow} variants={container} {...reveal}>
            {FLOW.map((s) => (
              <motion.div className={styles.flowStep} key={s.title} variants={item}>
                <span className={styles.flowIco}><s.Icon /></span>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ---- Strengths: divided rows ---- */}
      <section className={styles.section}>
        <div className={styles.shell}>
          <div className={styles.sectionHead}>
            <h2 className={styles.sectionTitle}>Made to be inspected</h2>
            <p className={styles.sectionSub}>
              The details that keep a run honest, not just a demo that happened to work once.
            </p>
          </div>
          <motion.div className={styles.strengths} variants={container} {...reveal}>
            {STRENGTHS.map((s) => (
              <motion.div className={styles.strengthRow} key={s.title} variants={item}>
                <span className={styles.strengthIco}><s.Icon /></span>
                <div className={styles.strengthText}>
                  <h3>{s.title}</h3>
                  <p>{s.body}</p>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ---- Final CTA band ---- */}
      <section className={styles.section}>
        <div className={styles.shell}>
          <div className={styles.ctaBand}>
            <h2 className={styles.ctaBandTitle}>Open the console and author your first agent</h2>
            <div className={styles.ctaBandActions}>
              <a className={`${styles.cta} ${styles.ctaPrimary} ${styles.ctaLg}`} href={CONSOLE_HREF}>
                <PlayIcon />
                Open the console
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ---- Footer ---- */}
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            <span className={styles.footerBrandRow}>
              <span className={styles.brandMark} aria-hidden="true">
                <LogoMark />
              </span>
              AgentForge
            </span>
            <p className={styles.footerNote}>
              A demo build of the AgentForge workbench: author agents in YAML, run them in a sandbox, and watch the
              trace.
            </p>
          </div>
          <div className={styles.footerLinks}>
            <div className={styles.footerCol}>
              <span className={styles.footerColHead}>Project</span>
              <a className={styles.footerLink} href={REPO_HREF}>GitHub</a>
              <a className={styles.footerLink} href={DOCS_HREF}>Docs</a>
            </div>
            <div className={styles.footerCol}>
              <span className={styles.footerColHead}>Product</span>
              <a className={styles.footerLink} href={CONSOLE_HREF}>Open the console</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
