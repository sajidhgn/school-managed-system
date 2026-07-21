import { NextRequest, NextResponse } from "next/server";

/**
 * Edge gate for the dashboard.
 *
 * This is a cheap redirect for the common case, NOT an authorization check —
 * it only sees whether a session cookie exists, not whether it is valid or
 * what role it carries. Real enforcement lives in the backend's
 * `require_roles` dependencies; server components re-verify via
 * `requireUser()`.
 */

const ACCESS_COOKIE = "sms_access";
const REFRESH_COOKIE = "sms_refresh";

const PUBLIC_ROUTES = [
  "/login",
  "/register",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
  "/admissions",
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const hasSession =
    request.cookies.has(ACCESS_COOKIE) || request.cookies.has(REFRESH_COOKIE);
  const isPublic = PUBLIC_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );

  if (!hasSession && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    // Preserve where they were headed so login can bounce them back.
    if (pathname !== "/") url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  // Already signed in and landing on an auth page — send them to the dashboard.
  if (hasSession && (pathname === "/login" || pathname === "/register")) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Skip static assets, the BFF/auth handlers (they manage their own 401s),
  // and Next internals.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|webp)$).*)"],
};
