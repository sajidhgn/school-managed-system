"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";

import { Field, FormError } from "@/components/form/field";
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
import { sectionFormSchema, toSectionPayload, type SectionFormValues } from "@/lib/validation/classes";

/** Both SectionRead and SectionSummary satisfy this, so either can be edited. */
export type EditableSection = {
  id: string;
  name: string;
  capacity: number | null;
  class_teacher_id: string | null;
};

const EMPTY: SectionFormValues = { name: "", capacity: "", class_teacher_id: "" };

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
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  classId: string;
  classLabel: string;
  section?: EditableSection | null;
}) {
  const isEdit = Boolean(section);
  const [formError, setFormError] = React.useState<string | null>(null);

  const createSection = useCreateSection();
  const updateSection = useUpdateSection();

  const form = useForm<SectionFormValues>({
    resolver: zodResolver(sectionFormSchema),
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
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit section" : "Add section"}</DialogTitle>
          <DialogDescription>
            {isEdit ? `Update this section of ${classLabel}.` : `Add a section to ${classLabel}.`}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          <FormError message={formError} />

          <div className="grid gap-4">
            <Field
              label="Section name"
              htmlFor="name"
              error={form.formState.errors.name}
              hint="For example, A or Blue."
              required
            >
              <Input autoFocus {...form.register("name")} />
            </Field>

            <Field
              label="Capacity"
              htmlFor="capacity"
              error={form.formState.errors.capacity}
              hint="Leave blank for no seat limit."
            >
              <Input type="number" min={1} step={1} {...form.register("capacity")} />
            </Field>

            <Field
              label="Class teacher ID"
              htmlFor="class_teacher_id"
              error={form.formState.errors.class_teacher_id}
              hint="Optional. Paste the teacher's user ID."
            >
              <Input {...form.register("class_teacher_id")} />
            </Field>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              {isEdit ? "Save changes" : "Add section"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
