"use client";

import * as React from "react";
import { ChevronDown, ChevronRight, NotebookPen } from "lucide-react";

import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import {
  useDiaryAgentPreview,
  useDiaryAgentSettings,
  useDiaryDrafts,
  useSaveDiaryAgentSettings,
} from "@/hooks/use-whatsapp";
import { errorMessage } from "@/lib/api/errors";
import type { DiaryAgentSettingsWrite, DiaryDraftStatus } from "@/lib/api/types";
import { cn, formatDate, formatDateTime } from "@/lib/utils";
import { WhatsAppBubble } from "./whatsapp-text";

export function DiaryAgentPanel({ canManage }: { canManage: boolean }) {
  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-sm text-muted-foreground">
        Teachers send a photo of the day&apos;s diary to the school&apos;s WhatsApp number. The agent
        reads it, writes it in this format, shows the teacher a preview, and posts it to the class
        group when they reply OK.
      </p>
      <p className="max-w-3xl text-sm text-muted-foreground">
        Teachers can also take attendance on the same number: a message such as{" "}
        <span className="font-medium text-foreground">Nursery-A absent 12, 13, 15</span> is matched
        to the students&apos; names, shown back, and submitted to the register when they reply OK.
      </p>
      <DiaryFormatEditor canManage={canManage} />
      <RecentDiaries />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Format
// ---------------------------------------------------------------------------

type Field = HTMLInputElement | HTMLTextAreaElement;

/** Put `token` where the caret is (replacing any selection), then restore focus after it. */
function insertAtCursor(
  field: Field | null,
  value: string,
  setValue: (next: string) => void,
  token: string,
) {
  const start = field?.selectionStart ?? value.length;
  const end = field?.selectionEnd ?? value.length;
  setValue(value.slice(0, start) + token + value.slice(end));
  requestAnimationFrame(() => {
    if (!field) return;
    field.focus();
    field.setSelectionRange(start + token.length, start + token.length);
  });
}

function PlaceholderChips({
  names,
  disabled,
  onInsert,
}: {
  names: string[];
  disabled: boolean;
  onInsert: (token: string) => void;
}) {
  if (!names.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      <span className="me-1">Placeholders:</span>
      {names.map((name) => (
        <button
          key={name}
          type="button"
          disabled={disabled}
          onClick={() => onInsert(`{${name}}`)}
          className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground transition-colors hover:bg-accent disabled:cursor-default disabled:hover:bg-muted"
        >
          {`{${name}}`}
        </button>
      ))}
    </div>
  );
}

function DiaryFormatEditor({ canManage }: { canManage: boolean }) {
  const settings = useDiaryAgentSettings();
  const save = useSaveDiaryAgentSettings();

  const [enabled, setEnabled] = React.useState(false);
  const [template, setTemplate] = React.useState("");
  const [entryTemplate, setEntryTemplate] = React.useState("");
  const [instructions, setInstructions] = React.useState("");
  const templateRef = React.useRef<HTMLTextAreaElement>(null);
  const entryRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (!settings.data) return;
    setEnabled(settings.data.enabled);
    setTemplate(settings.data.template);
    setEntryTemplate(settings.data.entry_template);
    setInstructions(settings.data.instructions ?? "");
  }, [settings.data]);

  // Memoised so the debounce only restarts when a value actually changes.
  const draft = React.useMemo<DiaryAgentSettingsWrite>(
    () => ({
      enabled,
      template,
      entry_template: entryTemplate,
      instructions: instructions.trim() || null,
    }),
    [enabled, template, entryTemplate, instructions],
  );
  const debounced = useDebouncedValue(draft, 400);
  const preview = useDiaryAgentPreview(debounced, !!settings.data);

  if (settings.isLoading) return <TableCardSkeleton columns={2} rows={4} />;
  if (settings.isError)
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;

  const stale = draft !== debounced || preview.isFetching;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Diary format</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate(draft);
            }}
          >
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                role="switch"
                checked={enabled}
                disabled={!canManage}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              Let teachers post the diary by sending a photo on WhatsApp
            </label>
            <div className="grid gap-1.5">
              <Label htmlFor="diary-template">Message</Label>
              <Textarea
                id="diary-template"
                ref={templateRef}
                rows={8}
                value={template}
                disabled={!canManage}
                className="font-mono"
                onChange={(event) => setTemplate(event.target.value)}
              />
              <PlaceholderChips
                names={settings.data?.placeholders ?? []}
                disabled={!canManage}
                onInsert={(token) =>
                  insertAtCursor(templateRef.current, template, setTemplate, token)
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="diary-entry-template">Each subject&apos;s line</Label>
              <Input
                id="diary-entry-template"
                ref={entryRef}
                value={entryTemplate}
                disabled={!canManage}
                className="font-mono"
                onChange={(event) => setEntryTemplate(event.target.value)}
              />
              <PlaceholderChips
                names={settings.data?.entry_placeholders ?? []}
                disabled={!canManage}
                onInsert={(token) =>
                  insertAtCursor(entryRef.current, entryTemplate, setEntryTemplate, token)
                }
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="diary-instructions">Instructions for the agent (optional)</Label>
              <Textarea
                id="diary-instructions"
                rows={3}
                value={instructions}
                disabled={!canManage}
                placeholder="Keep Urdu homework in Urdu. Call Maths 'Mathematics'."
                onChange={(event) => setInstructions(event.target.value)}
              />
            </div>
            {canManage && (
              <Button type="submit" loading={save.isPending}>
                Save format
              </Button>
            )}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Preview</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-xs text-muted-foreground">
            A sample diary in this format, as parents will see it. Updates as you type.
          </p>
          {!template.trim() ? (
            <EmptyState title="No format yet" description="Write the message to see a preview." />
          ) : preview.isError ? (
            <p className="text-sm text-destructive">{errorMessage(preview.error)}</p>
          ) : preview.data ? (
            <WhatsAppBubble
              text={preview.data.body}
              className={cn("transition-opacity", stale && "opacity-60")}
            />
          ) : (
            <TableCardSkeleton columns={1} rows={4} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recent diaries
// ---------------------------------------------------------------------------

const DRAFT_STATUS: Record<DiaryDraftStatus, { label: string; variant: BadgeProps["variant"] }> = {
  reading: { label: "Reading", variant: "default" },
  needs_class: { label: "Asked for class", variant: "warning" },
  awaiting_confirmation: { label: "Waiting for OK", variant: "warning" },
  posted: { label: "Posted", variant: "success" },
  cancelled: { label: "Cancelled", variant: "neutral" },
  failed: { label: "Failed", variant: "destructive" },
};

function RecentDiaries() {
  const [page, setPage] = React.useState(1);
  const drafts = useDiaryDrafts({ page, size: 20 });
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent diaries</CardTitle>
      </CardHeader>
      <CardContent>
        {drafts.isLoading ? (
          <TableCardSkeleton columns={5} />
        ) : drafts.isError ? (
          <ErrorState error={drafts.error} onRetry={() => void drafts.refetch()} />
        ) : !drafts.data?.items.length ? (
          <EmptyState
            icon={NotebookPen}
            title="No diaries yet"
            description="Diaries teachers send on WhatsApp appear here."
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8">
                      <span className="sr-only">Expand</span>
                    </TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Teacher</TableHead>
                    <TableHead>Class</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {drafts.data.items.map((draft) => {
                    const open = expanded.has(draft.id);
                    const status = DRAFT_STATUS[draft.status];
                    return (
                      <React.Fragment key={draft.id}>
                        <TableRow>
                          <TableCell className="align-top">
                            {draft.body && (
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-expanded={open}
                                aria-label={open ? "Hide diary" : "Show diary"}
                                onClick={() => toggle(draft.id)}
                              >
                                {open ? (
                                  <ChevronDown className="h-4 w-4" aria-hidden />
                                ) : (
                                  <ChevronRight className="h-4 w-4" aria-hidden />
                                )}
                              </Button>
                            )}
                          </TableCell>
                          <TableCell className="whitespace-nowrap align-top">
                            <div>{draft.diary_date ? formatDate(draft.diary_date) : "—"}</div>
                            <div className="text-xs text-muted-foreground">
                              Sent {formatDateTime(draft.created_at)}
                            </div>
                          </TableCell>
                          <TableCell className="align-top">{draft.teacher_name ?? "—"}</TableCell>
                          <TableCell className="align-top">
                            {draft.class_label ??
                              (draft.class_hint ? (
                                <span className="text-muted-foreground">
                                  &ldquo;{draft.class_hint}&rdquo;
                                </span>
                              ) : (
                                "—"
                              ))}
                          </TableCell>
                          <TableCell className="max-w-xs align-top">
                            <Badge variant={status.variant}>{status.label}</Badge>
                            {draft.error && (
                              <p className="mt-1 text-xs text-destructive">{draft.error}</p>
                            )}
                          </TableCell>
                        </TableRow>
                        {open && draft.body && (
                          <TableRow className="hover:bg-transparent">
                            <TableCell />
                            <TableCell colSpan={4}>
                              <WhatsAppBubble text={draft.body} className="max-w-xl" />
                            </TableCell>
                          </TableRow>
                        )}
                      </React.Fragment>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2 text-sm">
              <Button
                variant="outline"
                size="sm"
                disabled={!drafts.data.meta.has_prev}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="text-muted-foreground">
                Page {drafts.data.meta.page} of {Math.max(drafts.data.meta.pages, 1)}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!drafts.data.meta.has_next}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
