import type { Metadata } from "next";
import { Suspense } from "react";

import { SignupForm } from "./signup-form";
import { AuthCard, AuthLink } from "@/components/auth/auth-card";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Create your organization" };

export default async function SignupPage() {
  const t = await getTranslations();

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
        <SignupForm />
      </Suspense>
    </AuthCard>
  );
}
