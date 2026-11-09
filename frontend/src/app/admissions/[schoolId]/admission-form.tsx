"use client";

import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { CheckCircle2, Copy, Lock, School, SearchX } from "lucide-react";

import { Field, FormError } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/misc";
import { admissionsApi } from "@/lib/api/resources/students";
import { ApiError, errorMessage } from "@/lib/api/errors";
import {
  admissionFormSchema,
  toNullable,
  type AdmissionFormValues,
} from "@/lib/validation/students";
import type { AdmissionResponse, StudentAdmissionRequest } from "@/lib/api/types";
import { localizeFieldError, studentsMessages } from "@/lib/i18n/modules/students";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { useLabels } from "@/lib/i18n/use-labels";

const EMPTY: AdmissionFormValues = {
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
};

/** Radix Select cannot hold "" as a value, so "prefer not to say" needs a sentinel. */
const NONE = "__none__";

/** Parents fill this in on a phone; 44px targets, not 36px. */
const TOUCH = "h-11 text-base";

function Shell({ children }: { children: React.ReactNode }) {
  const m = useCatalog(studentsMessages).apply;
  return (
    <div className="min-h-svh bg-muted/40">
      <div className="mx-auto w-full max-w-xl px-4 py-10 sm:px-6 sm:py-14">
        <div className="mb-8 flex items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <School className="size-4.5" />
          </div>
          <span className="text-sm font-semibold">{m.brand}</span>
        </div>
        <main id="main">{children}</main>
      </div>
    </div>
  );
}

/**
 * Public admissions application.
 *
 * The whole page is one column and standalone — it renders outside the
 * dashboard shell because the person filling it in has no account and no
 * navigation to speak of.
 */
export function AdmissionForm({ schoolId }: { schoolId: string }) {
  const { apply: m, validation } = useCatalog(studentsMessages);
  const L = useLabels();
  const [submitted, setSubmitted] = React.useState<AdmissionResponse | null>(null);
  const [unknownSchool, setUnknownSchool] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

  const form = useForm<AdmissionFormValues>({
    resolver: zodResolver(admissionFormSchema),
    defaultValues: EMPTY,
  });
  const errors = form.formState.errors;
  const fieldError = (name: keyof AdmissionFormValues) =>
    localizeFieldError(errors[name], validation);

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      const response = await admissionsApi.submit({
        ...toNullable(values),
        school_id: schoolId,
      } as StudentAdmissionRequest);
      setSubmitted(response);
    } catch (error) {
      if (error instanceof ApiError) {
        const fields = error.fieldErrors();

        // A bad link is not something the family can fix by editing the form,
        // so it gets its own screen instead of a validation message.
        if (error.isNotFound || "school_id" in fields) {
          setUnknownSchool(true);
          return;
        }

        let matched = false;
        for (const [name, message] of Object.entries(fields)) {
          if (name in values) {
            form.setError(name as keyof AdmissionFormValues, { message });
            matched = true;
          }
        }
        if (matched) return;
      }
      setFormError(errorMessage(error));
    }
  });

  async function copyReference(reference: string) {
    try {
      await navigator.clipboard.writeText(reference);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied; the number is on screen either way.
    }
  }

  if (unknownSchool) {
    return (
      <Shell>
        <div className="rounded-xl border border-border bg-card p-8 text-center shadow-sm">
          <div className="mx-auto mb-5 flex size-12 items-center justify-center rounded-full bg-muted">
            <SearchX className="size-5 text-muted-foreground" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">{m.unknownTitle}</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
            {m.unknownBody}
          </p>
        </div>
      </Shell>
    );
  }

  if (submitted) {
    return (
      <Shell>
        <div className="rounded-xl border border-border bg-card p-8 text-center shadow-sm">
          <div className="mx-auto mb-5 flex size-12 items-center justify-center rounded-full bg-success/12">
            <CheckCircle2 className="size-6 text-success" />
          </div>

          <h1 className="text-2xl font-semibold tracking-tight">{m.receivedTitle}</h1>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
            {submitted.detail}
          </p>

          {/* The reference number is the only thing on this page the family
              needs to keep, so it outranks everything else visually. */}
          <div className="mt-7 rounded-lg border border-border bg-muted/50 px-5 py-6">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {m.referenceLabel}
            </p>
            <p className="mt-2 select-all break-all font-mono text-3xl font-semibold tracking-tight">
              {submitted.admission_number}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => void copyReference(submitted.admission_number)}
            >
              <Copy />
              {copied ? m.copied : m.copyNumber}
            </Button>
          </div>

          <p className="mt-6 text-sm text-muted-foreground">{m.keepReference}</p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="rounded-xl border border-border bg-card p-6 shadow-sm sm:p-8">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{m.title}</h1>
          <p className="text-sm leading-relaxed text-muted-foreground">{m.intro}</p>
        </header>

        <Separator className="my-6" />

        <form onSubmit={onSubmit} className="space-y-6" noValidate>
          <FormError message={formError} />

          <section className="space-y-4">
            <h2 className="text-sm font-semibold">{m.studentDetails}</h2>

            <Field
              label={m.firstName}
              htmlFor="first_name"
              error={fieldError("first_name")}
              required
            >
              <Input
                className={TOUCH}
                autoComplete="given-name"
                autoFocus
                {...form.register("first_name")}
              />
            </Field>

            <Field
              label={m.lastName}
              htmlFor="last_name"
              error={fieldError("last_name")}
              required
            >
              <Input
                className={TOUCH}
                autoComplete="family-name"
                {...form.register("last_name")}
              />
            </Field>

            <Field
              label={m.dateOfBirth}
              htmlFor="date_of_birth"
              error={fieldError("date_of_birth")}
            >
              <Input type="date" className={TOUCH} {...form.register("date_of_birth")} />
            </Field>

            <Field label={m.gender} htmlFor="gender" error={fieldError("gender")}>
              <Controller
                control={form.control}
                name="gender"
                render={({ field }) => (
                  <Select
                    value={field.value || NONE}
                    onValueChange={(value) => field.onChange(value === NONE ? "" : value)}
                  >
                    <SelectTrigger id="gender" className={TOUCH}>
                      <SelectValue placeholder={m.preferNotToSay} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>{m.preferNotToSay}</SelectItem>
                      {Object.entries(L.gender).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>

            <Field label={m.homeAddress} htmlFor="address" error={fieldError("address")}>
              <Textarea rows={3} className="text-base" {...form.register("address")} />
            </Field>
          </section>

          <Separator />

          <section className="space-y-4">
            <h2 className="text-sm font-semibold">{m.parentSection}</h2>

            <Field
              label={m.fullName}
              htmlFor="guardian_name"
              error={fieldError("guardian_name")}
              required
            >
              <Input className={TOUCH} autoComplete="name" {...form.register("guardian_name")} />
            </Field>

            <Field
              label={m.phone}
              htmlFor="guardian_phone"
              error={fieldError("guardian_phone")}
              hint={m.phoneHint}
              required
            >
              <Input
                type="tel"
                inputMode="tel"
                className={TOUCH}
                autoComplete="tel"
                {...form.register("guardian_phone")}
              />
            </Field>

            <Field
              label={m.email}
              htmlFor="guardian_email"
              error={fieldError("guardian_email")}
              hint={m.optional}
            >
              <Input
                type="email"
                inputMode="email"
                className={TOUCH}
                autoComplete="email"
                {...form.register("guardian_email")}
              />
            </Field>
          </section>

          <Separator />

          <section className="space-y-4">
            <h2 className="text-sm font-semibold">{m.emergencySection}</h2>
            <p className="text-sm text-muted-foreground">{m.emergencyIntro}</p>

            <Field
              label={m.fullName}
              htmlFor="emergency_contact_name"
              error={fieldError("emergency_contact_name")}
            >
              <Input className={TOUCH} {...form.register("emergency_contact_name")} />
            </Field>

            <Field
              label={m.phone}
              htmlFor="emergency_contact_phone"
              error={fieldError("emergency_contact_phone")}
            >
              <Input
                type="tel"
                inputMode="tel"
                className={TOUCH}
                {...form.register("emergency_contact_phone")}
              />
            </Field>
          </section>

          <Button
            type="submit"
            className="h-12 w-full text-base"
            loading={form.formState.isSubmitting}
          >
            {m.submit}
          </Button>

          <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
            <Lock className="size-3" />
            {m.privacy}
          </p>
        </form>
      </div>
    </Shell>
  );
}
