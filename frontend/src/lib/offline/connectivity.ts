/**
 * Is the app able to reach its server right now?
 *
 * =============================================================================
 * `navigator.onLine` IS NOT THE ANSWER
 * =============================================================================
 *   It reports whether a network interface is up. A school's wifi with no working
 *   internet behind it — common enough to design for — reads as online while every
 *   request hangs and fails. So the store has two inputs:
 *
 *     * the browser's `offline` / `online` events, which are right when they fire;
 *     * the API client, which reports a request that failed at the network level
 *       (`reportNetworkFailure`) and any response at all (`reportReachable`).
 *
 *   Once offline, it polls `/api/ping` until the server answers, so the app notices
 *   the connection coming back even when the browser does not fire an event.
 *
 * TanStack Query's `onlineManager` is driven from here (see `OfflineProvider`), so
 * queries pause instead of erroring while offline and refetch on reconnect.
 */

type Listener = (online: boolean) => void;

const PING_URL = "/api/ping";
const PING_INTERVAL_MS = 10_000;
const PING_TIMEOUT_MS = 5_000;

let online = typeof navigator === "undefined" ? true : navigator.onLine;
const listeners = new Set<Listener>();
let pingTimer: ReturnType<typeof setTimeout> | null = null;
let browserEventsBound = false;

function set(next: boolean) {
  if (next === online) return;
  online = next;
  for (const listener of listeners) listener(online);
  if (!online) schedulePing();
}

function schedulePing() {
  if (pingTimer !== null || typeof window === "undefined") return;
  pingTimer = setTimeout(async () => {
    pingTimer = null;
    if (online) return;
    if (await ping()) set(true);
    else schedulePing();
  }, PING_INTERVAL_MS);
}

/** One reachability check. True when the server answered at all. */
export async function ping(): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PING_TIMEOUT_MS);
  try {
    const response = await fetch(PING_URL, { cache: "no-store", signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function bindBrowserEvents() {
  if (browserEventsBound || typeof window === "undefined") return;
  browserEventsBound = true;
  window.addEventListener("offline", () => set(false));
  // The browser saying "online" only means an interface came up; confirm with the
  // server before telling the app, or a wifi with no internet would flap.
  window.addEventListener("online", () => {
    void ping().then((reachable) => (reachable ? set(true) : schedulePing()));
  });
  if (!online) schedulePing();
}

export function isOnline(): boolean {
  return online;
}

export function subscribeConnectivity(listener: Listener): () => void {
  bindBrowserEvents();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** A request failed before any response arrived: treat the server as unreachable. */
export function reportNetworkFailure() {
  bindBrowserEvents();
  set(false);
}

/** A response arrived (any status): the server is reachable. */
export function reportReachable() {
  set(true);
}

/** Check now, rather than waiting for the next poll — the banner's "Try again". */
export async function checkConnectivity(): Promise<boolean> {
  const reachable = await ping();
  set(reachable);
  return reachable;
}
