import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The demo is reached through a cloudflared quick tunnel whose hostname
  // changes every run — allow any *.trycloudflare.com origin instead of
  // committing an ephemeral hostname. Without this Next 16 blocks the HMR
  // websocket and the tunnel preview hangs. (Matches hostname only.)
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
    "*.trycloudflare.com",
    "hardening-thinly-deferred.ngrok-free.dev",
  ],
  // Same-origin proxy: the browser calls /api/* on the frontend origin and
  // Next forwards it to the backend, so one public URL serves the whole
  // demo (no second tunnel, no CORS). Enabled in dev, and in production when
  // BACKEND_ORIGIN is set (the hosted demo); Vercel-style deploys leave
  // BACKEND_ORIGIN unset and point NEXT_PUBLIC_API_URL at the backend instead.
  async rewrites() {
    if (
      process.env.NODE_ENV !== "development" &&
      !process.env.BACKEND_ORIGIN
    ) {
      return [];
    }
    const backend = process.env.BACKEND_ORIGIN ?? "http://localhost:43124";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
