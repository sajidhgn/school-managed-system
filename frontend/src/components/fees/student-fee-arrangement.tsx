"use client";

import * as React from "react";
import { Check, MoreHorizontal, Plus, RotateCcw, X } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/data-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useFeeHeads,
  useRemoveStructureItem,
  useRemoveStudentFeeAssignment,
  useSetStudentFeeAssignment,
  useStudentFeeProfile,
} from "@/hooks/use-fees";
import { fill } from "@/lib/i18n/format";
import { feesStudentMessages } from "@/lib/i18n/modules/fees-student";
import { useCatalog } from "@/lib/i18n/use-catalog";

/**
 * What THIS student is charged, as opposed to what their class is.
 *
 * =============================================================================
 * THE SCREEN SHOWS THE WORKING, NOT JUST THE ANSWER
 * =============================================================================
 *   Every line is tagged with where it came from — `Class` for the structure every
 *   student in the year group inherits, `This student` for an arrangement that
 *   belongs to this child alone, `Custom rate` for a class line repriced for them.
 *
 *   That tag is the whole point of the layout. Without it an operator looking at
 *   "Tuition 5,000" has no way to know whether changing it affects one child or two
 *   hundred, and the day they guess wrong they reprice a whole grade.
 *
 * WHY EDITING A CLASS LINE DOES NOT TOUCH THE CLASS, AND DELETING ONE DOES
 *   Editing a class line does not write to the structure — it records an OVERRIDE
 *   for this child, which is a different fact ("Ali pays a different tuition") and
 *   is stored as one. The structure keeps its number and the rest of the grade keeps
 *   paying it; the row simply re-tags itself `Custom rate` so the departure stays
 *   visible, and "back to class rate" deletes the override rather than typing the
 *   old number back in.
 *
 *   DELETING a class line is the exception, and the only one on the screen: there is
 *   no per-student copy of it to destroy, so the delete goes to the structure and
 *   takes the line off every student in the class. That is a real consequence
 *   reached from one child's page, which is why it is the single action here whose
 *   dialog names the structure and says "every student" before the button does
 *   anything — and why the per-student alternative is offered in the same menu,
 *   under a name that is not "delete".
 *
 * WHY THE ACTIONS ARE A MENU OF WORDS AND NOT A ROW OF ICONS
 *   Deleting a class line and deleting this student's own line are the same gesture
 *   on screen and completely different records underneath — one writes a standing
 *   "do not charge", the other destroys an arrangement. A trash icon says the same
 *   thing in both places. Naming each action, per row, is what lets an operator read
 *   the consequence before they commit to it rather than after.
 *
 * WHY DELETIONS ASK AND EDITS DO NOT
 *   An edit is visible in the row the moment it lands and is corrected by editing
 *   again. A deletion makes the line disappear, so the thing that would tell you it
 *   was a mistake is exactly what is gone — and a stopped charge costs the school
 *   money every month until somebody notices. Those get a confirm; putting a student
 *   back on a line does not, because it restores the default rather than destroying
 *   anything.
 *
 * WHY A STUDENT WITH NO ARRANGEMENTS SHOWS AN EMPTY LIST AND NOT AN EMPTY SCREEN
 *   The common case is a student billed exactly their class structure, and that is
 *   worth SEEING — it is the confirmation that a newly admitted child is already
 *   being billed correctly without anyone having typed anything. An empty state
 *   here would imply something still needs doing.
 */
export function StudentFeeArrangement({
  studentId,
  academicYear,
  canManage,
}: {
  studentId: string;
  academicYear: string;
  /** `fee:manage`. Reading is `fee:read` — the panel above already gates that. */
  canManage: boolean;
}) {
  const { arrangement: m, deletion: deletionCopy } = useCatalog(feesStudentMessages);
  const profile = useStudentFeeProfile(studentId, academicYear);
  const heads = useFeeHeads({ size: 100 });
  const setAssignment = useSetStudentFeeAssignment();
  const removeAssignment = useRemoveStudentFeeAssignment();
  // Reaches PAST this student, into the structure their whole class is billed from.
  // Held here rather than only on the fee-setup screen because "delete this line"
  // has to mean deleted — see `deletion.structure` in
  // `lib/i18n/modules/fees-student.ts` for what the operator is told.
  const removeStructureItem = useRemoveStructureItem();

  const [adding, setAdding] = React.useState(false);
  const [headId, setHeadId] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [note, setNote] = React.useState("");

  /** The row being edited in place, and the draft of what it will become. */
  const [editing, setEditing] = React.useState<EditDraft | null>(null);
  /** The deletion awaiting confirmation. Deletions are the only asking actions. */
  const [confirming, setConfirming] = React.useState<PendingDeletion | null>(null);

  const money = React.useMemo(
    () =>
      new Intl.NumberFormat("en-PK", {
        style: "currency",
        currency: "PKR",
        maximumFractionDigits: 0,
      }),
    [],
  );

  if (profile.isError) {
    return (
      <Card className="mt-3 p-0">
        <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />
      </Card>
    );
  }
  if (profile.isPending) return <Card className="mt-3 h-40 animate-pulse" />;

  const data = profile.data;
  const arranged = new Set(data.assignments.map((a) => a.head_id));
  const onClass = new Set(data.base.map((line) => line.head_id));

  // The picker offers only heads that are neither already arranged nor priced by the
  // class. A class head is adjusted on its own row — where the amount it currently
  // bills is on screen next to the control that changes it — rather than by being
  // re-picked out of a list that cannot show what it costs today.
  const available = (heads.data?.items ?? []).filter(
    (head) => head.is_active && !arranged.has(head.id) && !onClass.has(head.id),
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!headId || !isValidAmount(amount)) return;
    await setAssignment.mutateAsync({
      studentId,
      body: {
        head_id: headId,
        academic_year: academicYear,
        mode: "added",
        amount: amount.trim() || "0",
        ...(note.trim() ? { note: note.trim() } : {}),
      },
    });
    setAdding(false);
    setHeadId("");
    setAmount("");
    setNote("");
  }

  /** Save an in-place edit. The mode carries which KIND of departure this is. */
  async function saveEdit() {
    if (!editing || !isValidAmount(editing.amount)) return;
    await setAssignment.mutateAsync({
      studentId,
      body: {
        head_id: editing.headId,
        academic_year: academicYear,
        mode: editing.mode,
        amount: editing.amount.trim() || "0",
        // Sent even when cleared: the PUT rewrites the whole arrangement, so an
        // omitted note would leave the old one standing on a row that no longer
        // shows it — the note says WHY the rate is what it is, and one describing
        // a rate that has since changed is worse than none.
        note: editing.note.trim() || null,
      },
    });
    setEditing(null);
  }

  const excludedHeads = data.assignments.filter((a) => a.mode === "excluded");
  const busy =
    setAssignment.isPending || removeAssignment.isPending || removeStructureItem.isPending;

  return (
    <>
      <Card className="mt-3 overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
          <div className="min-w-0">
            <h3 className="text-sm font-medium">{m.title}</h3>
            <p className="text-xs text-muted-foreground">
              {data.structure_name
                ? fill(m.structureLine, { name: data.structure_name, year: academicYear })
                : fill(m.noStructure, { year: academicYear })}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm tabular-nums">
              <span className="text-muted-foreground">{m.perPeriod} </span>
              <span className="font-semibold">
                {money.format(Number(data.effective_total))}
              </span>
            </span>
            {canManage && available.length > 0 ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setAdding((open) => !open);
                  setEditing(null);
                }}
              >
                <Plus className="size-4" aria-hidden />
                {m.adjust}
              </Button>
            ) : null}
          </div>
        </div>

        {data.effective.length === 0 && excludedHeads.length === 0 ? (
          <p className="px-5 py-6 text-center text-sm text-muted-foreground">
            {data.structure_id ? m.nothingPriced : m.noActiveStructure}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colHead}</TableHead>
                  <TableHead>{m.colSource}</TableHead>
                  <TableHead className="text-end">{m.colAmount}</TableHead>
                  {canManage ? <TableHead className="w-12" /> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.effective.map((line) => {
                  const assignment = data.assignments.find((a) => a.head_id === line.head_id);
                  const own = line.source === "student";
                  const overridden = line.source === "override";
                  const discounted = line.source === "discount";
                  const editingThis = editing?.headId === line.head_id;
                  const discount = Number(line.discount_amount ?? 0);

                  return (
                    <React.Fragment key={line.head_id}>
                      <TableRow>
                        <TableCell>
                          {line.head_name}
                          {assignment?.note ? (
                            <span className="ms-2 text-xs text-muted-foreground">
                              {assignment.note}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <Badge variant={own || overridden ? "success" : "neutral"}>
                            {own
                              ? m.sourceStudent
                              : overridden
                                ? m.sourceOverride
                                : discounted
                                  ? m.sourceDiscount
                                  : m.sourceClass}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-end tabular-nums">
                          {money.format(Number(line.net_amount ?? line.amount))}
                          {/* The gross and the remission are shown separately, never
                              netted into one number: a reduction that looks like a
                              lower price is one nobody can see they were granted. */}
                          {discount > 0 ? (
                            <span className="block text-xs font-normal text-muted-foreground">
                              {fill(m.lessDiscount, {
                                gross: money.format(Number(line.amount)),
                                discount: money.format(discount),
                              })}
                              {line.concession_name ? ` · ${line.concession_name}` : ""}
                            </span>
                          ) : null}
                        </TableCell>
                        {canManage ? (
                          <TableCell className="text-end">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  disabled={busy}
                                  aria-label={fill(m.actionsFor, { name: line.head_name })}
                                >
                                  <MoreHorizontal aria-hidden />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="min-w-52">
                                {/* A concession is priced by a scheme, a percent or a
                                    flat sum, and only one of the three at a time —
                                    editing it as a bare amount here would silently
                                    detach a student from the scheme paying for it. So
                                    it is deleted and re-awarded, never patched. */}
                                {discounted ? null : (
                                  <DropdownMenuItem
                                    onClick={() => {
                                      setAdding(false);
                                      setEditing({
                                        headId: line.head_id,
                                        headName: line.head_name,
                                        // A class line is repriced for this child as
                                        // an OVERRIDE; their own line stays an ADDED
                                        // one. Sending the wrong mode here would
                                        // either bill a second line or bill nothing.
                                        mode: own ? "added" : "override",
                                        amount: String(line.amount),
                                        note: assignment?.note ?? "",
                                      });
                                    }}
                                  >
                                    {own ? m.editAmount : m.editRate}
                                  </DropdownMenuItem>
                                )}

                                {/* Two different undos on a repriced or discounted
                                    line, and they are not interchangeable: one drops
                                    the arrangement and bills the class rate again,
                                    the other stops billing the head at all. */}
                                {overridden || discounted ? (
                                  <DropdownMenuItem
                                    onClick={() =>
                                      setConfirming({
                                        headId: line.head_id,
                                        headName: line.head_name,
                                        kind: overridden ? "override" : "discount",
                                        hasAssignment: true,
                                      })
                                    }
                                  >
                                    {overridden ? m.backToClassRate : m.deleteConcession}
                                  </DropdownMenuItem>
                                ) : null}

                                {/* Keeping the whole class on a head while taking ONE
                                    child off it is the common case — a child who walks
                                    to school on a structure that prices transport. It
                                    is deliberately NOT called a delete: nothing is
                                    destroyed, and the head keeps billing everyone
                                    else. The delete below is the one that removes it. */}
                                {own ? null : (
                                  <DropdownMenuItem
                                    onClick={() =>
                                      setConfirming({
                                        headId: line.head_id,
                                        headName: line.head_name,
                                        kind: "exclude",
                                        hasAssignment: Boolean(assignment),
                                      })
                                    }
                                  >
                                    {m.leaveOff}
                                  </DropdownMenuItem>
                                )}

                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  destructive
                                  // A student's own charge is theirs alone, so deleting
                                  // it is local. A class line lives on the STRUCTURE,
                                  // so the only honest delete of it is the structure's
                                  // — which reprices every student in the class. The
                                  // dialog says which of the two is about to happen,
                                  // and the item is disabled outright when there is no
                                  // structure to delete from.
                                  disabled={!own && !data.structure_id}
                                  onClick={() =>
                                    setConfirming({
                                      headId: line.head_id,
                                      headName: line.head_name,
                                      kind: own ? "added" : "structure",
                                      hasAssignment: Boolean(assignment),
                                    })
                                  }
                                >
                                  {own ? m.deleteCharge : m.deleteFromStructure}
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        ) : null}
                      </TableRow>

                      {editingThis && editing ? (
                        <TableRow className="bg-muted/30 hover:bg-muted/30">
                          <TableCell colSpan={4} className="py-3">
                            <form
                              onSubmit={(event) => {
                                event.preventDefault();
                                void saveEdit();
                              }}
                              className="flex flex-wrap items-end gap-2"
                            >
                              <label className="grid w-32 gap-1.5 text-sm">
                                <span className="text-xs font-medium">{m.amount}</span>
                                <Input
                                  autoFocus
                                  value={editing.amount}
                                  onChange={(event) =>
                                    setEditing({ ...editing, amount: event.target.value })
                                  }
                                  inputMode="decimal"
                                  placeholder="0"
                                />
                              </label>
                              <label className="grid w-56 gap-1.5 text-sm">
                                <span className="text-xs font-medium">{m.note}</span>
                                <Input
                                  value={editing.note}
                                  onChange={(event) =>
                                    setEditing({ ...editing, note: event.target.value })
                                  }
                                  placeholder={m.notePlaceholder}
                                />
                              </label>
                              <Button
                                type="submit"
                                size="sm"
                                variant="outline"
                                loading={setAssignment.isPending}
                                disabled={!isValidAmount(editing.amount)}
                              >
                                <Check className="size-4" aria-hidden />
                                {m.saveRate}
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                onClick={() => setEditing(null)}
                              >
                                <X className="size-4" aria-hidden />
                                {m.cancel}
                              </Button>
                              <p className="w-full text-xs text-muted-foreground">
                                {editing.mode === "override"
                                  ? fill(m.overrideHelp, {
                                      amount: money.format(Number(line.amount)),
                                      name: data.student_name,
                                    })
                                  : m.ownHelp}{" "}
                                {m.appliesNext}
                              </p>
                            </form>
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </React.Fragment>
                  );
                })}

                {/* Exclusions have no amount and no effective line, so they would
                    otherwise be invisible — and "why is Transport missing?" is exactly
                    the question this card exists to answer. */}
                {excludedHeads.map((assignment) => (
                  <TableRow key={assignment.id} className="opacity-60">
                    <TableCell className="line-through">{assignment.head_name}</TableCell>
                    <TableCell>
                      <Badge variant="neutral">{m.notCharged}</Badge>
                    </TableCell>
                    <TableCell className="text-end text-sm text-muted-foreground">—</TableCell>
                    {canManage ? (
                      <TableCell className="text-end">
                        {/* Unconfirmed, unlike the deletions above: this puts the
                            student back on what their class pays, so the worst case
                            is a line reappearing where everyone can see it. */}
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={fill(m.chargeAgain, { name: assignment.head_name })}
                          disabled={busy}
                          onClick={() =>
                            removeAssignment.mutate({
                              studentId,
                              headId: assignment.head_id,
                              academicYear,
                            })
                          }
                        >
                          <RotateCcw className="size-4" aria-hidden />
                        </Button>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {canManage && adding ? (
          <form
            onSubmit={submit}
            className="flex flex-wrap items-end gap-2 border-t border-border bg-muted/30 p-4"
          >
            <label className="grid flex-1 gap-1.5 text-sm">
              <span className="text-xs font-medium">{m.colHead}</span>
              <NativeSelect
                value={headId}
                onChange={(event) => setHeadId(event.target.value)}
              >
                <option value="">{m.choose}</option>
                {available.map((head) => (
                  <option key={head.id} value={head.id}>
                    {head.name}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="grid w-32 gap-1.5 text-sm">
              <span className="text-xs font-medium">{m.amount}</span>
              <Input
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                inputMode="decimal"
                placeholder="0"
              />
            </label>
            <label className="grid w-44 gap-1.5 text-sm">
              <span className="text-xs font-medium">{m.note}</span>
              <Input
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder={m.notePlaceholder}
              />
            </label>
            <Button
              type="submit"
              variant="outline"
              loading={setAssignment.isPending}
              disabled={!headId || !isValidAmount(amount)}
            >
              {m.addCharge}
            </Button>
            <p className="w-full text-xs text-muted-foreground">{m.addHelp}</p>
          </form>
        ) : null}
      </Card>

      {/* One dialog for every ending a line can come to. The copy differs per kind
          because the consequence does — dropping one child's charge, dropping a
          negotiated rate, and deleting a line the whole class is billed are three
          different acts that look identical on the row. */}
      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(next) => !next && setConfirming(null)}
        title={
          confirming ? fill(deletionCopy[confirming.kind].title, { name: confirming.headName }) : ""
        }
        description={
          confirming
            ? confirming.kind === "structure"
              ? fill(deletionCopy.structure.description, {
                  structure: data.structure_name ?? deletionCopy.structure.structureFallback,
                })
              : deletionCopy[confirming.kind].description
            : undefined
        }
        confirmLabel={confirming ? deletionCopy[confirming.kind].confirm : m.confirm}
        variant={
          confirming?.kind === "override" || confirming?.kind === "discount"
            ? "default"
            : "destructive"
        }
        loading={busy}
        onConfirm={async () => {
          if (!confirming) return;
          // Belt to the menu item's braces: no structure, nothing to delete from.
          // Written as its own branch rather than an `&&` on the condition, because
          // falling through to the next one would delete an ARRANGEMENT instead —
          // a different record, on a confirm the operator read as something else.
          if (confirming.kind === "structure") {
            if (!data.structure_id) {
              setConfirming(null);
              return;
            }
            // The arrangement goes FIRST, and only then the structure line. An
            // override or exclusion left behind on a head the class no longer prices
            // is invisible — it contributes nothing to a bill — right up until
            // somebody re-adds the head next year and it silently takes effect. And
            // ordering it this way means a failure leaves the structure intact rather
            // than half-deleted.
            if (confirming.hasAssignment) {
              await removeAssignment.mutateAsync({
                studentId,
                headId: confirming.headId,
                academicYear,
              });
            }
            await removeStructureItem.mutateAsync({
              id: data.structure_id,
              headId: confirming.headId,
            });
          } else if (confirming.kind === "exclude") {
            // Not a deletion, and the menu does not call it one: it REPLACES whatever
            // the head was on with a standing "do not charge", which is a record in
            // its own right and outlives the arrangement it displaces.
            await setAssignment.mutateAsync({
              studentId,
              body: {
                head_id: confirming.headId,
                academic_year: academicYear,
                mode: "excluded",
              },
            });
          } else {
            await removeAssignment.mutateAsync({
              studentId,
              headId: confirming.headId,
              academicYear,
            });
          }
          setConfirming(null);
          setEditing(null);
        }}
      />
    </>
  );
}

type EditDraft = {
  headId: string;
  headName: string;
  /** Which kind of departure is being written — see `StudentFeeAssignmentMode`. */
  mode: "added" | "override";
  amount: string;
  note: string;
};

type PendingDeletion = {
  headId: string;
  headName: string;
  kind: "added" | "override" | "discount" | "exclude" | "structure";
  /** Whether this student has their own arrangement on the head — a structure delete
   *  has to take it with them, or it outlives the line it belonged to. */
  hasAssignment: boolean;
};


/**
 * A blank box is not zero.
 *
 * Guarding the button rather than trusting the API's 422 is what keeps an operator
 * who typed "2,500" from being told "Input should be a valid decimal" — the comma is
 * how half the world writes money, and the error names a type they never chose.
 */
function isValidAmount(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0;
}
