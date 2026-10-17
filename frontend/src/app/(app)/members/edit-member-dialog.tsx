"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Can } from "@/components/auth/can";
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
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { PasswordInput } from "@/components/ui/password-input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/use-toast";
import { ApiError } from "@/lib/api/errors";
import { members as membersApi } from "@/lib/api/resources";
import { classesApi } from "@/lib/api/resources/classes";
import { subjectsApi } from "@/lib/api/resources/subjects";
import { PERMISSIONS, type MemberRead, type MemberUpdate, type RoleRead } from "@/lib/api/types";

type Assignment = MemberRead["assigned_classes"] extends (infer A)[] | undefined ? A : never;

/**
 * Edit one staff member: name, contact details, sign-in password, role, and the
 * classes they teach.
 *
 * Email and password are the member's SIGN-IN details. The server refuses to change
 * them for a principal, for someone with more access than you, or for an account
 * that also belongs to another organization; those refusals come back as inline
 * errors rather than being second-guessed here. Setting a password needs
 * `member:reset_password` and signs the member out on every device.
 *
 * Removing a class assignment does not touch the membership — it clears the
 * section's class teacher (or the curriculum row's teacher) through the classes
 * API, so it needs `class:update` on top of `member:update`.
 */
export function EditMemberDialog({
  schoolId,
  member,
  roles,
  onClose,
}: {
  schoolId: string;
  member: MemberRead | null;
  roles: RoleRead[];
  onClose: () => void;
}) {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [roleId, setRoleId] = useState("");
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [saving, setSaving] = useState(false);
  const [removingKey, setRemovingKey] = useState<string | null>(null);

  useEffect(() => {
    if (!member) return;
    setFullName(member.full_name);
    setEmail(member.email);
    setPhone(member.phone ?? "");
    setPassword("");
    setConfirmPassword("");
    setEmailError(null);
    setPasswordError(null);
    setRoleId(member.role_id);
    setAssignments(member.assigned_classes ?? []);
  }, [member]);

  // The principal role is transferred, never granted, so it is not offered here.
  const isOwner = member?.role_code === "principal";

  function fail(error: unknown) {
    toast({
      variant: "destructive",
      title: "Something went wrong",
      description: error instanceof ApiError ? error.message : "Please try again.",
    });
  }

  async function save() {
    if (!member) return;
    setEmailError(null);
    setPasswordError(null);
    if (password && password !== confirmPassword) {
      setPasswordError("The two passwords do not match.");
      return;
    }

    const body: MemberUpdate = {};
    const name = fullName.trim();
    if (name && name !== member.full_name) body.full_name = name;
    const newEmail = email.trim();
    if (!isOwner && newEmail && newEmail.toLowerCase() !== member.email.toLowerCase()) {
      body.email = newEmail;
    }
    // An empty string clears the number on the server.
    const newPhone = phone.trim();
    if (newPhone !== (member.phone ?? "")) body.phone = newPhone;
    if (!isOwner && password) body.password = password;
    if (!isOwner && roleId && roleId !== member.role_id) body.role_id = roleId;
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    setSaving(true);
    try {
      await membersApi.update(schoolId, member.membership_id, body);
      toast({
        title: `${name || member.full_name} was updated.`,
        description: body.password ? "Their new password is set and they were signed out." : undefined,
      });
      router.refresh();
      onClose();
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "EMAIL_TAKEN") {
          setEmailError(error.message);
          return;
        }
        if (error.code === "WEAK_PASSWORD") {
          setPasswordError(error.message);
          return;
        }
      }
      fail(error);
    } finally {
      setSaving(false);
    }
  }

  async function removeAssignment(a: Assignment, key: string) {
    setRemovingKey(key);
    try {
      if (a.section_id) {
        await classesApi.sections.update(a.section_id, { class_teacher_id: null });
      } else if (a.class_subject_id) {
        await subjectsApi.curriculum.update(a.class_subject_id, { teacher_id: null });
      }
      setAssignments((current) => current.filter((x) => x !== a));
      toast({ title: `Removed from ${describe(a)}.` });
      router.refresh();
    } catch (error) {
      fail(error);
    } finally {
      setRemovingKey(null);
    }
  }

  return (
    <Dialog open={member !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit {member?.full_name}</DialogTitle>
          <DialogDescription>{member?.email}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label htmlFor="member-name">Full name</Label>
            <Input
              id="member-name"
              value={fullName}
              maxLength={200}
              onChange={(event) => setFullName(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="member-role">Role</Label>
            <NativeSelect
              id="member-role"
              value={roleId}
              disabled={isOwner}
              onChange={(event) => setRoleId(event.target.value)}
            >
              {isOwner || !roles.some((r) => r.id === member?.role_id) ? (
                <option value={member?.role_id}>{member?.role_name}</option>
              ) : null}
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="member-email">Email (used to sign in)</Label>
            <Input
              id="member-email"
              type="email"
              autoComplete="off"
              value={email}
              maxLength={320}
              disabled={isOwner}
              aria-invalid={emailError ? true : undefined}
              aria-describedby={emailError ? "member-email-error" : undefined}
              onChange={(event) => {
                setEmail(event.target.value);
                setEmailError(null);
              }}
            />
            {emailError ? (
              <p id="member-email-error" className="text-sm text-destructive">
                {emailError}
              </p>
            ) : null}
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="member-phone">Phone</Label>
            <Input
              id="member-phone"
              type="tel"
              autoComplete="off"
              value={phone}
              maxLength={32}
              placeholder="Not set"
              onChange={(event) => setPhone(event.target.value)}
            />
          </div>
        </div>

        <Can permission={PERMISSIONS.memberResetPassword}>
          <div className="grid gap-2 rounded-md border p-4">
            <div>
              <Label>Change password</Label>
              <p className="text-sm text-muted-foreground">
                {isOwner
                  ? "The principal changes their own password from their account."
                  : "Leave blank to keep the current password. Setting a new one signs them out on every device."}
              </p>
            </div>
            {isOwner ? null : (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="member-password">New password</Label>
                  <PasswordInput
                    id="member-password"
                    autoComplete="new-password"
                    value={password}
                    maxLength={200}
                    aria-invalid={passwordError ? true : undefined}
                    aria-describedby={passwordError ? "member-password-error" : undefined}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      setPasswordError(null);
                    }}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="member-password-confirm">Confirm new password</Label>
                  <PasswordInput
                    id="member-password-confirm"
                    autoComplete="new-password"
                    value={confirmPassword}
                    maxLength={200}
                    disabled={!password}
                    aria-invalid={passwordError ? true : undefined}
                    onChange={(event) => {
                      setConfirmPassword(event.target.value);
                      setPasswordError(null);
                    }}
                  />
                </div>
                {passwordError ? (
                  <p id="member-password-error" className="text-sm text-destructive sm:col-span-2">
                    {passwordError}
                  </p>
                ) : null}
              </div>
            )}
          </div>
        </Can>

        <div className="grid gap-2">
          <Label>Classes assigned</Label>
          {assignments.length === 0 ? (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              Not assigned to any class.
            </p>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Class</TableHead>
                    <TableHead>Section / Subject</TableHead>
                    <TableHead>Assignment</TableHead>
                    <TableHead className="w-28" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {assignments.map((a) => {
                    const key = a.section_id ?? a.class_subject_id ?? describe(a);
                    return (
                      <TableRow key={key}>
                        <TableCell className="font-medium">{a.class_name}</TableCell>
                        <TableCell>{a.section_name ?? a.subject_name}</TableCell>
                        <TableCell>
                          <Badge variant={a.section_id ? "default" : "neutral"}>
                            {a.section_id ? "Class teacher" : "Subject teacher"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <Can permission={PERMISSIONS.classUpdate}>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive"
                              disabled={removingKey !== null}
                              onClick={() => removeAssignment(a, key)}
                            >
                              <X className="size-4" aria-hidden />
                              {removingKey === key ? "Removing…" : "Remove"}
                            </Button>
                          </Can>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={save}
            disabled={saving || fullName.trim() === "" || (!isOwner && email.trim() === "")}
          >
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function describe(a: Assignment): string {
  return a.section_name
    ? `${a.class_name} – ${a.section_name}`
    : `${a.class_name} · ${a.subject_name ?? ""}`;
}
