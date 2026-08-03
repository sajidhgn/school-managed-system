"use client";

import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api/client";
import { USAGE_LABELS, type PlanImpactResponse } from "@/lib/api/types";

/**
 * The confirmation step in front of every plan-limit save.
 *
 * =============================================================================
 * WHY A SAVE BUTTON IS NOT ENOUGH HERE
 * =============================================================================
 *   Lowering a limit succeeds instantly, changes one JSONB value, and produces no
 *   error. What it actually does is push every organization above the new figure
 *   into `over_limit`, where their next enrolment is refused with a 402.
 *
 *   Nobody finds out at the time. It surfaces days later as support tickets from
 *   schools that cannot admit students — by which point the operator has forgotten
 *   they touched it.
 *
 *   So the save asks the server first and shows the answer. Crucially it shows
 *   NAMES, not a count: "3 organizations affected" is a number people click past;
 *   "Springfield Trust will be blocked from adding students" is not.
 *
 * The harmless case is shown too, in green. A dialog that only ever appears when
 * something is wrong trains operators to dismiss it; one that confirms "this affects
 * nobody" is worth reading every time.
 */
export function PlanImpactDialog({
  planId,
  planName,
  proposedLimits,
  open,
  onOpenChange,
  onConfirm,
  saving,
}: {
  planId: string;
  planName: string;
  /** Merged over the plan's current limits server-side, exactly as PATCH does. */
  proposedLimits: Record<string, number> | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  saving: boolean;
}) {
  const [impact, setImpact] = useState<PlanImpactResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setImpact(null);
      setError(null);
      return;
    }

    let cancelled = false;
    api
      .post<PlanImpactResponse>(`/platform/plans/${planId}/impact`, {
        limits: proposedLimits,
      })
      .then((result) => {
        if (!cancelled) setImpact(result);
      })
      .catch(() => {
        // Fail LOUD, not silent. If the preview cannot be computed the operator must
        // not be able to save blind — the whole point of this dialog is that the
        // consequence is otherwise invisible.
        if (!cancelled) setError("Could not calculate the impact of this change.");
      });

    return () => {
      cancelled = true;
    };
  }, [open, planId, proposedLimits]);

  const loading = open && impact === null && error === null;
  const affected = impact?.would_exceed ?? [];
  const blocked = error !== null || loading;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Save changes to {planName}?</DialogTitle>
          <DialogDescription>
            Checking what this does to organizations already on this plan.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <p className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Calculating impact…
          </p>
        ) : error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error} Saving is disabled until it can be checked.
          </p>
        ) : affected.length === 0 ? (
          <div className="flex items-start gap-2 rounded-lg bg-success/10 p-4 text-sm">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
            <div>
              <p className="font-medium">No organization is affected.</p>
              <p className="mt-0.5 text-muted-foreground">
                {impact?.subscriber_count === 0
                  ? "Nobody is on this plan yet."
                  : `All ${impact?.subscriber_count} organization${
                      impact?.subscriber_count === 1 ? "" : "s"
                    } on this plan stay within the new limits.`}
              </p>
            </div>
          </div>
        ) : (
          <div className="grid gap-3">
            <div className="flex items-start gap-2 rounded-lg bg-warning/15 p-4 text-sm">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <div>
                <p className="font-medium">
                  {affected.length} of {impact?.subscriber_count} organization
                  {affected.length === 1 ? "" : "s"} will go over limit.
                </p>
                <p className="mt-0.5 text-pretty">
                  {/* The reassuring half is stated as prominently as the warning,
                      because "will I destroy their data?" is the operator's actual
                      question and the answer is no. */}
                  Their existing records stay readable and exportable. New ones are
                  refused until they upgrade or fall back under the cap.
                </p>
              </div>
            </div>

            <ul className="grid gap-2">
              {affected.map((org) => (
                <li key={org.organization_id} className="rounded-lg border border-border p-3 text-sm">
                  <p className="font-medium">{org.name}</p>
                  <ul className="mt-1 grid gap-0.5 text-xs text-muted-foreground">
                    {org.breaches.map((breach) => (
                      <li key={breach.key}>
                        {USAGE_LABELS[breach.key] ?? breach.key}: using{" "}
                        <span className="font-medium text-destructive">{breach.current}</span>, new
                        limit <span className="font-medium">{breach.allowed}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </div>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            variant={affected.length > 0 ? "destructive" : "default"}
            disabled={blocked || saving}
            onClick={onConfirm}
          >
            {saving
              ? "Saving…"
              : affected.length > 0
                ? `Save anyway (${affected.length} affected)`
                : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
