import { z } from "zod";

import type { ClassCreate, SectionCreate } from "@/lib/api/types";

/**
 * Class and section form schemas.
 *
 * Numeric fields are validated as strings rather than with `z.coerce.number()`:
 * a cleared `<input type="number">` yields `""`, which coercion turns into `0` —
 * silently capping a section at zero seats instead of leaving it uncapped.
 * Parsing happens once, explicitly, in the payload builders below.
 */

const WHOLE_NUMBER = /^\d+$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const classFormSchema = z.object({
  name: z.string().trim().min(1, "Class name is required").max(80, "Keep this under 80 characters"),
  level: z
    .string()
    .trim()
    .min(1, "Level is required")
    .refine((value) => WHOLE_NUMBER.test(value), "Level must be a whole number")
    .refine((value) => Number(value) <= 100, "Level must be 100 or below"),
});
export type ClassFormValues = z.infer<typeof classFormSchema>;

export const sectionFormSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Section name is required")
    .max(40, "Keep this under 40 characters"),
  capacity: z
    .string()
    .trim()
    .refine((value) => value === "" || WHOLE_NUMBER.test(value), "Capacity must be a whole number")
    .refine((value) => value === "" || Number(value) >= 1, "Capacity must be at least 1"),
  class_teacher_id: z
    .string()
    .trim()
    .refine((value) => value === "" || UUID.test(value), "Enter a valid teacher ID"),
});
export type SectionFormValues = z.infer<typeof sectionFormSchema>;

export function toClassPayload(values: ClassFormValues): ClassCreate {
  return { name: values.name.trim(), level: Number(values.level) };
}

/** Blank capacity means "uncapped", which the API models as null rather than 0. */
export function toSectionPayload(values: SectionFormValues): SectionCreate {
  return {
    name: values.name.trim(),
    capacity: values.capacity === "" ? null : Number(values.capacity),
    class_teacher_id: values.class_teacher_id === "" ? null : values.class_teacher_id.trim(),
  };
}
