"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Field } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/ui/password-input";
import { publicRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { resetPasswordSchema, type ResetPasswordValues } from "@/lib/validation/auth";

/**
 * Set a new password from an emailed link.
 *
 * The reset also revokes every existing session, which the success copy states
 * plainly — a user who was signed in on their phone needs to know why it logged them
 * out, or they will assume something broke.
 *
 * That revocation is not incidental: the usual reason for resetting is a belief the
 * password was compromised, and a reset that leaves the attacker's session alive
 * accomplishes nothing.
 */
export function ResetPasswordForm({ token }: { token: string }) {
  const { t } = useTranslations();
  const [done, setDone] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { token, password: "", confirm_password: "" },
  });

  async function onSubmit(values: ResetPasswordValues) {
    setFormError(null);
    try {
      await publicRequest("/reset-password", {
        token: values.token,
        password: values.password,
      });
      setDone(true);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "WEAK_PASSWORD") {
          form.setError("password", { message: error.message });
          return;
        }
        setFormError(error.message);
        return;
      }
      setFormError(t.errors.generic);
    }
  }

  if (done) {
    return (
      <div className="grid gap-4 text-center">
        <CheckCircle2 className="mx-auto size-10 text-success" aria-hidden />
        <p className="text-sm text-muted-foreground text-pretty">
          Your password is updated, and you have been signed out everywhere else.
        </p>
        <Button asChild>
          <Link href="/login">{t.common.signIn}</Link>
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <input type="hidden" {...form.register("token")} />

      <Field
        label="New password"
        htmlFor="password"
        error={form.formState.errors.password}
        hint="At least 10 characters. A phrase of unrelated words works best."
        required
      >
        <PasswordInput autoComplete="new-password" autoFocus {...form.register("password")} />
      </Field>

      <Field
        label="Confirm password"
        htmlFor="confirm_password"
        error={form.formState.errors.confirm_password}
        required
      >
        <PasswordInput autoComplete="new-password" {...form.register("confirm_password")} />
      </Field>

      {formError ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {formError}
        </p>
      ) : null}

      <Button type="submit" disabled={form.formState.isSubmitting}>
        {form.formState.isSubmitting ? t.common.loading : "Update password"}
      </Button>
    </form>
  );
}
