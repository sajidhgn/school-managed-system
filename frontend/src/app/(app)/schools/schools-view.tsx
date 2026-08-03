"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Building2, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Can } from "@/components/auth/can";
import { EmptyState } from "@/components/data-states";
import { Field } from "@/components/form/field";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
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
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { ApiError } from "@/lib/api/errors";
import { schools as schoolsApi } from "@/lib/api/resources";
import {
  PERMISSIONS,
  SCHOOL_STATUS_LABELS,
  label,
  type SchoolRead,
  type UsageItem,
} from "@/lib/api/types";
import { schoolCreateSchema, type SchoolCreateValues } from "@/lib/validation/schools";

/**
 * School list and creation.
 *
 * Creating a school is entitlement-checked: the free plan allows one, and the server
 * answers a second attempt with 402 naming the limit and an upgrade URL. That
 * response is surfaced as a specific message rather than a generic failure, because
 * "you have used your plan's only school" is actionable and "could not create" is
 * not.
 *
 * The button is also disabled when the seat count is exhausted — the same
 * belt-and-braces as the members table: the server guarantees, the UI explains.
 */
export function SchoolsView({
  schools,
  schoolSeats,
}: {
  schools: SchoolRead[];
  schoolSeats: UsageItem | null;
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const exhausted = schoolSeats?.is_exhausted ?? false;

  const form = useForm<SchoolCreateValues>({
    resolver: zodResolver(schoolCreateSchema),
    defaultValues: { name: "", code: "", city: "" },
  });

  async function create(values: SchoolCreateValues) {
    setFormError(null);
    try {
      const result = await schoolsApi.create({
        name: values.name,
        code: values.code.toUpperCase(),
        city: values.city || undefined,
      });
      toast({
        title: `${result.school.name} created.`,
        description: result.principal_granted
          ? t.schools.createdPrincipal
          : t.schools.createdNoPrincipal,
      });
      form.reset();
      setCreating(false);
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "plan_limit_exceeded") {
          setFormError(`${error.message} Upgrade your plan to add more campuses.`);
          return;
        }
        if (error.code === "SCHOOL_CODE_TAKEN") {
          form.setError("code", { message: error.message });
          return;
        }
        setFormError(error.message);
        return;
      }
      setFormError("Please try again.");
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <PageHeader
        title={t.schools.title}
        description={t.schools.subtitle}
        actions={
          <Can permission={PERMISSIONS.schoolCreate}>
            <Button onClick={() => setCreating(true)} disabled={exhausted}>
              <Plus className="size-4" aria-hidden />
              {t.schools.newSchool}
            </Button>
          </Can>
        }
      />

      {exhausted ? (
        <p className="mb-6 rounded-lg bg-warning/15 p-4 text-sm">
          You are using all {schoolSeats?.allowed} schools on your plan. Upgrade to add another.
        </p>
      ) : null}

      {schools.length === 0 ? (
        <EmptyState
          icon={Building2}
          title={t.schools.emptyTitle}
          description={t.schools.emptyBody}
          action={
            <Can permission={PERMISSIONS.schoolCreate}>
              <Button onClick={() => setCreating(true)}>{t.onboarding.create}</Button>
            </Can>
          }
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {schools.map((school) => (
            <li
              key={school.id}
              className="rounded-xl border border-border bg-card p-5"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate font-medium">{school.name}</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {school.code}
                    {school.city ? ` · ${school.city}` : ""}
                  </p>
                </div>
                <Badge variant={school.status === "active" ? "success" : "neutral"}>
                  {label(SCHOOL_STATUS_LABELS, school.status)}
                </Badge>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.schools.newSchool}</DialogTitle>
            <DialogDescription>
              {t.schools.rolesCreated}
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={form.handleSubmit(create)} className="grid gap-4" noValidate>
            <Field label={t.onboarding.schoolName} htmlFor="name" error={form.formState.errors.name} required>
              <Input autoFocus {...form.register("name")} />
            </Field>
            <Field
              label={t.onboarding.schoolCode}
              htmlFor="code"
              error={form.formState.errors.code}
              hint={t.onboarding.schoolCodeHint}
              required
            >
              <Input className="uppercase" {...form.register("code")} />
            </Field>
            <Field label={t.onboarding.city} htmlFor="city" error={form.formState.errors.city}>
              <Input {...form.register("city")} />
            </Field>

            {formError ? (
              <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {formError}
              </p>
            ) : null}

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCreating(false)}>
                {t.common.cancel}
              </Button>
              <Button type="submit" disabled={form.formState.isSubmitting}>
                {t.onboarding.create}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
