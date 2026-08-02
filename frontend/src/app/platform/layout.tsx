import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Operator console", template: "%s · Operator console" },
  // The console must never be indexed. It is not secret — the backend refuses
  // unauthenticated requests regardless — but a search result pointing at it is an
  // invitation to probe.
  robots: { index: false, follow: false },
};

/**
 * Platform operator console group (spec §9's `(platform)`).
 *
 * A pass-through: `/platform/login` needs no chrome, and the authenticated pages
 * wrap themselves in `<PlatformChrome>` after resolving the operator. Putting the
 * chrome here instead would mean either rendering a nav to someone who is not signed
 * in, or fetching the session twice.
 */
export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  return children;
}
