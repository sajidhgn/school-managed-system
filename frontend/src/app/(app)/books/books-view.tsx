"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Library, Plus, Search, Sparkles } from "lucide-react";

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
import { fill } from "@/lib/i18n/format";
import { booksMessages } from "@/lib/i18n/modules/books";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { BookFormDialog } from "./book-form-dialog";
import { LibraryDialog } from "./library-dialog";

/** Fills whole rows of the two- and three-column grid. */
const PAGE_SIZE = 12;

export function BooksView({ canWrite }: { canWrite: boolean }) {
  const m = useCatalog(booksMessages).list;
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
        title={m.title}
        description={m.description}
        actions={
          <>
            {/* For every reader, not only writers: asking changes nothing. */}
            <Button variant="outline" asChild>
              <Link href="/books/ask">
                <Sparkles /> {m.askLibrary}
              </Link>
            </Button>
            {canWrite ? (
              <>
                <Button variant="outline" onClick={() => setBrowsing(true)}>
                  <Library /> {m.browseLibrary}
                </Button>
                <Button onClick={() => setOpen(true)}>
                  <Plus /> {m.addBook}
                </Button>
              </>
            ) : null}
          </>
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
            placeholder={m.searchPlaceholder}
            aria-label={m.searchAria}
            maxLength={200}
            className="ps-9"
          />
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="books-class" className="text-sm text-muted-foreground">
            {m.classLabel}
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
            <option value="">{m.allClasses}</option>
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
                ? m.noMatch
                : classId
                  ? m.noBooksForClass
                  : m.noBooks
            }
            description={
              debouncedSearch
                ? m.noMatchHint
                : m.emptyHint
            }
            action={
              canWrite && !debouncedSearch ? (
                <div className="flex flex-wrap justify-center gap-2">
                  <Button variant="outline" onClick={() => setBrowsing(true)}>
                    <Library /> {m.browseLibrary}
                  </Button>
                  <Button variant="outline" onClick={() => setOpen(true)}>
                    <Plus /> {m.addBook}
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
                          {fill(m.chaptersReady, {
                            ready: book.ready_chapter_count,
                            total: book.chapter_count,
                          })}
                        </Badge>
                        {book.from_library ? (
                          <span className="truncate text-xs text-muted-foreground">
                            {m.fromLibrary}
                          </span>
                        ) : book.created_by_name ? (
                          <span className="truncate text-xs text-muted-foreground">
                            {fill(m.byName, { name: book.created_by_name })}
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
