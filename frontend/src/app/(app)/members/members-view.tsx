"use client";

import { MoreHorizontal, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Can } from "@/components/auth/can";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/data-states";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { ApiError } from "@/lib/api/errors";
import { members as membersApi } from "@/lib/api/resources";
import { MEMBER_STATUS_LABELS, PERMISSIONS, label, type MemberRead, type RoleRead, type SchoolRead } from "@/lib/api/types";

/**
 * The staff table: change role, suspend, remove.
 *
 * =============================================================================
 * THE SERVER REFUSES THINGS THIS TABLE ALSO REFUSES — BOTH ARE NEEDED
 * =============================================================================
 *   You cannot act on your OWN membership here, and the last principal cannot be
 *   removed. Both are enforced server-side (409 SELF_MODIFICATION, 409 LAST_OWNER),
 *   and both are also disabled in the UI.
 *
 *   The duplication is deliberate. The server check is the guarantee; the UI check
 *   is the explanation. An administrator who clicks "Remove" on themselves and gets
 *   a red toast has learned the rule the hard way — a disabled row with a reason
 *   teaches it before the mistake.
 */
export function MembersView({
  schoolId,
  initialMembers,
  roles,
  schools,
  canAssignBranches,
  currentMembershipId,
}: {
  schoolId: string;
  initialMembers: MemberRead[];
  roles: RoleRead[];
  schools: SchoolRead[];
  canAssignBranches: boolean;
  currentMembershipId: string | null;
}) {
  const { t } = useTranslations();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [removing, setRemoving] = useState<MemberRead | null>(null);
  const [assigning, setAssigning] = useState<MemberRead | null>(null);
  const [selectedBranches, setSelectedBranches] = useState<string[]>([]);

  // Only roles for THIS school are assignable. The org-level `principal` role appears
  // in the list so its existence is visible, but assigning it here would be a scope
  // violation the server rejects — it is transferred, never granted.
  const assignableRoles = roles.filter((r) => r.school_id === schoolId);

  async function act(fn: () => Promise<unknown>, successMessage: string, id: string) {
    setBusy(id);
    try {
      await fn();
      toast({ title: successMessage });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: t.common.somethingWrong,
        description: error instanceof ApiError ? error.message : t.common.tryAgain,
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl">
      <PageHeader
        title={t.members.title}
        description={t.members.subtitle}
        actions={
          <Can permission={PERMISSIONS.memberInvite}>
            <Button asChild>
              <Link href="/invitations">
                <UserPlus className="size-4" aria-hidden />
                {t.members.inviteStaff}
              </Link>
            </Button>
          </Can>
        }
      />

      {initialMembers.length === 0 ? (
        <EmptyState
          title={t.members.emptyTitle}
          description={t.members.emptyBody}
          action={
            <Can permission={PERMISSIONS.memberInvite}>
              <Button asChild>
                <Link href="/invitations">{t.members.inviteStaff}</Link>
              </Button>
            </Can>
          }
        />
      ) : (
        <div className="rounded-xl border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.common.name}</TableHead>
                <TableHead>{t.common.role}</TableHead>
                <TableHead>{t.common.status}</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {initialMembers.map((member) => {
                const isSelf = member.membership_id === currentMembershipId;
                // The org-level principal. Removing the last one would leave the
                // organization with nobody who can pay for it or appoint a successor.
                const isOwner = member.role_code === "principal";

                return (
                  <TableRow key={member.membership_id}>
                    <TableCell>
                      <div className="font-medium">{member.full_name}</div>
                      <div className="text-xs text-muted-foreground">{member.email}</div>
                    </TableCell>
                    <TableCell>{member.role_name}</TableCell>
                    <TableCell>
                      <Badge variant={member.status === "active" ? "success" : "destructive"}>
                        {label(MEMBER_STATUS_LABELS, member.status)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {isSelf ? (
                        <span className="text-xs text-muted-foreground">{t.common.you}</span>
                      ) : (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" disabled={busy !== null}>
                              <MoreHorizontal className="size-4" aria-hidden />
                              <span className="sr-only">Actions for {member.full_name}</span>
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-56">
                            <Can permission={PERMISSIONS.memberUpdate}>
                              {canAssignBranches ? (
                                <DropdownMenuItem
                                  onSelect={() => {
                                    setSelectedBranches([]);
                                    setAssigning(member);
                                  }}
                                >
                                  Assign school branches
                                </DropdownMenuItem>
                              ) : null}
                              {assignableRoles
                                .filter((role) => role.id !== member.role_id)
                                .map((role) => (
                                  <DropdownMenuItem
                                    key={role.id}
                                    onSelect={() =>
                                      act(
                                        () =>
                                          membersApi.update(schoolId, member.membership_id, {
                                            role_id: role.id,
                                          }),
                                        `${member.full_name} is now ${role.name}.`,
                                        member.membership_id,
                                      )
                                    }
                                  >
                                    {t.members.changeRoleTo} {role.name}
                                  </DropdownMenuItem>
                                ))}
                              <DropdownMenuSeparator />
                            </Can>

                            <Can permission={PERMISSIONS.memberSuspend}>
                              <DropdownMenuItem
                                onSelect={() =>
                                  act(
                                    () =>
                                      membersApi.update(schoolId, member.membership_id, {
                                        suspended: member.status === "active",
                                      }),
                                    member.status === "active"
                                      ? `${member.full_name} is suspended.`
                                      : `${member.full_name} is active again.`,
                                    member.membership_id,
                                  )
                                }
                              >
                                {member.status === "active"
                                  ? t.members.suspendAccess
                                  : t.members.reactivate}
                              </DropdownMenuItem>
                            </Can>

                            <Can permission={PERMISSIONS.memberRemove}>
                              <DropdownMenuItem
                                className="text-destructive focus:text-destructive"
                                // The server refuses to remove the last principal (409).
                                // Disabling it here explains the rule instead of
                                // teaching it through a failed action.
                                disabled={isOwner}
                                onSelect={() => setRemoving(member)}
                              >
                                {t.members.removeFromSchool}
                              </DropdownMenuItem>
                            </Can>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.full_name}?`}
        description={t.members.removeBody}
        confirmLabel="Remove"
        variant="destructive"
        onConfirm={async () => {
          if (!removing) return;
          await act(
            () => membersApi.remove(schoolId, removing.membership_id),
            `${removing.full_name} was removed.`,
            removing.membership_id,
          );
          setRemoving(null);
        }}
      />

      <Dialog open={assigning !== null} onOpenChange={(open) => !open && setAssigning(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Assign school branches</DialogTitle>
            <DialogDescription>
              Add {assigning?.full_name} to one or more branches. Existing branch access is preserved.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            {schools.filter((school) => school.id !== schoolId && school.status === "active").map((school) => (
              <label key={school.id} className="flex items-center gap-3 rounded-md border p-3 text-sm">
                <input
                  type="checkbox"
                  checked={selectedBranches.includes(school.id)}
                  onChange={(event) => setSelectedBranches((current) => event.target.checked ? [...current, school.id] : current.filter((id) => id !== school.id))}
                />
                <span><span className="font-medium">{school.name}</span> <span className="text-muted-foreground">({school.code})</span></span>
              </label>
            ))}
            {schools.filter((school) => school.id !== schoolId && school.status === "active").length === 0 ? (
              <p className="text-sm text-muted-foreground">There are no other active school branches.</p>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssigning(null)}>Cancel</Button>
            <Button
              disabled={!assigning || selectedBranches.length === 0 || busy !== null}
              onClick={async () => {
                if (!assigning) return;
                await act(
                  () => membersApi.assignBranches(schoolId, assigning.membership_id, selectedBranches),
                  `${assigning.full_name} was assigned to ${selectedBranches.length} additional branch${selectedBranches.length === 1 ? "" : "es"}.`,
                  assigning.membership_id,
                );
                setAssigning(null);
              }}
            >
              Assign branches
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
