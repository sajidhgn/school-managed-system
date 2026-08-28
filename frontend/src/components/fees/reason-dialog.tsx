"use client";

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

/**
 * A confirmation that will not proceed without a written reason.
 *
 * Voiding a challan and reversing a receipt both un-record money, and both are
 * refused by the API without a reason of at least three characters. The reason is
 * the only thing the audit row can show a future reader that the amounts cannot —
 * "what was this?" is answerable, "who did this?" is not enough.
 *
 * Shared between the challan screen and the student's own page, because the same
 * two actions are offered from both and a second copy of this would eventually
 * disagree with the first about what it warns.
 */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  reason,
  onReasonChange,
  busy,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  reason: string;
  onReasonChange: (value: string) => void;
  busy: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const tooShort = reason.trim().length < 3;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">Reason</span>
          <Input
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            placeholder="Duplicate challan, keyed in error…"
            autoFocus
          />
          <span className="text-xs text-muted-foreground">
            Recorded in the audit log against your name. Write it for whoever reads this
            in six months.
          </span>
        </label>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={busy || tooShort}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
