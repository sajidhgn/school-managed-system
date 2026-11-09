"use client";

import * as React from "react";
import { CalendarRange, Check, Plus, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import {
  useAcademicYears,
  useBackfillEnrollments,
  useDeleteAcademicYear,
  useDeleteTerm,
  useSetCurrentYear,
  useTerms,
} from "@/hooks/use-calendar";
import type { AcademicYearRead } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { calendarMessages } from "@/lib/i18n/modules/calendar";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { TermFormDialog } from "./term-form-dialog";
import { YearFormDialog } from "./year-form-dialog";

function formatRange(template: string, from: string, to: string) {
  return fill(template, { from, to });
}

/** The terms of one year, loaded only when the year is expanded. */
function TermList({ year, canManage }: { year: AcademicYearRead; canManage: boolean }) {
  const { terms: m, page } = useCatalog(calendarMessages);
  const query = useTerms(year.id);
  const deleteTerm = useDeleteTerm();
  const [formOpen, setFormOpen] = React.useState(false);
  const [confirming, setConfirming] = React.useState<string | null>(null);

  return (
    <div className="space-y-2 border-t pt-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">{m.title}</p>
        {canManage && (
          <Button size="sm" variant="outline" onClick={() => setFormOpen(true)}>
            <Plus className="me-1 h-3 w-3" aria-hidden />
            {m.addTerm}
          </Button>
        )}
      </div>

      {query.isPending && <Skeleton className="h-8 w-full" />}

      {query.data && query.data.length === 0 && (
        <p className="text-sm text-muted-foreground">{m.empty}</p>
      )}

      {query.data?.map((term) => (
        <div
          key={term.id}
          className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
        >
          <div>
            <span className="font-medium">
              {term.sequence}. {term.name}
            </span>
            <span className="ms-2 text-muted-foreground">
              {formatRange(page.range, term.start_date, term.end_date)}
            </span>
          </div>
          {canManage && (
            <Button size="sm" variant="ghost" onClick={() => setConfirming(term.id)}>
              <Trash2 className="h-3 w-3" aria-hidden />
              <span className="sr-only">{fill(m.deleteNamed, { name: term.name })}</span>
            </Button>
          )}
        </div>
      ))}

      <TermFormDialog open={formOpen} onOpenChange={setFormOpen} year={year} />
      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={m.deleteTitle}
        description={m.deleteDescription}
        confirmLabel={m.delete}
        variant="destructive"
        onConfirm={() => {
          if (confirming) deleteTerm.mutate(confirming);
          setConfirming(null);
        }}
      />
    </div>
  );
}

export function CalendarView({
  canManage,
  canBackfill,
}: {
  canManage: boolean;
  canBackfill: boolean;
}) {
  const m = useCatalog(calendarMessages).page;
  const query = useAcademicYears({ size: 50, sort_by: "start_date", sort_dir: "desc" });
  const setCurrent = useSetCurrentYear();
  const deleteYear = useDeleteAcademicYear();
  const backfill = useBackfillEnrollments();

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<AcademicYearRead | null>(null);
  const [confirming, setConfirming] = React.useState<AcademicYearRead | null>(null);

  const years = query.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title={m.title}
        description={m.description}
        actions={
          canManage && (
            <Button
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="me-1 h-4 w-4" aria-hidden />
              {m.newYear}
            </Button>
          )
        }
      />

      {query.isPending && <Skeleton className="h-40 w-full" />}
      {query.isError && <ErrorState error={query.error} onRetry={() => void query.refetch()} />}

      {query.data && years.length === 0 && (
        <EmptyState
          icon={CalendarRange}
          title={m.emptyTitle}
          description={m.emptyHint}
        />
      )}

      <div className="space-y-4">
        {years.map((year) => (
          <Card key={year.id}>
            <CardHeader className="flex-row items-start justify-between space-y-0">
              <div>
                <CardTitle className="flex items-center gap-2">
                  {year.name}
                  {year.is_current && <Badge variant="success">{m.current}</Badge>}
                </CardTitle>
                <CardDescription>
                  {formatRange(m.range, year.start_date, year.end_date)} &middot;{" "}
                  {fill(year.term_count === 1 ? m.terms.one : m.terms.other, {
                    count: year.term_count ?? 0,
                  })}
                </CardDescription>
              </div>
              <div className="flex gap-2">
                {canManage && !year.is_current && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={setCurrent.isPending}
                    onClick={() => setCurrent.mutate(year.id)}
                  >
                    <Check className="me-1 h-3 w-3" aria-hidden />
                    {m.makeCurrent}
                  </Button>
                )}
                {canManage && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditing(year);
                      setFormOpen(true);
                    }}
                  >
                    {m.edit}
                  </Button>
                )}
                {canManage && !year.is_current && (
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(year)}>
                    <Trash2 className="h-3 w-3" aria-hidden />
                    <span className="sr-only">{fill(m.deleteNamed, { name: year.name })}</span>
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <TermList year={year} canManage={canManage} />

              {canBackfill && (
                <div className="rounded-md bg-muted/50 p-3 text-sm">
                  <p className="font-medium">{m.historyTitle}</p>
                  <p className="mt-1 text-muted-foreground">
                    {fill(m.historyBody, { year: year.name })}
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-2"
                    disabled={backfill.isPending}
                    onClick={() => backfill.mutate(year.id)}
                  >
                    {m.openHistory}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <YearFormDialog open={formOpen} onOpenChange={setFormOpen} year={editing} />
      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(open) => !open && setConfirming(null)}
        title={fill(m.deleteTitle, { name: confirming?.name ?? m.deleteFallback })}
        description={m.deleteDescription}
        confirmLabel={m.delete}
        variant="destructive"
        onConfirm={() => {
          if (confirming) deleteYear.mutate(confirming.id);
          setConfirming(null);
        }}
      />
    </div>
  );
}
