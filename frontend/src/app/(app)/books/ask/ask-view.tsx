"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, BookOpen, Loader2, Search, Sparkles } from "lucide-react";

import { ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { SimpleMarkdown } from "@/components/ui/simple-markdown";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/misc";
import { useAskLibrary, useBooks, useLibrarySearch } from "@/hooks/use-books";
import { useClassSummary } from "@/hooks/use-classes";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useSubjects } from "@/hooks/use-subjects";
import type { LibraryScopeParams } from "@/lib/api/resources/books";
import type { LibraryHit } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { booksMessages } from "@/lib/i18n/modules/books";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { cn } from "@/lib/utils";

/**
 * Ask the library a question, or search it for passages.
 *
 * =============================================================================
 * THE ANSWER MAY ONLY COME FROM THE BOOKS
 * =============================================================================
 *   The model writes from the passages the search found and cites them as [1], [2].
 *   When the books do not cover the question it says so (`found: false`) instead of
 *   answering from general knowledge — a teacher preparing a lesson needs to know
 *   the textbook's version, not a plausible one. Every citation links to the source
 *   passage below it, with its chapter and printed page, so the claim can be checked.
 *
 * SEARCH IS THE CHEAP HALF
 *   Passage search runs as you type (meaning + keywords, no model writing). Asking is
 *   a button, because each question is a paid model call.
 */
export function AskLibraryView() {
  const m = useCatalog(booksMessages).ask;
  const searchParams = useSearchParams();
  const classes = useClassSummary();
  const subjects = useSubjects({ size: 100 });
  const books = useBooks({ size: 100 });

  const [scope, setScope] = React.useState<LibraryScopeParams>(() => ({
    book_id: searchParams.get("book"),
  }));

  const scopedBooks = (books.data?.items ?? []).filter(
    (book) =>
      (!scope.class_id || book.class_id === scope.class_id) &&
      (!scope.subject_id || book.subject_id === scope.subject_id),
  );
  const chosenBook = (books.data?.items ?? []).find((book) => book.id === scope.book_id);

  function setFilter(key: keyof LibraryScopeParams, value: string) {
    setScope((current) => {
      const next = { ...current, [key]: value || null };
      // A book outside the newly chosen class or subject would silently match nothing.
      if (key !== "book_id") next.book_id = null;
      return next;
    });
  }

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <Link
        href="/books"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden />
        {m.back}
      </Link>

      <PageHeader
        title={m.title}
        description={m.description}
      />

      <Card>
        <CardContent className="grid gap-3 pt-6 sm:grid-cols-3">
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">{m.class}</span>
            <NativeSelect
              value={scope.class_id ?? ""}
              onChange={(event) => setFilter("class_id", event.target.value)}
            >
              <option value="">{m.allClasses}</option>
              {classes.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">{m.subject}</span>
            <NativeSelect
              value={scope.subject_id ?? ""}
              onChange={(event) => setFilter("subject_id", event.target.value)}
            >
              <option value="">{m.allSubjects}</option>
              {subjects.data?.items.map((subject) => (
                <option key={subject.id} value={subject.id}>
                  {subject.name}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">{m.book}</span>
            <NativeSelect
              value={scope.book_id ?? ""}
              onChange={(event) => setFilter("book_id", event.target.value)}
            >
              <option value="">{m.allBooks}</option>
              {/* Keep a book chosen from its own page even before the list loads. */}
              {scope.book_id && !scopedBooks.some((b) => b.id === scope.book_id) ? (
                <option value={scope.book_id}>{chosenBook?.title ?? m.thisBook}</option>
              ) : null}
              {scopedBooks.map((book) => (
                <option key={book.id} value={book.id}>
                  {book.title} · {book.class_name}
                </option>
              ))}
            </NativeSelect>
          </label>
        </CardContent>
      </Card>

      <Tabs defaultValue="ask">
        <TabsList>
          <TabsTrigger value="ask">
            <Sparkles className="me-1.5 size-4" aria-hidden />
            {m.askTab}
          </TabsTrigger>
          <TabsTrigger value="search">
            <Search className="me-1.5 size-4" aria-hidden />
            {m.searchTab}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="ask" className="mt-4">
          <AskPanel scope={scope} />
        </TabsContent>
        <TabsContent value="search" className="mt-4">
          <SearchPanel scope={scope} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ask
// ---------------------------------------------------------------------------

function AskPanel({ scope }: { scope: LibraryScopeParams }) {
  const m = useCatalog(booksMessages).ask;
  const ask = useAskLibrary();
  const [question, setQuestion] = React.useState("");
  const [highlight, setHighlight] = React.useState<number | null>(null);
  const trimmed = question.trim();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (trimmed.length < 3 || ask.isPending) return;
    setHighlight(null);
    ask.mutate({ question: trimmed, ...scope });
  }

  const answer = ask.data;
  const cited = new Set(answer?.cited ?? []);

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="grid gap-2">
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit(event);
          }}
          rows={3}
          maxLength={500}
          placeholder={m.questionPlaceholder}
          aria-label={m.questionAria}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" loading={ask.isPending} disabled={trimmed.length < 3}>
            <Sparkles className="size-4" aria-hidden />
            {m.ask}
          </Button>
          <span className="text-xs text-muted-foreground">
            {m.askHint}
          </span>
        </div>
      </form>

      {ask.isPending ? (
        <Card>
          <CardContent className="flex items-center gap-2 pt-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {m.readingBooks}
          </CardContent>
        </Card>
      ) : ask.isError ? (
        <ErrorState error={ask.error} onRetry={() => ask.reset()} />
      ) : answer ? (
        <div className="space-y-4">
          <Card className={cn(!answer.found && "border-dashed")}>
            <CardContent className="space-y-2 pt-6">
              {!answer.found ? (
                <Badge variant="neutral">{m.notCovered}</Badge>
              ) : null}
              <SimpleMarkdown
                text={answer.answer}
                className="text-sm leading-relaxed"
                renderCitation={(n, key) =>
                  answer.sources[n - 1] ? (
                    <button
                      key={key}
                      type="button"
                      onClick={() => {
                        setHighlight(n);
                        document
                          .getElementById(`source-${n}`)
                          ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                      }}
                      className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded bg-primary/10 px-1 align-baseline text-[11px] font-semibold text-primary hover:bg-primary/20"
                      aria-label={fill(m.sourceAria, { n })}
                    >
                      {n}
                    </button>
                  ) : (
                    <span key={key}>[{n}]</span>
                  )
                }
              />
            </CardContent>
          </Card>

          {answer.sources.length > 0 ? (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-muted-foreground">{m.sources}</h3>
              <ol className="space-y-2">
                {answer.sources.map((hit, index) => (
                  <HitCard
                    key={hit.chunk_id}
                    hit={hit}
                    number={index + 1}
                    cited={cited.has(index + 1)}
                    highlighted={highlight === index + 1}
                  />
                ))}
              </ol>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

function SearchPanel({ scope }: { scope: LibraryScopeParams }) {
  const m = useCatalog(booksMessages).ask;
  const [q, setQ] = React.useState("");
  const debounced = useDebouncedValue(q.trim(), 450);
  const results = useLibrarySearch(debounced, scope);

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search
          className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder={m.searchPlaceholder}
          aria-label={m.searchAria}
          maxLength={500}
          className="ps-9"
        />
      </div>
      {debounced.length < 2 ? null : results.isFetching && !results.data ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden /> {m.searching}
        </p>
      ) : results.isError ? (
        <ErrorState error={results.error} />
      ) : !results.data?.length ? (
        <p className="text-sm text-muted-foreground">{m.noHits}</p>
      ) : (
        <ol className="space-y-2">
          {results.data.map((hit) => (
            <HitCard key={hit.chunk_id} hit={hit} showScore />
          ))}
        </ol>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// One passage
// ---------------------------------------------------------------------------

function HitCard({
  hit,
  number,
  cited,
  highlighted,
  showScore,
}: {
  hit: LibraryHit;
  number?: number;
  cited?: boolean;
  highlighted?: boolean;
  showScore?: boolean;
}) {
  const { ask: m, refs } = useCatalog(booksMessages);
  const pages =
    hit.printed_start !== null
      ? hit.printed_start === hit.printed_end
        ? fill(refs.page, { n: hit.printed_start })
        : fill(refs.pageRange, { start: hit.printed_start, end: hit.printed_end ?? "" })
      : fill(refs.pagePositions, { start: hit.page_start, end: hit.page_end });

  return (
    <li
      id={number ? `source-${number}` : undefined}
      className={cn(
        "rounded-lg border border-border p-3 transition-colors",
        highlighted && "border-primary bg-primary/5",
        number !== undefined && !cited && "opacity-70",
      )}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {number !== undefined ? (
          <span className="inline-flex h-5 min-w-5 items-center justify-center rounded bg-primary/10 px-1 font-semibold text-primary">
            {number}
          </span>
        ) : null}
        <Link
          href={`/books/${hit.book_id}`}
          className="inline-flex items-center gap-1 font-medium text-foreground hover:underline"
        >
          <BookOpen className="size-3.5" aria-hidden />
          {hit.book_title}
        </Link>
        <span>
          {fill(m.hitChapter, { number: hit.chapter_number, title: hit.chapter_title })}
        </span>
        <span>{pages}</span>
        {showScore ? (
          <Badge variant="outline">
            {fill(refs.match, { percent: Math.round(hit.score * 100) })}
          </Badge>
        ) : null}
        {number !== undefined && !cited ? <span>{m.readNotCited}</span> : null}
      </div>
      <p className="line-clamp-5 whitespace-pre-line text-sm">{hit.content}</p>
    </li>
  );
}
