import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { OnboardingForm } from "./onboarding-form";
import { serverGet } from "@/lib/api/server";
import { PERMISSIONS, type SchoolRead } from "@/lib/api/types";
import { hasPermission, requireUser } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Create your first school" };

/**
 * First-run onboarding (spec §4.3B step 5).
 *
 * A brand-new organization has a principal and no schools. The dashboard would
 * render empty with nothing to explain why, so signup lands here instead.
 *
 * "Already has a school" is a question about the ORGANIZATION, not about the user's
 * memberships. The principal holds a single org-level membership no matter how many
 * campuses exist, so a membership test would answer "no schools" forever and pin
 * them on this page — the school list is the only thing that actually knows.
 */
export default async function OnboardingPage() {
  const [user, t] = await Promise.all([requireUser(), getTranslations()]);

  // Only an org-level role holds `school:create`. A school-scoped member who
  // somehow reached this URL gets sent back rather than shown a form the server
  // would refuse. Checked before the fetch — they have nothing to gain from it.
  if (!hasPermission(user, PERMISSIONS.schoolCreate)) redirect("/dashboard");

  const schools = await serverGet<SchoolRead[]>("/schools", []);
  if (schools.length > 0) redirect("/dashboard");

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
