"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { AuthLink } from "@/components/auth/auth-card";
import { ContextPicker } from "@/components/auth/context-picker";
import { useTranslations } from "@/components/providers/i18n-provider";
import { Field } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { authRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { LoginResponse } from "@/lib/api/types";
import { loginSchema, type LoginValues } from "@/lib/validation/auth";

/**
 * Sign-in form.
 *
 * =============================================================================
 * A SUCCESSFUL LOGIN DOES NOT ALWAYS MEAN "SIGNED IN"
 * =============================================================================
 *   A user with several memberships — a teacher at two schools, or someone who is a
 *   principal at one organization and staff at another — gets `select_required: true`
 *   and no session yet. That is not an error and must not look like one: they have
 *   not done anything wrong, they simply have not said which hat they are wearing.
 *
 *   Guessing on their behalf would drop them into the wrong school's data, so the
 *   form swaps to a context picker instead. The picker calls `/api/auth/context`,
 *   which is what actually mints the session.
 */
export function LoginForm() {
  const { t } = useTranslations();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState<LoginResponse | null>(null);

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  // Only same-origin paths are honoured. An absolute URL here would turn the login
  // page into an open redirect — a phishing primitive, since the destination looks
  // legitimate right up until the browser leaves.
  const raw = searchParams.get("next");
  const next = raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/dashboard";

  async function onSubmit(values: LoginValues) {
    setFormError(null);
    try {
      const result = await authRequest<LoginResponse>("/login", values);

      if (result.select_required) {
        setPending(result);
        return;
      }

      // `router.refresh()` before navigating: the session cookie was just written by
      // the route handler, and without a refresh the app-group layout would still
      // render from the cached signed-out RSC payload.
      router.refresh();
      // Cast: `next` is a runtime value, so `typedRoutes` cannot verify it.
      // It is validated as a same-origin path above, which is the check that
      // actually matters — an unvalidated redirect target here would be an open
      // redirect, and no type could catch that anyway.
      router.push(next as Route);
    } catch (error) {
      setFormError(
        error instanceof ApiError ? error.message : t.errors.generic,
      );
    }
  }

  if (pending) {
    return <ContextPicker memberships={pending.memberships} redirectTo={next} />;
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <Field label={t.auth.email} htmlFor="email" error={form.formState.errors.email} required>
        <Input
          type="email"
          autoComplete="email"
          autoFocus
          {...form.register("email")}
        />
      </Field>

      <Field
        label={t.auth.password}
        htmlFor="password"
        error={form.formState.errors.password}
        required
      >
        <PasswordInput autoComplete="current-password" {...form.register("password")} />
      </Field>

      {formError ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {formError}
        </p>
      ) : null}

      <Button type="submit" disabled={form.formState.isSubmitting}>
        {form.formState.isSubmitting ? t.common.loading : t.common.signIn}
      </Button>

      <p className="text-center text-sm">
        <AuthLink href="/forgot-password">{t.auth.forgotPassword}</AuthLink>
      </p>
    </form>
  );
}
