"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { useTranslations } from "@/components/providers/i18n-provider";
import { Field } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import { authRequest } from "@/lib/api/client";
import { schools } from "@/lib/api/resources";
import { schoolCreateSchema, type SchoolCreateValues } from "@/lib/validation/schools";

/**
 * Create the organization's first school.
 *
 * Creating a school grants the caller nothing: they are the org-level principal, and
 * that membership already covers every campus including this one. What DOES change is
 * that they now have a campus to look at, so it is selected for them — otherwise the
 * next school-scoped page would bounce them straight to a picker holding one option.
 *
 * `router.refresh()` is not optional either: the shell renders the campus list, and
 * without it the new school would be missing from the switcher until a hard reload.
 */
export function OnboardingForm() {
  const { t } = useTranslations();
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<SchoolCreateValues>({
    resolver: zodResolver(schoolCreateSchema),
    defaultValues: { name: "", code: "", city: "" },
  });

  async function onSubmit(values: SchoolCreateValues) {
    setFormError(null);
    try {
      const created = await schools.create({
        name: values.name,
        code: values.code.toUpperCase(),
        city: values.city || undefined,
      });
      await authRequest("/school", { school_id: created.id });
      // Push before refresh so the shared app layout (sidebar) re-renders for the
      // newly created school; a refresh issued before the push is superseded by it.
      router.push("/dashboard");
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "SCHOOL_CODE_TAKEN") {
          form.setError("code", { message: error.message });
          return;
        }
        setFormError(error.message);
        return;
      }
      setFormError(t.errors.generic);
    }
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <Field
        label={t.onboarding.schoolName}
        htmlFor="name"
        error={form.formState.errors.name}
        required
      >
        <Input autoFocus {...form.register("name")} />
      </Field>

      <Field
        label={t.onboarding.schoolCode}
        htmlFor="code"
        error={form.formState.errors.code}
        hint={t.onboarding.schoolCodeHint}
        required
      >
        <Input
          className="uppercase"
          // Stored uppercase by the server; showing it uppercase as they type avoids
          // the small jolt of the value changing after save.
          {...form.register("code")}
        />
      </Field>

      <Field label={t.onboarding.city} htmlFor="city" error={form.formState.errors.city}>
        <Input {...form.register("city")} />
      </Field>

      {formError ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {formError}
        </p>
      ) : null}

      <Button type="submit" disabled={form.formState.isSubmitting}>
        {form.formState.isSubmitting ? t.common.loading : t.onboarding.create}
      </Button>
    </form>
  );
}
