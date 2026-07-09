/** @type {import('next').NextConfig} */
// Proxy API + health to the FastAPI backend so the browser talks to a single
// origin (no CORS changes needed on the backend). Override the target with
// AGENTFORGE_API_BASE when the API runs on a different host/port.
const API_BASE = process.env.AGENTFORGE_API_BASE || "http://127.0.0.1:8077";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_BASE}/api/:path*` },
      { source: "/health", destination: `${API_BASE}/health` },
    ];
  },
};

module.exports = nextConfig;
