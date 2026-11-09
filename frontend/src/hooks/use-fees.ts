"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import {
  feesApi,
  type StationeryListParams,
  type StructureListParams,
  type VoucherListParams,
} from "@/lib/api/resources/fees";
import type {
  FeeBillingScheduleInput,
  FeeConcessionCreate,
  FeeConcessionUpdate,
  FeeHeadCreate,
  FeeHeadUpdate,
  FeePaymentCreate,
  FeeSiblingRuleInput,
  FeeStructureCreate,
  FeeStructureItemInput,
  FeeStructureStationeryInput,
  LateFeePolicyCreate,
  LedgerAdjustmentInput,
  PageParams,
  SiblingApplyRequest,
  StationeryItemCreate,
  StationeryItemUpdate,
  StudentFeeAssignmentInput,
  VoucherFeeChargeInput,
  VoucherGenerateRequest,
  VoucherStationeryInput,
} from "@/lib/api/types";
import { fill, ltr } from "@/lib/i18n/format";
import { feesMessages } from "@/lib/i18n/modules/fees";
import { useCatalog } from "@/lib/i18n/use-catalog";

/**
 * Fees data layer.
 *
 * Every mutation here invalidates `queryKeys.fees.all` rather than a narrower key.
 * The reason is that money moves through this module in linked steps: recording one
 * payment changes the voucher, the register it sits in, AND the collection summary
 * at the top of the page. Invalidating precisely would mean listing those three
 * relationships at every call site and getting one wrong eventually — and a stale
 * "outstanding" figure is the kind of wrong an accountant acts on.
 */

// --- Reads -----------------------------------------------------------------

export function useFeeSummary(academicYear: string, period?: string) {
  return useQuery({
    queryKey: queryKeys.fees.summary(academicYear, period),
    queryFn: () => feesApi.summary(academicYear, period),
    enabled: Boolean(academicYear),
  });
}

export function useFeeHeads(params: PageParams = {}) {
  return useQuery({
    queryKey: queryKeys.fees.heads(params),
    queryFn: () => feesApi.heads.list(params),
    placeholderData: (previous) => previous,
  });
}

export function useFeeStructures(params: StructureListParams = {}) {
  return useQuery({
    queryKey: queryKeys.fees.structures(params),
    queryFn: () => feesApi.structures.list(params),
    placeholderData: (previous) => previous,
  });
}

export function useFeeStructure(id: string | null) {
  return useQuery({
    queryKey: queryKeys.fees.structure(id ?? ""),
    queryFn: () => feesApi.structures.get(id!),
    enabled: Boolean(id),
  });
}

export function useStationeryItems(params: StationeryListParams = {}) {
  return useQuery({
    queryKey: queryKeys.fees.stationery(params),
    queryFn: () => feesApi.stationery.list(params),
    placeholderData: (previous) => previous,
  });
}

/**
 * What one student is billed for a year — the class base, their departures from it,
 * and the result.
 *
 * Keyed on both the student and the year: a school running two sessions side by side
 * during a transition must not have one overwrite the other in the cache.
 */
export function useStudentFeeProfile(studentId: string | null, academicYear: string) {
  return useQuery({
    queryKey: queryKeys.fees.studentProfile(studentId ?? "", academicYear),
    queryFn: () => feesApi.students.profile(studentId!, academicYear),
    enabled: Boolean(studentId && academicYear),
  });
}

/**
 * When this campus bills without being asked.
 *
 * Returns `null` — not an error — when automation has never been configured, so the
 * settings screen renders an empty form rather than a failure on a page nobody has
 * visited yet.
 */
export function useBillingSchedule(academicYear: string) {
  return useQuery({
    queryKey: queryKeys.fees.billingSchedule(academicYear),
    queryFn: () => feesApi.billingSchedule.get(academicYear),
    enabled: Boolean(academicYear),
  });
}

/** The late-fee rules for one year. An empty list is "not set up", not an error. */
export function useLateFeePolicies(academicYear: string) {
  return useQuery({
    queryKey: queryKeys.fees.lateFees(academicYear),
    queryFn: () => feesApi.lateFees.list(academicYear),
    enabled: Boolean(academicYear),
  });
}

/** A student's running account — balance first, then every movement, newest first. */
export function useStudentLedger(studentId: string, params: PageParams = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.fees.ledger(studentId, params),
    queryFn: () => feesApi.students.ledger(studentId, params),
    enabled: enabled && Boolean(studentId),
    placeholderData: (previous) => previous,
  });
}

export function useConcessions(params: PageParams & { is_active?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.fees.concessions(params),
    queryFn: () => feesApi.concessions.list(params),
    placeholderData: (previous) => previous,
  });
}

/** `null` until the campus sets a rule up — an empty form, not an error. */
export function useSiblingRule() {
  return useQuery({
    queryKey: queryKeys.fees.siblingRule,
    queryFn: () => feesApi.siblings.rule(),
  });
}

/**
 * Families with a child at this campus and what the rule proposes for each.
 *
 * Only enabled once a rule exists: without one the API answers 422, and the screen
 * shows the rule form instead of an error.
 */
export function useSiblingReview(academicYear: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.fees.siblings(academicYear),
    queryFn: () => feesApi.siblings.review(academicYear),
    enabled: enabled && Boolean(academicYear),
  });
}

export function useVouchers(params: VoucherListParams = {}) {
  return useQuery({
    queryKey: queryKeys.fees.vouchers(params),
    queryFn: () => feesApi.vouchers.list(params),
    // Keeps the previous page on screen while the next one loads, so paging through
    // a register does not flash an empty table between clicks.
    placeholderData: (previous) => previous,
  });
}

export function useVoucher(id: string | null) {
  return useQuery({
    queryKey: queryKeys.fees.voucher(id ?? ""),
    queryFn: () => feesApi.vouchers.get(id!),
    enabled: Boolean(id),
  });
}

// --- Mutations -------------------------------------------------------------

function useFeeMutation<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
  messages: { success: (result: TResult) => [string, string?]; failure: string },
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.fees.all });
      const [title, body] = messages.success(result);
      toast.success(title, body);
    },
    onError: (error) => toast.error(messages.failure, errorMessage(error)),
  });
}

/** The toast strings, in the viewer's language. Read at the top of each hook. */
function useFeeToasts() {
  return useCatalog(feesMessages).toast;
}

/** "1 challan" / "3 challans" — the one- and many- forms are separate catalog keys. */
function counted(count: number, one: string, many: string): string {
  return fill(count === 1 ? one : many, { count });
}

export function useCreateFeeHead() {
  const m = useFeeToasts();
  return useFeeMutation((body: FeeHeadCreate) => feesApi.heads.create(body), {
    success: (head) => [m.feeHeadCreated, head.name],
    failure: m.feeHeadCreateFailed,
  });
}

export function useUpdateFeeHead() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeeHeadUpdate }) => feesApi.heads.update(id, body),
    { success: () => [m.feeHeadUpdated], failure: m.feeHeadUpdateFailed },
  );
}

export function useDeleteFeeHead() {
  const m = useFeeToasts();
  return useFeeMutation((id: string) => feesApi.heads.remove(id), {
    success: () => [m.feeHeadDeleted],
    failure: m.feeHeadDeleteFailed,
  });
}

export function useCreateStationeryItem() {
  const m = useFeeToasts();
  return useFeeMutation((body: StationeryItemCreate) => feesApi.stationery.create(body), {
    success: (item) => [m.stationeryAdded, item.name],
    failure: m.itemAddFailed,
  });
}

/**
 * Edit or reprice an article.
 *
 * The success message says the reprice is not retroactive, because that is the one
 * thing a bursar needs to be sure of before changing a number that appears on bills.
 */
export function useUpdateStationeryItem() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, body }: { id: string; body: StationeryItemUpdate }) =>
      feesApi.stationery.update(id, body),
    {
      success: (item) => [m.stationeryUpdated, fill(m.stationeryUpdatedBody, { name: item.name })],
      failure: m.itemUpdateFailed,
    },
  );
}

export function useDeleteStationeryItem() {
  const m = useFeeToasts();
  return useFeeMutation((id: string) => feesApi.stationery.remove(id), {
    success: () => [m.stationeryDeleted],
    failure: m.itemDeleteFailed,
  });
}

export function useSetStructureStationery() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeeStructureStationeryInput }) =>
      feesApi.structures.setStationery(id, body),
    { success: () => [m.structureUpdated], failure: m.itemAddFailed },
  );
}

export function useRemoveStructureStationery() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, stationeryItemId }: { id: string; stationeryItemId: string }) =>
      feesApi.structures.removeStationery(id, stationeryItemId),
    { success: () => [m.itemRemoved], failure: m.lineRemoveFailed },
  );
}

/**
 * Charge an article to one student's DRAFT challan.
 *
 * The failure copy matters here: the common 409 is "this challan has already been
 * issued", and an operator who only sees "couldn't add" will try again rather than
 * put the charge on next month's bill, which is what they actually need to do.
 */
export function useAddVoucherStationery() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, body }: { id: string; body: VoucherStationeryInput }) =>
      feesApi.vouchers.addStationery(id, body),
    { success: () => [m.chargeAdded], failure: m.chargeAddFailed },
  );
}

export function useRemoveVoucherStationery() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, stationeryItemId }: { id: string; stationeryItemId: string }) =>
      feesApi.vouchers.removeStationery(id, stationeryItemId),
    { success: () => [m.chargeRemoved], failure: m.chargeRemoveFailed },
  );
}

/**
 * Put a student on a fee head, or take them off one.
 *
 * The success copy states that it applies to the next run, because the operator's
 * immediate question after changing a bus fare is whether the challan they printed
 * this morning just changed. It did not — issued challans snapshot their lines.
 */
export function useSetStudentFeeAssignment() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ studentId, body }: { studentId: string; body: StudentFeeAssignmentInput }) =>
      feesApi.students.setAssignment(studentId, body),
    {
      success: () => [m.arrangementSaved, m.arrangementSavedBody],
      failure: m.arrangementSaveFailed,
    },
  );
}

export function useRemoveStudentFeeAssignment() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({
      studentId,
      headId,
      academicYear,
    }: {
      studentId: string;
      headId: string;
      academicYear: string;
    }) => feesApi.students.removeAssignment(studentId, headId, academicYear),
    {
      success: () => [m.backOnClassDefault],
      failure: m.arrangementRemoveFailed,
    },
  );
}

/**
 * Set or revise the automatic billing day.
 *
 * The success copy names the next run rather than saying "saved", because the only
 * thing the owner actually wants confirmed is WHEN this will now happen — a settings
 * screen that says "saved" leaves them to work that out from a day number.
 */
export function useSetBillingSchedule() {
  const m = useFeeToasts();
  return useFeeMutation(
    (body: FeeBillingScheduleInput) => feesApi.billingSchedule.set(body),
    {
      success: (schedule) => [
        schedule.is_active ? m.billingOn : m.billingPaused,
        schedule.is_active && schedule.next_run_on
          ? fill(m.billingNextRun, { date: schedule.next_run_on })
          : m.billingPausedBody,
      ],
      failure: m.billingSaveFailed,
    },
  );
}

/**
 * Run the monthly generation now.
 *
 * `ran: false` is a SUCCESS with an explanation — "already generated for 2026-08" is
 * the answer, not a failure — so it reports the reason rather than a count. Showing
 * "0 challans generated" for that case reads as a broken run, and the operator's next
 * move is to click it again.
 */
export function useRunBillingSchedule() {
  const m = useFeeToasts();
  return useFeeMutation((academicYear: string) => feesApi.billingSchedule.run(academicYear), {
    success: (result) =>
      result.ran
        ? [
            counted(result.created ?? 0, m.challansGeneratedOne, m.challansGeneratedMany),
            [
              fill(result.structures === 1 ? m.structuresBilledOne : m.structuresBilledMany, {
                count: result.structures ?? 0,
                period: result.period_label ?? "",
              }),
              result.skipped
                ? counted(result.skipped, m.skippedBilledOne, m.skippedBilledMany)
                : "",
              result.absorbed_vouchers
                ? counted(result.absorbed_vouchers, m.carriedForwardOne, m.carriedForwardMany)
                : "",
              result.truncated ? m.runTruncated : "",
            ]
              .filter(Boolean)
              .join(" "),
          ]
        : [m.nothingToGenerate, result.reason ?? undefined],
    failure: m.billingRunFailed,
  });
}

export function useCreateConcession() {
  const m = useFeeToasts();
  return useFeeMutation((body: FeeConcessionCreate) => feesApi.concessions.create(body), {
    success: (concession) => [m.concessionCreated, concession.name],
    failure: m.concessionCreateFailed,
  });
}

/**
 * Edit, re-rate, retire or restore a scheme.
 *
 * The success copy says who the new rate reaches, because the person changing
 * "Staff child" from 40% to 50% needs to know it moves every child on it — and
 * that challans already issued do not move.
 */
export function useUpdateConcession() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeeConcessionUpdate }) =>
      feesApi.concessions.update(id, body),
    {
      success: (concession) => [
        m.concessionUpdated,
        fill(m.concessionUpdatedBody, { name: concession.name }),
      ],
      failure: m.concessionUpdateFailed,
    },
  );
}

export function useDeleteConcession() {
  const m = useFeeToasts();
  return useFeeMutation((id: string) => feesApi.concessions.remove(id), {
    success: () => [m.concessionDeleted],
    failure: m.concessionDeleteFailed,
  });
}

export function useSetSiblingRule() {
  const m = useFeeToasts();
  return useFeeMutation((body: FeeSiblingRuleInput) => feesApi.siblings.setRule(body), {
    success: () => [m.siblingRuleSaved, m.siblingRuleSavedBody],
    failure: m.siblingRuleSaveFailed,
  });
}

export function useDeleteSiblingRule() {
  const m = useFeeToasts();
  return useFeeMutation<void, void>(() => feesApi.siblings.removeRule(), {
    success: () => [m.siblingRuleOff, m.siblingRuleOffBody],
    failure: m.siblingRuleOffFailed,
  });
}

/**
 * Apply the chosen proposals.
 *
 * Reports skips in the toast, because a child left alone (another discount already
 * on the head, a retired scheme) looks exactly like one that was applied otherwise.
 */
export function useApplySiblings() {
  const m = useFeeToasts();
  return useFeeMutation((body: SiblingApplyRequest) => feesApi.siblings.apply(body), {
    success: (result) => {
      const done = result.applied + result.changed + result.removed;
      const parts = [
        result.applied ? fill(m.siblingsApplied, { count: result.applied }) : "",
        result.changed ? fill(m.siblingsChanged, { count: result.changed }) : "",
        result.removed ? fill(m.siblingsRemoved, { count: result.removed }) : "",
        result.skipped.length
          ? fill(m.siblingsSkipped, {
              count: result.skipped.length,
              reason: result.skipped[0]?.reason ?? "",
            })
          : "",
      ].filter(Boolean);
      return [
        done ? counted(done, m.siblingsUpdatedOne, m.siblingsUpdatedMany) : m.nothingChanged,
        fill(m.siblingsAppliesFrom, { parts: parts.join(m.sentenceSeparator) }),
      ];
    },
    failure: m.siblingsApplyFailed,
  });
}

export function useCreateStructure() {
  const m = useFeeToasts();
  return useFeeMutation((body: FeeStructureCreate) => feesApi.structures.create(body), {
    success: (structure) => [m.structureCreated, structure.name],
    failure: m.structureCreateFailed,
  });
}

export function useSetStructureItem() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeeStructureItemInput }) =>
      feesApi.structures.setItem(id, body),
    { success: () => [m.structureUpdated], failure: m.structureItemFailed },
  );
}

export function useRemoveStructureItem() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, headId }: { id: string; headId: string }) =>
      feesApi.structures.removeItem(id, headId),
    { success: () => [m.feeHeadRemoved], failure: m.lineRemoveFailed },
  );
}

export function useActivateStructure() {
  const m = useFeeToasts();
  return useFeeMutation((id: string) => feesApi.structures.activate(id), {
    success: () => [m.structureActivated, m.structureActivatedBody],
    failure: m.structureActivateFailed,
  });
}

export function useArchiveStructure() {
  const m = useFeeToasts();
  return useFeeMutation((id: string) => feesApi.structures.archive(id), {
    success: () => [m.structureArchived],
    failure: m.structureArchiveFailed,
  });
}

/**
 * Bulk-generate challans.
 *
 * The success message reports skips, because a run that quietly bills 180 of 200
 * students looks identical to a complete one otherwise.
 */
export function useGenerateVouchers() {
  const m = useFeeToasts();
  return useFeeMutation((body: VoucherGenerateRequest) => feesApi.vouchers.generate(body), {
    success: (result) => [
      counted(result.created, m.challansGeneratedOne, m.challansGeneratedMany),
      result.skipped.length
        ? counted(result.skipped.length, m.skippedPeriodOne, m.skippedPeriodMany)
        : undefined,
    ],
    failure: m.generateFailed,
  });
}

export function useIssueVoucher() {
  const m = useFeeToasts();
  return useFeeMutation((id: string) => feesApi.vouchers.issue(id), {
    success: (voucher) => [m.challanIssued, voucher.voucher_number],
    failure: m.issueFailed,
  });
}

export function useVoidVoucher() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, reason }: { id: string; reason: string }) => feesApi.vouchers.void(id, reason),
    { success: () => [m.challanVoided], failure: m.voidFailed },
  );
}

export function useRecordPayment() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeePaymentCreate }) =>
      feesApi.vouchers.recordPayment(id, body),
    {
      success: (payment) => [
        m.paymentRecorded,
        fill(m.receiptNumber, { number: ltr(payment.receipt_number) }),
      ],
      failure: m.paymentFailed,
    },
  );
}

export function useReversePayment() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ paymentId, reason }: { paymentId: string; reason: string }) =>
      feesApi.payments.reverse(paymentId, reason),
    { success: () => [m.paymentReversed], failure: m.reverseFailed },
  );
}

// --- One-off charges on a draft challan -----------------------------------

export function useAddVoucherFeeCharge() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, body }: { id: string; body: VoucherFeeChargeInput }) =>
      feesApi.vouchers.addCharge(id, body),
    { success: () => [m.chargeAdded], failure: m.chargeAddFailed },
  );
}

export function useRemoveVoucherFeeCharge() {
  const m = useFeeToasts();
  return useFeeMutation(
    ({ id, headId }: { id: string; headId: string }) => feesApi.vouchers.removeCharge(id, headId),
    { success: () => [m.lineRemoved], failure: m.lineRemoveFailed },
  );
}

// --- Late fees --------------------------------------------------------------

/**
 * Save the year's late-fee rule. The success copy says when it bites, because the
 * owner's real question is "will this fine anyone tonight?"
 */
export function useSetLateFeePolicy() {
  const m = useFeeToasts();
  return useFeeMutation((body: LateFeePolicyCreate) => feesApi.lateFees.set(body), {
    success: (policy) => [
      policy.is_active ? m.lateFeeSaved : m.lateFeePaused,
      policy.is_active
        ? fill(policy.grace_days === 1 ? m.lateFeeActiveBodyOne : m.lateFeeActiveBodyMany, {
            days: policy.grace_days,
          })
        : m.lateFeePausedBody,
    ],
    failure: m.lateFeeSaveFailed,
  });
}

export function useDeleteLateFeePolicy() {
  const m = useFeeToasts();
  return useFeeMutation((id: string) => feesApi.lateFees.remove(id), {
    success: () => [m.lateFeeRemoved, m.lateFeeRemovedBody],
    failure: m.lateFeeRemoveFailed,
  });
}

/**
 * Apply late fees now. A run that fines nobody is the normal case on most days, so
 * it is reported with its reasons rather than as "0" — which reads like a failure.
 *
 * The reasons are the codes `apply_late_fees` reports, worded in the catalog's
 * `skipReason`; a code it does not know is shown as the code itself.
 */
export function useRunLateFees() {
  const m = useFeeToasts();
  return useFeeMutation((academicYear: string) => feesApi.lateFees.run(academicYear), {
    success: (result) => {
      if (result.assessed > 0) {
        return [
          counted(result.assessed, m.lateFeesRaisedOne, m.lateFeesRaisedMany),
          [
            counted(result.considered, m.overdueCheckedOne, m.overdueCheckedMany),
            result.truncated ? m.lateFeesMoreWaiting : "",
          ]
            .filter(Boolean)
            .join(" "),
        ];
      }
      const reasons = Object.entries(result.skipped_reasons)
        .map(([reason, count]) => {
          const known = (m.skipReason as Record<string, string>)[reason];
          return known
            ? fill(known, { count })
            : fill(m.skipReasonUnknown, { count, reason: reason.replaceAll("_", " ") });
        })
        .join(m.listSeparator);
      return [
        m.noOneToFine,
        result.considered === 0
          ? m.noneOverdue
          : fill(m.overdueSkipped, { count: result.considered, reasons: reasons || m.allSkipped }),
      ];
    },
    failure: m.lateFeesFailed,
  });
}

// --- The ledger ------------------------------------------------------------

/** `fee:void`. A write-off or a correction with no voucher behind it. */
export function useAdjustLedger(studentId: string) {
  const m = useFeeToasts();
  return useFeeMutation(
    (body: LedgerAdjustmentInput) => feesApi.students.adjustLedger(studentId, body),
    {
      success: (statement) => {
        const balance = Number(statement.balance);
        const money = new Intl.NumberFormat("en-PK", {
          style: "currency",
          currency: "PKR",
          maximumFractionDigits: 0,
        }).format(Math.abs(balance));
        return [
          m.balanceAdjusted,
          fill(balance < 0 ? m.balanceInCredit : m.balanceOwed, { amount: money }),
        ];
      },
      failure: m.balanceAdjustFailed,
    },
  );
}
