"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { ChevronDown, KeyRound, Mail, RotateCw, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Can } from "@/components/auth/can";
import { EmptyState } from "@/components/data-states";
import { Field } from "@/components/form/field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api/errors";
import { invitations as invitationsApi, members as membersApi } from "@/lib/api/resources";
import {
  INVITATION_STATUS_LABELS,
  PERMISSIONS,
  label,
  type InvitationRead,
  type RoleRead,
  type UsageItem,
} from "@/lib/api/types";
import { invitationCreateSchema, type InvitationCreateValues } from "@/lib/validation/rbac";
import { memberCreateSchema, type MemberCreateValues } from "@/lib/validation/rbac";

/**
 * Send and manage staff invitations (spec §7), embedded in the Members page as a
 * collapsible section — the "Invite staff" button in the page header opens it.
 *
 * Three things this section makes explicit, because each is surprising otherwise:
 *
 *   SEATS ARE CONSUMED ON SEND, not on accept. Otherwise a school could invite
 *   fifty people onto a twenty-five seat plan and discover the problem when the
 *   twenty-sixth tried to sign in. Revoking returns the seat.
 *
 *   RESENDING ISSUES A NEW LINK and kills the old one. The original cannot be
 *   re-sent — only its digest was stored — and rotating is the safer behaviour if
 *   the first email went somewhere it should not have.
 *
 *   THE ROLE LIST IS LIMITED to roles the inviter could grant. Inviting into a role
 *   more powerful than your own is the same escalation as editing a role, through a
 *   different door, and the server refuses it.
 */
export function InvitationsSection({
  schoolId,
  schoolName,
  invitations,
  roles,
  staffSeats,
  open,
  onToggle,
}: {
  schoolId: string;
  schoolName: string;
  invitations: InvitationRead[];
  roles: RoleRead[];
  staffSeats: UsageItem | null;
  open: boolean;
  onToggle: () => void;
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [busy, setBusy] = useState<string | null>(null);
  const [creationMode, setCreationMode] = useState<"invite" | "manual">("invite");

  const form = useForm<InvitationCreateValues>({
    resolver: zodResolver(invitationCreateSchema),
    defaultValues: { email: "", full_name: "", role_id: roles[0]?.id ?? "" },
  });
  const manualForm = useForm<MemberCreateValues>({
    resolver: zodResolver(memberCreateSchema),
    defaultValues: { email: "", full_name: "", password: "", role_id: roles[0]?.id ?? "" },
  });

  const seatsExhausted = staffSeats?.is_exhausted ?? false;
  const pendingCount = invitations.filter((i) => i.status === "pending").length;

  async function send(values: InvitationCreateValues) {
    try {
      await invitationsApi.create(schoolId, {
        email: values.email,
        full_name: values.full_name || undefined,
        role_id: values.role_id,
      });
      toast({ title: `Invitation sent to ${values.email}.` });
      form.reset({ email: "", full_name: "", role_id: values.role_id });
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "plan_limit_exceeded") {
          toast({
            variant: "destructive",
            title: t.invitations.noSeatsTitle,
            description: `${error.message} Upgrade your plan to invite more people.`,
          });
          return;
        }
        if (error.code === "ALREADY_MEMBER" || error.code === "INVITATION_PENDING") {
          form.setError("email", { message: error.message });
          return;
        }
        toast({ variant: "destructive", title: t.common.somethingWrong, description: error.message });
        return;
      }
      toast({ variant: "destructive", title: t.common.somethingWrong });
    }
  }

  async function createManually(values: MemberCreateValues) {
    try {
      await membersApi.create(schoolId, values);
      toast({ title: `${values.full_name} was added to ${schoolName}.` });
      manualForm.reset({ email: "", full_name: "", password: "", role_id: values.role_id });
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "plan_limit_exceeded") {
          toast({ variant: "destructive", title: t.invitations.noSeatsTitle, description: error.message });
          return;
        }
        if (error.code === "ACCOUNT_EXISTS_USE_INVITATION") {
          manualForm.setError("email", { message: error.message });
          return;
        }
        if (error.code === "WEAK_PASSWORD") {
          manualForm.setError("password", { message: error.message });
          return;
        }
        toast({ variant: "destructive", title: t.common.somethingWrong, description: error.message });
        return;
      }
      toast({ variant: "destructive", title: t.common.somethingWrong });
    }
  }

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

  function remove(id: string, email: string) {
    if (!window.confirm(`Delete the invitation to ${email}? It will be removed from this list.`)) {
      return;
    }
    void act(id, () => invitationsApi.remove(schoolId, id), `Invitation to ${email} deleted.`);
  }

  const pending = invitations.filter((i) => i.status === "pending");
  const past = invitations.filter((i) => i.status !== "pending");

  return (
    <section className="mb-8 rounded-xl border border-border bg-card">
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
            <div className="mb-3 flex gap-2" role="group" aria-label="Member creation method">
              <Button type="button" variant={creationMode === "invite" ? "default" : "outline"} onClick={() => setCreationMode("invite")}>
                <Mail className="size-4" aria-hidden /> Send invite
              </Button>
              <Button type="button" variant={creationMode === "manual" ? "default" : "outline"} onClick={() => setCreationMode("manual")}>
                <KeyRound className="size-4" aria-hidden /> Create with password
              </Button>
            </div>
            <p className="mb-3 text-sm text-muted-foreground">
              School branch: <span className="font-medium text-foreground">{schoolName}</span>
            </p>
            {creationMode === "invite" ? <form
              onSubmit={form.handleSubmit(send)}
              className="mb-8 grid gap-4 rounded-xl border border-border bg-background p-5"
              noValidate
            >
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label={t.common.email} htmlFor="email" error={form.formState.errors.email} required>
                  <Input type="email" placeholder="teacher@school.pk" {...form.register("email")} />
                </Field>
                <Field label={t.common.name} htmlFor="full_name" error={form.formState.errors.full_name}>
                  <Input placeholder={t.invitations.namePlaceholder} {...form.register("full_name")} />
                </Field>
                <Field label={t.common.role} htmlFor="role_id" error={form.formState.errors.role_id} required>
                  <NativeSelect {...form.register("role_id")}>
                    {roles.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.name}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
              </div>

              {seatsExhausted ? (
                <p className="rounded-md bg-warning/15 px-3 py-2 text-sm">
                  You have used all {staffSeats?.allowed} staff seats on your plan. Upgrade, or
                  remove a member, before inviting anyone else.
                </p>
              ) : staffSeats && !staffSeats.is_unlimited ? (
                <p className="text-xs text-muted-foreground">
                  {staffSeats.remaining} of {staffSeats.allowed} staff seats remaining.
                </p>
              ) : null}

              <div>
                <Button type="submit" disabled={form.formState.isSubmitting || seatsExhausted}>
                  <Mail className="size-4" aria-hidden />
                  {t.invitations.sendInvitation}
                </Button>
              </div>
            </form> : (
              <form onSubmit={manualForm.handleSubmit(createManually)} className="mb-8 grid gap-4 rounded-xl border border-border bg-background p-5" noValidate>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label={t.common.email} htmlFor="manual-email" error={manualForm.formState.errors.email} required>
                    <Input id="manual-email" type="email" {...manualForm.register("email")} />
                  </Field>
                  <Field label={t.common.name} htmlFor="manual-name" error={manualForm.formState.errors.full_name} required>
                    <Input id="manual-name" {...manualForm.register("full_name")} />
                  </Field>
                  <Field label="Temporary password" htmlFor="manual-password" error={manualForm.formState.errors.password} required>
                    <PasswordInput id="manual-password" autoComplete="new-password" {...manualForm.register("password")} />
                  </Field>
                  <Field label={t.common.role} htmlFor="manual-role" error={manualForm.formState.errors.role_id} required>
                    <NativeSelect id="manual-role" {...manualForm.register("role_id")}>
                      {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
                    </NativeSelect>
                  </Field>
                </div>
                {seatsExhausted ? <p className="rounded-md bg-warning/15 px-3 py-2 text-sm">No staff seats remain on the current plan.</p> : null}
                <div><Button type="submit" disabled={manualForm.formState.isSubmitting || seatsExhausted}><KeyRound className="size-4" aria-hidden />Create member</Button></div>
              </form>
            )}
          </Can>

          {invitations.length === 0 ? (
            <EmptyState
              title={t.invitations.emptyTitle}
              description={t.invitations.emptyBody}
            />
          ) : (
            <div className="grid gap-6">
              <InvitationTable
                heading={t.invitations.pending}
                rows={pending}
                busy={busy}
                onResend={(id, email) =>
                  act(id, () => invitationsApi.resend(schoolId, id), `New link sent to ${email}.`)
                }
                onRevoke={(id, email) =>
                  act(id, () => invitationsApi.revoke(schoolId, id), `Invitation to ${email} revoked.`)
                }
                onDelete={remove}
              />
              {past.length > 0 ? (
                <InvitationTable heading={t.invitations.past} rows={past} busy={busy} onDelete={remove} />
              ) : null}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

function InvitationTable({
  heading,
  rows,
  busy,
  onResend,
  onRevoke,
  onDelete,
}: {
  heading: string;
  rows: InvitationRead[];
  busy: string | null;
  onResend?: (id: string, email: string) => void;
  onRevoke?: (id: string, email: string) => void;
  onDelete?: (id: string, email: string) => void;
}) {
  const hasActions = Boolean(onResend || onRevoke || onDelete);

  if (rows.length === 0) return null;

  return (
    <section>
      <h2 className="mb-2 text-sm font-medium text-muted-foreground">{heading}</h2>
      <div className="rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
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
                      {onResend ? (
                      <Can permission={PERMISSIONS.invitationResend}>
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={busy === invitation.id}
                          onClick={() => onResend(invitation.id, invitation.email)}
                          title="Send a new link (the old one stops working)"
                        >
                          <RotateCw className="size-4" aria-hidden />
                          <span className="sr-only">Resend to {invitation.email}</span>
                        </Button>
                      </Can>
                      ) : null}
                      {onRevoke ? (
                      <Can permission={PERMISSIONS.invitationRevoke}>
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={busy === invitation.id}
                          onClick={() => onRevoke?.(invitation.id, invitation.email)}
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
                            onClick={() => onDelete(invitation.id, invitation.email)}
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
      </div>
    </section>
  );
}
