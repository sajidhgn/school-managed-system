"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState, PageSpinner } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { StudentStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useClassSummary } from "@/hooks/use-classes";
import { useDeleteStudent, useStudent } from "@/hooks/use-students";
import { GENDER_LABELS } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/utils";
import { StudentFormDialog } from "../student-form-dialog";

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

export function StudentDetailView({
  studentId,
  canManage,
}: {
  studentId: string;
  canManage: boolean;
}) {
  const router = useRouter();
  const query = useStudent(studentId);
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

  async function onConfirmDelete() {
    await deleteStudent.mutateAsync(studentId);
    setConfirmDelete(false);
    router.push("/students");
  }

  return (
    <>
      <Link
        href="/students"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        All students
      </Link>

      <PageHeader
        title={student.full_name}
        description={`Admission number ${student.admission_number}`}
        actions={
          canManage ? (
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
          ) : null
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
              <Detail
                label="Class & section"
                value={
                  placement ? `${placement.cls.name} — ${placement.section.name}` : "Unassigned"
                }
              />
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
    </>
  );
}
