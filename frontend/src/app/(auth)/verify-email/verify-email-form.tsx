"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Field, FormError } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/use-toast";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { verifyEmailSchema, type VerifyEmailValues } from "@/lib/validation/auth";

/**
 * Email verification.
 *
 * The email is prefilled from the `?email=` param that /register redirects
 * with, but stays editable so a user arriving cold can still verify.
 */
export function VerifyEmailForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [formError, setFormError] = React.useState<string | null>(null);
  const [resending, setResending] = React.useState(false);

  const form = useForm<VerifyEmailValues>({
    resolver: zodResolver(verifyEmailSchema),
    defaultValues: { email: searchParams.get("email") ?? "", code: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.post("/auth/verify-email", values);
      toast.success("Email verified", "You can sign in now.");
      router.push("/login");
    } catch (error) {
      setFormError(errorMessage(error));
    }
  });

  async function resend() {
    const email = form.getValues("email");
    if (!email) {
      form.setError("email", { message: "Enter your email first" });
      return;
    }
    setResending(true);
    try {
      await api.post("/auth/resend-verification", { email });
      toast.success("Code sent", "Check your inbox for a new code.");
    } catch (error) {
      toast.error("Couldn't resend", errorMessage(error));
    } finally {
      setResending(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <h1 className="text-xl font-semibold tracking-tight">Verify your email</h1>
        <p className="text-sm text-muted-foreground">
          Enter the code we emailed you to activate your account.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError message={formError} />

        <Field label="Email" htmlFor="email" error={form.formState.errors.email} required>
          <Input type="email" autoComplete="email" {...form.register("email")} />
        </Field>

        <Field label="Verification code" htmlFor="code" error={form.formState.errors.code} required>
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            placeholder="123456"
            className="text-center text-lg tracking-[0.4em]"
            {...form.register("code")}
          />
        </Field>

        <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
          Verify email
        </Button>

        <Button
          type="button"
          variant="ghost"
          className="w-full"
          onClick={resend}
          loading={resending}
        >
          Resend code
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
