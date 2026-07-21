import type { UserRole } from "@/lib/api/types";

/**
 * Client-side role checks.
 *
 * These drive what the UI *shows* — they are not security. Every one of these
 * maps to a `require_roles(...)` dependency in the backend, which is what
 * actually enforces access. Hiding a button the API would reject is a courtesy
 * to the user, nothing more.
 */

export const can = {
  /** Manage students, classes, sections. Backend: require_roles("school_admin"). */
  manageSchoolData: (role: UserRole) => role === "school_admin",

  /** Onboard/approve/suspend schools. Backend: require_super_admin. */
  manageTenants: (role: UserRole) => role === "super_admin",

  /** Read-only visibility into rosters. Teachers get this, and admins too. */
  viewRosters: (role: UserRole) =>
    role === "school_admin" || role === "teacher" || role === "super_admin",
};

/** Where each role lands after login. */
export function homeRouteFor(role: UserRole): string {
  return role === "super_admin" ? "/schools" : "/dashboard";
}
