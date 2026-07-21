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
import { Separator } from "@/components/ui/misc";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateSchool, useUpdateSchool } from "@/hooks/use-schools";
import { ApiError, errorMessage } from "@/lib/api/errors";
import { PLAN_LABELS, type SchoolCreate, type SchoolRead, type SchoolUpdate } from "@/lib/api/types";
import { schoolFormSchema, type SchoolFormValues } from "@/lib/validation/schools";
import { toNullable } from "@/lib/validation/students";

const EMPTY: SchoolFormValues = {
  name: "",
  email: "",
  phone: "",
  address: "",
  city: "",
  country: "",
  logo_url: "",
  plan: "trial",
  max_students: 100,
};

function toFormValues(school: SchoolRead): SchoolFormValues {
  return {
    name: school.name,
    email: school.email,
    phone: school.phone ?? "",
    address: school.address ?? "",
    city: school.city ?? "",
    country: school.country ?? "",
    logo_url: school.logo_url ?? "",
    plan: school.plan,
    max_students: school.max_students,
  };
}

/**
 * Onboard/edit school.
 *
 * One dialog serves both modes: `school` present means edit (PATCH), absent
 * means onboard (POST). The slug and status are omitted deliberately — the
 * backend derives the slug and status only moves through approve/suspend.
 */
export function SchoolFormDialog({
  open,
  onOpenChange,
  school,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  school?: SchoolRead | null;
}) {
  const isEdit = Boolean(school);
  const [formError, setFormError] = React.useState<string | null>(null);

  const createSchool = useCreateSchool();
  const updateSchool = useUpdateSchool();

  const form = useForm<SchoolFormValues>({
    resolver: zodResolver(schoolFormSchema),
    defaultValues: EMPTY,
  });

  // Re-seed on open so a previous edit never leaks into the next one.
  React.useEffect(() => {
    if (!open) return;
    setFormError(null);
    form.reset(school ? toFormValues(school) : EMPTY);
  }, [open, school, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    const payload = toNullable(values);

    try {
      if (isEdit && school) {
        await updateSchool.mutateAsync({ id: school.id, body: payload as SchoolUpdate });
      } else {
        await createSchool.mutateAsync(payload as SchoolCreate);
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError) {
        const fields = error.fieldErrors();
        let matched = false;
        for (const [name, message] of Object.entries(fields)) {
          if (name in values) {
            form.setError(name as keyof SchoolFormValues, { message });
            matched = true;
          }
        }
        // A duplicate name/slug comes back as a 409, not a field error.
        if (error.status === 409) {
          form.setError("name", { message: error.message });
          return;
        }
        if (matched) return;
      }
      setFormError(errorMessage(error));
    }
  });

  const saving = createSchool.isPending || updateSchool.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit school" : "Onboard school"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update this tenant's details and subscription."
              : "Provision a new tenant on the platform."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-5" noValidate>
          <FormError message={formError} />

          <section className="grid gap-4 sm:grid-cols-2">
            <Field
              label="School name"
              htmlFor="name"
              error={form.formState.errors.name}
              className="sm:col-span-2"
              required
            >
              <Input autoFocus {...form.register("name")} />
            </Field>

            <Field
              label="Contact email"
              htmlFor="email"
              error={form.formState.errors.email}
              hint="The school's official address, not a login."
              required
            >
              <Input type="email" {...form.register("email")} />
            </Field>

            <Field label="Phone" htmlFor="phone" error={form.formState.errors.phone}>
              <Input type="tel" {...form.register("phone")} />
            </Field>

            <Field label="City" htmlFor="city" error={form.formState.errors.city}>
              <Input {...form.register("city")} />
            </Field>

            <Field label="Country" htmlFor="country" error={form.formState.errors.country}>
              <Input {...form.register("country")} />
            </Field>

            <Field
              label="Address"
              htmlFor="address"
              error={form.formState.errors.address}
              className="sm:col-span-2"
            >
              <Textarea rows={2} {...form.register("address")} />
            </Field>

            <Field
              label="Logo URL"
              htmlFor="logo_url"
              error={form.formState.errors.logo_url}
              hint="Used on ID cards, certificates and vouchers."
              className="sm:col-span-2"
            >
              <Input type="url" {...form.register("logo_url")} />
            </Field>
          </section>

          <Separator />

          <section className="grid gap-4 sm:grid-cols-2">
            <Field label="Plan" htmlFor="plan" error={form.formState.errors.plan} required>
              <Controller
                control={form.control}
                name="plan"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="plan">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(PLAN_LABELS).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>

            <Field
              label="Student cap"
              htmlFor="max_students"
              error={form.formState.errors.max_students}
              hint="Maximum students this school may enrol."
              required
            >
              <Input
                type="number"
                min={1}
                {...form.register("max_students", { valueAsNumber: true })}
              />
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
              {isEdit ? "Save changes" : "Onboard school"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
