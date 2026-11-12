import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Reachability probe for offline mode (`lib/offline/connectivity.ts`).
 *
 * `navigator.onLine` only says a network interface is up. On school wifi with no
 * working internet behind it, that is true while every request fails, so the app
 * decides it is offline from failed requests and polls this to learn when it is
 * back. Answers with no body and no caching, and touches nothing else.
 */
export function GET() {
  return new NextResponse(null, { status: 204, headers: { "cache-control": "no-store" } });
}
