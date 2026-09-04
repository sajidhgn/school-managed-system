"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { PasswordInput } from "@/components/ui/password-input";

import { ApiError, toProblem } from "@/lib/api/errors";
import { platformLoginSchema, type PlatformLoginValues } from "@/lib/validation/auth";

export function PlatformLoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const form = useForm<PlatformLoginValues>({
    resolver: zodResolver(platformLoginSchema),
    defaultValues: { email: "", password: "", totp_code: "" },
  });

  async function onSubmit(values: PlatformLoginValues) {
    setError(null);
    try {
      const response = await fetch("/api/platform/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          email: values.email,
          password: values.password,
          // OMITTED when blank, never sent as "". `PlatformLoginRequest.totp_code`
          // is constrained to `^\d{6}$` when the key is PRESENT, so an empty string
          // is a 422 before authentication is even attempted -- which made signing
          // in impossible for an operator who has not enrolled MFA, the exact state
          // the seed CLI leaves a fresh account in.
          ...(values.totp_code ? { totp_code: values.totp_code } : {}),
        }),
      });
      if (!response.ok) throw new ApiError(await toProblem(response));

      // Push before refresh so the destination renders with the fresh session;
      // a refresh issued before the push is superseded by it.
      router.push("/platform/organizations");
      router.refresh();
    } catch (err) {
      // The backend returns one indistinguishable error for unknown account, wrong
      // password and locked account — same reasoning as tenant login. Whatever it
      // says is shown verbatim rather than being reinterpreted here.
      setError(err instanceof ApiError ? err.message : "Sign in failed.");
    }
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <div className="grid gap-1.5">
        <label htmlFor="email" className="text-sm font-medium text-slate-300">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          autoFocus
          className="h-9 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-slate-500"
          {...form.register("email")}
        />
        {form.formState.errors.email ? (
          <p className="text-xs text-red-400">{form.formState.errors.email.message}</p>
        ) : null}
      </div>

      <div className="grid gap-1.5">
        <label htmlFor="totp_code" className="text-sm font-medium text-slate-300">
          Authentication code
        </label>
        <input
          id="totp_code"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          placeholder="123456"
          className="h-9 rounded-md border border-slate-700 bg-slate-950 px-3 font-mono text-sm tracking-widest text-slate-100 outline-none focus:ring-2 focus:ring-slate-500"
          {...form.register("totp_code")}
        />
        {form.formState.errors.totp_code ? (
          <p className="text-xs text-red-400">{form.formState.errors.totp_code.message}</p>
        ) : null}
      </div>

      <div className="grid gap-1.5">
        <label htmlFor="password" className="text-sm font-medium text-slate-300">
          Password
        </label>
        <PasswordInput
          id="password"
          autoComplete="current-password"
          className="h-9 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 shadow-none focus-visible:ring-slate-500 focus-visible:ring-offset-0"
          toggleClassName="text-slate-400 hover:text-slate-100 focus-visible:ring-slate-500"
          {...form.register("password")}
        />
        {form.formState.errors.password ? (
          <p className="text-xs text-red-400">{form.formState.errors.password.message}</p>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-red-950/60 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={form.formState.isSubmitting}
        className="h-9 rounded-md bg-slate-100 text-sm font-medium text-slate-950 transition-colors hover:bg-white disabled:opacity-60"
      >
        {form.formState.isSubmitting ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
