"use client";

import * as React from "react";
import Link from "next/link";
import { ClipboardList, Plus, Scale, Trash2 } from "lucide-react";

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
import { fill } from "@/lib/i18n/format";
import { examsMessages } from "@/lib/i18n/modules/exams";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { formatDate } from "@/lib/utils";
import { ExamFormDialog } from "./exam-form-dialog";
import { GradingScaleDialog } from "./grading-scale-dialog";

const STATUS_VARIANT: Record<ExamStatus, "neutral" | "success" | "outline"> = {
  scheduled: "outline",
  completed: "neutral",
  published: "success",
};

export function ExamsView({
  canManage,
  canSetGrading,
}: {
  canManage: boolean;
  canSetGrading: boolean;
}) {
  const { list: m, status: statusLabel } = useCatalog(examsMessages);
  const [search, setSearch] = React.useState("");
  const debounced = useDebouncedValue(search, 300);
  const query = useExams({ q: debounced || null, size: 50 });
  const remove = useDeleteExam();

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<ExamRead | null>(null);
  const [confirming, setConfirming] = React.useState<ExamRead | null>(null);
  const [grading, setGrading] = React.useState(false);

  const exams = query.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title={m.title}
        description={m.description}
        actions={
          <>
            <Button variant="outline" onClick={() => setGrading(true)}>
              <Scale className="me-1 h-4 w-4" aria-hidden />
              {m.gradingScale}
            </Button>
            {canManage ? (
              <Button
                onClick={() => {
                  setEditing(null);
                  setFormOpen(true);
                }}
              >
                <Plus className="me-1 h-4 w-4" aria-hidden />
                {m.newExam}
              </Button>
            ) : null}
          </>
        }
      />

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>{m.scheduleTitle}</CardTitle>
          <Input
            placeholder={m.searchPlaceholder}
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
              title={debounced ? m.noMatches : m.noExams}
              description={debounced ? m.tryDifferentSearch : m.emptyHint}
            />
          )}

          {exams.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colExam}</TableHead>
                  <TableHead className="w-44">{m.colDates}</TableHead>
                  <TableHead className="w-24">{m.colPapers}</TableHead>
                  <TableHead className="w-28">{m.colStatus}</TableHead>
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
                        {statusLabel[exam.status]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-end">
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
                            {m.edit}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setConfirming(exam)}
                          >
                            <Trash2 className="h-3 w-3" aria-hidden />
                            <span className="sr-only">{fill(m.deleteNamed, { name: exam.name })}</span>
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
        title={fill(m.deleteTitle, { name: confirming?.name ?? m.deleteFallback })}
        description={m.deleteDescription}
        confirmLabel={m.delete}
        variant="destructive"
        onConfirm={() => {
          if (confirming) remove.mutate(confirming.id);
          setConfirming(null);
        }}
      />
      <GradingScaleDialog open={grading} onOpenChange={setGrading} canEdit={canSetGrading} />
    </div>
  );
}
