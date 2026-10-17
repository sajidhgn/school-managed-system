"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Library, Plus } from "lucide-react";

import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { NativeSelect } from "@/components/ui/native-select";
import { useBooks } from "@/hooks/use-books";
import { useClassSummary } from "@/hooks/use-classes";
import { BookFormDialog } from "./book-form-dialog";

export function BooksView({ canWrite }: { canWrite: boolean }) {
  const router = useRouter();
  const classes = useClassSummary();
  const [classId, setClassId] = React.useState("");
  const books = useBooks(classId || null);
  const [open, setOpen] = React.useState(false);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Books"
        description="Textbooks for each class, uploaded chapter by chapter. An AI agent reads every page, puts the pages in order, checks each upload against the chapter list and indexes the text for search."
        actions={
          canWrite ? (
            <Button onClick={() => setOpen(true)}>
              <Plus /> Add book
            </Button>
          ) : null
        }
      />

      <div className="flex items-center gap-2">
        <label htmlFor="books-class" className="text-sm text-muted-foreground">
          Class
        </label>
        <NativeSelect
          id="books-class"
          className="w-56"
          value={classId}
          onChange={(event) => setClassId(event.target.value)}
        >
          <option value="">All classes</option>
          {classes.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </NativeSelect>
      </div>

      {books.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : books.isError ? (
        <ErrorState error={books.error} onRetry={() => void books.refetch()} />
      ) : !books.data?.length ? (
        <Card>
          <EmptyState
            icon={Library}
            title={classId ? "No books for this class yet" : "No books yet"}
            description="Add a book with its chapter list, then upload each chapter as a PDF or as photos of its pages."
            action={
              canWrite ? (
                <Button variant="outline" onClick={() => setOpen(true)}>
                  <Plus /> Add book
                </Button>
              ) : null
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {books.data.map((book) => {
            const done = book.chapter_count > 0 && book.ready_chapter_count === book.chapter_count;
            return (
              <Link
                key={book.id}
                href={`/books/${book.id}` as Route}
                className="group rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Card className="h-full transition-colors group-hover:border-primary/40">
                  <CardContent className="space-y-3 p-5">
                    <div className="space-y-1">
                      <p className="font-semibold leading-snug">{book.title}</p>
                      <p className="text-sm text-muted-foreground">
                        {book.class_name}
                        {book.subject_name ? ` · ${book.subject_name}` : ""}
                      </p>
                    </div>
                    <p className="text-sm">
                      {book.publisher} <span className="text-muted-foreground">·</span>{" "}
                      {book.version}
                    </p>
                    <div className="flex items-center justify-between gap-2">
                      <Badge variant={done ? "success" : "neutral"}>
                        {book.ready_chapter_count} / {book.chapter_count} chapters ready
                      </Badge>
                      {book.created_by_name ? (
                        <span className="truncate text-xs text-muted-foreground">
                          by {book.created_by_name}
                        </span>
                      ) : null}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}

      <BookFormDialog
        open={open}
        onOpenChange={setOpen}
        book={null}
        onCreated={(book) => router.push(`/books/${book.id}` as Route)}
      />
    </div>
  );
}
