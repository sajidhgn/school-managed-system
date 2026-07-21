"use client";

import * as React from "react";
import Link from "next/link";
import { Check, PartyPopper, X } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useStudents, useUpdateStudent } from "@/hooks/use-students";
import type { StudentRead } from "@/lib/api/types";
import { formatDate } from "@/lib/utils";

const PAGE_SIZE = 20;

type Decision = { student: StudentRead; action: "approve" | "reject" };

/**
 * Review queue for public admissions applications.
 *
 * Every row here is a family waiting on an answer, so both outcomes are
 * confirmed — a mis-click on "Reject" is not recoverable from this screen.
 */
export function AdmissionsQueueView() {
  const [page, setPage] = React.useState(1);
  const [decision, setDecision] = React.useState<Decision | null>(null);

  const updateStudent = useUpdateStudent();

  const query = useStudents({
    status: "pending",
    page,
    size: PAGE_SIZE,
    // Oldest first: the family that has waited longest gets seen first.
    sort_by: "created_at",
    sort_dir: "asc",
  });

  const applications = query.data?.items ?? [];
  const meta = query.data?.meta;

  async function confirmDecision() {
    if (!decision) return;
    await updateStudent.mutateAsync({
      id: decision.student.id,
      body: { status: decision.action === "approve" ? "active" : "inactive" },
    });
    // The mutation invalidates the list, so the row leaves the queue on its own.
    setDecision(null);

    // Approving the last row on a page would otherwise strand the user on an
    // empty page N.
    if (applications.length === 1 && page > 1) setPage(page - 1);
  }

  return (
    <>
      <PageHeader
        title="Admissions"
        description="Applications submitted through your school's public admissions form."
      />

      <Card className="overflow-hidden">
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Applicant</TableHead>
                  <TableHead>Guardian</TableHead>
                  <TableHead>Submitted</TableHead>
                  <TableHead className="w-56 text-right">
                    <span className="sr-only">Decision</span>
                  </TableHead>
                </TableRow>
              </TableHeader>

              <TableBody>
                {query.isLoading ? (
                  <TableSkeleton columns={4} />
                ) : applications.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="p-0">
                      <EmptyState
                        icon={PartyPopper}
                        title="No pending applications"
                        description="You're all caught up. New applications from the public admissions form will appear here."
                        action={
                          <Button variant="outline" size="sm" asChild>
                            <Link href="/students">View all students</Link>
                          </Button>
                        }
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  applications.map((student) => (
                    <TableRow key={student.id}>
                      <TableCell>
                        <Link
                          href={`/students/${student.id}`}
                          className="font-medium text-foreground hover:text-primary hover:underline"
                        >
                          {student.full_name}
                        </Link>
                        <p className="text-xs text-muted-foreground">
                          {student.admission_number}
                        </p>
                      </TableCell>

                      <TableCell>
                        <p className="text-sm">{student.guardian_name ?? "—"}</p>
                        {student.guardian_phone ? (
                          <a
                            href={`tel:${student.guardian_phone}`}
                            className="text-xs text-muted-foreground hover:underline"
                          >
                            {student.guardian_phone}
                          </a>
                        ) : null}
                      </TableCell>

                      <TableCell className="text-muted-foreground">
                        {formatDate(student.created_at)}
                      </TableCell>

                      <TableCell>
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            size="sm"
                            onClick={() => setDecision({ student, action: "approve" })}
                          >
                            <Check />
                            Approve
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setDecision({ student, action: "reject" })}
                          >
                            <X />
                            Reject
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>

            {meta ? (
              <Pagination meta={meta} onPageChange={setPage} disabled={query.isFetching} />
            ) : null}
          </>
        )}
      </Card>

      <ConfirmDialog
        open={Boolean(decision)}
        onOpenChange={(open) => !open && setDecision(null)}
        title={decision?.action === "reject" ? "Reject application?" : "Approve application?"}
        description={
          decision ? (
            <>
              <span className="font-medium text-foreground">{decision.student.full_name}</span>{" "}
              {decision.action === "approve"
                ? "will become an active student and can be assigned to a section."
                : "will be marked inactive and will not be enrolled."}
            </>
          ) : null
        }
        confirmLabel={decision?.action === "reject" ? "Reject application" : "Approve student"}
        variant={decision?.action === "reject" ? "destructive" : "default"}
        loading={updateStudent.isPending}
        onConfirm={() => void confirmDecision()}
      />
    </>
  );
}
