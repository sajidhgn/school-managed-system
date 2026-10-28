"use client";

import * as React from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FileQuestion, Loader2, Plus, Search } from "lucide-react";

import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
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
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { BUSY_PAPER_STATUSES, usePapers } from "@/hooks/use-papers";
import type { PaperStatus } from "@/lib/api/types";
import { formatDate } from "@/lib/utils";
import { PaperFormDialog } from "./paper-form-dialog";
import {
  LANGUAGE_LABELS,
  PAPER_DIFFICULTY_LABELS,
  PAPER_STATUS,
  PAPER_TYPE_LABELS,
} from "./paper-meta";

const PAGE_SIZE = 20;

export function PapersView({ canWrite }: { canWrite: boolean }) {
  const router = useRouter();
  const classes = useClassSummary();
  const [classId, setClassId] = React.useState("");
  const [status, setStatus] = React.useState<PaperStatus | "">("");
  const [search, setSearch] = React.useState("");
  const debouncedSearch = useDebouncedValue(search.trim(), 300);
  const [page, setPage] = React.useState(1);

  // A new search starts again at page 1: page 4 of the old results means nothing
  // against the new ones. Adjusted during render, so the stale page is never fetched.
  const [searched, setSearched] = React.useState(debouncedSearch);
  if (debouncedSearch !== searched) {
    setSearched(debouncedSearch);
    setPage(1);
  }

  // Search, filters and the page all go to the API, which applies them in the
  // database — only the rows on this page are ever sent.
  const papers = usePapers({
    class_id: classId || null,
    status: status || null,
    q: debouncedSearch || null,
    page,
    size: PAGE_SIZE,
  });
  const [open, setOpen] = React.useState(false);
  const filtered = Boolean(classId || status || debouncedSearch);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Test papers"
        description="Pick a book's chapters and the kind of paper you want; an AI agent writes the questions from those pages, checks each one against the book, and keeps them all in the class's question bank. Review, edit and print the paper here."
        actions={
          canWrite ? (
            <Button onClick={() => setOpen(true)}>
              <Plus /> New paper
            </Button>
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
            placeholder="Search by title…"
            aria-label="Search papers by title"
            maxLength={200}
            className="ps-9"
          />
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="papers-class" className="text-sm text-muted-foreground">
            Class
          </label>
          <NativeSelect
            id="papers-class"
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
        <div className="flex items-center gap-2">
          <label htmlFor="papers-status" className="text-sm text-muted-foreground">
            Status
          </label>
          <NativeSelect
            id="papers-status"
            className="w-44"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as PaperStatus | "");
              setPage(1);
            }}
          >
            <option value="">Any status</option>
            {(Object.keys(PAPER_STATUS) as PaperStatus[]).map((s) => (
              <option key={s} value={s}>
                {PAPER_STATUS[s].label}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>

      <Card>
        {papers.isLoading ? (
          <TableCardSkeleton columns={7} rows={4} />
        ) : papers.isError ? (
          <ErrorState error={papers.error} onRetry={() => void papers.refetch()} />
        ) : !papers.data?.items.length ? (
          <EmptyState
            icon={FileQuestion}
            title={filtered ? "No papers match" : "No test papers yet"}
            description={
              filtered
                ? "Try another title, class or status."
                : "Create a paper from the chapters of a book in the library. Only chapters the agent has read can be used."
            }
            action={
              canWrite && !filtered ? (
                <Button variant="outline" onClick={() => setOpen(true)}>
                  <Plus /> New paper
                </Button>
              ) : null
            }
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Paper</TableHead>
                  <TableHead>Class</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead className="w-36">Status</TableHead>
                  <TableHead className="w-24 text-end">Questions</TableHead>
                  <TableHead className="w-20 text-end">Marks</TableHead>
                  <TableHead className="w-40">Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {papers.data.items.map((paper) => {
                  const state = PAPER_STATUS[paper.status];
                  return (
                    <TableRow key={paper.id}>
                      <TableCell className="max-w-72">
                        <Link
                          href={`/papers/${paper.id}` as Route}
                          className="font-medium hover:underline"
                        >
                          {paper.title}
                        </Link>
                        {paper.book_title ? (
                          <p className="truncate text-xs text-muted-foreground">{paper.book_title}</p>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        {paper.class_name ?? "—"}
                        {paper.subject_name ? (
                          <p className="text-xs text-muted-foreground">{paper.subject_name}</p>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          <Badge variant="outline">{PAPER_TYPE_LABELS[paper.paper_type]}</Badge>
                          <Badge variant="neutral">{PAPER_DIFFICULTY_LABELS[paper.difficulty]}</Badge>
                          <Badge variant="neutral" lang={paper.language}>
                            {LANGUAGE_LABELS[paper.language]}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={state.variant} className="gap-1">
                          {BUSY_PAPER_STATUSES.has(paper.status) && (
                            <Loader2 className="size-3 animate-spin" />
                          )}
                          {state.label}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-end tabular-nums">{paper.question_count}</TableCell>
                      <TableCell className="text-end tabular-nums">{paper.total_marks}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(paper.created_at)}
                        {paper.created_by_name ? (
                          <p className="truncate text-xs">by {paper.created_by_name}</p>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <Pagination meta={papers.data.meta} onPageChange={setPage} disabled={papers.isFetching} />
          </>
        )}
      </Card>

      {canWrite && (
        <PaperFormDialog
          open={open}
          onOpenChange={setOpen}
          onCreated={(paper) => router.push(`/papers/${paper.id}` as Route)}
        />
      )}
    </div>
  );
}
