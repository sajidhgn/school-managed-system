import type { Metadata } from "next";
import { MailX } from "lucide-react";

import { AcceptInviteForm } from "./accept-form";
import { AuthCard, AuthLink } from "@/components/auth/auth-card";
import { API_BASE_URL, API_V1_PREFIX } from "@/lib/api/config";
import type { InvitationPreview } from "@/lib/api/types";
import { getCurrentUser } from "@/lib/auth/session";
import { getTranslations } from "@/lib/i18n/server";

export const metadata: Metadata = { title: "Accept your invitation" };

/**
 * Invitation landing page (spec §7.2).
 *
 * =============================================================================
 * THE PREVIEW IS FETCHED BEFORE ANYTHING IS ASKED OF THE USER
 * =============================================================================
 *   `GET /invitations/verify` returns the school, the role and the invited address
 *   — and nothing else, to a caller who has proven nothing beyond receiving an
 *   email. Showing that up front lets the recipient judge whether the invitation is
 *   legitimate WITHOUT clicking through to find out, which is exactly what every
 *   phishing-awareness training asks for and most invitation emails make impossible.
 *
 *   It also lets the page render the right form: a full signup for someone new, or a
 *   sign-in prompt for an address that already has an account.
 *
 * An expired, revoked or already-used invitation returns 410 and gets a dead end
 * with a next step, rather than a form that will fail on submit.
 */
export default async function AcceptInvitePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  const t = await getTranslations();

  if (!token) {
    return (
      <AuthCard title={t.invite.expired} description={t.invite.expiredHint}>
        <MailX className="mx-auto size-10 text-muted-foreground" aria-hidden />
      </AuthCard>
    );
  }

  const response = await fetch(
    `${API_BASE_URL}${API_V1_PREFIX}/invitations/verify?token=${encodeURIComponent(token)}`,
    { cache: "no-store" },
  );

  if (!response.ok) {
    return (
      <AuthCard
        title={t.invite.expired}
        description={t.invite.expiredHint}
        footer={<AuthLink href="/login">{t.common.signIn}</AuthLink>}
      >
        <MailX className="mx-auto size-10 text-muted-foreground" aria-hidden />
      </AuthCard>
    );
  }

  const invitation: InvitationPreview = await response.json();

  // Whether the visitor is already signed in, and as whom. The backend enforces that
  // an authenticated accepter's email matches the invited address exactly — this
  // read exists so the UI can SAY so before they submit, rather than letting them
  // fill in a form that will be refused.
  const user = await getCurrentUser();
  const signedInAsSomeoneElse =
    user !== null && user.email.toLowerCase() !== invitation.email.toLowerCase();

  return (
    <AuthCard
      title={t.invite.title}
      description={
        invitation.inviter_name
          ? `${invitation.inviter_name} invited you to join ${invitation.school_name ?? "their organization"}.`
          : `You have been invited to join ${invitation.school_name ?? "an organization"}.`
      }
    >
      <dl className="mb-6 grid gap-2 rounded-lg bg-muted/60 p-4 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">School</dt>
          <dd className="font-medium">{invitation.school_name ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">{t.invite.joinAs}</dt>
          <dd className="font-medium">{invitation.role_name ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Email</dt>
          <dd className="font-medium">{invitation.email}</dd>
        </div>
      </dl>

      <AcceptInviteForm
        token={token}
        invitation={invitation}
        requiresSignup={invitation.requires_signup}
        signedInAsSomeoneElse={signedInAsSomeoneElse}
        signedInAs={user?.email ?? null}
      />
    </AuthCard>
  );
}
