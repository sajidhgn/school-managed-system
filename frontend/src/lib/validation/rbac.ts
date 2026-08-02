import { z } from "zod";

/** Mirrors the backend's `RoleCreate`, `InvitationCreate` and `MemberUpdate`. */

export const roleCreateSchema = z.object({
  code: z
    .string()
    .min(2, "Enter a code")
    .max(50)
    // Matches the server's pattern exactly. The code appears in the token's `rol`
    // claim and in permission-check code, so mixed case or spaces would make those
    // comparisons quietly fragile.
    .regex(/^[a-z][a-z0-9_]*$/, "Lowercase letters, numbers and underscores; must start with a letter"),
  name: z.string().min(2, "Enter a display name").max(100),
  description: z.string().max(500).optional().or(z.literal("")),
  permissions: z.array(z.string()).default([]),
});
export type RoleCreateValues = z.infer<typeof roleCreateSchema>;

export const invitationCreateSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  full_name: z.string().max(200).optional().or(z.literal("")),
  role_id: z.string().uuid("Choose a role"),
});
export type InvitationCreateValues = z.infer<typeof invitationCreateSchema>;
