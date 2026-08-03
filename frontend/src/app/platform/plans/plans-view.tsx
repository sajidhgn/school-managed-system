"use client";

import { Archive, Pencil, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { PlanFormDialog } from "@/components/platform/plan-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";
import { platformPlans } from "@/lib/api/resources";
import { USAGE_LABELS, type PlanAdminRead } from "@/lib/api/types";

/**
 * The product catalog, editable.
 *
 * This table is the SOURCE OF TRUTH for the public pricing page and for every
 * entitlement check. Editing a limit here changes what customers can create; editing
 * a price changes what they are charged. Which is why the edit path goes through an
 * impact preview and the free plan cannot be retired at all.
 */
export function PlansView({
  plans,
  subscriberCounts,
}: {
  plans: PlanAdminRead[];
  subscriberCounts: Record<string, number>;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState<PlanAdminRead | null>(null);
  const [creating, setCreating] = useState(false);
  const [retiring, setRetiring] = useState<PlanAdminRead | null>(null);
  const [busy, setBusy] = useState(false);

  async function retire(plan: PlanAdminRead) {
    setBusy(true);
    try {
      await platformPlans.retire(plan.id);
      toast({
        title: `${plan.name} retired.`,
        description: "Existing subscribers keep it; nobody new can select it.",
      });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not retire this plan",
        // The server explains the free-plan guard in full; passing it through beats
        // any generic message this component could write.
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(false);
      setRetiring(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Plans"
        description="What the pricing page shows and what entitlements enforce."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" aria-hidden />
            New plan
          </Button>
        }
      />

      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Plan</TableHead>
              <TableHead className="text-end">On plan</TableHead>
              <TableHead>Price</TableHead>
              <TableHead>Trial</TableHead>
              {Object.values(USAGE_LABELS).map((limitLabel) => (
                <TableHead key={limitLabel} className="text-end">
                  {limitLabel}
                </TableHead>
              ))}
              <TableHead>Visibility</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {plans.map((plan) => {
              const subscribers = subscriberCounts[plan.code] ?? 0;
              const isFree = plan.code === "free";

              return (
                <TableRow key={plan.id}>
                  <TableCell>
                    <div className="font-medium">{plan.name}</div>
                    <code className="text-xs text-muted-foreground">{plan.code}</code>
                  </TableCell>
                  <TableCell className="text-end tabular-nums">
                    {/* Shown next to every row so an operator sees the stakes before
                        opening the editor, not only inside the confirmation. */}
                    {subscribers > 0 ? (
                      <span className="font-medium">{subscribers}</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap tabular-nums">
                    {plan.price_monthly === null
                      ? "Quoted"
                      : `${plan.currency} ${plan.price_monthly}/mo`}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {plan.trial_days > 0 ? `${plan.trial_days}d` : "—"}
                  </TableCell>
                  {Object.keys(USAGE_LABELS).map((key) => {
                    const value = Number(plan.limits?.[key] ?? 0);
                    return (
                      <TableCell key={key} className="text-end tabular-nums">
                        {/* -1 is the unlimited sentinel; rendering it raw would read
                            as a data error. */}
                        {value === -1 ? "∞" : value.toLocaleString()}
                      </TableCell>
                    );
                  })}
                  <TableCell>
                    <div className="flex gap-1">
                      {plan.is_public ? (
                        <Badge variant="success">Public</Badge>
                      ) : (
                        <Badge variant="neutral">Hidden</Badge>
                      )}
                      {!plan.is_active ? <Badge variant="destructive">Retired</Badge> : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={busy}
                        onClick={() => setEditing(plan)}
                        title={`Edit ${plan.name}`}
                      >
                        <Pencil className="size-4" aria-hidden />
                        <span className="sr-only">Edit {plan.name}</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={busy || !plan.is_active || isFree}
                        onClick={() => setRetiring(plan)}
                        title={
                          isFree
                            ? "The free plan cannot be retired — every new organization starts on it"
                            : `Retire ${plan.name}`
                        }
                      >
                        <Archive className="size-4" aria-hidden />
                        <span className="sr-only">Retire {plan.name}</span>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <p className="mt-4 text-sm text-muted-foreground">
        Hidden plans are assignable to a specific organization from its detail page, but never
        selectable by customers themselves.
      </p>

      {/* `key` remounts the form when a different plan is opened, so its inputs
          re-seed from the new row instead of keeping the previous one's values. */}
      <PlanFormDialog
        key={editing?.id ?? "new"}
        plan={editing}
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
      />
      <PlanFormDialog
        key="create"
        plan={null}
        open={creating}
        onOpenChange={setCreating}
      />

      <ConfirmDialog
        open={retiring !== null}
        onOpenChange={(open) => !open && setRetiring(null)}
        title={`Retire ${retiring?.name}?`}
        description={
          retiring && (subscriberCounts[retiring.code] ?? 0) > 0
            ? `${subscriberCounts[retiring.code]} organization(s) stay on this plan and keep the terms they agreed to. It disappears from the pricing page, so nobody new can select it. Nothing is deleted.`
            : "It disappears from the pricing page and can no longer be selected. Nothing is deleted, and it can be re-enabled later."
        }
        confirmLabel="Retire plan"
        variant="destructive"
        loading={busy}
        onConfirm={() => retiring && retire(retiring)}
      />
    </>
  );
}
