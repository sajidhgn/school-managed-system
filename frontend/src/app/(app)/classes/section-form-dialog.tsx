"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import dynamic from "next/dynamic";
import { Controller, useForm } from "react-hook-form";

import { Field, FormError } from "@/components/form/field";
import { isInsidePortalledMenu } from "@/components/form/select-portal";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useCreateSection, useUpdateSection } from "@/hooks/use-classes";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { fill } from "@/lib/i18n/format";
import { classesMessages } from "@/lib/i18n/modules/classes";
import { useCatalog } from "@/lib/i18n/use-catalog";
import {
  createSectionFormSchema,
  toSectionPayload,
  type SectionFormValues,
} from "@/lib/validation/classes";

/** Both SectionRead and SectionSummary satisfy this, so either can be edited. */
export type EditableSection = {
  id: string;
  name: string;
  capacity: number | null;
  class_teacher_id: string | null;
};

const EMPTY: SectionFormValues = { name: "", capacity: "", class_teacher_id: "" };

/**
 * Loaded on demand, not with the page.
 *
 * react-select brings Emotion with it -- together about 30kB, which is more than the
 * entire classes route otherwise weighs. Every visitor to /classes was paying for it,
 * including the majority who only ever read the table. It lives behind a dialog that
 * one administrator opens occasionally, so it loads when that dialog does.
 *
 * `ssr: false` because the control is interactive-only: there is nothing meaningful to
 * render on the server for a combobox whose options arrive from a client query.
 */
const TeacherSelect = dynamic(
  () => import("@/components/form/teacher-select").then((m) => m.TeacherSelect),
  {
    ssr: false,
    loading: () => (
      <div
        className="h-9 w-full animate-pulse rounded-md border border-input bg-muted/40"
        aria-hidden
      />
    ),
  },
);

/**
 * Create/edit section within a class.
 *
 * The parent class is fixed by `classId` rather than being a form field — a
 * section cannot be moved between classes without re-seating every student, so
 * offering it here would imply a capability the API does not have.
 */
export function SectionFormDialog({
  open,
  onOpenChange,
  classId,
  classLabel,
  section,
  schoolId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  classId: string;
  classLabel: string;
  section?: EditableSection | null;
  /** The campus this class belongs to -- scopes the class-teacher list to its staff. */
  schoolId: string | null;
}) {
  const { sectionForm: m, validation } = useCatalog(classesMessages);
  const schema = React.useMemo(() => createSectionFormSchema(validation), [validation]);
  const isEdit = Boolean(section);
  const [formError, setFormError] = React.useState<string | null>(null);

  const createSection = useCreateSection();
  const updateSection = useUpdateSection();

  const form = useForm<SectionFormValues>({
    resolver: zodResolver(schema),
    defaultValues: EMPTY,
  });

  React.useEffect(() => {
    if (!open) return;
    setFormError(null);
    form.reset(
      section
        ? {
            name: section.name,
            capacity: section.capacity === null ? "" : String(section.capacity),
            class_teacher_id: section.class_teacher_id ?? "",
          }
        : EMPTY,
    );
  }, [open, section, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    const payload = toSectionPayload(values);

    try {
      if (isEdit && section) {
        await updateSection.mutateAsync({ sectionId: section.id, classId, body: payload });
      } else {
        await createSection.mutateAsync({ classId, body: payload });
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError) {
        // Section names must be unique within a class; that clash is a 409.
        if (error.status === 409) {
          form.setError("name", { message: error.message });
          return;
        }
        let matched = false;
        for (const [name, message] of Object.entries(error.fieldErrors())) {
          if (name in values) {
            form.setError(name as keyof SectionFormValues, { message });
            matched = true;
          }
        }
        if (matched) return;
      }
      setFormError(errorMessage(error));
    }
  });

  const saving = createSection.isPending || updateSection.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-md"
        // The teacher menu is portalled to `document.body` to escape this dialog's
        // clipping, which puts it outside the dismissable layer. Without these two
        // guards, picking a teacher counts as a click outside and closes the form
        // instead of filling the field. See `select-portal.ts`.
        onPointerDownOutside={(event) => {
          if (isInsidePortalledMenu(event.detail.originalEvent)) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (isInsidePortalledMenu(event.detail.originalEvent)) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>{isEdit ? m.editTitle : m.addTitle}</DialogTitle>
          <DialogDescription>
            {fill(isEdit ? m.editDescription : m.addDescription, { class: classLabel })}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          <FormError message={formError} />

          <div className="grid gap-4">
            <Field
              label={m.name}
              htmlFor="name"
              error={form.formState.errors.name}
              hint={m.nameHint}
              required
            >
              <Input autoFocus {...form.register("name")} />
            </Field>

            <Field
              label={m.capacity}
              htmlFor="capacity"
              error={form.formState.errors.capacity}
              hint={m.capacityHint}
            >
              <Input type="number" min={1} step={1} {...form.register("capacity")} />
            </Field>

            <Field
              label={m.classTeacher}
              htmlFor="class_teacher_id"
              error={form.formState.errors.class_teacher_id}
              hint={m.classTeacherHint}
            >
              {/*
                `Controller`, not `register`: react-select is a custom listbox, not an
                input with a ref and an onChange event, so `{...register(...)}` has
                nothing to attach to. Same reason the Radix select needs a wrapper --
                see `NativeSelect`'s docstring.
              */}
              <Controller
                control={form.control}
                name="class_teacher_id"
                render={({ field, fieldState }) => (
                  <TeacherSelect
                    schoolId={schoolId}
                    value={field.value}
                    onChange={field.onChange}
                    onBlur={field.onBlur}
                    // Passed EXPLICITLY, not left to `Field`. Field wires labels and
                    // errors up by cloning its child and injecting `id` and the
                    // `aria-*` pair -- but its child here is `Controller`, which
                    // renders whatever it likes and drops unknown props on the floor.
                    // Without these the `<label for="class_teacher_id">` points at
                    // nothing: clicking it focuses no control, and a screen reader
                    // never hears the hint or the error.
                    id="class_teacher_id"
                    aria-invalid={fieldState.error ? true : undefined}
                    aria-describedby={
                      fieldState.error ? "class_teacher_id-error" : "class_teacher_id-hint"
                    }
                  />
                )}
              />
            </Field>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              {m.cancel}
            </Button>
            <Button type="submit" loading={saving}>
              {isEdit ? m.saveChanges : m.add}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
