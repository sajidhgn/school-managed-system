import { z } from "zod";

/**
 * Client-side mirrors of the backend Pydantic models.
 *
 * Bounds are copied from the OpenAPI schema (min/max lengths) so the browser
 * rejects what the server would reject anyway — instant feedback, one fewer
 * round trip. The server remains the authority; this is UX, not validation.
 */

const email = z.string().min(1, "Email is required").email("Enter a valid email address");

/** Backend: min 8, max 128. */
const password = z
  .string()
  .min(8, "Password must be at least 8 characters")
  .max(128, "Password must be at most 128 characters");

/** Backend: min 4, max 12 — emailed verification/2FA/reset codes. */
const code = z
  .string()
  .min(4, "Enter the code from your email")
  .max(12, "That code is too long");

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Password is required").max(128),
});
export type LoginValues = z.infer<typeof loginSchema>;

export const verify2faSchema = z.object({ email, code });
export type Verify2faValues = z.infer<typeof verify2faSchema>;

export const registerSchema = z
  .object({
    school_name: z.string().min(2, "School name is too short").max(200),
    school_email: email,
    school_phone: z.string().max(40).optional().or(z.literal("")),
    full_name: z.string().min(2, "Enter your full name").max(200),
    email,
    password,
    confirm_password: z.string(),
  })
  .refine((values) => values.password === values.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });
export type RegisterValues = z.infer<typeof registerSchema>;

export const verifyEmailSchema = z.object({ email, code });
export type VerifyEmailValues = z.infer<typeof verifyEmailSchema>;

export const forgotPasswordSchema = z.object({ email });
export type ForgotPasswordValues = z.infer<typeof forgotPasswordSchema>;

export const resetPasswordSchema = z
  .object({
    email,
    code,
    new_password: password,
    confirm_password: z.string(),
  })
  .refine((values) => values.new_password === values.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>;
