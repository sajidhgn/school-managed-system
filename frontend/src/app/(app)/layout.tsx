import { AppShell } from "@/components/layout/app-shell";
import { SessionProvider } from "@/components/providers/session-provider";
import { requireUser } from "@/lib/auth/session";

/**
 * Authenticated tenant shell.
 *
 * `requireUser()` VALIDATES the session against the backend — middleware only saw
 * that a cookie existed, which anyone can forge. This is the check that actually
 * matters on the frontend, and it runs before any page in the group renders.
 *
 * The resolved user (memberships, active context, permission set) is published once
 * here and consumed by client components through `useSession()`. Fetching it per
 * component would mean the nav renders with no permissions and then rebuilds itself
 * once the response lands — which reads as broken even though it settles correctly.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser();

  return (
    <SessionProvider user={user}>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
