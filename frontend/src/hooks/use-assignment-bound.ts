"use client";

import { useSession } from "@/components/providers/session-provider";
import { PERMISSIONS } from "@/lib/api/types";
import { can } from "@/lib/auth/permissions";

/**
 * Whether the server narrows this user's classes, students, registers and diaries
 * to the ones they are assigned to -- i.e. their role lacks `class:view_all`.
 *
 * Only for WORDING. An empty list means "nothing assigned to you" for a teacher and
 * "nothing created yet" for an administrator, and telling a teacher to "create your
 * first class" sends them looking for a button they will never have.
 */
export function useAssignmentBound(): boolean {
  const { user } = useSession();
  return !!user && !can(user, PERMISSIONS.classViewAll);
}

export const UNASSIGNED_TITLE = "Nothing assigned to you yet";
export const UNASSIGNED_DESCRIPTION =
  "You see the classes you teach. Ask your principal to make you class teacher of a section or subject teacher for a class.";
