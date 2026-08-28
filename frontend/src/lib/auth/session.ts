import "server-only";

import { createHash } from "node:crypto";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { API_BASE_URL, API_V1_PREFIX, COOKIE_SECURE } from "@/lib/api/config";
import type { MeResponse, PlatformAdminRead, SchoolRead } from "@/lib/api/types";

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

/**
 * Which campus an ORG-LEVEL user is currently looking at.
 *
 * Not part of the session, and deliberately not a token claim. The principal is
 * org-level: their membership spans every school, and the backend authorises the
 * school-scoped routes from the `{school_id}` in the path plus that org-level scope.
 * So "which campus am I viewing" is a view preference, not an authorisation fact,
 * and putting it in the token would mean re-minting a session to change a heading.
 *
 * Forging this cookie gains nothing: it only selects which school id the page asks
 * for, and the backend still refuses any school outside the caller's organisation.
 */
export const ACTIVE_SCHOOL_COOKIE = "educloud_active_school";

/**
 * Set for a few seconds while a dead session is being recovered.
 *
 * The loop breaker. `/api/auth/recover` refreshes and sends the user back; if that
 * page STILL cannot resolve a session it bounces to recover again, and without a
 * marker the two would trade redirects forever. Seeing this cookie on entry means
 * "we already tried" — so recover stops trying and signs the user out instead.
 */
const RECOVERY_COOKIES = {
  tenant: "educloud_recovering",
  platform: "educloud_platform_recovering",
} as const;
const RECOVERY_MAX_AGE = 10;

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

export function readAccessToken(response: Response): string | null {
  return response.headers.get("x-access-token");
}

export async function setAccessToken(accessToken: string): Promise<void> {
  const store = await cookies();
  store.set(ACCESS_COOKIE, accessToken, { ...BASE_COOKIE, maxAge: 60 * 5 });
  store.delete(REFRESH_COOKIE);
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
  // The next person to sign in on this browser must not inherit the last one's
  // campus selection — they may not even be in the same organisation.
  if (kind === "tenant") store.delete(ACTIVE_SCHOOL_COOKIE);
}

export async function isRecovering(kind: SessionKind = "tenant"): Promise<boolean> {
  return (await cookies()).has(RECOVERY_COOKIES[kind]);
}

export async function beginRecovery(kind: SessionKind = "tenant"): Promise<void> {
  const store = await cookies();
  store.set(RECOVERY_COOKIES[kind], "1", { ...BASE_COOKIE, maxAge: RECOVERY_MAX_AGE });
}

export async function endRecovery(kind: SessionKind = "tenant"): Promise<void> {
  (await cookies()).delete(RECOVERY_COOKIES[kind]);
}

/**
 * A same-origin path from untrusted input, or null.
 *
 * `//evil.example` and `/\evil.example` are both read as protocol-relative URLs by
 * browsers, so a leading-slash test alone is an open redirect. This is the only
 * validation between a query string and a `Location` header.
 */
export function safePath(value: string | null | undefined): string | null {
  if (!value || !value.startsWith("/")) return null;
  if (value.startsWith("//") || value.startsWith("/\\")) return null;
  return value;
}

/** The path currently being rendered, published by middleware. */
async function currentPath(): Promise<string> {
  return safePath((await headers()).get("x-pathname")) ?? "/dashboard";
}

export async function getActiveSchoolId(): Promise<string | null> {
  return (await cookies()).get(ACTIVE_SCHOOL_COOKIE)?.value ?? null;
}

export async function setActiveSchoolId(schoolId: string): Promise<void> {
  const store = await cookies();
  store.set(ACTIVE_SCHOOL_COOKIE, schoolId, { ...BASE_COOKIE, maxAge: REFRESH_MAX_AGE });
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
const refreshes = new Map<string, Promise<TokenPair | null>>();

async function rotateRefreshToken(refresh: string): Promise<TokenPair | null> {
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

  if (!response.ok) return null;

  const tokens = readTokens(response);
  return tokens;
}

export async function refreshSession(kind: SessionKind = "tenant"): Promise<TokenPair | null> {
  const refresh = await getRefreshToken(kind);
  if (!refresh) return null;

  // Key by the credential digest, not only tenant/platform kind: two users whose
  // requests land on the same Next.js process must never share a refresh result.
  const key = `${kind}:${createHash("sha256").update(refresh).digest("hex")}`;
  let pending = refreshes.get(key);
  if (!pending) {
    pending = rotateRefreshToken(refresh);
    refreshes.set(key, pending);
    void pending.finally(() => refreshes.delete(key));
  }

  const tokens = await pending;
  if (!tokens) {
    await clearSession(kind);
    return null;
  }

  // Each waiting route-handler request writes the shared result into its own
  // response cookie context. The backend rotation itself occurred exactly once.
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
  allowRefresh = false,
): Promise<Response | null> {
  let token = await getAccessToken(kind);

  if (!token) {
    if (!allowRefresh) return null;
    const refreshed = await refreshSession(kind);
    if (!refreshed) return null;
    token = refreshed.accessToken;
  }

  // The campus an org-level user has selected, forwarded so the backend's
  // school-scoped repositories filter to it. The server reads it from the httpOnly
  // cookie rather than trusting a client header — see the BFF's stripped list.
  const activeSchoolId = kind === "tenant" ? await getActiveSchoolId() : null;

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
    if (activeSchoolId) headers.set("x-active-school", activeSchoolId);

    return fetch(`${API_BASE_URL}${API_V1_PREFIX}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
  };

  let response = await send(token);

  if (response.status === 401) {
    if (!allowRefresh) return response;
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
 *
 * =============================================================================
 * WHY THIS DOES NOT REDIRECT STRAIGHT TO /login
 * =============================================================================
 *   It used to, and that was an infinite redirect loop. Middleware bounces a
 *   request holding a session cookie AWAY from /login; this guard bounces a request
 *   whose session does not resolve TOWARDS it. A cookie that exists but no longer
 *   works satisfies both at once, and the two trade 307s until the browser gives up.
 *
 *   The state is not rare. `getCurrentUser()` deliberately does not refresh — a
 *   Server Component cannot write cookies in Next 15, so it has no way to persist a
 *   rotated pair — which means an access token that expired while the refresh token
 *   is still perfectly good lands here. That is every session left idle past
 *   ACCESS_MAX_AGE.
 *
 *   So the failure path goes through a ROUTE HANDLER, which can write cookies: it
 *   refreshes and puts the user back where they were, or clears the cookies and
 *   sends them to a /login that middleware will now leave alone. Either way the
 *   loop cannot form, because the cookie never survives the bounce unusable.
 */
export async function requireUser(): Promise<MeResponse> {
  const user = await getCurrentUser();
  if (!user) redirect(`/api/auth/recover?next=${encodeURIComponent(await currentPath())}`);
  return user;
}

export interface SchoolScopedSession {
  user: MeResponse;
  /** The campus these pages should render. Never null — the guard redirects instead. */
  schoolId: string;
}

/**
 * Guard for pages that need an ACTIVE SCHOOL, not merely a signed-in user.
 *
 * There are two ways to have one, and the difference matters:
 *
 *   * A school-scoped member (teacher, accountant) carries `school_id` in the
 *     session itself. It is fixed — it IS their authorisation scope, and they have
 *     no say in it.
 *
 *   * The principal is org-level, so their session carries no school. They pick a
 *     campus, and the choice lives in a cookie. It narrows what these pages DISPLAY
 *     without narrowing what they may do, which is exactly right: the principal
 *     administers every campus, and looking at one of them is not a demotion.
 *
 * WHY NOTHING IS GUESSED WHEN NO CAMPUS IS CHOSEN
 *   Picking one implicitly — the organization's first, say — would mean these pages
 *   always render SOME campus, and the sidebar would always offer them. The campus
 *   modules are meant to open for the branch you opened, and stay shut until you
 *   open one. Guessing makes "which branch am I looking at?" a question the
 *   interface answers silently and sometimes wrongly.
 *
 *   `SidebarNav` gates the same items on the same fact, so the nav and this guard
 *   cannot drift into offering pages that bounce, or hiding pages that work.
 */
export async function requireSchoolContext(): Promise<SchoolScopedSession> {
  const user = await requireUser();
  if (user.school_id) return { user, schoolId: user.school_id };

  const activeSchoolId = await getActiveSchoolId();
  if (activeSchoolId) return { user, schoolId: activeSchoolId };

  redirect("/select-school");
}

/**
 * The campuses this session can see, or an empty list.
 *
 * Fetched through `fetchWithSession` rather than `serverGet` to keep this module
 * free of an import cycle: `lib/api/server` is built on top of this file.
 */
export async function listSchools(): Promise<SchoolRead[]> {
  try {
    const response = await fetchWithSession("/schools", { method: "GET" });
    if (!response || !response.ok) return [];
    return (await response.json()) as SchoolRead[];
  } catch {
    return [];
  }
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

/** The platform half of `requireUser()`, with the same loop and the same fix. */
export async function requirePlatformAdmin(): Promise<PlatformAdminRead> {
  const admin = await getCurrentPlatformAdmin();
  if (!admin) redirect(`/api/platform/recover?next=${encodeURIComponent(await currentPath())}`);
  return admin;
}
