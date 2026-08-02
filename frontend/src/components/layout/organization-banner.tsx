"use client";

import { AlertTriangle, CreditCard, Lock } from "lucide-react";
import Link from "next/link";

import { useTranslations } from "@/components/providers/i18n-provider";
import { cn } from "@/lib/utils";

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
 * All three take care to state what STILL WORKS. A billing banner that only says
 * what is broken reads as a threat, and the underlying policy is deliberately not
 * one: spec §6.3 refuses to lock a school out of its own student records.
 */
export function OrganizationBanner({ status }: { status: string | null | undefined }) {
  const { t } = useTranslations();

  if (!status || status === "active" || status === "trialing") return null;

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
      title: "This subscription has been cancelled",
      body: "Your records remain available for export. Resubscribe to restore full access.",
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
