import { z } from "zod";

/** Mirrors the backend's `SchoolCreate` / `SchoolUpdate` bounds. */

export const schoolCreateSchema = z.object({
  name: z.string().min(2, "Enter the school's name").max(200),
  code: z
    .string()
    .min(1, "A short code is required")
    .max(32, "Keep the code under 32 characters")
    // Constrained because the code lands on ID cards, report headers and export
    // filenames. Spaces and punctuation survive none of those cleanly.
    .regex(/^[A-Za-z0-9_-]+$/, "Use letters, numbers, hyphens or underscores only"),
  city: z.string().max(100).optional().or(z.literal("")),
  logo_url: z.string().optional(),
});
export type SchoolCreateValues = z.infer<typeof schoolCreateSchema>;

export const schoolUpdateSchema = z.object({
  name: z.string().min(2, "Enter the school's name").max(200),
  email: z.string().email("Enter a valid email address").optional().or(z.literal("")),
  phone: z.string().max(32).optional().or(z.literal("")),
  address: z.string().max(500).optional().or(z.literal("")),
  city: z.string().max(100).optional().or(z.literal("")),
  academic_year_start_month: z.coerce.number().int().min(1).max(12),
  timezone: z.string().max(64).optional().or(z.literal("")),
});
export type SchoolUpdateValues = z.infer<typeof schoolUpdateSchema>;
