import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { OnboardingForm } from "./onboarding-form";
import { PERMISSIONS } from "@/lib/api/types";
import { hasPermission, requireUser } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Create your first school" };

/**
 * First-run onboarding (spec §4.3B step 5).
 *
 * A brand-new organization has an owner and no schools. The dashboard would render
 * empty with nothing to explain why, so signup lands here instead.
 *
 * Creating the first school also grants the owner a PRINCIPAL membership on it —
 * spec decision D2's payoff, and the step that produces the behaviour requirement #6
 * describes: sign up, buy a plan, land in the admin panel as principal.
 *
 * Anyone who already has a school is redirected out: this page has no meaning for
 * them, and leaving it reachable invites a second "first" school.
 */
export default async function OnboardingPage() {
  const [user, t] = await Promise.all([requireUser(), getTranslations()]);

  const hasAnySchool = user.memberships.some((m) => !m.is_org_level);
  if (hasAnySchool) redirect("/dashboard");

  // Only an org-level role holds `school:create`. A principal who somehow reached
  // this URL gets sent back rather than shown a form the server would refuse.
  if (!hasPermission(user, PERMISSIONS.schoolCreate)) redirect("/dashboard");

  return (
    <div className="mx-auto w-full max-w-lg py-8">
      <h1 className="text-2xl font-semibold tracking-tight">{t.onboarding.title}</h1>
      <p className="mt-2 text-muted-foreground text-pretty">{t.onboarding.subtitle}</p>
      <div className="mt-8 rounded-xl border border-border bg-card p-6">
        <OnboardingForm />
      </div>
    </div>
  );
}
