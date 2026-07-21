import { ApiError, toProblem } from "./errors";

/**
 * Browser-side API client.
 *
 * Talks to the BFF proxy (`/api/bff/*`), never to FastAPI directly — the proxy
 * attaches the Bearer token from the httpOnly cookie. That means no token
 * handling, no Authorization header, and no refresh logic lives in the browser.
 */

const BFF_PREFIX = "/api/bff";

export type QueryValue = string | number | boolean | null | undefined;

/** Serialise params, dropping null/undefined/"" so we never send `?q=`. */
export function toSearchParams(params: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

interface RequestOptions {
  params?: Record<string, QueryValue>;
  signal?: AbortSignal;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const url = `${BFF_PREFIX}${path.startsWith("/") ? path : `/${path}`}${toSearchParams(
    options.params,
  )}`;

  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: options.signal,
    credentials: "same-origin",
  });

  if (!response.ok) {
    throw new ApiError(await toProblem(response));
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, undefined, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("POST", path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PATCH", path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>("PUT", path, body, options),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>("DELETE", path, undefined, options),
};

/**
 * Auth endpoints bypass the BFF proxy — they mint tokens, so they are handled
 * by dedicated route handlers that set httpOnly cookies server-side.
 */
export async function authRequest<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`/api/auth${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });

  if (!response.ok) {
    throw new ApiError(await toProblem(response));
  }

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}
