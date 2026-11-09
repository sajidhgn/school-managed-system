import { z } from "zod";

import type { Translation } from "@/lib/i18n/catalog";
import type { adminMessages } from "@/lib/i18n/modules/admin";

/**
 * Mirrors the backend's `RoleCreate`, `InvitationCreate` and `MemberUpdate`.
 *
 * Built from the viewer's validation messages (`adminMessages.validation`), so a
 * form error reads in their language.
 */

type ValidationMessages = Translation<(typeof adminMessages)["en"]>["validation"];

export function createRoleSchema(m: ValidationMessages) {
  return z.object({
    code: z
      .string()
      .min(2, m.enterCode)
      .max(50)
      // Matches the server's pattern exactly. The code appears in the token's `rol`
      // claim and in permission-check code, so mixed case or spaces would make those
      // comparisons quietly fragile.
      .regex(/^[a-z][a-z0-9_]*$/, m.roleCodePattern),
    name: z.string().min(2, m.enterDisplayName).max(100),
    description: z.string().max(500).optional().or(z.literal("")),
    permissions: z.array(z.string()).default([]),
  });
}
export type RoleCreateValues = z.infer<ReturnType<typeof createRoleSchema>>;

export function createInvitationSchema(m: ValidationMessages) {
  return z.object({
    email: z.string().min(1, m.emailRequired).email(m.emailInvalid),
    full_name: z.string().max(200).optional().or(z.literal("")),
    role_id: z.string().uuid(m.chooseRole),
  });
}
export type InvitationCreateValues = z.infer<ReturnType<typeof createInvitationSchema>>;

export function createMemberSchema(m: ValidationMessages) {
  return createInvitationSchema(m).extend({
    full_name: z.string().min(2, m.nameRequired).max(200),
    password: z.string().min(1, m.passwordRequired).max(200),
  });
}
export type MemberCreateValues = z.infer<ReturnType<typeof createMemberSchema>>;
