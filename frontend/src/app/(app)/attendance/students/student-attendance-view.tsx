"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, ArrowUpDown, Search } from "lucide-react";

import { AttendanceTabs } from "@/components/attendance/attendance-tabs";
import { TodayBadge, formatPct, shiftIso, todayIso } from "@/components/attendance/status";
import { StudentAttendanceDialog } from "@/components/attendance/student-attendance-panel";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useStudentAttendanceList } from "@/hooks/use-attendance";
import { useClassSummary } from "@/hooks/use-classes";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import type { AttendanceRate, SortDirection } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { attendanceMessages } from "@/lib/i18n/modules/attendance";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { cn } from "@/lib/utils";

/**
 * Every child's attendance on one table: today, this month, last month, overall.
 *
 * WORST FIRST BY DEFAULT. The reason to open this screen is to find the children who
 * need a phone call home, and they should be on page one, not page four. Children
 * nobody has marked yet have no rate and sort after everyone who has one, in either
 * direction — "no data" is not the worst attendance.
 *
 * TODAY HAS THREE STATES, NOT TWO. A submitted register says present / absent / late
 * / half day / leave; "Register open" means a teacher has started one and not
 * submitted it (its pre-filled lines are not reported); "Not marked" means no
 * register covers the child yet. See `TodayBadge`.
 *
 * Scope is the server's: the whole campus for a principal, a teacher's own sections
 * for a teacher. The class and section pickers come from the class summary, which is
 * bounded the same way, so a teacher is never offered a section that would 404.
 */

type SortKey = "overall" | "this_month" | "previous_month" | "name" | "class" | "roll_number";
type Range = "year" | "90" | "30";

const PAGE_SIZE = 25;

export function StudentAttendanceView({
  initialSectionId,
  initialClassId,
}: {
  initialSectionId: string | null;
  initialClassId: string | null;
}) {
  const m = useCatalog(attendanceMessages).students;
  const classes = useClassSummary();
  const [search, setSearch] = React.useState("");
  const debounced = useDebouncedValue(search.trim());
  const [classId, setClassId] = React.useState(initialClassId ?? "");
  const [sectionId, setSectionId] = React.useState(initialSectionId ?? "");
  const [range, setRange] = React.useState<Range>("year");
  const [sort, setSort] = React.useState<{ by: SortKey; dir: SortDirection }>({
    by: "overall",
    dir: "asc",
  });
  const [page, setPage] = React.useState(1);
  const [drill, setDrill] = React.useState<{ id: string; name: string; detail?: string } | null>(
    null,
  );

  // A section link from the class analytics arrives with only `section_id`; fill in
  // its class once the summary loads so both pickers agree with the filter.
  const sectionClass = React.useMemo(
    () => classes.data?.find((c) => c.sections.some((s) => s.id === sectionId))?.id ?? "",
    [classes.data, sectionId],
  );
  const effectiveClassId = classId || sectionClass;
  const sections = classes.data?.find((c) => c.id === effectiveClassId)?.sections ?? [];

  const today = todayIso();
  const overall =
    range === "year" ? {} : { from_date: shiftIso(today, -(Number(range) - 1)), to_date: today };

  // Any filter change starts again at page one: page four of a new filter is
  // usually empty, and always meaningless.
  React.useEffect(() => setPage(1), [debounced, classId, sectionId, range, sort]);

  const query = useStudentAttendanceList({
    page,
    size: PAGE_SIZE,
    sort_by: sort.by,
    sort_dir: sort.dir,
    q: debounced || null,
    class_id: classId || null,
    section_id: sectionId || null,
    ...overall,
  });
  const data = query.data;
  const reloading = query.isFetching && query.isPlaceholderData;

  const header = (key: SortKey, label: string, className?: string, firstDir: SortDirection = "asc") => {
    const active = sort.by === key;
    const Icon = !active ? ArrowUpDown : sort.dir === "desc" ? ArrowDown : ArrowUp;
    return (
      <TableHead
        className={className}
        aria-sort={active ? (sort.dir === "desc" ? "descending" : "ascending") : "none"}
      >
        <button
          type="button"
          className="inline-flex items-center gap-1 hover:text-foreground"
          onClick={() =>
            setSort({ by: key, dir: active ? (sort.dir === "asc" ? "desc" : "asc") : firstDir })
          }
        >
          {label}
          <Icon className="size-3.5" aria-hidden />
        </button>
      </TableHead>
    );
  };

  const overallLabel =
    data && range === "year"
      ? fill(m.overallSince, { date: data.overall.from_date })
      : range === "year"
        ? m.overall
        : fill(m.lastDays, { days: range });

  return (
    <div className="space-y-6">
      <PageHeader title={m.title} description={m.description} />
      <AttendanceTabs />

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full space-y-1 sm:w-64">
          <Label htmlFor="student-search" className="text-xs">
            {m.search}
          </Label>
          <div className="relative">
            <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              id="student-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={m.searchPlaceholder}
              className="ps-8"
            />
          </div>
        </div>
        {classes.data && classes.data.length > 0 ? (
          <>
            <div className="space-y-1">
              <Label htmlFor="class-filter" className="text-xs">
                {m.class}
              </Label>
              <NativeSelect
                id="class-filter"
                value={effectiveClassId}
                onChange={(e) => {
                  setClassId(e.target.value);
                  setSectionId("");
                }}
                className="w-40"
              >
                <option value="">{m.allClasses}</option>
                {classes.data.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-1">
              <Label htmlFor="section-filter" className="text-xs">
                {m.section}
              </Label>
              <NativeSelect
                id="section-filter"
                value={sectionId}
                onChange={(e) => setSectionId(e.target.value)}
                disabled={sections.length === 0}
                className="w-32"
              >
                <option value="">{m.allSections}</option>
                {sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </>
        ) : null}
        <div className="space-y-1">
          <Label htmlFor="overall-range" className="text-xs">
            {m.overallCovers}
          </Label>
          <NativeSelect
            id="overall-range"
            value={range}
            onChange={(e) => setRange(e.target.value as Range)}
            className="w-44"
          >
            <option value="year">{m.thisYear}</option>
            <option value="90">{m.last90}</option>
            <option value="30">{m.last30}</option>
          </NativeSelect>
        </div>
      </div>

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <Card className={cn("transition-opacity", reloading && "opacity-60")} aria-busy={reloading}>
          <CardContent className="px-0 pb-0">
            {data && data.items.length === 0 ? (
              <EmptyState
                title={debounced ? m.noMatch : m.noStudents}
                description={debounced ? m.noMatchHint : m.noStudentsHint}
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    {header("roll_number", m.colRoll, "w-16")}
                    {header("name", m.colStudent)}
                    {header("class", m.colClass)}
                    <TableHead>{m.colToday}</TableHead>
                    {header("this_month", m.colThisMonth, "text-end")}
                    {header("previous_month", m.colLastMonth, "text-end")}
                    {header("overall", overallLabel, "text-end")}
                    <TableHead className="w-24" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {!data ? (
                    <TableSkeleton columns={8} rows={8} />
                  ) : (
                    data.items.map((row) => {
                      const placement = row.class_name
                        ? `${row.class_name} · ${row.section_name}`
                        : m.unplaced;
                      return (
                        <TableRow key={row.student_id}>
                          <TableCell className="tabular-nums text-muted-foreground">
                            {row.roll_number ?? "—"}
                          </TableCell>
                          <TableCell>
                            <Link
                              href={`/students/${row.student_id}`}
                              className="font-medium hover:underline"
                            >
                              {row.full_name}
                            </Link>
                            <p className="text-xs text-muted-foreground">{row.admission_number}</p>
                          </TableCell>
                          <TableCell className="whitespace-nowrap">{placement}</TableCell>
                          <TableCell>
                            <TodayBadge register={row.today_register} status={row.today_status} />
                          </TableCell>
                          <RateCell rate={row.this_month} />
                          <RateCell rate={row.previous_month} />
                          <RateCell rate={row.overall} strong />
                          <TableCell className="text-end">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                setDrill({ id: row.student_id, name: row.full_name, detail: placement })
                              }
                            >
                              {m.calendar}
                            </Button>
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            )}
            {data ? <Pagination meta={data.meta} onPageChange={setPage} disabled={query.isFetching} /> : null}
          </CardContent>
        </Card>
      )}

      {data ? (
        <p className="text-xs text-muted-foreground">
          {fill(m.footnote, {
            from: data.this_month.from_date,
            to: data.this_month.to_date,
            prevFrom: data.previous_month.from_date,
            prevTo: data.previous_month.to_date,
          })}
        </p>
      ) : null}

      <StudentAttendanceDialog student={drill} onClose={() => setDrill(null)} />
    </div>
  );
}

function RateCell({ rate, strong = false }: { rate: AttendanceRate; strong?: boolean }) {
  const m = useCatalog(attendanceMessages).students;
  const { counts } = rate;
  const detail =
    rate.counted === 0 && counts.excused === 0
      ? m.noRegisters
      : fill(m.detail, {
          present: counts.present,
          late: counts.late,
          half: counts.half_day,
          absent: counts.absent,
          leave: counts.excused,
        });
  return (
    <TableCell className="text-end" title={detail}>
      <span className={cn("tabular-nums", strong && "font-medium")}>{formatPct(rate.percentage)}</span>
      {counts.absent > 0 ? (
        <p className="text-xs text-muted-foreground tabular-nums">
          {fill(m.absentCount, { count: counts.absent })}
        </p>
      ) : null}
      <span className="sr-only">{detail}</span>
    </TableCell>
  );
}
