"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CreditCard, MoreHorizontal, Plus, Search, Users, X } from "lucide-react";

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
import { useExams } from "@/hooks/use-exams";
import { useDeleteStudent, useStudents } from "@/hooks/use-students";
import {
  STUDENT_STATUS_LABELS,
  type ExamResultFilter,
  type FeeStandingFilter,
  type StudentListRow,
  type StudentRead,
  type StudentStatus,
} from "@/lib/api/types";
import { cn, formatDate } from "@/lib/utils";
import { CardDesignDialog } from "./card-design-dialog";
import type { CardSchool } from "./student-card";
import { StudentFormDialog } from "./student-form-dialog";
import { StudentIdCardDialog } from "./student-id-card-dialog";
import { StudentResultDialog } from "./student-result-dialog";

const ALL = "__all__";

/**
 * Labels for the fee filter.
 *
 * "No dues" rather than "Paid": the set includes children who have never been billed
 * at all, and calling that "paid" would be actively wrong on a screen an accountant
 * reads. The question the filter answers is whether the family owes the school
 * anything -- see `FeeStandingFilter` on the backend.
 */
const FEE_STANDING_LABELS: Record<string, string> = {
  pending: "Fees pending",
  overdue: "Fees overdue",
  clear: "No dues",
};

/** Column heading, so the number is never ambiguous about which money it is. */
const DUES_COLUMN_LABELS: Record<string, string> = {
  pending: "Pending dues",
  overdue: "Overdue dues",
};

/**
 * Labels for the exam-result filter.
 *
 * All three imply "marked in the chosen exam": an unmarked student is missing
 * data, not a pass — see `ExamResultFilter` on the backend.
 */
const EXAM_RESULT_LABELS: Record<string, string> = {
  passed: "Passed",
  failed: "Failed",
  absent: "Absent",
};

/**
 * A billing period as a human reads it.
 *
 * `period_label` is FREE TEXT on the backend -- "2026-08" at a monthly school,
 * "Term 1" or "Annual" elsewhere. Only the `YYYY-MM` shape is prettified into a
 * month; everything else is printed exactly as the school typed it. Parsing the rest
 * as a date is how "Term 1" becomes "Invalid Date" on a fee chase list.
 */
function formatPeriod(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  const month = Number(match[2]);
  if (month < 1 || month > 12) return period;
  return new Date(Number(match[1]), month - 1, 1).toLocaleDateString(undefined, {
    month: "short",
    year: "numeric",
  });
}
const PAGE_SIZE = 20;

/** Where the directory leaves its filters for the detail page's back link. */
export const STUDENTS_LIST_QUERY_KEY = "students:list-query";

export function StudentsView({
  canManage,
  canFilterByFees,
  canFilterByResults,
  canDesignCard,
  school,
}: {
  canManage: boolean;
  /** Whether the caller holds `fee:read`. See the page component. */
  canFilterByFees: boolean;
  /** Whether the caller holds `grade:read`, which gates the exam-result filter
   *  the same way `fee:read` gates the fee one. */
  canFilterByResults: boolean;
  /** Whether the caller holds `school:update` and may save the card template. */
  canDesignCard: boolean;
  /**
   * Identity, effective branding (branch override or organization default,
   * resolved by the page) and saved card template of the active campus.
   * Null when the school list is unreadable.
   */
  school: CardSchool | null;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // =========================================================================
  // THE FILTERS LIVE IN THE URL, NOT IN THIS COMPONENT
  // =========================================================================
  // Someone searches "Fatima", opens the third result, then hits Back. With the
  // filters held in component state that returns them to an unfiltered page one
  // and they have to type the search again — which, on a counter with a parent
  // waiting, is the difference between one interaction and three.
  //
  // Putting the state in the query string makes the browser do the remembering:
  // Back restores `/students?q=fatima&page=3` and the table renders it. It also
  // makes a filtered directory a link someone can send to a colleague.
  //
  // Every write is `replace`, not `push`. Typing six letters must leave ONE
  // history entry, otherwise Back becomes a per-keystroke undo and never reaches
  // the page the user came from.
  const urlSearch = searchParams.get("q") ?? "";
  const status = (searchParams.get("status") ?? "") as StudentStatus | "";
  const sectionId = searchParams.get("section") ?? "";
  const fees = (searchParams.get("fees") ?? "") as FeeStandingFilter | "";
  const examId = searchParams.get("exam") ?? "";
  const examResult = (searchParams.get("result") ?? "") as ExamResultFilter | "";
  const page = Math.max(1, Number(searchParams.get("page")) || 1);

  // The input keeps its own copy so typing stays instant; the URL catches up on
  // the debounce. Everything else writes straight through.
  const [search, setSearch] = React.useState(urlSearch);

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<StudentRead | null>(null);
  const [deleting, setDeleting] = React.useState<StudentRead | null>(null);
  const [cardStudent, setCardStudent] = React.useState<StudentListRow | null>(null);
  const [designingCard, setDesigningCard] = React.useState(false);
  // The row whose result numbers were clicked, with the class its section
  // belongs to — the result-sheet endpoint is addressed by class, not section.
  const [resultTarget, setResultTarget] = React.useState<{
    student: StudentListRow;
    classId: string;
  } | null>(null);

  const debouncedSearch = useDebouncedValue(search);
  const { data: classes } = useClassSummary();
  const deleteStudent = useDeleteStudent();

  const writeParams = React.useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      const qs = next.toString();
      // `scroll: false` — changing a filter is not a navigation, and yanking the
      // page to the top mid-typing is disorienting.
      router.replace((qs ? `${pathname}?${qs}` : pathname) as Route, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  // Tells our own writes apart from a Back/Forward, which changes the URL without
  // touching the input. Without it the two effects below chase each other.
  const lastWritten = React.useRef(urlSearch);

  React.useEffect(() => {
    if (urlSearch === lastWritten.current) return;
    lastWritten.current = urlSearch;
    setSearch(urlSearch);
  }, [urlSearch]);

  React.useEffect(() => {
    // Only once the input has settled. A Back pressed mid-word rewinds the URL and
    // the box together, but the in-flight debounce is still carrying the abandoned
    // word — writing it would immediately undo the navigation.
    if (debouncedSearch !== search || debouncedSearch === urlSearch) return;
    lastWritten.current = debouncedSearch;
    // Any filter change invalidates the current page number — page 7 of the old
    // result set is meaningless against the new one.
    writeParams({ q: debouncedSearch || null, page: null });
  }, [debouncedSearch, search, urlSearch, writeParams]);

  // Fetches off the URL, not off the debounced box: the debounce already gates
  // when the URL is written, and querying the laggier of the two would fire a
  // second, wrong request every time Back restores a search.
  const query = useStudents({
    q: urlSearch || null,
    status: status || null,
    section_id: sectionId || null,
    fees: fees || null,
    exam: examId || null,
    result: examResult || null,
    page,
    size: PAGE_SIZE,
    sort_by: "last_name",
    sort_dir: "asc",
  });

  // The exam dropdown's options. Fetched only for holders of `grade:read` —
  // the same people the server would accept the filter from.
  const examOptions = useExams({ size: 50 }, { enabled: canFilterByResults });
  const activeExamName =
    examOptions.data?.items.find((exam) => exam.id === examId)?.name ?? "Result";

  // Remembered for the "All students" link on a student's page: Back already
  // restores the filtered list, but people click the breadcrumb just as often and
  // it should land in the same place. Keyed to the tab, so it can never leak into
  // another session, and absent on a cold deep link — which falls back to the
  // unfiltered directory.
  React.useEffect(() => {
    try {
      sessionStorage.setItem(STUDENTS_LIST_QUERY_KEY, searchParams.toString());
    } catch {
      // Private-mode / disabled storage. The breadcrumb just forgets; nothing else
      // on the page depends on it.
    }
  }, [searchParams]);

  const students = query.data?.items ?? [];
  const meta = query.data?.meta;
  const hasFilters = Boolean(urlSearch || status || sectionId || fees || examId);

  function clearFilters() {
    setSearch("");
    writeParams({
      q: null,
      status: null,
      section: null,
      fees: null,
      exam: null,
      result: null,
      page: null,
    });
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

  // The dues column exists only while a fee filter is applied: without one the
  // server sends no amounts at all (see `StudentListRow.dues`), so a permanently
  // present column would be permanently empty.
  const showDues = Boolean(fees) && fees !== "clear";
  // Same rule as the dues column: without an exam filter the server sends no
  // totals at all, so the column exists only while one is applied.
  const showResult = Boolean(examId);
  // Which class each section belongs to, for opening a row's result breakdown:
  // rows carry only their section, but the result sheet is fetched per class.
  const sectionClassId = React.useMemo(() => {
    const map = new Map<string, string>();
    for (const cls of classes ?? []) {
      for (const section of cls.sections) map.set(section.id, cls.id);
    }
    return map;
  }, [classes]);
  const columnCount = (canManage ? 7 : 6) + (showDues ? 1 : 0) + (showResult ? 1 : 0);

  // Currency comes from the challans themselves rather than being assumed: the rows
  // carry it, and a school billing in anything else would otherwise have its totals
  // silently relabelled as rupees.
  const duesCurrency = students.find((s) => s.dues)?.dues?.currency ?? "PKR";
  const money = React.useMemo(
    () =>
      new Intl.NumberFormat("en-PK", {
        style: "currency",
        currency: duesCurrency,
        maximumFractionDigits: 0,
      }),
    [duesCurrency],
  );

  return (
    <>
      <PageHeader
        title="Students"
        description="Search, filter, and manage your school's student directory."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {/* The card DESIGNER lives here, once per school — a row's "View
                card" only renders the saved template. See CardDesignDialog. */}
            {canDesignCard && school ? (
              <Button variant="outline" onClick={() => setDesigningCard(true)}>
                <CreditCard />
                Card design
              </Button>
            ) : null}
            {canManage ? (
              <Button onClick={openCreate}>
                <Plus />
                Enroll student
              </Button>
            ) : null}
          </div>
        }
      />

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by name or admission number…"
              className="ps-9"
              aria-label="Search students"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={status || ALL}
              onValueChange={(value) =>
                writeParams({ status: value === ALL ? null : value, page: null })
              }
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
              onValueChange={(value) =>
                writeParams({ section: value === ALL ? null : value, page: null })
              }
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

            {/*
              Fee standing. Three states rather than a "Fees pending" checkbox,
              because "who owes nothing" is a question people actually ask -- clearing
              a child for a trip -- and a checkbox can only express two of the three.
            */}
            {canFilterByFees ? (
              <Select
                value={fees || ALL}
                onValueChange={(value) =>
                  writeParams({ fees: value === ALL ? null : value, page: null })
                }
              >
                <SelectTrigger className="w-40" aria-label="Filter by fee standing">
                  <SelectValue placeholder="All fees" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All fees</SelectItem>
                  {Object.entries(FEE_STANDING_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}

            {/*
              Exam results, in two steps: pick the exam, then optionally the
              outcome. Clearing the exam clears the outcome with it — a `result`
              without an `exam` is a request the server (rightly) refuses.
            */}
            {canFilterByResults ? (
              <>
                <Select
                  value={examId || ALL}
                  onValueChange={(value) =>
                    writeParams({
                      exam: value === ALL ? null : value,
                      ...(value === ALL ? { result: null } : {}),
                      page: null,
                    })
                  }
                >
                  <SelectTrigger className="w-48" aria-label="Filter by exam">
                    <SelectValue placeholder="Any exam" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>Any exam</SelectItem>
                    {(examOptions.data?.items ?? []).map((exam) => (
                      <SelectItem key={exam.id} value={exam.id}>
                        {exam.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {examId ? (
                  <Select
                    value={examResult || ALL}
                    onValueChange={(value) =>
                      writeParams({ result: value === ALL ? null : value, page: null })
                    }
                  >
                    <SelectTrigger className="w-36" aria-label="Filter by result">
                      <SelectValue placeholder="Any result" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL}>Any result</SelectItem>
                      {Object.entries(EXAM_RESULT_LABELS).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : null}
              </>
            ) : null}

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
                  <TableHead>Class</TableHead>
                  {showDues ? (
                    <TableHead className="text-right">
                      {DUES_COLUMN_LABELS[fees] ?? "Dues"}
                    </TableHead>
                  ) : null}
                  {showResult ? (
                    // The exam's own name, so a screenshot of the table still says
                    // WHICH result the column shows.
                    <TableHead className="text-right">{activeExamName}</TableHead>
                  ) : null}
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
                      {/*
                        Class and section in ONE column, in the "Grade 9 · B" form the
                        attendance screen already uses. Two columns would be mostly
                        whitespace -- a section name is a single letter -- and the pair
                        is read as one fact anyway: where this child sits.

                        The dash is the ADMISSIONS case, not an error: an applicant is
                        accepted before a seat is chosen, so a pending student having
                        no class is the system working.
                      */}
                      <TableCell className="text-muted-foreground">
                        {student.class_name ? (
                          <>
                            {student.class_name}
                            {student.section_name ? ` · ${student.section_name}` : ""}
                          </>
                        ) : (
                          <span aria-label="Not assigned to a class">—</span>
                        )}
                      </TableCell>
                      {/*
                        Amount over the periods it covers. The months are the half an
                        office actually acts on -- "8,800" starts no conversation,
                        "8,800, Term 1" tells the clerk which challan to pull up.

                        `formatPeriod` leaves anything that is not `YYYY-MM` alone,
                        because the label is free text and a termly school's "Term 1"
                        is not a date.
                      */}
                      {showDues ? (
                        <TableCell className="text-right">
                          {student.dues ? (
                            (() => {
                              const owed = Number(student.dues.amount);
                              const late = Number(student.dues.overdue_amount);
                              return (
                                <div className="flex flex-col items-end">
                                  <span
                                    className={cn(
                                      "font-medium tabular-nums",
                                      // RED MEANS LATE, not merely owed -- the palette
                                      // reserves saturated colour for status and
                                      // documents a red cell as "something is wrong".
                                      // A bill issued this morning is not wrong.
                                      late > 0
                                        ? "text-destructive"
                                        : "text-warning-foreground dark:text-warning",
                                    )}
                                  >
                                    {money.format(owed)}
                                  </span>
                                  <span className="text-xs text-muted-foreground">
                                    {student.dues.periods.map(formatPeriod).join(", ")}
                                  </span>
                                  {/*
                                    Only when PART of the balance is late. Colouring the
                                    whole figure red already says "chase this"; without
                                    this line it would also imply the whole figure is
                                    overdue, and an office quoting the wrong number to a
                                    parent loses the argument at the counter.
                                  */}
                                  {late > 0 && late < owed ? (
                                    <span className="text-xs font-medium tabular-nums text-destructive">
                                      {money.format(late)} overdue
                                    </span>
                                  ) : null}
                                </div>
                              );
                            })()
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      ) : null}
                      {/*
                        The chosen exam's totals. Red only for a paper below its
                        declared pass line — the same "saturated colour means
                        something is wrong" rule the dues column follows: a low
                        percentage on papers with no pass line is a number, not
                        a verdict.
                      */}
                      {showResult ? (
                        <TableCell className="text-right">
                          {student.exam_result ? (
                            (() => {
                              const summary = (
                                <>
                                  <span
                                    className={cn(
                                      "font-medium tabular-nums",
                                      student.exam_result.failed_papers > 0 &&
                                        "text-destructive",
                                    )}
                                  >
                                    {student.exam_result.percentage}%
                                  </span>
                                  <span className="text-xs tabular-nums text-muted-foreground">
                                    {student.exam_result.total_obtained}/
                                    {student.exam_result.total_max}
                                  </span>
                                  {student.exam_result.failed_papers > 0 ? (
                                    <span className="text-xs font-medium text-destructive">
                                      {student.exam_result.failed_papers} paper
                                      {student.exam_result.failed_papers === 1 ? "" : "s"} failed
                                    </span>
                                  ) : null}
                                  {student.exam_result.absent_papers > 0 ? (
                                    <span className="text-xs text-muted-foreground">
                                      {student.exam_result.absent_papers} absent
                                    </span>
                                  ) : null}
                                </>
                              );
                              const resultClassId = student.section_id
                                ? sectionClassId.get(student.section_id)
                                : undefined;
                              // Clickable only when the section resolves to a
                              // class — the breakdown is fetched off the class
                              // result sheet, so without one there is nothing
                              // to open.
                              return resultClassId ? (
                                <button
                                  type="button"
                                  onClick={() =>
                                    setResultTarget({ student, classId: resultClassId })
                                  }
                                  aria-label={`Subject-wise result for ${student.full_name}`}
                                  title="View subject-wise marks"
                                  className="-my-1 flex w-full cursor-pointer flex-col items-end rounded-md px-1 py-1 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                >
                                  {summary}
                                </button>
                              ) : (
                                <div className="flex flex-col items-end">{summary}</div>
                              );
                            })()
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      ) : null}
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
                              <DropdownMenuItem onClick={() => setCardStudent(student)}>
                                View card
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
              <Pagination
                meta={meta}
                onPageChange={(next) => writeParams({ page: next > 1 ? String(next) : null })}
                disabled={query.isFetching}
              />
            ) : null}
          </>
        )}
      </Card>

      {canManage ? (
        <>
          <StudentFormDialog open={formOpen} onOpenChange={setFormOpen} student={editing} />

          <StudentIdCardDialog
            open={Boolean(cardStudent)}
            onOpenChange={(open) => !open && setCardStudent(null)}
            student={cardStudent}
            school={school}
          />

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

      {/* Outside the canManage block: the subject-wise breakdown rides on
          `grade:read` — the same permission that put the column on screen. */}
      {examId ? (
        <StudentResultDialog
          examId={examId}
          examName={activeExamName}
          student={resultTarget?.student ?? null}
          classId={resultTarget?.classId ?? null}
          school={school}
          onClose={() => setResultTarget(null)}
        />
      ) : null}

      {/* Outside the canManage block: designing the card rides on
          `school:update`, which is not implied by the student permissions. */}
      {canDesignCard ? (
        <CardDesignDialog
          open={designingCard}
          onOpenChange={setDesigningCard}
          school={school}
        />
      ) : null}
    </>
  );
}
