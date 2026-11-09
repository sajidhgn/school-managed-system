"use client";

import * as React from "react";
import { Layers, MoreHorizontal, Plus, Users } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/misc";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAssignmentBound } from "@/hooks/use-assignment-bound";
import { useClassSummary, useDeleteClass, useDeleteSection } from "@/hooks/use-classes";
import type { ClassSummary, SectionSummary } from "@/lib/api/types";
import type { Translation } from "@/lib/i18n/catalog";
import { fill } from "@/lib/i18n/format";
import { classesMessages } from "@/lib/i18n/modules/classes";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { ClassFormDialog } from "./class-form-dialog";
import { SectionFormDialog } from "./section-form-dialog";

type BadgeVariant = "neutral" | "success" | "warning" | "destructive" | "outline";
type CapacityMessages = Translation<(typeof classesMessages)["en"]>["capacity"];

/** `{ one, other }` picked by the count and filled with it. */
function counted(forms: { one: string; other: string }, count: number): string {
  return fill(count === 1 ? forms.one : forms.other, { count });
}

/** A template with one `{name}` slot filled by a node (here, the bold name). */
function withName(template: string, name: React.ReactNode): React.ReactNode {
  const [before, after = ""] = template.split("{name}");
  return (
    <>
      {before}
      {name}
      {after}
    </>
  );
}

/**
 * Seat pressure for a section.
 *
 * An over-subscribed section is an operational problem — students without a
 * desk — so it is escalated to the destructive variant rather than being left
 * as a number the admin has to compare by eye.
 */
function capacityStatus(
  section: SectionSummary,
  m: CapacityMessages,
): { label: string; variant: BadgeVariant } {
  if (section.capacity === null) return { label: m.noLimit, variant: "outline" };

  const remaining = section.capacity - section.student_count;
  if (remaining < 0) {
    return { label: fill(m.overBy, { count: Math.abs(remaining) }), variant: "destructive" };
  }
  if (remaining === 0) return { label: m.full, variant: "warning" };
  if (remaining <= Math.max(1, Math.round(section.capacity * 0.1))) {
    return { label: counted(m.seatsLeft, remaining), variant: "warning" };
  }
  return { label: counted(m.seatsLeft, remaining), variant: "success" };
}

function ClassesSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 3 }).map((_, index) => (
        <Card key={index}>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-56" />
          </CardHeader>
          <CardContent className="space-y-2">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function ClassesView({
  canManage,
  schoolId,
}: {
  canManage: boolean;
  /** Active campus. Scopes the class-teacher picker to the staff who work there. */
  schoolId: string | null;
}) {
  const { page: m, capacity: capacityMessages } = useCatalog(classesMessages);
  const query = useClassSummary();
  const bound = useAssignmentBound();
  const deleteClass = useDeleteClass();
  const deleteSection = useDeleteSection();

  const [classFormOpen, setClassFormOpen] = React.useState(false);
  const [editingClass, setEditingClass] = React.useState<ClassSummary | null>(null);
  const [deletingClass, setDeletingClass] = React.useState<ClassSummary | null>(null);

  // Sections are always addressed with their parent class, since the update and
  // delete mutations need the class id to invalidate the right cache entry.
  const [sectionTarget, setSectionTarget] = React.useState<{
    cls: ClassSummary;
    section: SectionSummary | null;
  } | null>(null);
  const [sectionFormOpen, setSectionFormOpen] = React.useState(false);
  const [deletingSection, setDeletingSection] = React.useState<{
    cls: ClassSummary;
    section: SectionSummary;
  } | null>(null);

  const classes = React.useMemo(() => {
    const items = query.data ?? [];
    // Level is the school's own ordering (Grade 1 before Grade 10); name only
    // breaks ties between streams sharing a level.
    return [...items].sort((a, b) => a.level - b.level || a.name.localeCompare(b.name));
  }, [query.data]);

  function openCreateClass() {
    setEditingClass(null);
    setClassFormOpen(true);
  }

  function openEditClass(cls: ClassSummary) {
    setEditingClass(cls);
    setClassFormOpen(true);
  }

  function openSectionForm(cls: ClassSummary, section: SectionSummary | null) {
    setSectionTarget({ cls, section });
    setSectionFormOpen(true);
  }

  async function confirmDeleteClass() {
    if (!deletingClass) return;
    await deleteClass.mutateAsync(deletingClass.id);
    setDeletingClass(null);
  }

  async function confirmDeleteSection() {
    if (!deletingSection) return;
    await deleteSection.mutateAsync({
      sectionId: deletingSection.section.id,
      classId: deletingSection.cls.id,
    });
    setDeletingSection(null);
  }

  return (
    <>
      <PageHeader
        title={m.title}
        description={m.description}
        actions={
          canManage ? (
            <Button onClick={openCreateClass}>
              <Plus />
              {m.addClass}
            </Button>
          ) : null
        }
      />

      {query.isLoading ? (
        <ClassesSkeleton />
      ) : query.isError ? (
        <Card>
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </Card>
      ) : classes.length === 0 ? (
        <Card>
          <EmptyState
            icon={Layers}
            title={bound ? m.unassignedTitle : m.noClasses}
            description={bound ? m.unassignedDescription : m.noClassesHint}
            action={
              canManage ? (
                <Button size="sm" onClick={openCreateClass}>
                  <Plus />
                  {m.addClass}
                </Button>
              ) : null
            }
          />
        </Card>
      ) : (
        <div className="space-y-4">
          {classes.map((cls) => {
            const sections = [...cls.sections].sort((a, b) => a.name.localeCompare(b.name));

            return (
              <Card key={cls.id} className="overflow-hidden">
                <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <CardTitle>{cls.name}</CardTitle>
                      <Badge variant="neutral">{fill(m.level, { level: cls.level })}</Badge>
                    </div>
                    <CardDescription className="flex items-center gap-1.5">
                      <Users className="size-3.5" aria-hidden />
                      {fill(m.studentsAcross, {
                        students: counted(m.students, cls.student_count),
                        sections: counted(m.sections, cls.section_count),
                      })}
                    </CardDescription>
                  </div>

                  {canManage ? (
                    <div className="flex shrink-0 items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openSectionForm(cls, null)}
                      >
                        <Plus />
                        {m.addSection}
                      </Button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={fill(m.actionsFor, { name: cls.name })}
                          >
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => openEditClass(cls)}>
                            {m.editClass}
                          </DropdownMenuItem>
                          <DropdownMenuItem destructive onClick={() => setDeletingClass(cls)}>
                            {m.deleteClass}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  ) : null}
                </CardHeader>

                <CardContent className="p-0">
                  {sections.length === 0 ? (
                    <EmptyState
                      icon={Layers}
                      title={m.noSections}
                      description={m.noSectionsHint}
                      action={
                        canManage ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => openSectionForm(cls, null)}
                          >
                            <Plus />
                            {m.addSection}
                          </Button>
                        ) : null
                      }
                      className="py-10"
                    />
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>{m.colSection}</TableHead>
                          <TableHead>{m.colClassTeacher}</TableHead>
                          <TableHead>{m.colEnrolment}</TableHead>
                          <TableHead>{m.colCapacity}</TableHead>
                          {canManage ? (
                            <TableHead className="w-12">
                              <span className="sr-only">{m.actions}</span>
                            </TableHead>
                          ) : null}
                        </TableRow>
                      </TableHeader>

                      <TableBody>
                        {sections.map((section) => {
                          const status = capacityStatus(section, capacityMessages);

                          return (
                            <TableRow key={section.id}>
                              <TableCell className="font-medium text-foreground">
                                {section.name}
                              </TableCell>
                              {/*
                                An em dash, not an empty cell. "No class teacher yet"
                                and "the name failed to load" look identical when the
                                cell is blank, and only one of them is worth acting on.
                              */}
                              <TableCell className="text-muted-foreground">
                                {section.class_teacher_name ?? (
                                  <span aria-label={m.noClassTeacher}>—</span>
                                )}
                              </TableCell>
                              <TableCell className="tabular-nums text-muted-foreground">
                                {section.capacity === null
                                  ? section.student_count
                                  : `${section.student_count} / ${section.capacity}`}
                              </TableCell>
                              <TableCell>
                                <Badge variant={status.variant}>{status.label}</Badge>
                              </TableCell>
                              {canManage ? (
                                <TableCell>
                                  <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        aria-label={fill(m.sectionActions, {
                                          section: section.name,
                                          class: cls.name,
                                        })}
                                      >
                                        <MoreHorizontal />
                                      </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                      <DropdownMenuItem
                                        onClick={() => openSectionForm(cls, section)}
                                      >
                                        {m.editSection}
                                      </DropdownMenuItem>
                                      <DropdownMenuItem
                                        destructive
                                        onClick={() => setDeletingSection({ cls, section })}
                                      >
                                        {m.deleteSection}
                                      </DropdownMenuItem>
                                    </DropdownMenuContent>
                                  </DropdownMenu>
                                </TableCell>
                              ) : null}
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {canManage ? (
        <>
          <ClassFormDialog
            open={classFormOpen}
            onOpenChange={setClassFormOpen}
            schoolClass={editingClass}
          />

          {sectionTarget ? (
            <SectionFormDialog
              open={sectionFormOpen}
              onOpenChange={setSectionFormOpen}
              classId={sectionTarget.cls.id}
              classLabel={sectionTarget.cls.name}
              section={sectionTarget.section}
              schoolId={schoolId}
            />
          ) : null}

          <ConfirmDialog
            open={Boolean(deletingClass)}
            onOpenChange={(open) => !open && setDeletingClass(null)}
            title={m.deleteClassTitle}
            description={withName(
              m.deleteClassDescription,
              <span className="font-medium text-foreground">{deletingClass?.name}</span>,
            )}
            confirmLabel={m.deleteClass}
            loading={deleteClass.isPending}
            onConfirm={confirmDeleteClass}
          />

          <ConfirmDialog
            open={Boolean(deletingSection)}
            onOpenChange={(open) => !open && setDeletingSection(null)}
            title={m.deleteSectionTitle}
            description={withName(
              m.deleteSectionDescription,
              <span className="font-medium text-foreground">
                {deletingSection?.cls.name} — {deletingSection?.section.name}
              </span>,
            )}
            confirmLabel={m.deleteSection}
            loading={deleteSection.isPending}
            onConfirm={confirmDeleteSection}
          />
        </>
      ) : null}
    </>
  );
}
