import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The backend is reached server-side only (see src/app/api/bff). Nothing here
  // should expose API_BASE_URL to the browser bundle.
  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
