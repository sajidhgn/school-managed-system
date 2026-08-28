/**
 * Permission checks for the UI.
 *
 * =============================================================================
 * UI HIDING IS COSMETIC ONLY — spec §9
 * =============================================================================
 *   Every one of these maps to a `require("...")` dependency on the server, which is
 *   what actually enforces access. Hiding a button the API would reject is a
 *   courtesy to the user, nothing more: it keeps the interface honest about what
 *   they can do instead of presenting controls that fail.
 *
 *   Treating these as security would be a mistake. The permission list arrives from
 *   `GET /auth/me` over a channel the user controls, and every guarded action is one
 *   `curl` away from bypassing the UI entirely. The server does not trust this file,
 *   and neither should a reader.
 *
 * WHY STRING CODES RATHER THAN ROLE NAMES
 *   This replaced a `role === "school_admin"` check. Customers create custom roles —
 *   "Head of Year", "Registrar" — and a role-name comparison cannot express them. It
 *   would force every school wanting a slightly different job title to hand out the
 *   full admin role, which is how least-privilege quietly stops being practised.
 */

export interface PermissionSource {
  permissions: string[];
}

/** True when the holder has EVERY code. Mirrors the server's `AuthContext.has`. */
export function can(source: PermissionSource | null | undefined, ...codes: string[]): boolean {
  if (!source) return false;
  return codes.every((code) => source.permissions.includes(code));
}

/**
 * True when the holder has AT LEAST ONE of the codes.
 *
 * For nav sections several different permissions can unlock — the "People" group is
 * worth showing to someone who can read members OR manage roles OR see invitations,
 * and requiring all three would hide it from almost everyone.
 */
export function canAny(source: PermissionSource | null | undefined, ...codes: string[]): boolean {
  if (!source) return false;
  return codes.some((code) => source.permissions.includes(code));
}

// `homeRouteFor()` used to live here, routing a user with no SCHOOL membership to
// /onboarding. That test is unanswerable now: the principal holds one org-level
// membership however many campuses exist, so it reported "no schools" forever. Only
// the school list knows, so the decision moved to the two pages that already fetch
// it -- `/onboarding` redirects out when schools exist, and `/dashboard` shows the
// "create your first school" prompt when they do not.
