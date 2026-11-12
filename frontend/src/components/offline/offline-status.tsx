"use client";

import * as React from "react";
import { CloudOff, Loader2, RefreshCw, RotateCcw, Trash2, TriangleAlert } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { useOffline } from "@/components/offline/offline-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { fill } from "@/lib/i18n/format";
import { offlineMessages } from "@/lib/i18n/modules/offline";
import { useCatalog } from "@/lib/i18n/use-catalog";
import {
  removeOfflineRegister,
  updateOfflineRegister,
  useOutbox,
  type OfflineRegister,
} from "@/lib/offline/attendance-outbox";
import { checkConnectivity } from "@/lib/offline/connectivity";
import { cn, formatDate } from "@/lib/utils";

/**
 * The header pill: offline, waiting to sync, or failed — and nothing at all when
 * everything is online and sent, so it never competes for attention it has not earned.
 * Opens the panel listing what is queued.
 */
export function OfflineStatus() {
  const m = useCatalog(offlineMessages);
  const { online, syncing } = useOffline();
  const items = useOutbox();
  const [open, setOpen] = React.useState(false);

  const pending = items.filter((item) => item.state === "pending").length;
  const failed = items.filter((item) => item.state === "failed").length;
  if (online && !syncing && pending === 0 && failed === 0) return null;

  let label: string;
  let tone: string;
  let Icon: typeof CloudOff = CloudOff;
  if (failed > 0) {
    label = fill(failed === 1 ? m.status.failedOne : m.status.failedMany, { count: failed });
    tone = "border-destructive/40 bg-destructive/10 text-destructive";
    Icon = TriangleAlert;
  } else if (!online) {
    label = pending
      ? `${m.status.offline} · ${fill(pending === 1 ? m.status.pendingOne : m.status.pendingMany, { count: pending })}`
      : m.status.offline;
    tone = "border-warning/50 bg-warning/15 text-foreground";
  } else if (syncing) {
    label = m.status.syncing;
    tone = "border-border bg-muted text-foreground";
    Icon = Loader2;
  } else {
    label = fill(pending === 1 ? m.status.pendingOne : m.status.pendingMany, { count: pending });
    tone = "border-border bg-muted text-foreground";
    Icon = RefreshCw;
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`${m.status.openPanel}: ${label}`}
        className={cn(
          "inline-flex h-8 max-w-[14rem] shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium sm:px-3",
          tone,
        )}
      >
        <Icon className={cn("size-3.5 shrink-0", syncing && "animate-spin")} aria-hidden />
        {/* On a phone the header is tight: the icon, plus the count when something
            is queued, leaves room for the campus name. The full label (and the
            aria-label) carry the words. */}
        <span className="hidden truncate sm:inline">{label}</span>
        {pending + failed > 0 ? (
          <span className="tabular-nums sm:hidden">{pending + failed}</span>
        ) : null}
      </button>
      <SyncPanel open={open} onOpenChange={setOpen} items={items} />
    </>
  );
}

/** Shown under the header while offline: what still works, and a manual re-check. */
export function OfflineBanner() {
  const m = useCatalog(offlineMessages).banner;
  const { online } = useOffline();
  const [checking, setChecking] = React.useState(false);
  if (online) return null;

  return (
    <div
      role="status"
      className="flex flex-col gap-3 border-b border-border bg-warning/15 px-4 py-3 sm:flex-row sm:items-center sm:px-6"
    >
      <div className="flex min-w-0 flex-1 items-start gap-3 text-sm">
        <CloudOff className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="min-w-0">
          <p className="font-medium">{m.title}</p>
          <p className="text-pretty text-muted-foreground">{m.body}</p>
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        loading={checking}
        onClick={async () => {
          setChecking(true);
          try {
            await checkConnectivity();
          } finally {
            setChecking(false);
          }
        }}
      >
        {checking ? m.checking : m.retry}
      </Button>
    </div>
  );
}

function SyncPanel({
  open,
  onOpenChange,
  items,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: OfflineRegister[];
}) {
  const m = useCatalog(offlineMessages).panel;
  const { online, syncing, syncNow } = useOffline();
  const [discarding, setDiscarding] = React.useState<OfflineRegister | null>(null);
  const sorted = [...items].sort((a, b) => a.date.localeCompare(b.date) || a.updatedAt - b.updatedAt);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{m.title}</DialogTitle>
          <DialogDescription>{m.description}</DialogDescription>
        </DialogHeader>

        {sorted.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">{m.empty}</p>
        ) : (
          <ul className="max-h-[50vh] space-y-2 overflow-y-auto">
            {sorted.map((item) => {
              const count = Object.keys(item.changes).length;
              return (
                <li key={item.id} className="rounded-lg border border-border p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium">
                        {fill(m.sectionDate, { section: item.sectionLabel, date: formatDate(item.date) })}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {fill(count === 1 ? m.changesOne : m.changesMany, { count })} ·{" "}
                        {item.submit ? m.willSubmit : m.draftOnly}
                      </p>
                    </div>
                    <Badge variant={item.state === "failed" ? "destructive" : "neutral"}>
                      {item.state === "failed" ? m.failed : m.pending}
                    </Badge>
                  </div>
                  {item.error ? (
                    <p className="mt-2 text-xs text-destructive text-pretty">{item.error}</p>
                  ) : null}
                  <div className="mt-2 flex flex-wrap gap-2">
                    {item.state === "failed" ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          await updateOfflineRegister(item.id, { state: "pending", error: null });
                          void syncNow();
                        }}
                      >
                        <RotateCcw className="size-3.5" aria-hidden />
                        {m.retry}
                      </Button>
                    ) : null}
                    <Button size="sm" variant="ghost" onClick={() => setDiscarding(item)}>
                      <Trash2 className="size-3.5" aria-hidden />
                      {m.discard}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {!online && sorted.length > 0 ? (
          <p className="text-xs text-muted-foreground">{m.offlineHint}</p>
        ) : null}

        <DialogFooter>
          <Button
            loading={syncing}
            disabled={!sorted.some((item) => item.state === "pending")}
            onClick={() => void syncNow()}
          >
            <RefreshCw className="size-4" aria-hidden />
            {syncing ? m.syncing : m.syncNow}
          </Button>
        </DialogFooter>

        <ConfirmDialog
          open={discarding !== null}
          onOpenChange={(next) => !next && setDiscarding(null)}
          title={fill(m.discardTitle, { section: discarding?.sectionLabel ?? "" })}
          description={m.discardBody}
          confirmLabel={m.discard}
          variant="destructive"
          onConfirm={async () => {
            if (discarding) await removeOfflineRegister(discarding.id);
            setDiscarding(null);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
