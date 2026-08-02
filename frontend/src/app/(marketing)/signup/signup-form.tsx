"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Field } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { RegisterResponse } from "@/lib/api/types";
import { signupSchema, type SignupValues } from "@/lib/validation/auth";

/**
 * Self-service signup: creates the person AND their organization in one step.
 *
 * Ends on a "check your email" state rather than signing the user in. Login is
 * blocked until the address is verified — the gate that stops signup from becoming
 * a way to send mail from our domain to arbitrary addresses.
 *
 * Server-side password rejections (breached, too guessable) are surfaced against the
 * password field rather than as a banner, because that is where the user needs to
 * act. The backend's message is shown verbatim: it explains WHY, which no generic
 * client-side copy could.
 */
export function SignupForm() {
  const { t } = useTranslations();
  const [done, setDone] = useState<RegisterResponse | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      full_name: "",
      email: "",
      organization_name: "",
      country: "",
      password: "",
      confirm_password: "",
    },
  });

  async function onSubmit(values: SignupValues) {
    setFormError(null);
    try {
      const result = await authRequest<RegisterResponse>("/register", {
        full_name: values.full_name,
        email: values.email,
        password: values.password,
        organization_name: values.organization_name,
        country: values.country || undefined,
      });
      setDone(result);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "WEAK_PASSWORD") {
          form.setError("password", { message: error.message });
          return;
        }
        if (error.code === "EMAIL_TAKEN") {
          form.setError("email", { message: error.message });
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
      <div className="grid gap-3 text-center">
        <MailCheck className="mx-auto size-10 text-success" aria-hidden />
        <h2 className="font-medium">{t.auth.checkEmail}</h2>
        <p className="text-sm text-muted-foreground text-pretty">{t.auth.verifyEmailSent}</p>
        <p className="text-sm text-muted-foreground">
          Sent to <span className="font-medium text-foreground">{done.email}</span>
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <Field
        label={t.auth.organizationName}
        htmlFor="organization_name"
        error={form.formState.errors.organization_name}
        hint="The trust, group or school company that owns your campuses."
        required
      >
        <Input autoFocus autoComplete="organization" {...form.register("organization_name")} />
      </Field>

      <Field
        label={t.auth.fullName}
        htmlFor="full_name"
        error={form.formState.errors.full_name}
        required
      >
        <Input autoComplete="name" {...form.register("full_name")} />
      </Field>

      <Field label={t.auth.email} htmlFor="email" error={form.formState.errors.email} required>
        <Input type="email" autoComplete="email" {...form.register("email")} />
      </Field>

      <Field
        label={t.auth.password}
        htmlFor="password"
        error={form.formState.errors.password}
        hint="At least 10 characters. A phrase of unrelated words works best."
        required
      >
        <Input type="password" autoComplete="new-password" {...form.register("password")} />
      </Field>

      <Field
        label="Confirm password"
        htmlFor="confirm_password"
        error={form.formState.errors.confirm_password}
        required
      >
        <Input
          type="password"
          autoComplete="new-password"
          {...form.register("confirm_password")}
        />
      </Field>

      {formError ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {formError}
        </p>
      ) : null}

      <Button type="submit" disabled={form.formState.isSubmitting}>
        {form.formState.isSubmitting ? t.common.loading : t.common.signUp}
      </Button>
    </form>
  );
}
