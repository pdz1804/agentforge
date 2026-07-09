import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "AgentForge — Agent Builder",
  description: "Author, validate, run, and replay agents on the Unified Agent Core.",
};

// Applied before first paint to set data-theme from the persisted choice,
// preventing a flash of the wrong theme (FOUC). "system" is resolved by CSS
// via prefers-color-scheme, so we only need to reflect the stored choice here.
const themeInit = `(function(){try{var t=localStorage.getItem("agentforge-theme");if(t!=="light"&&t!=="dark")t="system";document.documentElement.setAttribute("data-theme",t);}catch(e){document.documentElement.setAttribute("data-theme","system");}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable}`}
      data-theme="system"
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
