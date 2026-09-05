"use client";

import * as React from "react";
import Link from "next/link";
import { ClipboardList, Plus, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useDeleteExam, useExams } from "@/hooks/use-exams";
import type { ExamRead, ExamStatus } from "@/lib/api/types";
import { formatDate } from "@/lib/utils";
import { EXAM_STATUS_LABELS, ExamFormDialog } from "./exam-form-dialog";

const STATUS_VARIANT: Record<ExamStatus, "neutral" | "success" | "outline"> = {
  scheduled: "outline",
  completed: "neutral",
  published: "success",
};

export function ExamsView({ canManage }: { canManage: boolean }) {
  const [search, setSearch] = React.useState("");
  const debounced = useDebouncedValue(search, 300);
  const query = useExams({ q: debounced || null, size: 50 });
  const remove = useDeleteExam();

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<ExamRead | null>(null);
  const [confirming, setConfirming] = React.useState<ExamRead | null>(null);

  const exams = query.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Exams"
        description="Schedule exams, add papers per class and subject, and enter marks."
        actions={
          canManage && (
            <Button
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="mr-1 h-4 w-4" aria-hidden />
              New exam
            </Button>
          )
        }
      />

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Exam schedule</CardTitle>
          <Input
            placeholder="Search exams…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="max-w-xs"
          />
        </CardHeader>
        <CardContent className="px-0">
          {query.isPending && <Skeleton className="mx-6 h-24" />}
          {query.isError && (
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          )}

          {query.data && exams.length === 0 && (
            <EmptyState
              icon={ClipboardList}
              title={debounced ? "No matching exams" : "No exams yet"}
              description={
                debounced
                  ? "Try a different search."
                  : "Create an exam, add its papers, and mark sheets open from there."
              }
            />
          )}

          {exams.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Exam</TableHead>
                  <TableHead className="w-44">Dates</TableHead>
                  <TableHead className="w-24">Papers</TableHead>
                  <TableHead className="w-28">Status</TableHead>
                  <TableHead className="w-32" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {exams.map((exam) => (
                  <TableRow key={exam.id}>
                    <TableCell>
                      <Link
                        href={`/exams/${exam.id}`}
                        className="font-medium hover:underline"
                      >
                        {exam.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {exam.start_date
                        ? `${formatDate(exam.start_date)}${
                            exam.end_date ? ` – ${formatDate(exam.end_date)}` : ""
                          }`
                        : "—"}
                    </TableCell>
                    <TableCell>{exam.paper_count}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[exam.status]}>
                        {EXAM_STATUS_LABELS[exam.status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {canManage && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setEditing(exam);
                              setFormOpen(true);
                            }}
                          >
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setConfirming(exam)}
                          >
                            <Trash2 className="h-3 w-3" aria-hidden />
                            <span className="sr-only">Delete {exam.name}</span>
                          </Button>
                        </>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ExamFormDialog open={formOpen} onOpenChange={setFormOpen} exam={editing} />
      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={`Delete ${confirming?.name ?? "this exam"}?`}
        description="This is refused once any marks have been entered — an exam with marks is the academic record."
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => {
          if (confirming) remove.mutate(confirming.id);
          setConfirming(null);
        }}
      />
    </div>
  );
}
