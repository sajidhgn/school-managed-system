"use client";

import { ChevronDown, Mail, RotateCw, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { AddMemberForm, type Branch } from "./add-member-form";
import { Can } from "@/components/auth/can";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/data-states";
import { Pagination } from "@/components/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api/errors";
import { invitations as invitationsApi } from "@/lib/api/resources";
import {
  INVITATION_STATUS_LABELS,
  PERMISSIONS,
  label,
  type InvitationRead,
  type Page,
  type RoleRead,
  type UsageItem,
} from "@/lib/api/types";

/**
 * Add staff and manage invitations (spec §7) across the branches the Members page is
 * showing, embedded as a collapsible section — the "Add member" button in the page
 * header opens it. The form sits on top; the invitations sent follow below it.
 *
 * Two things this section makes explicit, because each is surprising otherwise:
 *
 *   SEATS ARE CONSUMED ON SEND, not on accept. Otherwise a school could invite
 *   fifty people onto a twenty-five seat plan and discover the problem when the
 *   twenty-sixth tried to sign in. Revoking returns the seat.
 *
 *   RESENDING ISSUES A NEW LINK and kills the old one. The original cannot be
 *   re-sent — only its digest was stored — and rotating is the safer behaviour if
 *   the first email went somewhere it should not have.
 *
 * Every action is addressed to the invitation's OWN branch. Rows from several
 * branches share this list, and the page's branch filter says nothing about which
 * campus a given row was sent from.
 *
 * The list is one page of `GET /org/invitations`: the branch and status filters and
 * the page are applied in the database, and the pending badge is that query's total
 * — so neither depends on how many rows happen to be on screen.
 */
export function InvitationsSection({
  invitations,
  pendingCount,
  statusFilter,
  onStatusChange,
  onPageChange,
  branches,
  branchNames,
  rolesByBranch,
  defaultBranchId,
  showBranch,
  staffSeats,
  open,
  onToggle,
}: {
  invitations: Page<InvitationRead>;
  /** Pending invitations in scope, counted by the database. */
  pendingCount: number;
  statusFilter: string | null;
  onStatusChange: (status: string | null) => void;
  onPageChange: (page: number) => void;
  /** Branches a member can be added to. */
  branches: Branch[];
  branchNames: Record<string, string>;
  rolesByBranch: Record<string, RoleRead[]>;
  defaultBranchId: string | null;
  showBranch: boolean;
  staffSeats: UsageItem | null;
  open: boolean;
  onToggle: () => void;
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [busy, setBusy] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<InvitationRead | null>(null);

  async function act(id: string, fn: () => Promise<unknown>, message: string) {
    setBusy(id);
    try {
      await fn();
      toast({ title: message });
      router.refresh();
    } catch (error) {
      toast({
        variant: "destructive",
        title: t.common.somethingWrong,
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(null);
    }
  }

  // Listed per branch, so `school_id` is always the branch the row was fetched from.
  const branchOf = (invitation: InvitationRead) => invitation.school_id ?? "";

  // Confirmed in the same dialog the staff table uses for "Remove", not the
  // browser's `window.confirm`: that one cannot be styled or translated, and some
  // browsers offer to suppress it, after which deletes go through unasked.
  function remove(invitation: InvitationRead) {
    setDeleting(invitation);
  }

  return (
    <section className="mb-4 rounded-xl border border-border bg-card">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="invitations-panel"
        className="flex w-full items-center justify-between gap-4 rounded-xl px-5 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div>
          <span className="flex items-center gap-2 text-sm font-medium">
            <Mail className="size-4 text-muted-foreground" aria-hidden />
            {t.invitations.title}
            {pendingCount > 0 ? (
              <Badge variant="warning">
                {pendingCount} {t.invitations.pending.toLowerCase()}
              </Badge>
            ) : null}
          </span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{t.invitations.subtitle}</span>
        </div>
        <ChevronDown
          className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>

      {open ? (
        <div id="invitations-panel" className="border-t border-border p-5">
          <Can
            permission={PERMISSIONS.memberInvite}
            fallback={
              <p className="mb-6 rounded-lg bg-muted/60 p-4 text-sm text-muted-foreground">
                {t.invitations.readOnlyNotice}
              </p>
            }
          >
            <AddMemberForm
              branches={branches}
              rolesByBranch={rolesByBranch}
              defaultBranchId={defaultBranchId}
              staffSeats={staffSeats}
            />
          </Can>

          <div className="mb-3 flex items-center gap-2">
            <label htmlFor="invitation-status" className="text-sm text-muted-foreground">
              {t.common.status}
            </label>
            <NativeSelect
              id="invitation-status"
              className="w-44"
              value={statusFilter ?? ""}
              onChange={(event) => onStatusChange(event.target.value || null)}
            >
              <option value="">All statuses</option>
              {Object.entries(INVITATION_STATUS_LABELS).map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </NativeSelect>
          </div>

          {invitations.meta.total === 0 ? (
            <EmptyState
              title={statusFilter ? "No invitations with this status" : t.invitations.emptyTitle}
              description={statusFilter ? undefined : t.invitations.emptyBody}
            />
          ) : (
            <InvitationTable
              rows={invitations.items}
              busy={busy}
              branchNames={showBranch ? branchNames : null}
              onResend={(invitation) =>
                act(
                  invitation.id,
                  () => invitationsApi.resend(branchOf(invitation), invitation.id),
                  `New link sent to ${invitation.email}.`,
                )
              }
              onRevoke={(invitation) =>
                act(
                  invitation.id,
                  () => invitationsApi.revoke(branchOf(invitation), invitation.id),
                  `Invitation to ${invitation.email} revoked.`,
                )
              }
              onDelete={remove}
              footer={
                <Pagination
                  meta={invitations.meta}
                  onPageChange={onPageChange}
                  disabled={busy !== null}
                />
              }
            />
          )}
        </div>
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(isOpen) => !isOpen && setDeleting(null)}
        title={`Delete the invitation to ${deleting?.email}?`}
        description="It will be removed from this list. A pending invitation's link stops working and its staff seat is returned."
        confirmLabel="Delete"
        variant="destructive"
        loading={deleting !== null && busy === deleting.id}
        onConfirm={async () => {
          if (!deleting) return;
          await act(
            deleting.id,
            () => invitationsApi.remove(branchOf(deleting), deleting.id),
            `Invitation to ${deleting.email} deleted.`,
          );
          setDeleting(null);
        }}
      />
    </section>
  );
}

function InvitationTable({
  rows,
  busy,
  branchNames,
  onResend,
  onRevoke,
  onDelete,
  footer,
}: {
  rows: InvitationRead[];
  busy: string | null;
  /** Branch name by id, or null to leave the Branch column out. */
  branchNames: Record<string, string> | null;
  onResend?: (invitation: InvitationRead) => void;
  onRevoke?: (invitation: InvitationRead) => void;
  onDelete?: (invitation: InvitationRead) => void;
  /** Rendered under the table, inside its border — the pagination. */
  footer?: ReactNode;
}) {
  const hasActions = Boolean(onResend || onRevoke || onDelete);

  return (
    <section>
      <div className="rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              {branchNames ? <TableHead>Branch</TableHead> : null}
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Expires</TableHead>
              {hasActions ? <TableHead className="w-32" /> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((invitation) => (
              <TableRow key={invitation.id}>
                <TableCell>
                  <div className="font-medium">{invitation.email}</div>
                  {invitation.full_name ? (
                    <div className="text-xs text-muted-foreground">{invitation.full_name}</div>
                  ) : null}
                </TableCell>
                {branchNames ? (
                  <TableCell>{branchNames[invitation.school_id ?? ""] ?? "—"}</TableCell>
                ) : null}
                <TableCell>{invitation.role_name ?? "—"}</TableCell>
                <TableCell>
                  <Badge
                    variant={
                      invitation.status === "pending"
                        ? "warning"
                        : invitation.status === "accepted"
                          ? "success"
                          : "neutral"
                    }
                  >
                    {label(INVITATION_STATUS_LABELS, invitation.status)}
                  </Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {new Date(invitation.expires_at).toLocaleDateString()}
                </TableCell>
                {hasActions ? (
                  <TableCell>
                    <div className="flex gap-1">
                      {onResend && invitation.status === "pending" ? (
                      <Can permission={PERMISSIONS.invitationResend}>
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={busy === invitation.id}
                          onClick={() => onResend(invitation)}
                          title="Send a new link (the old one stops working)"
                        >
                          <RotateCw className="size-4" aria-hidden />
                          <span className="sr-only">Resend to {invitation.email}</span>
                        </Button>
                      </Can>
                      ) : null}
                      {onRevoke && invitation.status === "pending" ? (
                      <Can permission={PERMISSIONS.invitationRevoke}>
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={busy === invitation.id}
                          onClick={() => onRevoke?.(invitation)}
                          title="Revoke — the link dies immediately and the seat is returned"
                        >
                          <X className="size-4" aria-hidden />
                          <span className="sr-only">Revoke {invitation.email}</span>
                        </Button>
                      </Can>
                      ) : null}
                      {onDelete ? (
                        <Can permission={PERMISSIONS.invitationRevoke}>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="text-destructive hover:text-destructive"
                            disabled={busy === invitation.id}
                            onClick={() => onDelete(invitation)}
                            title="Delete — removes it from this list"
                          >
                            <Trash2 className="size-4" aria-hidden />
                            <span className="sr-only">Delete invitation to {invitation.email}</span>
                          </Button>
                        </Can>
                      ) : null}
                    </div>
                  </TableCell>
                ) : null}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {footer}
      </div>
    </section>
  );
}
