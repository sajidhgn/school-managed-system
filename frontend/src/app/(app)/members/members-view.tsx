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
import { MEMBER_STATUS_LABELS, PERMISSIONS, label, type MemberRead, type RoleRead } from "@/lib/api/types";

/**
 * The staff table: change role, suspend, remove.
 *
 * =============================================================================
 * THE SERVER REFUSES THINGS THIS TABLE ALSO REFUSES — BOTH ARE NEEDED
 * =============================================================================
 *   You cannot act on your OWN membership here, and the last owner cannot be
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
  currentMembershipId,
}: {
  schoolId: string;
  initialMembers: MemberRead[];
  roles: RoleRead[];
  currentMembershipId: string | null;
}) {
  const { t } = useTranslations();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [removing, setRemoving] = useState<MemberRead | null>(null);

  // Only roles for THIS school are assignable. Org-level roles (owner) appear in the
  // list so a principal can see they exist, but assigning one here would be a scope
  // violation the server rejects.
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
                const isOwner = member.role_code === "owner";

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
                                // The server refuses to remove the last owner (409).
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
    </div>
  );
}
