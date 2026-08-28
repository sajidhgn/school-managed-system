"use client";

import * as React from "react";
import { AlertTriangle } from "lucide-react";

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
import { NativeSelect } from "@/components/ui/native-select";
import {
  useFeeHeads,
  useFeeStructure,
  useFeeStructures,
  useGenerateVouchers,
} from "@/hooks/use-fees";
import type { VoucherGenerateResult } from "@/lib/api/types";

/**
 * Bill a whole class for one period.
 *
 * =============================================================================
 * THE RESULT SCREEN IS NOT OPTIONAL
 * =============================================================================
 *   This is the only bulk write in the module, and it deliberately SKIPS rather than
 *   fails: a student already billed for the period is passed over and the rest still
 *   generate. That is the right behaviour — rolling back 400 challans because one
 *   student was billed twice is not a usable product — but it means a successful run
 *   and a mostly-successful run look identical unless the skips are shown.
 *
 *   So the dialog does not close on success. It swaps to a receipt of the run: how
 *   many were created, who was skipped and why, and whether the 500-student cap
 *   truncated it. The operator dismisses it once they have read it.
 */
export function GenerateChallansDialog({
  open,
  onOpenChange,
  academicYear,
  canCollect,
  studentIds,
  studentName,
  classId,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  academicYear: string;
  /** Issuing immediately is only offered to someone who could then take the money. */
  canCollect: boolean;
  /**
   * Narrow the run to specific students — how the student's own page bills one
   * child without the operator having to find the class and un-tick everyone else.
   *
   * The backend takes `student_ids` as a filter ON TOP of the structure's class, so
   * a student who is not in that class is simply not billed rather than being billed
   * against a structure that was never meant for them. Same endpoint, same skip
   * reporting, same 500 cap — only the audience is narrower.
   */
  studentIds?: string[];
  /** Names the one student in the copy, so a single-student run reads like one. */
  studentName?: string;
  /**
   * The class whose structure should bill — the student's own, resolved from their
   * section by the page that opened this.
   *
   * A structure belongs to exactly one class, and a challan is always billed against
   * the structure for the student's own class. When the caller already knows the
   * class, asking an operator to pick the structure is asking them to re-state
   * something the screen behind the dialog is already showing them — and it is a
   * question they can get WRONG, which bills a child against another grade's fees.
   *
   * So the list is narrowed to this class, and a class with exactly one active
   * structure for the year is not asked about at all: the dialog says which
   * structure it will bill and gets on with the two things it genuinely cannot
   * know, the period and the dates.
   */
  classId?: string;
  /** Names the class in the copy when the structure was resolved from it. */
  className?: string;
}) {
  // Narrowed server-side when the class is known, so a campus with forty structures
  // does not ship thirty-nine irrelevant ones to filter in the browser.
  const structures = useFeeStructures({
    size: 100,
    ...(classId ? { class_id: classId } : {}),
  });
  const generate = useGenerateVouchers();
  // Only read when the operator asks to carry dues forward, but the hook cannot be
  // conditional — the list is small, cached, and usually already loaded by the setup
  // screen, so fetching it up front costs nothing worth optimising.
  const heads = useFeeHeads({ size: 100 });

  const [structureId, setStructureId] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [issueDate, setIssueDate] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [dueDate, setDueDate] = React.useState(() => {
    const due = new Date();
    due.setDate(due.getDate() + 14);
    return due.toISOString().slice(0, 10);
  });
  const [issueImmediately, setIssueImmediately] = React.useState(true);
  const [includeStationery, setIncludeStationery] = React.useState(true);
  const [carryForward, setCarryForward] = React.useState(false);
  const [carryHeadId, setCarryHeadId] = React.useState("");
  const [result, setResult] = React.useState<VoucherGenerateResult | null>(null);

  /** One named student, billed from their own page rather than a class run. */
  const single = Boolean(studentIds?.length);

  // `stationery_total` is on the structure DETAIL, not on the list row — the list is
  // a picker and does not carry per-line sums. Fetched only once a structure is
  // chosen, and usually already cached from the setup screen.
  const selected = useFeeStructure(structureId || null).data;

  // Only an ACTIVE structure can bill. Offering a draft here would produce a 422 the
  // operator cannot interpret, so drafts are filtered out and their absence is
  // explained below rather than left as a mystery.
  const billable = (structures.data?.items ?? []).filter((s) => s.status === "active");
  const sameYear = billable.filter((s) => s.academic_year === academicYear);

  // The one structure this class bills against. Only auto-resolved when there is no
  // ambiguity — a class carrying two active structures for the same year (a monthly
  // one and an annual book set, say) is a real choice, and guessing at it would bill
  // the wrong one silently.
  const resolved = classId && sameYear.length === 1 ? sameYear[0] : null;

  // Runs on open and again after a run is reset, so "generate more" does not drop
  // back to an empty picker the operator has to re-answer.
  React.useEffect(() => {
    if (open && resolved && !structureId) setStructureId(resolved.id);
  }, [open, resolved, structureId]);

  function reset() {
    setResult(null);
    setStructureId("");
    setDescription("");
    setIncludeStationery(true);
    setCarryForward(false);
    setCarryHeadId("");
  }

  function close() {
    onOpenChange(false);
    // After the exit animation, so the panel does not visibly change on the way out.
    window.setTimeout(reset, 200);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!structureId || !description.trim()) return;
    const outcome = await generate.mutateAsync({
      structure_id: structureId,
      // Still `period_label` on the wire: this string is what a re-run is
      // deduped against and what the register groups by, which is exactly the
      // job it has always done. Only the question put to the operator changed.
      period_label: description.trim(),
      issue_date: issueDate,
      due_date: dueDate,
      issue_immediately: issueImmediately,
      include_stationery: includeStationery,
      carry_forward_dues: carryForward,
      ...(carryForward ? { carry_forward_head_id: carryHeadId } : {}),
      ...(studentIds?.length ? { student_ids: studentIds } : {}),
    });
    setResult(outcome);
  }

  const dueBeforeIssue = dueDate < issueDate;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-lg">
        {result ? (
          <>
            <DialogHeader>
              <DialogTitle>
                {result.created} challan{result.created === 1 ? "" : "s"} generated
              </DialogTitle>
              <DialogDescription>
                {result.skipped.length === 0
                  ? single
                    ? `${studentName ?? "The student"} was billed for this period.`
                    : "Every student in the class was billed."
                  : `${result.skipped.length} student${result.skipped.length === 1 ? " was" : "s were"} skipped.`}
              </DialogDescription>
            </DialogHeader>

            {result.truncated ? (
              <p className="flex items-start gap-2 rounded-md bg-warning/15 px-3 py-2 text-sm">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>
                  This run hit the 500-student cap and stopped there. Filter by section and
                  run it again for the rest.
                </span>
              </p>
            ) : null}

            {result.skipped.length > 0 ? (
              <div className="max-h-56 overflow-y-auto rounded-md border border-border">
                <ul className="divide-y divide-border text-sm">
                  {result.skipped.map((skip) => (
                    <li key={skip.student_id} className="flex justify-between gap-3 px-3 py-2">
                      <span className="font-mono text-xs">{skip.admission_number}</span>
                      <span className="text-xs text-muted-foreground">{skip.reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <DialogFooter>
              {single ? null : (
                <Button variant="outline" onClick={reset}>
                  Generate more
                </Button>
              )}
              <Button onClick={close}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={submit} className="grid gap-4" noValidate>
            <DialogHeader>
              <DialogTitle>{single ? "Generate a challan" : "Generate challans"}</DialogTitle>
              <DialogDescription>
                {single
                  ? `Bills ${studentName ?? "this student"} alone for one period, against the structure you pick. If they are already billed for it they are skipped, not billed twice.`
                  : "Bills every active student in the class for one period. Anyone already billed for it is skipped, not billed twice."}
              </DialogDescription>
            </DialogHeader>

            {resolved ? (
              /* Nothing to ask: this class has exactly one active structure for the
                 year. Stated rather than hidden — the operator still has to be able
                 to see WHICH fees are about to be billed before they commit. */
              <div className="rounded-md border border-border bg-muted/40 px-3 py-2.5 text-sm">
                <span className="font-medium">{resolved.name}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {className
                    ? `The active structure for ${className}, ${academicYear}.`
                    : `The active structure for this class, ${academicYear}.`}
                </span>
              </div>
            ) : (
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Fee structure</span>
                <NativeSelect
                  value={structureId}
                  onChange={(event) => setStructureId(event.target.value)}
                  required
                >
                  <option value="">Choose a structure…</option>
                  {sameYear.map((structure) => (
                    <option key={structure.id} value={structure.id}>
                      {structure.name}
                    </option>
                  ))}
                </NativeSelect>
                {structures.isSuccess && sameYear.length === 0 ? (
                  <span className="text-xs text-muted-foreground">
                    {classId ? (
                      <>
                        {className ?? "This class"} has no active structure for{" "}
                        {academicYear}. One has to be created for the class and activated
                        before it can bill — do that under Heads &amp; structures.
                      </>
                    ) : (
                      <>
                        No active structure for {academicYear}. A structure has to be
                        activated before it can bill — do that under Heads &amp;
                        structures.
                      </>
                    )}
                  </span>
                ) : null}
                {/* An unassigned student cannot be resolved to a class, and the
                    backend applies `student_ids` ON TOP of the structure's class —
                    so they would be silently SKIPPED by the run rather than billed
                    against whatever was picked here. Said before the run, not after
                    it, because a skip report nobody expected reads as a bug. */}
                {single && !classId ? (
                  <span className="text-xs text-warning-foreground dark:text-warning">
                    {studentName ?? "This student"} is not assigned to a class, so no
                    structure applies to them and this run would skip them. Assign a class
                    and section first.
                  </span>
                ) : null}
                {/* Two active structures for one class is a real choice, not an
                    oversight, so it is put to the operator rather than guessed. */}
                {classId && sameYear.length > 1 ? (
                  <span className="text-xs text-muted-foreground">
                    {className ?? "This class"} has more than one active structure for{" "}
                    {academicYear}.
                  </span>
                ) : null}
              </label>
            )}

            {/* =====================================================================
                WHAT THIS CHALLAN IS FOR, IN THE OPERATOR'S OWN WORDS
                =====================================================================
                  This is the string a parent reads on the printed challan, the one
                  the register groups by, and the one a re-run is deduped against —
                  billing the same student the same description twice is what "already
                  billed" means. Asking for a period CODE made all three of those
                  jobs harder: "2026-08" tells a parent nothing, and an office that
                  types "Aug 2026" one month and "2026-08" the next splits its own
                  register in two without noticing.

                  So it asks for a description instead. Consistency still matters —
                  it is what stops the same bill going out twice — but a sentence
                  people can read is far easier to keep consistent than a code they
                  have to remember the shape of. */}
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Description</span>
              <Input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="August 2026 fees, Term 1 fees, Annual book set…"
                required
              />
              <span className="text-xs text-muted-foreground">
                Printed on the challan and shown in the register. Billing the same student
                the same description twice is treated as a duplicate and skipped, so keep
                the wording consistent from one month to the next.
              </span>
            </label>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Issue date</span>
                <Input
                  type="date"
                  value={issueDate}
                  onChange={(event) => setIssueDate(event.target.value)}
                  required
                />
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">Due date</span>
                <Input
                  type="date"
                  value={dueDate}
                  onChange={(event) => setDueDate(event.target.value)}
                  aria-invalid={dueBeforeIssue || undefined}
                  required
                />
                {dueBeforeIssue ? (
                  <span className="text-xs text-destructive">
                    The due date cannot be before the issue date.
                  </span>
                ) : null}
              </label>
            </div>

            {/* =====================================================================
                THE ONE SWITCH THAT COSTS A PARENT MONEY IF IT IS WRONG
                =====================================================================
                  A structure holding an annual book set would re-bill those books on
                  every monthly run — twelve times the books. Only offered when the
                  chosen structure actually carries stationery, so the ordinary
                  fees-only run is not asked a question it has no stake in. */}
            {selected && Number(selected.stationery_total ?? 0) > 0 ? (
              <label className="flex items-start gap-2.5 text-sm">
                <input
                  type="checkbox"
                  checked={includeStationery}
                  onChange={(event) => setIncludeStationery(event.target.checked)}
                  className="mt-0.5 size-4 rounded border-input"
                />
                <span>
                  Include this structure&rsquo;s stationery
                  <span className="block text-xs text-muted-foreground">
                    Turn this off for the monthly runs of a structure whose books or
                    uniform are meant to be billed once a year — otherwise every month
                    charges them again.
                  </span>
                </span>
              </label>
            ) : null}

            {/* =====================================================================
                THE SWITCH THAT CANCELS OTHER CHALLANS
                =====================================================================
                  Consolidation does not just add a line: the older challans it
                  absorbs are voided, so a family holds one payable document instead
                  of three. That is a change to paper somebody may already have, so
                  the copy names the cancellation rather than the feature — and the
                  cancellation itself waits until these challans are ISSUED, which is
                  what makes generating drafts a reversible act. */}
            <div className="grid gap-2">
              <label className="flex items-start gap-2.5 text-sm">
                <input
                  type="checkbox"
                  checked={carryForward}
                  onChange={(event) => setCarryForward(event.target.checked)}
                  className="mt-0.5 size-4 rounded border-input"
                />
                <span>
                  Carry unpaid dues onto {single ? "this challan" : "these challans"}
                  <span className="block text-xs text-muted-foreground">
                    Bills what is still owed as a line on the new challan and cancels
                    the older ones it absorbs. A challan that has taken part payment is
                    never absorbed — its receipt points at it.
                  </span>
                </span>
              </label>
              {carryForward ? (
                <label className="ms-6 grid gap-1.5 text-sm">
                  <span className="text-xs font-medium">Bill those dues under</span>
                  <NativeSelect
                    value={carryHeadId}
                    onChange={(event) => setCarryHeadId(event.target.value)}
                  >
                    <option value="">Choose a fee head…</option>
                    {(heads.data?.items ?? [])
                      .filter((head) => head.is_active)
                      .map((head) => (
                        <option key={head.id} value={head.id}>
                          {head.name}
                        </option>
                      ))}
                  </NativeSelect>
                </label>
              ) : null}
            </div>

            {canCollect ? (
              <label className="flex items-start gap-2.5 text-sm">
                <input
                  type="checkbox"
                  checked={issueImmediately}
                  onChange={(event) => setIssueImmediately(event.target.checked)}
                  className="mt-0.5 size-4 rounded border-input"
                />
                <span>
                  Issue straight away
                  <span className="block text-xs text-muted-foreground">
                    Leave this off to generate drafts you can check before they count as
                    billed. A draft collects no money.
                  </span>
                </span>
              </label>
            ) : null}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  generate.isPending ||
                  !structureId ||
                  !description.trim() ||
                  dueBeforeIssue ||
                  // The server refuses the pairing too, but a disabled button beats a
                  // 422 the operator has to decode mid-run.
                  (carryForward && !carryHeadId)
                }
              >
                {generate.isPending ? "Generating…" : "Generate"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
