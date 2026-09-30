import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Cursor preview tunnel reaches the dev server from a different origin;
  // without this Next 16 blocks the HMR websocket and the preview hangs.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
