"use client";

import * as React from "react";
import { MessageCircle, Pencil, RotateCw, Send, Trash2, X } from "lucide-react";

import { EmptyState, ErrorState, TableCardSkeleton } from "@/components/data-states";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/misc";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCancelWhatsAppMessage,
  useDeleteWhatsAppGroup,
  useFeeNoticePreview,
  useQueueFeeNotices,
  useRetryWhatsAppMessage,
  useSaveWhatsAppSettings,
  useSendCustomMessage,
  useWhatsAppConnection,
  useWhatsAppGroups,
  useWhatsAppMessages,
  useWhatsAppSettings,
} from "@/hooks/use-whatsapp";
import {
  label,
  type WhatsAppGroupRead,
  type WhatsAppMessageRead,
  type WhatsAppMessageStatus,
} from "@/lib/api/types";
import type { Translation } from "@/lib/i18n/catalog";
import { fill } from "@/lib/i18n/format";
import { sharedMessages } from "@/lib/i18n/modules/shared";
import { whatsappMessages } from "@/lib/i18n/modules/whatsapp";
import { useCatalog } from "@/lib/i18n/use-catalog";
import { formatDate, formatDateTime } from "@/lib/utils";
import { AbsenceAlertsPanel } from "./absence-alerts-panel";
import { ConnectionCard } from "./connection-card";
import { DiaryAgentPanel } from "./diary-agent-panel";
import { GroupFormDialog } from "./group-form-dialog";

function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function groupClassLabel(group: WhatsAppGroupRead): string {
  return group.section_name ? `${group.class_name} – ${group.section_name}` : group.class_name;
}

export function WhatsAppView({ canSend, canManage }: { canSend: boolean; canManage: boolean }) {
  const m = useCatalog(whatsappMessages).page;
  return (
    <div className="space-y-6">
      <PageHeader title={m.title} description={m.description} />
      <ConnectionCard canManage={canManage} />
      <Tabs defaultValue="groups">
        <TabsList>
          <TabsTrigger value="groups">{m.tabGroups}</TabsTrigger>
          <TabsTrigger value="fee-notice">{m.tabFeeNotice}</TabsTrigger>
          <TabsTrigger value="diary">{m.tabDiary}</TabsTrigger>
          <TabsTrigger value="absence">{m.tabAbsence}</TabsTrigger>
          {canSend && <TabsTrigger value="send">{m.tabSend}</TabsTrigger>}
          <TabsTrigger value="outbox">{m.tabOutbox}</TabsTrigger>
        </TabsList>
        <TabsContent value="groups">
          <GroupsPanel canManage={canManage} />
        </TabsContent>
        <TabsContent value="fee-notice">
          <FeeNoticePanel canManage={canManage} canSend={canSend} />
        </TabsContent>
        <TabsContent value="diary">
          <DiaryAgentPanel canManage={canManage} />
        </TabsContent>
        <TabsContent value="absence">
          <AbsenceAlertsPanel canManage={canManage} />
        </TabsContent>
        {canSend && (
          <TabsContent value="send">
            <SendPanel />
          </TabsContent>
        )}
        <TabsContent value="outbox">
          <OutboxPanel canSend={canSend} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Groups
// ---------------------------------------------------------------------------

function GroupsPanel({ canManage }: { canManage: boolean }) {
  const m = useCatalog(whatsappMessages).groups;
  const groups = useWhatsAppGroups();
  const remove = useDeleteWhatsAppGroup();
  // Reachability only means something when the school's own number is on the gateway.
  const gateway = useWhatsAppConnection().data?.configured ?? false;
  const [editing, setEditing] = React.useState<WhatsAppGroupRead | null>(null);
  const [open, setOpen] = React.useState(false);

  const openForm = (group: WhatsAppGroupRead | null) => {
    setEditing(group);
    setOpen(true);
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <CardTitle>{m.title}</CardTitle>
        {canManage && <Button onClick={() => openForm(null)}>{m.link}</Button>}
      </CardHeader>
      <CardContent>
        {groups.isLoading ? (
          <TableCardSkeleton columns={5} rows={3} />
        ) : groups.isError ? (
          <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
        ) : !groups.data?.length ? (
          <EmptyState icon={MessageCircle} title={m.emptyTitle} description={m.emptyHint} />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{m.colGroup}</TableHead>
                  <TableHead>{m.colClass}</TableHead>
                  <TableHead>{m.colFeeNotice}</TableHead>
                  <TableHead>{m.colLastSent}</TableHead>
                  {canManage && <TableHead className="text-end">{m.colActions}</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.data.map((group) => (
                  <TableRow key={group.id}>
                    <TableCell>
                      <div className="font-medium">{group.name}</div>
                      <div className="flex flex-wrap gap-1">
                        {!group.is_active && <Badge variant="neutral">{m.paused}</Badge>}
                        {gateway &&
                          (group.chat_id ? (
                            <Badge variant="success">{m.linked}</Badge>
                          ) : (
                            <Badge variant="warning" title={m.unreachableTitle}>
                              {m.unreachable}
                            </Badge>
                          ))}
                      </div>
                    </TableCell>
                    <TableCell>{groupClassLabel(group)}</TableCell>
                    <TableCell>
                      {group.send_fee_notice ? (
                        <Badge variant="success">{m.on}</Badge>
                      ) : (
                        <Badge variant="neutral">{m.off}</Badge>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {group.last_sent_at ? formatDateTime(group.last_sent_at) : m.never}
                    </TableCell>
                    {canManage && (
                      <TableCell className="text-end">
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={fill(m.editNamed, { name: group.name })}
                          onClick={() => openForm(group)}
                        >
                          <Pencil className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={fill(m.unlinkNamed, { name: group.name })}
                          disabled={remove.isPending}
                          onClick={() => {
                            if (window.confirm(fill(m.unlinkConfirm, { name: group.name })))
                              remove.mutate(group.id);
                          }}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden />
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
      {canManage && <GroupFormDialog open={open} onOpenChange={setOpen} group={editing} />}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Monthly fee notice
// ---------------------------------------------------------------------------

function FeeNoticePanel({ canManage, canSend }: { canManage: boolean; canSend: boolean }) {
  const m = useCatalog(whatsappMessages).fee;
  const settings = useWhatsAppSettings();
  const save = useSaveWhatsAppSettings();
  const [period, setPeriod] = React.useState(currentPeriod);
  const preview = useFeeNoticePreview(period);
  const queue = useQueueFeeNotices();

  const [enabled, setEnabled] = React.useState(false);
  const [sendDay, setSendDay] = React.useState(1);
  const [template, setTemplate] = React.useState("");
  const [note, setNote] = React.useState("");

  React.useEffect(() => {
    if (!settings.data) return;
    setEnabled(settings.data.fee_notice_enabled);
    setSendDay(settings.data.send_day);
    setTemplate(settings.data.fee_template);
    setNote(settings.data.monthly_note ?? "");
  }, [settings.data]);

  if (settings.isLoading) return <TableCardSkeleton columns={2} rows={4} />;
  if (settings.isError)
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;

  const ready = preview.data?.filter((p) => p.body) ?? [];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{m.settings}</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              save.mutate({
                fee_notice_enabled: enabled,
                send_day: sendDay,
                fee_template: template,
                monthly_note: note.trim() || null,
              });
            }}
          >
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enabled}
                disabled={!canManage}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              {m.autoSend}
            </label>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-send-day">{m.sendDay}</Label>
              <Input
                id="wa-send-day"
                type="number"
                min={1}
                max={28}
                value={sendDay}
                disabled={!canManage}
                onChange={(event) => setSendDay(Number(event.target.value))}
                className="w-24"
              />
              <p className="text-xs text-muted-foreground">
                {m.sendDayHint}
                {settings.data?.next_send_on
                  ? ` ${fill(m.nextSend, { date: formatDate(settings.data.next_send_on) })}`
                  : ""}
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-template">{m.message}</Label>
              <Textarea
                id="wa-template"
                rows={8}
                value={template}
                disabled={!canManage}
                onChange={(event) => setTemplate(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {m.placeholders}{" "}
                {settings.data?.placeholders.map((p) => (
                  <code key={p} className="me-1 rounded bg-muted px-1">
                    {`{${p}}`}
                  </code>
                ))}
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-note">{m.note}</Label>
              <Textarea
                id="wa-note"
                rows={3}
                value={note}
                disabled={!canManage}
                placeholder={m.notePlaceholder}
                onChange={(event) => setNote(event.target.value)}
              />
            </div>
            {canManage && (
              <Button type="submit" disabled={save.isPending}>
                {m.save}
              </Button>
            )}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <CardTitle>{m.preview}</CardTitle>
          <Input
            type="month"
            aria-label={m.month}
            value={period}
            onChange={(event) => event.target.value && setPeriod(event.target.value)}
            className="w-44"
          />
        </CardHeader>
        <CardContent className="space-y-4">
          {preview.isLoading ? (
            <TableCardSkeleton columns={1} rows={3} />
          ) : preview.isError ? (
            <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
          ) : !preview.data?.length ? (
            <EmptyState title={m.emptyTitle} description={m.emptyHint} />
          ) : (
            preview.data.map((item) => (
              <div key={item.group_id} className="rounded-md border p-3">
                <div className="mb-1 text-sm font-medium">{item.group_name}</div>
                {item.body ? (
                  <pre className="whitespace-pre-wrap font-sans text-sm">{item.body}</pre>
                ) : (
                  <p className="text-sm text-muted-foreground">{item.reason}</p>
                )}
              </div>
            ))
          )}
          {canSend && (
            <Button
              disabled={queue.isPending || ready.length === 0}
              onClick={() => {
                if (
                  window.confirm(
                    fill(ready.length === 1 ? m.confirmOne : m.confirmOther, {
                      period,
                      count: ready.length,
                    }),
                  )
                )
                  queue.mutate({ period_label: period });
              }}
            >
              <Send className="me-1 h-4 w-4" aria-hidden />
              {m.sendNow}
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom message
// ---------------------------------------------------------------------------

function SendPanel() {
  const m = useCatalog(whatsappMessages).send;
  const groups = useWhatsAppGroups();
  const send = useSendCustomMessage();
  const [body, setBody] = React.useState("");
  const [selected, setSelected] = React.useState<Set<string>>(new Set());

  const active = (groups.data ?? []).filter((g) => g.is_active);
  const allSelected = active.length > 0 && active.every((g) => selected.has(g.id));

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{m.title}</CardTitle>
      </CardHeader>
      <CardContent>
        {groups.isLoading ? (
          <TableCardSkeleton columns={1} rows={3} />
        ) : active.length === 0 ? (
          <EmptyState title={m.emptyTitle} description={m.emptyHint} />
        ) : (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              send.mutate(
                { body, group_ids: [...selected] },
                {
                  onSuccess: () => {
                    setBody("");
                    setSelected(new Set());
                  },
                },
              );
            }}
          >
            <fieldset className="space-y-2">
              <legend className="mb-1 text-sm font-medium">{m.groups}</legend>
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(event) =>
                    setSelected(event.target.checked ? new Set(active.map((g) => g.id)) : new Set())
                  }
                />
                {m.allGroups}
              </label>
              <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                {active.map((group) => (
                  <label key={group.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selected.has(group.id)}
                      onChange={() => toggle(group.id)}
                    />
                    {group.name}
                    <span className="text-muted-foreground">({groupClassLabel(group)})</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-body">{m.message}</Label>
              <Textarea
                id="wa-body"
                rows={6}
                maxLength={4000}
                value={body}
                onChange={(event) => setBody(event.target.value)}
                placeholder={m.placeholder}
              />
            </div>
            <Button type="submit" disabled={send.isPending || !body.trim() || selected.size === 0}>
              <Send className="me-1 h-4 w-4" aria-hidden />
              {fill(selected.size === 1 ? m.sendToOne : m.sendToOther, { count: selected.size })}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Outbox
// ---------------------------------------------------------------------------

type OutboxMessages = Translation<(typeof whatsappMessages)["en"]>["outbox"];

function messageKindLabel(message: WhatsAppMessageRead, m: OutboxMessages): string {
  const name = message.created_by_name;
  const period = message.period_label ?? "";
  switch (message.kind) {
    case "fee_notice":
      return fill(m.kindFeeNotice, { period });
    case "diary":
      return name ? fill(m.kindDiaryBy, { name }) : m.kindDiary;
    case "absence_alert":
      return fill(m.kindAbsence, { period });
    default:
      return name ? fill(m.kindCustomBy, { name }) : m.kindCustom;
  }
}

const STATUS_BADGE: Record<WhatsAppMessageStatus, "warning" | "success" | "destructive"> = {
  queued: "warning",
  sent: "success",
  failed: "destructive",
};

function OutboxPanel({ canSend }: { canSend: boolean }) {
  const m = useCatalog(whatsappMessages).outbox;
  const shared = useCatalog(sharedMessages);
  const [status, setStatus] = React.useState<WhatsAppMessageStatus | "">("");
  const [page, setPage] = React.useState(1);
  const messages = useWhatsAppMessages({ page, size: 20, ...(status ? { status } : {}) });
  const retry = useRetryWhatsAppMessage();
  const cancel = useCancelWhatsAppMessage();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <CardTitle>{m.title}</CardTitle>
        <NativeSelect
          aria-label={m.status}
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as WhatsAppMessageStatus | "");
            setPage(1);
          }}
          className="w-40"
        >
          <option value="">{m.all}</option>
          <option value="queued">{m.statusLabel.queued}</option>
          <option value="sent">{m.statusLabel.sent}</option>
          <option value="failed">{m.statusLabel.failed}</option>
        </NativeSelect>
      </CardHeader>
      <CardContent>
        {messages.isLoading ? (
          <TableCardSkeleton columns={4} />
        ) : messages.isError ? (
          <ErrorState error={messages.error} onRetry={() => void messages.refetch()} />
        ) : !messages.data?.items.length ? (
          <EmptyState title={m.emptyTitle} description={m.emptyHint} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{m.colGroup}</TableHead>
                    <TableHead>{m.colMessage}</TableHead>
                    <TableHead>{m.colStatus}</TableHead>
                    <TableHead>{m.colWhen}</TableHead>
                    {canSend && <TableHead className="text-end">{m.colActions}</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {messages.data.items.map((message) => (
                    <TableRow key={message.id}>
                      <TableCell className="align-top">
                        <div className="font-medium">{message.group_name}</div>
                        <div className="text-xs text-muted-foreground">
                          {messageKindLabel(message, m)}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-md align-top">
                        <p className="line-clamp-3 whitespace-pre-wrap text-sm">{message.body}</p>
                        {message.last_error && (
                          <p className="mt-1 text-xs text-destructive">{message.last_error}</p>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge variant={STATUS_BADGE[message.status]}>
                          {label(m.statusLabel, message.status)}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap align-top text-sm text-muted-foreground">
                        {formatDateTime(message.sent_at ?? message.created_at)}
                      </TableCell>
                      {canSend && (
                        <TableCell className="text-end align-top">
                          {message.status === "failed" && (
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={m.retry}
                              disabled={retry.isPending}
                              onClick={() => retry.mutate(message.id)}
                            >
                              <RotateCw className="h-4 w-4" aria-hidden />
                            </Button>
                          )}
                          {message.status !== "sent" && (
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={m.cancel}
                              disabled={cancel.isPending}
                              onClick={() => cancel.mutate(message.id)}
                            >
                              <X className="h-4 w-4" aria-hidden />
                            </Button>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2 text-sm">
              <Button
                variant="outline"
                size="sm"
                disabled={!messages.data.meta.has_prev}
                onClick={() => setPage((p) => p - 1)}
              >
                {shared.previous}
              </Button>
              <span className="text-muted-foreground">
                {fill(shared.pageOf, {
                  page: messages.data.meta.page,
                  pages: Math.max(messages.data.meta.pages, 1),
                })}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!messages.data.meta.has_next}
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
