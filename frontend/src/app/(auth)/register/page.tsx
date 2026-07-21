"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Field, FormError } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/misc";
import { authRequest } from "@/lib/api/client";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { registerSchema, type RegisterValues } from "@/lib/validation/auth";
import type { RegisterResponse } from "@/lib/api/types";

/**
 * Self-service school registration.
 *
 * Creates the tenant and its first school_admin in one call. The school lands
 * in `pending_approval` and the admin in `pending_verification`, so success
 * routes to email verification — not to the dashboard.
 */
export default function RegisterPage() {
  const router = useRouter();
  const [formError, setFormError] = React.useState<string | null>(null);

  const form = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      school_name: "",
      school_email: "",
      school_phone: "",
      full_name: "",
      email: "",
      password: "",
      confirm_password: "",
    },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await authRequest<RegisterResponse>("/register", {
        school_name: values.school_name,
        school_email: values.school_email,
        school_phone: values.school_phone || null,
        full_name: values.full_name,
        email: values.email,
        password: values.password,
      });
      router.push(`/verify-email?email=${encodeURIComponent(values.email)}`);
    } catch (error) {
      if (error instanceof ApiError) {
        // Surface per-field problems (duplicate email, weak password) on the
        // field itself rather than in a generic banner.
        const fields = error.fieldErrors();
        let matched = false;
        for (const [name, message] of Object.entries(fields)) {
          if (name in values) {
            form.setError(name as keyof RegisterValues, { message });
            matched = true;
          }
        }
        if (matched) return;
      }
      setFormError(errorMessage(error));
    }
  });

  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <h1 className="text-xl font-semibold tracking-tight">Register your school</h1>
        <p className="text-sm text-muted-foreground">
          Creates your school and your administrator account.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        <FormError message={formError} />

        <fieldset className="space-y-4">
          <legend className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            School
          </legend>

          <Field
            label="School name"
            htmlFor="school_name"
            error={form.formState.errors.school_name}
            required
          >
            <Input autoFocus placeholder="Green Valley High School" {...form.register("school_name")} />
          </Field>

          <Field
            label="School email"
            htmlFor="school_email"
            error={form.formState.errors.school_email}
            required
          >
            <Input type="email" placeholder="office@school.edu" {...form.register("school_email")} />
          </Field>

          <Field label="School phone" htmlFor="school_phone" error={form.formState.errors.school_phone}>
            <Input type="tel" placeholder="Optional" {...form.register("school_phone")} />
          </Field>
        </fieldset>

        <Separator />

        <fieldset className="space-y-4">
          <legend className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Administrator
          </legend>

          <Field
            label="Full name"
            htmlFor="full_name"
            error={form.formState.errors.full_name}
            required
          >
            <Input autoComplete="name" {...form.register("full_name")} />
          </Field>

          <Field label="Email" htmlFor="email" error={form.formState.errors.email} required>
            <Input type="email" autoComplete="email" {...form.register("email")} />
          </Field>

          <Field
            label="Password"
            htmlFor="password"
            error={form.formState.errors.password}
            hint="At least 8 characters."
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
        </fieldset>

        <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
          Create account
        </Button>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        Already registered?{" "}
        <Link href="/login" className="font-medium text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
