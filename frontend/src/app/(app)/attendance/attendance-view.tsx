"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  CalendarCheck,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CloudOff,
  Lock,
  TriangleAlert,
} from "lucide-react";

import { AttendanceTabs } from "@/components/attendance/attendance-tabs";
import { EmptyState, ErrorState } from "@/components/data-states";
import { useOffline } from "@/components/offline/offline-provider";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/misc";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAttendanceSession, useDailyOverview, useOpenRegister } from "@/hooks/use-attendance";
import { isOfflineError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { attendanceApi } from "@/lib/api/resources/attendance";
import { classesApi } from "@/lib/api/resources/classes";
import type { DailyOverview, RegisterState, SectionDayStatus } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { attendanceMessages } from "@/lib/i18n/modules/attendance";
import { offlineMessages } from "@/lib/i18n/modules/offline";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { registerId, useOutbox } from "@/lib/offline/attendance-outbox";
import { formatDate } from "@/lib/utils";
import { OfflineRegisterDialog, type OfflineRegisterTarget } from "./offline-register-dialog";
import { RegisterDialog } from "./register-dialog";

/** Kept offline per section: a roster changes rarely, a draft register often. */
const ROSTER_STALE_MS = 6 * 60 * 60 * 1000;
/** How many sections' lists are fetched ahead for offline use, and how many at once. */
const PREFETCH_LIMIT = 60;
const PREFETCH_CONCURRENCY = 4;

function sectionLabel(row: SectionDayStatus): string {
  return `${row.class_name} · ${row.section_name}`;
}

/** Today in the browser's timezone, as the `YYYY-MM-DD` the API expects. */
function todayIso(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}

type BadgeVariant = "neutral" | "success" | "warning" | "destructive" | "outline";

/**
 * How one section's register reads at a glance.
 *
 * THE THREE STATES ARE THE POINT OF THIS SCREEN. "Not started" is a distinct,
 * actionable state — not an absence of information — and rendering it the same as
 * "everyone present" is precisely the confusion the backend's session table exists
 * to remove. It gets the warning treatment because an unmarked register at 09:30 is
 * something someone has to go and chase.
 */
function registerStatus(row: SectionDayStatus): {
  state: RegisterState;
  variant: BadgeVariant;
  Icon: typeof CircleCheck;
} {
  if (row.session_id === null) {
    return { state: "not_started", variant: "warning", Icon: CircleDashed };
  }
  if (row.status === "submitted") {
    return { state: "submitted", variant: "success", Icon: CircleCheck };
  }
  return { state: "draft", variant: "neutral", Icon: CircleAlert };
}

function BoardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-48" />
      </CardHeader>
      <CardContent className="space-y-2">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-10 w-full" />
        ))}
      </CardContent>
    </Card>
  );
}

export function AttendanceView({
  canMark,
  canAmend,
}: {
  canMark: boolean;
  canAmend: boolean;
}) {
  const { board: m, registerState } = useCatalog(attendanceMessages);
  const off = useCatalog(offlineMessages).board;
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { online } = useOffline();
  const outbox = useOutbox();
  const [date, setDate] = React.useState(todayIso);
  const [openSessionId, setOpenSessionId] = React.useState<string | null>(null);
  const [openLabel, setOpenLabel] = React.useState<string>("");
  const [offlineTarget, setOfflineTarget] = React.useState<OfflineRegisterTarget | null>(null);

  const query = useDailyOverview(date);
  const openRegister = useOpenRegister();

  // Offline with no copy of this date's board: fall back to the newest board saved on
  // this device, for its LIST of sections. Their statuses are another day's, so they
  // are shown as unknown rather than as today's.
  const savedBoard = React.useMemo((): DailyOverview | undefined => {
    if (query.data || online) return undefined;
    const newest = queryClient
      .getQueryCache()
      .findAll({ queryKey: ["attendance", "today"] })
      .filter((cached) => cached.state.data)
      .sort((a, b) => b.state.dataUpdatedAt - a.state.dataUpdatedAt)[0];
    return newest?.state.data as DailyOverview | undefined;
  }, [query.data, online, queryClient]);
  const boardIsStale = !query.data && savedBoard !== undefined && savedBoard.session_date !== date;

  // While online, keep each section's student list (and any register in progress)
  // on the device, so the register can be taken if the connection drops later.
  const sectionsKey = query.data?.sections.map((row) => `${row.section_id}:${row.session_id}`).join(",");
  React.useEffect(() => {
    if (!online || !query.data) return;
    const rows = query.data.sections.slice(0, PREFETCH_LIMIT);
    let cancelled = false;
    let next = 0;
    const worker = async () => {
      while (!cancelled && next < rows.length) {
        const row = rows[next++];
        await queryClient.prefetchQuery({
          queryKey: queryKeys.classes.roster(row.section_id),
          queryFn: () => classesApi.sections.roster(row.section_id),
          staleTime: ROSTER_STALE_MS,
        });
        if (row.session_id && row.status !== "submitted") {
          await queryClient.prefetchQuery({
            queryKey: queryKeys.attendance.session(row.session_id),
            queryFn: () => attendanceApi.get(row.session_id as string),
            staleTime: 60_000,
          });
        }
      }
    };
    // After the board has painted: this is background work.
    const timer = setTimeout(() => {
      for (let i = 0; i < PREFETCH_CONCURRENCY; i++) void worker();
    }, 1500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online, sectionsKey, queryClient]);

  // A register linked from global search (`?session=`) opens on arrival, and the
  // board behind it moves to that register's day — so closing the dialog lands on
  // its own row, not on today's. Same query key as the dialog's, so one fetch.
  const linkedSessionId = searchParams.get("session");
  const linkedDate = useAttendanceSession(linkedSessionId).data?.session_date;

  React.useEffect(() => {
    if (linkedSessionId) setOpenSessionId(linkedSessionId);
  }, [linkedSessionId]);

  React.useEffect(() => {
    if (linkedDate) setDate(linkedDate);
  }, [linkedDate]);

  function closeRegister() {
    setOpenSessionId(null);
    // Drop the link once followed, so a refresh does not reopen the register and
    // the same search result can be opened again.
    if (linkedSessionId) router.replace("/attendance");
  }

  const isToday = date === todayIso();

  /**
   * Open (or continue) a section's register, then show it.
   *
   * One call for both cases: the backend returns the existing register when one is
   * already open, so a teacher tapping a section they started this morning lands
   * back in it rather than getting a conflict.
   */
  async function handleOpen(row: SectionDayStatus) {
    const offlineTarget: OfflineRegisterTarget = {
      sectionId: row.section_id,
      sectionLabel: sectionLabel(row),
      date,
      sessionId: boardIsStale ? null : row.session_id,
      submitted: !boardIsStale && row.status === "submitted",
    };
    // Offline, or a register already waiting on this device: keep working on the
    // device's copy, so the queued taps are what the teacher sees.
    if (!online || outbox.some((item) => item.id === registerId(row.section_id, date))) {
      setOfflineTarget(offlineTarget);
      return;
    }
    setOpenLabel(sectionLabel(row));
    if (row.session_id) {
      setOpenSessionId(row.session_id);
      return;
    }
    try {
      const session = await openRegister.mutateAsync({
        section_id: row.section_id,
        session_date: date,
        period: 0,
      });
      setOpenSessionId(session.id);
    } catch (error) {
      // The connection dropped on the way: carry on offline.
      if (isOfflineError(error)) setOfflineTarget(offlineTarget);
    }
  }

  const overview = query.data ?? savedBoard;
  // The day after a register's date is the last day `attendance:mark` can touch it.
  // An amender can still open and correct it, so only they keep the buttons.
  const lockedForMe = (overview?.locked ?? false) && !canAmend;

  return (
    <div className="space-y-6">
      <PageHeader
        title={m.title}
        description={m.description}
        actions={
          <div className="flex items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor="attendance-date" className="text-xs">
                {m.date}
              </Label>
              <Input
                id="attendance-date"
                type="date"
                value={date}
                // Future registers are refused by the backend (`FUTURE_DATE`) —
                // nobody can record who attended a lesson that has not happened.
                // Capping the picker means the user never has to be told.
                max={todayIso()}
                onChange={(event) => setDate(event.target.value)}
                className="w-44"
              />
            </div>
            {!isToday && (
              <Button variant="outline" onClick={() => setDate(todayIso())}>
                {m.today}
              </Button>
            )}
          </div>
        }
      />
      {/* Registers, class analytics and every student's attendance are three views
          of one module; the tabs are how a head teacher moves between them. */}
      <AttendanceTabs />

      {!online && boardIsStale && savedBoard ? (
        <p className="flex items-start gap-2 rounded-lg bg-warning/15 p-4 text-sm">
          <CloudOff className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span className="text-pretty">
            {fill(off.staleBoard, { date: formatDate(savedBoard.session_date) })}
          </span>
        </p>
      ) : null}
      {!online && !overview && !query.isError ? (
        <p className="flex items-start gap-2 rounded-lg bg-warning/15 p-4 text-sm">
          <CloudOff className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span className="text-pretty">{off.noBoard}</span>
        </p>
      ) : null}

      {lockedForMe && (
        <p className="flex items-start gap-2 rounded-lg bg-muted/60 p-4 text-sm text-muted-foreground">
          <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span className="text-pretty">{fill(m.locked, { date })}</span>
        </p>
      )}

      {overview && !boardIsStale && (
        <div className="grid gap-4 sm:grid-cols-3">
          <SummaryTile
            label={m.sections}
            value={overview.sections_total}
            Icon={CalendarCheck}
          />
          <SummaryTile
            label={m.submitted}
            value={overview.sections_submitted}
            Icon={CircleCheck}
          />
          <SummaryTile
            label={m.notStarted}
            value={overview.sections_not_started}
            Icon={CircleDashed}
            // Only an alarm when there is something to act on. A zero here is the
            // goal state and should read as calm, not as a red zero.
            emphasis={overview.sections_not_started > 0}
          />
        </div>
      )}

      {query.isPending && online && !overview && <BoardSkeleton />}
      {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}

      {overview && overview.sections.length === 0 && (
        <EmptyState title={m.noSections} description={m.noSectionsHint} />
      )}

      {overview && overview.sections.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{fill(m.registersFor, { date })}</CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colSection}</TableHead>
                  <TableHead>{m.colTeacher}</TableHead>
                  <TableHead>{m.colStatus}</TableHead>
                  <TableHead className="text-end">{m.colPresent}</TableHead>
                  <TableHead className="text-end">{m.colAbsent}</TableHead>
                  <TableHead className="w-32" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {overview.sections.map((row) => {
                  const status = registerStatus(row);
                  const queued = outbox.find(
                    (item) => item.id === registerId(row.section_id, date),
                  );
                  return (
                    <TableRow key={row.section_id}>
                      <TableCell className="font-medium">
                        {row.class_name} &middot; {row.section_name}
                      </TableCell>
                      {/*
                        Who to chase when the status says nobody has marked it. An em
                        dash rather than an empty cell: a section with no class teacher
                        is a gap worth seeing, not a blank to skim past.
                      */}
                      <TableCell className="text-muted-foreground">
                        {row.class_teacher_name ?? (
                          <span aria-label={m.noTeacher}>&mdash;</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {boardIsStale ? (
                            <Badge variant="outline">{off.unknown}</Badge>
                          ) : (
                            <Badge variant={status.variant}>
                              <status.Icon className="me-1 h-3 w-3" aria-hidden />
                              {registerState[status.state]}
                            </Badge>
                          )}
                          {queued ? (
                            <Badge variant={queued.state === "failed" ? "destructive" : "warning"}>
                              {queued.state === "failed" ? (
                                <TriangleAlert className="me-1 h-3 w-3" aria-hidden />
                              ) : (
                                <CloudOff className="me-1 h-3 w-3" aria-hidden />
                              )}
                              {queued.state === "failed" ? off.syncFailed : off.savedOnDevice}
                            </Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      {/* An em dash, not a 0. Nobody marked this register, so
                          "0 present" would be a claim the data does not support. */}
                      <TableCell className="text-end tabular-nums">
                        {row.session_id && !boardIsStale ? row.present_count : "—"}
                      </TableCell>
                      <TableCell className="text-end tabular-nums">
                        {row.session_id && !boardIsStale ? row.absent_count : "—"}
                      </TableCell>
                      <TableCell className="text-end">
                        <Button
                          size="sm"
                          variant={row.session_id ? "outline" : "default"}
                          disabled={
                            (!canMark || lockedForMe) && (row.session_id === null || boardIsStale)
                          }
                          onClick={() => void handleOpen(row)}
                        >
                          {queued
                            ? m.continue
                            : row.session_id === null || boardIsStale
                              ? m.take
                              : row.status === "submitted" || lockedForMe
                                ? m.view
                                : m.continue}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <RegisterDialog
        sessionId={openSessionId}
        sectionLabel={openLabel}
        onClose={closeRegister}
        canMark={canMark}
        canAmend={canAmend}
      />
      <OfflineRegisterDialog target={offlineTarget} onClose={() => setOfflineTarget(null)} />
    </div>
  );
}

function SummaryTile({
  label,
  value,
  Icon,
  emphasis = false,
}: {
  label: string;
  value: number;
  Icon: typeof CircleCheck;
  emphasis?: boolean;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-4">
        <Icon
          className={emphasis ? "h-5 w-5 text-warning" : "h-5 w-5 text-muted-foreground"}
          aria-hidden
        />
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold tabular-nums">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}
