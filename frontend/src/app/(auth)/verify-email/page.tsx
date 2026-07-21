import type { Metadata } from "next";
import { Suspense } from "react";

import { VerifyEmailForm } from "./verify-email-form";

export const metadata: Metadata = { title: "Verify email" };

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailForm />
    </Suspense>
  );
}
