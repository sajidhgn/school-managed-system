import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ContextPicker } from "@/components/auth/context-picker";
import { requireUser } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Choose a school" };

/**
 * Where `requireSchoolContext()` sends an org-level user.
 *
 * The owner's default context is org-level (`school_id` is null), which is right for
 * billing, the school list and organization settings — but meaningless for members,
 * roles, invitations or attendance. Rather than erroring on those pages, the owner is
 * asked which campus they mean.
 *
 * An organization with no schools yet goes to onboarding instead: offering a picker
 * with nothing in it is a dead end.
 */
export default async function SelectSchoolPage() {
  const [user, t] = await Promise.all([requireUser(), getTranslations()]);

  const schoolMemberships = user.memberships.filter((m) => !m.is_org_level);

  if (schoolMemberships.length === 0) redirect("/onboarding");
  if (user.school_id) redirect("/dashboard");

  return (
    <div className="mx-auto w-full max-w-md py-10">
      <h1 className="text-2xl font-semibold tracking-tight">{t.selectSchool.title}</h1>
      <p className="mt-2 text-muted-foreground text-pretty">
        {t.selectSchool.body}
      </p>
      <div className="mt-8 rounded-xl border border-border bg-card p-6">
        <ContextPicker memberships={schoolMemberships} redirectTo="/dashboard" />
      </div>
      <p className="mt-4 text-center text-xs text-muted-foreground">{t.auth.selectContextHint}</p>
    </div>
  );
}
