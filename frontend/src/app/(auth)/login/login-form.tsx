"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Field, FormError } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authRequest } from "@/lib/api/client";
import { ApiError, errorMessage } from "@/lib/api/errors";
import {
  loginSchema,
  verify2faSchema,
  type LoginValues,
  type Verify2faValues,
} from "@/lib/validation/auth";

/**
 * Sign-in, including the two-factor branch.
 *
 * The backend's /auth/login returns `requires_2fa` instead of tokens when the
 * account has 2FA enabled, so this component owns a small two-step state
 * machine rather than assuming success means "signed in".
 */
export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next");

  const [challengeEmail, setChallengeEmail] = React.useState<string | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);

  function onAuthenticated() {
    // `next` is attacker-controllable, so only same-origin absolute paths are
    // honoured — `//evil.com` and `https://evil.com` would both be open
    // redirects. The cast is unavoidable: a runtime string cannot be proven to
    // be a known route at compile time.
    const safeNext =
      nextPath && nextPath.startsWith("/") && !nextPath.startsWith("//")
        ? (nextPath as Route)
        : ("/dashboard" as Route);

    // `replace` so Back doesn't return to the login form on a live session.
    router.replace(safeNext);
    router.refresh();
  }

  if (challengeEmail) {
    return (
      <TwoFactorStep
        email={challengeEmail}
        onBack={() => setChallengeEmail(null)}
        onVerified={onAuthenticated}
      />
    );
  }

  return (
    <CredentialsStep
      formError={formError}
      setFormError={setFormError}
      onChallenge={setChallengeEmail}
      onAuthenticated={onAuthenticated}
    />
  );
}

function CredentialsStep({
  formError,
  setFormError,
  onChallenge,
  onAuthenticated,
}: {
  formError: string | null;
  setFormError: (message: string | null) => void;
  onChallenge: (email: string) => void;
  onAuthenticated: () => void;
}) {
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      const result = await authRequest<{ requires_2fa: boolean }>("/login", values);
      if (result.requires_2fa) {
        onChallenge(values.email);
        return;
      }
      onAuthenticated();
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        // Unverified accounts can't sign in — send them where they can fix it.
        setFormError(`${error.message} Check your inbox, or verify your email below.`);
        return;
      }
      setFormError(errorMessage(error));
    }
  });

  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <h1 className="text-xl font-semibold tracking-tight">Sign in</h1>
        <p className="text-sm text-muted-foreground">
          Enter your credentials to access your school.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError message={formError} />

        <Field label="Email" htmlFor="email" error={form.formState.errors.email} required>
          <Input
            type="email"
            autoComplete="email"
            autoFocus
            placeholder="you@school.edu"
            {...form.register("email")}
          />
        </Field>

        <Field label="Password" htmlFor="password" error={form.formState.errors.password} required>
          <Input type="password" autoComplete="current-password" {...form.register("password")} />
        </Field>

        <div className="flex justify-end">
          <Link
            href="/forgot-password"
            className="text-xs font-medium text-primary hover:underline"
          >
            Forgot password?
          </Link>
        </div>

        <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>
          Sign in
        </Button>
      </form>

      <div className="space-y-2 text-center text-sm text-muted-foreground">
        <p>
          Don't have an account?{" "}
          <Link href="/register" className="font-medium text-primary hover:underline">
            Register your school
          </Link>
        </p>
        <p>
          <Link href="/verify-email" className="text-xs hover:underline">
            Need to verify your email?
          </Link>
        </p>
      </div>
    </div>
  );
}

function TwoFactorStep({
  email,
  onBack,
  onVerified,
}: {
  email: string;
  onBack: () => void;
  onVerified: () => void;
}) {
  const [formError, setFormError] = React.useState<string | null>(null);

  const form = useForm<Verify2faValues>({
    resolver: zodResolver(verify2faSchema),
    defaultValues: { email, code: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await authRequest("/verify-2fa", values);
      onVerified();
    } catch (error) {
      setFormError(errorMessage(error));
    }
  });

  return (
    <div className="space-y-6">
      <header className="space-y-1.5">
        <h1 className="text-xl font-semibold tracking-tight">Two-factor verification</h1>
        <p className="text-sm text-muted-foreground">
          We sent a code to <span className="font-medium text-foreground">{email}</span>.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <FormError message={formError} />

        <Field
          label="Verification code"
          htmlFor="code"
          error={form.formState.errors.code}
          required
        >
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
          Verify and sign in
        </Button>

        <Button type="button" variant="ghost" className="w-full" onClick={onBack}>
          Use a different account
        </Button>
      </form>
    </div>
  );
}
