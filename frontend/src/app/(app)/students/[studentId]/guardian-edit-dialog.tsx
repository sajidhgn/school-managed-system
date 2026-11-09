"use client";

import * as React from "react";
import Link from "next/link";
import { Link2, Search, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/misc";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import {
  useChangeGuardianPhone,
  useGuardianDetail,
  useLinkGuardian,
  useSetGuardianPortal,
  useUnlinkGuardian,
  useUpdateGuardian,
  useUpdateGuardianLink,
} from "@/hooks/use-guardians";
import { useStudents } from "@/hooks/use-students";
import type { GuardianDetail, GuardianRelationship, StudentGuardianRead } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { studentsGuardiansMessages } from "@/lib/i18n/modules/students-guardians";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { useLabels } from "@/lib/i18n/use-labels";
import { fillNodes } from "@/lib/i18n/format";

/** Relationship keys in display order, from the localized label map. */
function useRelationships() {
  const L = useLabels();
  return { labels: L.relationship, values: Object.keys(L.relationship) as GuardianRelationship[] };
}

/**
 * Everything about one parent, from the child's page.
 *
 * =============================================================================
 * FOUR TABS, BECAUSE THEY ARE FOUR DIFFERENT KINDS OF CHANGE
 * =============================================================================
 *   Details      — the person: name, CNIC, email. A profile edit (`guardian:update`).
 *   This child   — what they are to THIS student: father, may collect them at the
 *                  gate, gets notices. Lives on the link, so it differs per child.
 *   Sign-in      — the phone they sign in with, and whether the portal is open.
 *                  A CREDENTIAL change (`guardian:portal`): whoever holds the new
 *                  number sees this family's records. Kept apart so it is never
 *                  changed by accident while fixing a misspelt name.
 *   Family       — their other children. Linking a sibling here is what makes the
 *                  sibling fee discount see the two as one family.
 *
 * Removing them from this child keeps the record while they still have other
 * children. When this was their last child and the caller holds `guardian:delete`,
 * the record goes too — an orphaned contact is noise in every search.
 */
export function GuardianEditDialog({
  open,
  onOpenChange,
  guardian,
  studentId,
  canUpdate,
  canPortal,
  canDelete,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  guardian: StudentGuardianRead;
  studentId: string;
  canUpdate: boolean;
  canPortal: boolean;
  canDelete: boolean;
}) {
  const m = useCatalog(studentsGuardiansMessages).edit;
  const detail = useGuardianDetail(guardian.guardian_id, open);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{guardian.full_name}</DialogTitle>
          <DialogDescription>{m.description}</DialogDescription>
        </DialogHeader>

        {detail.isPending ? (
          <div className="h-64 animate-pulse rounded-lg bg-muted" />
        ) : detail.isError ? (
          <p className="text-sm text-destructive">{m.loadFailed}</p>
        ) : (
          <Tabs defaultValue="details">
            <TabsList>
              <TabsTrigger value="details">{m.tabDetails}</TabsTrigger>
              <TabsTrigger value="child">{m.tabChild}</TabsTrigger>
              {canPortal ? <TabsTrigger value="signin">{m.tabSignIn}</TabsTrigger> : null}
              <TabsTrigger value="family">{m.tabFamily}</TabsTrigger>
            </TabsList>
            <TabsContent value="details" className="mt-4">
              <DetailsTab detail={detail.data} canUpdate={canUpdate} />
            </TabsContent>
            <TabsContent value="child" className="mt-4">
              <ChildTab
                guardian={guardian}
                detail={detail.data}
                studentId={studentId}
                canUpdate={canUpdate}
                canDelete={canDelete}
                onRemoved={() => onOpenChange(false)}
              />
            </TabsContent>
            {canPortal ? (
              <TabsContent value="signin" className="mt-4">
                <SignInTab detail={detail.data} />
              </TabsContent>
            ) : null}
            <TabsContent value="family" className="mt-4">
              <FamilyTab
                detail={detail.data}
                currentStudentId={studentId}
                defaultRelationship={guardian.relationship_type}
                canUpdate={canUpdate}
              />
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Details
// ---------------------------------------------------------------------------

function DetailsTab({ detail, canUpdate }: { detail: GuardianDetail; canUpdate: boolean }) {
  const m = useCatalog(studentsGuardiansMessages).details;
  const update = useUpdateGuardian();
  const [form, setForm] = React.useState(() => ({
    full_name: detail.full_name,
    email: detail.email ?? "",
    cnic: detail.cnic ?? "",
    occupation: detail.occupation ?? "",
    alternate_phone: detail.alternate_phone ?? "",
    address: detail.address ?? "",
    notes: detail.notes ?? "",
  }));

  const set = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [key]: event.target.value });

  const emailOk = !form.email.trim() || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim());
  const valid = form.full_name.trim().length > 0 && emailOk;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    // Blank means "clear it", so blanks go as null rather than "".
    const orNull = (value: string) => value.trim() || null;
    await update.mutateAsync({
      guardianId: detail.id,
      body: {
        full_name: form.full_name.trim(),
        email: orNull(form.email),
        cnic: orNull(form.cnic),
        occupation: orNull(form.occupation),
        alternate_phone: orNull(form.alternate_phone),
        address: orNull(form.address),
        notes: orNull(form.notes),
      },
    });
  }

  return (
    <form onSubmit={submit} className="grid gap-4" noValidate>
      <fieldset disabled={!canUpdate} className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label={m.fullName} value={form.full_name} onChange={set("full_name")} />
          <TextField
            label={m.email}
            type="email"
            value={form.email}
            onChange={set("email")}
            invalid={!emailOk}
          />
          <TextField label={m.cnic} value={form.cnic} onChange={set("cnic")} placeholder="35202-1234567-1" />
          <TextField label={m.occupation} value={form.occupation} onChange={set("occupation")} />
          <TextField
            label={m.otherPhone}
            type="tel"
            value={form.alternate_phone}
            onChange={set("alternate_phone")}
            hint={m.otherPhoneHint}
            ltr
          />
          <TextField label={m.address} value={form.address} onChange={set("address")} />
        </div>
        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">{m.notes}</span>
          <textarea
            value={form.notes}
            onChange={set("notes")}
            maxLength={1000}
            rows={3}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </label>
      </fieldset>
      {canUpdate ? (
        <div>
          <Button type="submit" loading={update.isPending} disabled={!valid}>
            {m.save}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{m.readOnly}</p>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// This child
// ---------------------------------------------------------------------------

function ChildTab({
  guardian,
  detail,
  studentId,
  canUpdate,
  canDelete,
  onRemoved,
}: {
  guardian: StudentGuardianRead;
  detail: GuardianDetail;
  studentId: string;
  canUpdate: boolean;
  canDelete: boolean;
  onRemoved: () => void;
}) {
  const m = useCatalog(studentsGuardiansMessages).child;
  const relationships = useRelationships();
  const updateLink = useUpdateGuardianLink();
  const unlink = useUnlinkGuardian();
  const [confirming, setConfirming] = React.useState(false);
  const [form, setForm] = React.useState(() => ({
    relationship_type: guardian.relationship_type,
    relationship_label: guardian.relationship_label ?? "",
    is_primary_contact: guardian.is_primary_contact,
    is_emergency_contact: guardian.is_emergency_contact,
    can_pickup: guardian.can_pickup,
    receives_notifications: guardian.receives_notifications,
  }));

  const labelMissing = form.relationship_type === "other" && !form.relationship_label.trim();
  // The record goes too only when this is the last child it is linked to.
  const lastChild = detail.students.length <= 1;
  const removeRecord = lastChild && canDelete;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (labelMissing) return;
    await updateLink.mutateAsync({
      guardianId: guardian.guardian_id,
      studentId,
      body: {
        relationship_type: form.relationship_type,
        relationship_label:
          form.relationship_type === "other" ? form.relationship_label.trim() : null,
        is_primary_contact: form.is_primary_contact,
        is_emergency_contact: form.is_emergency_contact,
        can_pickup: form.can_pickup,
        receives_notifications: form.receives_notifications,
      },
    });
  }

  const flag = (key: "is_primary_contact" | "is_emergency_contact" | "can_pickup" | "receives_notifications") =>
    ({
      checked: form[key],
      onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
        setForm({ ...form, [key]: event.target.checked }),
    });

  return (
    <div className="grid gap-5">
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <fieldset disabled={!canUpdate} className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm">
              <span className="font-medium">{m.relationship}</span>
              <NativeSelect
                value={form.relationship_type}
                onChange={(event) =>
                  setForm({ ...form, relationship_type: event.target.value as GuardianRelationship })
                }
              >
                {relationships.values.map((value) => (
                  <option key={value} value={value}>
                    {relationships.labels[value]}
                  </option>
                ))}
              </NativeSelect>
            </label>
            {form.relationship_type === "other" ? (
              <TextField
                label={m.describeIt}
                value={form.relationship_label}
                onChange={(event) => setForm({ ...form, relationship_label: event.target.value })}
                placeholder={m.relationshipPlaceholder}
                invalid={labelMissing}
              />
            ) : null}
          </div>

          <div className="grid gap-2.5 rounded-lg border border-border p-4 text-sm">
            <Check label={m.primaryContact} hint={m.primaryContactHint} {...flag("is_primary_contact")} />
            <Check label={m.emergencyContact} {...flag("is_emergency_contact")} />
            <Check label={m.canPickup} {...flag("can_pickup")} />
            <Check
              label={m.receivesMessages}
              hint={m.receivesMessagesHint}
              {...flag("receives_notifications")}
            />
          </div>
        </fieldset>
        {canUpdate ? (
          <div>
            <Button type="submit" loading={updateLink.isPending} disabled={labelMissing}>
              {m.save}
            </Button>
          </div>
        ) : null}
      </form>

      {canUpdate ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
          <p className="text-xs text-muted-foreground">
            {lastChild
              ? removeRecord
                ? m.onlyChildDeletes
                : m.onlyChildKeeps
              : fill(detail.students.length - 1 === 1 ? m.otherChildrenOne : m.otherChildrenMany, {
                  count: detail.students.length - 1,
                })}
          </p>
          <Button variant="ghost" onClick={() => setConfirming(true)}>
            <Trash2 className="size-4" aria-hidden />
            {m.removeFromStudent}
          </Button>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={fill(m.removeTitle, { name: guardian.full_name })}
        description={removeRecord ? m.removeDeletes : m.removeKeeps}
        confirmLabel={m.remove}
        variant="destructive"
        loading={unlink.isPending}
        onConfirm={async () => {
          await unlink.mutateAsync({
            guardianId: guardian.guardian_id,
            studentId,
            removeRecord,
          });
          setConfirming(false);
          onRemoved();
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sign-in
// ---------------------------------------------------------------------------

function SignInTab({ detail }: { detail: GuardianDetail }) {
  const m = useCatalog(studentsGuardiansMessages).signIn;
  const changePhone = useChangeGuardianPhone();
  const setPortal = useSetGuardianPortal();
  const [phone, setPhone] = React.useState("");
  const [confirmingPhone, setConfirmingPhone] = React.useState(false);
  const [confirmingClose, setConfirmingClose] = React.useState(false);

  const digits = phone.replace(/\D/g, "");
  const validPhone = digits.length >= 7 && digits.length <= 15;

  return (
    <div className="grid gap-5">
      <div className="grid gap-3 rounded-lg border border-border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-sm font-medium">{m.number}</p>
            <p className="text-sm tabular-nums" dir="ltr">
              {detail.phone}
            </p>
          </div>
          <Badge variant={detail.portal_enabled ? "success" : "neutral"}>
            {detail.portal_enabled ? m.portalOpen : m.portalClosed}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          {detail.last_login_at
            ? fill(m.lastSignedIn, { when: new Date(detail.last_login_at).toLocaleString() })
            : m.neverSignedIn}
        </p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (validPhone) setConfirmingPhone(true);
        }}
        className="grid gap-2"
      >
        <label className="grid gap-1.5 text-sm">
          <span className="font-medium">{m.changeLabel}</span>
          <div className="flex flex-wrap gap-2">
            <Input
              type="tel"
              dir="ltr"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="0300-1234567"
              className="max-w-xs"
            />
            <Button type="submit" variant="outline" disabled={!validPhone}>
              {m.change}
            </Button>
          </div>
        </label>
        <p className="text-xs text-muted-foreground">{m.changeHelp}</p>
      </form>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p className="max-w-md text-xs text-muted-foreground">
          {detail.portal_enabled ? m.closeHelp : m.closedHelp}
        </p>
        {detail.portal_enabled ? (
          <Button variant="outline" onClick={() => setConfirmingClose(true)}>
            {m.close}
          </Button>
        ) : (
          <Button
            variant="outline"
            loading={setPortal.isPending}
            onClick={() => setPortal.mutate({ guardianId: detail.id, enabled: true })}
          >
            {m.open}
          </Button>
        )}
      </div>

      <ConfirmDialog
        open={confirmingPhone}
        onOpenChange={setConfirmingPhone}
        title={m.changeTitle}
        description={fillNodes(m.changeDescription, {
          phone: (
            <span dir="ltr" className="font-medium">
              {phone}
            </span>
          ),
          name: detail.full_name,
        })}
        confirmLabel={m.change}
        loading={changePhone.isPending}
        onConfirm={async () => {
          await changePhone.mutateAsync({ guardianId: detail.id, phone: phone.trim() });
          setConfirmingPhone(false);
          setPhone("");
        }}
      />
      <ConfirmDialog
        open={confirmingClose}
        onOpenChange={setConfirmingClose}
        title={m.closeTitle}
        description={m.closeDescription}
        confirmLabel={m.close}
        variant="destructive"
        loading={setPortal.isPending}
        onConfirm={async () => {
          await setPortal.mutateAsync({ guardianId: detail.id, enabled: false });
          setConfirmingClose(false);
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Family
// ---------------------------------------------------------------------------

function FamilyTab({
  detail,
  currentStudentId,
  defaultRelationship,
  canUpdate,
}: {
  detail: GuardianDetail;
  currentStudentId: string;
  defaultRelationship: GuardianRelationship;
  canUpdate: boolean;
}) {
  const m = useCatalog(studentsGuardiansMessages).family;
  const relationships = useRelationships();
  const link = useLinkGuardian();
  const [query, setQuery] = React.useState("");
  const [relationship, setRelationship] = React.useState<GuardianRelationship>(
    defaultRelationship === "other" ? "father" : defaultRelationship,
  );
  const debounced = useDebouncedValue(query.trim());
  const results = useStudents({ q: debounced, size: 6 });
  const linkedIds = new Set(detail.students.map((student) => student.student_id));
  const candidates = debounced.length >= 2
    ? (results.data?.items ?? []).filter((student) => !linkedIds.has(student.id))
    : [];

  return (
    <div className="grid gap-5">
      <div className="grid gap-2">
        <p className="text-sm font-medium">{fill(m.childrenOf, { name: detail.full_name })}</p>
        <ul className="grid gap-2">
          {detail.students.map((student) => (
            <li
              key={student.link_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-sm"
            >
              <div className="min-w-0">
                {student.student_id === currentStudentId ? (
                  <span className="font-medium">{student.full_name}</span>
                ) : (
                  <Link href={`/students/${student.student_id}`} className="font-medium hover:underline">
                    {student.full_name}
                  </Link>
                )}
                <span className="ms-2 text-xs text-muted-foreground">
                  {student.admission_number} · {relationships.labels[student.relationship_type]}
                </span>
              </div>
              {student.student_id === currentStudentId ? (
                <Badge variant="neutral">{m.thisStudent}</Badge>
              ) : null}
            </li>
          ))}
        </ul>
      </div>

      {canUpdate ? (
        <div className="grid gap-3 rounded-lg border border-dashed border-border p-4">
          <div>
            <p className="text-sm font-medium">{m.linkSibling}</p>
            <p className="text-xs text-muted-foreground">{m.linkSiblingHint}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-52 flex-1">
              <Search
                className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={m.searchPlaceholder}
                className="ps-9"
                aria-label={m.searchLabel}
              />
            </div>
            <NativeSelect
              value={relationship}
              onChange={(event) => setRelationship(event.target.value as GuardianRelationship)}
              className="w-40"
              aria-label={m.relationshipToChild}
            >
              {relationships.values
                .filter((value) => value !== "other")
                .map((value) => (
                  <option key={value} value={value}>
                    {relationships.labels[value]}
                  </option>
                ))}
            </NativeSelect>
          </div>
          {debounced.length >= 2 ? (
            results.isPending ? (
              <p className="text-xs text-muted-foreground">{m.searching}</p>
            ) : candidates.length === 0 ? (
              <p className="text-xs text-muted-foreground">{m.noMatches}</p>
            ) : (
              <ul className="grid gap-1.5">
                {candidates.map((student) => (
                  <li
                    key={student.id}
                    className="flex items-center justify-between gap-2 rounded-md bg-muted/40 px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 truncate">
                      {student.full_name}
                      <span className="ms-2 text-xs text-muted-foreground">
                        {student.admission_number}
                        {student.class_name ? ` · ${student.class_name}` : ""}
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      loading={link.isPending && link.variables?.body.student_id === student.id}
                      onClick={() =>
                        link.mutate({
                          guardianId: detail.id,
                          studentName: student.full_name,
                          body: {
                            student_id: student.id,
                            relationship_type: relationship,
                            receives_notifications: true,
                            can_view_results: true,
                          },
                        })
                      }
                    >
                      <Link2 className="size-4" aria-hidden />
                      {m.link}
                    </Button>
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small pieces
// ---------------------------------------------------------------------------

function TextField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  hint,
  invalid,
  ltr,
}: {
  label: string;
  value: string;
  onChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  type?: string;
  placeholder?: string;
  hint?: string;
  invalid?: boolean;
  ltr?: boolean;
}) {
  return (
    <label className="grid gap-1.5 text-sm">
      <span className="font-medium">{label}</span>
      <Input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        aria-invalid={invalid || undefined}
        dir={ltr ? "ltr" : undefined}
      />
      {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
    </label>
  );
}

function Check({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="flex items-start gap-2.5">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="mt-0.5 size-4 rounded border-input"
      />
      <span>
        {label}
        {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      </span>
    </label>
  );
}
