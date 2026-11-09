import { z } from "zod";

import type { Translation } from "@/lib/i18n/catalog";
import type { adminMessages } from "@/lib/i18n/modules/admin";

/**
 * Mirrors the backend's `SchoolCreate` / `SchoolUpdate` bounds.
 *
 * Built from the viewer's validation messages (`adminMessages.validation`), so a
 * form error reads in their language.
 */

type ValidationMessages = Translation<(typeof adminMessages)["en"]>["validation"];

export function createSchoolCreateSchema(m: ValidationMessages) {
  return z.object({
    name: z.string().min(2, m.enterSchoolName).max(200),
    code: z
      .string()
      .min(1, m.schoolCodeRequired)
      .max(32, m.schoolCodeMax)
      // Constrained because the code lands on ID cards, report headers and export
      // filenames. Spaces and punctuation survive none of those cleanly.
      .regex(/^[A-Za-z0-9_-]+$/, m.schoolCodePattern),
    city: z.string().max(100).optional().or(z.literal("")),
    logo_url: z.string().optional(),
  });
}
export type SchoolCreateValues = z.infer<ReturnType<typeof createSchoolCreateSchema>>;

export function createSchoolUpdateSchema(m: ValidationMessages) {
  return z.object({
    name: z.string().min(2, m.enterSchoolName).max(200),
    email: z.string().email(m.emailInvalid).optional().or(z.literal("")),
    phone: z.string().max(32).optional().or(z.literal("")),
    address: z.string().max(500).optional().or(z.literal("")),
    city: z.string().max(100).optional().or(z.literal("")),
    academic_year_start_month: z.coerce.number().int().min(1).max(12),
    timezone: z.string().max(64).optional().or(z.literal("")),
  });
}
export type SchoolUpdateValues = z.infer<ReturnType<typeof createSchoolUpdateSchema>>;
