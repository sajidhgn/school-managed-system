"use client";

import { AlertTriangle, Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Can } from "@/components/auth/can";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";
import { roles as rolesApi } from "@/lib/api/resources";
import { PERMISSIONS, type PermissionCategory, type RoleRead } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * The permission checkboxes for one role.
 *
 * =============================================================================
 * THE ACTOR'S OWN GRANT IS THE CEILING — spec §5.3 rule 1
 * =============================================================================
 *   A principal may only grant permissions they themselves hold. The server enforces
 *   it (403 PERMISSION_ESCALATION); this matrix disables the boxes and says why, so
 *   the boundary is visible rather than discovered by submitting a form.
 *
 *   Without that, a principal building a "Head of Year" role would tick fifteen
 *   boxes, submit, and get one opaque rejection naming a permission they may not
 *   even remember selecting.
 *
 * =============================================================================
 * SAVING REPLACES THE WHOLE SET, AND BUMPS `permissions_version`
 * =============================================================================
 *   The endpoint is a PUT taking the complete list, not a series of add/remove
 *   calls. That makes the request self-describing — what you send is what the role
 *   ends up with — and avoids the failure mode where a client forgets the remove
 *   half and revoked permissions silently persist.
 *
 *   Every save increments the role's `permissions_version`, which invalidates every
 *   existing token for it. Anyone holding this role picks up the change on their
 *   NEXT request, not when their token expires. The copy says so, because an
 *   administrator revoking access needs to know it has actually taken effect.
 */
export function PermissionMatrix({
  schoolId,
  role,
  catalog,
  actorPermissions,
}: {
  schoolId: string;
  role: RoleRead;
  catalog: PermissionCategory[];
  actorPermissions: string[];
}) {
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const [saving, setSaving] = useState(false);

  const held = useMemo(() => new Set(actorPermissions), [actorPermissions]);

  // The role LIST does not carry permission codes, so the detail endpoint is
  // fetched once per selected role.
  //
  // `selected` is nullable so "not loaded yet" and "loaded, and empty" stay
  // distinguishable — an empty set is a legitimate answer for a freshly created
  // role, and rendering it as a spinner forever would be a real bug.
  //
  // The `cancelled` flag guards the classic race: click role A, click role B before
  // A's response lands, and without it A's slower response would overwrite B's.
  useEffect(() => {
    let cancelled = false;
    setSelected(null);

    rolesApi
      .get(schoolId, role.id)
      .then((detail) => {
        if (!cancelled) setSelected(new Set(detail.permissions));
      })
      .catch(() => {
        if (!cancelled) setSelected(new Set());
      });

    return () => {
      cancelled = true;
    };
  }, [schoolId, role.id]);

  if (selected === null) {
    return <p className="text-sm text-muted-foreground">Loading permissions…</p>;
  }

  function toggle(code: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  async function save() {
    if (!selected) return;
    setSaving(true);
    try {
      await rolesApi.setPermissions(schoolId, role.id, [...selected]);
      toast({
        title: `${role.name} updated.`,
        description: "Anyone with this role sees the change on their next request.",
      });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Could not save",
        description: error instanceof ApiError ? error.message : "Please try again.",
      });
    } finally {
      setSaving(false);
    }
  }

  // Org-scoped permissions cannot be attached to a school role at all — the server
  // returns 422. They are filtered out entirely rather than shown disabled: an
  // unreachable checkbox in a 60-row matrix is clutter, not information.
  const categories = catalog
    .map((category) => ({
      ...category,
      permissions: category.permissions.filter((p) => p.min_scope !== "org"),
    }))
    .filter((category) => category.permissions.length > 0);

  return (
    <div className="grid gap-6">
      {categories.map((category) => (
        <fieldset key={category.category}>
          <legend className="mb-2 text-sm font-medium">{category.category}</legend>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {category.permissions.map((permission) => {
              const grantable = held.has(permission.code);
              const checked = selected.has(permission.code);

              return (
                <label
                  key={permission.code}
                  className={cn(
                    "flex cursor-pointer items-start gap-2.5 rounded-md p-2 text-sm transition-colors",
                    grantable ? "hover:bg-accent/50" : "cursor-not-allowed opacity-55",
                  )}
                  title={
                    grantable
                      ? permission.description
                      : "You cannot grant a permission you do not hold yourself."
                  }
                >
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 shrink-0 accent-primary"
                    checked={checked}
                    disabled={!grantable || saving}
                    onChange={() => toggle(permission.code)}
                  />
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5 font-medium">
                      {permission.description}
                      {permission.is_dangerous ? (
                        <AlertTriangle
                          className="size-3.5 text-warning"
                          aria-label="Destructive or high-impact"
                        />
                      ) : null}
                    </span>
                    <code className="text-xs text-muted-foreground">{permission.code}</code>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
      ))}

      <Can permission={PERMISSIONS.roleAssignPermissions}>
        <div className="flex items-center gap-3 border-t border-border pt-4">
          <Button onClick={save} disabled={saving}>
            <Save className="size-4" aria-hidden />
            {saving ? "Saving…" : "Save permissions"}
          </Button>
          <p className="text-xs text-muted-foreground">
            {selected.size} permission{selected.size === 1 ? "" : "s"} selected
          </p>
        </div>
      </Can>
    </div>
  );
}
