"use client";

import { AlertTriangle, Clock, CreditCard, Lock } from "lucide-react";
import Link from "next/link";

import { useTranslations } from "@/components/providers/i18n-provider";
import { cn, formatDate } from "@/lib/utils";

/**
 * Subscription-state banner.
 *
 * =============================================================================
 * WHY THIS IS IN THE SHELL AND NOT ON THE BILLING PAGE
 * =============================================================================
 *   A user hits the CONSEQUENCE somewhere else entirely: a 402 when adding a
 *   student, a create button that fails, a read-only form. Explaining it only on the
 *   billing page means they meet the symptom with no cause in sight, and the obvious
 *   conclusion is that the software is broken.
 *
 *   Persistent, above the content, on every page — which is exactly what spec §6.3
 *   asks for with "persistent in-app banner".
 *
 * The three states say different things on purpose:
 *   over_limit — nothing is lost, new creates are paused
 *   past_due   — full access continues during the grace window
 *   suspended  — read-only, and exports still work
 *
 * An expired trial is a fourth, sharper case of `suspended`: the same read-only
 * access, but with a deadline -- the account is deleted on `scheduledDeletionAt`
 * unless a plan is chosen -- so it names the date and points straight at upgrading.
 *
 * All of them take care to state what STILL WORKS. A billing banner that only says
 * what is broken reads as a threat, and the underlying policy is deliberately not
 * one: spec §6.3 refuses to lock a school out of its own student records.
 */
export function OrganizationBanner({
  status,
  trialExpired = false,
  scheduledDeletionAt = null,
}: {
  status: string | null | undefined;
  trialExpired?: boolean;
  scheduledDeletionAt?: string | null;
}) {
  const { t } = useTranslations();

  if (!status || status === "active" || status === "trialing") return null;

  if (status === "suspended" && trialExpired) {
    return (
      <div
        role="alert"
        className="flex flex-col gap-3 border-b border-border bg-destructive/12 px-4 py-3 text-destructive sm:flex-row sm:items-center sm:px-6"
      >
        <div className="flex min-w-0 flex-1 items-start gap-3 text-sm">
          <Clock className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium">{t.billing.trialExpiredTitle}</p>
            <p className="text-pretty opacity-90">
              {t.billing.trialExpiredBody}{" "}
              <strong className="font-semibold">{formatDate(scheduledDeletionAt)}</strong>.
            </p>
          </div>
        </div>
        <Link
          href="/billing"
          className="shrink-0 self-start rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90 sm:self-center"
        >
          {t.billing.upgradePlan}
        </Link>
      </div>
    );
  }

  const config = {
    over_limit: {
      icon: AlertTriangle,
      tone: "bg-warning/15 text-warning-foreground",
      title: t.billing.overLimitTitle,
      body: t.billing.overLimitBody,
      cta: t.billing.changePlan,
    },
    past_due: {
      icon: CreditCard,
      tone: "bg-warning/15 text-warning-foreground",
      title: t.billing.pastDueTitle,
      body: t.billing.pastDueBody,
      cta: t.nav.billing,
    },
    suspended: {
      icon: Lock,
      tone: "bg-destructive/12 text-destructive",
      title: t.billing.suspendedTitle,
      body: t.billing.suspendedBody,
      cta: t.nav.billing,
    },
    cancelled: {
      icon: Lock,
      tone: "bg-destructive/12 text-destructive",
      title: t.billing.cancelledTitle,
      body: t.billing.cancelledBody,
      cta: t.billing.changePlan,
    },
  }[status];

  if (!config) return null;

  const { icon: Icon, tone, title, body, cta } = config;

  return (
    <div className={cn("flex items-start gap-3 border-b border-border px-4 py-3 sm:px-6", tone)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium">{title}</p>
        <p className="text-pretty opacity-90">{body}</p>
      </div>
      <Link
        href="/billing"
        className="shrink-0 self-center rounded-md border border-current/30 px-3 py-1.5 text-xs font-medium hover:bg-current/10"
      >
        {cta}
      </Link>
    </div>
  );
}
