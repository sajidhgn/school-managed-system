"use client";

import * as React from "react";
import { BookOpen, Plus, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/misc";
import { NativeSelect } from "@/components/ui/native-select";
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
import {
  useAddToCurriculum,
  useCurriculum,
  useDeleteSubject,
  useRemoveFromCurriculum,
  useSubjects,
} from "@/hooks/use-subjects";
import type { SubjectKind, SubjectRead } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { subjectsMessages } from "@/lib/i18n/modules/subjects";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { SubjectFormDialog } from "./subject-form-dialog";

const KIND_VARIANT: Record<SubjectKind, "neutral" | "outline" | "success"> = {
  core: "success",
  elective: "neutral",
  activity: "outline",
};

/** Which subjects one class studies, and the controls to change that. */
function CurriculumPanel({ canManage }: { canManage: boolean }) {
  const { curriculum: m, kind: kindLabel } = useCatalog(subjectsMessages);
  const classes = useClassSummary();
  const [classId, setClassId] = React.useState<string>("");

  React.useEffect(() => {
    if (!classId && classes.data?.length) setClassId(classes.data[0].id);
  }, [classes.data, classId]);

  const curriculum = useCurriculum(classId || null);
  const subjects = useSubjects({ size: 100 });
  const add = useAddToCurriculum();
  const remove = useRemoveFromCurriculum(classId);

  const linked = new Set(curriculum.data?.map((entry) => entry.subject_id) ?? []);
  const available = (subjects.data?.items ?? []).filter((s) => !linked.has(s.id));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{m.title}</CardTitle>
        <CardDescription>{m.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <Label htmlFor="curriculum-class">{m.classLabel}</Label>
          <NativeSelect
            id="curriculum-class"
            value={classId}
            onChange={(event) => setClassId(event.target.value)}
            className="max-w-xs"
          >
            {(classes.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </NativeSelect>
        </div>

        {curriculum.isPending && classId && <Skeleton className="h-24 w-full" />}

        {curriculum.data && curriculum.data.length === 0 && (
          <p className="text-sm text-muted-foreground">{m.noSubjects}</p>
        )}

        {curriculum.data && curriculum.data.length > 0 && (
          <div className="space-y-1">
            {curriculum.data.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground">
                    {entry.subject_code}
                  </span>
                  <span className="font-medium">{entry.subject_name}</span>
                  <Badge variant={KIND_VARIANT[entry.subject_kind]}>
                    {kindLabel[entry.subject_kind]}
                  </Badge>
                  {entry.weekly_periods !== null && (
                    <span className="text-muted-foreground">
                      {fill(m.perWeek, { count: entry.weekly_periods })}
                    </span>
                  )}
                </div>
                {canManage && (
                  <Button size="sm" variant="ghost" onClick={() => remove.mutate(entry.id)}>
                    <Trash2 className="h-3 w-3" aria-hidden />
                    <span className="sr-only">{fill(m.removeNamed, { name: entry.subject_name })}</span>
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}

        {canManage && classId && available.length > 0 && (
          <div className="flex items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor="curriculum-add">{m.addLabel}</Label>
              <NativeSelect id="curriculum-add" defaultValue="" className="max-w-xs">
                <option value="" disabled>
                  {m.choose}
                </option>
                {available.map((subject) => (
                  <option key={subject.id} value={subject.id}>
                    {subject.code} — {subject.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <Button
              variant="outline"
              disabled={add.isPending}
              onClick={(event) => {
                const select = (event.currentTarget.previousElementSibling as HTMLElement)
                  ?.querySelector("select") as HTMLSelectElement | null;
                if (select?.value) {
                  add.mutate({ classId, body: { subject_id: select.value } });
                  select.value = "";
                }
              }}
            >
              {m.add}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function SubjectsView({ canManage }: { canManage: boolean }) {
  const { page: m, kind: kindLabel } = useCatalog(subjectsMessages);
  const [search, setSearch] = React.useState("");
  const debounced = useDebouncedValue(search, 300);
  const query = useSubjects({ q: debounced || null, size: 50 });
  const remove = useDeleteSubject();

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<SubjectRead | null>(null);
  const [confirming, setConfirming] = React.useState<SubjectRead | null>(null);

  const subjects = query.data?.items ?? [];

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
              {m.newSubject}
            </Button>
          )
        }
      />

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>{m.catalogTitle}</CardTitle>
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

          {query.data && subjects.length === 0 && (
            <EmptyState
              icon={BookOpen}
              title={debounced ? m.noMatches : m.noSubjects}
              description={debounced ? m.tryDifferentSearch : m.emptyHint}
            />
          )}

          {subjects.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-24">{m.colCode}</TableHead>
                  <TableHead>{m.colName}</TableHead>
                  <TableHead className="w-28">{m.colType}</TableHead>
                  <TableHead className="w-28" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {subjects.map((subject) => (
                  <TableRow key={subject.id}>
                    <TableCell className="font-mono text-xs">{subject.code}</TableCell>
                    <TableCell className="font-medium">{subject.name}</TableCell>
                    <TableCell>
                      <Badge variant={KIND_VARIANT[subject.kind]}>
                        {kindLabel[subject.kind]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-end">
                      {canManage && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setEditing(subject);
                              setFormOpen(true);
                            }}
                          >
                            {m.edit}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setConfirming(subject)}
                          >
                            <Trash2 className="h-3 w-3" aria-hidden />
                            <span className="sr-only">{fill(m.deleteNamed, { name: subject.name })}</span>
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

      <CurriculumPanel canManage={canManage} />

      <SubjectFormDialog open={formOpen} onOpenChange={setFormOpen} subject={editing} />
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
    </div>
  );
}
