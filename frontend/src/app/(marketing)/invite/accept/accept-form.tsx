"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Field } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { authRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { InvitationAcceptResponse, InvitationPreview } from "@/lib/api/types";
import { acceptInviteSchema, type AcceptInviteValues } from "@/lib/validation/auth";

/**
 * Accept an invitation. Three states, matching spec §7.2's branches plus one guard.
 *
 *   1. NEW USER      — no account for the invited address. Collect a name and
 *                      password; the backend creates the account already verified,
 *                      because receiving the invitation email IS proof of inbox
 *                      control. Asking them to verify a second time would be asking
 *                      them to prove twice what they just proved once.
 *
 *   2. EXISTING USER — an account exists and they are signed in as it. One button;
 *                      nothing to collect.
 *
 *   3. WRONG ACCOUNT — signed in as somebody else. The server refuses this
 *                      (INVITATION_EMAIL_MISMATCH) and so does the UI, up front. It
 *                      is a real attack: forward an invite to a colleague, or find
 *                      one, and join an organization that never invited you.
 */
export function AcceptInviteForm({
  token,
  invitation,
  requiresSignup,
  signedInAsSomeoneElse,
  signedInAs,
}: {
  token: string;
  invitation: InvitationPreview;
  requiresSignup: boolean;
  signedInAsSomeoneElse: boolean;
  signedInAs: string | null;
}) {
  const { t } = useTranslations();
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<AcceptInviteValues>({
    resolver: zodResolver(acceptInviteSchema),
    defaultValues: { token, full_name: "", password: "", confirm_password: "" },
  });

  async function onSubmit(values: AcceptInviteValues) {
    setFormError(null);
    try {
      const result = await authRequest<InvitationAcceptResponse>("/accept-invite", {
        token: values.token,
        // Omitted entirely for the existing-user branch. Sending empty strings would
        // trip the backend's "provide both or neither" validator.
        ...(requiresSignup
          ? { full_name: values.full_name, password: values.password }
          : {}),
      });

      router.refresh();
      router.push(result.school_id ? "/dashboard" : "/onboarding");
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

  // --- 3. Wrong account ---------------------------------------------------
  if (signedInAsSomeoneElse) {
    return (
      <div className="grid gap-4">
        <p className="rounded-md bg-warning/15 px-3 py-2 text-sm">
          This invitation was sent to{" "}
          <span className="font-medium">{invitation.email}</span>, but you are signed in as{" "}
          <span className="font-medium">{signedInAs}</span>. Sign out and sign back in as the
          invited address to accept it.
        </p>
        <Button asChild variant="outline">
          <Link href="/login">Sign in as {invitation.email}</Link>
        </Button>
      </div>
    );
  }

  // --- 2. Existing user, already signed in --------------------------------
  if (!requiresSignup) {
    return (
      <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
        {signedInAs ? (
          <p className="text-sm text-muted-foreground">
            Accepting as <span className="font-medium text-foreground">{signedInAs}</span>.
          </p>
        ) : (
          <p className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
            You already have an account for this address. Sign in to accept.
          </p>
        )}

        {formError ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {formError}
          </p>
        ) : null}

        {signedInAs ? (
          <Button type="submit" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? t.common.loading : t.invite.acceptCta}
          </Button>
        ) : (
          <Button asChild>
            <Link href={`/login?next=/invite/accept?token=${encodeURIComponent(token)}`}>
              {t.invite.signInToAccept}
            </Link>
          </Button>
        )}
      </form>
    );
  }

  // --- 1. New user --------------------------------------------------------
  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <p className="text-sm text-muted-foreground">{t.invite.createAccount}</p>

      <Field
        label={t.auth.fullName}
        htmlFor="full_name"
        error={form.formState.errors.full_name}
        required
      >
        <Input autoFocus autoComplete="name" {...form.register("full_name")} />
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
        {form.formState.isSubmitting ? t.common.loading : t.invite.acceptCta}
      </Button>
    </form>
  );
}
