"use client";

import * as React from "react";
import { useQueries } from "@tanstack/react-query";

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
import { useAcademicYears } from "@/hooks/use-calendar";
import { useCreateExam, useUpdateExam } from "@/hooks/use-exams";
import { queryKeys } from "@/lib/api/query-keys";
import { calendarApi } from "@/lib/api/resources/calendar";
import type { ExamRead, ExamStatus } from "@/lib/api/types";

export const EXAM_STATUS_LABELS: Record<ExamStatus, string> = {
  scheduled: "Scheduled",
  completed: "Completed",
  published: "Published",
};

/**
 * Create or edit an exam.
 *
 * `status` appears only when editing: a new exam is always `scheduled` (there
 * is nothing to have completed yet), and offering the field at creation would
 * invite exams born "published" with no marks behind them.
 */
export function ExamFormDialog({
  open,
  onOpenChange,
  exam,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  exam: ExamRead | null;
}) {
  const create = useCreateExam();
  const update = useUpdateExam();

  // Every year's terms, fetched in parallel and rendered as ONE grouped
  // dropdown. Two chained selects (year, then term) would be more requests
  // saved and more clicks spent — a school has a handful of years, and the
  // grouped list also lets an existing `term_id` resolve without knowing its
  // year in advance.
  const years = useAcademicYears({ size: 50 });
  const yearItems = React.useMemo(() => years.data?.items ?? [], [years.data]);
  const termQueries = useQueries({
    queries: yearItems.map((year) => ({
      queryKey: queryKeys.calendar.terms(year.id),
      queryFn: () => calendarApi.terms.list(year.id),
      enabled: open,
    })),
  });
  const termGroups = yearItems
    .map((year, index) => ({ year, terms: termQueries[index]?.data ?? [] }))
    .filter((group) => group.terms.length > 0);

  const [name, setName] = React.useState("");
  const [termId, setTermId] = React.useState("");
  const [startDate, setStartDate] = React.useState("");
  const [endDate, setEndDate] = React.useState("");
  const [status, setStatus] = React.useState<ExamStatus>("scheduled");

  React.useEffect(() => {
    if (open) {
      setName(exam?.name ?? "");
      setTermId(exam?.term_id ?? "");
      setStartDate(exam?.start_date ?? "");
      setEndDate(exam?.end_date ?? "");
      setStatus(exam?.status ?? "scheduled");
    }
  }, [open, exam]);

  const saving = create.isPending || update.isPending;

  async function save() {
    const body = {
      name: name.trim(),
      term_id: termId || null,
      start_date: startDate || null,
      end_date: endDate || null,
    };
    if (exam) {
      await update.mutateAsync({ id: exam.id, body: { ...body, status } });
    } else {
      await create.mutateAsync(body);
    }
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{exam ? `Edit ${exam.name}` : "New exam"}</DialogTitle>
          <DialogDescription>
            Name the exam for its session (e.g. &quot;Mid-Term 2026-27&quot;) — names are
            unique per school, so recurring exams carry their year.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="exam-name">Name</Label>
            <Input
              id="exam-name"
              value={name}
              placeholder="Mid-Term 2026-27"
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          {termGroups.length > 0 ? (
            <div className="grid gap-1.5">
              <Label htmlFor="exam-term">Term</Label>
              <NativeSelect
                id="exam-term"
                value={termId}
                onChange={(event) => setTermId(event.target.value)}
              >
                <option value="">No term</option>
                {termGroups.map(({ year, terms }) => (
                  <optgroup key={year.id} label={year.name}>
                    {terms.map((term) => (
                      <option key={term.id} value={term.id}>
                        {term.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </NativeSelect>
              <p className="text-xs text-muted-foreground">
                The reporting period this exam belongs to, from the Academic year page.
              </p>
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="exam-start">Starts</Label>
              <Input
                id="exam-start"
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="exam-end">Ends</Label>
              <Input
                id="exam-end"
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </div>
          </div>
          {exam ? (
            <div className="grid gap-1.5">
              <Label htmlFor="exam-status">Status</Label>
              <NativeSelect
                id="exam-status"
                value={status}
                onChange={(event) => setStatus(event.target.value as ExamStatus)}
              >
                {(Object.keys(EXAM_STATUS_LABELS) as ExamStatus[]).map((value) => (
                  <option key={value} value={value}>
                    {EXAM_STATUS_LABELS[value]}
                  </option>
                ))}
              </NativeSelect>
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={save} disabled={saving || !name.trim()}>
            {saving ? "Saving…" : exam ? "Save changes" : "Create exam"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
