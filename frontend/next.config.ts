import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Emits .next/standalone with only the traced runtime deps, so the Docker
  // image ships ~150 MB instead of the full node_modules tree.
  output: "standalone",
};

export default nextConfig;
