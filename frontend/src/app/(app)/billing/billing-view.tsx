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
  label,
  type InvoiceRead,
  type BillingCycle,
  type PlanPublic,
  type SubscriptionRead,
  type UsageResponse,
} from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { adminMessages } from "@/lib/i18n/modules/admin";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { useLabels } from "@/lib/i18n/use-labels";
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
  const { billing: m, usage: usageText } = useCatalog(adminMessages);
  const L = useLabels();
  const [busy, setBusy] = useState(false);
  const [changingTo, setChangingTo] = useState<PlanPublic | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [billingCycle, setBillingCycle] = useState<BillingCycle>(
    subscription?.billing_cycle === "yearly" ? "yearly" : "monthly",
  );

  const currentCode = subscription
    ? plans.find((p) => p.name === subscription.plan_name)?.code ?? subscription.plan_code
    : null;

  async function changePlan(plan: PlanPublic) {
    setBusy(true);
    try {
      const request = { plan_code: plan.code, billing_cycle: billingCycle };
      if (!subscription || subscription.plan_code === "free") {
        await billingApi.subscribe(request);
      } else {
        await billingApi.changePlan(request);
      }
      toast({ title: fill(m.nowOn, { plan: plan.name }) });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: m.changeFailed,
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
        title: m.cancelled,
        description: m.cancelledBody,
      });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: m.cancelFailed,
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
              {label(L.subscriptionStatus, subscription.status)}
            </Badge>
          </div>

          {subscription.cancel_at_period_end ? (
            <p className="mt-3 rounded-md bg-warning/15 px-3 py-2 text-sm">
              {subscription.current_period_end
                ? fill(m.endsOn, {
                    date: new Date(subscription.current_period_end).toLocaleDateString(),
                  })
                : m.endsAtPeriodEnd}{" "}
              {t.billing.keepAccessUntilThen}
            </p>
          ) : null}

          {canManage && !subscription.cancel_at_period_end && subscription.status !== "expired" ? (
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
          <UsageCard
            usage={usage}
            strings={{
              labels: L.usage,
              unlimited: usageText.unlimited,
              exhausted: t.billing.limitReached,
            }}
          />
        </section>
      ) : null}

      {canManage && plans.length > 0 ? (
        <section className="mb-8">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-medium text-muted-foreground">{t.billing.changePlan}</h2>
            <div className="flex rounded-md border border-border p-1" aria-label={t.marketing.billingPeriod}>
              {(["monthly", "yearly"] as const).map((cycle) => (
                <Button
                  key={cycle}
                  type="button"
                  size="sm"
                  variant={billingCycle === cycle ? "secondary" : "ghost"}
                  onClick={() => setBillingCycle(cycle)}
                >
                  {cycle === "monthly" ? t.marketing.monthly : t.marketing.yearly}
                </Button>
              ))}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {plans.map((plan) => {
              // An expired trial has no current plan to keep: picking the one it
              // trialled is how it starts paying, so that card stays clickable.
              const isCurrent = plan.code === currentCode && subscription?.status !== "expired";
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
                    {(billingCycle === "monthly" ? plan.price_monthly : plan.price_yearly) === null
                      ? m.customPrice
                      : `${plan.currency} ${
                          billingCycle === "monthly" ? plan.price_monthly : plan.price_yearly
                        }${billingCycle === "monthly" ? t.common.perMonth : t.common.perYear}`}
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
                  <TableHead>{m.colNumber}</TableHead>
                  <TableHead>{m.colAmount}</TableHead>
                  <TableHead>{t.common.status}</TableHead>
                  <TableHead>{m.colIssued}</TableHead>
                  <TableHead className="text-end">{m.colDownload}</TableHead>
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
                        {label(m.invoiceStatus, invoice.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {invoice.issued_at
                        ? new Date(invoice.issued_at).toLocaleDateString()
                        : "—"}
                    </TableCell>
                    <TableCell className="text-end">
                      <Button asChild variant="outline" size="sm">
                        <a
                          href={`/api/bff/billing/invoices/${invoice.id}/pdf`}
                          download={`invoice-${invoice.number}.pdf`}
                        >
                          PDF
                        </a>
                      </Button>
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
        title={fill(m.switchTo, { plan: changingTo?.name ?? "" })}
        description={
          changingTo && isDowngrade(changingTo)
            ? t.billing.downgradeBody
            : t.billing.upgradeBody
        }
        confirmLabel={m.switchPlan}
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
