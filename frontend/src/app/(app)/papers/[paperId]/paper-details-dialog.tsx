"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdatePaper } from "@/hooks/use-papers";
import type { PaperDetail } from "@/lib/api/types";
import { isRtlLanguage } from "../script-font";

/**
 * The paper's printed details -- title, time allowed, instructions. The questions are
 * not touched; the book, chapters and mix are fixed once the paper is written
 * (regenerate, or make a new paper, to change those).
 */
export function PaperDetailsDialog({
  open,
  onOpenChange,
  paper,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  paper: PaperDetail;
}) {
  const update = useUpdatePaper(paper.id);
  const [title, setTitle] = React.useState("");
  const [duration, setDuration] = React.useState("");
  const [instructions, setInstructions] = React.useState("");

  React.useEffect(() => {
    if (!open) return;
    setTitle(paper.title);
    setDuration(paper.duration_minutes ? String(paper.duration_minutes) : "");
    setInstructions(paper.instructions ?? "");
  }, [open, paper]);

  const minutes = Number(duration);
  const badDuration =
    duration.trim() !== "" && (!Number.isInteger(minutes) || minutes < 5 || minutes > 600);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit paper details</DialogTitle>
          <DialogDescription>
            What prints at the top of the paper. The questions are not changed.
          </DialogDescription>
        </DialogHeader>
        <form
          id="paper-details-form"
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (badDuration || !title.trim()) return;
            update.mutate(
              {
                title: title.trim(),
                duration_minutes: duration.trim() ? minutes : null,
                instructions: instructions.trim() || null,
              },
              { onSuccess: () => onOpenChange(false) },
            );
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="paper-edit-title">Title</Label>
            <Input
              id="paper-edit-title"
              required
              maxLength={200}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="paper-edit-duration">
              Time allowed <span className="font-normal text-muted-foreground">(minutes)</span>
            </Label>
            <Input
              id="paper-edit-duration"
              type="number"
              min={5}
              max={600}
              className="w-32"
              value={duration}
              placeholder="None"
              aria-invalid={badDuration}
              onChange={(event) => setDuration(event.target.value)}
            />
            {badDuration && (
              <p className="text-sm text-destructive">Time allowed must be 5–600 minutes.</p>
            )}
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="paper-edit-instructions">
              Instructions <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Textarea
              id="paper-edit-instructions"
              dir={isRtlLanguage(paper.language) ? "rtl" : "auto"}
              lang={paper.language}
              maxLength={2000}
              rows={4}
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
            />
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={update.isPending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="paper-details-form"
            loading={update.isPending}
            disabled={badDuration}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
