import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Pin the tracing root to this folder. Otherwise Next guesses it from the nearest
  // stray lockfile above the repo, and `.next/standalone/server.js` lands under a
  // copy of that path, which the systemd unit and Dockerfile cannot predict.
  outputFileTracingRoot: __dirname,
  // The backend is reached server-side only (see src/app/api/bff). Nothing here
  // should expose API_BASE_URL to the browser bundle.
  // Route literals are type-checked against the actual app/ tree, so a typo'd
  // `href` is a build error rather than a 404 someone finds in production.
  typedRoutes: true,
  // SITE_NOINDEX=true (staging, pre-launch): tag every response, route handlers'
  // PDFs and images included, so nothing from this deployment is indexed. Read at
  // build time; src/lib/site.ts covers the page metadata and the sitemap.
  async headers() {
    if (process.env.SITE_NOINDEX !== "true") return [];
    return [{ source: "/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }];
  },
};

export default nextConfig;
