"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Check, ChevronDown, Pencil, Trash2 } from "lucide-react";

import { StudentFeesPanel } from "./student-fees-panel";
import { StudentFormDialog } from "../student-form-dialog";
import { STUDENTS_LIST_QUERY_KEY } from "../students-view";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, PageSpinner } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { StudentStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useClassSummary } from "@/hooks/use-classes";
import { useDeleteStudent, useStudent, useUpdateStudent } from "@/hooks/use-students";
import {
  GENDER_LABELS,
  STUDENT_STATUS_LABELS,
  label as labelFor,
  type StudentRead,
  type StudentStatus,
} from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/utils";

/**
 * One student, whole.
 *
 * =============================================================================
 * THIS IS THE PAGE SEARCH LANDS ON, SO IT HAS TO ANSWER THE QUESTION
 * =============================================================================
 *   Someone types a name into ⌘K because a parent is standing in front of them.
 *   What they need next is almost never "the profile" — it is which class the child
 *   is in, what is owed, and the ability to take the money without navigating
 *   anywhere else. A page that shows only the record and makes them go hunt the fees
 *   register for the rest turns a thirty-second counter interaction into three.
 *
 *   So everything lives here: identity, placement, guardians, the fee ledger, and
 *   the actions that change any of them. Nothing on this page is a read-only mirror
 *   of a screen that holds the real controls.
 *
 * WHERE THE CONTROLS COME FROM
 *   Editing goes through the same `StudentFormDialog` the directory uses, so the two
 *   can never drift field-by-field. Fees go through the same mutations the challan
 *   screen fires, guarded by the same permissions. The only thing this page adds is
 *   the status menu, which is a one-field PATCH of the form dialog's status field —
 *   put in the header because "this child has left" is a single decision, and making
 *   someone open a fifteen-field form to record it is how records go stale.
 *
 * PERMISSIONS ARE PROPS, RESOLVED SERVER-SIDE
 *   This component never reads a permission code. `page.tsx` resolves them from the
 *   session and hands down booleans, so a control that must not exist is not rendered
 *   rather than rendered-and-disabled.
 */

/** Label/value row. Falls back to an em dash so empty fields stay aligned. */
function Detail({ label, value }: { label: string; value?: React.ReactNode }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="text-sm">{value || "—"}</dd>
    </div>
  );
}

/**
 * Where "All students" goes back to.
 *
 * The directory keeps its search and filters in the query string and leaves a copy
 * in session storage, so leaving this page returns to the list the way the user
 * left it rather than to an unfiltered page one — the same thing the browser's Back
 * button now does. Read after mount, never during render: the server has no session
 * storage and a differing first paint is a hydration mismatch.
 */
function useStudentsListHref(): Route {
  const [href, setHref] = React.useState("/students" as Route);

  React.useEffect(() => {
    try {
      const query = sessionStorage.getItem(STUDENTS_LIST_QUERY_KEY);
      if (query) setHref(`/students?${query}` as Route);
    } catch {
      // Storage unavailable — the unfiltered directory is a fine answer.
    }
  }, []);

  return href;
}

export function StudentDetailView({
  studentId,
  canManage,
  canReadFees,
  canManageFees,
  canIssue,
  canCollect,
  canVoid,
}: {
  studentId: string;
  canManage: boolean;
  canReadFees: boolean;
  canManageFees: boolean;
  canIssue: boolean;
  canCollect: boolean;
  canVoid: boolean;
}) {
  const router = useRouter();
  const query = useStudent(studentId);
  const listHref = useStudentsListHref();
  const { data: classes } = useClassSummary();
  const deleteStudent = useDeleteStudent();

  const [editOpen, setEditOpen] = React.useState(false);
  const [confirmDelete, setConfirmDelete] = React.useState(false);

  if (query.isLoading) return <PageSpinner />;
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  const student = query.data;
  if (!student) return null;

  // Resolve the section UUID to a human label via the class summary.
  const placement = (classes ?? [])
    .flatMap((cls) => cls.sections.map((section) => ({ cls, section })))
    .find(({ section }) => section.id === student.section_id);
  const placementLabel = placement
    ? `${placement.cls.name} — ${placement.section.name}`
    : "Unassigned";

  async function onConfirmDelete() {
    await deleteStudent.mutateAsync(studentId);
    setConfirmDelete(false);
    router.push(listHref);
  }

  return (
    <div className="mx-auto w-full max-w-6xl">
      <Link
        href={listHref}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        All students
      </Link>

      <PageHeader
        title={student.full_name}
        description={`Admission ${student.admission_number} · ${placementLabel}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {canManage ? (
              <StatusMenu student={student} />
            ) : (
              <StudentStatusBadge status={student.status} />
            )}
            {canManage ? (
              <>
                <Button variant="outline" onClick={() => setEditOpen(true)}>
                  <Pencil />
                  Edit
                </Button>
                <Button variant="outline" onClick={() => setConfirmDelete(true)}>
                  <Trash2 />
                  Remove
                </Button>
              </>
            ) : null}
          </div>
        }
      />

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Student details</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-5 sm:grid-cols-2">
              <Detail label="First name" value={student.first_name} />
              <Detail label="Last name" value={student.last_name} />
              <Detail label="Date of birth" value={formatDate(student.date_of_birth)} />
              <Detail
                label="Gender"
                value={student.gender ? GENDER_LABELS[student.gender] : null}
              />
              <Detail
                label="Status"
                value={<StudentStatusBadge status={student.status} />}
              />
              <Detail label="Enrolled on" value={formatDate(student.enrolled_on)} />
              <Detail label="Class & section" value={placementLabel} />
              <Detail label="Admission number" value={student.admission_number} />
              <Detail label="Address" value={student.address} />
            </dl>
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Guardian</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-4">
                <Detail label="Name" value={student.guardian_name} />
                <Detail
                  label="Phone"
                  value={
                    student.guardian_phone ? (
                      <a href={`tel:${student.guardian_phone}`} className="hover:underline">
                        {student.guardian_phone}
                      </a>
                    ) : null
                  }
                />
                <Detail
                  label="Email"
                  value={
                    student.guardian_email ? (
                      <a
                        href={`mailto:${student.guardian_email}`}
                        className="break-all hover:underline"
                      >
                        {student.guardian_email}
                      </a>
                    ) : null
                  }
                />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Emergency contact</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-4">
                <Detail label="Name" value={student.emergency_contact_name} />
                <Detail
                  label="Phone"
                  value={
                    student.emergency_contact_phone ? (
                      <a
                        href={`tel:${student.emergency_contact_phone}`}
                        className="hover:underline"
                      >
                        {student.emergency_contact_phone}
                      </a>
                    ) : null
                  }
                />
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Record</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="space-y-4">
                <Detail label="Created" value={formatDateTime(student.created_at)} />
                <Detail label="Last updated" value={formatDateTime(student.updated_at)} />
              </dl>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* --- The money -----------------------------------------------------
          Gated on `fee:read`, not on `student:read`. A class teacher can open this
          page and must not see what a family owes; an accountant sees it without
          being able to touch the record above. */}
      {canReadFees ? (
        <StudentFeesPanel
          studentId={student.id}
          studentName={student.full_name}
          classId={placement?.cls.id}
          className={placement?.cls.name}
          canManageFees={canManageFees}
          canIssue={canIssue}
          canCollect={canCollect}
          canVoid={canVoid}
        />
      ) : null}

      {canManage ? (
        <>
          <StudentFormDialog open={editOpen} onOpenChange={setEditOpen} student={student} />
          <ConfirmDialog
            open={confirmDelete}
            onOpenChange={setConfirmDelete}
            title="Remove student?"
            description={
              <>
                <span className="font-medium text-foreground">{student.full_name}</span> will be
                removed from the directory. This cannot be undone.
              </>
            }
            confirmLabel="Remove student"
            loading={deleteStudent.isPending}
            onConfirm={onConfirmDelete}
          />
        </>
      ) : null}
    </div>
  );
}

/**
 * Change the enrollment status without opening the whole form.
 *
 * The values come from `STUDENT_STATUS_LABELS`, which is the same open-ended map the
 * badge renders from — a status added on the backend appears here without a frontend
 * change, rather than silently missing from the menu that is supposed to set it.
 *
 * PATCHes one field. `useUpdateStudent` already writes the response into the detail
 * cache and invalidates the lists and the class rollups, because a child moving to
 * "transferred" changes a headcount somebody else is reading.
 */
function StatusMenu({ student }: { student: StudentRead }) {
  const update = useUpdateStudent();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" disabled={update.isPending}>
          <StudentStatusBadge status={student.status} />
          <ChevronDown className="size-3.5" aria-hidden />
          <span className="sr-only">Change enrollment status</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Enrollment status</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {Object.keys(STUDENT_STATUS_LABELS).map((value) => (
          <DropdownMenuItem
            key={value}
            disabled={value === student.status || update.isPending}
            onSelect={() =>
              update.mutate({ id: student.id, body: { status: value as StudentStatus } })
            }
          >
            {value === student.status ? (
              <Check className="size-4" aria-hidden />
            ) : (
              <span className="size-4" aria-hidden />
            )}
            {labelFor(STUDENT_STATUS_LABELS, value)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
