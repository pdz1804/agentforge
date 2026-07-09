"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import type { TraceEvent } from "@/lib/api";
import type { Group, Mesh } from "three";

// Derive a small graph from the trace: one central "agent" node plus a node per
// distinct tool that was invoked. `activeIdx` marks the node touched most
// recently so it can pulse.
type GraphNode = { id: string; kind: "agent" | "tool"; angle: number };

function buildGraph(events: TraceEvent[]): { nodes: GraphNode[]; activeId: string | null } {
  const toolNames: string[] = [];
  let activeId: string | null = null;
  for (const ev of events) {
    if (ev.type === "model" || ev.type === "answer") activeId = "agent";
    if (ev.type === "tool" && ev.node) {
      if (!toolNames.includes(ev.node)) toolNames.push(ev.node);
      activeId = ev.node;
    }
  }
  const nodes: GraphNode[] = [{ id: "agent", kind: "agent", angle: 0 }];
  toolNames.forEach((t, i) => {
    nodes.push({ id: t, kind: "tool", angle: (i / Math.max(1, toolNames.length)) * Math.PI * 2 });
  });
  return { nodes, activeId };
}

function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    // Release the probe context so it doesn't count against the browser's limit.
    (gl as WebGLRenderingContext | null)?.getExtension("WEBGL_lose_context")?.loseContext();
    return !!gl;
  } catch {
    return false;
  }
}

function NodeMesh({ node, active }: { node: GraphNode; active: boolean }) {
  const ref = useRef<Mesh>(null);
  const R = 2.2;
  const pos: [number, number, number] =
    node.kind === "agent" ? [0, 0, 0] : [Math.cos(node.angle) * R, Math.sin(node.angle) * R, 0];
  useFrame((state) => {
    if (!ref.current) return;
    const t = state.clock.elapsedTime;
    const pulse = active ? 1 + Math.sin(t * 6) * 0.12 : 1;
    ref.current.scale.setScalar(pulse);
  });
  const color = node.kind === "agent" ? "#6b8afd" : active ? "#d29922" : "#3fb950";
  const size = node.kind === "agent" ? 0.55 : 0.36;
  return (
    <mesh ref={ref} position={pos}>
      <icosahedronGeometry args={[size, 1]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={active ? 0.6 : 0.18} />
    </mesh>
  );
}

function Edge({ to }: { to: GraphNode }) {
  const R = 2.2;
  const x = Math.cos(to.angle) * R;
  const y = Math.sin(to.angle) * R;
  const mid: [number, number, number] = [x / 2, y / 2, 0];
  const len = Math.hypot(x, y);
  const angle = Math.atan2(y, x);
  return (
    <mesh position={mid} rotation={[0, 0, angle]}>
      <boxGeometry args={[len, 0.02, 0.02]} />
      <meshStandardMaterial color="#283040" />
    </mesh>
  );
}

function Scene({ nodes, activeId }: { nodes: GraphNode[]; activeId: string | null }) {
  const group = useRef<Group>(null);
  useFrame((state) => {
    if (group.current) group.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.3) * 0.35;
  });
  return (
    <group ref={group}>
      <ambientLight intensity={0.7} />
      <pointLight position={[5, 5, 5]} intensity={40} />
      {nodes
        .filter((n) => n.kind === "tool")
        .map((n) => (
          <Edge key={`e-${n.id}`} to={n} />
        ))}
      {nodes.map((n) => (
        <NodeMesh key={n.id} node={n} active={activeId === n.id} />
      ))}
    </group>
  );
}

// 2D SVG fallback (also the reduced-motion / no-WebGL path per PRD).
function Fallback2D({ nodes, activeId }: { nodes: GraphNode[]; activeId: string | null }) {
  const cx = 200;
  const cy = 130;
  const R = 90;
  return (
    <svg viewBox="0 0 400 260" width="100%" height="260" data-testid="trace-2d-fallback">
      {nodes
        .filter((n) => n.kind === "tool")
        .map((n) => (
          <line
            key={`l-${n.id}`}
            x1={cx}
            y1={cy}
            x2={cx + Math.cos(n.angle) * R}
            y2={cy + Math.sin(n.angle) * R}
            stroke="#283040"
            strokeWidth={2}
          />
        ))}
      {nodes.map((n) => {
        const x = n.kind === "agent" ? cx : cx + Math.cos(n.angle) * R;
        const y = n.kind === "agent" ? cy : cy + Math.sin(n.angle) * R;
        const active = activeId === n.id;
        const fill = n.kind === "agent" ? "#6b8afd" : active ? "#d29922" : "#3fb950";
        return (
          <g key={n.id}>
            <circle cx={x} cy={y} r={n.kind === "agent" ? 20 : 14} fill={fill} opacity={active ? 1 : 0.75} />
            <text x={x} y={y + (n.kind === "agent" ? 34 : 26)} fill="#9aa7b8" fontSize="10" textAnchor="middle">
              {n.id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function TraceGraph3D({ events }: { events: TraceEvent[] }) {
  const [webgl, setWebgl] = useState<boolean | null>(null);
  const { nodes, activeId } = useMemo(() => buildGraph(events), [events]);

  useEffect(() => {
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    setWebgl(hasWebGL() && !reduced);
  }, []);

  // Show the graph once any run activity exists — even a tool-less run has the
  // central agent node worth rendering.
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

  if (!webgl) {
    return (
      <div style={{ padding: 8 }}>
        <Fallback2D nodes={nodes} activeId={activeId} />
        <p className="muted" style={{ margin: "0 0 4px", fontSize: 11, textAlign: "center" }}>
          2D fallback (no WebGL / reduced motion)
        </p>
      </div>
    );
  }

  return (
    <div style={{ height: 260 }} data-testid="trace-3d-canvas">
      <Canvas camera={{ position: [0, 0, 6], fov: 50 }} dpr={[1, 1.5]}>
        <Scene nodes={nodes} activeId={activeId} />
      </Canvas>
    </div>
  );
}
