"use client";

import * as React from "react";
import { onlineManager, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import { fill } from "@/lib/i18n/format";
import { offlineMessages } from "@/lib/i18n/modules/offline";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { getOutbox, loadOutbox, subscribeOutbox } from "@/lib/offline/attendance-outbox";
import { syncAttendanceOutbox } from "@/lib/offline/attendance-sync";
import {
  checkConnectivity,
  isOnline,
  subscribeConnectivity,
} from "@/lib/offline/connectivity";
import {
  clearOfflineData,
  restoreQueries,
  startQueryPersistence,
} from "@/lib/offline/query-persistence";

/**
 * Offline mode for the signed-in app. Mounted once, inside the app shell.
 *
 * For the current user on the current campus it:
 *   - restores the device's saved copy of key screens and keeps it up to date;
 *   - loads the queue of registers taken offline;
 *   - drives TanStack Query's idea of "online" from real reachability, so queries
 *     pause (showing saved data) instead of failing, and refetch on reconnect;
 *   - sends the queue when the app starts online, when the connection returns, and
 *     every minute while something is waiting;
 *   - registers the service worker (production builds only — in development it
 *     would serve stale pages over hot reload).
 *
 * When a different person signs in on the same device, everything the previous
 * one kept offline is deleted first.
 */

const SYNC_INTERVAL_MS = 60_000;
const LAST_USER_KEY = "sy-offline-user";

interface OfflineContextValue {
  online: boolean;
  syncing: boolean;
  syncNow: () => Promise<void>;
}

const OfflineContext = React.createContext<OfflineContextValue | null>(null);

let onlineManagerBound = false;
function bindOnlineManager() {
  if (onlineManagerBound) return;
  onlineManagerBound = true;
  onlineManager.setEventListener((setOnline) => {
    setOnline(isOnline());
    return subscribeConnectivity(setOnline);
  });
}

export function useOnline(): boolean {
  return React.useSyncExternalStore(subscribeConnectivity, isOnline, () => true);
}

export function OfflineProvider({
  userId,
  schoolId,
  children,
}: {
  userId: string;
  schoolId: string | null;
  children: React.ReactNode;
}) {
  const queryClient = useQueryClient();
  const m = useCatalog(offlineMessages);
  const online = useOnline();
  const [syncing, setSyncing] = React.useState(false);
  const [ready, setReady] = React.useState(false);
  const scope = `${userId}:${schoolId ?? "org"}`;
  const previousScope = React.useRef<string | null>(null);
  // One run at a time in this tab: the run's own queue updates would otherwise
  // trigger nested runs through the outbox subscription below.
  const running = React.useRef(false);

  // The latest strings for the sync callback, without re-creating it on locale change.
  const messagesRef = React.useRef(m);
  messagesRef.current = m;

  React.useEffect(() => {
    bindOnlineManager();
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
        // No service worker (unsupported, blocked): pages just won't open offline.
      });
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    let stopPersisting: (() => void) | null = null;
    setReady(false);

    void (async () => {
      // Another person signed in on this device: delete what the last one kept.
      let lastUser: string | null = null;
      try {
        lastUser = localStorage.getItem(LAST_USER_KEY);
      } catch {
        // Storage blocked: nothing to compare against.
      }
      if (lastUser && lastUser !== userId) await clearOfflineData();
      try {
        localStorage.setItem(LAST_USER_KEY, userId);
      } catch {
        // Storage blocked.
      }

      // A campus switch: what is in memory belongs to the other campus.
      if (previousScope.current && previousScope.current !== scope) queryClient.clear();
      previousScope.current = scope;

      await restoreQueries(queryClient, scope);
      await loadOutbox(scope);
      if (cancelled) return;
      stopPersisting = startQueryPersistence(queryClient, scope);
      setReady(true);
    })();

    return () => {
      cancelled = true;
      stopPersisting?.();
    };
  }, [queryClient, scope, userId]);

  const syncNow = React.useCallback(async () => {
    if (running.current) return;
    if (!getOutbox().some((item) => item.state === "pending")) return;
    if (!isOnline() && !(await checkConnectivity())) return;
    running.current = true;
    setSyncing(true);
    try {
      const strings = messagesRef.current;
      const result = await syncAttendanceOutbox(strings.errors);
      if (!result) return;
      if (result.synced > 0) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.attendance.all });
        toast.success(
          fill(result.synced === 1 ? strings.toast.syncedOne : strings.toast.syncedMany, {
            count: result.synced,
          }),
          strings.toast.syncedBody,
        );
      }
      if (result.failed > 0) {
        toast.error(
          fill(result.failed === 1 ? strings.toast.failedOne : strings.toast.failedMany, {
            count: result.failed,
          }),
          strings.toast.failedBody,
        );
      }
    } finally {
      running.current = false;
      setSyncing(false);
    }
  }, [queryClient]);

  // Send the queue: once loaded, whenever the connection returns, when something is
  // queued while online (a save that fell back to the device), and every minute.
  React.useEffect(() => {
    if (!ready || !online) return;
    void syncNow();
    const unsubscribe = subscribeOutbox(() => {
      if (isOnline()) void syncNow();
    });
    const timer = setInterval(() => void syncNow(), SYNC_INTERVAL_MS);
    return () => {
      unsubscribe();
      clearInterval(timer);
    };
  }, [ready, online, syncNow]);

  const value = React.useMemo(() => ({ online, syncing, syncNow }), [online, syncing, syncNow]);
  return <OfflineContext.Provider value={value}>{children}</OfflineContext.Provider>;
}

export function useOffline(): OfflineContextValue {
  const value = React.useContext(OfflineContext);
  if (!value) throw new Error("useOffline() was called outside <OfflineProvider>.");
  return value;
}
