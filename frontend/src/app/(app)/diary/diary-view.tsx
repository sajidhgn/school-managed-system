"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight, Download, ImageIcon, NotebookPen, Printer, Share2 } from "lucide-react";

import { EmptyState, ErrorState } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/misc";
import { NativeSelect } from "@/components/ui/native-select";
import { toast } from "@/components/ui/use-toast";
import { useDiaryPage, useDiarySections, useSaveDiary } from "@/hooks/use-diary";
import type { DiaryPage, DiarySectionOption } from "@/lib/api/types";
import { diaryDayLabels, renderDiaryImage, type DiaryBranding } from "@/lib/diary-image";
import { formatDateTime } from "@/lib/utils";

/** Today as YYYY-MM-DD in the browser's own timezone -- the teacher's school day. */
function localToday(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function shiftDay(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const ACCESS_LABEL: Record<DiarySectionOption["access"], string> = {
  class_teacher: "Class teacher",
  subject_teacher: "Subject teacher",
  manage: "Coordinator",
  read: "View only",
};

function sectionLabel(option: DiarySectionOption): string {
  const filled = option.subject_count
    ? ` (${option.filled_count}/${option.subject_count})`
    : "";
  return `${option.class_name} – ${option.section_name}${filled}`;
}

export function DiaryView({
  canWrite,
  branding,
}: {
  canWrite: boolean;
  branding: DiaryBranding;
}) {
  const [date, setDate] = React.useState(localToday);
  const [sectionId, setSectionId] = React.useState<string | null>(null);

  const sections = useDiarySections(date);
  const options = React.useMemo(() => sections.data ?? [], [sections.data]);

  // Land on the caller's own class: the server lists it first.
  React.useEffect(() => {
    if (sectionId === null && options.length > 0) setSectionId(options[0].section_id);
  }, [options, sectionId]);

  const page = useDiaryPage(sectionId, date);
  const save = useSaveDiary();

  const [drafts, setDrafts] = React.useState<Record<string, string>>({});
  // Reset the drafts whenever a different page (or a freshly saved one) arrives.
  React.useEffect(() => {
    if (!page.data) return;
    setDrafts(
      Object.fromEntries(page.data.rows.map((row) => [row.subject_id, row.content ?? ""])),
    );
  }, [page.data]);

  const changed = (page.data?.rows ?? []).filter(
    (row) => row.can_edit && (drafts[row.subject_id] ?? "") !== (row.content ?? ""),
  );

  const confirmDiscard = () =>
    changed.length === 0 || window.confirm("You have unsaved diary changes. Discard them?");

  const go = (next: { date?: string; sectionId?: string }) => {
    if (!confirmDiscard()) return;
    if (next.date !== undefined) setDate(next.date);
    if (next.sectionId !== undefined) setSectionId(next.sectionId);
  };

  const onSave = () => {
    if (!sectionId || changed.length === 0) return;
    save.mutate({
      sectionId,
      date,
      body: {
        entries: changed.map((row) => ({
          subject_id: row.subject_id,
          content: drafts[row.subject_id] ?? "",
        })),
      },
    });
  };

  const [imageOpen, setImageOpen] = React.useState(false);
  const { day } = diaryDayLabels(date);
  const mine = options.filter((o) => o.access === "class_teacher" || o.access === "subject_teacher");
  const others = options.filter((o) => !mine.includes(o));
  const selected = options.find((o) => o.section_id === sectionId) ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Class diary"
        description="Daily homework for each class. Class teachers fill every subject; subject teachers fill their own."
        actions={
          page.data && (
            <Button variant="outline" onClick={() => setImageOpen(true)} disabled={changed.length > 0}>
              <ImageIcon className="mr-1 h-4 w-4" aria-hidden />
              Diary image
            </Button>
          )
        }
      />

      <Card>
        <CardContent className="grid gap-4 pt-6 sm:grid-cols-[minmax(0,1fr)_auto]">
          <div className="grid gap-1.5">
            <Label htmlFor="diary-section">Class</Label>
            <NativeSelect
              id="diary-section"
              value={sectionId ?? ""}
              onChange={(event) => go({ sectionId: event.target.value })}
              disabled={options.length === 0}
            >
              {mine.length > 0 && (
                <optgroup label="My classes">
                  {mine.map((o) => (
                    <option key={o.section_id} value={o.section_id}>
                      {sectionLabel(o)}
                    </option>
                  ))}
                </optgroup>
              )}
              {others.length > 0 && (
                <optgroup label={mine.length > 0 ? "Other classes" : "Classes"}>
                  {others.map((o) => (
                    <option key={o.section_id} value={o.section_id}>
                      {sectionLabel(o)}
                    </option>
                  ))}
                </optgroup>
              )}
            </NativeSelect>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="diary-date">
              Date <span className="text-muted-foreground">· {day}</span>
            </Label>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                className="h-9"
                onClick={() => go({ date: shiftDay(date, -1) })}
                aria-label="Previous day"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden />
              </Button>
              <Input
                id="diary-date"
                type="date"
                value={date}
                onChange={(event) => event.target.value && go({ date: event.target.value })}
                className="w-40"
              />
              <Button
                variant="outline"
                size="sm"
                className="h-9"
                onClick={() => go({ date: shiftDay(date, 1) })}
                aria-label="Next day"
              >
                <ChevronRight className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {sections.isError && (
        <ErrorState error={sections.error} onRetry={() => void sections.refetch()} />
      )}
      {sections.data && options.length === 0 && (
        <EmptyState
          icon={NotebookPen}
          title="No classes yet"
          description="Create classes and sections first; each section gets its own diary."
        />
      )}

      {sectionId && (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                {page.data ? `${page.data.class_name} – ${page.data.section_name}` : "Diary"}
                {selected && <Badge variant="neutral">{ACCESS_LABEL[selected.access]}</Badge>}
              </CardTitle>
              {page.data && (
                <p className="text-sm text-muted-foreground">
                  Class teacher: {page.data.class_teacher_name ?? "not assigned"}
                </p>
              )}
            </div>
            {canWrite && page.data?.can_edit && (
              <Button onClick={onSave} disabled={changed.length === 0 || save.isPending}>
                {save.isPending
                  ? "Saving…"
                  : changed.length > 0
                    ? `Save ${changed.length} change${changed.length === 1 ? "" : "s"}`
                    : "Saved"}
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {page.isPending && <Skeleton className="h-48" />}
            {page.isError && <ErrorState error={page.error} onRetry={() => void page.refetch()} />}
            {page.data && page.data.rows.length === 0 && (
              <EmptyState
                icon={NotebookPen}
                title="No subjects for this class"
                description={`Add subjects to ${page.data.class_name} on the Subjects page, and they appear here as diary rows.`}
              />
            )}
            {page.data && page.data.rows.length > 0 && (
              <DiaryRows
                page={page.data}
                drafts={drafts}
                onChange={(subjectId, value) =>
                  setDrafts((prev) => ({ ...prev, [subjectId]: value }))
                }
              />
            )}
            {page.data && canWrite && !page.data.can_edit && page.data.rows.length > 0 && (
              <p className="mt-4 text-sm text-muted-foreground">
                You can view this diary. Only its class teacher, the subject teachers, or a
                coordinator can write on it.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {page.data && (
        <DiaryImageDialog
          open={imageOpen}
          onOpenChange={setImageOpen}
          page={page.data}
          branding={branding}
        />
      )}
    </div>
  );
}

function DiaryRows({
  page,
  drafts,
  onChange,
}: {
  page: DiaryPage;
  drafts: Record<string, string>;
  onChange: (subjectId: string, value: string) => void;
}) {
  return (
    <div className="divide-y rounded-md border">
      {page.rows.map((row) => (
        <div
          key={row.subject_id}
          className="grid gap-2 p-3 sm:grid-cols-[14rem_minmax(0,1fr)] sm:gap-4"
        >
          <div>
            <p className="font-medium">{row.subject_name}</p>
            <p className="text-xs text-muted-foreground">
              {row.teacher_name ?? "No subject teacher"}
            </p>
            {!row.can_edit && (
              <Badge variant="outline" className="mt-1">
                View only
              </Badge>
            )}
          </div>
          <div className="space-y-1">
            {row.can_edit ? (
              <Textarea
                // `dir="auto"` so an Urdu line types right-to-left and an English
                // one left-to-right, without anyone choosing.
                dir="auto"
                rows={2}
                className="min-h-16 text-base"
                maxLength={1000}
                placeholder="e.g. Pg 85 full L+w"
                value={drafts[row.subject_id] ?? ""}
                onChange={(event) => onChange(row.subject_id, event.target.value)}
              />
            ) : (
              <p dir="auto" className="min-h-10 whitespace-pre-wrap py-2 text-base">
                {row.content || <span className="text-muted-foreground">—</span>}
              </p>
            )}
            {row.updated_at && (
              <p className="text-xs text-muted-foreground">
                {row.written_by_name ?? "Someone"} · {formatDateTime(row.updated_at)}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function DiaryImageDialog({
  open,
  onOpenChange,
  page,
  branding,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  page: DiaryPage;
  branding: DiaryBranding;
}) {
  const [blob, setBlob] = React.useState<Blob | null>(null);
  const [url, setUrl] = React.useState<string | null>(null);
  const [failed, setFailed] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setFailed(null);
    renderDiaryImage(page, branding)
      .then((result) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(result);
        setBlob(result);
        setUrl(objectUrl);
      })
      .catch((error: unknown) => {
        if (!cancelled) setFailed(error instanceof Error ? error.message : "Unknown error");
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setBlob(null);
      setUrl(null);
    };
  }, [open, page, branding]);

  const fileName = `diary-${page.class_name}-${page.section_name}-${page.entry_date}.png`
    .replace(/\s+/g, "-")
    .toLowerCase();
  const file = blob ? new File([blob], fileName, { type: "image/png" }) : null;
  const canShare =
    file !== null &&
    typeof navigator !== "undefined" &&
    typeof navigator.canShare === "function" &&
    navigator.canShare({ files: [file] });

  const download = () => {
    if (!url) return;
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    link.click();
  };

  const share = async () => {
    if (!file) return;
    try {
      await navigator.share({ files: [file], title: `${page.class_name} diary` });
    } catch (error) {
      // Closing the share sheet is a cancel, not a failure.
      if (error instanceof Error && error.name !== "AbortError") {
        toast.error("Couldn't share the image", error.message);
      }
    }
  };

  const print = () => {
    if (!url) return;
    const win = window.open("", "_blank");
    if (!win) return;
    win.document.write(
      `<title>${fileName}</title><style>@page{margin:8mm}body{margin:0}img{width:100%}</style>` +
        `<img src="${url}" onload="window.print()" />`,
    );
    win.document.close();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Diary image</DialogTitle>
          <DialogDescription>
            Ready to send to parents. Subjects with no homework are left off.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto rounded-md border bg-muted/30">
          {url ? (
            // eslint-disable-next-line @next/next/no-img-element -- a local blob URL
            <img src={url} alt={`Diary for ${page.class_name} ${page.section_name}`} className="w-full" />
          ) : failed ? (
            <p className="p-6 text-sm text-destructive">Couldn&apos;t draw the image: {failed}</p>
          ) : (
            <Skeleton className="h-96" />
          )}
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={print} disabled={!url}>
            <Printer className="mr-1 h-4 w-4" aria-hidden />
            Print
          </Button>
          {canShare && (
            <Button variant="outline" onClick={() => void share()}>
              <Share2 className="mr-1 h-4 w-4" aria-hidden />
              Share
            </Button>
          )}
          <Button onClick={download} disabled={!url}>
            <Download className="mr-1 h-4 w-4" aria-hidden />
            Download PNG
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
