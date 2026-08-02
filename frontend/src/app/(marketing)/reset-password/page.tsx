import type { Metadata } from "next";
import { Suspense } from "react";

import { ResetPasswordForm } from "./reset-password-form";
import { AuthCard, AuthLink } from "@/components/auth/auth-card";

export const metadata: Metadata = { title: "Choose a new password" };

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;

  if (!token) {
    return (
      <AuthCard
        title="Link incomplete"
        description="This reset link is missing its token. Request a new one."
        footer={<AuthLink href="/forgot-password">Request a new link</AuthLink>}
      >
        <p className="text-sm text-muted-foreground">
          Reset links expire after an hour and can only be used once.
        </p>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Choose a new password"
      description="Signing you out of every device once it's set."
      footer={<AuthLink href="/login">Back to sign in</AuthLink>}
    >
      <Suspense fallback={null}>
        <ResetPasswordForm token={token} />
      </Suspense>
    </AuthCard>
  );
}
