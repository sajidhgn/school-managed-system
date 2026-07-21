import { NextRequest, NextResponse } from "next/server";

import { backendUrl } from "@/lib/api/config";
import { getAccessToken, refreshSession } from "@/lib/auth/session";

/**
 * Backend-for-frontend proxy.
 *
 * Every browser call to FastAPI goes through here. This handler attaches the
 * Bearer token from the httpOnly cookie server-side, so the token never enters
 * the browser bundle, and transparently retries once after a refresh when the
 * access token has expired mid-session.
 */

export const dynamic = "force-dynamic";

/**
 * Paths the browser may NOT reach through the proxy.
 *
 * These endpoints mint or rotate tokens. Proxying them would hand the raw
 * token pair back to client JS and defeat the httpOnly cookie design — the
 * dedicated handlers under /api/auth/* exist for exactly these flows.
 */
const BLOCKED = ["auth/login", "auth/refresh", "auth/register", "auth/login/verify-2fa"];

/** Header names that must not be forwarded upstream or back downstream. */
const STRIPPED_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "cookie",
  "authorization",
]);
const STRIPPED_RESPONSE_HEADERS = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
]);

async function proxy(request: NextRequest, segments: string[]): Promise<NextResponse> {
  const path = segments.join("/");

  if (BLOCKED.some((blocked) => path === blocked)) {
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

  const search = request.nextUrl.search;
  const target = `${backendUrl(`/${path}`)}${search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });

  // Buffer the body once so the 401 retry can replay it.
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();

  const send = async (token: string | undefined) => {
    const outbound = new Headers(headers);
    if (token) outbound.set("authorization", `Bearer ${token}`);
    return fetch(target, {
      method: request.method,
      headers: outbound,
      body: body && body.byteLength > 0 ? body : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  };

  let token = await getAccessToken();
  let upstream = await send(token);

  if (upstream.status === 401) {
    const refreshed = await refreshSession();
    if (refreshed) {
      token = refreshed.access_token;
      upstream = await send(token);
    }
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
