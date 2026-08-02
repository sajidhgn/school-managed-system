"use client";

import type { ReactNode } from "react";

/**
 * Sign out of the operator console ONLY.
 *
 * Clears the platform cookies and leaves any tenant session alone — an operator
 * debugging a customer issue is often signed into both, and "leave the console"
 * should not also log them out of their own school.
 */
export function PlatformSignOut({ children }: { children: ReactNode }) {
  async function signOut() {
    await fetch("/api/platform/logout", { method: "POST" });
    // Full navigation, not a client-side push: no cached RSC payload holding a
    // customer's data may survive sign-out.
    window.location.href = "/platform/login";
  }

  return (
    <button
      type="button"
      onClick={signOut}
      className="rounded-md p-1.5 text-slate-300 transition-colors hover:bg-slate-800 hover:text-slate-50"
    >
      {children}
    </button>
  );
}
