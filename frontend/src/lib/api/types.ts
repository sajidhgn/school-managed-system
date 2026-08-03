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
export type SchoolCreateResponse = S["SchoolCreateResponse"];

// --- RBAC ------------------------------------------------------------------
export type PermissionRead = S["PermissionRead"];
export type PermissionCategory = S["PermissionCategory"];
export type RoleRead = S["RoleRead"];
export type RoleDetail = S["RoleDetail"];
export type RoleCreate = S["RoleCreate"];
export type RoleUpdate = S["RoleUpdate"];
export type RolePermissionsUpdate = S["RolePermissionsUpdate"];
export type MemberRead = S["MemberRead"];
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

// --- Academic modules ------------------------------------------------------
export type StudentRead = S["StudentRead"];
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
} as const;

export type PermissionCode = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

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
export function label(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "—";
  return map[value] ?? value;
}
