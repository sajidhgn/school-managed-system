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
import { resetPasswordSchema, type ResetPasswordValues } from "@/lib/validation/auth";

export function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [formError, setFormError] = React.useState<string | null>(null);

  const form = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: {
      email: searchParams.get("email") ?? "",
      code: "",
      new_password: "",
      confirm_password: "",
    },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      // confirm_password is a client-side guard only — the backend takes the
      // three fields below.
      await api.post("/auth/reset-password", {
        email: values.email,
        code: values.code,
        new_password: values.new_password,
      });
      toast.success("Password reset", "Sign in with your new password.");
      router.push("/login");
    } catch (error) {
      setFormError(errorMessage(error));
    }
  });

  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <h1 className="text-xl font-semibold tracking-tight">Set a new password</h1>
        <p className="text-sm text-muted-foreground">
          Enter the code we emailed you, then choose a new password.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError message={formError} />

        <Field label="Email" htmlFor="email" error={form.formState.errors.email} required>
          <Input type="email" autoComplete="email" {...form.register("email")} />
        </Field>

        <Field label="Reset code" htmlFor="code" error={form.formState.errors.code} required>
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            placeholder="123456"
            className="text-center text-lg tracking-[0.4em]"
            {...form.register("code")}
          />
        </Field>

        <Field
          label="New password"
          htmlFor="new_password"
          error={form.formState.errors.new_password}
          hint="At least 8 characters."
          required
        >
          <Input type="password" autoComplete="new-password" {...form.register("new_password")} />
        </Field>

        <Field
          label="Confirm new password"
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

        <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
          Reset password
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
