"use client";

import * as React from "react";
import { Printer } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { StudentListRow } from "@/lib/api/types";
import {
  CardPrintStyle,
  StudentCardBackView,
  StudentCardView,
  resolveCardDesign,
  type CardSchool,
} from "./student-card";

/**
 * View and print ONE student's card, exactly as the campus template says.
 *
 * Deliberately no design controls here: the template belongs to the school
 * (see `CardDesignDialog`), and a per-student tweak would mean the cards in
 * one school bag stop matching. Printing FROM the dialog keeps the office
 * workflow at one click.
 */
export function StudentIdCardDialog({
  open,
  onOpenChange,
  student,
  school,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  student: StudentListRow | null;
  school: CardSchool | null;
}) {
  if (!student) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="student-id-card-dialog max-w-lg">
        <CardPrintStyle />

        <DialogHeader>
          <DialogTitle>Student card</DialogTitle>
          <DialogDescription>
            Standard ID card size (CR80, 85.6 × 53.98 mm — the same as a bank card).
            Print at 100% scale on card stock, trim both faces along the border and
            laminate back-to-back.
          </DialogDescription>
        </DialogHeader>

        {/* Both faces print from this sheet — the print stylesheet shows the
            sheet alone and hides the Front/Back captions. */}
        <div className="student-id-card-sheet grid gap-4">
          <div className="grid gap-1">
            <p className="card-side-label text-center text-xs text-muted-foreground">Front</p>
            <StudentCardView
              student={student}
              school={school}
              config={resolveCardDesign(school)}
            />
          </div>
          <div className="grid gap-1">
            <p className="card-side-label text-center text-xs text-muted-foreground">Back</p>
            <StudentCardBackView
              student={student}
              school={school}
              config={resolveCardDesign(school)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button onClick={() => window.print()}>
            <Printer className="size-4" aria-hidden />
            Print card
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
