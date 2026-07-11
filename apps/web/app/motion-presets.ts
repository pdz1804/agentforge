// Shared motion presets for the console. MOTIVATED-only motion with console
// restraint: short durations, one easing, and every helper degrades to a
// no-op object when the user prefers reduced motion (callers pass the
// `useReducedMotion()` result). motion.* forwards data-*/aria-*/className, so
// wrappers are applied in place and never change the DOM/testid contract.

import type { Variants } from "motion/react";

// Signature easing shared across the app (same curve as the CSS --ease token).
export const EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

// Scroll-reveal (About marketing surface). Parent orchestrates a gentle
// stagger; children rise into place. once:true — reveal only the first time.
export const revealContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.02 } },
};

export const revealItem: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE } },
};

// About hero — a single confident entrance (above the fold, so not gated on
// scroll).
export function heroProps(reduce: boolean) {
  if (reduce) return {};
  return {
    initial: { opacity: 0, y: 18 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.55, ease: EASE },
  } as const;
}

// Tab content entrance — a quiet fade/slide when a panel mounts.
export function tabEntranceProps(reduce: boolean) {
  if (reduce) return {};
  return {
    initial: { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.3, ease: EASE },
  } as const;
}

// Streaming rows / answer / report blocks — each element animates in once as
// it mounts (trace events arrive over SSE, so this reads as a natural stagger).
export function streamItemProps(reduce: boolean) {
  if (reduce) return {};
  return {
    initial: { opacity: 0, y: 6 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.28, ease: EASE },
  } as const;
}

// Work-surface card polish — a subtle hover lift + tap press. `tap` is dropped
// for cards that own a primary interaction (the YAML editor, the scrollable
// trace, the 3D canvas + scrubber) so a whole-card press never fights typing,
// scrolling, or dragging. The tinted lift shadow is handled by CSS :hover.
export function cardHoverProps(reduce: boolean, tap = true) {
  if (reduce) return {};
  return {
    whileHover: { y: -3 },
    ...(tap ? { whileTap: { scale: 0.98 } } : {}),
    transition: { duration: 0.18, ease: EASE },
  } as const;
}
