"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Field } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { publicRequest } from "@/lib/api/client";
import { forgotPasswordSchema, type ForgotPasswordValues } from "@/lib/validation/auth";

/**
 * Request a password-reset link.
 *
 * =============================================================================
 * THE SUCCESS STATE IS SHOWN EVEN WHEN THE ADDRESS DOES NOT EXIST
 * =============================================================================
 *   The backend deliberately returns an identical response either way, so this
 *   endpoint cannot be used to test which addresses are registered. Rendering a
 *   different UI for "no such account" would leak exactly what the API took care to
 *   hide — and for a school platform, that means revealing which schools are
 *   customers.
 *
 *   So: one message, always. The wording is careful to be true in both cases.
 */
export function ForgotPasswordForm() {
  const { t } = useTranslations();
  const [hydrated, setHydrated] = useState(false);
  const [sent, setSent] = useState(false);

  // Before hydration, a server-rendered form has no React submit handler. Keeping
  // the button disabled prevents a fast click from falling back to a native GET and
  // putting the email address in the URL instead of using the fixed public handler.
  useEffect(() => setHydrated(true), []);

  const form = useForm<ForgotPasswordValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  });

  async function onSubmit(values: ForgotPasswordValues) {
    // Even a transport failure resolves to the same state: distinguishing them
    // would reintroduce the oracle by a side door.
    await publicRequest("/forgot-password", values).catch(() => undefined);
    setSent(true);
  }

  if (sent) {
    return (
      <div className="grid gap-3 text-center">
        <MailCheck className="mx-auto size-10 text-success" aria-hidden />
        <p className="text-sm text-muted-foreground text-pretty">{t.auth.resetSent}</p>
      </div>
    );
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <Field label={t.auth.email} htmlFor="email" error={form.formState.errors.email} required>
        <Input type="email" autoComplete="email" autoFocus {...form.register("email")} />
      </Field>
      <Button type="submit" disabled={!hydrated || form.formState.isSubmitting}>
        {form.formState.isSubmitting ? t.common.loading : "Send reset link"}
      </Button>
    </form>
  );
}
