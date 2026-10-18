import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The demo is reached through a cloudflared quick tunnel whose hostname
  // changes every run — allow any *.trycloudflare.com origin instead of
  // committing an ephemeral hostname. Without this Next 16 blocks the HMR
  // websocket and the tunnel preview hangs. (Matches hostname only.)
  allowedDevOrigins: ["127.0.0.1", "localhost", "*.trycloudflare.com"],
  // Dev-only same-origin proxy: with NEXT_PUBLIC_API_URL="" (see
  // .env.example) the browser calls /api/* on the frontend origin and the
  // dev server forwards it to the local backend, so one public URL serves
  // the whole demo (no second tunnel, no CORS). Production deploys set
  // NEXT_PUBLIC_API_URL to the backend URL, so no rewrite is emitted there.
  async rewrites() {
    if (process.env.NODE_ENV !== "development") {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:43124/api/:path*",
      },
    ];
  },
};

export default nextConfig;
