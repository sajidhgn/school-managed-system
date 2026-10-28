"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toast } from "@/components/ui/use-toast";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query-keys";
import { booksApi } from "@/lib/api/resources/books";
import {
  papersApi,
  type PaperListParams,
  type QuestionBankParams,
} from "@/lib/api/resources/papers";
import type {
  PaperCreate,
  PaperDetail,
  PaperQuestionAdd,
  PaperQuestionRead,
  PaperStatus,
  PaperUpdate,
  QuestionDifficulty,
  QuestionUpdate,
} from "@/lib/api/types";

/** Statuses the agent is still working through -- the page polls while in one,
 * and the API refuses edits (409 `PAPER_BUSY`). */
export const BUSY_PAPER_STATUSES: ReadonlySet<PaperStatus> = new Set([
  "queued",
  "generating",
]);

export function usePapers(params: PaperListParams) {
  return useQuery({
    queryKey: queryKeys.papers.list(params),
    queryFn: () => papersApi.list(params),
    placeholderData: (previous) => previous,
    // A paper just created is still being written; keep its row's status honest.
    refetchInterval: (query) =>
      query.state.data?.items.some((p) => BUSY_PAPER_STATUSES.has(p.status)) ? 5000 : false,
  });
}

export function usePaper(id: string) {
  return useQuery({
    queryKey: queryKeys.papers.detail(id),
    queryFn: () => papersApi.get(id),
    // Poll only while the agent has the paper; a finished paper is not refetched.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && BUSY_PAPER_STATUSES.has(status) ? 3000 : false;
    },
  });
}

export function useQuestionBank(params: QuestionBankParams, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.papers.bank(params),
    queryFn: () => papersApi.bank(params),
    enabled,
    placeholderData: (previous) => previous,
  });
}

/**
 * The book a new paper is written from, for its chapter list. The book page's own
 * cache entry (same key), but fetched only once a book is chosen and not polled --
 * the form needs which chapters are read, not a live view of the agent.
 */
export function usePaperSourceBook(bookId: string | null) {
  return useQuery({
    queryKey: queryKeys.books.detail(bookId ?? ""),
    queryFn: () => booksApi.get(bookId as string),
    enabled: Boolean(bookId),
  });
}

function useInvalidatePapers() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.papers.all });
}

/** Write a changed question straight into the cached paper, then refresh around it
 * (section totals and the paper's total marks are the server's to recompute). */
function useEntryResult(paperId: string) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidatePapers();
  return (entry: PaperQuestionRead) => {
    queryClient.setQueryData<PaperDetail>(queryKeys.papers.detail(paperId), (paper) =>
      paper
        ? {
            ...paper,
            sections: paper.sections.map((section) => ({
              ...section,
              questions: section.questions.map((q) => (q.id === entry.id ? entry : q)),
            })),
          }
        : paper,
    );
    invalidate();
  };
}

export function useCreatePaper() {
  const invalidate = useInvalidatePapers();
  return useMutation({
    mutationFn: (body: PaperCreate) => papersApi.create(body),
    onSuccess: (paper) => {
      invalidate();
      toast.success("Paper queued", `${paper.title} — the questions are being written now.`);
    },
    onError: (error) => toast.error("Couldn't create the paper", errorMessage(error)),
  });
}

export function useUpdatePaper(paperId: string) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidatePapers();
  return useMutation({
    mutationFn: (body: PaperUpdate) => papersApi.update(paperId, body),
    onSuccess: (paper) => {
      queryClient.setQueryData(queryKeys.papers.detail(paperId), paper);
      invalidate();
      toast.success("Paper updated", paper.title);
    },
    onError: (error) => toast.error("Couldn't update the paper", errorMessage(error)),
  });
}

export function useDeletePaper() {
  const invalidate = useInvalidatePapers();
  return useMutation({
    mutationFn: (id: string) => papersApi.remove(id),
    onSuccess: () => {
      invalidate();
      toast.success("Paper deleted");
    },
    onError: (error) => toast.error("Couldn't delete the paper", errorMessage(error)),
  });
}

export function useRegeneratePaper(paperId: string) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidatePapers();
  return useMutation({
    mutationFn: () => papersApi.regenerate(paperId),
    onSuccess: (paper) => {
      queryClient.setQueryData(queryKeys.papers.detail(paperId), paper);
      invalidate();
      toast.success("Paper queued again", "New questions are being written.");
    },
    onError: (error) => toast.error("Couldn't regenerate the paper", errorMessage(error)),
  });
}

export function useAddPaperQuestion(paperId: string) {
  const invalidate = useInvalidatePapers();
  return useMutation({
    mutationFn: (body: PaperQuestionAdd) => papersApi.addQuestion(paperId, body),
    onSuccess: () => {
      invalidate();
      toast.success("Question added to the paper");
    },
    onError: (error) => toast.error("Couldn't add the question", errorMessage(error)),
  });
}

export function useUpdatePaperQuestion(paperId: string) {
  const onResult = useEntryResult(paperId);
  return useMutation({
    mutationFn: ({ entryId, body }: { entryId: string; body: QuestionUpdate }) =>
      papersApi.updateQuestion(paperId, entryId, body),
    onSuccess: (entry) => {
      onResult(entry);
      toast.success("Question saved");
    },
    onError: (error) => toast.error("Couldn't save the question", errorMessage(error)),
  });
}

export function useRemovePaperQuestion(paperId: string) {
  const invalidate = useInvalidatePapers();
  return useMutation({
    mutationFn: (entryId: string) => papersApi.removeQuestion(paperId, entryId),
    onSuccess: () => {
      invalidate();
      toast.success("Question removed", "It stays in the question bank.");
    },
    onError: (error) => toast.error("Couldn't remove the question", errorMessage(error)),
  });
}

export function useReplacePaperQuestion(paperId: string) {
  const onResult = useEntryResult(paperId);
  return useMutation({
    mutationFn: ({
      entryId,
      difficulty,
    }: {
      entryId: string;
      difficulty: QuestionDifficulty | null;
    }) => papersApi.replaceQuestion(paperId, entryId, difficulty),
    onSuccess: (entry) => {
      onResult(entry);
      toast.success("Question replaced", "The old one stays in the question bank.");
    },
    onError: (error) => toast.error("Couldn't replace the question", errorMessage(error)),
  });
}
