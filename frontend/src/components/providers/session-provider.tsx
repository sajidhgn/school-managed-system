"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { MeResponse } from "@/lib/api/types";

/**
 * Makes the signed-in user available to client components.
 *
 * The value is fetched ONCE, on the server, in the app-group layout, and passed
 * down. Client components never fetch `/auth/me` themselves.
 *
 * WHY NOT A CLIENT-SIDE QUERY
 *   The nav, the header and every `<Can>` need the permission set before first
 *   paint. Fetching it in the browser would mean the app renders once with no
 *   permissions — every guarded control hidden — and then again once the response
 *   lands. Users see the interface flicker and rebuild itself on every navigation,
 *   which reads as broken even though it settles correctly.
 *
 * The value is READ-ONLY here. Anything that changes the session — switching
 * context, signing out — goes through a route handler that rewrites the httpOnly
 * cookie and then triggers a router refresh, so the server re-renders with fresh
 * data. There is deliberately no setter: client state that disagrees with the
 * cookie is a bug waiting to be written.
 */

const SessionContext = createContext<MeResponse | null>(null);

export function SessionProvider({
  user,
  children,
}: {
  user: MeResponse;
  children: ReactNode;
}) {
  return <SessionContext.Provider value={user}>{children}</SessionContext.Provider>;
}

export function useSession(): { user: MeResponse | null } {
  return { user: useContext(SessionContext) };
}

/**
 * The session, asserting it exists.
 *
 * For components that only ever render inside the authenticated app group. Throwing
 * beats returning null here: a null user in that tree is a wiring mistake, and a
 * loud error at the point of use is far easier to trace than a component that
 * silently renders nothing.
 */
export function useRequiredSession(): MeResponse {
  const user = useContext(SessionContext);
  if (!user) {
    throw new Error(
      "useRequiredSession() was called outside <SessionProvider>. " +
        "This component must render inside the authenticated app layout.",
    );
  }
  return user;
}
