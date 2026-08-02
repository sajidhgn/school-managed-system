import type { Metadata } from "next";
import Link from "next/link";
import { CheckCircle2, XCircle } from "lucide-react";

import { AuthCard } from "@/components/auth/auth-card";
import { Button } from "@/components/ui/button";
import { API_BASE_URL, API_V1_PREFIX } from "@/lib/api/config";

export const metadata: Metadata = { title: "Verify your email" };

/**
 * Email verification — a link target, not a form.
 *
 * The token arrives in the URL and is consumed on the server during render, so the
 * user sees a result immediately rather than a page with a button they have to
 * press to complete something they already asked for by clicking the email.
 *
 * NOT a client component posting on mount: that would flash an empty page, and a
 * double-invoked effect in React strict mode would consume the single-use token
 * twice — the second attempt failing, and the user seeing an error for a
 * verification that actually succeeded.
 */
export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;

  let ok = false;
  let message = "This verification link is invalid or has expired.";

  if (token) {
    const response = await fetch(`${API_BASE_URL}${API_V1_PREFIX}/auth/verify-email`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
      cache: "no-store",
    });
    ok = response.ok;
    if (ok) {
      message = "Your email is verified. You can sign in now.";
    } else {
      const problem = await response.json().catch(() => null);
      message = problem?.detail ?? message;
    }
  }

  return (
    <AuthCard title={ok ? "Email verified" : "Verification failed"}>
      <div className="grid gap-4 text-center">
        {ok ? (
          <CheckCircle2 className="mx-auto size-10 text-success" aria-hidden />
        ) : (
          <XCircle className="mx-auto size-10 text-destructive" aria-hidden />
        )}
        <p className="text-sm text-muted-foreground text-pretty">{message}</p>
        <Button asChild>
          <Link href="/login">Continue to sign in</Link>
        </Button>
      </div>
    </AuthCard>
  );
}
