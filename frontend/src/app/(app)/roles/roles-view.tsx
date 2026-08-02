"use client";

import { Lock, Plus, Shield, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Can } from "@/components/auth/can";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { PermissionMatrix } from "@/components/rbac/permission-matrix";
import { RoleFormDialog } from "@/components/rbac/role-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
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
 *   2. Locked roles                   -> owner/principal show a padlock and no
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
  const [selectedId, setSelectedId] = useState<string | null>(
    roles.find((r) => r.school_id === schoolId)?.id ?? roles[0]?.id ?? null,
  );
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<RoleRead | null>(null);
  const [busy, setBusy] = useState(false);

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

  return (
    <div className="mx-auto w-full max-w-6xl">
      <PageHeader
        title="Roles"
        description="What each kind of staff member can do in this school."
        actions={
          <Can permission={[PERMISSIONS.roleCreate, PERMISSIONS.roleAssignPermissions]}>
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" aria-hidden />
              New role
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
                  {selected.is_system ? <Badge variant="neutral">System</Badge> : null}
                  {isOrgLevel ? <Badge variant="outline">Organization</Badge> : null}
                </h2>
                {selected.description ? (
                  <p className="mt-1 text-sm text-muted-foreground">{selected.description}</p>
                ) : null}
              </div>

              {selected.is_editable && !selected.is_system ? (
                <Can permission={PERMISSIONS.roleDelete}>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => setDeleting(selected)}
                  >
                    <Trash2 className="size-4" aria-hidden />
                    Delete
                  </Button>
                </Can>
              ) : null}
            </header>

            {!selected.is_editable ? (
              <p className="flex items-start gap-2 rounded-lg bg-muted/60 p-4 text-sm text-muted-foreground">
                <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span className="text-pretty">
                  {/* Spec §5.3 rule 2, explained rather than merely enforced. */}
                  This role is managed by the platform and cannot be edited — including by
                  someone who holds it. That is what stops a principal from widening their own
                  access or the owner&apos;s.
                </span>
              </p>
            ) : isOrgLevel ? (
              <p className="rounded-lg bg-muted/60 p-4 text-sm text-muted-foreground text-pretty">
                This is an organization-level role. Edit it from the organization settings, not
                from a single school.
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
            Select a role to see what it grants.
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
        title={`Delete ${deleting?.name}?`}
        description="Anyone still holding this role must be reassigned first — the server will tell you how many if so."
        confirmLabel="Delete role"
        variant="destructive"
        loading={busy}
        onConfirm={() => deleting && remove(deleting)}
      />
    </div>
  );
}
