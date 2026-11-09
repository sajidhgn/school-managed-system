"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, ClipboardList, Pencil, Plus, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  useAddPaper,
  useExam,
  useExamPapers,
  useExamResults,
  usePaperMarks,
  useRemovePaper,
  useSaveMarks,
  useUpdatePaper,
} from "@/hooks/use-exams";
import { useSubjects } from "@/hooks/use-subjects";
import type { ExamPaperRead, MarkEntry } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { examsMessages } from "@/lib/i18n/modules/exams";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { formatDate } from "@/lib/utils";
import { ExamFormDialog } from "../exam-form-dialog";

/** Add a paper, or edit an existing one's date and marks scheme. */
function PaperFormDialog({
  examId,
  open,
  onOpenChange,
  paper,
}: {
  examId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  paper: ExamPaperRead | null;
}) {
  const m = useCatalog(examsMessages).paperForm;
  const classes = useClassSummary();
  const subjects = useSubjects({ size: 100 });
  const add = useAddPaper(examId);
  const update = useUpdatePaper(examId);

  const [classId, setClassId] = React.useState("");
  const [subjectId, setSubjectId] = React.useState("");
  const [scheduledOn, setScheduledOn] = React.useState("");
  const [maxMarks, setMaxMarks] = React.useState("100");
  const [passMarks, setPassMarks] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setClassId(paper?.class_id ?? "");
      setSubjectId(paper?.subject_id ?? "");
      setScheduledOn(paper?.scheduled_on ?? "");
      setMaxMarks(String(paper?.max_marks ?? 100));
      setPassMarks(paper?.pass_marks !== null && paper ? String(paper.pass_marks) : "");
    }
  }, [open, paper]);

  const saving = add.isPending || update.isPending;

  async function save() {
    const shared = {
      scheduled_on: scheduledOn || null,
      max_marks: Number(maxMarks),
      pass_marks: passMarks === "" ? null : Number(passMarks),
    };
    if (paper) {
      await update.mutateAsync({ paperId: paper.id, body: shared });
    } else {
      await add.mutateAsync({ ...shared, class_id: classId, subject_id: subjectId });
    }
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {paper ? `${paper.class_name} · ${paper.subject_name}` : m.addTitle}
          </DialogTitle>
          <DialogDescription>{paper ? m.editDescription : m.addDescription}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          {!paper && (
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="paper-class">{m.class}</Label>
                <NativeSelect
                  id="paper-class"
                  value={classId}
                  onChange={(event) => setClassId(event.target.value)}
                >
                  <option value="" disabled>
                    {m.choose}
                  </option>
                  {(classes.data ?? []).map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="paper-subject">{m.subject}</Label>
                <NativeSelect
                  id="paper-subject"
                  value={subjectId}
                  onChange={(event) => setSubjectId(event.target.value)}
                >
                  <option value="" disabled>
                    {m.choose}
                  </option>
                  {(subjects.data?.items ?? []).map((subject) => (
                    <option key={subject.id} value={subject.id}>
                      {subject.code} — {subject.name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            </div>
          )}
          <div className="grid grid-cols-3 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="paper-date">{m.date}</Label>
              <Input
                id="paper-date"
                type="date"
                value={scheduledOn}
                onChange={(event) => setScheduledOn(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="paper-max">{m.maxMarks}</Label>
              <Input
                id="paper-max"
                type="number"
                min={1}
                value={maxMarks}
                onChange={(event) => setMaxMarks(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="paper-pass">{m.passMarks}</Label>
              <Input
                id="paper-pass"
                type="number"
                min={0}
                value={passMarks}
                placeholder="—"
                onChange={(event) => setPassMarks(event.target.value)}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            {m.cancel}
          </Button>
          <Button
            onClick={save}
            disabled={saving || (!paper && (!classId || !subjectId)) || !Number(maxMarks)}
          >
            {saving ? m.saving : paper ? m.saveChanges : m.add}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The mark sheet for one paper.
 *
 * Local draft state per row, saved as ONE bulk upsert: a teacher keys a whole
 * column and presses Save once, and a re-save after a correction overwrites.
 * Rows left completely empty are omitted from the payload, so a partial sheet
 * (marking stopped at roll 23) saves what exists and loses nothing.
 */
function MarksDialog({
  examId,
  paperId,
  onClose,
  canManage,
}: {
  examId: string;
  paperId: string | null;
  onClose: () => void;
  canManage: boolean;
}) {
  const m = useCatalog(examsMessages).marks;
  const query = usePaperMarks(paperId);
  const save = useSaveMarks(examId);

  type Draft = { marks: string; absent: boolean; remarks: string };
  const [drafts, setDrafts] = React.useState<Record<string, Draft>>({});

  React.useEffect(() => {
    if (query.data) {
      const next: Record<string, Draft> = {};
      for (const row of query.data.rows) {
        next[row.student_id] = {
          marks: row.marks_obtained !== null ? String(row.marks_obtained) : "",
          absent: row.is_absent,
          remarks: row.remarks ?? "",
        };
      }
      setDrafts(next);
    }
  }, [query.data]);

  const paper = query.data?.paper;
  const setDraft = (studentId: string, patch: Partial<Draft>) =>
    setDrafts((current) => ({
      ...current,
      [studentId]: { ...current[studentId], ...patch },
    }));

  const entries: MarkEntry[] = Object.entries(drafts)
    .filter(([, draft]) => draft.absent || draft.marks.trim() !== "")
    .map(([studentId, draft]) => ({
      student_id: studentId,
      marks_obtained: draft.absent ? null : draft.marks.trim(),
      is_absent: draft.absent,
      remarks: draft.remarks.trim() || null,
    }));

  const overMax = paper
    ? entries.filter(
        (entry) =>
          entry.marks_obtained !== null && Number(entry.marks_obtained) > paper.max_marks,
      ).length
    : 0;

  async function submit() {
    if (!paperId || entries.length === 0) return;
    await save.mutateAsync({ paperId, body: { entries } });
    onClose();
  }

  return (
    <Dialog open={paperId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {paper ? `${paper.class_name} · ${paper.subject_name}` : m.title}
          </DialogTitle>
          <DialogDescription>
            {paper
              ? paper.pass_marks !== null
                ? fill(m.outOfWithPass, { max: paper.max_marks, pass: paper.pass_marks })
                : fill(m.outOf, { max: paper.max_marks })
              : ""}
          </DialogDescription>
        </DialogHeader>

        {query.isPending && <Skeleton className="h-40 w-full" />}
        {query.isError && (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        )}

        {query.data && (
          <div className="max-h-[50vh] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-24">{m.colRoll}</TableHead>
                  <TableHead>{m.colStudent}</TableHead>
                  <TableHead className="w-24">{m.colMarks}</TableHead>
                  <TableHead className="w-20">{m.colAbsent}</TableHead>
                  <TableHead>{m.colRemarks}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data.rows.map((row) => {
                  const draft = drafts[row.student_id] ?? {
                    marks: "",
                    absent: false,
                    remarks: "",
                  };
                  const invalid =
                    paper !== undefined &&
                    draft.marks.trim() !== "" &&
                    Number(draft.marks) > paper.max_marks;
                  return (
                    <TableRow key={row.student_id}>
                      <TableCell className="font-mono text-xs">
                        {row.admission_number}
                      </TableCell>
                      <TableCell className="font-medium">{row.full_name}</TableCell>
                      <TableCell>
                        <Input
                          type="number"
                          min={0}
                          step="0.5"
                          value={draft.marks}
                          disabled={!canManage || draft.absent}
                          aria-invalid={invalid || undefined}
                          aria-label={fill(m.marksFor, { name: row.full_name })}
                          onChange={(event) =>
                            setDraft(row.student_id, { marks: event.target.value })
                          }
                          className="h-8"
                        />
                      </TableCell>
                      <TableCell className="text-center">
                        <input
                          type="checkbox"
                          checked={draft.absent}
                          disabled={!canManage}
                          aria-label={fill(m.absentFor, { name: row.full_name })}
                          onChange={(event) =>
                            setDraft(row.student_id, {
                              absent: event.target.checked,
                              ...(event.target.checked ? { marks: "" } : {}),
                            })
                          }
                          className="size-4 accent-primary"
                        />
                      </TableCell>
                      <TableCell>
                        <Input
                          value={draft.remarks}
                          disabled={!canManage}
                          aria-label={fill(m.remarksFor, { name: row.full_name })}
                          onChange={(event) =>
                            setDraft(row.student_id, { remarks: event.target.value })
                          }
                          className="h-8"
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}

        {overMax > 0 && paper && (
          <p role="alert" className="text-sm text-destructive">
            {overMax === 1
              ? fill(m.overMaxOne, { max: paper.max_marks })
              : fill(m.overMaxMany, { count: overMax, max: paper.max_marks })}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>
            {m.close}
          </Button>
          {canManage && (
            <Button onClick={submit} disabled={save.isPending || entries.length === 0 || overMax > 0}>
              {save.isPending
                ? m.saving
                : entries.length === 1
                  ? m.saveOne
                  : fill(m.saveMany, { count: entries.length })}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The ranked result sheet for one class of this exam. */
function ResultsCard({ examId, papers }: { examId: string; papers: ExamPaperRead[] }) {
  const m = useCatalog(examsMessages).results;
  // The classes that actually sat this exam, derived from its papers.
  const classOptions = React.useMemo(() => {
    const seen = new Map<string, string>();
    for (const paper of papers) seen.set(paper.class_id, paper.class_name);
    return [...seen.entries()];
  }, [papers]);

  const [classId, setClassId] = React.useState("");
  React.useEffect(() => {
    if (!classId && classOptions.length) setClassId(classOptions[0][0]);
  }, [classOptions, classId]);

  const results = useExamResults(examId, classId || null);

  if (papers.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{m.title}</CardTitle>
        <CardDescription>{m.description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <NativeSelect
          value={classId}
          onChange={(event) => setClassId(event.target.value)}
          aria-label={m.classAria}
          className="max-w-xs"
        >
          {classOptions.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </NativeSelect>

        {results.isPending && classId && <Skeleton className="h-32 w-full" />}
        {results.isError && (
          <ErrorState error={results.error} onRetry={() => void results.refetch()} />
        )}

        {results.data && results.data.rows.length === 0 && (
          <p className="text-sm text-muted-foreground">{m.noStudents}</p>
        )}

        {results.data && results.data.rows.length > 0 && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-14">{m.colRank}</TableHead>
                  <TableHead>{m.colStudent}</TableHead>
                  {results.data.papers.map((paper) => (
                    <TableHead key={paper.id} className="text-end">
                      <span title={paper.subject_name}>{paper.subject_code}</span>
                      <span className="block text-[10px] font-normal text-muted-foreground">
                        /{paper.max_marks}
                      </span>
                    </TableHead>
                  ))}
                  <TableHead className="text-end">{m.colTotal}</TableHead>
                  <TableHead className="w-20 text-end">%</TableHead>
                  <TableHead className="w-20">{m.colGrade}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.data.rows.map((row) => (
                  <TableRow key={row.student_id}>
                    <TableCell className="tabular-nums">{row.rank}</TableCell>
                    <TableCell>
                      <span className="font-medium">{row.full_name}</span>
                      <span className="ms-2 font-mono text-xs text-muted-foreground">
                        {row.admission_number}
                      </span>
                    </TableCell>
                    {row.cells.map((cell) => (
                      <TableCell key={cell.paper_id} className="text-end tabular-nums">
                        {cell.is_absent ? (
                          <span className="text-destructive">{m.absentShort}</span>
                        ) : cell.marks_obtained !== null ? (
                          <>
                            {cell.marks_obtained}
                            {cell.grade ? (
                              <span className="block text-[10px] text-muted-foreground">
                                {cell.grade}
                              </span>
                            ) : null}
                          </>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                    ))}
                    <TableCell className="text-end tabular-nums">
                      {row.total_obtained}/{row.total_max}
                    </TableCell>
                    <TableCell className="text-end font-medium tabular-nums">
                      {row.percentage}%
                    </TableCell>
                    <TableCell>
                      {row.grade ? (
                        <span title={row.remark ?? undefined} className="font-semibold">
                          {row.grade}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {/* The legend: which bands these grades came from, so a printed sheet can be
            read without knowing this campus's settings. */}
        {results.data && results.data.rows.length > 0 ? (
          <p className="mt-3 text-xs text-muted-foreground">
            {m.gradesLegend}{" "}
            {results.data.grading_scale
              .map((band, index, all) =>
                index === all.length - 1
                  ? fill(m.bandBelow, {
                      grade: band.grade,
                      min: all[index - 1]?.min_percent.replace(/\.00$/, "") ?? "—",
                    })
                  : fill(m.bandFrom, {
                      grade: band.grade,
                      min: band.min_percent.replace(/\.00$/, ""),
                    }),
              )
              .join(" · ")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function ExamDetailView({
  examId,
  canManage,
}: {
  examId: string;
  canManage: boolean;
}) {
  const { detail: m, status: statusLabel } = useCatalog(examsMessages);
  const exam = useExam(examId);
  const papers = useExamPapers(examId);
  const removePaper = useRemovePaper(examId);

  const [editOpen, setEditOpen] = React.useState(false);
  const [paperFormOpen, setPaperFormOpen] = React.useState(false);
  const [editingPaper, setEditingPaper] = React.useState<ExamPaperRead | null>(null);
  const [marksPaperId, setMarksPaperId] = React.useState<string | null>(null);
  const [removingPaper, setRemovingPaper] = React.useState<ExamPaperRead | null>(null);

  if (exam.isError) {
    return <ErrorState error={exam.error} onRetry={() => void exam.refetch()} />;
  }

  return (
    <div className="space-y-6">
      <Link
        href="/exams"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-3.5 w-3.5 rtl:rotate-180" aria-hidden />
        {m.allExams}
      </Link>

      {exam.isPending ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <PageHeader
          title={exam.data.name}
          description={
            exam.data.start_date
              ? `${formatDate(exam.data.start_date)}${
                  exam.data.end_date ? ` – ${formatDate(exam.data.end_date)}` : ""
                }`
              : m.noDates
          }
          actions={
            <div className="flex items-center gap-2">
              <Badge
                variant={
                  exam.data.status === "published"
                    ? "success"
                    : exam.data.status === "completed"
                      ? "neutral"
                      : "outline"
                }
              >
                {statusLabel[exam.data.status]}
              </Badge>
              {canManage && (
                <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                  <Pencil className="me-1 h-3.5 w-3.5" aria-hidden />
                  {m.edit}
                </Button>
              )}
            </div>
          }
        />
      )}

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>{m.papersTitle}</CardTitle>
            <CardDescription>{m.papersDescription}</CardDescription>
          </div>
          {canManage && (
            <Button
              size="sm"
              onClick={() => {
                setEditingPaper(null);
                setPaperFormOpen(true);
              }}
            >
              <Plus className="me-1 h-4 w-4" aria-hidden />
              {m.addPaper}
            </Button>
          )}
        </CardHeader>
        <CardContent className="px-0">
          {papers.isPending && <Skeleton className="mx-6 h-24" />}
          {papers.isError && (
            <ErrorState error={papers.error} onRetry={() => void papers.refetch()} />
          )}

          {papers.data && papers.data.length === 0 && (
            <EmptyState
              icon={ClipboardList}
              title={m.noPapers}
              description={m.noPapersHint}
            />
          )}

          {papers.data && papers.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colClass}</TableHead>
                  <TableHead>{m.colSubject}</TableHead>
                  <TableHead className="w-32">{m.colDate}</TableHead>
                  <TableHead className="w-28">{m.colMaxPass}</TableHead>
                  <TableHead className="w-24">{m.colEntered}</TableHead>
                  <TableHead className="w-56" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {papers.data.map((paper) => (
                  <TableRow key={paper.id}>
                    <TableCell className="font-medium">{paper.class_name}</TableCell>
                    <TableCell>
                      <span className="font-mono text-xs text-muted-foreground">
                        {paper.subject_code}
                      </span>{" "}
                      {paper.subject_name}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {paper.scheduled_on ? formatDate(paper.scheduled_on) : "—"}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {paper.max_marks}
                      {paper.pass_marks !== null ? ` / ${paper.pass_marks}` : ""}
                    </TableCell>
                    <TableCell className="tabular-nums">{paper.marks_entered}</TableCell>
                    <TableCell className="text-end">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setMarksPaperId(paper.id)}
                      >
                        {canManage ? m.enterMarks : m.viewMarks}
                      </Button>
                      {canManage && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setEditingPaper(paper);
                              setPaperFormOpen(true);
                            }}
                          >
                            {m.edit}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setRemovingPaper(paper)}
                          >
                            <Trash2 className="h-3 w-3" aria-hidden />
                            <span className="sr-only">
                              {fill(m.removeNamed, {
                                className: paper.class_name,
                                subject: paper.subject_name,
                              })}
                            </span>
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

      <ResultsCard examId={examId} papers={papers.data ?? []} />

      {exam.data && (
        <ExamFormDialog open={editOpen} onOpenChange={setEditOpen} exam={exam.data} />
      )}
      <PaperFormDialog
        examId={examId}
        open={paperFormOpen}
        onOpenChange={setPaperFormOpen}
        paper={editingPaper}
      />
      <MarksDialog
        examId={examId}
        paperId={marksPaperId}
        onClose={() => setMarksPaperId(null)}
        canManage={canManage}
      />
      <ConfirmDialog
        open={removingPaper !== null}
        onOpenChange={(open) => !open && setRemovingPaper(null)}
        title={fill(m.removeTitle, {
          className: removingPaper?.class_name ?? "",
          subject: removingPaper?.subject_name ?? m.removeFallback,
        })}
        description={m.removeDescription}
        confirmLabel={m.remove}
        variant="destructive"
        onConfirm={() => {
          if (removingPaper) removePaper.mutate(removingPaper.id);
          setRemovingPaper(null);
        }}
      />
    </div>
  );
}
