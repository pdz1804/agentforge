/** @type {import('next').NextConfig} */
// Proxy API + health to the FastAPI backend so the browser talks to a single
// origin (no CORS changes needed on the backend). Override the target with
// AGENTFORGE_API_BASE when the API runs on a different host/port.
const API_BASE = process.env.AGENTFORGE_API_BASE || "http://127.0.0.1:8077";

const nextConfig = {
  reactStrictMode: true,
  // SSE (POST /api/runs) must stream to the browser event-by-event. Next.js
  // gzip-compresses responses by default, which BUFFERS the whole event-stream
  // and delivers it only at completion. Disabling Next's compression lets the
  // trace render live (a CDN/edge proxy should own compression in production).
  compress: false,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_BASE}/api/:path*` },
      { source: "/health", destination: `${API_BASE}/health` },
    ];
  },
};

module.exports = nextConfig;
