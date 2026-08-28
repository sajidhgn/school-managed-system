"use client";

import * as React from "react";

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
import { useCreateTerm, useTerms } from "@/hooks/use-calendar";
import type { AcademicYearRead } from "@/lib/api/types";

export function TermFormDialog({
  open,
  onOpenChange,
  year,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  year: AcademicYearRead;
}) {
  const create = useCreateTerm();
  const existing = useTerms(open ? year.id : null);

  const [name, setName] = React.useState("");
  const [sequence, setSequence] = React.useState(1);
  const [start, setStart] = React.useState("");
  const [end, setEnd] = React.useState("");

  React.useEffect(() => {
    if (!open) return;
    // Default to the next slot rather than 1. A registrar adding "Term 2" should not
    // have to discover that 1 is taken by submitting and reading a 409.
    const next = (existing.data?.length ?? 0) + 1;
    setName(`Term ${next}`);
    setSequence(next);
    setStart("");
    setEnd("");
  }, [open, existing.data]);

  const invalidRange = Boolean(start && end && end <= start);
  const outsideYear = Boolean(
    (start && start < year.start_date) || (end && end > year.end_date),
  );

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (invalidRange || outsideYear) return;
    await create.mutateAsync({
      yearId: year.id,
      body: { name, sequence, start_date: start, end_date: end },
    });
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={(event) => void handleSubmit(event)}>
          <DialogHeader>
            <DialogTitle>Add a term to {year.name}</DialogTitle>
            <DialogDescription>
              Terms may not overlap each other, and must fall inside {year.start_date} to{" "}
              {year.end_date}.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="grid grid-cols-[1fr_6rem] gap-3">
              <div className="space-y-1">
                <Label htmlFor="term-name">Name</Label>
                <Input
                  id="term-name"
                  required
                  maxLength={60}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="term-sequence">Order</Label>
                <Input
                  id="term-sequence"
                  type="number"
                  min={1}
                  max={12}
                  required
                  value={sequence}
                  onChange={(event) => setSequence(Number(event.target.value))}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="term-start">Starts</Label>
                <Input
                  id="term-start"
                  type="date"
                  required
                  min={year.start_date}
                  max={year.end_date}
                  value={start}
                  onChange={(event) => setStart(event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="term-end">Ends</Label>
                <Input
                  id="term-end"
                  type="date"
                  required
                  min={year.start_date}
                  max={year.end_date}
                  value={end}
                  onChange={(event) => setEnd(event.target.value)}
                />
              </div>
            </div>
            {invalidRange && (
              <p className="text-sm text-destructive">The term must end after it starts.</p>
            )}
            {outsideYear && (
              <p className="text-sm text-destructive">
                The term must fall inside {year.name}.
              </p>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={invalidRange || outsideYear || create.isPending}
            >
              Add term
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
