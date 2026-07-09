"use client";

import { useEffect, useState } from "react";
import { MonitorIcon, MoonIcon, SunIcon } from "./icons";

type Mode = "system" | "light" | "dark";
const KEY = "agentforge-theme";
const ORDER: Mode[] = ["system", "light", "dark"];

const META: Record<Mode, { label: string; Icon: typeof SunIcon }> = {
  system: { label: "System", Icon: MonitorIcon },
  light: { label: "Light", Icon: SunIcon },
  dark: { label: "Dark", Icon: MoonIcon },
};

function apply(mode: Mode) {
  document.documentElement.setAttribute("data-theme", mode);
}

/**
 * Cycling theme control (system → light → dark). The concrete look for
 * "system" is resolved by CSS via prefers-color-scheme, so no matchMedia
 * subscription is needed here. The initial paint is handled by the inline
 * script in the document head; this component only reflects and updates the
 * persisted choice after hydration.
 */
export default function ThemeToggle() {
  // Deterministic first render (matches SSR) → no hydration mismatch. The real
  // stored value is read in the mount effect below.
  const [mode, setMode] = useState<Mode>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    let stored: Mode = "system";
    try {
      const v = localStorage.getItem(KEY) as Mode | null;
      if (v === "light" || v === "dark" || v === "system") stored = v;
    } catch {
      /* localStorage unavailable — fall back to system */
    }
    setMode(stored);
    apply(stored);
    setMounted(true);
  }, []);

  function cycle() {
    const next = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
    setMode(next);
    apply(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* ignore persistence failure */
    }
  }

  const { label, Icon } = META[mode];
  const nextLabel = META[ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length]].label;

  return (
    <button
      type="button"
      className="icon-btn"
      data-testid="theme-toggle"
      onClick={cycle}
      aria-label={`Theme: ${label}. Activate to switch to ${nextLabel}.`}
      title={`Theme: ${label} (click for ${nextLabel})`}
    >
      {/* key forces the rise animation on each change; suppress icon flip until
          the stored choice is known to avoid a one-frame swap. */}
      <span className="ico-swap" key={mounted ? mode : "init"} aria-hidden="true">
        <Icon />
      </span>
    </button>
  );
}
