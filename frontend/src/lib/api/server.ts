import "server-only";

import { fetchWithSession, type SessionKind } from "@/lib/auth/session";

/**
 * Typed reads for Server Components.
 *
 * =============================================================================
 * WHY SERVER COMPONENTS DO NOT GO THROUGH THE BFF
 * =============================================================================
 *   The BFF proxy exists so the BROWSER can reach the API without holding a token.
 *   A Server Component is already on the server and already has the session — routing
 *   its request out to `/api/bff/*` and back would be a pointless HTTP round trip
 *   through the app's own process.
 *
 *   So: server components call the backend directly through `fetchWithSession`
 *   (which attaches the token and retries once after a refresh), and client
 *   components call the BFF. Same session, two entry points, no duplication of the
 *   refresh logic.
 *
 * Spec §9: "Server Components for reads, Server Actions or route handlers for
 * writes." This is the read half.
 */

/**
 * Fetch and parse, or return `fallback` on any failure.
 *
 * A page that renders with an empty section beats a page that 500s: an admin panel
 * where one slow or failing endpoint takes down the whole dashboard is far worse
 * than one where a card says it has nothing to show. Genuine auth failures are
 * handled earlier, by `requireUser()`, so a failure here is a server or network
 * problem rather than a permissions one.
 */
export async function serverGet<T>(
  path: string,
  fallback: T,
  kind: SessionKind = "tenant",
): Promise<T> {
  try {
    const response = await fetchWithSession(path, { method: "GET" }, kind);
    if (!response || !response.ok) return fallback;
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

/**
 * Fetch and parse, distinguishing "not found / not permitted" from "worked".
 *
 * For detail pages that must render a 404 rather than an empty shell — a school id
 * that does not exist should not show a blank form the user could type into.
 */
export async function serverGetOrNull<T>(
  path: string,
  kind: SessionKind = "tenant",
): Promise<T | null> {
  const response = await fetchWithSession(path, { method: "GET" }, kind);
  if (!response || !response.ok) return null;
  return (await response.json()) as T;
}

/** Required protected data: fail closed so mutation controls never render on fakes. */
export async function serverGetRequired<T>(
  path: string,
  kind: SessionKind = "tenant",
): Promise<T> {
  const response = await fetchWithSession(path, { method: "GET" }, kind);
  if (!response || !response.ok) {
    throw new Error(`Required API read failed (${response?.status ?? "no response"}): ${path}`);
  }
  return (await response.json()) as T;
}
