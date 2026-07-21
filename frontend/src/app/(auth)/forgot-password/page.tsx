"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { MailCheck } from "lucide-react";

import { Field, FormError } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { forgotPasswordSchema, type ForgotPasswordValues } from "@/lib/validation/auth";

/**
 * Request a password reset code.
 *
 * Always shows the same confirmation regardless of whether the account exists —
 * the backend responds identically by design, and the UI must not leak the
 * difference either.
 */
export default function ForgotPasswordPage() {
  const router = useRouter();
  const [sent, setSent] = React.useState<string | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);

  const form = useForm<ForgotPasswordValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.post("/auth/forgot-password", values);
      setSent(values.email);
    } catch (error) {
      setFormError(errorMessage(error));
    }
  });

  if (sent) {
    return (
      <div className="space-y-6 text-center">
        <div className="mx-auto flex size-11 items-center justify-center rounded-full bg-success/12">
          <MailCheck className="size-5 text-success" />
        </div>
        <div className="space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">Check your email</h1>
          <p className="text-sm text-muted-foreground">
            If an account exists for <span className="font-medium text-foreground">{sent}</span>,
            we've sent a reset code.
          </p>
        </div>
        <Button
          className="w-full"
          onClick={() => router.push(`/reset-password?email=${encodeURIComponent(sent)}`)}
        >
          Enter reset code
        </Button>
        <Link href="/login" className="block text-sm text-muted-foreground hover:underline">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <h1 className="text-xl font-semibold tracking-tight">Forgot password</h1>
        <p className="text-sm text-muted-foreground">
          We'll email you a code to reset your password.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError message={formError} />

        <Field label="Email" htmlFor="email" error={form.formState.errors.email} required>
          <Input type="email" autoComplete="email" autoFocus {...form.register("email")} />
        </Field>

        <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
          Send reset code
        </Button>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        <Link href="/login" className="font-medium text-primary hover:underline">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}
