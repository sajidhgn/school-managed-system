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
import type { Translation } from "@/lib/i18n/catalog";
import { fill } from "@/lib/i18n/format";
import { whatsappMessages } from "@/lib/i18n/modules/whatsapp";
import { useCatalog } from "@/lib/i18n/use-catalog";

import { fillNodes } from "@/lib/i18n/format";

type ConnectionMessages = Translation<(typeof whatsappMessages)["en"]>["connection"];
type GatewayStatus = keyof ConnectionMessages["status"];

/** Gateway session states; the words are `connection.status` in the catalog. */
const STATUS_VARIANT: Record<GatewayStatus, BadgeProps["variant"]> = {
  STOPPED: "neutral",
  STARTING: "warning",
  SCAN_QR_CODE: "warning",
  WORKING: "success",
  FAILED: "destructive",
};

function isGatewayStatus(value: string): value is GatewayStatus {
  return value in STATUS_VARIANT;
}

function statusBadge(
  connection: WhatsAppConnectionRead,
  m: ConnectionMessages,
): { label: string; variant: BadgeProps["variant"] } {
  if (!connection.configured) return { label: m.notSetUp, variant: "neutral" };
  const status = connection.status || "STOPPED";
  // An unknown state is shown as the gateway names it.
  if (!isGatewayStatus(status)) return { label: status, variant: "outline" };
  return { label: m.status[status], variant: STATUS_VARIANT[status] };
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
  const m = useCatalog(whatsappMessages).connection;
  const connection = useWhatsAppConnection();
  const connect = useConnectWhatsApp();
  const disconnect = useDisconnectWhatsApp();
  const [confirmOpen, setConfirmOpen] = React.useState(false);

  const data = connection.data;
  const status = data?.status ?? null;
  const qr = useWhatsAppQr(canManage && !!data?.configured && status === "SCAN_QR_CODE");

  const badge = data ? statusBadge(data, m) : null;
  const pending = status === "STARTING" || status === "SCAN_QR_CODE";
  const working = status === "WORKING";

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-4">
        <CardTitle className="flex items-center gap-2">
          <Smartphone className="h-4 w-4" aria-hidden />
          {m.title}
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
            {fillNodes(m.notConfigured, {
              backend: <code className="rounded bg-muted px-1">{data.backend}</code>,
              env: <code className="rounded bg-muted px-1">WHATSAPP_BACKEND=waha</code>,
            })}
          </p>
        ) : working ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-lg font-medium" dir="ltr">
                  {data.phone ? formatWhatsAppNumber(data.phone) : m.linkedFallback}
                </div>
                {data.push_name && (
                  <div className="text-sm text-muted-foreground">{data.push_name}</div>
                )}
              </div>
              {canManage && (
                <Button variant="outline" onClick={() => setConfirmOpen(true)}>
                  <Power className="h-4 w-4" aria-hidden />
                  {m.disconnect}
                </Button>
              )}
            </div>
            {data.unresolved_groups > 0 && (
              <div className="flex gap-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                <p>
                  {fill(data.unresolved_groups === 1 ? m.unresolvedOne : m.unresolvedOther, {
                    count: data.unresolved_groups,
                  })}
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
                    alt={m.qrAlt}
                    className="size-full"
                  />
                ) : (
                  <LoaderCircle className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden />
                )}
              </div>
              <div className="space-y-3 text-sm">
                <p>{fillNodes(m.pairSteps, { path: <strong>{m.pairPath}</strong> })}</p>
                <p className="text-muted-foreground">{m.qrRefresh}</p>
                <Button
                  variant="outline"
                  size="sm"
                  loading={connect.isPending}
                  onClick={() => connect.mutate()}
                >
                  <RotateCw className="h-4 w-4" aria-hidden />
                  {m.restart}
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{m.waitingAdmin}</p>
          )
        ) : pending ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
            {m.starting}
          </p>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-prose text-sm text-muted-foreground">
              {status === "FAILED" ? m.failed : m.intro}
              {!canManage && ` ${m.askAdmin}`}
            </p>
            {canManage && (
              <Button loading={connect.isPending} onClick={() => connect.mutate()}>
                <PlugZap className="h-4 w-4" aria-hidden />
                {m.connect}
              </Button>
            )}
          </div>
        )}
      </CardContent>
      {canManage && (
        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title={m.confirmTitle}
          description={m.confirmDescription}
          confirmLabel={m.disconnect}
          loading={disconnect.isPending}
          onConfirm={() => disconnect.mutate(undefined, { onSuccess: () => setConfirmOpen(false) })}
        />
      )}
    </Card>
  );
}
