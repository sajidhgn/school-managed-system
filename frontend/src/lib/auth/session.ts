import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { API_BASE_URL, API_V1_PREFIX, COOKIE_SECURE } from "@/lib/api/config";
import type { MeResponse, PlatformAdminRead } from "@/lib/api/types";

/**
 * Server-only session handling.
 *
 * =============================================================================
 * THE TOKEN NEVER REACHES THE BROWSER, AND THE BROWSER NEVER REACHES THE API
 * =============================================================================
 *   The Next.js server is a confidential client. It calls FastAPI with
 *   `X-Token-Transport: body`, reads the token pair out of the response HEADERS,
 *   and stores it in its own httpOnly cookies. The browser holds an opaque cookie
 *   it cannot read and talks only to `/api/bff/*`.
 *
 *   So a token is never in `localStorage`, never in a JSON body a script can see,
 *   and never in the browser bundle. An XSS payload on this app cannot exfiltrate
 *   a session — it can only ride along on requests while the tab is open, which is
 *   a far smaller blast radius.
 *
 * =============================================================================
 * TWO SESSION KINDS, TWO COOKIE NAMES — deliberately
 * =============================================================================
 *   A tenant user and a platform operator authenticate through different backend
 *   endpoints and carry different `typ` claims. Spec §9 requires the platform
 *   surface to be unreachable with a tenant token and vice versa.
 *
 *   Separate cookies (`educloud_*` vs `educloud_platform_*`) make that
 *   structural rather than a check someone can forget: the tenant BFF simply has
 *   no platform token to send, and the platform BFF has no tenant token. Signing
 *   into the console does not silently sign you out of your school, either —
 *   which matters, because an operator debugging a customer issue is often logged
 *   into both.
 */

// --- Tenant session --------------------------------------------------------
export const ACCESS_COOKIE = "educloud_access";
export const REFRESH_COOKIE = "educloud_refresh";

// --- Platform session ------------------------------------------------------
export const PLATFORM_ACCESS_COOKIE = "educloud_platform_access";
export const PLATFORM_REFRESH_COOKIE = "educloud_platform_refresh";

const BASE_COOKIE = {
  httpOnly: true,
  sameSite: "lax",
  secure: COOKIE_SECURE,
  path: "/",
} as const;

// Mirrors the backend's ACCESS_TOKEN_EXPIRE_MINUTES / REFRESH_TOKEN_EXPIRE_DAYS.
// The access cookie is allowed to outlive its token slightly: an expired token
// produces a 401 the BFF handles by refreshing, whereas a missing cookie makes
// middleware bounce the user to login mid-session for no reason.
const ACCESS_MAX_AGE = 60 * 20;
const REFRESH_MAX_AGE = 60 * 60 * 24 * 30;

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
}

/**
 * Read the token pair out of a backend response's headers.
 *
 * The backend sets its own `Set-Cookie` headers too, but those are scoped to the
 * FastAPI origin and useless here — the browser talks to Next.js. The
 * `X-Token-Transport: body` opt-in makes it also emit the pair as headers, which
 * is the channel this app uses. Returns null when the response carried no tokens
 * (e.g. a login that needs a context selection first).
 */
export function readTokens(response: Response): TokenPair | null {
  const accessToken = response.headers.get("x-access-token");
  const refreshToken = response.headers.get("x-refresh-token");
  if (!accessToken || !refreshToken) return null;
  return { accessToken, refreshToken };
}

export async function setSession(tokens: TokenPair, kind: SessionKind = "tenant"): Promise<void> {
  const store = await cookies();
  const [access, refresh] = cookieNames(kind);
  store.set(access, tokens.accessToken, { ...BASE_COOKIE, maxAge: ACCESS_MAX_AGE });
  store.set(refresh, tokens.refreshToken, { ...BASE_COOKIE, maxAge: REFRESH_MAX_AGE });
}

export async function clearSession(kind: SessionKind = "tenant"): Promise<void> {
  const store = await cookies();
  const [access, refresh] = cookieNames(kind);
  store.delete(access);
  store.delete(refresh);
}

export type SessionKind = "tenant" | "platform";

function cookieNames(kind: SessionKind): [string, string] {
  return kind === "platform"
    ? [PLATFORM_ACCESS_COOKIE, PLATFORM_REFRESH_COOKIE]
    : [ACCESS_COOKIE, REFRESH_COOKIE];
}

export async function getAccessToken(kind: SessionKind = "tenant"): Promise<string | undefined> {
  return (await cookies()).get(cookieNames(kind)[0])?.value;
}

export async function getRefreshToken(kind: SessionKind = "tenant"): Promise<string | undefined> {
  return (await cookies()).get(cookieNames(kind)[1])?.value;
}

/**
 * Exchange the refresh token for a fresh pair.
 *
 * THE NEW PAIR MUST BE PERSISTED. The backend rotates on every refresh and treats
 * a replayed token as theft — presenting the old one again revokes the entire
 * session family. So a refresh whose result is dropped does not merely fail; it
 * arms a trap that logs the user out of every device on their next request.
 *
 * Returns null when the refresh token is expired, revoked, or was already rotated.
 */
export async function refreshSession(kind: SessionKind = "tenant"): Promise<TokenPair | null> {
  const refresh = await getRefreshToken(kind);
  if (!refresh) return null;

  const response = await fetch(`${API_BASE_URL}${API_V1_PREFIX}/auth/refresh`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      // The backend reads the refresh token from this header OR its own cookie.
      // The header is used here because the backend's cookie was never stored by
      // this app — see the module docstring.
      "x-refresh-token": refresh,
      "x-token-transport": "body",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    await clearSession(kind);
    return null;
  }

  const tokens = readTokens(response);
  if (!tokens) {
    await clearSession(kind);
    return null;
  }
  await setSession(tokens, kind);
  return tokens;
}

/**
 * Call a backend endpoint with the current session, refreshing once on a 401.
 *
 * The single retry is deliberate. An access token expiring mid-request is routine
 * and invisible to the user; a second consecutive 401 means the session is
 * genuinely dead, and retrying further would just hammer the auth endpoint.
 */
export async function fetchWithSession(
  path: string,
  init: RequestInit = {},
  kind: SessionKind = "tenant",
): Promise<Response | null> {
  let token = await getAccessToken(kind);

  if (!token) {
    const refreshed = await refreshSession(kind);
    if (!refreshed) return null;
    token = refreshed.accessToken;
  }

  const send = (bearer: string) => {
    // `new Headers(init.headers)` — NOT `{ ...init.headers }`.
    //
    // Spreading a `Headers` INSTANCE produces `{}`: its entries live behind an
    // iterator, not as own enumerable properties. Callers that pass a plain object
    // would work; the BFF proxy passes a real `Headers`, so the spread silently
    // dropped every header including `content-type` — and FastAPI then rejected the
    // body as "not a valid dictionary" on every POST.
    //
    // The constructor accepts both shapes, which is why it is the right thing here.
    const headers = new Headers(init.headers);
    headers.set("authorization", `Bearer ${bearer}`);

    return fetch(`${API_BASE_URL}${API_V1_PREFIX}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
  };

  let response = await send(token);

  if (response.status === 401) {
    const refreshed = await refreshSession(kind);
    if (!refreshed) return null;
    response = await send(refreshed.accessToken);
  }

  return response;
}

// ---------------------------------------------------------------------------
// Tenant session
// ---------------------------------------------------------------------------

/**
 * The signed-in user with their memberships, active context and permissions.
 *
 * Returns null rather than throwing so callers can decide between redirecting and
 * rendering a signed-out view. One round trip: the app shell needs the permission
 * set before it can render the nav, the header needs the active school, and the
 * switcher needs the membership list.
 */
export async function getCurrentUser(): Promise<MeResponse | null> {
  const response = await fetchWithSession("/auth/me");
  if (!response || !response.ok) return null;
  return (await response.json()) as MeResponse;
}

/**
 * Server-component guard for the tenant app.
 *
 * `redirect()` throws, so control never returns on the failure path — which is why
 * the return type is non-nullable and callers need no null check.
 */
export async function requireUser(): Promise<MeResponse> {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return user;
}

/**
 * Guard for pages that need an ACTIVE SCHOOL, not merely a signed-in user.
 *
 * An organization owner's default context is org-level (`school_id` is null), and
 * pages like members, roles and invitations are school-scoped — they have no
 * meaning without a campus. Rather than erroring, this sends the owner to pick one.
 * A brand-new organization with no schools at all goes to onboarding instead.
 */
export async function requireSchoolContext(): Promise<MeResponse> {
  const user = await requireUser();
  if (!user.school_id) redirect("/select-school");
  return user;
}

/** Whether the user holds every one of `codes`. Mirrors the server's `AuthContext.has`. */
export function hasPermission(user: MeResponse | null, ...codes: string[]): boolean {
  if (!user) return false;
  return codes.every((code) => user.permissions.includes(code));
}

// ---------------------------------------------------------------------------
// Platform session
// ---------------------------------------------------------------------------

export async function getCurrentPlatformAdmin(): Promise<PlatformAdminRead | null> {
  const response = await fetchWithSession("/platform/auth/me", {}, "platform");
  if (!response || !response.ok) return null;
  return (await response.json()) as PlatformAdminRead;
}

export async function requirePlatformAdmin(): Promise<PlatformAdminRead> {
  const admin = await getCurrentPlatformAdmin();
  if (!admin) redirect("/platform/login");
  return admin;
}
