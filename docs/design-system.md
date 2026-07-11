# AgentForge Web Console — Design System

Reference for the AgentForge web console (`apps/web`). Single source of truth is
`app/globals.css` (token-driven) plus `app/motion-presets.ts` (motion). This doc
mirrors the code — when they disagree, the code wins.

## Direction — "instrument panel"

A dense, calm developer **console**, not a marketing site. The surface reads like
an instrument panel: deep neutral canvas, systematic elevation, one disciplined
indigo accent, and color used as *signal* (ok / warn / bad status) rather than
decoration. Motion is MOTIVATED-only — it clarifies state changes (a run
streaming in, a tab mounting) and never performs. The one richer surface is the
**About** tab, the app's single marketing moment.

Default theme is **OLED-dark**; a professional **light** theme mirrors the same
language. Theme choice (`system | light | dark`) lives on `<html data-theme>` and
`localStorage["agentforge-theme"]`, applied pre-paint by an inline script to avoid
FOUC. `system` resolves via `prefers-color-scheme`.

## Typography

Two families, loaded via `next/font/google` as CSS variables:

| Role | Family | Variable | Usage |
|------|--------|----------|-------|
| Sans (UI) | **Inter** | `--font-inter` → `--font-sans` | Body, labels, headings, buttons |
| Mono (data) | **JetBrains Mono** | `--font-mono` → `--mono` | Trace, YAML editor, IDs, costs, metrics, timeline |

- Body base: `--text-md` (14px) / line-height 1.55, antialiased, `optimizeLegibility`.
- **`font-variant-numeric: tabular-nums`** on every numeric/data run (backend meta,
  costs, run IDs, token usage, eval metrics, task scores, timeline step counts) so
  digits align in columns and don't jitter as they update.
- Uppercase micro-labels use `letter-spacing` 0.02–0.09em; the mono editor uses
  `tab-size: 2`, `white-space: pre`, line-height 1.7.

### Type scale (discrete ramp)

| Token | px | Typical use |
|-------|----|-------------|
| `--text-2xs` | 10 | metric labels, trace type-pills |
| `--text-xs` | 11 | labels, pills, meta chips |
| `--text-sm` | 12 | secondary body, mono data |
| `--text-base` | 13 | inputs, buttons, card body |
| `--text-md` | 14 | body base, card titles content |
| `--text-lg` | 15 | brand h1, About lede |
| `--text-2xl` | 20 | eval metric values |
| `--text-display` | clamp(26px, 4vw, 38px) | About hero heading (only large display) |

## Color tokens

Color is semantic: surfaces (elevation), ink (text), lines (borders), one brand
accent, and three status hues. All pairs verified WCAG AA on their backgrounds.

### Dark (default `:root`)

| Token | Hex / value | Role |
|-------|-------------|------|
| `--bg` | `#0b0e14` | app canvas |
| `--panel` | `#12161f` | elevation 1 — cards |
| `--panel-2` | `#171c28` | elevation 2 — inputs, inner rows |
| `--panel-3` | `#1c2233` | elevation 3 — hover / active fills |
| `--ink` | `#e9edf5` | primary text |
| `--ink-soft` | `#c4ccdb` | secondary text |
| `--muted` | `#8b95a7` | tertiary / labels |
| `--faint` | `#5c6577` | disabled / placeholder |
| `--line` | `#232a38` | default border |
| `--line-soft` | `#1b2130` | subtle divider |
| `--line-strong` | `#313a4d` | emphasized border |
| `--primary` | `#818cf8` | indigo-400 accent (text/fill) |
| `--primary-strong` | `#6f74f2` | hover fill |
| `--primary-ink` | `#0a0d18` | text on primary fill |
| `--primary-soft` | `rgba(129,140,248,.14)` | tinted accent bg |
| `--primary-glow` | `rgba(129,140,248,.35)` | glow / lift tint |
| `--ok` | `#4ec27a` | success (+ `--ok-soft` .13, `--ok-line` .32) |
| `--warn` | `#e2a54a` | warning (+ `--warn-soft` .13, `--warn-line` .32) |
| `--bad` | `#f2696a` | error (+ `--bad-soft` .13, `--bad-line` .34) |

### Light (`[data-theme="light"]`, and `system` + OS light)

| Token | Hex / value | Role |
|-------|-------------|------|
| `--bg` | `#f5f7fb` | app canvas (cool off-white) |
| `--panel` | `#ffffff` | elevation 1 — cards |
| `--panel-2` | `#f2f4f9` | elevation 2 — inputs |
| `--panel-3` | `#e7ebf3` | elevation 3 — hover / active |
| `--ink` | `#171c26` | primary text (~14:1) |
| `--ink-soft` | `#3d4658` | secondary (~9:1) |
| `--muted` | `#5b647a` | tertiary (~5.6:1, AA) |
| `--faint` | `#97a0b3` | placeholder / disabled |
| `--line` | `#e3e7ef` | default border |
| `--line-soft` | `#eef1f7` | subtle divider |
| `--line-strong` | `#ccd3e0` | emphasized border |
| `--primary` | `#4f46e5` | indigo-600 (white text ~6.6:1) |
| `--primary-strong` | `#4338ca` | indigo-700 hover |
| `--primary-ink` | `#ffffff` | text on primary fill |
| `--primary-soft` | `rgba(79,70,229,.10)` | tinted accent bg |
| `--primary-glow` | `rgba(79,70,229,.28)` | glow / lift tint |
| `--ok` | `#148a4e` | success (~4.9:1) |
| `--warn` | `#b06a12` | warning (~4.7:1) |
| `--bad` | `#d13438` | error (~4.8:1) |

**Status semantics:** pills, trace event left-borders, and the regression banner
map `ok → done/pass/no-regression`, `warn → running/stopped/live-cost`,
`bad → error/limit/fail/regression`. Text is always the primary signal; color
reinforces. Trace event left-border colors: `model → --primary`, `tool → --warn`,
`answer → --ok`, `error/limit → --bad`, `run_started/done → --line-strong`.

## Spacing scale (4px grid)

| Token | px |
|-------|----|
| `--space-1` | 4 |
| `--space-2` | 8 |
| `--space-3` | 12 |
| `--space-4` | 16 |
| `--space-5` | 20 |
| `--space-6` | 24 |
| `--space-8` | 32 |

Card body padding 15px; card header 11px/15px. Page gutters 22px desktop → 14px
mobile. Content max-width 1500px (console), 1040px (About).

## Radius

| Token | px | Use |
|-------|----|-----|
| `--r-sm` | 7 | inputs, buttons, small chips |
| `--r-md` | 10 | answer / error blocks, feature tiles, eval splits |
| `--r-lg` | 12 | cards, hero |
| `--r-pill` | 999 | pills, status chip, toggle |

## Elevation / shadow

| Token | Value (dark) | Use |
|-------|--------------|-----|
| `--shadow-1` | `0 1px 2px rgba(0,0,0,.4)` | resting cards |
| `--shadow-2` | `0 4px 16px -4px rgba(0,0,0,.5)` | raised panels |
| `--shadow-glow` | ring + `rgba(primary-glow)` | primary button hover |
| `--shadow-lift` | `0 10px 26px -12px var(--primary-glow), 0 3px 10px -4px rgba(0,0,0,.5)` | **card :hover lift (new)** |

Light theme re-tunes each shadow for its brighter canvas (softer, indigo-tinted
`--shadow-lift`). `--shadow-lift` pairs with the motion translateY on hover: CSS
carries the tinted shadow + border, motion carries the transform.

## Z-index tokens

| Token | Value | Layer |
|-------|-------|-------|
| `--z-sticky` | 1 | sticky table header inside a scroll area (eval tasks) |
| `--z-tabbar` | 19 | sticky tab bar |
| `--z-topbar` | 20 | sticky top bar |

The tab bar sticks at `top: var(--topbar-h)` (55px) directly beneath the topbar —
both read one token so a change can't cause overlap. On ≤768px the topbar sheds
its sub-label + backend meta to stay a single `--topbar-h` row (see Responsive).

## Motion (new)

Library: **`motion`** (`motion/react`). Presets in `app/motion-presets.ts`.
Dials: variance 5 / motion 4 / density 4 — MOTIVATED-only with console restraint.

- **Easing:** `EASE = [0.16, 1, 0.3, 1]` (matches CSS `--ease`). One curve everywhere.
- **Durations:** tab entrance 0.30s · stream/report rows 0.28s · hover/tap 0.18s ·
  scroll-reveal items 0.50s · About hero 0.55s.
- **Stagger:** scroll-reveal container `staggerChildren: 0.06`, `delayChildren: 0.02`.

### Where motion is applied

| Surface | Motion | File |
|---------|--------|------|
| Tab content (Builder `.layout`, Eval `.eval`) | fade + y 8→0, 0.30s on mount | `page.tsx`, `eval-panel.tsx` |
| About hero | fade + y 18→0, 0.55s entrance | `AboutPanel.tsx` |
| About pillars / feature grid / steps | `whileInView` staggered reveal, `once:true`, `amount:0.25`, y 16→0 | `AboutPanel.tsx` |
| Cards (all Builder cards, Eval split cards, About feature tiles) | hover lift `y:-3` (+ tinted `--shadow-lift` via CSS); tap `scale:.98` | all panels |
| Trace `.event` rows + `.answer` | each fades + y 6→0 as it mounts (natural SSE stagger) | `page.tsx` |
| Eval report | regression banner fade-in; split cards staggered reveal | `eval-panel.tsx` |

**Tap-scale is intentionally omitted** on the cards that own a primary
interaction — the YAML editor (manifest), the scrollable trace, and the 3D
canvas + scrubber — so a whole-card press never fights typing, scrolling, or
dragging. Those cards still get the hover lift. The R3F `<Canvas>` and the
timeline scrubber are never wrapped in remounting motion; the 3D graph keeps its
own animation.

### Legacy CSS animations (kept)

`spin` (spinners), `pulse` (live dots), `rise` (validity line, theme-toggle icon
swap). The streaming `.event` / `.answer` `rise` keyframes were replaced by the
motion equivalents above to avoid double-animating.

### Reduced motion (mandatory)

Two layers, both honored:
1. **JS** — every preset takes the `useReducedMotion()` result and returns a
   no-op (`{}`) / static variants, so no motion props are attached.
2. **CSS** — the global `@media (prefers-reduced-motion: reduce)` block collapses
   all animation/transition durations to ~0, so hover shadow/border snap instead
   of easing.

## Component notes

- **Cards** — `.card` (panel, `--line`, `--r-lg`, `--shadow-1`); header `.card > h2`
  is an uppercase mono-spaced micro-label bar; `.body` 15px pad, `.body.flush` for
  self-padding lists (history, 3D graph).
- **Buttons** — filled primary (glow on hover); `.secondary` (panel-2 outline);
  `.danger` (transparent, `--bad` outline). ≥40px min-height on mobile.
- **Pills** — status chips with a leading dot; `.ok/.bad/.warn/.info` variants.
- **Trace** — mono list, colored left-border per event type, scrolls at 460px
  (60vh on mobile).
- **Eval** — dev vs held-out split cards (stack ≤720px); metric grid with
  tabular-nums; sticky task-table header.
- **About** — hero + pillars (3-col) + feature grid (3→2→1 col) + numbered steps.

## Responsive

Mobile-first hardening; no horizontal overflow at 360px. Full-height uses
`min-height: 100dvh` (with `100vh` fallback).

| Breakpoint | Behavior |
|------------|----------|
| ≤960px | Builder `.layout` 1fr 1fr → single column (editor above output) |
| ≤820px | About pillars → 1 col; feature grid → 2 col |
| ≤768px | Topbar sheds sub-label + meta (stays single `--topbar-h` row); tap targets ≥40px (buttons/inputs 40, tabs 44, icon-btn 40); trace `max-height:60vh`; graph box 220px |
| ≤720px | Eval split cards stack |
| ≤640px | About feature grid → 1 col |
| ≤560px | Tabbar / About gutters → 14px |

`min-width: 0` on grid/flex columns prevents long unbreakable content (history
rows, trace URLs) from blowing out the tracks; long text ellipsizes or wraps
within its track. The YAML `<textarea>` scrolls its own long lines rather than
overflowing the page.

## Accessibility

- Focus-visible: 2px `--primary` outline, 2px offset (inset on tabs).
- Tablist: roving focus (Arrow/Home/End), `role=tab`/`tabpanel`, `aria-selected`,
  `aria-controls`; hidden panels use the `hidden` attribute.
- Color contrast verified AA on both themes; status is text-first, color-second.
- All motion degrades to static under `prefers-reduced-motion`.
