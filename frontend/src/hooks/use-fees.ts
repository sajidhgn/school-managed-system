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
  FeeHeadCreate,
  FeeHeadUpdate,
  FeePaymentCreate,
  FeeStructureCreate,
  FeeStructureItemInput,
  FeeStructureStationeryInput,
  PageParams,
  StationeryItemCreate,
  StationeryItemUpdate,
  StudentFeeAssignmentInput,
  VoucherGenerateRequest,
  VoucherStationeryInput,
} from "@/lib/api/types";

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

export function useCreateFeeHead() {
  return useFeeMutation((body: FeeHeadCreate) => feesApi.heads.create(body), {
    success: (head) => ["Fee head created", head.name],
    failure: "Couldn't create fee head",
  });
}

export function useUpdateFeeHead() {
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeeHeadUpdate }) => feesApi.heads.update(id, body),
    { success: () => ["Fee head updated"], failure: "Couldn't update fee head" },
  );
}

export function useDeleteFeeHead() {
  return useFeeMutation((id: string) => feesApi.heads.remove(id), {
    success: () => ["Fee head deleted"],
    failure: "Couldn't delete fee head",
  });
}

export function useCreateStationeryItem() {
  return useFeeMutation((body: StationeryItemCreate) => feesApi.stationery.create(body), {
    success: (item) => ["Stationery item added", item.name],
    failure: "Couldn't add that item",
  });
}

/**
 * Edit or reprice an article.
 *
 * The success message says the reprice is not retroactive, because that is the one
 * thing a bursar needs to be sure of before changing a number that appears on bills.
 */
export function useUpdateStationeryItem() {
  return useFeeMutation(
    ({ id, body }: { id: string; body: StationeryItemUpdate }) =>
      feesApi.stationery.update(id, body),
    {
      success: (item) => [
        "Stationery item updated",
        `Challans already issued keep charging what ${item.name} cost when they were generated.`,
      ],
      failure: "Couldn't update that item",
    },
  );
}

export function useDeleteStationeryItem() {
  return useFeeMutation((id: string) => feesApi.stationery.remove(id), {
    success: () => ["Stationery item deleted"],
    failure: "Couldn't delete that item",
  });
}

export function useSetStructureStationery() {
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeeStructureStationeryInput }) =>
      feesApi.structures.setStationery(id, body),
    { success: () => ["Structure updated"], failure: "Couldn't add that item" },
  );
}

export function useRemoveStructureStationery() {
  return useFeeMutation(
    ({ id, stationeryItemId }: { id: string; stationeryItemId: string }) =>
      feesApi.structures.removeStationery(id, stationeryItemId),
    { success: () => ["Item removed"], failure: "Couldn't remove that line" },
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
  return useFeeMutation(
    ({ id, body }: { id: string; body: VoucherStationeryInput }) =>
      feesApi.vouchers.addStationery(id, body),
    { success: () => ["Charge added"], failure: "Couldn't add that charge" },
  );
}

export function useRemoveVoucherStationery() {
  return useFeeMutation(
    ({ id, stationeryItemId }: { id: string; stationeryItemId: string }) =>
      feesApi.vouchers.removeStationery(id, stationeryItemId),
    { success: () => ["Charge removed"], failure: "Couldn't remove that charge" },
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
  return useFeeMutation(
    ({ studentId, body }: { studentId: string; body: StudentFeeAssignmentInput }) =>
      feesApi.students.setAssignment(studentId, body),
    {
      success: () => [
        "Fee arrangement saved",
        "Applies from the next challan generated. Challans already issued are unchanged.",
      ],
      failure: "Couldn't save that arrangement",
    },
  );
}

export function useRemoveStudentFeeAssignment() {
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
      success: () => ["Back on the class default"],
      failure: "Couldn't remove that arrangement",
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
  return useFeeMutation(
    (body: FeeBillingScheduleInput) => feesApi.billingSchedule.set(body),
    {
      success: (schedule) => [
        schedule.is_active ? "Automatic billing on" : "Automatic billing paused",
        schedule.is_active && schedule.next_run_on
          ? `Next run ${schedule.next_run_on}. Challans already issued are never restated.`
          : "Nothing will be generated until you turn it back on.",
      ],
      failure: "Couldn't save the billing schedule",
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
  return useFeeMutation((academicYear: string) => feesApi.billingSchedule.run(academicYear), {
    success: (result) =>
      result.ran
        ? [
            `${result.created} challan${result.created === 1 ? "" : "s"} generated`,
            [
              `${result.structures} class structure${result.structures === 1 ? "" : "s"} billed for ${result.period_label}.`,
              result.skipped
                ? `${result.skipped} student${result.skipped === 1 ? " was" : "s were"} skipped — already billed.`
                : "",
              result.absorbed_vouchers
                ? `${result.absorbed_vouchers} earlier challan${result.absorbed_vouchers === 1 ? "" : "s"} carried forward.`
                : "",
              result.truncated ? "A class was too large for one run — bill the rest by section." : "",
            ]
              .filter(Boolean)
              .join(" "),
          ]
        : ["Nothing to generate", result.reason ?? undefined],
    failure: "Couldn't run the billing",
  });
}

export function useCreateStructure() {
  return useFeeMutation((body: FeeStructureCreate) => feesApi.structures.create(body), {
    success: (structure) => ["Fee structure created", structure.name],
    failure: "Couldn't create fee structure",
  });
}

export function useSetStructureItem() {
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeeStructureItemInput }) =>
      feesApi.structures.setItem(id, body),
    { success: () => ["Structure updated"], failure: "Couldn't price that fee head" },
  );
}

export function useRemoveStructureItem() {
  return useFeeMutation(
    ({ id, headId }: { id: string; headId: string }) =>
      feesApi.structures.removeItem(id, headId),
    { success: () => ["Fee head removed"], failure: "Couldn't remove that line" },
  );
}

export function useActivateStructure() {
  return useFeeMutation((id: string) => feesApi.structures.activate(id), {
    success: () => ["Structure activated", "It can now be used to bill."],
    failure: "Couldn't activate",
  });
}

export function useArchiveStructure() {
  return useFeeMutation((id: string) => feesApi.structures.archive(id), {
    success: () => ["Structure archived"],
    failure: "Couldn't archive",
  });
}

/**
 * Bulk-generate challans.
 *
 * The success message reports skips, because a run that quietly bills 180 of 200
 * students looks identical to a complete one otherwise.
 */
export function useGenerateVouchers() {
  return useFeeMutation((body: VoucherGenerateRequest) => feesApi.vouchers.generate(body), {
    success: (result) => [
      `${result.created} challan${result.created === 1 ? "" : "s"} generated`,
      result.skipped.length
        ? `${result.skipped.length} student${result.skipped.length === 1 ? " was" : "s were"} skipped — already billed for this period.`
        : undefined,
    ],
    failure: "Couldn't generate challans",
  });
}

export function useIssueVoucher() {
  return useFeeMutation((id: string) => feesApi.vouchers.issue(id), {
    success: (voucher) => ["Challan issued", voucher.voucher_number],
    failure: "Couldn't issue this challan",
  });
}

export function useVoidVoucher() {
  return useFeeMutation(
    ({ id, reason }: { id: string; reason: string }) => feesApi.vouchers.void(id, reason),
    { success: () => ["Challan voided"], failure: "Couldn't void this challan" },
  );
}

export function useRecordPayment() {
  return useFeeMutation(
    ({ id, body }: { id: string; body: FeePaymentCreate }) =>
      feesApi.vouchers.recordPayment(id, body),
    {
      success: (payment) => ["Payment recorded", `Receipt ${payment.receipt_number}`],
      failure: "Couldn't record this payment",
    },
  );
}

export function useReversePayment() {
  return useFeeMutation(
    ({ paymentId, reason }: { paymentId: string; reason: string }) =>
      feesApi.payments.reverse(paymentId, reason),
    { success: () => ["Payment reversed"], failure: "Couldn't reverse this payment" },
  );
}
