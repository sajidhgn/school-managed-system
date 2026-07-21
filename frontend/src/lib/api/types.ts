import type { components } from "./schema";

/**
 * Ergonomic aliases over the generated OpenAPI types.
 *
 * `schema.d.ts` is generated — never edit it. Regenerate after any backend
 * route/schema change:
 *   backend$  uv run python scripts/dump_openapi.py
 *   frontend$ npm run gen:api
 * A renamed or removed backend field becomes a TypeScript error here, which is
 * the entire point of generating rather than hand-writing these.
 */

type S = components["schemas"];

// --- Enums -----------------------------------------------------------------
export type UserRole = S["UserRole"];
export type UserStatus = S["UserStatus"];
export type SchoolStatus = S["SchoolStatus"];
export type StudentStatus = S["StudentStatus"];
export type SubscriptionPlan = S["SubscriptionPlan"];
export type Gender = S["Gender"];
export type SortDirection = S["SortDirection"];

// --- Auth ------------------------------------------------------------------
export type LoginRequest = S["LoginRequest"];
export type LoginResult = S["LoginResult"];
export type TokenPair = S["TokenPair"];
export type UserRead = S["UserRead"];
export type RegisterRequest = S["RegisterRequest"];
export type RegisterResponse = S["RegisterResponse"];
export type Verify2FARequest = S["Verify2FARequest"];
export type VerifyEmailRequest = S["VerifyEmailRequest"];
export type ForgotPasswordRequest = S["ForgotPasswordRequest"];
export type ResetPasswordRequest = S["ResetPasswordRequest"];
export type ResendVerificationRequest = S["ResendVerificationRequest"];
export type MessageResponse = S["MessageResponse"];

// --- Students --------------------------------------------------------------
export type StudentRead = S["StudentRead"];
export type StudentCreate = S["StudentCreate"];
export type StudentUpdate = S["StudentUpdate"];
export type StudentAdmissionRequest = S["StudentAdmissionRequest"];
export type AdmissionResponse = S["AdmissionResponse"];

// --- Academics -------------------------------------------------------------
export type ClassRead = S["ClassRead"];
export type ClassCreate = S["ClassCreate"];
export type ClassUpdate = S["ClassUpdate"];
export type ClassSummary = S["ClassSummary"];
export type SectionRead = S["SectionRead"];
export type SectionCreate = S["SectionCreate"];
export type SectionUpdate = S["SectionUpdate"];
export type SectionSummary = S["SectionSummary"];

// --- Tenancy ---------------------------------------------------------------
export type SchoolRead = S["SchoolRead"];
export type SchoolCreate = S["SchoolCreate"];
export type SchoolUpdate = S["SchoolUpdate"];

// --- Pagination ------------------------------------------------------------
export type PageMeta = S["PageMeta"];

/** The backend's `Page[T]` envelope, generic over the item type. */
export interface Page<T> {
  items: T[];
  meta: PageMeta;
}

export interface PageParams {
  page?: number;
  size?: number;
  sort_by?: string | null;
  sort_dir?: SortDirection;
}

// --- Display labels --------------------------------------------------------
// Keys are exhaustive over each enum, so adding a backend variant fails to
// compile here until the UI gets a label for it.

export const USER_ROLE_LABELS: Record<UserRole, string> = {
  super_admin: "Super Admin",
  school_admin: "School Admin",
  teacher: "Teacher",
};

export const STUDENT_STATUS_LABELS: Record<StudentStatus, string> = {
  pending: "Pending",
  active: "Active",
  inactive: "Inactive",
  graduated: "Graduated",
  transferred: "Transferred",
};

export const SCHOOL_STATUS_LABELS: Record<SchoolStatus, string> = {
  pending_approval: "Pending Approval",
  active: "Active",
  suspended: "Suspended",
  cancelled: "Cancelled",
};

export const USER_STATUS_LABELS: Record<UserStatus, string> = {
  pending_verification: "Pending Verification",
  active: "Active",
  suspended: "Suspended",
};

export const PLAN_LABELS: Record<SubscriptionPlan, string> = {
  trial: "Trial",
  basic: "Basic",
  standard: "Standard",
  premium: "Premium",
};

export const GENDER_LABELS: Record<Gender, string> = {
  male: "Male",
  female: "Female",
  other: "Other",
};
