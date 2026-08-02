"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";

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
import { Input, Textarea } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/misc";
import { useClassSummary } from "@/hooks/use-classes";
import { useCreateStudent, useUpdateStudent } from "@/hooks/use-students";
import { ApiError, errorMessage } from "@/lib/api/errors";
import {
  studentFormSchema,
  toNullable,
  type StudentFormValues,
} from "@/lib/validation/students";
import {
  GENDER_LABELS,
  STUDENT_STATUS_LABELS,
  type StudentCreate,
  type StudentRead,
  type StudentUpdate,
} from "@/lib/api/types";

const EMPTY: StudentFormValues = {
  first_name: "",
  last_name: "",
  date_of_birth: "",
  gender: "",
  address: "",
  guardian_name: "",
  guardian_phone: "",
  guardian_email: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
  admission_number: "",
  section_id: "",
  status: "active",
  enrolled_on: "",
};

/** Radix Select cannot hold "" as a value, so unassigned uses a sentinel. */
const NO_SECTION = "__none__";

function toFormValues(student: StudentRead): StudentFormValues {
  return {
    first_name: student.first_name,
    last_name: student.last_name,
    date_of_birth: student.date_of_birth ?? "",
    gender: student.gender ?? "",
    address: student.address ?? "",
    guardian_name: student.guardian_name ?? "",
    guardian_phone: student.guardian_phone ?? "",
    guardian_email: student.guardian_email ?? "",
    emergency_contact_name: student.emergency_contact_name ?? "",
    emergency_contact_phone: student.emergency_contact_phone ?? "",
    admission_number: student.admission_number,
    section_id: student.section_id ?? "",
    status: student.status,
    enrolled_on: student.enrolled_on ?? "",
  };
}

/**
 * Create/edit student.
 *
 * One dialog serves both modes: `student` present means edit (PATCH), absent
 * means enroll (POST). Keeping them together guarantees the two forms never
 * drift apart field-by-field.
 */
export function StudentFormDialog({
  open,
  onOpenChange,
  student,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  student?: StudentRead | null;
}) {
  const isEdit = Boolean(student);
  const [formError, setFormError] = React.useState<string | null>(null);

  const createStudent = useCreateStudent();
  const updateStudent = useUpdateStudent();
  const { data: classes } = useClassSummary();

  const form = useForm<StudentFormValues>({
    resolver: zodResolver(studentFormSchema),
    defaultValues: EMPTY,
  });

  // Re-seed whenever the dialog opens, so a previous edit never leaks into the
  // next one.
  React.useEffect(() => {
    if (!open) return;
    setFormError(null);
    form.reset(student ? toFormValues(student) : EMPTY);
  }, [open, student, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    const payload = toNullable(values);

    try {
      if (isEdit && student) {
        await updateStudent.mutateAsync({ id: student.id, body: payload as StudentUpdate });
      } else {
        await createStudent.mutateAsync(payload as StudentCreate);
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError) {
        const fields = error.fieldErrors();
        let matched = false;
        for (const [name, message] of Object.entries(fields)) {
          if (name in values) {
            form.setError(name as keyof StudentFormValues, { message });
            matched = true;
          }
        }
        // A duplicate admission number comes back as a 409, not a field error.
        if (error.status === 409) {
          form.setError("admission_number", { message: error.message });
          return;
        }
        if (matched) return;
      }
      setFormError(errorMessage(error));
    }
  });

  const saving = createStudent.isPending || updateStudent.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit student" : "Enroll student"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update this student's record."
              : "Add a student to your school's directory."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          <FormError message={formError} />

          <section className="grid gap-4 sm:grid-cols-2">
            <Field
              label="First name"
              htmlFor="first_name"
              error={form.formState.errors.first_name}
              required
            >
              <Input autoFocus {...form.register("first_name")} />
            </Field>

            <Field
              label="Last name"
              htmlFor="last_name"
              error={form.formState.errors.last_name}
              required
            >
              <Input {...form.register("last_name")} />
            </Field>

            <Field
              label="Admission number"
              htmlFor="admission_number"
              error={form.formState.errors.admission_number}
              hint="Must be unique within your school."
              required
            >
              <Input {...form.register("admission_number")} />
            </Field>

            <Field
              label="Date of birth"
              htmlFor="date_of_birth"
              error={form.formState.errors.date_of_birth}
            >
              <Input type="date" {...form.register("date_of_birth")} />
            </Field>

            <Field label="Gender" htmlFor="gender" error={form.formState.errors.gender}>
              <Controller
                control={form.control}
                name="gender"
                render={({ field }) => (
                  <Select
                    value={field.value || NO_SECTION}
                    onValueChange={(value) => field.onChange(value === NO_SECTION ? "" : value)}
                  >
                    <SelectTrigger id="gender">
                      <SelectValue placeholder="Not specified" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_SECTION}>Not specified</SelectItem>
                      {Object.entries(GENDER_LABELS).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>

            <Field label="Status" htmlFor="status" error={form.formState.errors.status} required>
              <Controller
                control={form.control}
                name="status"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="status">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(STUDENT_STATUS_LABELS).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>

            <Field label="Section" htmlFor="section_id" error={form.formState.errors.section_id}>
              <Controller
                control={form.control}
                name="section_id"
                render={({ field }) => (
                  <Select
                    value={field.value || NO_SECTION}
                    onValueChange={(value) => field.onChange(value === NO_SECTION ? "" : value)}
                  >
                    <SelectTrigger id="section_id">
                      <SelectValue placeholder="Unassigned" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NO_SECTION}>Unassigned</SelectItem>
                      {(classes ?? []).flatMap((cls) =>
                        cls.sections.map((section) => (
                          <SelectItem key={section.id} value={section.id}>
                            {cls.name} — {section.name}
                          </SelectItem>
                        )),
                      )}
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>

            <Field
              label="Enrolled on"
              htmlFor="enrolled_on"
              error={form.formState.errors.enrolled_on}
            >
              <Input type="date" {...form.register("enrolled_on")} />
            </Field>
          </section>

          <Separator />

          <section className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Guardian name"
              htmlFor="guardian_name"
              error={form.formState.errors.guardian_name}
            >
              <Input {...form.register("guardian_name")} />
            </Field>

            <Field
              label="Guardian phone"
              htmlFor="guardian_phone"
              error={form.formState.errors.guardian_phone}
            >
              <Input type="tel" {...form.register("guardian_phone")} />
            </Field>

            <Field
              label="Guardian email"
              htmlFor="guardian_email"
              error={form.formState.errors.guardian_email}
              className="sm:col-span-2"
            >
              <Input type="email" {...form.register("guardian_email")} />
            </Field>

            <Field
              label="Emergency contact"
              htmlFor="emergency_contact_name"
              error={form.formState.errors.emergency_contact_name}
            >
              <Input {...form.register("emergency_contact_name")} />
            </Field>

            <Field
              label="Emergency phone"
              htmlFor="emergency_contact_phone"
              error={form.formState.errors.emergency_contact_phone}
            >
              <Input type="tel" {...form.register("emergency_contact_phone")} />
            </Field>

            <Field
              label="Address"
              htmlFor="address"
              error={form.formState.errors.address}
              className="sm:col-span-2"
            >
              <Textarea rows={2} {...form.register("address")} />
            </Field>
          </section>

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
              {isEdit ? "Save changes" : "Enroll student"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
