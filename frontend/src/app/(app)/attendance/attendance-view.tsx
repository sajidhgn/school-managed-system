"use client";

import * as React from "react";
import { CalendarCheck, CircleAlert, CircleCheck, CircleDashed } from "lucide-react";

import { EmptyState, ErrorState } from "@/components/data-states";
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
import { useDailyOverview, useOpenRegister } from "@/hooks/use-attendance";
import type { SectionDayStatus } from "@/lib/api/types";
import { RegisterDialog } from "./register-dialog";

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
  label: string;
  variant: BadgeVariant;
  Icon: typeof CircleCheck;
} {
  if (row.session_id === null) {
    return { label: "Not started", variant: "warning", Icon: CircleDashed };
  }
  if (row.status === "submitted") {
    return { label: "Submitted", variant: "success", Icon: CircleCheck };
  }
  return { label: "In progress", variant: "neutral", Icon: CircleAlert };
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
  const [date, setDate] = React.useState(todayIso);
  const [openSessionId, setOpenSessionId] = React.useState<string | null>(null);

  const query = useDailyOverview(date);
  const openRegister = useOpenRegister();

  const isToday = date === todayIso();

  /**
   * Open (or continue) a section's register, then show it.
   *
   * One call for both cases: the backend returns the existing register when one is
   * already open, so a teacher tapping a section they started this morning lands
   * back in it rather than getting a conflict.
   */
  async function handleOpen(row: SectionDayStatus) {
    if (row.session_id) {
      setOpenSessionId(row.session_id);
      return;
    }
    const session = await openRegister.mutateAsync({
      section_id: row.section_id,
      session_date: date,
      period: 0,
    });
    setOpenSessionId(session.id);
  }

  const overview = query.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance"
        description="Who was in the room, section by section."
        actions={
          <div className="flex items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor="attendance-date" className="text-xs">
                Date
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
                Today
              </Button>
            )}
          </div>
        }
      />

      {overview && (
        <div className="grid gap-4 sm:grid-cols-3">
          <SummaryTile
            label="Sections"
            value={overview.sections_total}
            Icon={CalendarCheck}
          />
          <SummaryTile
            label="Submitted"
            value={overview.sections_submitted}
            Icon={CircleCheck}
          />
          <SummaryTile
            label="Not started"
            value={overview.sections_not_started}
            Icon={CircleDashed}
            // Only an alarm when there is something to act on. A zero here is the
            // goal state and should read as calm, not as a red zero.
            emphasis={overview.sections_not_started > 0}
          />
        </div>
      )}

      {query.isPending && <BoardSkeleton />}
      {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}

      {overview && overview.sections.length === 0 && (
        <EmptyState
          title="No sections yet"
          description="Create a class and at least one section before taking attendance."
        />
      )}

      {overview && overview.sections.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Registers for {date}</CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Section</TableHead>
                  <TableHead>Class teacher</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Present</TableHead>
                  <TableHead className="text-right">Absent</TableHead>
                  <TableHead className="w-32" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {overview.sections.map((row) => {
                  const status = registerStatus(row);
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
                          <span aria-label="No class teacher assigned">&mdash;</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={status.variant}>
                          <status.Icon className="mr-1 h-3 w-3" aria-hidden />
                          {status.label}
                        </Badge>
                      </TableCell>
                      {/* An em dash, not a 0. Nobody marked this register, so
                          "0 present" would be a claim the data does not support. */}
                      <TableCell className="text-right tabular-nums">
                        {row.session_id ? row.present_count : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {row.session_id ? row.absent_count : "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant={row.session_id ? "outline" : "default"}
                          disabled={!canMark && row.session_id === null}
                          onClick={() => void handleOpen(row)}
                        >
                          {row.session_id === null
                            ? "Take"
                            : row.status === "submitted"
                              ? "View"
                              : "Continue"}
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
        onClose={() => setOpenSessionId(null)}
        canMark={canMark}
        canAmend={canAmend}
      />
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
          className={emphasis ? "h-5 w-5 text-amber-600" : "h-5 w-5 text-muted-foreground"}
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
