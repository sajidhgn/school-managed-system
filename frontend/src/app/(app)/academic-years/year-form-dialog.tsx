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
import { useCreateAcademicYear, useUpdateAcademicYear } from "@/hooks/use-calendar";
import type { AcademicYearRead } from "@/lib/api/types";
import { calendarMessages } from "@/lib/i18n/modules/calendar";
import { useCatalog } from "@/lib/i18n/use-catalog";

export function YearFormDialog({
  open,
  onOpenChange,
  year,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  year: AcademicYearRead | null;
}) {
  const m = useCatalog(calendarMessages).yearForm;
  const create = useCreateAcademicYear();
  const update = useUpdateAcademicYear();

  const [name, setName] = React.useState("");
  const [start, setStart] = React.useState("");
  const [end, setEnd] = React.useState("");
  const [makeCurrent, setMakeCurrent] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setName(year?.name ?? "");
    setStart(year?.start_date ?? "");
    setEnd(year?.end_date ?? "");
    setMakeCurrent(false);
  }, [open, year]);

  // Checked here as well as by the backend's CHECK constraint. The constraint is
  // the guarantee; this is what stops the user submitting to find out.
  const invalidRange = Boolean(start && end && end <= start);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (invalidRange) return;
    if (year) {
      await update.mutateAsync({
        id: year.id,
        body: { name, start_date: start, end_date: end },
      });
    } else {
      await create.mutateAsync({
        name,
        start_date: start,
        end_date: end,
        is_current: makeCurrent,
      });
    }
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={(event) => void handleSubmit(event)}>
          <DialogHeader>
            <DialogTitle>{year ? m.editTitle : m.newTitle}</DialogTitle>
            <DialogDescription>{m.description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-1">
              <Label htmlFor="year-name">{m.name}</Label>
              <Input
                id="year-name"
                required
                maxLength={32}
                placeholder="2026-2027"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="year-start">{m.starts}</Label>
                <Input
                  id="year-start"
                  type="date"
                  required
                  value={start}
                  onChange={(event) => setStart(event.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="year-end">{m.ends}</Label>
                <Input
                  id="year-end"
                  type="date"
                  required
                  value={end}
                  onChange={(event) => setEnd(event.target.value)}
                />
              </div>
            </div>
            {invalidRange && (
              <p className="text-sm text-destructive">{m.invalidRange}</p>
            )}

            {/* Only on create. Promoting an existing year DEMOTES another, so it is
                its own action on the list rather than a checkbox buried in an edit
                form that looks like it changes one record. */}
            {!year && (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={makeCurrent}
                  onChange={(event) => setMakeCurrent(event.target.checked)}
                />
                {m.makeCurrent}
                <span className="text-muted-foreground">{m.makeCurrentHint}</span>
              </label>
            )}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {m.cancel}
            </Button>
            <Button type="submit" disabled={invalidRange || create.isPending || update.isPending}>
              {year ? m.save : m.create}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
