import { api } from "@/lib/api/client";
import type {
  BillingRunResult,
  FeeBillingScheduleInput,
  FeeBillingScheduleRead,
  FeeHeadCreate,
  FeeHeadRead,
  FeeHeadUpdate,
  FeePaymentCreate,
  FeePaymentRead,
  FeeStructureCreate,
  FeeStructureDetail,
  FeeStructureItemInput,
  FeeStructureRead,
  FeeSummary,
  FeeVoucherDetail,
  FeeVoucherRead,
  FeeStructureStationeryInput,
  Page,
  PageParams,
  StationeryItemCreate,
  StationeryItemRead,
  StationeryItemUpdate,
  StudentFeeAssignmentInput,
  StudentFeeProfile,
  VoucherGenerateRequest,
  VoucherGenerateResult,
  VoucherStationeryInput,
} from "@/lib/api/types";

/** Mirrors backend/app/modules/fees/router.py. */

export interface StationeryListParams extends PageParams {
  active_only?: boolean;
  category?: string;
}

/**
 * Structures are asked for BY CLASS more often than in bulk.
 *
 * A challan is always billed against the structure for the student's own class, so
 * the caller that matters most already knows which class it wants — the student's
 * page resolves the structure from their placement rather than asking an operator to
 * pick a class they can already see on the screen.
 */
export interface StructureListParams extends PageParams {
  class_id?: string;
  academic_year?: string;
  status?: string;
}

export interface VoucherListParams extends PageParams {
  student_id?: string;
  status?: string;
  academic_year?: string;
  period_label?: string;
}

export const feesApi = {
  /** Billed, collected, outstanding and overdue for a year, optionally one period. */
  summary: (academic_year: string, period_label?: string) =>
    api.get<FeeSummary>("/fees/summary", {
      params: { academic_year, ...(period_label ? { period_label } : {}) },
    }),

  heads: {
    list: (params: PageParams = {}) =>
      api.get<Page<FeeHeadRead>>("/fees/heads", { params: { ...params } }),
    create: (body: FeeHeadCreate) => api.post<FeeHeadRead>("/fees/heads", body),
    update: (id: string, body: FeeHeadUpdate) =>
      api.patch<FeeHeadRead>(`/fees/heads/${id}`, body),
    /** 409s once any structure or issued voucher references the head. */
    remove: (id: string) => api.delete<void>(`/fees/heads/${id}`),
  },

  /**
   * The catalog of things the school SELLS — copies, pencils, books, uniform.
   *
   * Guarded by `fee:manage`, the same code as fee heads: both answer "what may this
   * campus put on a challan". Charging one to a student is `fee:issue` and lives
   * under `vouchers` below, because that answers the other question — who is charged.
   */
  stationery: {
    list: (params: StationeryListParams = {}) =>
      api.get<Page<StationeryItemRead>>("/fees/stationery", { params: { ...params } }),
    create: (body: StationeryItemCreate) =>
      api.post<StationeryItemRead>("/fees/stationery", body),
    /** Repricing is not retroactive — every charged line snapshotted what it sold at. */
    update: (id: string, body: StationeryItemUpdate) =>
      api.patch<StationeryItemRead>(`/fees/stationery/${id}`, body),
    /** 409s once any structure or challan line charges it. Deactivate instead. */
    remove: (id: string) => api.delete<void>(`/fees/stationery/${id}`),
  },

  structures: {
    list: (params: StructureListParams = {}) =>
      api.get<Page<FeeStructureRead>>("/fees/structures", { params: { ...params } }),
    get: (id: string) => api.get<FeeStructureDetail>(`/fees/structures/${id}`),
    create: (body: FeeStructureCreate) =>
      api.post<FeeStructureDetail>("/fees/structures", body),
    rename: (id: string, name: string) =>
      api.patch<FeeStructureRead>(`/fees/structures/${id}`, { name }),

    /** Add a head or reprice one already on the structure — same call either way. */
    setItem: (id: string, body: FeeStructureItemInput) =>
      api.put<FeeStructureDetail>(`/fees/structures/${id}/items`, body),
    removeItem: (id: string, headId: string) =>
      api.delete<FeeStructureDetail>(`/fees/structures/${id}/items/${headId}`),

    /**
     * The per-class stationery default — "every child in Grade 1 gets twelve copies".
     * Idempotent by article, like `setItem`. The unit price comes from the catalog
     * and is not sent, so a structure can never charge a price the catalog never had.
     */
    setStationery: (id: string, body: FeeStructureStationeryInput) =>
      api.put<FeeStructureDetail>(`/fees/structures/${id}/stationery`, body),
    removeStationery: (id: string, stationeryItemId: string) =>
      api.delete<FeeStructureDetail>(`/fees/structures/${id}/stationery/${stationeryItemId}`),

    /** Only an ACTIVE structure can bill; activation is what makes it usable. */
    activate: (id: string) => api.post<FeeStructureRead>(`/fees/structures/${id}/activate`),
    archive: (id: string) => api.post<FeeStructureRead>(`/fees/structures/${id}/archive`),
  },

  /**
   * What ONE student is billed, and where each line comes from.
   *
   * The class structure is the base every student inherits; these endpoints record
   * only the departures from it — a head this student pays that their class does
   * not (at their own rate), or one their class pays that they do not. A student
   * with no assignments is billed their class's structure exactly.
   *
   * Guarded by `fee:manage`, not `fee:issue`: putting a child on the bus at 2,000 a
   * month is a pricing decision that recurs, not a billing run.
   */
  /**
   * When this campus bills without being asked.
   *
   * `get` returns null rather than 404ing when automation has never been set up:
   * "not configured" is a normal state the settings screen renders as an empty form,
   * and a screen that has never been visited should not look broken.
   */
  billingSchedule: {
    get: (academicYear: string) =>
      api.get<FeeBillingScheduleRead | null>("/fees/billing-schedule", {
        params: { academic_year: academicYear },
      }),
    /** Idempotent by year — sending it twice revises the schedule. */
    set: (body: FeeBillingScheduleInput) =>
      api.put<FeeBillingScheduleRead>("/fees/billing-schedule", body),
    /**
     * The same run the nightly job performs, on demand and with a name against it.
     * Skips the is-it-the-day test but NOT the already-generated one, so clicking
     * twice cannot bill a period twice.
     */
    run: (academicYear: string) =>
      api.post<BillingRunResult>(
        "/fees/billing-schedule/run",
        undefined,
        { params: { academic_year: academicYear } },
      ),
  },

  students: {
    profile: (studentId: string, academicYear: string) =>
      api.get<StudentFeeProfile>(`/fees/students/${studentId}/fee-profile`, {
        params: { academic_year: academicYear },
      }),
    /** Idempotent by head and year — sending the same head twice changes the rate. */
    setAssignment: (studentId: string, body: StudentFeeAssignmentInput) =>
      api.put<StudentFeeProfile>(`/fees/students/${studentId}/fee-assignments`, body),
    removeAssignment: (studentId: string, headId: string, academicYear: string) =>
      api.delete<StudentFeeProfile>(
        `/fees/students/${studentId}/fee-assignments/${headId}`,
        { params: { academic_year: academicYear } },
      ),
  },

  vouchers: {
    list: (params: VoucherListParams = {}) =>
      api.get<Page<FeeVoucherRead>>("/fees/vouchers", { params: { ...params } }),
    get: (id: string) => api.get<FeeVoucherDetail>(`/fees/vouchers/${id}`),

    /**
     * Bulk-bill a class for one period.
     *
     * Skips rather than fails: a student already billed for the period is reported
     * in `skipped[]` and the rest still generate. Capped at 500 per run, and
     * `truncated` says so — a partial run must never read as a complete one.
     */
    generate: (body: VoucherGenerateRequest) =>
      api.post<VoucherGenerateResult>("/fees/vouchers/generate", body),

    issue: (id: string) => api.post<FeeVoucherDetail>(`/fees/vouchers/${id}/issue`),
    void: (id: string, reason: string) =>
      api.post<FeeVoucherDetail>(`/fees/vouchers/${id}/void`, { reason }),

    /**
     * The per-student charge — "Ali also took two more copies".
     *
     * DRAFT ONLY: 409 once the challan is issued, because an issued bill is never
     * rewritten. Idempotent by article — the same item twice sets the quantity.
     */
    addStationery: (id: string, body: VoucherStationeryInput) =>
      api.put<FeeVoucherDetail>(`/fees/vouchers/${id}/stationery`, body),
    removeStationery: (id: string, stationeryItemId: string) =>
      api.delete<FeeVoucherDetail>(`/fees/vouchers/${id}/stationery/${stationeryItemId}`),

    payments: (id: string) => api.get<FeePaymentRead[]>(`/fees/vouchers/${id}/payments`),
    recordPayment: (id: string, body: FeePaymentCreate) =>
      api.post<FeePaymentRead>(`/fees/vouchers/${id}/payments`, body),

    /** The printable challan. Opened, not fetched — see the view. */
    pdfUrl: (id: string) => `/api/bff/fees/vouchers/${id}/pdf`,

    /**
     * Several months on ONE printed challan — the term-at-a-time page.
     *
     * The vouchers stay separate underneath: each keeps its own number, status and
     * receipts, so paying two of three settles exactly those two. This combines the
     * printing only. The API refuses ids belonging to different students, and
     * refuses to fold a voided challan into a live total.
     */
    combinedPdfUrl: (ids: string[]) =>
      `/api/bff/fees/vouchers/print?${ids.map((id) => `ids=${id}`).join("&")}`,
  },

  payments: {
    /** Requires `fee:void`, not `fee:collect`. Separation of duties, deliberately. */
    reverse: (paymentId: string, reason: string) =>
      api.post<FeePaymentRead>(`/fees/payments/${paymentId}/reverse`, { reason }),
  },
};
