"use client";

import { Lock, Pencil, Plus, Shield, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Can } from "@/components/auth/can";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { PermissionMatrix } from "@/components/rbac/permission-matrix";
import { RoleFormDialog } from "@/components/rbac/role-form-dialog";
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
import { roles as rolesApi } from "@/lib/api/resources";
import { PERMISSIONS, type PermissionCategory, type RoleRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Role list + permission matrix editor.
 *
 * =============================================================================
 * THE THREE SERVER-SIDE GUARDS, MADE VISIBLE
 * =============================================================================
 *   Spec §5.3 calls the escalation guards "the part that gets built wrong". They
 *   are enforced by the server; this screen's job is to make them legible, so a
 *   principal understands the shape of their authority instead of discovering it
 *   through a sequence of 403s.
 *
 *   1. Cannot grant beyond own grant  -> checkboxes for permissions the actor does
 *                                        not hold are disabled with a reason.
 *   2. Locked roles                   -> `principal` shows a padlock and no
 *                                        editable matrix.
 *   3. Scope                          -> org-level roles are listed but read-only,
 *                                        since this page acts on one school.
 */
export function RolesView({
  schoolId,
  roles,
  catalog,
  actorPermissions,
}: {
  schoolId: string;
  roles: RoleRead[];
  catalog: PermissionCategory[];
  actorPermissions: string[];
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [selectedId, setSelectedId] = useState<string | null>(
    roles.find((r) => r.school_id === schoolId)?.id ?? roles[0]?.id ?? null,
  );
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<RoleRead | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<RoleRead | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");

  const selected = roles.find((r) => r.id === selectedId) ?? null;
  const isOrgLevel = selected?.school_id === null;

  async function remove(role: RoleRead) {
    setBusy(true);
    try {
      await rolesApi.remove(schoolId, role.id);
      toast({ title: `${role.name} deleted.` });
      setSelectedId(null);
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not delete this role",
        description:
          error instanceof ApiError
            ? // The server returns the blocking member count on 409 ROLE_IN_USE,
              // which is far more actionable than "delete failed".
              error.message
            : "Please try again.",
      });
    } finally {
      setBusy(false);
      setDeleting(null);
    }
  }

  function beginEdit(role: RoleRead) {
    setEditing(role);
    setEditName(role.name);
    setEditDescription(role.description ?? "");
  }

  async function saveMetadata() {
    if (!editing || editName.trim().length < 2) return;
    setBusy(true);
    try {
      await rolesApi.update(schoolId, editing.id, {
        name: editName.trim(),
        description: editDescription.trim() || null,
      });
      toast({ title: `${editName.trim()} updated.` });
      setEditing(null);
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not update this role",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title={t.roles.title}
        description={t.roles.subtitle}
        actions={
          <Can permission={[PERMISSIONS.roleCreate, PERMISSIONS.roleAssignPermissions]}>
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden />
              {t.roles.newRole}
            </Button>
          </Can>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
        <nav className="grid h-fit gap-1 rounded-xl border border-border bg-card p-2">
          {roles.map((role) => {
            const active = role.id === selectedId;
            return (
              <button
                key={role.id}
                type="button"
                onClick={() => setSelectedId(role.id)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-start text-sm transition-colors",
                  active ? "bg-accent font-medium text-accent-foreground" : "hover:bg-accent/60",
                )}
              >
                <Shield className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{role.name}</span>
                {!role.is_editable ? (
                  <Lock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                ) : null}
              </button>
            );
          })}
        </nav>

        {selected ? (
          <section className="rounded-xl border border-border bg-card p-6">
            <header className="mb-5 flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="flex items-center gap-2 text-lg font-medium">
                  {selected.name}
                  {selected.is_system ? <Badge variant="neutral">{t.roles.systemBadge}</Badge> : null}
                  {isOrgLevel ? <Badge variant="outline">{t.roles.organizationBadge}</Badge> : null}
                </h2>
                {selected.description ? (
                  <p className="mt-1 text-sm text-muted-foreground">{selected.description}</p>
                ) : null}
              </div>

              {selected.is_editable && !selected.is_system ? (
                <div className="flex gap-1">
                  <Can permission={PERMISSIONS.roleUpdate}>
                    <Button variant="ghost" size="sm" disabled={busy} onClick={() => beginEdit(selected)}>
                      <Pencil className="size-4" aria-hidden />
                      Edit details
                    </Button>
                  </Can>
                  <Can permission={PERMISSIONS.roleDelete}>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() => setDeleting(selected)}
                    >
                      <Trash2 className="size-4" aria-hidden />
                      {t.common.delete}
                    </Button>
                  </Can>
                </div>
              ) : null}
            </header>

            {!selected.is_editable ? (
              <p className="flex items-start gap-2 rounded-lg bg-muted/60 p-4 text-sm text-muted-foreground">
                <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span className="text-pretty">
                  {/* Spec §5.3 rule 2, explained rather than merely enforced. */}
                  {t.roles.lockedExplain}
                </span>
              </p>
            ) : isOrgLevel ? (
              <p className="rounded-lg bg-muted/60 p-4 text-sm text-muted-foreground text-pretty">
                {t.roles.orgLevelExplain}
              </p>
            ) : (
              <PermissionMatrix
                schoolId={schoolId}
                role={selected}
                catalog={catalog}
                actorPermissions={actorPermissions}
              />
            )}
          </section>
        ) : (
          <section className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
            {t.roles.selectPrompt}
          </section>
        )}
      </div>

      <RoleFormDialog
        schoolId={schoolId}
        catalog={catalog}
        actorPermissions={actorPermissions}
        open={creating}
        onOpenChange={setCreating}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={deleting ? `${t.common.delete} ${deleting.name}?` : t.roles.deleteTitle}
        description={t.roles.deleteBody}
        confirmLabel="Delete role"
        variant="destructive"
        loading={busy}
        onConfirm={() => deleting && remove(deleting)}
      />

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit role details</DialogTitle>
            <DialogDescription>
              Renaming is cosmetic. Permissions remain in the separate matrix and are audited separately.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <label htmlFor="role-edit-name" className="text-sm font-medium">Display name</label>
              <Input id="role-edit-name" value={editName} onChange={(event) => setEditName(event.target.value)} />
            </div>
            <div className="grid gap-1.5">
              <label htmlFor="role-edit-description" className="text-sm font-medium">Description</label>
              <Input
                id="role-edit-description"
                value={editDescription}
                onChange={(event) => setEditDescription(event.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
            <Button onClick={saveMetadata} loading={busy} disabled={editName.trim().length < 2}>
              Save details
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
