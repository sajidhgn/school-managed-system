"use client";

import * as React from "react";

import { ErrorState, TableCardSkeleton } from "@/components/data-states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSaveWhatsAppSettings, useWhatsAppSettings } from "@/hooks/use-whatsapp";

import { WhatsAppText } from "./whatsapp-text";

/**
 * The campus switch for absence alerts.
 *
 * When a teacher submits TODAY'S whole-day register, each absent child's guardians
 * get a message from this campus's WhatsApp, one to one -- never in the class group.
 * Only guardians who may see the child's records and have not opted out for that
 * child are messaged, and nobody is messaged twice for the same day.
 *
 * Off by default: a school turns this on knowingly, because a burst of automated
 * messages from its number is what WhatsApp flags.
 */
export function AbsenceAlertsPanel({ canManage }: { canManage: boolean }) {
  const settings = useWhatsAppSettings();
  const save = useSaveWhatsAppSettings();

  if (settings.isLoading) return <TableCardSkeleton columns={1} rows={3} />;
  if (settings.isError || !settings.data) {
    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  }
  const current = settings.data;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Absence alerts</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={current.absence_alerts_enabled}
              disabled={!canManage || save.isPending}
              onChange={(event) =>
                save.mutate({
                  fee_notice_enabled: current.fee_notice_enabled,
                  send_day: current.send_day,
                  fee_template: current.fee_template,
                  monthly_note: current.monthly_note,
                  absence_alerts_enabled: event.target.checked,
                })
              }
            />
            <span>
              <span className="font-medium">Message parents when their child is absent</span>
              <span className="mt-1 block text-muted-foreground">
                Sent from this campus&apos;s WhatsApp when today&apos;s whole-day register is
                submitted, to each parent on their own, never in the class group.
              </span>
            </span>
          </label>
          <ul className="list-disc space-y-1 ps-5 text-muted-foreground">
            <li>Only parents allowed to see that child&apos;s records are messaged, not pickup-only contacts.</li>
            <li>A parent turned off for a child on the student&apos;s page is not messaged.</li>
            <li>Late, half day and leave send nothing. So do lesson registers and past days.</li>
            <li>Reopening and resubmitting a register never sends a second message.</li>
            <li>A number without WhatsApp shows as failed in the Outbox.</li>
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>What a parent receives</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <WhatsAppText
            text={
              "Assalam-o-Alaikum Ayesha.\nAli Khan was marked absent at Main Campus today " +
              "(Tue 28 Oct 2026).\nIf you were not expecting this, please contact the school office."
            }
          />
          <p className="text-xs text-muted-foreground">
            Parents who use the portal in Urdu receive it in Urdu.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
