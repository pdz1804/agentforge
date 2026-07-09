// Presentational inline SVG icons. All are decorative by default (aria-hidden);
// pass a title/aria-label from the caller when an icon stands alone as a control.
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function base(props: IconProps) {
  return {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    ...props,
  };
}

// Brand mark: an anvil-inspired hexagon spark for "AgentForge".
export function LogoMark(props: IconProps) {
  return (
    <svg {...base({ viewBox: "0 0 24 24", strokeWidth: 1.75, ...props })}>
      <path d="M12 2 20.5 7v10L12 22 3.5 17V7Z" />
      <path d="M12 7v10" />
      <path d="m8.5 9 3.5 2 3.5-2" />
    </svg>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m20 6-11 11-5-5" />
    </svg>
  );
}

export function PlayIcon(props: IconProps) {
  return (
    <svg {...base({ fill: "currentColor", stroke: "none", ...props })}>
      <path d="M8 5.14v13.72a1 1 0 0 0 1.54.84l10.29-6.86a1 1 0 0 0 0-1.68L9.54 4.3A1 1 0 0 0 8 5.14Z" />
    </svg>
  );
}

export function StopIcon(props: IconProps) {
  return (
    <svg {...base({ fill: "currentColor", stroke: "none", ...props })}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

export function SpinnerIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}

export function HistoryIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 3v5h5" />
      <path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

export function GraphIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="2.4" />
      <circle cx="5" cy="6" r="1.8" />
      <circle cx="19" cy="6" r="1.8" />
      <circle cx="6" cy="19" r="1.8" />
      <path d="m10.3 10.5-3.7-3M13.8 10.6l3.5-3M10.6 13.4l-3.2 4" />
    </svg>
  );
}

export function TraceIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 6h16M4 12h16M4 18h10" />
    </svg>
  );
}

export function DocIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

export function OutputIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 4h16v14H4z" />
      <path d="m8 9 3 3-3 3M13 15h4" />
    </svg>
  );
}

// Tool-call marker (replaces the ⚙ emoji in the trace).
export function ToolIcon(props: IconProps) {
  return (
    <svg {...base({ strokeWidth: 1.75, ...props })}>
      <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2-2Z" />
    </svg>
  );
}
