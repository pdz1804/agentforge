"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import type { TraceEvent } from "@/lib/api";
import type { Group, Mesh, MeshStandardMaterial } from "three";
import { PauseIcon, PlayIcon } from "./icons";

// ---------------------------------------------------------------------------
// Timeline reconstruction
// ---------------------------------------------------------------------------
// The graph is rebuilt purely from the (read-only) trace `events`. We compute a
// stable node layout once from the *final* set of tools, then derive one "frame"
// per event so the scrubber can replay any step: which nodes existed, which node
// was active, which edge pulsed, and which node just entered.

type GraphNode = { id: string; kind: "agent" | "tool"; angle: number };

type Frame = {
  present: Set<string>; // node ids that exist at this step
  activeId: string | null; // node emphasised at this step
  pulseToolId: string | null; // tool whose edge pulses (a tool invocation)
  enteringId: string | null; // node that first appeared at this step
  step: number | null;
  type: TraceEvent["type"];
  label: string;
};

const R = 2.2; // tool orbit radius

function nodePos(n: GraphNode): [number, number, number] {
  if (n.kind === "agent") return [0, 0, 0];
  // -PI/2 so the first tool sits at the top, then clockwise.
  return [Math.cos(n.angle) * R, Math.sin(n.angle) * R, 0];
}

function buildTimeline(events: TraceEvent[]): { nodes: GraphNode[]; frames: Frame[] } {
  // Final tool ordering → stable angles (positions don't jump as more tools
  // appear during replay).
  const toolNames: string[] = [];
  for (const ev of events) {
    if (ev.type === "tool" && ev.node && !toolNames.includes(ev.node)) toolNames.push(ev.node);
  }
  const nodes: GraphNode[] = [{ id: "agent", kind: "agent", angle: 0 }];
  const count = Math.max(1, toolNames.length);
  toolNames.forEach((t, i) => {
    nodes.push({ id: t, kind: "tool", angle: (i / count) * Math.PI * 2 - Math.PI / 2 });
  });

  const frames: Frame[] = [];
  const present = new Set<string>(["agent"]);
  for (const ev of events) {
    let activeId: string | null = null;
    let pulseToolId: string | null = null;
    let enteringId: string | null = null;
    if (ev.type === "model" || ev.type === "answer" || ev.type === "run_started") {
      activeId = "agent";
    }
    if (ev.type === "tool" && ev.node) {
      if (!present.has(ev.node)) {
        present.add(ev.node);
        enteringId = ev.node;
      }
      activeId = ev.node;
      pulseToolId = ev.node;
    }
    frames.push({
      present: new Set(present),
      activeId,
      pulseToolId,
      enteringId,
      step: ev.step ?? null,
      type: ev.type,
      label: ev.node ?? ev.type,
    });
  }
  return { nodes, frames };
}

// ---------------------------------------------------------------------------
// Theme-aware colors (read straight from the CSS design tokens)
// ---------------------------------------------------------------------------
type Palette = {
  agent: string;
  tool: string;
  active: string;
  edge: string;
  label: string;
  panel: string;
};

const FALLBACK_PALETTE: Palette = {
  agent: "#7c93ff",
  tool: "#4ec27a",
  active: "#e2a54a",
  edge: "#313a4d",
  label: "#8b95a7",
  panel: "#12161f",
};

function readPalette(): Palette {
  if (typeof window === "undefined") return FALLBACK_PALETTE;
  const s = getComputedStyle(document.documentElement);
  const get = (v: string, fb: string) => s.getPropertyValue(v).trim() || fb;
  return {
    agent: get("--primary", FALLBACK_PALETTE.agent),
    tool: get("--ok", FALLBACK_PALETTE.tool),
    active: get("--warn", FALLBACK_PALETTE.active),
    edge: get("--line-strong", FALLBACK_PALETTE.edge),
    label: get("--muted", FALLBACK_PALETTE.label),
    panel: get("--panel", FALLBACK_PALETTE.panel),
  };
}

function usePalette(): Palette {
  const [palette, setPalette] = useState<Palette>(FALLBACK_PALETTE);
  useEffect(() => {
    const update = () => setPalette(readPalette());
    update();
    // Re-read on explicit theme switches and on system scheme changes.
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener?.("change", update);
    return () => {
      obs.disconnect();
      mq?.removeEventListener?.("change", update);
    };
  }, []);
  return palette;
}

function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    (gl as WebGLRenderingContext | null)?.getExtension("WEBGL_lose_context")?.loseContext();
    return !!gl;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// 3D scene
// ---------------------------------------------------------------------------
function NodeMesh({
  node,
  active,
  palette,
}: {
  node: GraphNode;
  active: boolean;
  palette: Palette;
}) {
  const ref = useRef<Mesh>(null);
  const ring = useRef<Mesh>(null);
  const ringMat = useRef<MeshStandardMaterial>(null);
  // Enter progress: a freshly-mounted mesh scales up from 0. Because we only
  // render *present* nodes, a node that appears mid-run mounts here → animates
  // in; scrubbing back unmounts it and forward remounts → replays the entrance.
  const appear = useRef(0);
  const pos = nodePos(node);
  const size = node.kind === "agent" ? 0.55 : 0.36;

  useFrame((state, delta) => {
    const m = ref.current;
    if (!m) return;
    if (appear.current < 1) appear.current = Math.min(1, appear.current + delta * 3.2);
    const t = state.clock.elapsedTime;
    const grow = active ? 1 + Math.sin(t * 6) * 0.12 : 1;
    m.scale.setScalar(appear.current * grow);
    if (active) m.rotation.y += delta * 0.9;

    if (ring.current && ringMat.current) {
      const rp = 1.45 + (Math.sin(t * 4) * 0.5 + 0.5) * 0.35;
      ring.current.scale.setScalar(appear.current * rp);
      ringMat.current.opacity = active ? 0.35 + (Math.sin(t * 4) * 0.5 + 0.5) * 0.3 : 0;
    }
  });

  const color = node.kind === "agent" ? palette.agent : active ? palette.active : palette.tool;

  return (
    <group position={pos}>
      {/* current-step emphasis ring */}
      <mesh ref={ring} visible={active}>
        <torusGeometry args={[size * 1.5, 0.03, 10, 40]} />
        <meshStandardMaterial
          ref={ringMat}
          color={palette.active}
          emissive={palette.active}
          emissiveIntensity={0.8}
          transparent
          opacity={0}
        />
      </mesh>
      <mesh ref={ref}>
        <icosahedronGeometry args={[size, 1]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={active ? 0.7 : 0.18}
        />
      </mesh>
    </group>
  );
}

function Edge({ to, pulsing, palette }: { to: GraphNode; pulsing: boolean; palette: Palette }) {
  const mat = useRef<MeshStandardMaterial>(null);
  const packet = useRef<Mesh>(null);
  const [x, y] = nodePos(to);
  const mid: [number, number, number] = [x / 2, y / 2, 0];
  const len = Math.hypot(x, y);
  const angle = Math.atan2(y, x);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (mat.current) {
      mat.current.emissiveIntensity = pulsing ? 0.5 + (Math.sin(t * 5) * 0.5 + 0.5) * 0.7 : 0;
    }
    if (packet.current) {
      // A glowing packet travels agent → tool while the edge is pulsing.
      const p = (t * 0.9) % 1;
      packet.current.position.set(x * p, y * p, 0);
    }
  });

  return (
    <group>
      <mesh position={mid} rotation={[0, 0, angle]}>
        <boxGeometry args={[len, 0.025, 0.025]} />
        <meshStandardMaterial
          ref={mat}
          color={pulsing ? palette.active : palette.edge}
          emissive={palette.active}
          emissiveIntensity={0}
        />
      </mesh>
      {pulsing && (
        <mesh ref={packet}>
          <sphereGeometry args={[0.09, 12, 12]} />
          <meshStandardMaterial color={palette.active} emissive={palette.active} emissiveIntensity={1.1} />
        </mesh>
      )}
    </group>
  );
}

function Scene({ frame, nodes, palette }: { frame: Frame; nodes: GraphNode[]; palette: Palette }) {
  const group = useRef<Group>(null);
  useFrame((state) => {
    if (group.current) group.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.3) * 0.25;
  });
  const visible = nodes.filter((n) => frame.present.has(n.id));
  return (
    <group ref={group}>
      <ambientLight intensity={0.7} />
      <pointLight position={[5, 5, 5]} intensity={40} />
      {visible
        .filter((n) => n.kind === "tool")
        .map((n) => (
          <Edge key={`e-${n.id}`} to={n} pulsing={frame.pulseToolId === n.id} palette={palette} />
        ))}
      {visible.map((n) => (
        <NodeMesh key={n.id} node={n} active={frame.activeId === n.id} palette={palette} />
      ))}
    </group>
  );
}

// 2D SVG fallback (also the reduced-motion / no-WebGL path). Reflects the same
// scrubbed frame as the 3D scene.
function Fallback2D({ frame, nodes, palette }: { frame: Frame; nodes: GraphNode[]; palette: Palette }) {
  const cx = 200;
  const cy = 130;
  const r = 90;
  const visible = nodes.filter((n) => frame.present.has(n.id));
  return (
    <svg viewBox="0 0 400 260" width="100%" height="260" data-testid="trace-2d-fallback">
      {visible
        .filter((n) => n.kind === "tool")
        .map((n) => {
          const pulsing = frame.pulseToolId === n.id;
          return (
            <line
              key={`l-${n.id}`}
              x1={cx}
              y1={cy}
              x2={cx + Math.cos(n.angle) * r}
              y2={cy + Math.sin(n.angle) * r}
              stroke={pulsing ? palette.active : palette.edge}
              strokeWidth={pulsing ? 3 : 2}
            />
          );
        })}
      {visible.map((n) => {
        const x = n.kind === "agent" ? cx : cx + Math.cos(n.angle) * r;
        const y = n.kind === "agent" ? cy : cy + Math.sin(n.angle) * r;
        const active = frame.activeId === n.id;
        const fill = n.kind === "agent" ? palette.agent : active ? palette.active : palette.tool;
        const rad = n.kind === "agent" ? 20 : 14;
        return (
          <g key={n.id}>
            {active && (
              <circle cx={x} cy={y} r={rad + 6} fill="none" stroke={palette.active} strokeWidth={2} opacity={0.7} />
            )}
            <circle cx={x} cy={y} r={rad} fill={fill} opacity={active ? 1 : 0.75} />
            <text
              x={x}
              y={y + (n.kind === "agent" ? 34 : 26)}
              fill={palette.label}
              fontSize="10"
              textAnchor="middle"
            >
              {n.id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Timeline scrubber
// ---------------------------------------------------------------------------
const TYPE_PILL: Record<TraceEvent["type"], string> = {
  run_started: "info",
  model: "info",
  tool: "warn",
  answer: "ok",
  limit: "bad",
  error: "bad",
  done: "ok",
};

function TimelineScrubber({
  frame,
  scrub,
  maxIndex,
  total,
  live,
  playing,
  reduced,
  onScrub,
  onTogglePlay,
}: {
  frame: Frame;
  scrub: number;
  maxIndex: number;
  total: number;
  live: boolean;
  playing: boolean;
  reduced: boolean;
  onScrub: (v: number) => void;
  onTogglePlay: () => void;
}) {
  const stepLabel = frame.step != null ? `step ${frame.step}` : `event ${scrub + 1}`;
  return (
    <div className="trace-timeline" data-testid="trace-timeline">
      <div className="tl-head">
        {!reduced && (
          <button
            type="button"
            className="icon-btn tl-play"
            onClick={onTogglePlay}
            disabled={live || total <= 1}
            aria-label={playing ? "Pause replay" : "Play replay"}
            title={playing ? "Pause replay" : "Play replay"}
          >
            {playing ? <PauseIcon /> : <PlayIcon />}
          </button>
        )}
        <span className="tl-step">{stepLabel}</span>
        <span className={`pill ${TYPE_PILL[frame.type] ?? "info"}`}>{frame.type}</span>
        <span className="tl-node">{frame.label}</span>
        {live ? (
          <span className="tl-live">LIVE</span>
        ) : (
          <span className="tl-count">
            {scrub + 1} / {total}
          </span>
        )}
      </div>
      <input
        type="range"
        className="tl-range"
        min={0}
        max={maxIndex}
        step={1}
        value={scrub}
        onChange={(e) => onScrub(Number(e.target.value))}
        aria-label="Replay run timeline"
        aria-valuetext={`${stepLabel}, ${frame.type}`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------
export default function TraceGraph3D({
  events,
  status,
}: {
  events: TraceEvent[];
  status?: string;
}) {
  const [webgl, setWebgl] = useState<boolean | null>(null);
  const [reduced, setReduced] = useState(false);
  const palette = usePalette();
  const { nodes, frames } = useMemo(() => buildTimeline(events), [events]);

  const [scrub, setScrub] = useState(0);
  const [follow, setFollow] = useState(true);
  const [playing, setPlaying] = useState(false);
  const prevLen = useRef(events.length);

  const running = status === "running";
  const maxIndex = Math.max(0, frames.length - 1);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    setReduced(reduce);
    setWebgl(hasWebGL() && !reduce);
  }, []);

  // Live-follow: track the newest event while following; reset on a new run.
  useEffect(() => {
    const len = events.length;
    if (len < prevLen.current) {
      setFollow(true);
      setPlaying(false);
      setScrub(Math.max(0, len - 1));
    } else if (len > prevLen.current && follow) {
      setScrub(len - 1);
    }
    prevLen.current = len;
  }, [events.length, follow]);

  // Replay auto-advance (idle/done only, never under reduced motion).
  useEffect(() => {
    if (!playing || reduced || running) return;
    const id = window.setInterval(() => {
      setScrub((s) => {
        if (s >= maxIndex) {
          setPlaying(false);
          return s;
        }
        return s + 1;
      });
      setFollow(false);
    }, 750);
    return () => window.clearInterval(id);
  }, [playing, reduced, running, maxIndex]);

  const onScrub = useCallback(
    (v: number) => {
      setPlaying(false);
      setScrub(v);
      setFollow(v >= maxIndex);
    },
    [maxIndex],
  );

  const onTogglePlay = useCallback(() => {
    setPlaying((p) => {
      if (p) return false;
      setFollow(false);
      setScrub((s) => (s >= maxIndex ? 0 : s));
      return true;
    });
  }, [maxIndex]);

  if (events.length === 0) {
    return (
      <p className="muted" style={{ margin: 0, padding: 14 }}>
        Run an agent to reconstruct its execution graph.
      </p>
    );
  }

  if (webgl === null) {
    return <div style={{ height: 260 }} />;
  }

  const clamped = Math.min(scrub, maxIndex);
  const frame = frames[clamped];
  const live = follow && running;

  return (
    <div>
      {webgl ? (
        <div style={{ height: 260 }} data-testid="trace-3d-canvas">
          <Canvas camera={{ position: [0, 0, 6], fov: 50 }} dpr={[1, 1.5]}>
            <Scene frame={frame} nodes={nodes} palette={palette} />
          </Canvas>
        </div>
      ) : (
        <div style={{ padding: 8 }}>
          <Fallback2D frame={frame} nodes={nodes} palette={palette} />
          <p className="muted" style={{ margin: "0 0 4px", fontSize: 11, textAlign: "center" }}>
            2D fallback (no WebGL / reduced motion)
          </p>
        </div>
      )}
      <TimelineScrubber
        frame={frame}
        scrub={clamped}
        maxIndex={maxIndex}
        total={frames.length}
        live={live}
        playing={playing}
        reduced={reduced}
        onScrub={onScrub}
        onTogglePlay={onTogglePlay}
      />
    </div>
  );
}
