"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Check, Copy, ExternalLink, Inbox, UserCheck, X } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useClassSummary } from "@/hooks/use-classes";
import { useAdmitApplicant, useDeclineApplicant, useStudents } from "@/hooks/use-students";
import { label, type StudentListRow } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { studentsMessages } from "@/lib/i18n/modules/students";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { useLabels } from "@/lib/i18n/use-labels";
import { formatDate } from "@/lib/utils";

const PAGE_SIZE = 20;

/**
 * Applications waiting for a decision, oldest first.
 *
 * =============================================================================
 * A QUEUE, NOT A FILTER
 * =============================================================================
 *   The directory can already be filtered to "Pending", but a filter only shows the
 *   applicants; it does not say what to do with them. Here each row has the two
 *   decisions a school actually makes — admit (and where to seat them) or decline —
 *   and the oldest application is at the top, because a family that applied three
 *   weeks ago has waited longest.
 *
 * ADMITTING TAKES A PLAN SEAT
 *   A pending application consumes nothing. Admitting turns the child ACTIVE, and that
 *   is when the plan's student limit applies — so a full plan refuses here (402) with
 *   the reason in the toast, not silently.
 *
 * DECLINING IS A SOFT DELETE
 *   The application leaves the directory, but the record and its audit trail remain.
 */
export function AdmissionsView({
  schoolId,
  canAdmit,
  canDecline,
}: {
  schoolId: string;
  canAdmit: boolean;
  canDecline: boolean;
}) {
  const m = useCatalog(studentsMessages).queue;
  const L = useLabels();
  const [page, setPage] = React.useState(1);
  const [admitting, setAdmitting] = React.useState<StudentListRow | null>(null);
  const [declining, setDeclining] = React.useState<StudentListRow | null>(null);
  const decline = useDeclineApplicant();

  const applicants = useStudents({
    status: "pending",
    page,
    size: PAGE_SIZE,
    sort_by: "created_at",
    sort_dir: "asc",
  });

  return (
    <div className="mx-auto w-full max-w-6xl">
      <Link
        href="/students"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden />
        {m.back}
      </Link>

      <PageHeader
        title={m.title}
        description={m.description}
        actions={<FormLinkActions schoolId={schoolId} />}
      />

      <Card className="overflow-hidden p-0">
        {applicants.isPending ? (
          <TableCardSkeleton columns={5} />
        ) : applicants.isError ? (
          <ErrorState error={applicants.error} onRetry={() => void applicants.refetch()} />
        ) : applicants.data.items.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title={m.emptyTitle}
            description={m.emptyHint}
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colApplicant}</TableHead>
                  <TableHead>{m.colDateOfBirth}</TableHead>
                  <TableHead>{m.colParent}</TableHead>
                  <TableHead>{m.colApplied}</TableHead>
                  <TableHead className="text-end">{m.colDecision}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {applicants.data.items.map((applicant) => (
                  <TableRow key={applicant.id}>
                    <TableCell>
                      <Link
                        href={`/students/${applicant.id}`}
                        className="font-medium hover:text-primary hover:underline"
                      >
                        {applicant.full_name}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        {applicant.admission_number}
                        {applicant.gender ? ` · ${label(L.gender, applicant.gender)}` : ""}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {applicant.date_of_birth ? formatDate(applicant.date_of_birth) : "—"}
                    </TableCell>
                    <TableCell className="text-sm">
                      {applicant.guardian_name ?? "—"}
                      {applicant.guardian_phone ? (
                        <a
                          href={`tel:${applicant.guardian_phone}`}
                          className="block text-xs text-muted-foreground hover:underline"
                          dir="ltr"
                        >
                          {applicant.guardian_phone}
                        </a>
                      ) : null}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {formatDate(applicant.created_at)}
                    </TableCell>
                    <TableCell className="text-end">
                      <div className="flex justify-end gap-2">
                        {canDecline ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDeclining(applicant)}
                          >
                            <X className="size-4" aria-hidden />
                            {m.decline}
                          </Button>
                        ) : null}
                        {canAdmit ? (
                          <Button size="sm" onClick={() => setAdmitting(applicant)}>
                            <UserCheck className="size-4" aria-hidden />
                            {m.admit}
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      {applicants.data ? (
        <div className="mt-4">
          <Pagination
            meta={applicants.data.meta}
            onPageChange={setPage}
            disabled={applicants.isFetching}
          />
        </div>
      ) : null}

      {canAdmit ? (
        <AdmitDialog applicant={admitting} onClose={() => setAdmitting(null)} />
      ) : null}

      <ConfirmDialog
        open={declining !== null}
        onOpenChange={(open) => !open && setDeclining(null)}
        title={
          declining
            ? fill(m.declineTitle, { name: declining.full_name })
            : m.declineTitleFallback
        }
        description={m.declineDescription}
        confirmLabel={m.declineConfirm}
        variant="destructive"
        loading={decline.isPending}
        onConfirm={async () => {
          if (!declining) return;
          await decline.mutateAsync(declining.id);
          setDeclining(null);
        }}
      />
    </div>
  );
}

/** Local date, not UTC: an admission dated "yesterday" after 7pm in Karachi is wrong. */
function localToday(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

/**
 * Admit one applicant, optionally choosing their section now.
 *
 * The section is optional because a school often admits before timetabling: the
 * child is accepted in March and seated in a section in August. Sections at capacity
 * are shown but disabled, with the count, so nobody picks one the API will refuse.
 */
function AdmitDialog({
  applicant,
  onClose,
}: {
  applicant: StudentListRow | null;
  onClose: () => void;
}) {
  const m = useCatalog(studentsMessages).queue;
  const classes = useClassSummary();
  const admit = useAdmitApplicant();
  const [sectionId, setSectionId] = React.useState("");
  const [enrolledOn, setEnrolledOn] = React.useState(localToday);

  React.useEffect(() => {
    if (applicant) {
      setSectionId("");
      setEnrolledOn(localToday());
    }
  }, [applicant]);

  const sortedClasses = [...(classes.data ?? [])].sort((a, b) => a.level - b.level);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!applicant || !enrolledOn) return;
    await admit.mutateAsync({ id: applicant.id, sectionId: sectionId || null, enrolledOn });
    onClose();
  }

  return (
    <Dialog open={applicant !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{fill(m.admitTitle, { name: applicant?.full_name ?? "" })}</DialogTitle>
            <DialogDescription>{m.admitDescription}</DialogDescription>
          </DialogHeader>

          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">{m.classAndSection}</span>
            <NativeSelect value={sectionId} onChange={(event) => setSectionId(event.target.value)}>
              <option value="">{m.chooseLater}</option>
              {sortedClasses.map((cls) => (
                <optgroup key={cls.id} label={cls.name}>
                  {cls.sections.map((section) => {
                    const full =
                      section.capacity !== null && section.student_count >= section.capacity;
                    return (
                      <option key={section.id} value={section.id} disabled={full}>
                        {section.capacity !== null
                          ? fill(full ? m.sectionOptionFull : m.sectionOption, {
                              class: cls.name,
                              section: section.name,
                              count: section.student_count,
                              capacity: section.capacity,
                            })
                          : fill(m.sectionOptionUncapped, {
                              class: cls.name,
                              section: section.name,
                              count: section.student_count,
                            })}
                      </option>
                    );
                  })}
                </optgroup>
              ))}
            </NativeSelect>
            {classes.data && classes.data.length === 0 ? (
              <span className="text-xs text-muted-foreground">{m.noClasses}</span>
            ) : null}
          </label>

          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">{m.admissionDate}</span>
            <Input
              type="date"
              value={enrolledOn}
              onChange={(event) => setEnrolledOn(event.target.value)}
              required
            />
          </label>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {m.cancel}
            </Button>
            <Button type="submit" loading={admit.isPending} disabled={!enrolledOn}>
              <UserCheck className="size-4" aria-hidden />
              {m.admit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The public form's address, ready to paste into a WhatsApp message to families. */
function FormLinkActions({ schoolId }: { schoolId: string }) {
  const m = useCatalog(studentsMessages).queue;
  const [copied, setCopied] = React.useState(false);
  const path = `/admissions/${schoolId}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${path}`);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked (insecure origin or permission): the Open link still works.
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" onClick={copy}>
        {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
        {copied ? m.copied : m.copyFormLink}
      </Button>
      <Button variant="outline" asChild>
        <a href={path} target="_blank" rel="noreferrer">
          <ExternalLink className="size-4" aria-hidden />
          {m.openForm}
        </a>
      </Button>
    </div>
  );
}
