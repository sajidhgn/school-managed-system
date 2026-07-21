import { z } from "zod";

/**
 * Student form schemas.
 *
 * Optional text fields use `""` in the form (controlled inputs cannot hold
 * null) and are converted to `null` on submit — the backend distinguishes
 * "cleared" from "not provided".
 */

const optionalText = (max: number) => z.string().trim().max(max).optional().or(z.literal(""));

/** HTML date inputs emit "" when empty and YYYY-MM-DD otherwise. */
const optionalDate = z
  .string()
  .optional()
  .or(z.literal(""))
  .refine((value) => !value || /^\d{4}-\d{2}-\d{2}$/.test(value), "Enter a valid date");

const optionalEmail = z
  .string()
  .trim()
  .optional()
  .or(z.literal(""))
  .refine((value) => !value || z.string().email().safeParse(value).success, "Enter a valid email");

/** Fields shared by the admin form and the public admissions form. */
const personFields = {
  first_name: z.string().trim().min(1, "First name is required").max(100),
  last_name: z.string().trim().min(1, "Last name is required").max(100),
  date_of_birth: optionalDate,
  gender: z.enum(["male", "female", "other"]).optional().or(z.literal("")),
  address: optionalText(500),
  guardian_name: optionalText(200),
  guardian_phone: optionalText(40),
  guardian_email: optionalEmail,
  emergency_contact_name: optionalText(200),
  emergency_contact_phone: optionalText(40),
};

export const studentFormSchema = z.object({
  ...personFields,
  admission_number: z.string().trim().min(1, "Admission number is required").max(50),
  section_id: z.string().optional().or(z.literal("")),
  status: z.enum(["pending", "active", "inactive", "graduated", "transferred"]),
  enrolled_on: optionalDate,
});
export type StudentFormValues = z.infer<typeof studentFormSchema>;

/** Public admissions form — no admission number, no status, no section. */
export const admissionFormSchema = z.object({
  ...personFields,
  guardian_name: z.string().trim().min(1, "Guardian name is required").max(200),
  guardian_phone: z.string().trim().min(1, "Guardian phone is required").max(40),
});
export type AdmissionFormValues = z.infer<typeof admissionFormSchema>;

/** Strip empty strings to null for the API payload. */
export function toNullable<T extends Record<string, unknown>>(values: T) {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(values)) {
    out[key] = value === "" ? null : value;
  }
  return out;
}
