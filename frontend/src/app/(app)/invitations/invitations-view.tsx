"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Mail, RotateCw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Can } from "@/components/auth/can";
import { EmptyState } from "@/components/data-states";
import { Field } from "@/components/form/field";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";
import { invitations as invitationsApi } from "@/lib/api/resources";
import {
  INVITATION_STATUS_LABELS,
  PERMISSIONS,
  label,
  type InvitationRead,
  type RoleRead,
  type UsageItem,
} from "@/lib/api/types";
import { invitationCreateSchema, type InvitationCreateValues } from "@/lib/validation/rbac";

/**
 * Send and manage staff invitations (spec §7).
 *
 * Three things this screen makes explicit, because each is surprising otherwise:
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
export function InvitationsView({
  schoolId,
  invitations,
  roles,
  staffSeats,
}: {
  schoolId: string;
  invitations: InvitationRead[];
  roles: RoleRead[];
  staffSeats: UsageItem | null;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);

  const form = useForm<InvitationCreateValues>({
    resolver: zodResolver(invitationCreateSchema),
    defaultValues: { email: "", full_name: "", role_id: roles[0]?.id ?? "" },
  });

  const seatsExhausted = staffSeats?.is_exhausted ?? false;

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
            title: "No staff seats left",
            description: `${error.message} Upgrade your plan to invite more people.`,
          });
          return;
        }
        if (error.code === "ALREADY_MEMBER" || error.code === "INVITATION_PENDING") {
          form.setError("email", { message: error.message });
          return;
        }
        toast({ variant: "destructive", title: "Could not send", description: error.message });
        return;
      }
      toast({ variant: "destructive", title: "Could not send" });
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
        title: "That didn't work",
        description: error instanceof ApiError ? error.message : undefined,
      });
    } finally {
      setBusy(null);
    }
  }

  const pending = invitations.filter((i) => i.status === "pending");
  const past = invitations.filter((i) => i.status !== "pending");

  return (
    <div className="mx-auto w-full max-w-4xl">
      <PageHeader
        title="Invitations"
        description="Invite staff to this school. They choose their own password when they accept."
      />

      <Can
        permission={PERMISSIONS.memberInvite}
        fallback={
          <p className="mb-6 rounded-lg bg-muted/60 p-4 text-sm text-muted-foreground">
            You can see pending invitations but cannot send new ones.
          </p>
        }
      >
        <form
          onSubmit={form.handleSubmit(send)}
          className="mb-8 grid gap-4 rounded-xl border border-border bg-card p-5"
          noValidate
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Email" htmlFor="email" error={form.formState.errors.email} required>
              <Input type="email" placeholder="teacher@school.pk" {...form.register("email")} />
            </Field>
            <Field label="Name" htmlFor="full_name" error={form.formState.errors.full_name}>
              <Input placeholder="Optional" {...form.register("full_name")} />
            </Field>
            <Field label="Role" htmlFor="role_id" error={form.formState.errors.role_id} required>
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
              Send invitation
            </Button>
          </div>
        </form>
      </Can>

      {invitations.length === 0 ? (
        <EmptyState
          title="No invitations yet"
          description="Invited staff appear here until they accept."
        />
      ) : (
        <div className="grid gap-6">
          <InvitationTable
            heading="Pending"
            rows={pending}
            busy={busy}
            onResend={(id, email) =>
              act(id, () => invitationsApi.resend(schoolId, id), `New link sent to ${email}.`)
            }
            onRevoke={(id, email) =>
              act(id, () => invitationsApi.revoke(schoolId, id), `Invitation to ${email} revoked.`)
            }
          />
          {past.length > 0 ? <InvitationTable heading="Past" rows={past} busy={busy} /> : null}
        </div>
      )}
    </div>
  );
}

function InvitationTable({
  heading,
  rows,
  busy,
  onResend,
  onRevoke,
}: {
  heading: string;
  rows: InvitationRead[];
  busy: string | null;
  onResend?: (id: string, email: string) => void;
  onRevoke?: (id: string, email: string) => void;
}) {
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
              {onResend ? <TableHead className="w-32" /> : null}
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
                {onResend ? (
                  <TableCell>
                    <div className="flex gap-1">
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
