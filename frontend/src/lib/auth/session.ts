import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { API_BASE_URL, API_V1_PREFIX, COOKIE_SECURE } from "@/lib/api/config";
import type { TokenPair, UserRead } from "@/lib/api/types";

export const ACCESS_COOKIE = "sms_access";
export const REFRESH_COOKIE = "sms_refresh";

const BASE_COOKIE = {
  httpOnly: true,
  sameSite: "lax",
  secure: COOKIE_SECURE,
  path: "/",
} as const;

/**
 * Persist a token pair as httpOnly cookies.
 *
 * The access cookie expires with the token (`expires_in`); the refresh cookie
 * outlives it so a returning user is silently re-authenticated. Because both
 * are httpOnly, no browser script can read them — the BFF proxy is the only
 * thing that ever sees a raw token.
 */
export async function setSession(tokens: TokenPair): Promise<void> {
  const store = await cookies();
  store.set(ACCESS_COOKIE, tokens.access_token, {
    ...BASE_COOKIE,
    maxAge: tokens.expires_in,
  });
  store.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...BASE_COOKIE,
    // Backend default is REFRESH_TOKEN_EXPIRE_DAYS=7.
    maxAge: 60 * 60 * 24 * 7,
  });
}

export async function clearSession(): Promise<void> {
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
}

export async function getAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(ACCESS_COOKIE)?.value;
}

export async function getRefreshToken(): Promise<string | undefined> {
  return (await cookies()).get(REFRESH_COOKIE)?.value;
}

/**
 * Exchange the refresh token for a fresh pair.
 *
 * The backend rotates refresh tokens, so the old one is dead after this call —
 * we must persist the new pair or the user is logged out on the next request.
 * Returns null when the refresh token is expired/revoked.
 */
export async function refreshSession(): Promise<TokenPair | null> {
  const refresh = await getRefreshToken();
  if (!refresh) return null;

  const response = await fetch(`${API_BASE_URL}${API_V1_PREFIX}/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
    cache: "no-store",
  });

  if (!response.ok) {
    await clearSession();
    return null;
  }

  const tokens = (await response.json()) as TokenPair;
  await setSession(tokens);
  return tokens;
}

/**
 * Resolve the signed-in user for server components and middleware-adjacent
 * checks. Returns null rather than throwing so callers can redirect.
 */
export async function getCurrentUser(): Promise<UserRead | null> {
  let token = await getAccessToken();

  if (!token) {
    const refreshed = await refreshSession();
    if (!refreshed) return null;
    token = refreshed.access_token;
  }

  const fetchMe = async (bearer: string) =>
    fetch(`${API_BASE_URL}${API_V1_PREFIX}/auth/me`, {
      headers: { authorization: `Bearer ${bearer}` },
      cache: "no-store",
    });

  let response = await fetchMe(token);

  if (response.status === 401) {
    const refreshed = await refreshSession();
    if (!refreshed) return null;
    response = await fetchMe(refreshed.access_token);
  }

  if (!response.ok) return null;
  return (await response.json()) as UserRead;
}

/** Server-component guard: returns the user or throws to the nearest redirect. */
export async function requireUser(): Promise<UserRead> {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return user;
}
