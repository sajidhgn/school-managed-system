"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { PlanImpactDialog } from "@/components/platform/plan-impact-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";
import { platformPlans } from "@/lib/api/resources";
import { USAGE_LABELS, type PlanAdminRead } from "@/lib/api/types";

/**
 * Create or edit a plan.
 *
 * =============================================================================
 * EDITING GOES THROUGH AN IMPACT PREVIEW; CREATING DOES NOT
 * =============================================================================
 *   A new plan has no subscribers, so there is nothing to break and a confirmation
 *   would be theatre. An EXISTING plan may have hundreds, and lowering one of its
 *   limits silently pushes every organization above the new figure into
 *   `over_limit`.
 *
 *   So the save path branches: create writes immediately, edit asks the server who
 *   would be affected and shows the answer first.
 *
 * =============================================================================
 * LIMITS ARE SENT AS A COMPLETE SET, AND THE FORM ENFORCES IT
 * =============================================================================
 *   Spec §6.1: every limit key must exist on every plan — no missing-key fallbacks,
 *   because `.get(key, 0)` silently blocks a paying customer and `.get(key, -1)`
 *   silently gives away unlimited usage.
 *
 *   Every key therefore gets a field, and the server rejects an incomplete set with
 *   422 INCOMPLETE_PLAN. `-1` means unlimited, which the hint states rather than
 *   leaving the operator to infer from a magic number.
 */

const FEATURE_KEYS = [
  "custom_branding",
  "api_access",
  "priority_support",
  "sso",
  "advanced_reports",
] as const;

const FEATURE_LABELS: Record<string, string> = {
  custom_branding: "Custom branding",
  api_access: "API access",
  priority_support: "Priority support",
  sso: "Single sign-on",
  advanced_reports: "Advanced reports",
};

const LIMIT_KEYS = [...Object.keys(USAGE_LABELS), "audit_retention_days"] as const;

const LIMIT_LABELS: Record<string, string> = {
  ...USAGE_LABELS,
  audit_retention_days: "Audit retention (days)",
};

interface FormState {
  code: string;
  name: string;
  marketing_tagline: string;
  price_monthly: string;
  price_yearly: string;
  currency: string;
  trial_days: string;
  is_public: boolean;
  sort_order: string;
  limits: Record<string, string>;
  features: Record<string, boolean>;
}

function initialState(plan: PlanAdminRead | null): FormState {
  return {
    code: plan?.code ?? "",
    name: plan?.name ?? "",
    marketing_tagline: plan?.marketing_tagline ?? "",
    // Empty string means "no price" (a quoted enterprise tier), which is distinct
    // from "0" (genuinely free). Coercing both to 0 would put a price on a plan the
    // sales team negotiates.
    price_monthly: plan?.price_monthly != null ? String(plan.price_monthly) : "",
    price_yearly: plan?.price_yearly != null ? String(plan.price_yearly) : "",
    currency: plan?.currency ?? "USD",
    trial_days: String(plan?.trial_days ?? 0),
    is_public: plan?.is_public ?? true,
    sort_order: String(plan?.sort_order ?? 0),
    limits: Object.fromEntries(
      LIMIT_KEYS.map((key) => [key, String(plan?.limits?.[key] ?? 0)]),
    ),
    features: Object.fromEntries(
      FEATURE_KEYS.map((key) => [key, Boolean(plan?.features?.[key])]),
    ),
  };
}

export function PlanFormDialog({
  plan,
  open,
  onOpenChange,
}: {
  /** null = create a new plan. */
  plan: PlanAdminRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  // Seeded once from props. The PARENT remounts this component with a `key` derived
  // from the plan id, which resets the form when a different row is opened — cleaner
  // than syncing state to props on every render, and it cannot get out of step.
  const [form, setForm] = useState<FormState>(() => initialState(plan));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const numericLimits = Object.fromEntries(
    Object.entries(form.limits).map(([key, value]) => [key, Number(value)]),
  );

  const payload = {
    name: form.name,
    marketing_tagline: form.marketing_tagline || undefined,
    price_monthly: form.price_monthly === "" ? null : Number(form.price_monthly),
    price_yearly: form.price_yearly === "" ? null : Number(form.price_yearly),
    currency: form.currency,
    trial_days: Number(form.trial_days),
    is_public: form.is_public,
    sort_order: Number(form.sort_order),
    limits: numericLimits,
    features: form.features,
  };

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (plan) {
        await platformPlans.update(plan.id, payload);
        toast({ title: `${form.name} updated.` });
      } else {
        await platformPlans.create({ ...payload, code: form.code, is_active: true });
        toast({ title: `${form.name} created.` });
      }
      setConfirming(false);
      onOpenChange(false);
      router.refresh();
    } catch (err) {
      setConfirming(false);
      if (err instanceof ApiError) {
        // The server's message names the missing keys or the offending field, which
        // is far more useful than "save failed".
        setError(err.message);
        return;
      }
      setError("Please try again.");
    } finally {
      setSaving(false);
    }
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (plan) {
      // Existing plan: check the blast radius before writing.
      setConfirming(true);
    } else {
      void save();
    }
  }

  const invalidLimits = Object.entries(form.limits).filter(
    ([, value]) => value === "" || Number.isNaN(Number(value)),
  );

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[85svh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{plan ? `Edit ${plan.name}` : "New plan"}</DialogTitle>
            <DialogDescription>
              {plan
                ? "Changes apply to everyone on this plan. You'll see who is affected before saving."
                : "A new plan has no subscribers, so it takes effect immediately."}
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={onSubmit} className="grid gap-5" noValidate>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="plan-name" required>
                  Display name
                </Label>
                <Input
                  id="plan-name"
                  value={form.name}
                  required
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="plan-code" required>
                  Code
                </Label>
                <Input
                  id="plan-code"
                  value={form.code}
                  required
                  // Immutable after creation: the code appears in `POST
                  // /billing/change-plan` payloads and in any customer integration,
                  // so renaming it would break them silently.
                  disabled={plan !== null}
                  placeholder="growth"
                  onChange={(e) => setForm({ ...form, code: e.target.value })}
                />
                {plan ? (
                  <p className="text-xs text-muted-foreground">
                    Codes cannot change — customers and integrations reference them.
                  </p>
                ) : null}
              </div>
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="plan-tagline">Tagline</Label>
              <Input
                id="plan-tagline"
                value={form.marketing_tagline}
                placeholder="For school groups."
                onChange={(e) => setForm({ ...form, marketing_tagline: e.target.value })}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-4">
              <div className="grid gap-1.5">
                <Label htmlFor="price-monthly">Monthly</Label>
                <Input
                  id="price-monthly"
                  inputMode="decimal"
                  value={form.price_monthly}
                  placeholder="Quoted"
                  onChange={(e) => setForm({ ...form, price_monthly: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="price-yearly">Yearly</Label>
                <Input
                  id="price-yearly"
                  inputMode="decimal"
                  value={form.price_yearly}
                  placeholder="Quoted"
                  onChange={(e) => setForm({ ...form, price_yearly: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="currency">Currency</Label>
                <Input
                  id="currency"
                  maxLength={3}
                  className="uppercase"
                  value={form.currency}
                  onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="trial-days">Trial days</Label>
                <Input
                  id="trial-days"
                  inputMode="numeric"
                  value={form.trial_days}
                  onChange={(e) => setForm({ ...form, trial_days: e.target.value })}
                />
              </div>
            </div>
            <p className="-mt-3 text-xs text-muted-foreground">
              Leave a price empty for a quoted plan — that is what makes a tier
              &ldquo;Contact sales&rdquo; rather than free.
            </p>

            <fieldset>
              <legend className="mb-2 text-sm font-medium">Limits</legend>
              <div className="grid gap-3 sm:grid-cols-3">
                {LIMIT_KEYS.map((key) => (
                  <div key={key} className="grid gap-1.5">
                    <Label htmlFor={`limit-${key}`}>{LIMIT_LABELS[key] ?? key}</Label>
                    <Input
                      id={`limit-${key}`}
                      inputMode="numeric"
                      value={form.limits[key] ?? ""}
                      onChange={(e) =>
                        setForm({ ...form, limits: { ...form.limits, [key]: e.target.value } })
                      }
                    />
                  </div>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Use <code>-1</code> for unlimited. Every limit must have a value —
                a missing one would either block paying customers or give away
                unlimited usage.
              </p>
            </fieldset>

            <fieldset>
              <legend className="mb-2 text-sm font-medium">Features</legend>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {FEATURE_KEYS.map((key) => (
                  <label key={key} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={form.features[key] ?? false}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          features: { ...form.features, [key]: e.target.checked },
                        })
                      }
                    />
                    {FEATURE_LABELS[key]}
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="flex items-start gap-2 rounded-lg bg-muted/60 p-3 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-primary"
                checked={form.is_public}
                onChange={(e) => setForm({ ...form, is_public: e.target.checked })}
              />
              <span>
                <span className="font-medium">Show on the pricing page</span>
                <span className="block text-xs text-muted-foreground">
                  Unchecked keeps it hidden and unselectable by customers — the only way
                  onto it is a manual assignment from an organization&apos;s page.
                </span>
              </span>
            </label>

            {error ? (
              <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </p>
            ) : null}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={saving || invalidLimits.length > 0 || !form.name || !form.code}
              >
                {plan ? "Review changes" : "Create plan"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {plan ? (
        <PlanImpactDialog
          planId={plan.id}
          planName={plan.name}
          proposedLimits={numericLimits}
          open={confirming}
          onOpenChange={setConfirming}
          onConfirm={save}
          saving={saving}
        />
      ) : null}
    </>
  );
}
