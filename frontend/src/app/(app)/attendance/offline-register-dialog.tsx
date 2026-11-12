"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CloudOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/use-toast";
import { queryKeys } from "@/lib/api/query-keys";
import type {
  AttendanceSessionDetail,
  AttendanceStatus,
  SectionRosterEntry,
} from "@/lib/api/types";
import { fill } from "@/lib/i18n/format";
import { attendanceMessages } from "@/lib/i18n/modules/attendance";
import { offlineMessages } from "@/lib/i18n/modules/offline";
import { useCatalog } from "@/lib/i18n/use-catalog";
import {
  registerId,
  saveOfflineRegister,
  useOutbox,
} from "@/lib/offline/attendance-outbox";
import { formatDate } from "@/lib/utils";
import { STATUS_ORDER, STATUS_STYLE } from "./register-dialog";

export interface OfflineRegisterTarget {
  sectionId: string;
  sectionLabel: string;
  date: string;
  /** The register the board last saw for this section and date, if any. */
  sessionId: string | null;
  /** The board last saw it submitted: read-only here. */
  submitted: boolean;
}

interface Row {
  studentId: string;
  name: string;
  rollNumber: string | null;
  admissionNumber: string;
  /** The status the register started from (server copy, or present). */
  base: AttendanceStatus;
}

/**
 * Take a register with no connection.
 *
 * =============================================================================
 * WHERE THE LIST COMES FROM
 * =============================================================================
 *   1. The register itself, as last seen online — so a register half-marked before
 *      the connection dropped carries on from those marks.
 *   2. Otherwise the section's roster, saved when the board was last opened online,
 *      everyone starting as present (exactly how the server pre-fills a new one).
 *   3. Neither on this device: the dialog says so. Nothing is invented.
 *
 * Only the students the teacher taps are kept (see `attendance-outbox.ts`). "Submit
 * when online" asks the sync to submit after applying them; a register that was
 * already submitted is shown read-only, because changing it is an amendment and
 * amendments need the server's checks.
 */
export function OfflineRegisterDialog({
  target,
  onClose,
}: {
  target: OfflineRegisterTarget | null;
  onClose: () => void;
}) {
  const m = useCatalog(offlineMessages);
  const registerText = useCatalog(attendanceMessages).register;
  const statusLabel = registerText.status;
  const queryClient = useQueryClient();
  const outbox = useOutbox();

  const queued = target ? outbox.find((item) => item.id === registerId(target.sectionId, target.date)) : undefined;
  const [changes, setChanges] = React.useState<Record<string, AttendanceStatus>>({});
  /** Which button is saving, so only that one shows a spinner. */
  const [saving, setSaving] = React.useState<"draft" | "submit" | null>(null);

  // Start from what is already queued for this register, once per opening.
  const openedFor = React.useRef<string | null>(null);
  const key = target ? registerId(target.sectionId, target.date) : null;
  if (key !== openedFor.current) {
    openedFor.current = key;
    setChanges(queued?.changes ?? {});
  }

  const { rows, fromRegister } = React.useMemo((): { rows: Row[] | null; fromRegister: boolean } => {
    if (!target) return { rows: null, fromRegister: false };
    const session = target.sessionId
      ? queryClient.getQueryData<AttendanceSessionDetail>(queryKeys.attendance.session(target.sessionId))
      : undefined;
    if (session) {
      return {
        fromRegister: true,
        rows: session.entries.map((entry) => ({
          studentId: entry.student_id,
          name: entry.full_name,
          rollNumber: entry.roll_number,
          admissionNumber: entry.admission_number,
          base: entry.status,
        })),
      };
    }
    const roster = queryClient.getQueryData<SectionRosterEntry[]>(
      queryKeys.classes.roster(target.sectionId),
    );
    if (roster) {
      return {
        fromRegister: false,
        rows: roster
          .filter((student) => student.status === "active")
          .map((student) => ({
            studentId: student.student_id,
            name: student.full_name,
            rollNumber: student.roll_number,
            admissionNumber: student.admission_number,
            base: "present" as AttendanceStatus,
          })),
      };
    }
    return { rows: null, fromRegister: false };
  }, [target, queryClient]);

  const readOnly = target?.submitted ?? false;
  const statusOf = (row: Row) => changes[row.studentId] ?? row.base;
  const changedCount = rows
    ? rows.filter((row) => changes[row.studentId] && changes[row.studentId] !== row.base).length
    : 0;

  let present = 0;
  let absent = 0;
  for (const row of rows ?? []) {
    const status = statusOf(row);
    if (status === "absent" || status === "excused") absent += 1;
    else present += 1;
  }

  async function save(submit: boolean) {
    if (!target || !rows || saving) return;
    setSaving(submit ? "submit" : "draft");
    try {
      // Only real changes: a tap back to the starting status is no change.
      const kept = Object.fromEntries(
        rows
          .filter((row) => changes[row.studentId] && changes[row.studentId] !== row.base)
          .map((row) => [row.studentId, changes[row.studentId]]),
      );
      await saveOfflineRegister({
        sectionId: target.sectionId,
        sectionLabel: target.sectionLabel,
        date: target.date,
        changes: kept,
        submit,
      }, "replace");
      toast.success(m.toast.savedOffline, m.toast.savedOfflineBody);
      onClose();
    } finally {
      setSaving(null);
    }
  }

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CloudOff className="size-4 text-muted-foreground" aria-hidden />
            {m.register.title}
          </DialogTitle>
          <DialogDescription>
            {target
              ? fill(m.register.description, {
                  section: target.sectionLabel,
                  date: formatDate(target.date),
                })
              : null}
          </DialogDescription>
        </DialogHeader>

        {!rows ? (
          <p className="rounded-md bg-muted/60 p-4 text-sm text-muted-foreground">
            {m.register.notAvailable}
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {readOnly
                ? m.register.submittedReadOnly
                : fromRegister
                  ? m.register.fromSavedRegister
                  : m.register.fromRoster}{" "}
              <span className="font-medium text-foreground">
                {fill(m.register.summary, { present, absent })}
              </span>
            </p>
            <div className="max-h-[50vh] space-y-1 overflow-y-auto pe-1">
              {rows.map((row) => {
                const current = statusOf(row);
                return (
                  <div
                    key={row.studentId}
                    className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {row.rollNumber ? `${row.rollNumber}. ` : ""}
                        {row.name}
                      </p>
                      <p className="text-xs text-muted-foreground">{row.admissionNumber}</p>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      {STATUS_ORDER.map((status) => (
                        <button
                          key={status}
                          type="button"
                          disabled={readOnly}
                          aria-pressed={current === status}
                          aria-label={fill(registerText.markAs, { status: statusLabel[status], name: row.name })}
                          onClick={() =>
                            setChanges((prev) => ({ ...prev, [row.studentId]: status }))
                          }
                          className={[
                            "rounded-control border px-2 py-1 text-xs transition disabled:opacity-50",
                            current === status
                              ? STATUS_STYLE[status]
                              : "bg-background text-muted-foreground hover:bg-muted",
                          ].join(" ")}
                        >
                          {statusLabel[status]}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose}>
            {m.register.close}
          </Button>
          {rows && !readOnly ? (
            <>
              <Button
                variant="outline"
                loading={saving === "draft"}
                disabled={(changedCount === 0 && !queued) || saving !== null}
                onClick={() => void save(false)}
              >
                {m.register.saveDraft}
              </Button>
              <Button
                loading={saving === "submit"}
                disabled={saving !== null}
                onClick={() => void save(true)}
              >
                {m.register.saveAndSubmit}
              </Button>
            </>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
