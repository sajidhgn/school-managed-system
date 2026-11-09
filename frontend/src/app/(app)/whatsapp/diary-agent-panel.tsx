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
import { label, type DiaryAgentSettingsWrite, type DiaryDraftStatus } from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { sharedMessages } from "@/lib/i18n/modules/shared";
import { whatsappMessages } from "@/lib/i18n/modules/whatsapp";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { cn, formatDate, formatDateTime } from "@/lib/utils";
import { fillNodes } from "@/lib/i18n/format";
import { WhatsAppBubble } from "./whatsapp-text";

/**
 * What a teacher types to mark absentees over WhatsApp. A command for the agent,
 * not UI text, so it is shown as written in every language.
 */
const ATTENDANCE_COMMAND_EXAMPLE = "Nursery-A absent 12, 13, 15";

export function DiaryAgentPanel({ canManage }: { canManage: boolean }) {
  const m = useCatalog(whatsappMessages).diary;
  return (
    <div className="space-y-6">
      <p className="max-w-3xl text-sm text-muted-foreground">{m.intro}</p>
      <p className="max-w-3xl text-sm text-muted-foreground">
        {fillNodes(m.attendance, {
          example: (
            <span className="font-medium text-foreground" dir="ltr">
              {ATTENDANCE_COMMAND_EXAMPLE}
            </span>
          ),
        })}
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
  const m = useCatalog(whatsappMessages).diary;
  if (!names.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
      <span className="me-1">{m.placeholders}</span>
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
  const m = useCatalog(whatsappMessages).diary;
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
          <CardTitle>{m.formatTitle}</CardTitle>
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
              {m.enable}
            </label>
            <div className="grid gap-1.5">
              <Label htmlFor="diary-template">{m.message}</Label>
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
              <Label htmlFor="diary-entry-template">{m.entryLine}</Label>
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
              <Label htmlFor="diary-instructions">{m.instructions}</Label>
              <Textarea
                id="diary-instructions"
                rows={3}
                value={instructions}
                disabled={!canManage}
                placeholder={m.instructionsPlaceholder}
                onChange={(event) => setInstructions(event.target.value)}
              />
            </div>
            {canManage && (
              <Button type="submit" loading={save.isPending}>
                {m.save}
              </Button>
            )}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{m.preview}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <p className="text-xs text-muted-foreground">{m.previewHint}</p>
          {!template.trim() ? (
            <EmptyState title={m.noFormat} description={m.noFormatHint} />
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

/** Badge treatment per draft state; the words are `diary.draftStatus` in the catalog. */
const DRAFT_VARIANT: Record<DiaryDraftStatus, BadgeProps["variant"]> = {
  reading: "default",
  needs_class: "warning",
  awaiting_confirmation: "warning",
  posted: "success",
  cancelled: "neutral",
  failed: "destructive",
};

function RecentDiaries() {
  const m = useCatalog(whatsappMessages).diary;
  const shared = useCatalog(sharedMessages);
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
        <CardTitle>{m.recentTitle}</CardTitle>
      </CardHeader>
      <CardContent>
        {drafts.isLoading ? (
          <TableCardSkeleton columns={5} />
        ) : drafts.isError ? (
          <ErrorState error={drafts.error} onRetry={() => void drafts.refetch()} />
        ) : !drafts.data?.items.length ? (
          <EmptyState icon={NotebookPen} title={m.noDiaries} description={m.noDiariesHint} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8">
                      <span className="sr-only">{m.expand}</span>
                    </TableHead>
                    <TableHead>{m.colDate}</TableHead>
                    <TableHead>{m.colTeacher}</TableHead>
                    <TableHead>{m.colClass}</TableHead>
                    <TableHead>{m.colStatus}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {drafts.data.items.map((draft) => {
                    const open = expanded.has(draft.id);
                    const variant = DRAFT_VARIANT[draft.status];
                    return (
                      <React.Fragment key={draft.id}>
                        <TableRow>
                          <TableCell className="align-top">
                            {draft.body && (
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-expanded={open}
                                aria-label={open ? m.hide : m.show}
                                onClick={() => toggle(draft.id)}
                              >
                                {open ? (
                                  <ChevronDown className="h-4 w-4" aria-hidden />
                                ) : (
                                  <ChevronRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
                                )}
                              </Button>
                            )}
                          </TableCell>
                          <TableCell className="whitespace-nowrap align-top">
                            <div>{draft.diary_date ? formatDate(draft.diary_date) : "—"}</div>
                            <div className="text-xs text-muted-foreground">
                              {fill(m.sentAt, { time: formatDateTime(draft.created_at) })}
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
                            <Badge variant={variant}>{label(m.draftStatus, draft.status)}</Badge>
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
                {shared.previous}
              </Button>
              <span className="text-muted-foreground">
                {fill(shared.pageOf, {
                  page: drafts.data.meta.page,
                  pages: Math.max(drafts.data.meta.pages, 1),
                })}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!drafts.data.meta.has_next}
                onClick={() => setPage((p) => p + 1)}
              >
                {shared.next}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
