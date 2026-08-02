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
import { useClassSummary, useDeleteClass, useDeleteSection } from "@/hooks/use-classes";
import type { ClassSummary, SectionSummary } from "@/lib/api/types";
import { ClassFormDialog } from "./class-form-dialog";
import { SectionFormDialog } from "./section-form-dialog";

type BadgeVariant = "neutral" | "success" | "warning" | "destructive" | "outline";

/**
 * Seat pressure for a section.
 *
 * An over-subscribed section is an operational problem — students without a
 * desk — so it is escalated to the destructive variant rather than being left
 * as a number the admin has to compare by eye.
 */
function capacityStatus(section: SectionSummary): { label: string; variant: BadgeVariant } {
  if (section.capacity === null) return { label: "No limit set", variant: "outline" };

  const remaining = section.capacity - section.student_count;
  if (remaining < 0) {
    return { label: `Over by ${Math.abs(remaining)}`, variant: "destructive" };
  }
  if (remaining === 0) return { label: "Full", variant: "warning" };
  if (remaining <= Math.max(1, Math.round(section.capacity * 0.1))) {
    return { label: `${remaining} seat${remaining === 1 ? "" : "s"} left`, variant: "warning" };
  }
  return { label: `${remaining} seats left`, variant: "success" };
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

export function ClassesView({ canManage }: { canManage: boolean }) {
  const query = useClassSummary();
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
        title="Classes & sections"
        description="The structure of your school: every class, its sections, and how full they are."
        actions={
          canManage ? (
            <Button onClick={openCreateClass}>
              <Plus />
              Add class
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
            title="No classes yet"
            description="Create your first class, then add the sections students will be seated in."
            action={
              canManage ? (
                <Button size="sm" onClick={openCreateClass}>
                  <Plus />
                  Add class
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
                      <Badge variant="neutral">Level {cls.level}</Badge>
                    </div>
                    <CardDescription className="flex items-center gap-1.5">
                      <Users className="size-3.5" aria-hidden />
                      {cls.student_count} student{cls.student_count === 1 ? "" : "s"} across{" "}
                      {cls.section_count} section{cls.section_count === 1 ? "" : "s"}
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
                        Add section
                      </Button>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Actions for ${cls.name}`}
                          >
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => openEditClass(cls)}>
                            Edit class
                          </DropdownMenuItem>
                          <DropdownMenuItem destructive onClick={() => setDeletingClass(cls)}>
                            Delete class
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
                      title="No sections in this class"
                      description="Students are seated in sections, so add at least one before enrolling."
                      action={
                        canManage ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => openSectionForm(cls, null)}
                          >
                            <Plus />
                            Add section
                          </Button>
                        ) : null
                      }
                      className="py-10"
                    />
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Section</TableHead>
                          <TableHead>Enrolment</TableHead>
                          <TableHead>Capacity</TableHead>
                          {canManage ? (
                            <TableHead className="w-12">
                              <span className="sr-only">Actions</span>
                            </TableHead>
                          ) : null}
                        </TableRow>
                      </TableHeader>

                      <TableBody>
                        {sections.map((section) => {
                          const status = capacityStatus(section);

                          return (
                            <TableRow key={section.id}>
                              <TableCell className="font-medium text-foreground">
                                {section.name}
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
                                        aria-label={`Actions for section ${section.name} of ${cls.name}`}
                                      >
                                        <MoreHorizontal />
                                      </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                      <DropdownMenuItem
                                        onClick={() => openSectionForm(cls, section)}
                                      >
                                        Edit section
                                      </DropdownMenuItem>
                                      <DropdownMenuItem
                                        destructive
                                        onClick={() => setDeletingSection({ cls, section })}
                                      >
                                        Delete section
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
            />
          ) : null}

          <ConfirmDialog
            open={Boolean(deletingClass)}
            onOpenChange={(open) => !open && setDeletingClass(null)}
            title="Delete class?"
            description={
              <>
                <span className="font-medium text-foreground">{deletingClass?.name}</span> will be
                removed. Classes that still contain sections or students cannot be deleted.
              </>
            }
            confirmLabel="Delete class"
            loading={deleteClass.isPending}
            onConfirm={confirmDeleteClass}
          />

          <ConfirmDialog
            open={Boolean(deletingSection)}
            onOpenChange={(open) => !open && setDeletingSection(null)}
            title="Delete section?"
            description={
              <>
                <span className="font-medium text-foreground">
                  {deletingSection?.cls.name} — {deletingSection?.section.name}
                </span>{" "}
                will be removed. Sections with students still assigned cannot be deleted.
              </>
            }
            confirmLabel="Delete section"
            loading={deleteSection.isPending}
            onConfirm={confirmDeleteSection}
          />
        </>
      ) : null}
    </>
  );
}
