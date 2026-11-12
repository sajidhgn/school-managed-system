import { dehydrate, hydrate, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { idbDelete, idbGet, idbKeys, idbSet } from "./idb";

/**
 * Keep a copy of chosen query results on the device, so screens open offline.
 *
 * =============================================================================
 * AN ALLOWLIST, NOT THE WHOLE CACHE
 * =============================================================================
 *   What is kept is what someone needs with no connection: today's attendance board,
 *   registers and section rosters (to take attendance), the class list, and the
 *   student directory (to find a parent's number). Fees, payments and anything with
 *   money are NOT kept: those screens cannot act offline anyway, and a challan
 *   history has no business sitting on a staff-room computer.
 *
 * The copy is per user and per campus, older than three days is ignored, and it is
 * deleted on sign-out (`clearOfflineData`). The in-memory cache keeps these queries
 * for the same three days (`gcTime`), or a roster prefetched for later would be
 * garbage-collected — and so dropped from the device — five minutes after nobody
 * was looking at it.
 */

const PERSISTED_PREFIXES: QueryKey[] = [
  ["attendance", "today"],
  ["attendance", "session"],
  ["classes", "sections"],
  ["classes", "summary"],
  ["students", "list"],
  ["students", "detail"],
];

export const OFFLINE_MAX_AGE_MS = 3 * 24 * 60 * 60 * 1000;
const SAVE_DELAY_MS = 1_500;

const storageKey = (scope: string) => `rq:${scope}`;

function isPersisted(key: QueryKey): boolean {
  return PERSISTED_PREFIXES.some((prefix) =>
    prefix.every((part, index) => key[index] === part),
  );
}

interface Saved {
  savedAt: number;
  state: ReturnType<typeof dehydrate>;
}

/** Put the device's copy back into the cache. Newer data already in memory wins. */
export async function restoreQueries(client: QueryClient, scope: string): Promise<void> {
  const saved = await idbGet<Saved>(storageKey(scope));
  if (!saved || Date.now() - saved.savedAt > OFFLINE_MAX_AGE_MS) return;
  hydrate(client, saved.state);
}

/** Save allowlisted queries whenever one of them updates. Returns the unsubscribe. */
export function startQueryPersistence(client: QueryClient, scope: string): () => void {
  for (const prefix of PERSISTED_PREFIXES) {
    client.setQueryDefaults(prefix, { gcTime: OFFLINE_MAX_AGE_MS });
  }

  let timer: ReturnType<typeof setTimeout> | null = null;
  const save = () => {
    timer = null;
    const state = dehydrate(client, {
      shouldDehydrateQuery: (query) =>
        query.state.status === "success" && isPersisted(query.queryKey),
    });
    void idbSet(storageKey(scope), { savedAt: Date.now(), state } satisfies Saved);
  };
  const schedule = () => {
    if (timer === null) timer = setTimeout(save, SAVE_DELAY_MS);
  };

  const unsubscribe = client.getQueryCache().subscribe((event) => {
    if (!isPersisted(event.query.queryKey)) return;
    if (event.type === "removed") schedule();
    else if (event.type === "updated" && event.action.type === "success") schedule();
  });

  return () => {
    unsubscribe();
    if (timer !== null) {
      clearTimeout(timer);
      save();
    }
  };
}

/**
 * Delete what this device keeps offline: saved queries and queued registers for the
 * given user (every campus), or for everyone when `userId` is omitted — and the
 * pages the service worker cached. Called on sign-out and when a different person
 * signs in on the same device.
 */
export async function clearOfflineData(userId?: string): Promise<void> {
  const keys = await idbKeys();
  await Promise.all(
    keys
      .filter((key) => /^(rq|outbox):/.test(key))
      .filter((key) => !userId || key.split(":")[1] === userId)
      .map((key) => idbDelete(key)),
  );
  if (typeof caches !== "undefined") {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith("sy-pages")).map((n) => caches.delete(n)));
  }
}
