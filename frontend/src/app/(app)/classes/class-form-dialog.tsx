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
import { useCreateClass, useUpdateClass } from "@/hooks/use-classes";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { classFormSchema, toClassPayload, type ClassFormValues } from "@/lib/validation/classes";

/** Both ClassRead and ClassSummary satisfy this, so either can be edited. */
export type EditableClass = { id: string; name: string; level: number };

const EMPTY: ClassFormValues = { name: "", level: "" };

/**
 * Create/edit class.
 *
 * One dialog serves both modes: `schoolClass` present means edit (PATCH),
 * absent means create (POST).
 */
export function ClassFormDialog({
  open,
  onOpenChange,
  schoolClass,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  schoolClass?: EditableClass | null;
}) {
  const isEdit = Boolean(schoolClass);
  const [formError, setFormError] = React.useState<string | null>(null);

  const createClass = useCreateClass();
  const updateClass = useUpdateClass();

  const form = useForm<ClassFormValues>({
    resolver: zodResolver(classFormSchema),
    defaultValues: EMPTY,
  });

  // Re-seed whenever the dialog opens, so a previous edit never leaks into the
  // next one.
  React.useEffect(() => {
    if (!open) return;
    setFormError(null);
    form.reset(
      schoolClass ? { name: schoolClass.name, level: String(schoolClass.level) } : EMPTY,
    );
  }, [open, schoolClass, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    const payload = toClassPayload(values);

    try {
      if (isEdit && schoolClass) {
        await updateClass.mutateAsync({ id: schoolClass.id, body: payload });
      } else {
        await createClass.mutateAsync(payload);
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError) {
        // A duplicate class name comes back as a 409, not a field error.
        if (error.status === 409) {
          form.setError("name", { message: error.message });
          return;
        }
        let matched = false;
        for (const [name, message] of Object.entries(error.fieldErrors())) {
          if (name in values) {
            form.setError(name as keyof ClassFormValues, { message });
            matched = true;
          }
        }
        if (matched) return;
      }
      setFormError(errorMessage(error));
    }
  });

  const saving = createClass.isPending || updateClass.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit class" : "Add class"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update this class's name or level."
              : "Create a new class. You can add its sections afterwards."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          <FormError message={formError} />

          <div className="grid gap-4">
            <Field
              label="Class name"
              htmlFor="name"
              error={form.formState.errors.name}
              hint="For example, Grade 10."
              required
            >
              <Input autoFocus {...form.register("name")} />
            </Field>

            <Field
              label="Level"
              htmlFor="level"
              error={form.formState.errors.level}
              hint="Numeric rank used to order classes across the school."
              required
            >
              <Input type="number" min={0} max={100} step={1} {...form.register("level")} />
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
              {isEdit ? "Save changes" : "Add class"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
