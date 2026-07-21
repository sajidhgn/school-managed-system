import { AppShell } from "@/components/layout/app-shell";
import { API_BASE_URL, API_V1_PREFIX } from "@/lib/api/config";
import { getAccessToken, requireUser } from "@/lib/auth/session";
import type { SchoolRead } from "@/lib/api/types";

/**
 * Authenticated layout.
 *
 * `requireUser()` re-validates the session against the backend on every
 * navigation. Middleware only checked that a cookie existed; this is where an
 * expired or revoked session actually gets bounced.
 */

export const dynamic = "force-dynamic";

async function fetchCurrentSchool(): Promise<SchoolRead | null> {
  const token = await getAccessToken();
  if (!token) return null;

  try {
    const response = await fetch(`${API_BASE_URL}${API_V1_PREFIX}/schools/current`, {
      headers: { authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    // Super admins have no school of their own — a 404 here is expected.
    if (!response.ok) return null;
    return (await response.json()) as SchoolRead;
  } catch {
    return null;
  }
}

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser();
  const school = await fetchCurrentSchool();

  return (
    <AppShell user={user} school={school}>
      {children}
    </AppShell>
  );
}
