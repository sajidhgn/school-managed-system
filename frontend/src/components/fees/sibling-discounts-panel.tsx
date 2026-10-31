"use client";

import * as React from "react";
import { Users } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data-states";
import { concessionRate } from "@/components/fees/concessions-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import {
  useApplySiblings,
  useConcessions,
  useDeleteSiblingRule,
  useFeeHeads,
  useSetSiblingRule,
  useSiblingReview,
  useSiblingRule,
} from "@/hooks/use-fees";
import {
  GUARDIAN_RELATIONSHIP_LABELS,
  type FeeSiblingRuleRead,
  type SiblingAction,
  type SiblingFamily,
  type SiblingMember,
} from "@/lib/api/types";

/** The actions a person can apply from this screen. */
const ACTIONABLE: ReadonlySet<SiblingAction> = new Set(["apply", "change", "remove"]);

function ordinal(position: number): string {
  const tens = position % 100;
  if (tens >= 11 && tens <= 13) return `${position}th`;
  return `${position}${{ 1: "st", 2: "nd", 3: "rd" }[position % 10] ?? "th"}`;
}

/**
 * Sibling discounts: the campus rule, and the families it finds.
 *
 * =============================================================================
 * THE RULE PROPOSES; A PERSON APPLIES
 * =============================================================================
 *   Families are found through the guardian registry — children who share a father,
 *   mother or legal guardian. That is far better than a surname, but it is only as
 *   good as the links staff typed, and a father linked to the wrong child would
 *   discount a stranger. So saving the rule changes nobody's fees. The review below
 *   lists each family, who pays in full (the child in the highest class), and what
 *   the rule would do for every other child; ticking and applying is what writes it.
 *
 *   The same review is how the discount follows a family over time. When an elder
 *   child leaves, the next review shows the others moving up a position, and a child
 *   with no brother or sister left shows up under "No longer eligible".
 */
export function SiblingDiscountsPanel({
  academicYear,
  onOpenConcessions,
}: {
  academicYear: string;
  onOpenConcessions: () => void;
}) {
  const rule = useSiblingRule();

  if (rule.isError) {
    return (
      <Card className="p-0">
        <ErrorState error={rule.error} onRetry={() => void rule.refetch()} />
      </Card>
    );
  }
  if (rule.isPending) return <Card className="h-64 animate-pulse" />;

  return (
    <div className="grid gap-5">
      <RuleCard rule={rule.data} onOpenConcessions={onOpenConcessions} />
      {rule.data ? <ReviewCard academicYear={academicYear} /> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The rule
// ---------------------------------------------------------------------------

interface RuleForm {
  headId: string;
  second: string;
  third: string;
  later: string;
}

function toForm(rule: FeeSiblingRuleRead | null): RuleForm {
  return {
    headId: rule?.head_id ?? "",
    second: rule?.second.id ?? "",
    third: rule?.third?.id ?? "",
    later: rule?.later?.id ?? "",
  };
}

function RuleCard({
  rule,
  onOpenConcessions,
}: {
  rule: FeeSiblingRuleRead | null;
  onOpenConcessions: () => void;
}) {
  const heads = useFeeHeads({ size: 100 });
  const concessions = useConcessions({ size: 100 });
  const save = useSetSiblingRule();
  const remove = useDeleteSiblingRule();

  const [form, setForm] = React.useState<RuleForm>(() => toForm(rule));
  const [confirmingOff, setConfirmingOff] = React.useState(false);

  // Reload from what the server stored after a save, as the automation panel does.
  const stamp = rule ? `${rule.id}:${rule.updated_at}` : "none";
  const loadedStamp = React.useRef(stamp);
  if (loadedStamp.current !== stamp) {
    loadedStamp.current = stamp;
    setForm(toForm(rule));
  }

  const activeHeads = (heads.data?.items ?? []).filter((head) => head.is_active);
  const activeSchemes = (concessions.data?.items ?? []).filter((c) => c.is_active);
  const noSchemes = concessions.isSuccess && activeSchemes.length === 0;
  const tuition = activeHeads.find((head) => head.code === "TUITION");
  const headId = form.headId || tuition?.id || "";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!headId || !form.second) return;
    await save.mutateAsync({
      head_id: headId,
      second_concession_id: form.second,
      third_concession_id: form.third || null,
      later_concession_id: form.later || null,
    });
  }

  const schemeOptions = activeSchemes.map((scheme) => (
    <option key={scheme.id} value={scheme.id}>
      {scheme.name} · {concessionRate(scheme)}
    </option>
  ));

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <h3 className="font-medium">Sibling discount rule</h3>
          <p className="text-sm text-muted-foreground">
            The child in the family&rsquo;s highest class pays in full. Each younger child
            gets the scheme for their position.
          </p>
        </div>
        <Badge variant={rule ? "success" : "neutral"}>{rule ? "On" : "Not set up"}</Badge>
      </div>

      {noSchemes ? (
        <EmptyState
          icon={Users}
          title="Create the discount schemes first"
          description="Add a scheme for each position you discount, e.g. Sibling 2nd child 10% and Sibling 3rd child 15%. Then pick them here."
          action={<Button onClick={onOpenConcessions}>Go to concessions</Button>}
        />
      ) : (
        <form onSubmit={submit} className="grid gap-5 p-5">
          <label className="grid gap-1.5 text-sm sm:max-w-xs">
            <span className="font-medium">Discount comes off</span>
            <NativeSelect
              value={headId}
              onChange={(event) => setForm({ ...form, headId: event.target.value })}
            >
              <option value="" disabled>
                Choose a fee head
              </option>
              {activeHeads.map((head) => (
                <option key={head.id} value={head.id}>
                  {head.name}
                </option>
              ))}
            </NativeSelect>
          </label>

          <div className="grid gap-4 sm:grid-cols-3">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">2nd child</span>
              <NativeSelect
                value={form.second}
                onChange={(event) => setForm({ ...form, second: event.target.value })}
              >
                <option value="" disabled>
                  Choose a scheme
                </option>
                {schemeOptions}
              </NativeSelect>
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">3rd child</span>
              <NativeSelect
                value={form.third}
                onChange={(event) => setForm({ ...form, third: event.target.value })}
              >
                <option value="">Same as 2nd child</option>
                {schemeOptions}
              </NativeSelect>
            </label>
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">4th child and later</span>
              <NativeSelect
                value={form.later}
                onChange={(event) => setForm({ ...form, later: event.target.value })}
              >
                <option value="">Same as 3rd child</option>
                {schemeOptions}
              </NativeSelect>
            </label>
          </div>

          <p className="text-xs text-muted-foreground">
            Brothers and sisters are children who share a father, mother or legal guardian
            on their student pages, at any campus. Saving changes no child&rsquo;s fees.
          </p>

          <div className="flex flex-wrap items-center justify-end gap-2">
            {rule ? (
              <Button type="button" variant="outline" onClick={() => setConfirmingOff(true)}>
                Turn off
              </Button>
            ) : null}
            <Button type="submit" disabled={save.isPending || !headId || !form.second}>
              {save.isPending ? "Saving…" : rule ? "Save rule" : "Turn on"}
            </Button>
          </div>
        </form>
      )}

      <ConfirmDialog
        open={confirmingOff}
        onOpenChange={setConfirmingOff}
        title="Turn the sibling rule off?"
        description="The review stops. Children already on a sibling scheme keep it until you take them off from their student page."
        confirmLabel="Turn off"
        loading={remove.isPending}
        onConfirm={async () => {
          await remove.mutateAsync();
          setConfirmingOff(false);
        }}
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// The review
// ---------------------------------------------------------------------------

function ReviewCard({ academicYear }: { academicYear: string }) {
  const review = useSiblingReview(academicYear, true);
  const apply = useApplySiblings();

  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [onlyActionable, setOnlyActionable] = React.useState(true);

  if (review.isError) {
    return (
      <Card className="p-0">
        <ErrorState error={review.error} onRetry={() => void review.refetch()} />
      </Card>
    );
  }
  if (review.isPending) return <Card className="h-72 animate-pulse" />;

  const data = review.data;
  const allMembers = [
    ...data.families.flatMap((family) => family.members),
    ...data.no_longer_eligible,
  ];
  const suggested = allMembers.filter((m) => m.at_this_campus && ACTIONABLE.has(m.action));
  const needsDecision = (family: SiblingFamily) =>
    family.members.some((m) => ACTIONABLE.has(m.action) || m.action === "conflict");
  const families = onlyActionable ? data.families.filter(needsDecision) : data.families;

  function toggle(studentId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(studentId)) next.delete(studentId);
      else next.add(studentId);
      return next;
    });
  }

  async function run(studentIds: string[]) {
    if (studentIds.length === 0) return;
    await apply.mutateAsync({ academic_year: academicYear, student_ids: studentIds });
    setSelected(new Set());
  }

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0">
          <h3 className="font-medium">Families · {data.academic_year}</h3>
          <p className="text-sm text-muted-foreground">
            {data.families.length} famil{data.families.length === 1 ? "y" : "ies"} with a
            child at this campus. Changes apply from the next challan generated.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {data.to_apply ? <Badge>{data.to_apply} to apply</Badge> : null}
          {data.to_remove ? <Badge variant="warning">{data.to_remove} to take off</Badge> : null}
          {data.conflicts ? (
            <Badge variant="destructive">{data.conflicts} need a decision</Badge>
          ) : null}
        </div>
      </div>

      {data.families.length === 0 && data.no_longer_eligible.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No families found yet"
          description="Families appear when two children share a father, mother or legal guardian. Link parents from each student's page (Parent portal card)."
        />
      ) : (
        <div className="grid gap-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={onlyActionable}
                onChange={(event) => setOnlyActionable(event.target.checked)}
                className="size-4 rounded border-input"
              />
              Only families that need something done
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={apply.isPending || selected.size === 0}
                onClick={() => void run([...selected])}
              >
                Apply selected ({selected.size})
              </Button>
              <Button
                size="sm"
                disabled={apply.isPending || suggested.length === 0}
                onClick={() => void run(suggested.map((m) => m.student_id))}
              >
                {apply.isPending ? "Applying…" : `Apply all suggestions (${suggested.length})`}
              </Button>
            </div>
          </div>

          {families.length === 0 && data.families.length > 0 ? (
            <p className="rounded-lg border border-dashed border-border p-4 text-center text-sm text-muted-foreground">
              Every family is up to date.
            </p>
          ) : null}

          {families.map((family) => (
            <FamilyBlock
              key={family.members.map((m) => m.student_id).join(":")}
              title={family.guardians
                .map(
                  (g) =>
                    `${g.full_name} (${g.relationships
                      .map((r) => GUARDIAN_RELATIONSHIP_LABELS[r].toLowerCase())
                      .join(", ")})`,
                )
                .join(" · ")}
              members={family.members}
              selected={selected}
              onToggle={toggle}
            />
          ))}

          {data.no_longer_eligible.length ? (
            <FamilyBlock
              title="No longer eligible: no brother or sister enrolled now"
              members={data.no_longer_eligible}
              selected={selected}
              onToggle={toggle}
            />
          ) : null}
        </div>
      )}
    </Card>
  );
}

function FamilyBlock({
  title,
  members,
  selected,
  onToggle,
}: {
  title: string;
  members: SiblingMember[];
  selected: Set<string>;
  onToggle: (studentId: string) => void;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-border">
      <h4 className="border-b border-border bg-muted/30 px-4 py-2 text-sm font-medium">
        {title}
      </h4>
      <ul className="divide-y divide-border">
        {members.map((member) => {
          const actionable = member.at_this_campus && ACTIONABLE.has(member.action);
          return (
            <li
              key={member.student_id}
              className="grid grid-cols-[1.25rem_1fr] items-start gap-3 px-4 py-3 text-sm sm:grid-cols-[1.25rem_3rem_1fr_auto]"
            >
              {actionable ? (
                <input
                  type="checkbox"
                  aria-label={`Select ${member.student_name}`}
                  checked={selected.has(member.student_id)}
                  onChange={() => onToggle(member.student_id)}
                  className="mt-0.5 size-4 rounded border-input"
                />
              ) : (
                <span aria-hidden />
              )}
              <span className="hidden text-muted-foreground tabular-nums sm:block">
                {member.position ? ordinal(member.position) : "—"}
              </span>
              <div className="min-w-0">
                <p className="font-medium">
                  {member.student_name}
                  <span className="ms-2 font-normal text-muted-foreground">
                    {member.admission_number}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground">
                  {[member.class_name, member.section_name && `Section ${member.section_name}`]
                    .filter(Boolean)
                    .join(" · ") || "Not placed in a class"}
                  {member.at_this_campus ? null : ` · ${member.campus_name}`}
                  {member.current && member.action !== "ok" ? ` · Now on ${member.current}` : null}
                </p>
                {member.reason && member.action !== "full_fee" ? (
                  <p className="mt-1 text-xs text-muted-foreground">{member.reason}</p>
                ) : null}
              </div>
              <div className="col-start-2 sm:col-start-auto">
                <ActionBadge member={member} />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function ActionBadge({ member }: { member: SiblingMember }) {
  const scheme = member.proposed_concession_name ?? "";
  switch (member.action) {
    case "full_fee":
      return <Badge variant="neutral">Pays in full</Badge>;
    case "apply":
      return <Badge>Add {scheme}</Badge>;
    case "change":
      return <Badge variant="warning">Move to {scheme}</Badge>;
    case "ok":
      return <Badge variant="success">On {scheme}</Badge>;
    case "remove":
      return <Badge variant="warning">Take off</Badge>;
    case "conflict":
      return <Badge variant="destructive">Needs a decision</Badge>;
    case "other_campus":
      return <Badge variant="outline">{member.campus_name}</Badge>;
  }
}
