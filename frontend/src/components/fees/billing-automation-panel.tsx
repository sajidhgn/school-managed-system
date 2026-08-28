"use client";

import * as React from "react";
import { CalendarClock, Play } from "lucide-react";

import { ErrorState } from "@/components/data-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  useBillingSchedule,
  useFeeHeads,
  useRunBillingSchedule,
  useSetBillingSchedule,
} from "@/hooks/use-fees";
import { formatDate } from "@/lib/utils";

/**
 * When this campus bills, without anyone having to remember.
 *
 * =============================================================================
 * THE SCREEN OWNS THE DECISION; THE SERVER OWNS THE CLOCK
 * =============================================================================
 *   Everything here is a row the owner can read and change — the day, the days to
 *   pay, drafts or issued, whether unpaid challans are carried forward. The job
 *   outside knows only that a new day has started and asks each campus whether today
 *   is its day.
 *
 *   That is why the billing day is not in a config file: a school that cannot see
 *   its own billing day cannot correct it, and the day it is wrong is a day four
 *   hundred families are billed at the wrong time.
 *
 * WHY THE TWO DANGEROUS SWITCHES ARE OFF UNTIL SOMEBODY TURNS THEM ON
 *   "Issue straight away" hands out real bills at 2am: they count as outstanding,
 *   they earn late fees, and undoing one is a void with a reason, not a delete.
 *   "Carry forward unpaid dues" CANCELS older challans as it absorbs them.
 *
 *   Both are correct settings for a school that has watched a few runs. Neither is a
 *   good thing to inherit by accident, so both default off and both say plainly what
 *   they will do rather than what they are called.
 *
 * WHY "RUN NOW" IS SAFE TO PRESS TWICE
 *   It skips the is-it-the-day test but not the has-this-period-been-generated one,
 *   and behind that, a student already holding a challan for the period is skipped by
 *   a database constraint rather than by this button's good intentions.
 */
export function BillingAutomationPanel({
  academicYear,
  canIssue,
}: {
  academicYear: string;
  /** `fee:issue`. Configuring is `fee:manage` — the page already gates that. */
  canIssue: boolean;
}) {
  const schedule = useBillingSchedule(academicYear);
  const heads = useFeeHeads({ size: 100 });
  const save = useSetBillingSchedule();
  const run = useRunBillingSchedule();

  const [form, setForm] = React.useState<FormState | null>(null);

  // The saved row is the source of truth; the draft only exists once the operator
  // starts typing. Keyed on the row's id and updated_at so a save (or a switch to a
  // different year) reloads what the server actually stored rather than leaving the
  // form showing what was typed before it was normalised.
  const stamp = schedule.data ? `${schedule.data.id}:${schedule.data.updated_at}` : "none";
  const loadedStamp = React.useRef<string | null>(null);
  if (schedule.isSuccess && loadedStamp.current !== stamp) {
    loadedStamp.current = stamp;
    setForm(toForm(schedule.data));
  }

  if (schedule.isError) {
    return (
      <Card className="p-0">
        <ErrorState error={schedule.error} onRetry={() => void schedule.refetch()} />
      </Card>
    );
  }
  if (schedule.isPending || form === null) return <Card className="h-72 animate-pulse" />;

  const saved = schedule.data;
  const activeHeads = (heads.data?.items ?? []).filter((head) => head.is_active);
  // A head must be chosen before consolidation can be saved — the server refuses the
  // pairing too, but a disabled button beats a 422 the operator has to decode.
  const incomplete = form.carryForwardDues && !form.carryForwardHeadId;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (form === null || incomplete) return;
    await save.mutateAsync({
      academic_year: academicYear,
      is_active: form.isActive,
      generate_day: Number(form.generateDay),
      due_day_offset: Number(form.dueDayOffset),
      issue_immediately: form.issueImmediately,
      include_stationery: form.includeStationery,
      carry_forward_dues: form.carryForwardDues,
      carry_forward_head_id: form.carryForwardDues ? form.carryForwardHeadId : null,
    });
  }

  return (
    <div className="grid gap-5">
      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h3 className="font-medium">Automatic monthly challans</h3>
            <p className="text-sm text-muted-foreground">
              Every active structure for {academicYear}, billed on the same day each
              month, without anyone opening this page.
            </p>
          </div>
          <Badge variant={saved?.is_active ? "success" : "neutral"}>
            {saved?.is_active ? "On" : saved ? "Paused" : "Not set up"}
          </Badge>
        </div>

        <form onSubmit={submit} className="grid gap-5 p-5">
          <label className="flex items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              checked={form.isActive}
              onChange={(event) => setForm({ ...form, isActive: event.target.checked })}
              className="mt-0.5 size-4 rounded border-input"
            />
            <span>
              Generate challans automatically
              <span className="block text-xs text-muted-foreground">
                Turning this off keeps everything below, so resuming next term is one
                click rather than a form to fill in again.
              </span>
            </span>
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Bill on day</span>
              <NativeSelect
                value={form.generateDay}
                onChange={(event) => setForm({ ...form, generateDay: event.target.value })}
              >
                {Array.from({ length: 28 }, (_, index) => index + 1).map((day) => (
                  <option key={day} value={day}>
                    {day}
                    {ordinal(day)} of the month
                  </option>
                ))}
              </NativeSelect>
              {/* The cap is a decision, not a limitation, so it is explained where
                  somebody looking for the 31st will actually read it. */}
              <span className="text-xs text-muted-foreground">
                The list stops at 28 on purpose. A school that picks the 31st means
                the month end — but February would quietly move that to the 28th while
                the family&rsquo;s standing bank instruction did not move with it.
              </span>
            </label>

            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">Payable within</span>
              <div className="flex items-center gap-2">
                <Input
                  value={form.dueDayOffset}
                  onChange={(event) => setForm({ ...form, dueDayOffset: event.target.value })}
                  inputMode="numeric"
                  className="w-24"
                />
                <span className="text-sm text-muted-foreground">days of issue</span>
              </div>
              <span className="text-xs text-muted-foreground">
                Sets the due date on every challan the run produces, and with it the
                date late fees start counting from.
              </span>
            </label>
          </div>

          <div className="grid gap-3 rounded-lg border border-border bg-muted/30 p-4">
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                checked={form.issueImmediately}
                onChange={(event) =>
                  setForm({ ...form, issueImmediately: event.target.checked })
                }
                className="mt-0.5 size-4 rounded border-input"
              />
              <span>
                Issue them straight away, without anyone checking
                <span className="block text-xs text-muted-foreground">
                  Off means the run leaves drafts for someone to read and issue —
                  which is the safer place to start. An issued challan counts towards
                  outstanding, earns late fees, and is cancelled by voiding it with a
                  reason, never deleted.
                </span>
              </span>
            </label>

            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                checked={form.includeStationery}
                onChange={(event) =>
                  setForm({ ...form, includeStationery: event.target.checked })
                }
                className="mt-0.5 size-4 rounded border-input"
              />
              <span>
                Include each structure&rsquo;s stationery every month
                <span className="block text-xs text-muted-foreground">
                  Usually wrong for a monthly run: a book or uniform set is billed once
                  at admission, and leaving this on charges it twelve times a year.
                </span>
              </span>
            </label>
          </div>

          {/* =====================================================================
              THE SETTING THAT CANCELS OTHER CHALLANS
              =====================================================================
                Consolidation is the only thing on this screen that changes documents
                a family is already holding, so it gets its own block, its own head
                picker, and copy that names the cancellation rather than the feature.*/}
          <div className="grid gap-3 rounded-lg border border-border p-4">
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                checked={form.carryForwardDues}
                onChange={(event) =>
                  setForm({ ...form, carryForwardDues: event.target.checked })
                }
                className="mt-0.5 size-4 rounded border-input"
              />
              <span>
                Carry unpaid dues onto the new challan
                <span className="block text-xs text-muted-foreground">
                  The new challan bills what is still owed as its own line, and the
                  older challans it absorbs are cancelled — so a family has one
                  document to pay instead of three. A challan that has already taken
                  part payment is never absorbed: its receipt points at it, and its
                  balance keeps being printed beside the total instead.
                </span>
              </span>
            </label>

            {form.carryForwardDues ? (
              <label className="grid gap-1.5 text-sm sm:max-w-sm">
                <span className="font-medium">Bill those dues under</span>
                <NativeSelect
                  value={form.carryForwardHeadId ?? ""}
                  onChange={(event) =>
                    setForm({ ...form, carryForwardHeadId: event.target.value || null })
                  }
                >
                  <option value="">Choose a fee head…</option>
                  {activeHeads.map((head) => (
                    <option key={head.id} value={head.id}>
                      {head.name}
                    </option>
                  ))}
                </NativeSelect>
                <span className="text-xs text-muted-foreground">
                  A head like &ldquo;Previous dues&rdquo; or &ldquo;Arrears&rdquo;. It
                  has to be a head so the carried money appears in the collection
                  summary beside tuition and transport, rather than being a figure with
                  no home in any report the office already runs.
                </span>
              </label>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" loading={save.isPending} disabled={incomplete}>
              Save schedule
            </Button>
            {incomplete ? (
              <span className="text-xs text-destructive">
                Choose the head the carried dues are billed under.
              </span>
            ) : null}
          </div>
        </form>
      </Card>

      {saved ? (
        <Card className="grid gap-4 p-5">
          <h3 className="font-medium">Runs</h3>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">Next run</dt>
              <dd className="flex items-center gap-1.5">
                <CalendarClock className="size-4 text-muted-foreground" aria-hidden />
                {saved.next_run_on ? formatDate(saved.next_run_on) : "Paused"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Last run</dt>
              {/* A run that created 0 and skipped 400 is a WORKING run — everyone was
                  already billed. A run that never happened is a different fact, and
                  showing both as "0 challans" would hide the one worth acting on. */}
              <dd>
                {saved.last_run_at ? (
                  <>
                    {formatDate(saved.last_run_at)} · {saved.last_run_period}
                    <span className="block text-xs text-muted-foreground">
                      {saved.last_run_created} generated, {saved.last_run_skipped} already
                      billed
                    </span>
                  </>
                ) : (
                  <span className="text-muted-foreground">Has not run yet</span>
                )}
              </dd>
            </div>
          </dl>

          {canIssue ? (
            <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
              <Button
                variant="outline"
                loading={run.isPending}
                onClick={() => run.mutate(academicYear)}
              >
                <Play className="size-4" aria-hidden />
                Run this month now
              </Button>
              <span className="text-xs text-muted-foreground">
                Bills the current month without waiting for the {saved.generate_day}
                {ordinal(saved.generate_day)}. Pressing it twice cannot bill a period
                twice — the second run reports that it has already been generated.
              </span>
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

type FormState = {
  isActive: boolean;
  /** Held as strings: a half-typed number field is not a number, and coercing on
   *  every keystroke turns an empty box into 0 while the operator is still typing. */
  generateDay: string;
  dueDayOffset: string;
  issueImmediately: boolean;
  includeStationery: boolean;
  carryForwardDues: boolean;
  carryForwardHeadId: string | null;
};

/** The defaults a campus that has never configured this should start from — the
 *  cautious ones, matching the server's own defaults rather than the convenient
 *  settings a school arrives at after watching a few runs. */
function toForm(schedule: FeeBillingScheduleShape | null): FormState {
  return {
    isActive: schedule?.is_active ?? true,
    generateDay: String(schedule?.generate_day ?? 1),
    dueDayOffset: String(schedule?.due_day_offset ?? 10),
    issueImmediately: schedule?.issue_immediately ?? false,
    includeStationery: schedule?.include_stationery ?? false,
    carryForwardDues: schedule?.carry_forward_dues ?? false,
    carryForwardHeadId: schedule?.carry_forward_head_id ?? null,
  };
}

type FeeBillingScheduleShape = {
  is_active: boolean;
  generate_day: number;
  due_day_offset: number;
  issue_immediately: boolean;
  include_stationery: boolean;
  carry_forward_dues: boolean;
  carry_forward_head_id: string | null;
};

function ordinal(day: number): string {
  if (day % 100 >= 11 && day % 100 <= 13) return "th";
  return ["th", "st", "nd", "rd"][day % 10] ?? "th";
}
