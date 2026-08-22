import { z } from "zod";

/**
 * Client-side mirrors of the backend Pydantic models.
 *
 * Bounds are copied from the OpenAPI schema so the browser rejects what the server
 * would reject anyway — instant feedback, one fewer round trip. The server remains
 * the authority; this is UX, not validation.
 *
 * =============================================================================
 * PASSWORD STRENGTH IS NOT MIRRORED HERE, AND THAT IS DELIBERATE
 * =============================================================================
 *   The backend's real policy is a length floor PLUS a zxcvbn score >= 3 PLUS a
 *   breached-password list. Reimplementing that in the browser would mean shipping
 *   zxcvbn's dictionaries to every visitor, and the two implementations would drift
 *   the first time the server tuned its threshold.
 *
 *   So the client checks only the length floor and surfaces the server's specific
 *   rejection — which arrives as a 422 carrying the actual reason ("this password
 *   appears in known data breaches"). That message is more useful to the user than
 *   anything a mirrored rule could produce.
 */

const email = z.string().min(1, "Email is required").email("Enter a valid email address");

/** Backend: PASSWORD_MIN_LENGTH (10), plus entropy checks it performs itself. */
const password = z
  .string()
  .min(10, "Use at least 10 characters")
  .max(200, "That password is too long");

const token = z.string().min(16, "This link looks incomplete").max(512);

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Password is required").max(200),
});
export type LoginValues = z.infer<typeof loginSchema>;

export const platformLoginSchema = loginSchema.extend({
  totp_code: z
    .string()
    .regex(/^\d{6}$/, "Enter the 6-digit authentication code")
    .optional()
    .or(z.literal("")),
});
export type PlatformLoginValues = z.infer<typeof platformLoginSchema>;

export const signupSchema = z
  .object({
    full_name: z.string().min(2, "Enter your full name").max(200),
    email,
    organization_name: z.string().min(2, "Enter your organization's name").max(200),
    country: z.string().length(2, "Use a 2-letter country code").optional().or(z.literal("")),
    plan_code: z.string().min(1).max(50),
    billing_cycle: z.enum(["monthly", "yearly"]),
    password,
    confirm_password: z.string(),
  })
  .refine((values) => values.password === values.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });
export type SignupValues = z.infer<typeof signupSchema>;

export const forgotPasswordSchema = z.object({ email });
export type ForgotPasswordValues = z.infer<typeof forgotPasswordSchema>;

export const resetPasswordSchema = z
  .object({
    token,
    password,
    confirm_password: z.string(),
  })
  .refine((values) => values.password === values.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>;

/**
 * Invitation acceptance.
 *
 * Name and password travel together or not at all — mirroring the backend's own
 * model validator. Both present means "create my account" (the new-user branch);
 * both absent means "I am already signed in as this address" (the existing-user
 * branch). A half-filled form is neither, so it is rejected here rather than left
 * for the server to puzzle over.
 */
export const acceptInviteSchema = z
  .object({
    token,
    full_name: z.string().max(200).optional().or(z.literal("")),
    password: z.string().max(200).optional().or(z.literal("")),
    confirm_password: z.string().optional().or(z.literal("")),
  })
  .refine((v) => !v.password || v.password.length >= 10, {
    message: "Use at least 10 characters",
    path: ["password"],
  })
  .refine((v) => !v.password || (v.full_name?.length ?? 0) >= 2, {
    message: "Enter your full name",
    path: ["full_name"],
  })
  .refine((v) => (v.password ?? "") === (v.confirm_password ?? ""), {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });
export type AcceptInviteValues = z.infer<typeof acceptInviteSchema>;
