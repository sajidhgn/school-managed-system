import { z } from "zod";

/**
 * School form schemas.
 *
 * Same convention as students.ts: optional text fields hold `""` in the form
 * (controlled inputs cannot hold null) and are converted to `null` on submit
 * via `toNullable`.
 */

const optionalText = (max: number) => z.string().trim().max(max).optional().or(z.literal(""));

const optionalUrl = z
  .string()
  .trim()
  .optional()
  .or(z.literal(""))
  .refine((value) => !value || z.string().url().safeParse(value).success, "Enter a valid URL");

/** Contact details — the subset a school can maintain about itself. */
const contactFields = {
  name: z.string().trim().min(2, "Name must be at least 2 characters").max(200),
  email: z
    .string()
    .trim()
    .min(1, "Email is required")
    .email("Enter a valid email"),
  phone: optionalText(40),
  address: optionalText(500),
  city: optionalText(120),
  country: optionalText(120),
};

export const schoolProfileFormSchema = z.object(contactFields);
export type SchoolProfileFormValues = z.infer<typeof schoolProfileFormSchema>;

/** Super-admin onboarding/edit — contact details plus the commercial terms. */
export const schoolFormSchema = z.object({
  ...contactFields,
  logo_url: optionalUrl,
  plan: z.enum(["trial", "basic", "standard", "premium"]),
  // Registered with `valueAsNumber`, so an empty input arrives as NaN and trips
  // the type error rather than silently posting 0.
  max_students: z
    .number({ invalid_type_error: "Enter a number" })
    .int("Enter a whole number")
    .min(1, "Must allow at least 1 student")
    .max(100_000),
});
export type SchoolFormValues = z.infer<typeof schoolFormSchema>;
