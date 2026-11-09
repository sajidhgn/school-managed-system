"use client";

import * as React from "react";
import { Play, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/data-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  useDeleteLateFeePolicy,
  useFeeHeads,
  useLateFeePolicies,
  useRunLateFees,
  useSetLateFeePolicy,
} from "@/hooks/use-fees";
import type { LateFeeKind, LateFeePolicyRead, LateFeeRecurrence } from "@/lib/api/types";
import type { Translation } from "@/lib/i18n/catalog";
import { fill } from "@/lib/i18n/format";
import { feesSetupMessages } from "@/lib/i18n/modules/fees-setup";
import { useCatalog } from "@/lib/i18n/use-catalog";

type LateFeeCopy = Translation<(typeof feesSetupMessages)["en"]["lateFees"]>;

/**
 * The late-fee rule for one academic year, and the button that applies it now.
 *
 * =============================================================================
 * EACH FINE IS ITS OWN CHALLAN
 * =============================================================================
 *   An issued challan is never rewritten, so a fine cannot be added to the overdue
 *   one. The nightly run mints a separate challan under the head chosen here, which
 *   the family pays, the office prints and — if it was wrong — voids with a reason
 *   like any other bill. A fine is never itself fined.
 *
 * WHY A RECURRING RULE MUST HAVE A CAP
 *   Without one it keeps fining a family who has already stopped being able to pay,
 *   until the balance is beyond anything the school will collect. The API refuses an
 *   uncapped recurring rule; this form asks for the cap the moment "weekly" or
 *   "monthly" is picked, rather than letting the save fail.
 *
 * One live rule per year — saving revises it. Removing it stops future fines and
 * leaves every fine it already raised exactly where it is.
 */
export function LateFeePanel({
  academicYear,
  canIssue,
}: {
  academicYear: string;
  /** `fee:issue` — a fine is a challan, and "apply now" decides who gets one. */
  canIssue: boolean;
}) {
  const { lateFees: m, common: c } = useCatalog(feesSetupMessages);
  const policies = useLateFeePolicies(academicYear);
  const heads = useFeeHeads({ size: 100 });
  const save = useSetLateFeePolicy();
  const remove = useDeleteLateFeePolicy();
  const run = useRunLateFees();

  const [form, setForm] = React.useState<FormState | null>(null);
  const [confirmingRemove, setConfirmingRemove] = React.useState(false);

  const saved = policies.data?.[0] ?? null;

  // The saved row is the source of truth; reload the form whenever it changes.
  const stamp = saved ? `${saved.id}:${saved.updated_at}` : `none:${academicYear}`;
  const loadedStamp = React.useRef<string | null>(null);
  if (policies.isSuccess && loadedStamp.current !== stamp) {
    loadedStamp.current = stamp;
    setForm(toForm(saved, m.defaultName));
  }

  if (policies.isError) {
    return (
      <Card className="p-0">
        <ErrorState error={policies.error} onRetry={() => void policies.refetch()} />
      </Card>
    );
  }
  if (policies.isPending || form === null) return <Card className="h-72 animate-pulse" />;

  const activeHeads = (heads.data?.items ?? []).filter((head) => head.is_active);
  const recurring = form.recurrence !== "once";
  const problems = validate(form, m.problems);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (form === null || problems.length > 0) return;
    await save.mutateAsync({
      academic_year: academicYear,
      name: form.name.trim(),
      head_id: form.headId,
      kind: form.kind,
      value: Number(form.value).toFixed(2),
      grace_days: Number(form.graceDays),
      recurrence: form.recurrence,
      max_amount: form.maxAmount.trim() ? Number(form.maxAmount).toFixed(2) : null,
      min_outstanding: (form.minOutstanding.trim() ? Number(form.minOutstanding) : 0).toFixed(2),
      is_active: form.isActive,
    });
  }

  return (
    <div className="grid gap-5">
      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h3 className="font-medium">{fill(m.title, { year: academicYear })}</h3>
            <p className="text-sm text-muted-foreground">{m.intro}</p>
          </div>
          <Badge variant={saved?.is_active ? "success" : "neutral"}>
            {saved?.is_active ? c.statusOn : saved ? c.statusPaused : c.statusNotSetUp}
          </Badge>
        </div>

        {activeHeads.length === 0 && !heads.isPending ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">{m.noHeads}</p>
        ) : (
          <form onSubmit={submit} className="grid gap-5 p-5">
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                checked={form.isActive}
                onChange={(event) => setForm({ ...form, isActive: event.target.checked })}
                className="mt-0.5 size-4 rounded border-input"
              />
              <span>
                {m.enable}
                <span className="block text-xs text-muted-foreground">{m.enableHelp}</span>
              </span>
            </label>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.ruleName}</span>
                <Input
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                  maxLength={120}
                  placeholder={m.ruleNamePlaceholder}
                />
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.billFinesUnder}</span>
                <NativeSelect
                  value={form.headId}
                  onChange={(event) => setForm({ ...form, headId: event.target.value })}
                >
                  <option value="">{c.chooseHead}</option>
                  {activeHeads.map((head) => (
                    <option key={head.id} value={head.id}>
                      {head.name}
                    </option>
                  ))}
                </NativeSelect>
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.fine}</span>
                <NativeSelect
                  value={form.kind}
                  onChange={(event) =>
                    setForm({ ...form, kind: event.target.value as LateFeeKind })
                  }
                >
                  <option value="fixed">{m.kindFixed}</option>
                  <option value="percent">{m.kindPercent}</option>
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{form.kind === "percent" ? m.percent : c.amount}</span>
                <Input
                  value={form.value}
                  onChange={(event) => setForm({ ...form, value: event.target.value })}
                  inputMode="decimal"
                  placeholder={form.kind === "percent" ? "5" : "200"}
                />
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.gracePeriod}</span>
                <div className="flex items-center gap-2">
                  <Input
                    value={form.graceDays}
                    onChange={(event) => setForm({ ...form, graceDays: event.target.value })}
                    inputMode="numeric"
                    className="w-20"
                  />
                  <span className="text-sm text-muted-foreground">{m.daysAfterDue}</span>
                </div>
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.howOften}</span>
                <NativeSelect
                  value={form.recurrence}
                  onChange={(event) =>
                    setForm({ ...form, recurrence: event.target.value as LateFeeRecurrence })
                  }
                >
                  <option value="once">{m.once}</option>
                  <option value="weekly">{m.weekly}</option>
                  <option value="monthly">{m.monthly}</option>
                </NativeSelect>
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{recurring ? m.cap : m.capOptional}</span>
                <Input
                  value={form.maxAmount}
                  onChange={(event) => setForm({ ...form, maxAmount: event.target.value })}
                  inputMode="decimal"
                  placeholder={recurring ? m.capRequired : m.noCap}
                  aria-invalid={recurring && !form.maxAmount.trim()}
                />
                {recurring ? (
                  <span className="text-xs text-muted-foreground">{m.capHelp}</span>
                ) : null}
              </label>
              <label className="grid gap-1.5 text-sm">
                <span className="font-medium">{m.ignoreUnder}</span>
                <Input
                  value={form.minOutstanding}
                  onChange={(event) => setForm({ ...form, minOutstanding: event.target.value })}
                  inputMode="decimal"
                  placeholder="0"
                />
                <span className="text-xs text-muted-foreground">{m.ignoreHelp}</span>
              </label>
            </div>

            <p className="rounded-md bg-muted/50 px-3 py-2 text-sm">{describe(form, m.describe)}</p>

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" loading={save.isPending} disabled={problems.length > 0}>
                {m.saveRule}
              </Button>
              {saved ? (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setConfirmingRemove(true)}
                >
                  <Trash2 className="size-4" aria-hidden />
                  {m.removeRule}
                </Button>
              ) : null}
              {problems.length > 0 ? (
                <span className="text-xs text-destructive">{problems[0]}</span>
              ) : null}
            </div>
          </form>
        )}
      </Card>

      {saved && canIssue ? (
        <Card className="flex flex-wrap items-center gap-3 p-5">
          <Button
            variant="outline"
            loading={run.isPending}
            disabled={!saved.is_active}
            onClick={() => run.mutate(academicYear)}
          >
            <Play className="size-4" aria-hidden />
            {m.applyNow}
          </Button>
          <span className="text-xs text-muted-foreground">
            {saved.is_active ? m.applyNowHelp : m.turnOnToApply}
          </span>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmingRemove}
        onOpenChange={setConfirmingRemove}
        title={m.removeTitle}
        description={m.removeDescription}
        confirmLabel={m.removeRule}
        variant="destructive"
        loading={remove.isPending}
        onConfirm={async () => {
          if (!saved) return;
          await remove.mutateAsync(saved.id);
          setConfirmingRemove(false);
        }}
      />
    </div>
  );
}

type FormState = {
  isActive: boolean;
  name: string;
  headId: string;
  kind: LateFeeKind;
  /** Strings while typing — see BillingAutomationPanel. */
  value: string;
  graceDays: string;
  recurrence: LateFeeRecurrence;
  maxAmount: string;
  minOutstanding: string;
};

/** `defaultName` starts a new rule off with a name in the viewer's language. */
function toForm(policy: LateFeePolicyRead | null, defaultName: string): FormState {
  return {
    isActive: policy?.is_active ?? true,
    name: policy?.name ?? defaultName,
    headId: policy?.head_id ?? "",
    kind: policy?.kind ?? "fixed",
    value: policy ? trimZeros(policy.value) : "",
    graceDays: String(policy?.grace_days ?? 0),
    recurrence: policy?.recurrence ?? "once",
    maxAmount: policy?.max_amount ? trimZeros(policy.max_amount) : "",
    minOutstanding:
      policy && Number(policy.min_outstanding) > 0 ? trimZeros(policy.min_outstanding) : "",
  };
}

/** Mirrors `LateFeePolicyCreate`'s validators, so the button explains before the API refuses. */
function validate(form: FormState, copy: LateFeeCopy["problems"]): string[] {
  const problems: string[] = [];
  const value = Number(form.value);
  const grace = Number(form.graceDays);
  if (!form.name.trim()) problems.push(copy.name);
  if (!form.headId) problems.push(copy.head);
  if (!form.value.trim() || !Number.isFinite(value) || value <= 0) problems.push(copy.value);
  else if (form.kind === "percent" && value > 100) problems.push(copy.percent);
  if (!Number.isInteger(grace) || grace < 0 || grace > 365) problems.push(copy.grace);
  if (form.recurrence !== "once") {
    const cap = Number(form.maxAmount);
    if (!form.maxAmount.trim() || !Number.isFinite(cap) || cap <= 0)
      problems.push(copy.capRequired);
  } else if (form.maxAmount.trim() && !(Number(form.maxAmount) > 0)) {
    problems.push(copy.capPositive);
  }
  if (form.minOutstanding.trim() && !(Number(form.minOutstanding) >= 0))
    problems.push(copy.minimum);
  return problems;
}

/**
 * The rule read back as one sentence, so the owner can check it says what they meant.
 *
 * Each slot is a whole phrase from the catalog, and the sentence around them is a
 * template too — with and without the cap — so the word order is the language's own.
 */
function describe(form: FormState, copy: LateFeeCopy["describe"]): string {
  const value = form.value || "…";
  const fine = fill(form.kind === "percent" ? copy.finePercent : copy.fineFixed, { value });
  const grace = Number(form.graceDays) || 0;
  const when =
    grace > 0
      ? fill(grace === 1 ? copy.whenDaysOne : copy.whenDaysMany, { days: grace })
      : copy.whenNextDay;
  const often =
    form.recurrence === "once"
      ? copy.once
      : form.recurrence === "weekly"
        ? copy.weekly
        : copy.monthly;
  return form.maxAmount.trim()
    ? fill(copy.sentenceCapped, { fine, often, when, cap: form.maxAmount })
    : fill(copy.sentence, { fine, often, when });
}

function trimZeros(value: string): string {
  return value.replace(/\.00$/, "");
}
