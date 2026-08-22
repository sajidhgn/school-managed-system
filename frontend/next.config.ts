import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // The backend is reached server-side only (see src/app/api/bff). Nothing here
  // should expose API_BASE_URL to the browser bundle.
  // Route literals are type-checked against the actual app/ tree, so a typo'd
  // `href` is a build error rather than a 404 someone finds in production.
  typedRoutes: true,
};

export default nextConfig;
