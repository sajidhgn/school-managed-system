"use client";

import * as React from "react";
import Link from "next/link";
import { Printer } from "lucide-react";

import { ErrorState } from "@/components/data-states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/misc";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useExamResults } from "@/hooks/use-exams";
import type { ExamClassResults, ExamResultRow, StudentListRow } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { resolvePalette, type CardSchool } from "./student-card";

/**
 * The board letter grade for an overall percentage.
 *
 * The LEGACY Pakistani board scale (A1/A+ at 80, pass at 33) rather than the
 * post-2023 ten-band A++–U scheme: the revised scheme is still rolling out
 * board by board, and the cards schools actually hand to parents — including
 * every print-shop template this card is modelled on — carry this one. One
 * function, so switching a school to the new bands is a local edit.
 */
function gradeFor(percentage: number): { grade: string; remarks: string } {
  if (percentage >= 80) return { grade: "A+", remarks: "Excellent" };
  if (percentage >= 70) return { grade: "A", remarks: "Very Good" };
  if (percentage >= 60) return { grade: "B", remarks: "Good" };
  if (percentage >= 50) return { grade: "C", remarks: "Satisfactory" };
  if (percentage >= 40) return { grade: "D", remarks: "Fair" };
  if (percentage >= 33) return { grade: "E", remarks: "Needs improvement" };
  return { grade: "F", remarks: "Fail" };
}

/**
 * Prints ONLY the result card. Same visibility trick as `CardPrintStyle` (see
 * student-card.tsx for why the dialog shell must also be un-positioned): the
 * sheet is `display: none` on screen — the dialog's table IS the screen view —
 * and becomes the whole page in print.
 */
function ResultCardPrintStyle() {
  return (
    <style>{`
      @media print {
        body * { visibility: hidden; }
        /* The app's in-flow root would otherwise stretch the printed document
           into trailing blank pages; the dialog lives in a portal div that
           holds the sheet, which is the only body child that may keep height. */
        body > div:not(:has(.student-result-sheet)) { display: none !important; }
        .student-result-dialog {
          position: static !important;
          /* Tailwind v4 centers via the individual translate property, not
             transform — both must go, or the un-positioned dialog stays the
             sheet's containing block, shifted half a dialog off the page. */
          transform: none !important;
          translate: none !important;
          scale: none !important;
          rotate: none !important;
          max-height: none !important;
          max-width: none !important;
          overflow: visible !important;
          border: 0 !important;
          box-shadow: none !important;
          padding: 0 !important;
        }
        .student-result-sheet { display: block !important; }
        .student-result-sheet, .student-result-sheet * { visibility: visible !important; }
        .student-result-sheet {
          position: absolute;
          inset-inline-start: 0;
          top: 0;
          width: 100%;
          margin: 0;
          print-color-adjust: exact;
          -webkit-print-color-adjust: exact;
        }
      }
    `}</style>
  );
}

/** A labelled fill-in-the-blank line, the way the printed pro formas rule them. */
function BlankField({
  label,
  value,
  className,
}: {
  label: string;
  value: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 items-baseline gap-1.5", className)}>
      <span className="shrink-0 font-semibold">{label}</span>
      <span className="min-w-0 flex-1 truncate border-b border-dotted border-black px-1 text-center font-medium">
        {value}
      </span>
    </div>
  );
}

/**
 * The printable result card, in the layout Pakistani schools rule by hand and
 * order from print shops: school masthead over a registration/contact strip,
 * the Name / S/o, D/o line, class–examination–session, then the Sr# · Subjects
 * · Full Marks · Marks Obtained table with a Total row, the grade block, and
 * teacher/principal signature lines. Colours come from the school's own
 * palette so the card matches the ID cards from the same office.
 *
 * Always black-on-white regardless of app theme: it is a piece of paper.
 */
function ResultCardSheet({
  student,
  school,
  examName,
  results,
  row,
}: {
  student: StudentListRow;
  school: CardSchool | null;
  examName: string;
  results: ExamClassResults;
  row: ExamResultRow;
}) {
  const palette = resolvePalette(school);
  const primary = palette[0];
  const secondary = palette[1] ?? primary;

  const cellByPaper = new Map(row.cells.map((cell) => [cell.paper_id, cell]));
  const percentage = Number(row.percentage);
  const { grade, remarks } = gradeFor(percentage);
  // A paper under its declared pass line (or sat absent, where one is
  // declared) fails the subject; the board grade only ever softens the story,
  // so the verdict is computed from the papers, not the percentage.
  const failedPapers = results.papers.filter((paper) => {
    if (paper.pass_marks === null) return false;
    const cell = cellByPaper.get(paper.id);
    if (!cell) return false;
    if (cell.is_absent) return true;
    return cell.marks_obtained !== null && Number(cell.marks_obtained) < paper.pass_marks;
  }).length;
  const passed = failedPapers === 0 && percentage >= 33;

  const contactLine = [
    [school?.address, school?.city].filter(Boolean).join(", "),
    school?.phone,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="student-result-sheet hidden">
      <div
        className="mx-auto max-w-[180mm] border-4 border-double bg-white p-6 text-black"
        style={{ borderColor: primary }}
      >
        {/* Masthead: logo centred on top, the school name centred beneath it,
            then registration/contact and the RESULT CARD banner. */}
        <div className="text-center">
          {school?.logoUrl ? (
            // Plain <img> — school-supplied host, same as the ID card.
            // eslint-disable-next-line @next/next/no-img-element
            <img src={school.logoUrl} alt="" className="mx-auto size-20 object-contain" />
          ) : null}
          <h1
            className="mt-2 text-3xl font-extrabold uppercase leading-tight"
            style={{ color: primary }}
          >
            {school?.name ?? "School"}
          </h1>
          {school?.code ? (
            <p className="mt-1 text-sm font-semibold">Registration No: {school.code}</p>
          ) : null}
          {contactLine ? (
            <p
              className="mx-auto mt-1 inline-block rounded px-4 py-0.5 text-xs font-semibold"
              style={{ backgroundColor: secondary, color: "#ffffff" }}
            >
              {contactLine}
            </p>
          ) : null}
          <div>
            <span
              className="mt-3 inline-block rounded-md px-6 py-1 text-sm font-bold uppercase tracking-[0.2em]"
              style={{ backgroundColor: primary, color: "#ffffff" }}
            >
              Result card
            </span>
          </div>
        </div>

        {/* The pro-forma lines. S/o, D/o — son/daughter of — is the guardian
            line every Pakistani card carries; the neutral pairing covers both
            without the office striking one out. */}
        <div className="mt-5 space-y-2.5 text-sm">
          <div className="flex gap-6">
            <BlankField label="Name" value={student.full_name} className="flex-[3]" />
            <BlankField
              label="S/o, D/o"
              value={student.guardian_name ?? ""}
              className="flex-[2]"
            />
          </div>
          <div className="flex gap-6">
            <BlankField
              label="Class"
              value={
                student.class_name
                  ? `${student.class_name}${student.section_name ? ` (${student.section_name})` : ""}`
                  : ""
              }
              className="flex-1"
            />
            <BlankField label="Examination" value={examName} className="flex-[2]" />
            <BlankField
              label="Session"
              value={new Date().getFullYear()}
              className="w-32 flex-none"
            />
          </div>
          <div className="flex gap-6">
            <BlankField
              label="Admission No"
              value={student.admission_number}
              className="flex-1"
            />
            <BlankField
              label="Position in class"
              value={`${row.rank} of ${results.rows.length}`}
              className="flex-1"
            />
          </div>
        </div>

        {/* The marks table. Borders are plain black: this prints on office
            printers that drop background colour, and the ruled grid is the
            part a parent actually reads. */}
        <table className="mt-4 w-full border-collapse text-sm">
          <thead>
            <tr style={{ backgroundColor: primary, color: "#ffffff" }}>
              <th className="w-12 border border-black px-2 py-1.5">Sr.#</th>
              <th className="border border-black px-2 py-1.5 text-start">Subjects</th>
              <th className="w-24 border border-black px-2 py-1.5">Full Marks</th>
              <th className="w-24 border border-black px-2 py-1.5">Marks Obtained</th>
            </tr>
          </thead>
          <tbody>
            {results.papers.map((paper, index) => {
              const cell = cellByPaper.get(paper.id);
              return (
                <tr key={paper.id}>
                  <td className="border border-black px-2 py-1 text-center tabular-nums">
                    {index + 1}
                  </td>
                  <td className="border border-black px-2 py-1 font-medium">
                    {paper.subject_name}
                  </td>
                  <td className="border border-black px-2 py-1 text-center tabular-nums">
                    {paper.max_marks}
                  </td>
                  <td className="border border-black px-2 py-1 text-center font-medium tabular-nums">
                    {/* AB is the register's own notation for an absence; an
                        unmarked paper stays blank, exactly like a hand-ruled
                        card, rather than printing a zero nobody awarded. */}
                    {cell?.is_absent ? "AB" : (cell?.marks_obtained ?? "")}
                  </td>
                </tr>
              );
            })}
            <tr className="font-bold">
              <td className="border border-black px-2 py-1.5 text-center" colSpan={2}>
                Total
              </td>
              <td className="border border-black px-2 py-1.5 text-center tabular-nums">
                {row.total_max}
              </td>
              <td className="border border-black px-2 py-1.5 text-center tabular-nums">
                {row.total_obtained}
              </td>
            </tr>
          </tbody>
        </table>

        {/* The verdict strip: percentage, board grade, pass/fail. */}
        <div className="mt-4 flex items-stretch gap-4 text-sm">
          <div className="flex-1 border border-black p-2 text-center">
            <p className="text-xs font-semibold uppercase">Percentage</p>
            <p className="text-lg font-bold tabular-nums">{row.percentage}%</p>
          </div>
          <div className="flex-1 border border-black p-2 text-center">
            <p className="text-xs font-semibold uppercase">Grade</p>
            <p className="text-lg font-bold">{grade}</p>
          </div>
          <div className="flex-1 border border-black p-2 text-center">
            <p className="text-xs font-semibold uppercase">Result</p>
            <p className="text-lg font-bold" style={{ color: passed ? primary : "#b91c1c" }}>
              {passed ? "PASS" : "FAIL"}
            </p>
          </div>
          <div className="flex-[2] border border-black p-2 text-center">
            <p className="text-xs font-semibold uppercase">Remarks</p>
            <p className="text-lg font-bold">
              {failedPapers > 0
                ? `Failed in ${failedPapers} subject${failedPapers === 1 ? "" : "s"}`
                : remarks}
            </p>
          </div>
        </div>

        <BlankField label="General Remarks" value="" className="mt-5 text-sm" />

        {/* Signatures — the two hands every Pakistani result card is signed
            by, with room under each ruled line. */}
        <div className="mt-10 flex justify-between gap-8 text-sm">
          <div className="w-48 text-center">
            <div className="border-b border-black" />
            <p className="mt-1 font-semibold" style={{ color: primary }}>
              Teacher&apos;s Signature
            </p>
          </div>
          <div className="w-48 text-center">
            <div className="border-b border-black" />
            <p className="mt-1 font-semibold" style={{ color: primary }}>
              Principal
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * One student's paper-by-paper breakdown of the exam the directory is
 * filtered by — opened by clicking the totals in the result column.
 *
 * Reads the class result sheet the exam page already serves rather than a
 * per-student endpoint: React Query caches it by (exam, class), so checking
 * several children of the same class costs one request, which is exactly the
 * "go down the register" way the column gets used.
 */
export function StudentResultDialog({
  examId,
  examName,
  student,
  classId,
  school,
  onClose,
}: {
  examId: string;
  examName: string;
  /** The row whose numbers were clicked; null closes the dialog. */
  student: StudentListRow | null;
  /** The student's class, resolved from their section by the caller. */
  classId: string | null;
  /** Campus identity and branding, for the printable result card. */
  school: CardSchool | null;
  onClose: () => void;
}) {
  const open = Boolean(student && classId);
  const results = useExamResults(examId, open ? classId : null);

  const row = React.useMemo(
    () =>
      student
        ? results.data?.rows.find((candidate) => candidate.student_id === student.id)
        : undefined,
    [results.data, student],
  );

  // Marks come keyed by paper id, papers carry the labels — join them here so
  // a reordering on the server can never shift marks onto the wrong subject.
  const cellByPaper = React.useMemo(
    () => new Map((row?.cells ?? []).map((cell) => [cell.paper_id, cell])),
    [row],
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="student-result-dialog max-w-xl">
        <ResultCardPrintStyle />

        <DialogHeader>
          <DialogTitle>{student?.full_name ?? "Result"}</DialogTitle>
          <DialogDescription>
            {examName}
            {student?.class_name ? ` — ${student.class_name}` : ""}
            {student?.section_name ? ` · ${student.section_name}` : ""}
          </DialogDescription>
        </DialogHeader>

        {results.isPending && open ? <Skeleton className="h-40 w-full" /> : null}
        {results.isError ? (
          <ErrorState error={results.error} onRetry={() => void results.refetch()} />
        ) : null}

        {results.data && !row ? (
          // Seated in the class but on no marked sheet — possible when marks
          // were entered before a transfer. Missing data, not a zero.
          <p className="text-sm text-muted-foreground">
            No marks recorded for this student in {examName}.
          </p>
        ) : null}

        {results.data && row ? (
          <>
            <div className="max-h-[50vh] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Subject</TableHead>
                    <TableHead className="w-28 text-right">Marks</TableHead>
                    <TableHead className="w-20 text-right">Pass at</TableHead>
                    <TableHead className="w-24 text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.data.papers.map((paper) => {
                    const cell = cellByPaper.get(paper.id);
                    const marked = Boolean(cell && (cell.is_absent || cell.marks_obtained !== null));
                    const failed =
                      cell !== undefined &&
                      !cell.is_absent &&
                      cell.marks_obtained !== null &&
                      paper.pass_marks !== null &&
                      Number(cell.marks_obtained) < paper.pass_marks;
                    return (
                      <TableRow key={paper.id}>
                        <TableCell>
                          <span className="font-mono text-xs text-muted-foreground">
                            {paper.subject_code}
                          </span>{" "}
                          {paper.subject_name}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular-nums",
                            (failed || cell?.is_absent) && "text-destructive",
                          )}
                        >
                          {cell?.is_absent
                            ? `0/${paper.max_marks}`
                            : cell?.marks_obtained != null
                              ? `${cell.marks_obtained}/${paper.max_marks}`
                              : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {paper.pass_marks ?? "—"}
                        </TableCell>
                        <TableCell className="text-right">
                          {!marked ? (
                            // The paper exists but no mark was entered: the
                            // totals below exclude it, so say so rather than
                            // leaving a blank that reads as "fine".
                            <span className="text-xs text-muted-foreground">Not marked</span>
                          ) : cell?.is_absent ? (
                            <span className="text-xs font-medium text-destructive">Absent</span>
                          ) : failed ? (
                            <span className="text-xs font-medium text-destructive">Failed</span>
                          ) : paper.pass_marks !== null ? (
                            <span className="text-xs font-medium text-success">Passed</span>
                          ) : (
                            // No pass line declared — a number, not a verdict.
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>

            <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-sm">
              <span className="text-muted-foreground">
                Rank {row.rank} of {results.data.rows.length} in {results.data.class_name}
              </span>
              <span className="tabular-nums">
                <span className="font-medium">
                  {row.total_obtained}/{row.total_max}
                </span>{" "}
                <span className="text-muted-foreground">·</span>{" "}
                <span className="font-medium">{row.percentage}%</span>
              </span>
            </div>

            {student ? (
              <ResultCardSheet
                student={student}
                school={school}
                examName={examName}
                results={results.data}
                row={row}
              />
            ) : null}
          </>
        ) : null}

        <DialogFooter>
          {student ? (
            <Button variant="outline" asChild>
              <Link href={`/students/${student.id}`}>View profile</Link>
            </Button>
          ) : null}
          {results.data && row ? (
            <Button variant="outline" onClick={() => window.print()}>
              <Printer className="size-4" aria-hidden />
              Print result card
            </Button>
          ) : null}
          <Button onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
