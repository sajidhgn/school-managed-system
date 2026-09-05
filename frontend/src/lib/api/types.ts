import type { components } from "./schema";

/**
 * Ergonomic aliases over the generated OpenAPI types.
 *
 * `schema.d.ts` is GENERATED — never edit it. Regenerate after any backend
 * route/schema change:
 *   backend$  make openapi
 *   frontend$ npm run gen:api
 *
 * A renamed or removed backend field becomes a TypeScript error here, which is the
 * entire point of generating rather than hand-writing these. Backend CI fails if
 * `openapi.json` is stale, so the two cannot drift silently.
 */

type S = components["schemas"];

// --- Identity & session ----------------------------------------------------
export type LoginRequest = S["LoginRequest"];
export type LoginResponse = S["LoginResponse"];
export type RegisterRequest = S["RegisterRequest"];
export type RegisterResponse = S["RegisterResponse"];
export type MeResponse = S["MeResponse"];
export type MembershipSummary = S["MembershipSummary"];
export type ContextSwitchRequest = S["ContextSwitchRequest"];
export type VerifyEmailRequest = S["VerifyEmailRequest"];
export type ResendVerificationRequest = S["ResendVerificationRequest"];
export type ForgotPasswordRequest = S["ForgotPasswordRequest"];
export type ResetPasswordRequest = S["ResetPasswordRequest"];
export type MessageResponse = S["MessageResponse"];

// --- Organization & schools ------------------------------------------------
export type OrganizationRead = S["OrganizationRead"];
export type OrganizationUpdate = S["OrganizationUpdate"];
export type TransferOwnershipRequest = S["TransferOwnershipRequest"];
export type SchoolRead = S["SchoolRead"];
export type SchoolCreate = S["SchoolCreate"];
export type SchoolUpdate = S["SchoolUpdate"];
export type CardDesignConfig = S["CardDesignConfig"];

// --- RBAC ------------------------------------------------------------------
export type PermissionRead = S["PermissionRead"];
export type PermissionCategory = S["PermissionCategory"];
export type RoleRead = S["RoleRead"];
export type RoleDetail = S["RoleDetail"];
export type RoleCreate = S["RoleCreate"];
export type RoleUpdate = S["RoleUpdate"];
export type RolePermissionsUpdate = S["RolePermissionsUpdate"];
export type MemberRead = S["MemberRead"];
export type MemberCreate = S["MemberCreate"];
export type TeacherOption = S["TeacherOption"];
export type MemberUpdate = S["MemberUpdate"];
export type AuditLogRead = S["AuditLogRead"];

// --- Invitations -----------------------------------------------------------
export type InvitationCreate = S["InvitationCreate"];
export type InvitationRead = S["InvitationRead"];
export type InvitationPreview = S["InvitationPreview"];
export type InvitationAccept = S["InvitationAccept"];
export type InvitationAcceptResponse = S["InvitationAcceptResponse"];

// --- Billing ---------------------------------------------------------------
export type PlanPublic = S["PlanPublic"];
export type SubscriptionRead = S["SubscriptionRead"];
export type SubscribeRequest = S["SubscribeRequest"];
export type CancelRequest = S["CancelRequest"];
export type UsageResponse = S["UsageResponse"];
export type UsageItem = S["UsageItem"];
export type InvoiceRead = S["InvoiceRead"];
export type BillingCycle = S["BillingCycle"];

// --- Platform console ------------------------------------------------------
export type PlatformLoginRequest = S["PlatformLoginRequest"];
export type PlatformAdminRead = S["PlatformAdminRead"];
export type OrganizationSummary = S["OrganizationSummary"];
export type OrganizationDetail = S["OrganizationDetail"];
export type OrganizationStatusUpdate = S["OrganizationStatusUpdate"];
export type PlanOverrideRequest = S["PlanOverrideRequest"];
export type PlanAdminRead = S["PlanAdminRead"];
export type PlanWrite = S["PlanWrite"];
export type PlanPatch = S["PlanPatch"];
export type PlanImpactRequest = S["PlanImpactRequest"];
export type PlanImpactResponse = S["PlanImpactResponse"];
export type AffectedOrganization = S["AffectedOrganization"];
export type PlanLimitBreach = S["PlanLimitBreach"];
export type MetricsResponse = S["MetricsResponse"];
export type PlatformAuditRead = S["PlatformAuditRead"];
export type ImpersonateRequest = S["ImpersonateRequest"];
export type ImpersonationGrant = S["ImpersonationGrant"];

// --- Global search ---------------------------------------------------------
// Every field on these is derived server-side from the caller's permissions, which
// is why the omnibar has no permission logic of its own.
export type SearchEntity = S["SearchEntity"];
export type SearchHit = S["SearchHit"];
export type SearchGroup = S["SearchGroup"];
export type SearchResponse = S["SearchResponse"];
export type SearchSuggestion = S["SearchSuggestion"];
export type SearchScopeRead = S["SearchScopeRead"];
export type SearchConfigResponse = S["SearchConfigResponse"];
export type ParsedQueryRead = S["ParsedQueryRead"];

// --- Academic modules ------------------------------------------------------
export type StudentRead = S["StudentRead"];
export type StudentListRow = S["StudentListRow"];
export type StudentDues = S["StudentDues"];
export type FeeStandingFilter = S["FeeStandingFilter"];
export type StudentCreate = S["StudentCreate"];
export type StudentUpdate = S["StudentUpdate"];
export type StudentStatus = S["StudentStatus"];
export type StudentAdmissionRequest = S["StudentAdmissionRequest"];
export type AdmissionResponse = S["AdmissionResponse"];
export type Gender = S["Gender"];
export type ClassRead = S["ClassRead"];
export type ClassCreate = S["ClassCreate"];
export type ClassUpdate = S["ClassUpdate"];
export type ClassSummary = S["ClassSummary"];
export type SectionRead = S["SectionRead"];
export type SectionCreate = S["SectionCreate"];
export type SectionUpdate = S["SectionUpdate"];
export type SectionSummary = S["SectionSummary"];

// --- Academic calendar -----------------------------------------------------
export type AcademicYearRead = S["AcademicYearRead"];
export type AcademicYearCreate = S["AcademicYearCreate"];
export type AcademicYearUpdate = S["AcademicYearUpdate"];
export type TermRead = S["TermRead"];
export type TermCreate = S["TermCreate"];
export type TermUpdate = S["TermUpdate"];

// --- Curriculum ------------------------------------------------------------
export type SubjectRead = S["SubjectRead"];
export type SubjectCreate = S["SubjectCreate"];
export type SubjectUpdate = S["SubjectUpdate"];
export type SubjectKind = S["SubjectKind"];
export type ClassSubjectRead = S["ClassSubjectRead"];
export type ClassSubjectCreate = S["ClassSubjectCreate"];
export type ClassSubjectUpdate = S["ClassSubjectUpdate"];

// --- Exams -----------------------------------------------------------------
export type ExamRead = S["ExamRead"];
export type ExamCreate = S["ExamCreate"];
export type ExamUpdate = S["ExamUpdate"];
export type ExamStatus = S["ExamStatus"];
export type ExamPaperRead = S["ExamPaperRead"];
export type ExamPaperCreate = S["ExamPaperCreate"];
export type ExamPaperUpdate = S["ExamPaperUpdate"];
export type PaperMarksRead = S["PaperMarksRead"];
export type StudentMarkRow = S["StudentMarkRow"];
export type MarkEntry = S["MarkEntry"];
export type MarksUpsert = S["MarksUpsert"];
export type MarksUpsertResult = S["MarksUpsertResult"];
export type ExamClassResults = S["ExamClassResults"];
export type ExamResultRow = S["ExamResultRow"];
export type ExamResultFilter = S["ExamResultFilter"];
export type StudentExamResult = S["StudentExamResult"];

// --- Enrollment ledger -----------------------------------------------------
export type EnrollmentRead = S["EnrollmentRead"];
export type EnrollmentPlacement = S["EnrollmentPlacement"];
export type PromotionRequest = S["PromotionRequest"];
export type PromotionResult = S["PromotionResult"];
export type PromotionSkip = S["PromotionSkip"];
export type EnrollmentBackfillResult = S["EnrollmentBackfillResult"];
export type SectionRosterEntry = S["SectionRosterEntry"];

// --- Attendance ------------------------------------------------------------
export type AttendanceStatus = S["AttendanceStatus"];
export type AttendanceSessionStatus = S["AttendanceSessionStatus"];
export type AttendanceSessionRead = S["AttendanceSessionRead"];
export type AttendanceSessionDetail = S["AttendanceSessionDetail"];
export type AttendanceSessionOpen = S["AttendanceSessionOpen"];
export type AttendanceEntryRead = S["AttendanceEntryRead"];
export type AttendanceEntryInput = S["AttendanceEntryInput"];
export type AttendanceMarkRequest = S["AttendanceMarkRequest"];
export type DailyOverview = S["DailyOverview"];
export type SectionDayStatus = S["SectionDayStatus"];
export type StudentAttendanceSummary = S["StudentAttendanceSummary"];
export type SectionAttendanceReport = S["SectionAttendanceReport"];
export type SectionAttendanceDay = S["SectionAttendanceDay"];

// --- Pagination ------------------------------------------------------------
export type PageMeta = S["PageMeta"];
export type SortDirection = S["SortDirection"];

/** The backend's `Page[T]` envelope, generic over the item type. */
export interface Page<T> {
  items: T[];
  meta: PageMeta;
}

/**
 * Offset-pagination query parameters.
 *
 * Hand-declared rather than generated: these are QUERY parameters, and
 * openapi-typescript models them per-operation rather than as a reusable component.
 * Declaring the shape once keeps every list resource consistent.
 */
export interface PageParams {
  page?: number;
  size?: number;
  sort_by?: string;
  sort_dir?: SortDirection;
}

// ---------------------------------------------------------------------------
// Permissions
// ---------------------------------------------------------------------------

/**
 * Permission codes the UI branches on.
 *
 * NOT generated: the backend models permission codes as free-form strings, because
 * customers create custom roles and the catalog grows without a schema change. So
 * these are hand-declared constants rather than a union from `schema.d.ts`.
 *
 * A typo here names a permission nobody holds, which FAILS CLOSED — the control
 * stays hidden. The server re-checks every action regardless (`require(...)`), so
 * the worst case is a missing button, never an unguarded one. That asymmetry is why
 * hand-declaring is acceptable here and would not be on the server.
 */
export const PERMISSIONS = {
  orgRead: "org:read",
  orgUpdate: "org:update",
  orgTransferOwnership: "org:transfer_ownership",
  billingRead: "billing:read",
  billingManage: "billing:manage",
  invoiceRead: "invoice:read",
  schoolCreate: "school:create",
  schoolRead: "school:read",
  schoolUpdate: "school:update",
  schoolArchive: "school:archive",
  memberRead: "member:read",
  memberInvite: "member:invite",
  memberUpdate: "member:update",
  memberSuspend: "member:suspend",
  memberRemove: "member:remove",
  roleRead: "role:read",
  roleCreate: "role:create",
  roleUpdate: "role:update",
  roleDelete: "role:delete",
  roleAssignPermissions: "role:assign_permissions",
  invitationRead: "invitation:read",
  invitationResend: "invitation:resend",
  invitationRevoke: "invitation:revoke",
  auditRead: "audit:read",
  studentRead: "student:read",
  studentCreate: "student:create",
  studentUpdate: "student:update",
  studentDelete: "student:delete",
  classRead: "class:read",
  classCreate: "class:create",
  classUpdate: "class:update",
  classDelete: "class:delete",
  feeRead: "fee:read",
  feeManage: "fee:manage",
  feeIssue: "fee:issue",
  feeCollect: "fee:collect",
  // Separate from `fee:collect` on purpose, and absent from the accountant default:
  // whoever records money arriving must not be the one who can erase the record.
  feeVoid: "fee:void",
  studentPromote: "student:promote",
  guardianRead: "guardian:read",
  guardianCreate: "guardian:create",
  guardianUpdate: "guardian:update",
  guardianDelete: "guardian:delete",
  calendarRead: "calendar:read",
  calendarManage: "calendar:manage",
  subjectRead: "subject:read",
  subjectManage: "subject:manage",
  // The exam module rides on the grade pair: the codes were seeded ahead of the
  // module (see the RBAC catalog), so teachers already hold both by default.
  gradeRead: "grade:read",
  gradeManage: "grade:manage",
  attendanceRead: "attendance:read",
  attendanceMark: "attendance:mark",
  // Separate from `attendance:mark` on purpose, and absent from the teacher default:
  // whoever records absences must not be the one who can rewrite the record. Same
  // control as `feeVoid` above, applied to the register a truancy referral is built on.
  attendanceAmend: "attendance:amend",
} as const;

export type PermissionCode = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

// --- Fees ------------------------------------------------------------------
export type FeeHeadRead = S["FeeHeadRead"];
export type FeeHeadCreate = S["FeeHeadCreate"];
export type FeeHeadUpdate = S["FeeHeadUpdate"];
export type FeeStructureRead = S["FeeStructureRead"];
export type FeeStructureDetail = S["FeeStructureDetail"];
export type FeeStructureCreate = S["FeeStructureCreate"];
export type FeeStructureItemRead = S["FeeStructureItemRead"];
export type FeeStructureItemInput = S["FeeStructureItemInput"];
export type FeeVoucherRead = S["FeeVoucherRead"];
export type FeeVoucherDetail = S["FeeVoucherDetail"];
export type FeePaymentRead = S["FeePaymentRead"];
export type FeePaymentCreate = S["FeePaymentCreate"];
export type FeeSummary = S["FeeSummary"];
export type VoucherGenerateRequest = S["VoucherGenerateRequest"];
export type VoucherGenerateResult = S["VoucherGenerateResult"];
export type VoucherStatus = S["VoucherStatus"];
export type VoucherItemRead = S["VoucherItemRead"];
export type FeeLineType = S["FeeLineType"];

// --- Unattended monthly generation -----------------------------------------
export type FeeBillingScheduleRead = S["FeeBillingScheduleRead"];
export type FeeBillingScheduleInput = S["FeeBillingScheduleInput"];
export type BillingRunResult = S["BillingRunResult"];

// --- Stationery (what the school sells, priced per unit) --------------------
export type StationeryItemRead = S["StationeryItemRead"];
export type StationeryItemCreate = S["StationeryItemCreate"];
export type StationeryItemUpdate = S["StationeryItemUpdate"];
export type StationeryCategory = S["StationeryCategory"];
export type StationeryUnit = S["StationeryUnit"];
export type FeeStructureStationeryInput = S["FeeStructureStationeryInput"];
export type VoucherStationeryInput = S["VoucherStationeryInput"];

// --- Per-student fee arrangements ------------------------------------------
export type StudentFeeProfile = S["StudentFeeProfile"];
export type StudentFeeLine = S["StudentFeeLine"];
export type StudentFeeAssignmentRead = S["StudentFeeAssignmentRead"];
export type StudentFeeAssignmentInput = S["StudentFeeAssignmentInput"];
export type StudentFeeAssignmentMode = S["StudentFeeAssignmentMode"];
export type PaymentMethod = S["PaymentMethod"];

// ---------------------------------------------------------------------------
// Display labels
// ---------------------------------------------------------------------------
//
// Typed `Record<string, string>` with a lookup helper rather than
// `Record<SomeEnum, string>`. Several of these values are open-ended on the backend
// — an organization status can gain a value, a plan code is whatever the super admin
// created — so an exhaustive map would either be a lie or a build break every time
// product adds a state. `label()` falls back to the raw value, which is ugly but
// visible, rather than rendering blank.

export const ORG_STATUS_LABELS: Record<string, string> = {
  trialing: "Trialing",
  active: "Active",
  past_due: "Past due",
  over_limit: "Over limit",
  suspended: "Suspended",
  cancelled: "Cancelled",
};

export const SUBSCRIPTION_STATUS_LABELS: Record<string, string> = {
  trialing: "Trialing",
  active: "Active",
  past_due: "Past due",
  suspended: "Suspended",
  cancelled: "Cancelled",
  expired: "Expired",
};

export const SCHOOL_STATUS_LABELS: Record<string, string> = {
  active: "Active",
  inactive: "Inactive",
  archived: "Archived",
};

export const MEMBER_STATUS_LABELS: Record<string, string> = {
  active: "Active",
  suspended: "Suspended",
};

export const INVITATION_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  accepted: "Accepted",
  expired: "Expired",
  revoked: "Revoked",
};

export const STUDENT_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  active: "Active",
  inactive: "Inactive",
  graduated: "Graduated",
  transferred: "Transferred",
};

export const GENDER_LABELS: Record<string, string> = {
  male: "Male",
  female: "Female",
  other: "Other",
};

/**
 * Human phrasing for the metered limit keys from `GET /org/usage`.
 * The API returns machine keys; a usage bar reading "max_schools" is a leaked
 * implementation detail.
 */
export const USAGE_LABELS: Record<string, string> = {
  max_schools: "Schools",
  max_students: "Students",
  max_staff: "Staff seats",
  max_custom_roles: "Custom roles",
  storage_mb: "Storage (MB)",
};

/** Human label for a value, falling back to the raw value rather than blank. */
export const VOUCHER_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  issued: "Issued",
  partly_paid: "Part paid",
  paid: "Paid",
  overdue: "Overdue",
  void: "Void",
};

export const FEE_RECURRENCE_LABELS: Record<string, string> = {
  monthly: "Monthly",
  term: "Per term",
  annual: "Annual",
  one_time: "One time",
};

export const FEE_STRUCTURE_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  active: "Active",
  archived: "Archived",
};

export const STATIONERY_CATEGORY_LABELS: Record<string, string> = {
  book: "Books",
  notebook: "Copies & notebooks",
  stationery: "Stationery",
  uniform: "Uniform",
  sports: "Sports",
  other: "Other",
};

/**
 * Singular and plural, because a quantity always sits next to the unit and
 * "1 pieces" reads as a bug to the person holding the challan.
 */
export const STATIONERY_UNIT_LABELS: Record<string, string> = {
  piece: "piece",
  dozen: "dozen",
  pack: "pack",
  set: "set",
  pair: "pair",
  ream: "ream",
};

export function unitLabel(unit: string | null | undefined, quantity: number): string {
  const singular = unit ? (STATIONERY_UNIT_LABELS[unit] ?? unit) : "unit";
  return quantity === 1 ? singular : `${singular}s`;
}

export const PAYMENT_METHOD_LABELS: Record<string, string> = {
  cash: "Cash",
  bank_transfer: "Bank transfer",
  cheque: "Cheque",
  card: "Card",
  online: "Online",
  other: "Other",
};

export function label(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "—";
  return map[value] ?? value;
}
