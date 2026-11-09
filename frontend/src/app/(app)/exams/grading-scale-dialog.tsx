"use client";

import * as React from "react";
import { Plus, RotateCcw, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge } from "@/components/ui/badge";
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
import { useGradingScale, useResetGradingScale, useSetGradingScale } from "@/hooks/use-exams";
import type { GradeBand } from "@/lib/api/types";
import type { Translation } from "@/lib/i18n/catalog";
import { fill } from "@/lib/i18n/format";
import { examsMessages } from "@/lib/i18n/modules/exams";
import { useCatalog } from "@/lib/i18n/use-catalog";

type ScaleProblems = Translation<(typeof examsMessages)["en"]["grading"]["problems"]>;

type Row = { key: number; min: string; grade: string; remark: string };

let nextKey = 1;
const row = (min: string | number, grade: string, remark: string | null | undefined): Row => ({
  key: nextKey++,
  min: String(min).replace(/\.00$/, ""),
  grade,
  remark: remark ?? "",
});

/**
 * Which percentage earns which grade, for this campus.
 *
 * =============================================================================
 * EVERY CAMPUS STARTS ON THE BOARD SCALE
 * =============================================================================
 *   A+ from 80%, pass from 33% — what the printed result card has always used. This
 *   screen replaces it. The result sheet, the printed card and the parent portal all
 *   grade with what is saved here, so the three can never disagree.
 *
 * THE LOWEST BAND IS THE FAIL BAND
 *   The result card prints FAIL for an overall result in it (and for any paper under
 *   its pass mark). The form says so beside the last row, because that is the row a
 *   school changing "pass from 33" to "pass from 40" is looking for.
 *
 * Saving re-grades every exam, including published ones — marks never change. The
 * dialog says that before the button, not after.
 */
export function GradingScaleDialog({
  open,
  onOpenChange,
  canEdit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `grade:manage` and `school:update`. Everyone else sees the scale read-only. */
  canEdit: boolean;
}) {
  const m = useCatalog(examsMessages).grading;
  const scale = useGradingScale();
  const save = useSetGradingScale();
  const reset = useResetGradingScale();
  const [rows, setRows] = React.useState<Row[]>([]);
  const [confirmingReset, setConfirmingReset] = React.useState(false);

  const loadFrom = React.useCallback((bands: GradeBand[]) => {
    setRows(bands.map((band) => row(band.min_percent, band.grade, band.remark)));
  }, []);

  // Reload whenever the dialog opens or the saved scale changes underneath it.
  const stamp = scale.data ? `${scale.data.id ?? "default"}:${scale.data.updated_at ?? ""}` : null;
  React.useEffect(() => {
    if (open && scale.data) loadFrom(scale.data.bands);
  }, [open, stamp, loadFrom]); // eslint-disable-line react-hooks/exhaustive-deps

  const problems = validate(rows, m.problems);
  const sorted = [...rows].sort((a, b) => Number(b.min) - Number(a.min));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (problems.length > 0) return;
    await save.mutateAsync({
      bands: rows.map((r) => ({
        min_percent: Number(r.min),
        grade: r.grade.trim(),
        remark: r.remark.trim() || null,
      })),
    });
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle className="flex flex-wrap items-center gap-2">
              {m.title}
              {scale.data?.is_default ? <Badge variant="neutral">{m.boardScale}</Badge> : null}
            </DialogTitle>
            <DialogDescription>{m.description}</DialogDescription>
          </DialogHeader>

          {scale.isPending ? (
            <div className="h-64 animate-pulse rounded-lg bg-muted" />
          ) : (
            <>
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-start font-medium">{m.colFrom}</th>
                      <th className="px-3 py-2 text-start font-medium">{m.colTo}</th>
                      <th className="px-3 py-2 text-start font-medium">{m.colGrade}</th>
                      <th className="px-3 py-2 text-start font-medium">{m.colRemark}</th>
                      {canEdit ? <th className="w-10" /> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((r, index) => {
                      const upper = index === 0 ? 100 : Number(sorted[index - 1].min);
                      const last = index === sorted.length - 1;
                      return (
                        <tr key={r.key} className="border-t border-border">
                          <td className="px-3 py-2">
                            {canEdit ? (
                              <Input
                                value={r.min}
                                inputMode="decimal"
                                className="w-20"
                                aria-label={fill(m.lowestFor, { grade: r.grade || m.thisBand })}
                                onChange={(event) => update(r.key, { min: event.target.value })}
                              />
                            ) : (
                              <span className="tabular-nums">{r.min}</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-muted-foreground tabular-nums">
                            {Number.isFinite(upper)
                              ? index === 0
                                ? "100"
                                : fill(m.under, { value: upper })
                              : "—"}
                          </td>
                          <td className="px-3 py-2">
                            {canEdit ? (
                              <Input
                                value={r.grade}
                                maxLength={8}
                                className="w-20"
                                aria-label={m.gradeAria}
                                onChange={(event) => update(r.key, { grade: event.target.value })}
                              />
                            ) : (
                              <span className="font-semibold">{r.grade}</span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            {canEdit ? (
                              <Input
                                value={r.remark}
                                maxLength={60}
                                aria-label={m.remarkAria}
                                placeholder={last ? m.failPlaceholder : ""}
                                onChange={(event) => update(r.key, { remark: event.target.value })}
                              />
                            ) : (
                              <span>{r.remark}</span>
                            )}
                            {last ? (
                              <span className="mt-1 block text-xs text-muted-foreground">
                                {m.failBandNote}
                              </span>
                            ) : null}
                          </td>
                          {canEdit ? (
                            <td className="px-1 py-2">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={fill(m.removeBand, { grade: r.grade || m.bandFallback })}
                                disabled={rows.length <= 2}
                                onClick={() => setRows(rows.filter((x) => x.key !== r.key))}
                              >
                                <Trash2 className="size-4" aria-hidden />
                              </Button>
                            </td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {canEdit ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={rows.length >= 15}
                    onClick={() => setRows([...rows, row("", "", "")])}
                  >
                    <Plus className="size-4" aria-hidden />
                    {m.addBand}
                  </Button>
                  {!scale.data?.is_default ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmingReset(true)}
                    >
                      <RotateCcw className="size-4" aria-hidden />
                      {m.resetToBoard}
                    </Button>
                  ) : null}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">{m.readOnly}</p>
              )}

              {canEdit ? (
                <p className="rounded-md bg-warning/15 px-3 py-2 text-xs">{m.regradeWarning}</p>
              ) : null}
              {canEdit && problems.length > 0 ? (
                <p className="text-xs text-destructive">{problems[0]}</p>
              ) : null}
            </>
          )}

          {canEdit ? (
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {m.cancel}
              </Button>
              <Button type="submit" loading={save.isPending} disabled={problems.length > 0}>
                {m.save}
              </Button>
            </DialogFooter>
          ) : null}
        </form>

        <ConfirmDialog
          open={confirmingReset}
          onOpenChange={setConfirmingReset}
          title={m.resetTitle}
          description={m.resetDescription}
          confirmLabel={m.reset}
          loading={reset.isPending}
          onConfirm={async () => {
            await reset.mutateAsync();
            setConfirmingReset(false);
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );

  function update(key: number, patch: Partial<Row>) {
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }
}

/**
 * Mirrors `GradingScaleInput`, so the save button explains before the API refuses.
 * `t` is the localized problem text, from the dialog's catalog.
 */
function validate(rows: Row[], t: ScaleProblems): string[] {
  const problems: string[] = [];
  if (rows.length < 2) problems.push(t.tooFew);
  const mins = rows.map((r) => Number(r.min));
  if (rows.some((r) => r.min.trim() === "" || !Number.isFinite(Number(r.min))))
    problems.push(t.missingStart);
  else if (mins.some((m) => m < 0 || m > 100)) problems.push(t.outOfRange);
  else if (new Set(mins).size !== mins.length) problems.push(t.duplicateStart);
  else if (!mins.includes(0)) problems.push(t.noZero);
  if (rows.some((r) => !r.grade.trim())) problems.push(t.missingGrade);
  const grades = rows.map((r) => r.grade.trim().toLowerCase()).filter(Boolean);
  if (new Set(grades).size !== grades.length) problems.push(t.duplicateGrade);
  return problems;
}
