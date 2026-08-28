import { AppShell } from "@/components/layout/app-shell";
import { SessionProvider } from "@/components/providers/session-provider";
import { serverGetOrNull } from "@/lib/api/server";
import type { SchoolRead } from "@/lib/api/types";
import { getActiveSchoolId, listSchools, requireUser } from "@/lib/auth/session";

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

  // The campus list, for the header switcher. Only an org-level user can move
  // between campuses without re-issuing their session, so this is fetched only for
  // them -- a school-scoped member switches by MEMBERSHIP, which they already have.
  const [schools, activeSchoolId] = user.school_id
    ? [[] as SchoolRead[], null]
    : await Promise.all([listSchools(), getActiveSchoolId()]);

  // The branch that is OPEN, as a whole record — the header names it and shows its
  // address, so a name alone is not enough.
  //
  // A school-scoped member is permanently inside their own campus and has no say in
  // it, so theirs is read from the session's `school_id`. An org-level principal is
  // inside one only once they open it, which is why this reads the selection rather
  // than falling back to "any campus exists" — the sidebar is meant to answer "which
  // branch am I in", and it cannot do that if the answer is inferred.
  //
  // MUST agree with `requireSchoolContext()`, or the nav offers pages that bounce.
  const activeSchool: SchoolRead | null = user.school_id
    ? await serverGetOrNull<SchoolRead>(`/schools/${user.school_id}`)
    : (schools.find((s) => s.id === activeSchoolId) ?? null);

  return (
    <SessionProvider user={user}>
      <AppShell
        schools={schools}
        activeSchoolId={activeSchoolId}
        activeSchool={activeSchool}
        // A school-scoped member always has a campus even if the fetch above failed,
        // so the sidebar must not go dark over a slow request.
        activeSchoolName={activeSchool?.name ?? user.school_name ?? null}
      >
        {children}
      </AppShell>
    </SessionProvider>
  );
}
