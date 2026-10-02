import { NextRequest, NextResponse } from "next/server";

/**
 * Edge routing gate for the three route groups (spec §9).
 *
 * =============================================================================
 * THIS IS A REDIRECT, NOT AN AUTHORIZATION CHECK
 * =============================================================================
 *   Middleware runs on the edge with no database and no ability to verify a
 *   signature — it can only see WHETHER a cookie exists, not whether it is valid,
 *   whose it is, or what it permits.
 *
 *   So its job is UX: send a signed-out visitor to login instead of rendering an
 *   app shell that will fail every request. Real enforcement is the backend's
 *   `require(...)` dependency, and server components re-verify through
 *   `requireUser()` / `requirePlatformAdmin()`, which do validate the token.
 *
 *   Treating this file as the security boundary would be a mistake: forging a
 *   cookie with the right NAME is trivial, and it would get you past middleware —
 *   and precisely nowhere else.
 *
 * =============================================================================
 * WHY THE TWO SURFACES USE DIFFERENT COOKIES
 * =============================================================================
 *   Spec §9 requires the platform group to be unreachable with a tenant token and
 *   vice versa. Separate cookie names make that structural: the platform group
 *   checks for a platform cookie and would not accept a tenant one even if someone
 *   pasted it in, because the BFF attaches tokens by path and the backend checks
 *   the `typ` claim as the real gate.
 */

const ACCESS_COOKIE = "educloud_access";
const REFRESH_COOKIE = "educloud_refresh";
const PLATFORM_ACCESS_COOKIE = "educloud_platform_access";
const PLATFORM_REFRESH_COOKIE = "educloud_platform_refresh";

/** Marketing + auth surfaces: reachable with no session at all. */
const PUBLIC_PREFIXES = [
  "/pricing",
  "/login",
  "/signup",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
  "/invite",
  "/admissions",
  "/legal",
];

/** Signed-in users should not sit on these; bounce them into the app. */
const AUTH_ONLY_PAGES = ["/login", "/signup"];

/**
 * Continue, telling the server components which path they are rendering.
 *
 * A Server Component cannot read its own URL, and `requireUser()` needs it: when a
 * session turns out to be dead it sends the user through `/api/auth/recover`, which
 * has to know where to put them back afterwards. Middleware is the only layer that
 * sees both the request and the eventual render, so it forwards the path as a header.
 */
function passThrough(request: NextRequest): NextResponse {
  const headers = new Headers(request.headers);
  headers.set("x-pathname", `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.next({ request: { headers } });
}

function isPublic(pathname: string): boolean {
  if (pathname === "/") return true;
  return PUBLIC_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // --- Platform console --------------------------------------------------
  if (pathname.startsWith("/platform")) {
    const hasPlatformSession =
      request.cookies.has(PLATFORM_ACCESS_COOKIE) ||
      request.cookies.has(PLATFORM_REFRESH_COOKIE);

    if (pathname === "/platform/login") {
      // Already an operator? Skip the form.
      return hasPlatformSession
        ? NextResponse.redirect(new URL("/platform", request.url))
        : passThrough(request);
    }

    if (!hasPlatformSession) {
      const url = new URL("/platform/login", request.url);
      if (pathname !== "/platform") url.searchParams.set("next", pathname);
      return NextResponse.redirect(url);
    }
    return passThrough(request);
  }

  // --- Tenant app + marketing --------------------------------------------
  const hasSession =
    request.cookies.has(ACCESS_COOKIE) || request.cookies.has(REFRESH_COOKIE);

  if (hasSession && AUTH_ONLY_PAGES.includes(pathname)) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  if (!hasSession && !isPublic(pathname)) {
    const url = new URL("/login", request.url);
    // Preserve the destination so login can return them to it. Only same-origin
    // paths are carried, because an absolute URL here would be an open redirect.
    if (pathname !== "/") url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  return passThrough(request);
}

export const config = {
  // Skips API routes (they emit their own 401s rather than redirecting — an XHR
  // that receives a 302 to an HTML login page produces a baffling parse error),
  // Next internals, and static assets.
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|webp|ico)$).*)",
  ],
};
