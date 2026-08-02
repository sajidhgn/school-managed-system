import { NextRequest, NextResponse } from "next/server";

import { fetchWithSession, type SessionKind } from "@/lib/auth/session";

/**
 * Backend-for-frontend proxy.
 *
 * Every browser call to FastAPI goes through here. The handler attaches the Bearer
 * token from the httpOnly cookie server-side, so the token never enters the browser
 * bundle, and transparently retries once after a refresh when the access token has
 * expired mid-session.
 *
 * =============================================================================
 * WHY THE SESSION KIND IS DERIVED FROM THE PATH
 * =============================================================================
 *   A request to `platform/*` uses the platform operator's session; everything else
 *   uses the tenant session. Deriving it from the path rather than accepting it as
 *   a parameter means the browser cannot ask for the platform token to be attached
 *   to a tenant call, or vice versa.
 *
 *   That matters because the two sessions can legitimately coexist — an operator
 *   debugging a customer issue is often signed into both — and "which token do I
 *   send?" must not be a decision client JS gets to influence.
 */

export const dynamic = "force-dynamic";

/**
 * Paths the browser may NOT reach through the proxy.
 *
 * These endpoints mint or rotate tokens. Proxying them would hand the raw token
 * pair back to client JS and defeat the httpOnly design entirely — the dedicated
 * handlers under `/api/auth/*` exist for exactly these flows, and they keep the
 * tokens server-side.
 */
const BLOCKED = new Set([
  "auth/login",
  "auth/refresh",
  "auth/register",
  "auth/context",
  "platform/auth/login",
  "invitations/accept",
]);

/** Header names that must not be forwarded upstream or back downstream. */
const STRIPPED_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "cookie",
  "authorization",
  // A client could otherwise ask the backend to echo tokens back through the proxy.
  "x-token-transport",
  "x-refresh-token",
]);
const STRIPPED_RESPONSE_HEADERS = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
  // Belt and braces: nothing upstream should be emitting these on a proxied route,
  // but if it ever did, they must not reach the browser.
  "x-access-token",
  "x-refresh-token",
  "set-cookie",
]);

function sessionKindFor(path: string): SessionKind {
  return path === "platform" || path.startsWith("platform/") ? "platform" : "tenant";
}

async function proxy(request: NextRequest, segments: string[]): Promise<NextResponse> {
  const path = segments.join("/");

  if (BLOCKED.has(path)) {
    return NextResponse.json(
      {
        status: 403,
        title: "Forbidden",
        code: "PROXY_BLOCKED",
        detail: "This endpoint is not reachable through the proxy.",
      },
      { status: 403 },
    );
  }

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });

  // Read as TEXT, and buffered rather than streamed.
  //
  //   BUFFERED, because the 401 retry inside `fetchWithSession` replays the request.
  //   A stream can only be consumed once, so a refresh-and-retry would send an empty
  //   body — and the user would see a spurious validation error immediately after
  //   their token happened to expire.
  //
  //   TEXT, because Next.js instruments `fetch` and binary body types (ArrayBuffer,
  //   Uint8Array) do not survive that wrapper intact — the request arrives with the
  //   right headers and no body, which FastAPI reports as "not a valid dictionary".
  //   A string round-trips reliably.
  //
  // Every payload on this API is JSON. File uploads would need a streaming path,
  // and the retry would have to be rethought alongside it.
  const raw =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.text();

  const upstream = await fetchWithSession(
    `/${path}${request.nextUrl.search}`,
    {
      method: request.method,
      headers,
      body: raw && raw.length > 0 ? raw : undefined,
      redirect: "manual",
    },
    sessionKindFor(path),
  );

  if (!upstream) {
    // No session at all, or the refresh token is dead. A 401 lets the client-side
    // query layer redirect to login rather than rendering an empty page that looks
    // like the user simply has no data.
    return NextResponse.json(
      {
        status: 401,
        title: "Unauthenticated",
        code: "SESSION_EXPIRED",
        detail: "Your session has expired. Please sign in again.",
      },
      { status: 401 },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIPPED_RESPONSE_HEADERS.has(key.toLowerCase())) responseHeaders.set(key, value);
  });

  // 204 and 304 must not carry a body.
  if (upstream.status === 204 || upstream.status === 304) {
    return new NextResponse(null, { status: upstream.status, headers: responseHeaders });
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, { params }: Ctx) {
  return proxy(request, (await params).path);
}
export async function POST(request: NextRequest, { params }: Ctx) {
  return proxy(request, (await params).path);
}
export async function PATCH(request: NextRequest, { params }: Ctx) {
  return proxy(request, (await params).path);
}
export async function PUT(request: NextRequest, { params }: Ctx) {
  return proxy(request, (await params).path);
}
export async function DELETE(request: NextRequest, { params }: Ctx) {
  return proxy(request, (await params).path);
}
