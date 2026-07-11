import ConsoleShell from "../console-shell";

// The working console (Builder / Eval / About) now lives at /app. The marketing
// landing owns "/". ConsoleShell keeps its own "use client" boundary and every
// data-testid, so the console behaves exactly as before, only at a new route.
export default function AppRoute() {
  return <ConsoleShell />;
}
