"use client";

import * as React from "react";
import { MessageCircle, Pencil, RotateCw, Send, Trash2, X } from "lucide-react";

import { EmptyState, ErrorState, TableSkeleton } from "@/components/data-states";
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
  useWhatsAppGroups,
  useWhatsAppMessages,
  useWhatsAppSettings,
} from "@/hooks/use-whatsapp";
import type { WhatsAppGroupRead, WhatsAppMessageStatus } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/utils";
import { GroupFormDialog } from "./group-form-dialog";

function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function groupClassLabel(group: WhatsAppGroupRead): string {
  return group.section_name ? `${group.class_name} – ${group.section_name}` : group.class_name;
}

export function WhatsAppView({ canSend, canManage }: { canSend: boolean; canManage: boolean }) {
  return (
    <div className="space-y-6">
      <PageHeader
        title="WhatsApp groups"
        description="Post the monthly fee notice and your own messages to each class's parents' group."
      />
      <Tabs defaultValue="groups">
        <TabsList>
          <TabsTrigger value="groups">Groups</TabsTrigger>
          <TabsTrigger value="fee-notice">Monthly fee notice</TabsTrigger>
          {canSend && <TabsTrigger value="send">Send message</TabsTrigger>}
          <TabsTrigger value="outbox">Outbox</TabsTrigger>
        </TabsList>
        <TabsContent value="groups">
          <GroupsPanel canManage={canManage} />
        </TabsContent>
        <TabsContent value="fee-notice">
          <FeeNoticePanel canManage={canManage} canSend={canSend} />
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
  const groups = useWhatsAppGroups();
  const remove = useDeleteWhatsAppGroup();
  const [editing, setEditing] = React.useState<WhatsAppGroupRead | null>(null);
  const [open, setOpen] = React.useState(false);

  const openForm = (group: WhatsAppGroupRead | null) => {
    setEditing(group);
    setOpen(true);
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <CardTitle>Class groups</CardTitle>
        {canManage && <Button onClick={() => openForm(null)}>Link a group</Button>}
      </CardHeader>
      <CardContent>
        {groups.isLoading ? (
          <TableSkeleton columns={5} rows={3} />
        ) : groups.isError ? (
          <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
        ) : !groups.data?.length ? (
          <EmptyState
            icon={MessageCircle}
            title="No groups linked yet"
            description="Link each class's parents' group with its invite link (Group info → Invite via link)."
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Group</TableHead>
                  <TableHead>Class</TableHead>
                  <TableHead>Fee notice</TableHead>
                  <TableHead>Last sent</TableHead>
                  {canManage && <TableHead className="text-end">Actions</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.data.map((group) => (
                  <TableRow key={group.id}>
                    <TableCell>
                      <div className="font-medium">{group.name}</div>
                      {!group.is_active && <Badge variant="neutral">Paused</Badge>}
                    </TableCell>
                    <TableCell>{groupClassLabel(group)}</TableCell>
                    <TableCell>
                      {group.send_fee_notice ? (
                        <Badge variant="success">On</Badge>
                      ) : (
                        <Badge variant="neutral">Off</Badge>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {group.last_sent_at ? formatDateTime(group.last_sent_at) : "Never"}
                    </TableCell>
                    {canManage && (
                      <TableCell className="text-end">
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Edit ${group.name}`}
                          onClick={() => openForm(group)}
                        >
                          <Pencil className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Unlink ${group.name}`}
                          disabled={remove.isPending}
                          onClick={() => {
                            if (
                              window.confirm(
                                `Unlink "${group.name}"? Messages still waiting to be sent to it are dropped.`,
                              )
                            )
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

  if (settings.isLoading) return <TableSkeleton columns={2} rows={4} />;
  if (settings.isError)
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;

  const ready = preview.data?.filter((p) => p.body) ?? [];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Settings</CardTitle>
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
              Send the fee notice automatically every month
            </label>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-send-day">Day of the month</Label>
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
                Only issued challans are announced. If they are still drafts on this day, the
                notice goes out the night after they are issued.
                {settings.data?.next_send_on
                  ? ` Next: ${formatDate(settings.data.next_send_on)}.`
                  : ""}
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-template">Message</Label>
              <Textarea
                id="wa-template"
                rows={8}
                value={template}
                disabled={!canManage}
                onChange={(event) => setTemplate(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Placeholders:{" "}
                {settings.data?.placeholders.map((p) => (
                  <code key={p} className="me-1 rounded bg-muted px-1">
                    {`{${p}}`}
                  </code>
                ))}
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="wa-note">Custom message added every month (optional)</Label>
              <Textarea
                id="wa-note"
                rows={3}
                value={note}
                disabled={!canManage}
                placeholder="e.g. Summer uniform starts from next week."
                onChange={(event) => setNote(event.target.value)}
              />
            </div>
            {canManage && (
              <Button type="submit" disabled={save.isPending}>
                Save settings
              </Button>
            )}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <CardTitle>Preview</CardTitle>
          <Input
            type="month"
            aria-label="Month"
            value={period}
            onChange={(event) => event.target.value && setPeriod(event.target.value)}
            className="w-44"
          />
        </CardHeader>
        <CardContent className="space-y-4">
          {preview.isLoading ? (
            <TableSkeleton columns={1} rows={3} />
          ) : preview.isError ? (
            <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
          ) : !preview.data?.length ? (
            <EmptyState
              title="No groups take the fee notice"
              description="Link a group and leave its fee notice on."
            />
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
                    `Queue the ${period} fee notice for ${ready.length} group(s) now? Each group gets it once per month.`,
                  )
                )
                  queue.mutate({ period_label: period });
              }}
            >
              <Send className="mr-1 h-4 w-4" aria-hidden />
              Send now
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
        <CardTitle>Send a message</CardTitle>
      </CardHeader>
      <CardContent>
        {groups.isLoading ? (
          <TableSkeleton columns={1} rows={3} />
        ) : active.length === 0 ? (
          <EmptyState title="No active groups" description="Link a class group first." />
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
              <legend className="mb-1 text-sm font-medium">Groups</legend>
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(event) =>
                    setSelected(event.target.checked ? new Set(active.map((g) => g.id)) : new Set())
                  }
                />
                All groups
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
              <Label htmlFor="wa-body">Message</Label>
              <Textarea
                id="wa-body"
                rows={6}
                maxLength={4000}
                value={body}
                onChange={(event) => setBody(event.target.value)}
                placeholder="Dear Parents, the school will remain closed on…"
              />
            </div>
            <Button type="submit" disabled={send.isPending || !body.trim() || selected.size === 0}>
              <Send className="mr-1 h-4 w-4" aria-hidden />
              Send to {selected.size} group{selected.size === 1 ? "" : "s"}
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

const STATUS_BADGE: Record<WhatsAppMessageStatus, "warning" | "success" | "destructive"> = {
  queued: "warning",
  sent: "success",
  failed: "destructive",
};

function OutboxPanel({ canSend }: { canSend: boolean }) {
  const [status, setStatus] = React.useState<WhatsAppMessageStatus | "">("");
  const [page, setPage] = React.useState(1);
  const messages = useWhatsAppMessages({ page, size: 20, ...(status ? { status } : {}) });
  const retry = useRetryWhatsAppMessage();
  const cancel = useCancelWhatsAppMessage();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <CardTitle>Outbox</CardTitle>
        <NativeSelect
          aria-label="Status"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as WhatsAppMessageStatus | "");
            setPage(1);
          }}
          className="w-40"
        >
          <option value="">All</option>
          <option value="queued">Queued</option>
          <option value="sent">Sent</option>
          <option value="failed">Failed</option>
        </NativeSelect>
      </CardHeader>
      <CardContent>
        {messages.isLoading ? (
          <TableSkeleton columns={4} />
        ) : messages.isError ? (
          <ErrorState error={messages.error} onRetry={() => void messages.refetch()} />
        ) : !messages.data?.items.length ? (
          <EmptyState title="Nothing here yet" description="Queued and sent messages appear here." />
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Group</TableHead>
                    <TableHead>Message</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>When</TableHead>
                    {canSend && <TableHead className="text-end">Actions</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {messages.data.items.map((message) => (
                    <TableRow key={message.id}>
                      <TableCell className="align-top">
                        <div className="font-medium">{message.group_name}</div>
                        <div className="text-xs text-muted-foreground">
                          {message.kind === "fee_notice"
                            ? `Fee notice ${message.period_label ?? ""}`
                            : `Custom${message.created_by_name ? ` · ${message.created_by_name}` : ""}`}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-md align-top">
                        <p className="line-clamp-3 whitespace-pre-wrap text-sm">{message.body}</p>
                        {message.last_error && (
                          <p className="mt-1 text-xs text-destructive">{message.last_error}</p>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        <Badge variant={STATUS_BADGE[message.status]}>{message.status}</Badge>
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
                              aria-label="Retry"
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
                              aria-label="Cancel"
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
                Previous
              </Button>
              <span className="text-muted-foreground">
                Page {messages.data.meta.page} of {Math.max(messages.data.meta.pages, 1)}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!messages.data.meta.has_next}
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
