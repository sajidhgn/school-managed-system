import { z } from "zod";

import type { ClassCreate, SectionCreate } from "@/lib/api/types";
import type { Translation } from "@/lib/i18n/catalog";
import type { classesMessages } from "@/lib/i18n/modules/classes";

/**
 * Class and section form schemas.
 *
 * Numeric fields are validated as strings rather than with `z.coerce.number()`:
 * a cleared `<input type="number">` yields `""`, which coercion turns into `0` —
 * silently capping a section at zero seats instead of leaving it uncapped.
 * Parsing happens once, explicitly, in the payload builders below.
 *
 * The schemas are built from the viewer's validation messages
 * (`classesMessages.validation`), so a form error reads in their language.
 */

type ValidationMessages = Translation<(typeof classesMessages)["en"]>["validation"];

const WHOLE_NUMBER = /^\d+$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function createClassFormSchema(m: ValidationMessages) {
  return z.object({
    name: z.string().trim().min(1, m.classNameRequired).max(80, m.under80),
    level: z
      .string()
      .trim()
      .min(1, m.levelRequired)
      .refine((value) => WHOLE_NUMBER.test(value), m.levelWhole)
      .refine((value) => Number(value) <= 100, m.levelMax),
  });
}
export type ClassFormValues = z.infer<ReturnType<typeof createClassFormSchema>>;

export function createSectionFormSchema(m: ValidationMessages) {
  return z.object({
    name: z.string().trim().min(1, m.sectionNameRequired).max(40, m.under40),
    capacity: z
      .string()
      .trim()
      .refine((value) => value === "" || WHOLE_NUMBER.test(value), m.capacityWhole)
      .refine((value) => value === "" || Number(value) >= 1, m.capacityMin),
    // Kept as a guard, not as a prompt. The field is a picker now, so the only values
    // it can produce are a teacher's user id or "" -- but this schema is also what
    // `toSectionPayload` is typed against, and a malformed id should fail here rather
    // than travel to the API and come back as a foreign key error.
    class_teacher_id: z
      .string()
      .trim()
      .refine((value) => value === "" || UUID.test(value), m.selectTeacher),
  });
}
export type SectionFormValues = z.infer<ReturnType<typeof createSectionFormSchema>>;

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
