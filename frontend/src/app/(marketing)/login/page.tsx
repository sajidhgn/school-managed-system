import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "./login-form";
import { AuthCard, AuthLink } from "@/components/auth/auth-card";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage() {
  const t = await getTranslations();

  return (
    <AuthCard
      title={t.auth.loginTitle}
      description={t.auth.loginSubtitle}
      footer={
        <>
          {t.auth.noAccount} <AuthLink href="/signup">{t.common.signUp}</AuthLink>
        </>
      }
    >
      {/* The form reads `?next=` from the URL, which requires `useSearchParams`
          and therefore a Suspense boundary — without one, Next.js opts the whole
          route out of static rendering. */}
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </AuthCard>
  );
}
