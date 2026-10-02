import { api, authRequest } from "@/lib/api/client";
import type {
  AuditLogRead,
  InvitationCreate,
  InvitationRead,
  InvoiceRead,
  MemberRead,
  MemberCreate,
  MemberUpdate,
  PlanAdminRead,
  PlanImpactResponse,
  PlanPatch,
  PlanWrite,
  OrganizationRead,
  OrganizationUpdate,
  Page,
  PageParams,
  PermissionCategory,
  RoleCreate,
  RoleDetail,
  RoleRead,
  RoleUpdate,
  SchoolCreate,
  SchoolRead,
  SchoolUpdate,
  SubscribeRequest,
  SubscriptionRead,
  TeacherOption,
  UsageResponse,
} from "@/lib/api/types";

/**
 * Typed wrappers over the BFF proxy.
 *
 * One function per endpoint, named for the operation rather than the URL, so a route
 * change is a one-line edit here instead of a grep through components. Every path is
 * relative to `/api/bff`, which attaches the session server-side — no component ever
 * handles a token.
 *
 * The generic parameter is the RESPONSE type, taken from the generated schema. If the
 * backend renames a field, the compile error surfaces at the call site that reads it.
 */

// --- Organization ----------------------------------------------------------
export const organization = {
  get: () => api.get<OrganizationRead>("/org"),
  update: (body: OrganizationUpdate) => api.patch<OrganizationRead>("/org", body),
  usage: () => api.get<UsageResponse>("/org/usage"),
  transferOwnership: (membershipId: string) =>
    api.post<OrganizationRead>("/org/transfer-ownership", {
      new_owner_membership_id: membershipId,
    }),
};

// --- Schools ---------------------------------------------------------------
export const schools = {
  list: () => api.get<SchoolRead[]>("/schools"),
  get: (id: string) => api.get<SchoolRead>(`/schools/${id}`),
  create: (body: SchoolCreate) => api.post<SchoolRead>("/schools", body),
  update: (id: string, body: SchoolUpdate) => api.patch<SchoolRead>(`/schools/${id}`, body),
  archive: (id: string) => api.post<SchoolRead>(`/schools/${id}/archive`),
  /**
   * Make this the campus the school-scoped pages act on.
   *
   * Not a BFF call: it writes an httpOnly cookie, so it goes to the dedicated
   * route handler like the other session-shaped operations. Nothing is re-issued —
   * an org-level user's authority is identical before and after.
   */
  setActive: (id: string) => authRequest<SchoolRead>("/school", { school_id: id }),
};

// --- Roles & permissions ---------------------------------------------------
export const roles = {
  catalog: () => api.get<PermissionCategory[]>("/permissions"),
  list: (schoolId: string) => api.get<RoleRead[]>(`/schools/${schoolId}/roles`),
  get: (schoolId: string, roleId: string) =>
    api.get<RoleDetail>(`/schools/${schoolId}/roles/${roleId}`),
  create: (schoolId: string, body: RoleCreate) =>
    api.post<RoleDetail>(`/schools/${schoolId}/roles`, body),
  update: (schoolId: string, roleId: string, body: RoleUpdate) =>
    api.patch<RoleRead>(`/schools/${schoolId}/roles/${roleId}`, body),
  /** REPLACES the whole set — see `RolePermissionsUpdate` for why it is not a merge. */
  setPermissions: (schoolId: string, roleId: string, codes: string[]) =>
    api.put<RoleDetail>(`/schools/${schoolId}/roles/${roleId}/permissions`, { codes }),
  remove: (schoolId: string, roleId: string) =>
    api.delete<void>(`/schools/${schoolId}/roles/${roleId}`),
};

// --- Members ---------------------------------------------------------------
export const members = {
  list: (schoolId: string, params: PageParams = {}) =>
    api.get<Page<MemberRead>>(`/schools/${schoolId}/members`, { params: { ...params } }),
  /**
   * The branch's teaching staff, for the class-teacher and curriculum pickers.
   *
   * Separate from `list` because it answers a different question and is gated on a
   * different permission (`teacher:read`, not `member:read`). It also returns far
   * less per row -- see `TeacherOption`.
   */
  teachers: (schoolId: string) => api.get<TeacherOption[]>(`/schools/${schoolId}/teachers`),
  create: (schoolId: string, body: MemberCreate) =>
    api.post<MemberRead>(`/schools/${schoolId}/members`, body),
  update: (schoolId: string, membershipId: string, body: MemberUpdate) =>
    api.patch<MemberRead>(`/schools/${schoolId}/members/${membershipId}`, body),
  assignBranches: (schoolId: string, membershipId: string, schoolIds: string[]) =>
    api.post<MemberRead[]>(`/schools/${schoolId}/members/${membershipId}/branches`, {
      school_ids: schoolIds,
    }),
  remove: (schoolId: string, membershipId: string) =>
    api.delete<void>(`/schools/${schoolId}/members/${membershipId}`),
};

// --- Invitations -----------------------------------------------------------
export const invitations = {
  list: (schoolId: string) => api.get<InvitationRead[]>(`/schools/${schoolId}/invitations`),
  create: (schoolId: string, body: InvitationCreate) =>
    api.post<InvitationRead>(`/schools/${schoolId}/invitations`, body),
  resend: (schoolId: string, id: string) =>
    api.post<InvitationRead>(`/schools/${schoolId}/invitations/${id}/resend`),
  revoke: (schoolId: string, id: string) =>
    api.delete<InvitationRead>(`/schools/${schoolId}/invitations/${id}`),
  /** Gone for good, pending or not; a pending one's seat is returned. */
  remove: (schoolId: string, id: string) =>
    api.delete<void>(`/schools/${schoolId}/invitations/${id}/permanent`),
};

// --- Billing ---------------------------------------------------------------
export const billing = {
  subscription: () => api.get<SubscriptionRead>("/billing/subscription"),
  subscribe: (body: SubscribeRequest) =>
    api.post<SubscriptionRead>("/billing/subscribe", body, {
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
  changePlan: (body: SubscribeRequest) =>
    api.post<SubscriptionRead>("/billing/change-plan", body, {
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
  cancel: () =>
    api.post<SubscriptionRead>("/billing/cancel", { at_period_end: true }, {
      headers: { "Idempotency-Key": crypto.randomUUID() },
    }),
  invoices: () => api.get<InvoiceRead[]>("/billing/invoices"),
};

// --- Platform console ------------------------------------------------------
//
// Only the plan-management calls live here; the console's read endpoints are
// fetched by Server Components through `serverGet`. These are the mutations, which
// necessarily run in the browser.
export const platformPlans = {
  list: () => api.get<PlanAdminRead[]>("/platform/plans"),
  create: (body: PlanWrite) => api.post<PlanAdminRead>("/platform/plans", body),
  update: (id: string, body: PlanPatch) =>
    api.patch<PlanAdminRead>(`/platform/plans/${id}`, body),
  /** Dry run. Nothing is written; see `PlanImpactDialog` for why this exists. */
  impact: (id: string, limits: Record<string, number> | null) =>
    api.post<PlanImpactResponse>(`/platform/plans/${id}/impact`, { limits }),
  /** Retire — never a hard delete. Existing subscribers keep their terms. */
  retire: (id: string) => api.delete<PlanAdminRead>(`/platform/plans/${id}`),
};

// --- Audit -----------------------------------------------------------------
export const audit = {
  list: (schoolId: string, params?: { action?: string; limit?: number; before?: string }) =>
    api.get<AuditLogRead[]>(`/schools/${schoolId}/audit-logs`, { params }),
};
