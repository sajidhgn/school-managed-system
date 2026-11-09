"use client";

import * as React from "react";
import { Check, Copy, MessageCircle, Pencil, Plus } from "lucide-react";

import { Field } from "@/components/form/field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { fillNodes } from "@/lib/i18n/format";
import { GuardianEditDialog } from "./guardian-edit-dialog";
import {
  useGrantPortalAccess,
  useSetChildPortalAccess,
  useStudentGuardians,
} from "@/hooks/use-guardians";
import type { GuardianRelationship, StudentGuardianRead, StudentRead } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { studentsGuardiansMessages } from "@/lib/i18n/modules/students-guardians";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { useLabels } from "@/lib/i18n/use-labels";

/**
 * Who may sign in to the parent portal for this child.
 *
 * =============================================================================
 * A PERSON TURNS ACCESS ON. THE PHONE FIELD NEVER DOES IT BY ITSELF.
 * =============================================================================
 *   The guardian phone on the student form is free text: a landline, a sibling's
 *   number, a typo. Turning every one of those into a login would hand some
 *   stranger this child's records. So the number on the record is offered here,
 *   prefilled, and access starts only when a member of staff confirms it.
 *
 *   The parent then opens /parent on their phone and gets a code on WhatsApp from
 *   this campus's own number. A number with no WhatsApp gets no code.
 */

/** The last ten digits: enough to tell `0300-1234567` and `+923001234567` are one number. */
function phoneKey(phone: string | null | undefined): string {
  return (phone ?? "").replace(/\D/g, "").slice(-10);
}

export function ParentPortalCard({
  student,
  canGrant,
  canToggle,
  canPortal,
  canDelete,
}: {
  student: StudentRead;
  /** `guardian:create` and `guardian:update`. */
  canGrant: boolean;
  /** `guardian:update`: turning one child's access off and on, and editing the parent. */
  canToggle: boolean;
  /** `guardian:portal`: the sign-in number and the portal switch. */
  canPortal: boolean;
  /** `guardian:delete`: removing a record once its last child is unlinked. */
  canDelete: boolean;
}) {
  const m = useCatalog(studentsGuardiansMessages).portal;
  const query = useStudentGuardians(student.id);
  const guardians = query.data ?? [];

  // The number already on the student's record, unless it already has a login here.
  const recordPhoneLinked =
    !!student.guardian_phone &&
    guardians.some((g) => phoneKey(g.phone) === phoneKey(student.guardian_phone));
  const suggestion =
    student.guardian_phone && !recordPhoneLinked
      ? { name: student.guardian_name ?? "", phone: student.guardian_phone }
      : null;

  const [adding, setAdding] = React.useState(false);
  const showForm = canGrant && (adding || (query.isSuccess && guardians.length === 0));

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <CardTitle>{m.title}</CardTitle>
        <CopyPortalLink />
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          {fillNodes(m.intro, {
            path: (
              <bdi className="font-medium text-foreground" dir="ltr">
                /parent
              </bdi>
            ),
          })}
        </p>

        {query.isLoading ? (
          <p className="text-sm text-muted-foreground">{m.loading}</p>
        ) : query.isError ? (
          <p className="text-sm text-destructive">{m.loadFailed}</p>
        ) : (
          <ul className="space-y-3">
            {guardians.map((guardian) => (
              <GuardianRow
                key={guardian.link_id}
                guardian={guardian}
                studentId={student.id}
                canToggle={canToggle}
                canPortal={canPortal}
                canDelete={canDelete}
              />
            ))}
          </ul>
        )}

        {showForm ? (
          <GrantForm
            key={suggestion?.phone ?? "blank"}
            studentId={student.id}
            initialName={suggestion?.name ?? ""}
            initialPhone={suggestion?.phone ?? ""}
            fromRecord={!!suggestion}
            onDone={() => setAdding(false)}
            onCancel={guardians.length > 0 ? () => setAdding(false) : undefined}
          />
        ) : canGrant && query.isSuccess ? (
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            <Plus />
            {suggestion
              ? fill(m.giveAccessTo, { name: suggestion.name || suggestion.phone })
              : m.addParent}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function GuardianRow({
  guardian,
  studentId,
  canToggle,
  canPortal,
  canDelete,
}: {
  guardian: StudentGuardianRead;
  studentId: string;
  canToggle: boolean;
  canPortal: boolean;
  canDelete: boolean;
}) {
  const m = useCatalog(studentsGuardiansMessages).portal;
  const L = useLabels();
  const toggle = useSetChildPortalAccess(studentId);
  const [editing, setEditing] = React.useState(false);
  const canSignIn = guardian.can_view_results && guardian.portal_enabled;
  const relationship =
    guardian.relationship_type === "other"
      ? guardian.relationship_label
      : L.relationship[guardian.relationship_type];

  return (
    <li className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{guardian.full_name}</p>
          <p className="text-xs text-muted-foreground">
            {[relationship, guardian.is_primary_contact ? m.primaryContact : null]
              .filter(Boolean)
              .join(" · ")}
          </p>
          <p className="mt-0.5 text-sm tabular-nums" dir="ltr">
            {guardian.phone}
          </p>
        </div>
        <Badge variant={canSignIn ? "success" : "neutral"}>
          {canSignIn ? m.canSignIn : m.off}
        </Badge>
      </div>

      {!guardian.portal_enabled ? (
        <p className="text-xs text-muted-foreground">{m.portalOffByAdmin}</p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {guardian.portal_enabled && canToggle ? (
          <Button
            variant="outline"
            size="sm"
            loading={toggle.isPending}
            onClick={() =>
              toggle.mutate({ guardianId: guardian.guardian_id, canView: !guardian.can_view_results })
            }
          >
            {guardian.can_view_results ? m.turnOff : m.turnOn}
          </Button>
        ) : null}
        <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
          <Pencil />
          {canToggle || canPortal ? m.edit : m.view}
        </Button>
      </div>

      {editing ? (
        <GuardianEditDialog
          open={editing}
          onOpenChange={setEditing}
          guardian={guardian}
          studentId={studentId}
          canUpdate={canToggle}
          canPortal={canPortal}
          canDelete={canDelete}
        />
      ) : null}
    </li>
  );
}

function GrantForm({
  studentId,
  initialName,
  initialPhone,
  fromRecord,
  onDone,
  onCancel,
}: {
  studentId: string;
  initialName: string;
  initialPhone: string;
  fromRecord: boolean;
  onDone: () => void;
  onCancel?: () => void;
}) {
  const m = useCatalog(studentsGuardiansMessages).grant;
  const L = useLabels();
  const relationships = Object.keys(L.relationship) as GuardianRelationship[];
  const grant = useGrantPortalAccess(studentId);
  const [name, setName] = React.useState(initialName);
  const [phone, setPhone] = React.useState(initialPhone);
  const [relationship, setRelationship] = React.useState<GuardianRelationship | "">("");
  const [label, setLabel] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!name.trim() || phone.replace(/\D/g, "").length < 7 || !relationship) {
      setError(m.missingFields);
      return;
    }
    if (relationship === "other" && !label.trim()) {
      setError(m.describeRelationship);
      return;
    }
    try {
      await grant.mutateAsync({
        full_name: name.trim(),
        phone: phone.trim(),
        relationship_type: relationship,
        relationship_label: relationship === "other" ? label.trim() : null,
      });
      onDone();
    } catch {
      // The hook already showed the server's reason in a toast.
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3 rounded-lg border border-dashed border-border p-3">
      <p className="text-sm font-medium">
        {fromRecord ? m.fromRecordTitle : m.newTitle}
      </p>
      <Field label={m.parentName} htmlFor="portal_name">
        <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
      </Field>
      <Field label={m.whatsappNumber} htmlFor="portal_phone" hint={m.whatsappHint}>
        <Input
          type="tel"
          dir="ltr"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="0300-1234567"
          autoComplete="off"
        />
      </Field>
      <Field label={m.relationship} htmlFor="portal_relationship">
        <NativeSelect
          value={relationship}
          onChange={(e) => setRelationship(e.target.value as GuardianRelationship | "")}
        >
          <option value="" disabled>
            {m.choose}
          </option>
          {relationships.map((value) => (
            <option key={value} value={value}>
              {L.relationship[value]}
            </option>
          ))}
        </NativeSelect>
      </Field>
      {relationship === "other" ? (
        <Field label={m.relationshipToStudent} htmlFor="portal_label">
          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={m.relationshipPlaceholder}
          />
        </Field>
      ) : null}
      {error ? <p className="text-xs font-medium text-destructive">{error}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" loading={grant.isPending}>
          <MessageCircle />
          {m.submit}
        </Button>
        {onCancel ? (
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            {m.cancel}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

/** Copies the full sign-in link, ready to paste into a WhatsApp chat with the parent. */
function CopyPortalLink() {
  const m = useCatalog(studentsGuardiansMessages).portal;
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/parent/login`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked (insecure origin or permission): nothing useful to do.
    }
  }

  return (
    <Button variant="ghost" size="sm" onClick={copy}>
      {copied ? <Check /> : <Copy />}
      {copied ? m.copied : m.copyLink}
    </Button>
  );
}
