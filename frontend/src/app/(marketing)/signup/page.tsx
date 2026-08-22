import type { Metadata } from "next";
import { Suspense } from "react";

import { SignupForm } from "./signup-form";
import { AuthCard, AuthLink } from "@/components/auth/auth-card";
import { API_BASE_URL, API_V1_PREFIX } from "@/lib/api/config";
import type { PlanPublic } from "@/lib/api/types";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Create your organization" };

export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<{ plan?: string; cycle?: string }>;
}) {
  const [t, query, plansResponse] = await Promise.all([
    getTranslations(),
    searchParams,
    fetch(`${API_BASE_URL}${API_V1_PREFIX}/public/plans`, { next: { revalidate: 300 } }),
  ]);
  const plans: PlanPublic[] = plansResponse.ok ? await plansResponse.json() : [];
  const initialPlanCode = plans.some((plan) => plan.code === query.plan) ? query.plan! : "free";
  const initialCycle = query.cycle === "yearly" ? "yearly" : "monthly";

  return (
    <AuthCard
      title={t.auth.signupTitle}
      description={t.auth.signupSubtitle}
      footer={
        <>
          {t.auth.haveAccount} <AuthLink href="/login">{t.common.signIn}</AuthLink>
        </>
      }
    >
      <Suspense fallback={null}>
        <SignupForm
          plans={plans}
          initialPlanCode={initialPlanCode}
          initialCycle={initialCycle}
        />
      </Suspense>
    </AuthCard>
  );
}
