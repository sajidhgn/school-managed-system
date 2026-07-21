import "server-only";

/**
 * Server-only backend configuration.
 *
 * Importing this from a client component is a build error (`server-only`),
 * which is the point: the browser must never learn the FastAPI origin, and
 * never holds a token. All browser traffic goes through /api/bff/*.
 */

function required(name: string, fallback?: string): string {
  const value = process.env[name] ?? fallback;
  if (!value) {
    throw new Error(
      `Missing required environment variable ${name}. Copy .env.example to .env.local.`,
    );
  }
  return value;
}

export const API_BASE_URL = required("API_BASE_URL", "http://localhost:8000").replace(
  /\/+$/,
  "",
);

export const API_V1_PREFIX = (process.env.API_V1_PREFIX ?? "/api/v1").replace(/\/+$/, "");

export const COOKIE_SECURE = process.env.COOKIE_SECURE === "true";

/** Build an absolute backend URL for a versioned path, e.g. `/students`. */
export function backendUrl(path: string): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${API_V1_PREFIX}${suffix}`;
}
