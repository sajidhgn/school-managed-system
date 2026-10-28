"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, Mail } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Field } from "@/components/form/field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { PasswordInput } from "@/components/ui/password-input";
import { toast } from "@/components/ui/use-toast";
import { useTranslations } from "@/components/providers/i18n-provider";
import { ApiError } from "@/lib/api/errors";
import { invitations as invitationsApi, members as membersApi } from "@/lib/api/resources";
import type { RoleRead, UsageItem } from "@/lib/api/types";
import {
  invitationCreateSchema,
  memberCreateSchema,
  type InvitationCreateValues,
  type MemberCreateValues,
} from "@/lib/validation/rbac";

/** A branch a member can be added to. */
export interface Branch {
  id: string;
  name: string;
}

/**
 * Add a member to any branch: create them with a password, or send an invitation.
 * Rendered inline at the top of the Members page's invitation section.
 *
 * THE BRANCH IS PART OF THE FORM, NOT OF THE PAGE
 *   Members is not opened "for" a campus, so the form asks which one the new member
 *   joins. The role list follows the choice: roles belong to a branch, and the server
 *   refuses a role from another one (ROLE_SCOPE_MISMATCH). A school-scoped
 *   administrator has exactly one branch, so for them the picker is a fixed label.
 *
 * SEATS ARE CONSUMED ON SEND for invitations, and on create for a password account —
 * both are refused with a 402 before anything is written when the plan is full.
 */
export function AddMemberForm({
  branches,
  rolesByBranch,
  defaultBranchId,
  staffSeats,
}: {
  branches: Branch[];
  rolesByBranch: Record<string, RoleRead[]>;
  defaultBranchId: string | null;
  staffSeats: UsageItem | null;
}) {
  const router = useRouter();
  const { t } = useTranslations();
  const [mode, setMode] = useState<"manual" | "invite">("manual");
  const initialBranchId = defaultBranchId ?? branches[0]?.id ?? "";
  const [branchId, setBranchId] = useState(initialBranchId);

  // The page's branch filter lives in the URL, and changing it keeps this component
  // mounted — so the form follows the filter here, adjusted during render when it
  // changes, and adding while looking at one branch adds to that branch.
  const [followedDefault, setFollowedDefault] = useState(defaultBranchId);
  if (defaultBranchId !== followedDefault) {
    setFollowedDefault(defaultBranchId);
    setBranchId(initialBranchId);
  }

  const roles = rolesByBranch[branchId] ?? [];
  const branchName = branches.find((b) => b.id === branchId)?.name ?? "";
  const seatsExhausted = staffSeats?.is_exhausted ?? false;

  const inviteForm = useForm<InvitationCreateValues>({
    resolver: zodResolver(invitationCreateSchema),
    defaultValues: { email: "", full_name: "", role_id: roles[0]?.id ?? "" },
  });
  const manualForm = useForm<MemberCreateValues>({
    resolver: zodResolver(memberCreateSchema),
    defaultValues: { email: "", full_name: "", password: "", role_id: roles[0]?.id ?? "" },
  });

  // A role id from the previous branch would be refused by the server, so switching
  // branch re-points both forms at the new branch's first role.
  const setInviteValue = inviteForm.setValue;
  const setManualValue = manualForm.setValue;
  useEffect(() => {
    const firstRole = (rolesByBranch[branchId] ?? [])[0]?.id ?? "";
    setInviteValue("role_id", firstRole);
    setManualValue("role_id", firstRole);
  }, [branchId, rolesByBranch, setInviteValue, setManualValue]);

  function failed(error: unknown, onFieldError: (code: string, message: string) => boolean) {
    if (error instanceof ApiError) {
      if (error.code === "plan_limit_exceeded") {
        toast({
          variant: "destructive",
          title: t.invitations.noSeatsTitle,
          description: `${error.message} Upgrade your plan to add more people.`,
        });
        return;
      }
      if (onFieldError(error.code, error.message)) return;
      toast({ variant: "destructive", title: t.common.somethingWrong, description: error.message });
      return;
    }
    toast({ variant: "destructive", title: t.common.somethingWrong });
  }

  async function createManually(values: MemberCreateValues) {
    try {
      await membersApi.create(branchId, values);
      toast({ title: `${values.full_name} was added to ${branchName}.` });
      manualForm.reset({ email: "", full_name: "", password: "", role_id: values.role_id });
      router.refresh();
    } catch (error) {
      failed(error, (code, message) => {
        if (code === "ACCOUNT_EXISTS_USE_INVITATION") {
          manualForm.setError("email", { message });
          return true;
        }
        if (code === "WEAK_PASSWORD") {
          manualForm.setError("password", { message });
          return true;
        }
        return false;
      });
    }
  }

  async function send(values: InvitationCreateValues) {
    try {
      await invitationsApi.create(branchId, {
        email: values.email,
        full_name: values.full_name || undefined,
        role_id: values.role_id,
      });
      toast({ title: `Invitation sent to ${values.email}.` });
      inviteForm.reset({ email: "", full_name: "", role_id: values.role_id });
      router.refresh();
    } catch (error) {
      failed(error, (code, message) => {
        if (code === "ALREADY_MEMBER" || code === "INVITATION_PENDING") {
          inviteForm.setError("email", { message });
          return true;
        }
        return false;
      });
    }
  }

  const branchField = (
    <Field label={t.members.branch} htmlFor="member-branch" required>
      {branches.length > 1 ? (
        <NativeSelect value={branchId} onChange={(event) => setBranchId(event.target.value)}>
          {branches.map((branch) => (
            <option key={branch.id} value={branch.id}>
              {branch.name}
            </option>
          ))}
        </NativeSelect>
      ) : (
        <Input value={branchName} readOnly />
      )}
    </Field>
  );

  const roleOptions = roles.map((role) => (
    <option key={role.id} value={role.id}>
      {role.name}
    </option>
  ));

  const seatNotice = seatsExhausted ? (
    <p className="rounded-md bg-warning/15 px-3 py-2 text-sm">
      You have used all {staffSeats?.allowed} staff seats on your plan. Upgrade, or remove a
      member, before adding anyone else.
    </p>
  ) : staffSeats && !staffSeats.is_unlimited ? (
    <p className="text-xs text-muted-foreground">
      {staffSeats.remaining} of {staffSeats.allowed} staff seats remaining.
    </p>
  ) : null;

  const boxClass = "mb-8 grid gap-4 rounded-xl border border-border bg-background p-5";

  return (
    <>
      <div className="mb-3 flex gap-2" role="group" aria-label="Member creation method">
        <Button
          type="button"
          variant={mode === "manual" ? "default" : "outline"}
          onClick={() => setMode("manual")}
        >
          <KeyRound className="size-4" aria-hidden /> Create with password
        </Button>
        <Button
          type="button"
          variant={mode === "invite" ? "default" : "outline"}
          onClick={() => setMode("invite")}
        >
          <Mail className="size-4" aria-hidden /> Send invite
        </Button>
      </div>

      {branches.length === 0 ? (
        <p className="mb-8 rounded-md bg-muted/60 p-4 text-sm text-muted-foreground">
          Create a school branch first — every member belongs to one.
        </p>
      ) : mode === "manual" ? (
        <form onSubmit={manualForm.handleSubmit(createManually)} className={boxClass} noValidate>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {branchField}
            <Field label={t.common.role} htmlFor="manual-role" error={manualForm.formState.errors.role_id} required>
              <NativeSelect {...manualForm.register("role_id")}>{roleOptions}</NativeSelect>
            </Field>
            <Field label={t.common.name} htmlFor="manual-name" error={manualForm.formState.errors.full_name} required>
              <Input {...manualForm.register("full_name")} />
            </Field>
            <Field label={t.common.email} htmlFor="manual-email" error={manualForm.formState.errors.email} required>
              <Input type="email" placeholder="teacher@school.pk" {...manualForm.register("email")} />
            </Field>
            <Field label="Temporary password" htmlFor="manual-password" error={manualForm.formState.errors.password} required>
              <PasswordInput autoComplete="new-password" {...manualForm.register("password")} />
            </Field>
          </div>
          {seatNotice}
          <div>
            <Button type="submit" disabled={manualForm.formState.isSubmitting || seatsExhausted}>
              <KeyRound className="size-4" aria-hidden />
              Create member
            </Button>
          </div>
        </form>
      ) : (
        <form onSubmit={inviteForm.handleSubmit(send)} className={boxClass} noValidate>
          <div className="grid gap-4 sm:grid-cols-2">
            {branchField}
            <Field label={t.common.role} htmlFor="invite-role" error={inviteForm.formState.errors.role_id} required>
              <NativeSelect {...inviteForm.register("role_id")}>{roleOptions}</NativeSelect>
            </Field>
            <Field label={t.common.email} htmlFor="invite-email" error={inviteForm.formState.errors.email} required>
              <Input type="email" placeholder="teacher@school.pk" {...inviteForm.register("email")} />
            </Field>
            <Field label={t.common.name} htmlFor="invite-name" error={inviteForm.formState.errors.full_name}>
              <Input placeholder={t.invitations.namePlaceholder} {...inviteForm.register("full_name")} />
            </Field>
          </div>
          {seatNotice}
          <div>
            <Button type="submit" disabled={inviteForm.formState.isSubmitting || seatsExhausted}>
              <Mail className="size-4" aria-hidden />
              {t.invitations.sendInvitation}
            </Button>
          </div>
        </form>
      )}
    </>
  );
}
