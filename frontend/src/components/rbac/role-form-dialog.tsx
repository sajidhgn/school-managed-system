"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";

import { Field } from "@/components/form/field";
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
import { roles as rolesApi } from "@/lib/api/resources";
import type { PermissionCategory } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { adminMessages } from "@/lib/i18n/modules/admin";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { createRoleSchema, type RoleCreateValues } from "@/lib/validation/rbac";
import { cn } from "@/lib/utils";

/**
 * Create a custom role.
 *
 * Counted against the plan's `max_custom_roles`, so this is one of the places a 402
 * surfaces. That response is passed through verbatim — it names the limit and the
 * upgrade path, which is more useful than "could not create role".
 *
 * As in the matrix, permissions the actor does not hold are disabled rather than
 * hidden: seeing that `billing:manage` exists but is not yours to give explains the
 * boundary better than its absence would.
 */
export function RoleFormDialog({
  schoolId,
  catalog,
  actorPermissions,
  open,
  onOpenChange,
}: {
  schoolId: string;
  catalog: PermissionCategory[];
  actorPermissions: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslations();
  const { roles: m, validation } = useCatalog(adminMessages);
  const schema = useMemo(() => createRoleSchema(validation), [validation]);
  const router = useRouter();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [formError, setFormError] = useState<string | null>(null);

  const held = new Set(actorPermissions);

  const form = useForm<RoleCreateValues>({
    resolver: zodResolver(schema),
    defaultValues: { code: "", name: "", description: "", permissions: [] },
  });

  async function onSubmit(values: RoleCreateValues) {
    setFormError(null);
    try {
      await rolesApi.create(schoolId, {
        code: values.code,
        name: values.name,
        description: values.description || undefined,
        permissions: [...picked],
      });
      toast({ title: fill(m.created, { name: values.name }) });
      form.reset();
      setPicked(new Set());
      onOpenChange(false);
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "ROLE_CODE_TAKEN") {
          form.setError("code", { message: error.message });
          return;
        }
        setFormError(error.message);
        return;
      }
      setFormError(t.common.tryAgain);
    }
  }

  const schoolScoped = catalog
    .map((c) => ({ ...c, permissions: c.permissions.filter((p) => p.min_scope !== "org") }))
    .filter((c) => c.permissions.length > 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85svh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t.roles.newRole}</DialogTitle>
          <DialogDescription>{t.roles.onlyOwnPermissions}</DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t.roles.displayName} htmlFor="name" error={form.formState.errors.name} required>
              <Input placeholder={m.namePlaceholder} autoFocus {...form.register("name")} />
            </Field>
            <Field
              label={t.roles.code}
              htmlFor="code"
              error={form.formState.errors.code}
              hint={t.roles.codeHint}
              required
            >
              <Input placeholder="head_of_year" {...form.register("code")} />
            </Field>
          </div>

          <Field label={t.roles.description} htmlFor="description" error={form.formState.errors.description}>
            <Input placeholder={t.roles.descriptionPlaceholder} {...form.register("description")} />
          </Field>

          <div>
            <p className="mb-2 text-sm font-medium">{t.roles.permissions}</p>
            <div className="max-h-64 overflow-y-auto rounded-lg border border-border p-3">
              {schoolScoped.map((category) => (
                <fieldset key={category.category} className="mb-3 last:mb-0">
                  <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    {category.category}
                  </legend>
                  <div className="grid gap-1 sm:grid-cols-2">
                    {category.permissions.map((permission) => {
                      const grantable = held.has(permission.code);
                      return (
                        <label
                          key={permission.code}
                          className={cn(
                            "flex items-start gap-2 rounded p-1 text-sm",
                            grantable ? "cursor-pointer hover:bg-accent/50" : "opacity-55",
                          )}
                          title={
                            grantable
                              ? permission.description
                              : t.roles.cannotGrant
                          }
                        >
                          <input
                            type="checkbox"
                            className="mt-0.5 size-4 shrink-0 accent-primary"
                            disabled={!grantable}
                            checked={picked.has(permission.code)}
                            onChange={() =>
                              setPicked((current) => {
                                const next = new Set(current);
                                if (next.has(permission.code)) next.delete(permission.code);
                                else next.add(permission.code);
                                return next;
                              })
                            }
                          />
                          <span className="min-w-0">{permission.description}</span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
              ))}
            </div>
          </div>

          {formError ? (
            <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {formError}
            </p>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t.common.cancel}
            </Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {m.createRole}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
