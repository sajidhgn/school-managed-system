"use client";

import * as React from "react";
import Link from "next/link";
import { MoreHorizontal, Plus, Search, Users, X } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { StudentStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useClassSummary } from "@/hooks/use-classes";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useDeleteStudent, useStudents } from "@/hooks/use-students";
import { STUDENT_STATUS_LABELS, type StudentRead, type StudentStatus } from "@/lib/api/types";
import { formatDate } from "@/lib/utils";
import { StudentFormDialog } from "./student-form-dialog";

const ALL = "__all__";
const PAGE_SIZE = 20;

export function StudentsView({ canManage }: { canManage: boolean }) {
  const [search, setSearch] = React.useState("");
  const [status, setStatus] = React.useState<StudentStatus | "">("");
  const [sectionId, setSectionId] = React.useState("");
  const [page, setPage] = React.useState(1);

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<StudentRead | null>(null);
  const [deleting, setDeleting] = React.useState<StudentRead | null>(null);

  const debouncedSearch = useDebouncedValue(search);
  const { data: classes } = useClassSummary();
  const deleteStudent = useDeleteStudent();

  // Any filter change invalidates the current page number — page 7 of the old
  // result set is meaningless against the new one.
  React.useEffect(() => {
    setPage(1);
  }, [debouncedSearch, status, sectionId]);

  const query = useStudents({
    q: debouncedSearch || null,
    status: status || null,
    section_id: sectionId || null,
    page,
    size: PAGE_SIZE,
    sort_by: "last_name",
    sort_dir: "asc",
  });

  const students = query.data?.items ?? [];
  const meta = query.data?.meta;
  const hasFilters = Boolean(debouncedSearch || status || sectionId);

  function clearFilters() {
    setSearch("");
    setStatus("");
    setSectionId("");
  }

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(student: StudentRead) {
    setEditing(student);
    setFormOpen(true);
  }

  async function confirmDelete() {
    if (!deleting) return;
    await deleteStudent.mutateAsync(deleting.id);
    setDeleting(null);
  }

  const columnCount = canManage ? 6 : 5;

  return (
    <>
      <PageHeader
        title="Students"
        description="Search, filter, and manage your school's student directory."
        actions={
          canManage ? (
            <Button onClick={openCreate}>
              <Plus />
              Enroll student
            </Button>
          ) : null
        }
      />

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by name or admission number…"
              className="pl-9"
              aria-label="Search students"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={status || ALL}
              onValueChange={(value) => setStatus(value === ALL ? "" : (value as StudentStatus))}
            >
              <SelectTrigger className="w-40" aria-label="Filter by status">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All statuses</SelectItem>
                {Object.entries(STUDENT_STATUS_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select
              value={sectionId || ALL}
              onValueChange={(value) => setSectionId(value === ALL ? "" : value)}
            >
              <SelectTrigger className="w-48" aria-label="Filter by section">
                <SelectValue placeholder="All sections" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All sections</SelectItem>
                {(classes ?? []).flatMap((cls) =>
                  cls.sections.map((section) => (
                    <SelectItem key={section.id} value={section.id}>
                      {cls.name} — {section.name}
                    </SelectItem>
                  )),
                )}
              </SelectContent>
            </Select>

            {hasFilters ? (
              <Button variant="ghost" size="sm" onClick={clearFilters}>
                <X />
                Clear
              </Button>
            ) : null}
          </div>
        </div>

        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Admission no.</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Guardian</TableHead>
                  <TableHead>Enrolled</TableHead>
                  {canManage ? (
                    <TableHead className="w-12">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>

              <TableBody>
                {query.isLoading ? (
                  <TableSkeleton columns={columnCount} />
                ) : students.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={columnCount} className="p-0">
                      <EmptyState
                        icon={Users}
                        title={hasFilters ? "No matching students" : "No students yet"}
                        description={
                          hasFilters
                            ? "Try a different search term or clear the filters."
                            : "Enroll your first student to start building the directory."
                        }
                        action={
                          hasFilters ? (
                            <Button variant="outline" size="sm" onClick={clearFilters}>
                              Clear filters
                            </Button>
                          ) : canManage ? (
                            <Button size="sm" onClick={openCreate}>
                              <Plus />
                              Enroll student
                            </Button>
                          ) : null
                        }
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  students.map((student) => (
                    <TableRow key={student.id}>
                      <TableCell>
                        <Link
                          href={`/students/${student.id}`}
                          className="font-medium text-foreground hover:text-primary hover:underline"
                        >
                          {student.full_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {student.admission_number}
                      </TableCell>
                      <TableCell>
                        <StudentStatusBadge status={student.status} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {student.guardian_name ?? "—"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(student.enrolled_on)}
                      </TableCell>
                      {canManage ? (
                        <TableCell>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Actions for ${student.full_name}`}
                              >
                                <MoreHorizontal />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem asChild>
                                <Link href={`/students/${student.id}`}>View profile</Link>
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => openEdit(student)}>
                                Edit
                              </DropdownMenuItem>
                              <DropdownMenuItem destructive onClick={() => setDeleting(student)}>
                                Remove
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      ) : null}
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

      {canManage ? (
        <>
          <StudentFormDialog open={formOpen} onOpenChange={setFormOpen} student={editing} />

          <ConfirmDialog
            open={Boolean(deleting)}
            onOpenChange={(open) => !open && setDeleting(null)}
            title="Remove student?"
            description={
              <>
                <span className="font-medium text-foreground">{deleting?.full_name}</span> will be
                removed from the directory. This cannot be undone.
              </>
            }
            confirmLabel="Remove student"
            loading={deleteStudent.isPending}
            onConfirm={confirmDelete}
          />
        </>
      ) : null}
    </>
  );
}
