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
import { NativeSelect } from "@/components/ui/native-select";
import { useCreateSubject, useUpdateSubject } from "@/hooks/use-subjects";
import type { SubjectKind, SubjectRead } from "@/lib/api/types";

export function SubjectFormDialog({
  open,
  onOpenChange,
  subject,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  subject: SubjectRead | null;
}) {
  const create = useCreateSubject();
  const update = useUpdateSubject();

  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<SubjectKind>("core");

  React.useEffect(() => {
    if (!open) return;
    setCode(subject?.code ?? "");
    setName(subject?.name ?? "");
    setKind(subject?.kind ?? "core");
  }, [open, subject]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const body = { code, name, kind };
    if (subject) await update.mutateAsync({ id: subject.id, body });
    else await create.mutateAsync(body);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={(event) => void handleSubmit(event)}>
          <DialogHeader>
            <DialogTitle>{subject ? "Edit subject" : "New subject"}</DialogTitle>
            <DialogDescription>
              The code is a short handle for timetable grids and report-card columns, where
              &ldquo;Mathematics&rdquo; does not fit.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="grid grid-cols-[8rem_1fr] gap-3">
              <div className="space-y-1">
                <Label htmlFor="subject-code">Code</Label>
                <Input
                  id="subject-code"
                  required
                  maxLength={24}
                  placeholder="MATH"
                  value={code}
                  // Upper-cased as you type, matching what the server stores, so the
                  // field never shows something different from what will be saved.
                  onChange={(event) => setCode(event.target.value.toUpperCase())}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="subject-name">Name</Label>
                <Input
                  id="subject-name"
                  required
                  maxLength={120}
                  placeholder="Mathematics"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
            </div>

            <div className="space-y-1">
              <Label htmlFor="subject-kind">Type</Label>
              <NativeSelect
                id="subject-kind"
                value={kind}
                onChange={(event) => setKind(event.target.value as SubjectKind)}
              >
                <option value="core">Core — every student in the grade takes it</option>
                <option value="elective">Elective — chosen, so never &ldquo;missing&rdquo;</option>
                <option value="activity">Activity — timetabled and attended, not graded</option>
              </NativeSelect>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending || update.isPending}>
              {subject ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
