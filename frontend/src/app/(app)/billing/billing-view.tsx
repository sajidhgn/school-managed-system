"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { UsageCard } from "@/components/billing/usage-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { ApiError } from "@/lib/api/errors";
import { billing as billingApi } from "@/lib/api/resources";
import {
  SUBSCRIPTION_STATUS_LABELS,
  label,
  type InvoiceRead,
  type PlanPublic,
  type SubscriptionRead,
  type UsageResponse,
} from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Subscription, usage and invoices.
 *
 * =============================================================================
 * A DOWNGRADE IS OFFERED PLAINLY, WITH ITS CONSEQUENCE STATED
 * =============================================================================
 *   Moving to a smaller plan never deletes anything (spec §6.2). The organization
 *   goes `over_limit`: existing records stay readable and exportable, and only new
 *   creates are refused.
 *
 *   The confirmation says exactly that, because the fear a customer has when
 *   downgrading is "will I lose my students?", and the honest answer — no — is a
 *   reason to trust the product rather than something to bury.
 *
 * Cancellation is always at period end. The customer paid through the period; ending
 * it the moment they click would bill them for time they cannot use, and the server
 * refuses an immediate cancel from self-service anyway.
 */
export function BillingView({
  subscription,
  usage,
  invoices,
  plans,
  canManage,
}: {
  subscription: SubscriptionRead | null;
  usage: UsageResponse | null;
  invoices: InvoiceRead[];
  plans: PlanPublic[];
  canManage: boolean;
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [busy, setBusy] = useState(false);
  const [changingTo, setChangingTo] = useState<PlanPublic | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const currentCode = subscription
    ? plans.find((p) => p.name === subscription.plan_name)?.code ?? subscription.plan_code
    : null;

  async function changePlan(plan: PlanPublic) {
    setBusy(true);
    try {
      await billingApi.changePlan({ plan_code: plan.code, billing_cycle: "monthly" });
      toast({ title: `You are now on ${plan.name}.` });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not change plan",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(false);
      setChangingTo(null);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      await billingApi.cancel();
      toast({
        title: "Subscription cancelled",
        description: "You keep full access until the end of the current period.",
      });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not cancel",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(false);
      setCancelling(false);
    }
  }

  // Is the target smaller than the current plan? Compares the metered limits rather
  // than the price, because a plan can be cheaper and roomier during a promotion,
  // and the warning should follow the thing that actually constrains the customer.
  function isDowngrade(target: PlanPublic): boolean {
    const current = plans.find((p) => p.code === currentCode);
    if (!current) return false;
    return (["max_schools", "max_students", "max_staff"] as const).some((key) => {
      const now = Number(current.limits?.[key] ?? 0);
      const next = Number(target.limits?.[key] ?? 0);
      if (now === -1 && next !== -1) return true;
      return next !== -1 && next < now;
    });
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <PageHeader title={t.billing.title} description={t.billing.subtitle} />

      {subscription ? (
        <section className="mb-8 rounded-xl border border-border bg-card p-5">
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-muted-foreground">{t.billing.currentPlan}</p>
              <p className="text-xl font-semibold">{subscription.plan_name}</p>
            </div>
            <Badge
              variant={
                subscription.status === "active" || subscription.status === "trialing"
                  ? "success"
                  : subscription.status === "past_due"
                    ? "warning"
                    : "destructive"
              }
            >
              {label(SUBSCRIPTION_STATUS_LABELS, subscription.status)}
            </Badge>
          </div>

          {subscription.cancel_at_period_end ? (
            <p className="mt-3 rounded-md bg-warning/15 px-3 py-2 text-sm">
              Your subscription ends
              {subscription.current_period_end
                ? ` on ${new Date(subscription.current_period_end).toLocaleDateString()}`
                : " at the end of the current period"}
              . {t.billing.keepAccessUntilThen}
            </p>
          ) : null}

          {canManage && !subscription.cancel_at_period_end ? (
            <Button
              variant="ghost"
              size="sm"
              className="mt-3 text-muted-foreground"
              onClick={() => setCancelling(true)}
            >
              {t.billing.cancelPlan}
            </Button>
          ) : null}
        </section>
      ) : null}

      {usage ? (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">{t.billing.usage}</h2>
          <UsageCard usage={usage} />
        </section>
      ) : null}

      {canManage && plans.length > 0 ? (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">{t.billing.changePlan}</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            {plans.map((plan) => {
              const isCurrent = plan.code === currentCode;
              return (
                <div
                  key={plan.id}
                  className={cn(
                    "rounded-xl border p-4",
                    isCurrent ? "border-primary bg-accent/40" : "border-border bg-card",
                  )}
                >
                  <p className="font-medium">{plan.name}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {plan.price_monthly === null
                      ? "Custom"
                      : `${plan.currency} ${plan.price_monthly}/mo`}
                  </p>
                  <Button
                    size="sm"
                    variant={isCurrent ? "outline" : "default"}
                    className="mt-3 w-full"
                    disabled={isCurrent || busy}
                    onClick={() => setChangingTo(plan)}
                  >
                    {isCurrent ? t.billing.current : t.billing.switchPlan}
                  </Button>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {invoices.length > 0 ? (
        <section>
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">{t.billing.invoices}</h2>
          <div className="rounded-xl border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Number</TableHead>
                  <TableHead>Amount</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Issued</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invoices.map((invoice) => (
                  <TableRow key={invoice.id}>
                    <TableCell className="font-medium">{invoice.number}</TableCell>
                    <TableCell className="tabular-nums">
                      {invoice.currency} {invoice.amount_total}
                    </TableCell>
                    <TableCell>
                      <Badge variant={invoice.status === "paid" ? "success" : "neutral"}>
                        {invoice.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {invoice.issued_at
                        ? new Date(invoice.issued_at).toLocaleDateString()
                        : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </section>
      ) : null}

      <ConfirmDialog
        open={changingTo !== null}
        onOpenChange={(open) => !open && setChangingTo(null)}
        title={`Switch to ${changingTo?.name}?`}
        description={
          changingTo && isDowngrade(changingTo)
            ? t.billing.downgradeBody
            : t.billing.upgradeBody
        }
        confirmLabel="Switch plan"
        variant="default"
        loading={busy}
        onConfirm={() => changingTo && changePlan(changingTo)}
      />

      <ConfirmDialog
        open={cancelling}
        onOpenChange={setCancelling}
        title={t.billing.cancelTitle}
        description={t.billing.cancelBody}
        confirmLabel={t.billing.cancelPlan}
        variant="destructive"
        loading={busy}
        onConfirm={cancel}
      />
    </div>
  );
}
