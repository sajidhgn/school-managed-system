"use client";

import * as React from "react";

import { ErrorState, TableCardSkeleton } from "@/components/data-states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSaveWhatsAppSettings, useWhatsAppSettings } from "@/hooks/use-whatsapp";
import { whatsappMessages } from "@/lib/i18n/modules/whatsapp";
import { useCatalog } from "@/lib/i18n/use-catalog";

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
 *
 * The sample under "What a parent receives" is the server's English wording
 * (`render_absence_alert` in the backend), so it is content and is not translated.
 */
export function AbsenceAlertsPanel({ canManage }: { canManage: boolean }) {
  const m = useCatalog(whatsappMessages).absence;
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
          <CardTitle>{m.title}</CardTitle>
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
              <span className="font-medium">{m.toggle}</span>
              <span className="mt-1 block text-muted-foreground">{m.toggleHint}</span>
            </span>
          </label>
          <ul className="list-disc space-y-1 ps-5 text-muted-foreground">
            <li>{m.ruleRecords}</li>
            <li>{m.ruleOptOut}</li>
            <li>{m.ruleStatuses}</li>
            <li>{m.ruleOnce}</li>
            <li>{m.ruleFailed}</li>
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{m.sampleTitle}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <WhatsAppText
            text={
              "Assalam-o-Alaikum Ayesha.\nAli Khan was marked absent at Main Campus today " +
              "(Tue 28 Oct 2026).\nIf you were not expecting this, please contact the school office."
            }
          />
          <p className="text-xs text-muted-foreground">{m.sampleNote}</p>
        </CardContent>
      </Card>
    </div>
  );
}
