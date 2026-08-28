"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Archive, Building2, Pencil, Plus } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Can } from "@/components/auth/can";
import { ConfirmDialog } from "@/components/confirm-dialog";
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
  canSelectCampus = false,
}: {
  schools: SchoolRead[];
  schoolSeats: UsageItem | null;
  /**
   * Whether opening a branch should also make it the active one.
   *
   * True for an org-level user, who moves between campuses. A school-scoped member
   * is permanently inside their own and has nothing to select.
   */
  canSelectCampus?: boolean;
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [editing, setEditing] = useState<SchoolRead | null>(null);
  const [editName, setEditName] = useState("");
  const [editCity, setEditCity] = useState("");
  const [archiving, setArchiving] = useState<SchoolRead | null>(null);
  const [busy, setBusy] = useState(false);

  const exhausted = schoolSeats?.is_exhausted ?? false;

  const form = useForm<SchoolCreateValues>({
    resolver: zodResolver(schoolCreateSchema),
    defaultValues: { name: "", code: "", city: "" },
  });

  /**
   * Open a branch: make it the active campus, then show it.
   *
   * The selection is the point. The sidebar's campus modules — Members, Roles,
   * Invitations, Students, Classes, Audit — belong to whichever branch is open, so
   * clicking a card has to move them, not just navigate. Without this the reader
   * lands on Burewala's page with the sidebar still wired to Gaggoo Mandi.
   *
   * `preventDefault` on a real anchor rather than a button: the href keeps the card
   * a genuine link (focusable, says where it goes, opens in a new tab on
   * middle-click), and only ordinary activation takes the selecting path.
   */
  async function openBranch(event: React.MouseEvent, school: SchoolRead) {
    // Modified clicks are the browser's to handle: ctrl/cmd/middle-click opens the
    // card in a new tab, and hijacking that would be worse than not selecting.
    if (!canSelectCampus || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
      return;
    }
    event.preventDefault();
    setBusy(true);
    try {
      await schoolsApi.setActive(school.id);
    } catch {
      // Selecting is a convenience; the page itself works regardless. Navigate
      // anyway rather than swallowing the click and leaving the reader on a list
      // that appears not to respond.
    } finally {
      setBusy(false);
      router.refresh();
      router.push(`/schools/${school.id}` as Route);
    }
  }

  async function create(values: SchoolCreateValues) {
    setFormError(null);
    try {
      const result = await schoolsApi.create({
        name: values.name,
        code: values.code.toUpperCase(),
        city: values.city || undefined,
      });
      toast({
        title: `${result.name} created.`,
        description: t.schools.rolesCreated,
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

  function beginEdit(school: SchoolRead) {
    setEditing(school);
    setEditName(school.name);
    setEditCity(school.city ?? "");
    setFormError(null);
  }

  async function saveEdit() {
    if (!editing || !editName.trim()) return;
    setBusy(true);
    setFormError(null);
    try {
      await schoolsApi.update(editing.id, {
        name: editName.trim(),
        city: editCity.trim() || null,
      });
      toast({ title: `${editName.trim()} updated.` });
      setEditing(null);
      router.refresh();
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function archiveSchool() {
    if (!archiving) return;
    setBusy(true);
    try {
      await schoolsApi.archive(archiving.id);
      toast({ title: `${archiving.name} archived.` });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not archive this school",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(false);
      setArchiving(null);
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
            // The whole card opens the campus, but Edit and Archive still have to
            // work. So the LINK is the real anchor around the title — keyboard
            // focus lands on something that says where it goes — and it stretches
            // over the card with a pseudo-element. The action row then sits above
            // that overlay on its own stacking context. Wrapping the entire card in
            // an <a> instead would nest buttons inside a link, which is invalid and
            // leaves the buttons unreachable by keyboard.
            <li
              key={school.id}
              className="relative rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/60 focus-within:border-primary/60"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate font-medium">
                    <Link
                      href={`/schools/${school.id}`}
                      onClick={(event) => openBranch(event, school)}
                      aria-disabled={busy || undefined}
                      className="outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring"
                    >
                      {school.name}
                    </Link>
                  </h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {school.code}
                    {school.city ? ` · ${school.city}` : ""}
                  </p>
                </div>
                <Badge variant={school.status === "active" ? "success" : "neutral"}>
                  {label(SCHOOL_STATUS_LABELS, school.status)}
                </Badge>
              </div>
              <div className="relative z-10 mt-4 flex flex-wrap gap-2 border-t border-border pt-3">
                <Can permission={PERMISSIONS.schoolUpdate}>
                  <Button variant="outline" size="sm" onClick={() => beginEdit(school)}>
                    <Pencil className="size-4" aria-hidden />
                    Edit
                  </Button>
                </Can>
                {school.status === "active" ? (
                  <Can permission={PERMISSIONS.schoolArchive}>
                    <Button variant="ghost" size="sm" onClick={() => setArchiving(school)}>
                      <Archive className="size-4" aria-hidden />
                      Archive
                    </Button>
                  </Can>
                ) : null}
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

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit school</DialogTitle>
            <DialogDescription>The school code remains stable for links and imports.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <label htmlFor="edit-school-name" className="text-sm font-medium">Name</label>
              <Input
                id="edit-school-name"
                value={editName}
                onChange={(event) => setEditName(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <label htmlFor="edit-school-city" className="text-sm font-medium">City</label>
              <Input
                id="edit-school-city"
                value={editCity}
                onChange={(event) => setEditCity(event.target.value)}
              />
            </div>
            {formError ? <p role="alert" className="text-sm text-destructive">{formError}</p> : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
            <Button onClick={saveEdit} loading={busy} disabled={!editName.trim()}>Save changes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={archiving !== null}
        onOpenChange={(open) => !open && setArchiving(null)}
        title={`Archive ${archiving?.name}?`}
        description="The school and its records are retained, but it no longer accepts new work and its plan seat is released."
        confirmLabel="Archive school"
        variant="destructive"
        loading={busy}
        onConfirm={archiveSchool}
      />
    </div>
  );
}
