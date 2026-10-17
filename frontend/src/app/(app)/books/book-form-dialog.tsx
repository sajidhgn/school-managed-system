"use client";

import * as React from "react";
import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
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
import { NativeSelect } from "@/components/ui/native-select";
import { useCreateBook, useUpdateBook } from "@/hooks/use-books";
import { useClassSummary } from "@/hooks/use-classes";
import { useCurriculum } from "@/hooks/use-subjects";
import type { BookDetail, BookRead } from "@/lib/api/types";

interface ChapterRow {
  key: number;
  number: string;
  title: string;
}

/**
 * Add a book -- Title, Class, Publisher, Version -- with its chapter list, or edit a
 * book's details. The chapter list is what the agent checks every upload against,
 * so it is entered here first; chapters can still be added later on the book page.
 */
export function BookFormDialog({
  open,
  onOpenChange,
  book,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  book: BookRead | null;
  onCreated?: (book: BookDetail) => void;
}) {
  const classes = useClassSummary();
  const create = useCreateBook();
  const update = useUpdateBook(book?.id ?? "");

  const [title, setTitle] = React.useState("");
  const [classId, setClassId] = React.useState("");
  const [publisher, setPublisher] = React.useState("");
  const [version, setVersion] = React.useState("");
  const [subjectId, setSubjectId] = React.useState("");
  const [rows, setRows] = React.useState<ChapterRow[]>([]);
  const nextKey = React.useRef(1);
  // The row just added by Enter / "Add chapter", so typing carries on in it.
  const focusKey = React.useRef<number | null>(null);

  const curriculum = useCurriculum(classId || null);

  React.useEffect(() => {
    if (!open) return;
    setTitle(book?.title ?? "");
    setClassId(book?.class_id ?? "");
    setPublisher(book?.publisher ?? "");
    setVersion(book?.version ?? "");
    setSubjectId(book?.subject_id ?? "");
    setRows(book ? [] : [{ key: nextKey.current++, number: "1", title: "" }]);
  }, [open, book]);

  const addRow = () =>
    setRows((current) => {
      const highest = Math.max(0, ...current.map((r) => Number(r.number) || 0));
      focusKey.current = nextKey.current;
      return [...current, { key: nextKey.current++, number: String(highest + 1), title: "" }];
    });

  React.useEffect(() => {
    if (focusKey.current === null) return;
    document.getElementById(`book-chapter-title-${focusKey.current}`)?.focus();
    focusKey.current = null;
  }, [rows]);

  const chapters = rows
    .filter((r) => r.title.trim())
    .map((r) => ({ number: Number(r.number), title: r.title.trim() }));
  const numbers = chapters.map((c) => c.number);
  const duplicateNumber = numbers.length !== new Set(numbers).size;

  const pending = create.isPending || update.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{book ? "Edit book" : "Add a book"}</DialogTitle>
          <DialogDescription>
            {book
              ? "Change the book's details. Its chapters and uploads are not affected."
              : "Enter the book's details and its chapter list as printed in the contents page. You upload each chapter's pages on the next screen."}
          </DialogDescription>
        </DialogHeader>
        <form
          id="book-form"
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (duplicateNumber) return;
            if (book) {
              update.mutate(
                {
                  title,
                  class_id: classId,
                  publisher,
                  version,
                  subject_id: subjectId || null,
                  clear_subject: !subjectId,
                },
                { onSuccess: () => onOpenChange(false) },
              );
            } else {
              create.mutate(
                {
                  title,
                  class_id: classId,
                  publisher,
                  version,
                  subject_id: subjectId || null,
                  chapters,
                },
                {
                  onSuccess: (created) => {
                    onOpenChange(false);
                    onCreated?.(created);
                  },
                },
              );
            }
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="book-title">Title</Label>
              <Input
                id="book-title"
                required
                maxLength={200}
                value={title}
                placeholder="New Countdown 5"
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="book-class">Class</Label>
              <NativeSelect
                id="book-class"
                required
                value={classId}
                onChange={(event) => {
                  setClassId(event.target.value);
                  setSubjectId("");
                }}
              >
                <option value="" disabled>
                  Choose a class
                </option>
                {classes.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="book-subject">
                Subject <span className="font-normal text-muted-foreground">(optional)</span>
              </Label>
              <NativeSelect
                id="book-subject"
                value={subjectId}
                disabled={!classId}
                onChange={(event) => setSubjectId(event.target.value)}
              >
                <option value="">No subject</option>
                {curriculum.data?.map((s) => (
                  <option key={s.subject_id} value={s.subject_id}>
                    {s.subject_name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="book-publisher">Publisher</Label>
              <Input
                id="book-publisher"
                required
                maxLength={200}
                value={publisher}
                placeholder="Oxford University Press"
                onChange={(event) => setPublisher(event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="book-version">Version</Label>
              <Input
                id="book-version"
                required
                maxLength={60}
                value={version}
                placeholder="3rd Edition, 2024"
                onChange={(event) => setVersion(event.target.value)}
              />
            </div>
          </div>

          {!book && (
            <fieldset className="space-y-2">
              <div className="flex items-center justify-between">
                <legend className="text-sm font-medium">Chapter list</legend>
                <Button type="button" variant="ghost" size="sm" onClick={addRow}>
                  <Plus /> Add chapter
                </Button>
              </div>
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {rows.map((row, index) => (
                  <div key={row.key} className="flex items-center gap-2">
                    <Input
                      aria-label={`Chapter ${index + 1} number`}
                      type="number"
                      min={1}
                      max={999}
                      className="w-20"
                      value={row.number}
                      onChange={(event) =>
                        setRows((current) =>
                          current.map((r) =>
                            r.key === row.key ? { ...r, number: event.target.value } : r,
                          ),
                        )
                      }
                    />
                    <Input
                      id={`book-chapter-title-${row.key}`}
                      aria-label={`Chapter ${index + 1} title`}
                      maxLength={200}
                      value={row.title}
                      placeholder="Chapter title"
                      onChange={(event) =>
                        setRows((current) =>
                          current.map((r) =>
                            r.key === row.key ? { ...r, title: event.target.value } : r,
                          ),
                        )
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addRow();
                        }
                      }}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label="Remove chapter"
                      onClick={() => setRows((current) => current.filter((r) => r.key !== row.key))}
                    >
                      <X />
                    </Button>
                  </div>
                ))}
              </div>
              {duplicateNumber ? (
                <p className="text-sm text-destructive">Two chapters have the same number.</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Rows without a title are skipped. Press Enter to add the next chapter.
                </p>
              )}
            </fieldset>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" form="book-form" loading={pending} disabled={duplicateNumber}>
            {book ? "Save" : "Add book"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
