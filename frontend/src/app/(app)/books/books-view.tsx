"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Library, Plus, Search } from "lucide-react";

import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { NativeSelect } from "@/components/ui/native-select";
import { useBooks } from "@/hooks/use-books";
import { useClassSummary } from "@/hooks/use-classes";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { BookFormDialog } from "./book-form-dialog";
import { LibraryDialog } from "./library-dialog";

/** Fills whole rows of the two- and three-column grid. */
const PAGE_SIZE = 12;

export function BooksView({ canWrite }: { canWrite: boolean }) {
  const router = useRouter();
  const classes = useClassSummary();
  const [classId, setClassId] = React.useState("");
  const [search, setSearch] = React.useState("");
  const debouncedSearch = useDebouncedValue(search.trim(), 300);
  const [page, setPage] = React.useState(1);

  // A new search starts again at page 1, adjusted during render so the stale page
  // is never fetched against the new term.
  const [searched, setSearched] = React.useState(debouncedSearch);
  if (debouncedSearch !== searched) {
    setSearched(debouncedSearch);
    setPage(1);
  }

  // The class filter, the search and the page are applied by the API in the
  // database; only this page's books are sent.
  const books = useBooks({
    class_id: classId || null,
    q: debouncedSearch || null,
    page,
    size: PAGE_SIZE,
  });
  const [open, setOpen] = React.useState(false);
  const [browsing, setBrowsing] = React.useState(false);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Books"
        description="Textbooks for each class, uploaded chapter by chapter. An AI agent reads every page, puts the pages in order, checks each upload against the chapter list and indexes the text for search. Books are shared between schools: one already uploaded elsewhere is added from the library."
        actions={
          canWrite ? (
            <>
              <Button variant="outline" onClick={() => setBrowsing(true)}>
                <Library /> Browse library
              </Button>
              <Button onClick={() => setOpen(true)}>
                <Plus /> Add book
              </Button>
            </>
          ) : null
        }
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="relative w-full sm:w-72">
          <Search
            className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by title or publisher…"
            aria-label="Search books by title or publisher"
            maxLength={200}
            className="ps-9"
          />
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="books-class" className="text-sm text-muted-foreground">
            Class
          </label>
          <NativeSelect
            id="books-class"
            className="w-56"
            value={classId}
            onChange={(event) => {
              setClassId(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All classes</option>
            {classes.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>

      {books.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : books.isError ? (
        <ErrorState error={books.error} onRetry={() => void books.refetch()} />
      ) : !books.data?.items.length ? (
        <Card>
          <EmptyState
            icon={Library}
            title={
              debouncedSearch
                ? "No books match"
                : classId
                  ? "No books for this class yet"
                  : "No books yet"
            }
            description={
              debouncedSearch
                ? "Try another title or publisher, or clear the search."
                : "Add a book from the library, or upload a new one: its chapter list first, then each chapter as a PDF or as photos of its pages."
            }
            action={
              canWrite && !debouncedSearch ? (
                <div className="flex flex-wrap justify-center gap-2">
                  <Button variant="outline" onClick={() => setBrowsing(true)}>
                    <Library /> Browse library
                  </Button>
                  <Button variant="outline" onClick={() => setOpen(true)}>
                    <Plus /> Add book
                  </Button>
                </div>
              ) : null
            }
          />
        </Card>
      ) : (
        <div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {books.data.items.map((book) => {
              const done =
                book.chapter_count > 0 && book.ready_chapter_count === book.chapter_count;
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
                        {book.from_library ? (
                          <span className="truncate text-xs text-muted-foreground">
                            from the library
                          </span>
                        ) : book.created_by_name ? (
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
          <Pagination meta={books.data.meta} onPageChange={setPage} disabled={books.isFetching} />
        </div>
      )}

      <BookFormDialog
        open={open}
        onOpenChange={setOpen}
        book={null}
        onCreated={(book) => router.push(`/books/${book.id}` as Route)}
        onBrowseLibrary={() => {
          setOpen(false);
          setBrowsing(true);
        }}
      />
      <LibraryDialog
        open={browsing}
        onOpenChange={setBrowsing}
        onUploadInstead={() => {
          setBrowsing(false);
          setOpen(true);
        }}
      />
    </div>
  );
}
