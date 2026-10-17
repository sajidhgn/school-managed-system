"use client";

import * as React from "react";
import { LoaderCircle, PlugZap, Power, RotateCw, Smartphone, TriangleAlert } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/data-states";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import {
  useConnectWhatsApp,
  useDisconnectWhatsApp,
  useWhatsAppConnection,
  useWhatsAppQr,
} from "@/hooks/use-whatsapp";
import type { WhatsAppConnectionRead } from "@/lib/api/types";

const STATUS_LABEL: Record<string, { label: string; variant: BadgeProps["variant"] }> = {
  STOPPED: { label: "Not connected", variant: "neutral" },
  STARTING: { label: "Starting…", variant: "warning" },
  SCAN_QR_CODE: { label: "Waiting for scan", variant: "warning" },
  WORKING: { label: "Connected", variant: "success" },
  FAILED: { label: "Failed", variant: "destructive" },
};

function statusBadge(connection: WhatsAppConnectionRead) {
  if (!connection.configured) return { label: "Not set up", variant: "neutral" as const };
  if (!connection.status) return STATUS_LABEL.STOPPED;
  return STATUS_LABEL[connection.status] ?? { label: connection.status, variant: "outline" as const };
}

/** "923001234567@c.us" → "+923001234567". */
export function formatWhatsAppNumber(phone: string): string {
  const digits = phone.split("@")[0] ?? phone;
  return digits.startsWith("+") ? digits : `+${digits}`;
}

/**
 * The school's own WhatsApp number, linked to the self-hosted gateway by scanning a
 * QR code — the same "Linked devices" flow as WhatsApp Web. Everything the page
 * queues (fee notices, messages, diaries) goes out from this number.
 */
export function ConnectionCard({ canManage }: { canManage: boolean }) {
  const connection = useWhatsAppConnection();
  const connect = useConnectWhatsApp();
  const disconnect = useDisconnectWhatsApp();
  const [confirmOpen, setConfirmOpen] = React.useState(false);

  const data = connection.data;
  const status = data?.status ?? null;
  const qr = useWhatsAppQr(canManage && !!data?.configured && status === "SCAN_QR_CODE");

  const badge = data ? statusBadge(data) : null;
  const pending = status === "STARTING" || status === "SCAN_QR_CODE";
  const working = status === "WORKING";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <CardTitle className="flex items-center gap-2">
          <Smartphone className="h-4 w-4" aria-hidden />
          School WhatsApp number
        </CardTitle>
        {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
      </CardHeader>
      <CardContent className="space-y-4">
        {connection.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : connection.isError ? (
          <ErrorState error={connection.error} onRetry={() => void connection.refetch()} />
        ) : !data ? null : !data.configured ? (
          <p className="text-sm text-muted-foreground">
            Messages are sent through the server&apos;s configured WhatsApp provider (
            <code className="rounded bg-muted px-1">{data.backend}</code>). To link the
            school&apos;s own number here by scanning a QR code, the server administrator sets{" "}
            <code className="rounded bg-muted px-1">WHATSAPP_BACKEND=waha</code>.
          </p>
        ) : working ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-lg font-medium" dir="ltr">
                  {data.phone ? formatWhatsAppNumber(data.phone) : "Linked"}
                </div>
                {data.push_name && (
                  <div className="text-sm text-muted-foreground">{data.push_name}</div>
                )}
              </div>
              {canManage && (
                <Button variant="outline" onClick={() => setConfirmOpen(true)}>
                  <Power className="h-4 w-4" aria-hidden />
                  Disconnect
                </Button>
              )}
            </div>
            {data.unresolved_groups > 0 && (
              <div className="flex gap-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                <p>
                  {data.unresolved_groups} group{data.unresolved_groups === 1 ? " isn't" : "s aren't"}{" "}
                  reachable yet. The school&apos;s number must be a member of{" "}
                  {data.unresolved_groups === 1 ? "that group" : "those groups"} — the gateway
                  tries to join through the invite link; if that keeps failing, ask a group admin to
                  add the school&apos;s number.
                </p>
              </div>
            )}
          </>
        ) : status === "SCAN_QR_CODE" ? (
          canManage ? (
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <div className="flex size-56 shrink-0 items-center justify-center rounded-md border bg-white p-2">
                {qr.data ? (
                  // eslint-disable-next-line @next/next/no-img-element -- a data: URI, nothing to optimise
                  <img
                    src={`data:${qr.data.mimetype};base64,${qr.data.data}`}
                    alt="WhatsApp pairing QR code"
                    className="size-full"
                  />
                ) : (
                  <LoaderCircle className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
                )}
              </div>
              <div className="space-y-3 text-sm">
                <p>
                  On the school&apos;s phone: <strong>WhatsApp → Linked devices → Link a device</strong>,
                  then scan this code.
                </p>
                <p className="text-muted-foreground">
                  The code refreshes by itself every few seconds. This page updates once the phone
                  is linked.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  loading={connect.isPending}
                  onClick={() => connect.mutate()}
                >
                  <RotateCw className="h-4 w-4" aria-hidden />
                  Restart
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Waiting for an administrator to scan the QR code on the school&apos;s phone.
            </p>
          )
        ) : pending ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
            Starting the WhatsApp session…
          </p>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-prose text-sm text-muted-foreground">
              {status === "FAILED"
                ? "The WhatsApp session stopped working. Connect again to get a new QR code."
                : "Link the school's WhatsApp number so fee notices, messages and diaries go out from it."}
              {!canManage && " Ask an administrator to connect it."}
            </p>
            {canManage && (
              <Button loading={connect.isPending} onClick={() => connect.mutate()}>
                <PlugZap className="h-4 w-4" aria-hidden />
                Connect WhatsApp
              </Button>
            )}
          </div>
        )}
      </CardContent>
      {canManage && (
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title="Disconnect WhatsApp?"
          description="The school's number is logged out of the gateway. Fee notices, messages and diaries can't be sent until it is connected again."
          confirmLabel="Disconnect"
          loading={disconnect.isPending}
          onConfirm={() => disconnect.mutate(undefined, { onSuccess: () => setConfirmOpen(false) })}
        />
      )}
    </Card>
  );
}
