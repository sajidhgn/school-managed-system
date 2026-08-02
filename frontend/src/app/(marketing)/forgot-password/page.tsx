import type { Metadata } from "next";

import { ForgotPasswordForm } from "./forgot-password-form";
import { AuthCard, AuthLink } from "@/components/auth/auth-card";

export const metadata: Metadata = { title: "Reset your password" };

export default function ForgotPasswordPage() {
  return (
    <AuthCard
      title="Reset your password"
      description="We'll email you a link to choose a new one."
      footer={<AuthLink href="/login">Back to sign in</AuthLink>}
    >
      <ForgotPasswordForm />
    </AuthCard>
  );
}
